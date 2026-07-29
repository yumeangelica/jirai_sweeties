import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlECode

from store_data_extractor.src.data_extractor import try_get_page_content
from store_data_extractor.src.http_client import (
    HttpClientPool,
    HttpFetchError,
    ResponseTooLarge,
    is_retryable_curl_error,
)


STORE_OPTIONS = {
    "base_url": "https://example.test",
    "site_main_url": "https://example.test",
    "item_container_selector": "//article",
    "item_name_selector": ".//h2/text()",
    "item_price_selectors": [],
    "item_link_selector": ".//a/@href",
    "item_image_selector": ".//img/@src",
    "sold_out_selector": ".sold-out",
    "next_page_selector": "//a[@rel='next']",
    "next_page_selector_text": "Next",
    "next_page_attribute": "href",
    "delay_between_requests": 0,
    "encoding": "utf-8",
    "fetch_backend": "curl_cffi",
}


class FakeStreamResponse:
    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self.chunks = chunks
        self.status_code = status_code

    async def aiter_content(self):
        for chunk in self.chunks:
            yield chunk


class FakeStreamContext:
    def __init__(self, response: FakeStreamResponse) -> None:
        self.response = response
        self.exited = False

    async def __aenter__(self) -> FakeStreamResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exited = True


class FakeCurlSession:
    def __init__(self, chunks: list[bytes]) -> None:
        self.context = FakeStreamContext(FakeStreamResponse(chunks))
        self.closed = False

    def stream(self, method: str, url: str, **kwargs) -> FakeStreamContext:
        return self.context

    async def close(self) -> None:
        self.closed = True


class HttpClientPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_temporary_curl_failures_are_retryable(self) -> None:
        timeout = curl_requests.RequestsError(
            "timed out",
            code=CurlECode.OPERATION_TIMEDOUT,
        )
        malformed_url = curl_requests.RequestsError(
            "malformed URL",
            code=CurlECode.URL_MALFORMAT,
        )

        self.assertTrue(is_retryable_curl_error(timeout))
        self.assertFalse(is_retryable_curl_error(malformed_url))

    async def test_curl_only_pool_does_not_allocate_aiohttp_session(self) -> None:
        pool = HttpClientPool(max_clients=1)

        await pool.start(
            [
                {
                    "name": "test_store",
                    "name_format": "Test Store",
                    "options": STORE_OPTIONS,
                    "schedule": {
                        "minutes": [5],
                        "hours": "*",
                        "days": "*",
                        "months": "*",
                        "years": "*",
                    },
                }
            ]
        )
        self.addAsyncCleanup(pool.close)

        self.assertIsNone(pool._aiohttp_session)

    async def test_limited_fetch_returns_content_below_limit(self) -> None:
        session = FakeCurlSession([b"abc", b"def"])
        pool = HttpClientPool(curl_session=session)
        self.addAsyncCleanup(pool.close)

        content = await pool.fetch_limited_bytes(
            "https://images.example.test/product.jpg",
            max_bytes=6,
        )

        self.assertEqual(content, b"abcdef")
        self.assertTrue(session.context.exited)

    async def test_limited_fetch_aborts_when_chunks_cross_limit(self) -> None:
        session = FakeCurlSession([b"abcd", b"efgh"])
        pool = HttpClientPool(curl_session=session)
        self.addAsyncCleanup(pool.close)

        with self.assertRaises(ResponseTooLarge):
            await pool.fetch_limited_bytes(
                "https://images.example.test/product.jpg",
                max_bytes=6,
            )

        self.assertTrue(session.context.exited)

    async def test_permanent_error_is_not_retried(self) -> None:
        clients = SimpleNamespace(
            fetch_curl_bytes=AsyncMock(
                side_effect=HttpFetchError("not found", retryable=False, status_code=404)
            )
        )

        with patch(
            "store_data_extractor.src.data_extractor.asyncio.sleep",
            new=AsyncMock(),
        ):
            content = await try_get_page_content(
                "https://example.test/missing",
                clients,
                STORE_OPTIONS,
            )

        self.assertIsNone(content)
        self.assertEqual(clients.fetch_curl_bytes.await_count, 1)

    async def test_transient_error_uses_bounded_retries(self) -> None:
        clients = SimpleNamespace(
            fetch_curl_bytes=AsyncMock(
                side_effect=HttpFetchError("server error", retryable=True, status_code=503)
            )
        )

        with patch(
            "store_data_extractor.src.data_extractor.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            content = await try_get_page_content(
                "https://example.test/unavailable",
                clients,
                STORE_OPTIONS,
            )

        self.assertIsNone(content)
        self.assertEqual(clients.fetch_curl_bytes.await_count, 3)
        self.assertEqual(sleep.await_count, 2)


if __name__ == "__main__":
    unittest.main()
