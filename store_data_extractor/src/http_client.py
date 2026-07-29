import asyncio
import logging
import ssl
from dataclasses import dataclass
from typing import Iterable, Optional

import aiohttp
import certifi
from curl_cffi import CurlOpt
from curl_cffi.const import CurlECode
from curl_cffi import requests as curl_requests

from store_data_extractor.store_types import StoreConfigDataType, StoreOptionsDataType


TRANSIENT_STATUS_CODES = {408, 425, 429}
TRANSIENT_CURL_CODES = {
    CurlECode.COULDNT_RESOLVE_PROXY,
    CurlECode.COULDNT_RESOLVE_HOST,
    CurlECode.COULDNT_CONNECT,
    CurlECode.HTTP2,
    CurlECode.PARTIAL_FILE,
    CurlECode.OPERATION_TIMEDOUT,
    CurlECode.SSL_CONNECT_ERROR,
    CurlECode.GOT_NOTHING,
    CurlECode.SEND_ERROR,
    CurlECode.RECV_ERROR,
    CurlECode.AGAIN,
    CurlECode.NO_CONNECTION_AVAILABLE,
    CurlECode.HTTP2_STREAM,
    CurlECode.HTTP3,
    CurlECode.QUIC_CONNECT_ERROR,
}


@dataclass(frozen=True)
class HttpFetchError(Exception):
    message: str
    retryable: bool
    status_code: Optional[int] = None

    def __str__(self) -> str:
        return self.message


class ResponseTooLarge(HttpFetchError):
    def __init__(self, url: str, max_bytes: int) -> None:
        super().__init__(
            message=f"Response from {url} exceeded {max_bytes} bytes",
            retryable=False,
        )


def is_retryable_status(status_code: int) -> bool:
    return status_code in TRANSIENT_STATUS_CODES or status_code >= 500


def is_retryable_curl_error(error: curl_requests.RequestsError) -> bool:
    """Return whether a curl transport failure is plausibly temporary."""
    return error.code in TRANSIENT_CURL_CODES


class HttpClientPool:
    """Own and reuse scraper HTTP sessions for the application lifetime."""

    def __init__(
        self,
        *,
        max_clients: int = 3,
        curl_session=None,
        aiohttp_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.logger = logging.getLogger("HttpClientPool")
        self.max_clients = max_clients
        self._curl_session = curl_session
        self._aiohttp_session = aiohttp_session
        self._started = curl_session is not None or aiohttp_session is not None
        self._closed = False

    async def start(self, stores: Iterable[StoreConfigDataType]) -> None:
        if self._closed:
            raise RuntimeError("HTTP client pool has already been closed")

        if self._curl_session is None:
            self._curl_session = curl_requests.AsyncSession(max_clients=self.max_clients)

        needs_aiohttp = any(
            store["options"].get("fetch_backend", "auto") in ("auto", "aiohttp")
            for store in stores
        )
        if needs_aiohttp and self._aiohttp_session is None:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context, limit=self.max_clients)
            self._aiohttp_session = aiohttp.ClientSession(connector=connector)

        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._aiohttp_session is not None and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()
        self._aiohttp_session = None

        if self._curl_session is not None:
            await self._curl_session.close()
        self._curl_session = None

    def _require_curl_session(self):
        if not self._started or self._curl_session is None:
            raise RuntimeError("HTTP client pool has not been started")
        return self._curl_session

    def _require_aiohttp_session(self) -> aiohttp.ClientSession:
        if not self._started or self._aiohttp_session is None:
            raise RuntimeError("aiohttp session is not available for this configuration")
        return self._aiohttp_session

    async def fetch_curl_bytes(
        self,
        url: str,
        store: StoreOptionsDataType,
        headers: dict[str, str],
    ) -> bytes:
        session = self._require_curl_session()
        try:
            response = await session.get(
                url,
                headers=headers,
                impersonate=store.get("curl_impersonate", "chrome"),
                proxy=store.get("proxy_url"),
                timeout=store.get("request_timeout", 30),
            )
        except curl_requests.RequestsError as error:
            raise HttpFetchError(
                message=f"curl_cffi fetch failed for {url}: {error}",
                retryable=is_retryable_curl_error(error),
            ) from error
        except (asyncio.TimeoutError, OSError) as error:
            raise HttpFetchError(
                message=f"curl_cffi fetch failed for {url}: {error}",
                retryable=True,
            ) from error
        except Exception as error:
            raise HttpFetchError(
                message=f"curl_cffi fetch failed for {url}: {error}",
                retryable=False,
            ) from error

        if response.status_code >= 400:
            raise HttpFetchError(
                message=f"curl_cffi fetch failed for {url}: HTTP {response.status_code}",
                retryable=is_retryable_status(response.status_code),
                status_code=response.status_code,
            )
        if not response.content:
            raise HttpFetchError(
                message=f"curl_cffi fetch returned empty content for {url}",
                retryable=True,
                status_code=response.status_code,
            )
        return bytes(response.content)

    async def fetch_aiohttp_bytes(
        self,
        url: str,
        store: StoreOptionsDataType,
        headers: dict[str, str],
    ) -> bytes:
        session = self._require_aiohttp_session()
        timeout = aiohttp.ClientTimeout(total=store.get("request_timeout", 30))
        try:
            async with session.get(
                url,
                headers=headers,
                proxy=store.get("proxy_url"),
                timeout=timeout,
            ) as response:
                raw_content = await response.read()
                if response.status >= 400:
                    raise HttpFetchError(
                        message=f"aiohttp fetch failed for {url}: HTTP {response.status}",
                        retryable=is_retryable_status(response.status),
                        status_code=response.status,
                    )
                if not raw_content:
                    raise HttpFetchError(
                        message=f"aiohttp fetch returned empty content for {url}",
                        retryable=True,
                        status_code=response.status,
                    )
                return raw_content
        except HttpFetchError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            raise HttpFetchError(
                message=f"aiohttp fetch failed for {url}: {error}",
                retryable=True,
            ) from error

    async def fetch_limited_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout: float = 20,
        impersonate: str = "chrome",
    ) -> bytes:
        session = self._require_curl_session()
        try:
            async with session.stream(
                "GET",
                url,
                impersonate=impersonate,
                timeout=timeout,
                curl_options={CurlOpt.MAXFILESIZE_LARGE: max_bytes},
            ) as response:
                if response.status_code >= 400:
                    raise HttpFetchError(
                        message=f"Image fetch failed for {url}: HTTP {response.status_code}",
                        retryable=is_retryable_status(response.status_code),
                        status_code=response.status_code,
                    )

                content = bytearray()
                async for chunk in response.aiter_content():
                    if len(content) + len(chunk) > max_bytes:
                        raise ResponseTooLarge(url, max_bytes)
                    content.extend(chunk)

                if not content:
                    raise HttpFetchError(
                        message=f"Image fetch returned empty content for {url}",
                        retryable=True,
                        status_code=response.status_code,
                    )
                return bytes(content)
        except HttpFetchError:
            raise
        except curl_requests.RequestsError as error:
            if error.code == CurlECode.FILESIZE_EXCEEDED:
                raise ResponseTooLarge(url, max_bytes) from error
            raise HttpFetchError(
                message=f"Image fetch failed for {url}: {error}",
                retryable=is_retryable_curl_error(error),
            ) from error
        except (asyncio.TimeoutError, OSError) as error:
            raise HttpFetchError(
                message=f"Image fetch failed for {url}: {error}",
                retryable=True,
            ) from error
        except Exception as error:
            raise HttpFetchError(
                message=f"Image fetch failed for {url}: {error}",
                retryable=False,
            ) from error
