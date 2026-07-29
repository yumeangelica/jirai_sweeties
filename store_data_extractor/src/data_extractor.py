from typing import List, Optional, Any, Tuple
import random
from lxml import html
from lxml.etree import XPathError
from datetime import datetime
from charset_normalizer import from_bytes
from urllib.parse import urljoin
import asyncio
import logging
import re
from store_data_extractor.src.store_database import StoreDatabase
from store_data_extractor.src.http_client import HttpClientPool, HttpFetchError
from store_data_extractor.src.user_agent_manager import next_user_agent
from store_data_extractor.store_types import StoreConfigDataType, StoreOptionsDataType, ProductDataType, ProductPricesDataType

logger = logging.getLogger("DataExtractor")

async def get_page_content(url: str, clients: HttpClientPool, store: StoreOptionsDataType) -> str:
    """Fetch the HTML content of a page using a rotating user agent."""
    agent: str = await next_user_agent()
    logger.info(f"Fetching page {url}")
    logger.debug(f"Using user agent: {agent}")

    headers = build_request_headers(agent, store)
    fetch_backend = store.get("fetch_backend", "auto")

    if fetch_backend in ("auto", "aiohttp"):
        try:
            return await get_page_content_with_aiohttp(url, clients, store, headers)
        except HttpFetchError as error:
            if fetch_backend == "aiohttp":
                raise
            if error.status_code is not None and error.status_code != 403:
                raise
            logger.warning(f"{error}; falling back to curl_cffi")

    if fetch_backend in ("auto", "curl_cffi"):
        return await get_page_content_with_curl_cffi(url, clients, store, headers)

    raise HttpFetchError(
        message=f"Unsupported fetch_backend '{fetch_backend}' for {url}",
        retryable=False,
    )

async def get_page_content_with_aiohttp(
    url: str,
    clients: HttpClientPool,
    store: StoreOptionsDataType,
    headers: dict[str, str],
) -> str:
    return decode_page_content(await clients.fetch_aiohttp_bytes(url, store, headers), store)

async def get_page_content_with_curl_cffi(
    url: str,
    clients: HttpClientPool,
    store: StoreOptionsDataType,
    headers: dict[str, str],
) -> str:
    return decode_page_content(await clients.fetch_curl_bytes(url, store, headers), store)

def decode_page_content(raw_content: bytes, store: StoreOptionsDataType) -> str:
    encoding = store.get("encoding", "utf-8")

    try:
        return raw_content.decode(encoding)
    except Exception as e:
        logger.warning(f"Failed to decode using specified encoding. Attempting automatic encoding detection: {e}")

    detected = from_bytes(raw_content).best()
    if detected:
        logger.info(f"Detected encoding: {detected.encoding}")
        return str(detected)

    logger.error("Failed to detect encoding. Returning raw content as UTF-8 with errors ignored.")
    return raw_content.decode("utf-8", errors="ignore")

def build_request_headers(agent: str, store: StoreOptionsDataType) -> dict[str, str]:
    headers = {
        "User-Agent": agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    headers.update(store.get("request_headers", {}))
    return headers


async def try_get_page_content(
    url: str,
    clients: HttpClientPool,
    store: StoreOptionsDataType,
    max_retries: int = 3,
) -> Optional[str]:
    """Try to get page content with retries."""
    for attempt in range(max_retries):
        try:
            return await get_page_content(url, clients, store)
        except HttpFetchError as error:
            logger.warning(
                f"Attempt {attempt + 1}/{max_retries} failed to get content from {url}: {error}"
            )
            if not error.retryable:
                return None

        if attempt < max_retries - 1:
            await asyncio.sleep(5)  # Wait before retrying

    return None

def parse_prices(price_text: str, price_config) -> ProductPricesDataType:
    """Parse price information from the price string."""
    prices: ProductPricesDataType = {}
    try:
        price_text = price_text.strip()
        if price_config["currency"] == "JPY":
            match = re.search(r"[\d,]+", price_text)
            if match:
                cleaned_price = match.group(0).replace(",", "")
                prices["JPY"] = float(cleaned_price)
        elif price_config["currency"] == "EUR":
            match = re.search(r"[\d.,]+", price_text)
            if match:
                cleaned_price = match.group(0).replace(",", "").replace(".", "")
                prices["EUR"] = float(cleaned_price) / 100
    except Exception as e:
        logger.error(f"Error parsing price: {e}")

    return prices

def select_values(node: Any, selector: str) -> List[Any]:
    """Evaluate a selector as XPath by default, with CSS support for store configs."""
    selector = selector.strip()
    if not selector:
        return []

    if selector.startswith("xpath:"):
        return list(node.xpath(selector.removeprefix("xpath:").strip()))

    if selector.startswith("css:"):
        return list(node.cssselect(selector.removeprefix("css:").strip()))

    try:
        return list(node.xpath(selector))
    except XPathError:
        return list(node.cssselect(selector))

def format_selector_value(value: Any, attribute: Optional[str] = None) -> Optional[str]:
    if isinstance(value, str):
        return value.strip() or None

    if isinstance(value, bytes):
        decoded_value = value.decode("utf-8", errors="ignore").strip()
        return decoded_value or None

    if attribute and hasattr(value, "get"):
        attribute_value = value.get(attribute)
        if attribute_value:
            return str(attribute_value).strip() or None

    if hasattr(value, "text_content"):
        text_value = value.text_content().strip()
        return text_value or None

    string_value = str(value).strip()
    return string_value or None

def get_selector_value(node: Any, selector: str, attribute: Optional[str] = None) -> Optional[str]:
    """Return the first selector result as text or an attribute value."""
    values = select_values(node, selector)
    if not values:
        return None

    return format_selector_value(values[0], attribute)

def get_body_element(tree: html.HtmlElement) -> html.HtmlElement:
    if getattr(tree, "tag", "").lower() == "body":
        return tree

    body = tree.find("body")
    if body is not None:
        return body

    body_matches = tree.xpath("//body")
    return body_matches[0] if body_matches else tree

def parse_product_details(product, config) -> Optional[ProductDataType]:
    """Extract product details from a product element using XPath."""
    try:
        name = get_selector_value(product, config["item_name_selector"])

        link = get_selector_value(product, config["item_link_selector"], "href")
        product_url = urljoin(config["site_main_url"], link) if link else None

        image_url = get_selector_value(product, config["item_image_selector"], "src")

        prices: ProductPricesDataType = {}
        for price_config in config.get("item_price_selectors", []):
            price_text = get_selector_value(product, price_config["selector"])
            if price_text:
                prices.update(parse_prices(price_text, price_config))

        return {
            "name": name,
            "product_url": product_url,
            "image_url": image_url,
            "prices": prices,
            "archived": False
        } if (name and product_url and image_url and prices) else None # Image_url is identifier but all of there are required

    except Exception as e:
        logger.error(f"Error parsing product details: {e}")
        return None

async def extract_items_with_status(
    tree: html.HtmlElement,
    config: StoreOptionsDataType,
) -> Tuple[List[ProductDataType], bool]:
    """Extract products and report whether every matched card parsed successfully."""
    try:
        products = select_values(tree, config["item_container_selector"])
        current_items: List[ProductDataType] = []
        parse_complete = True

        for product in products:
            product_details = parse_product_details(product, config)
            if product_details:
                sold_out = check_sold_out(product, config["sold_out_selector"]) if "sold_out_selector" in config else False
                product_details["archived"] = sold_out
                current_items.append(product_details)
            else:
                parse_complete = False

        return current_items, parse_complete
    except Exception as e:
        logger.error(f"Error extracting items: {e}")
        return [], False


async def extract_items_by_config(tree: html.HtmlElement, config: StoreOptionsDataType) -> List[ProductDataType]:
    """Extract product details from the HTML using store-specific configuration."""
    current_items, _ = await extract_items_with_status(tree, config)
    return current_items

def check_sold_out(product, sold_out_selector) -> bool:
    """Check if a product is sold out."""
    try:
        return bool(select_values(product, sold_out_selector))
    except Exception as e:
        logger.error(f"Invalid sold_out_selector: {e}")
        return False

async def process_items(
    database: StoreDatabase,
    store_name: str,
    current_items: List[ProductDataType],
    *,
    crawl_complete: bool = True,
) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Save the items to the database and check for changes."""
    try:
        result = await database.sync_store_products(
            store_name,
            current_items,
            crawl_complete=crawl_complete,
        )
        new_products: List[ProductDataType]
        updated_products: List[ProductDataType]
        new_products, updated_products = result
        return new_products, updated_products
    except Exception as e:
        logger.error(f"Error processing items for {store_name}: {e}")
        return [], []

async def process_batch(
    database: StoreDatabase,
    store_name: str,
    items: List[ProductDataType],
    context: str = "",
    *,
    crawl_complete: bool = True,
) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Process a batch of items with error handling."""
    if not items:
        return [], []
    try:
        result = await process_items(
            database,
            store_name,
            items,
            crawl_complete=crawl_complete,
        )
        new_products, updated_products = result
        if new_products:
            logger.info(f"Found {len(new_products)} new items{' ' + context if context else ''}")
        if updated_products:
            logger.info(f"Updated {len(updated_products)} items{' ' + context if context else ''}")
        return new_products, updated_products
    except Exception as e:
        logger.error(f"Error processing batch{' ' + context if context else ''}: {e}")
        return [], []

async def get_next_page_url_by_config(tree: html.HtmlElement, store: StoreOptionsDataType) -> Optional[str]:
    """Identify the URL of the last 'Next' button based on the site configuration."""
    next_links = select_values(tree, store["next_page_selector"])
    if not next_links:
        logger.info(f"No next page link found for {store['base_url']}. Stopping pagination.")
        return None

    next_page_text = store.get("next_page_selector_text")
    if next_page_text:
        text_matches = [
            next_link
            for next_link in next_links
            if next_page_text in (format_selector_value(next_link) or "")
        ]
        if text_matches:
            next_links = text_matches

    next_url = format_selector_value(next_links[-1], store.get("next_page_attribute", "href"))
    if not next_url:
        logger.info(f"No next page URL found for {store['base_url']}. Stopping pagination.")
        return None
    return urljoin(store["site_main_url"], next_url)

async def main_program(
    clients: HttpClientPool,
    store: StoreConfigDataType,
    database: StoreDatabase,
) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Main program to fetch and process data for a store."""
    url = store['options']['base_url']
    logger.info(f'Fetching data for {store["name"]} from {url} at {datetime.now()}')

    all_product_urls: set[str] = set()
    all_items: List[ProductDataType] = []
    all_new_products: List[ProductDataType] = []
    all_updated_products: List[ProductDataType] = []
    visited_urls = set()

    try:
        current_url = store['options']["base_url"]
        success = True

        # Fetch and parse every reachable page before one database sync.
        while current_url:
            try:
                if current_url in visited_urls:
                    logger.warning(
                        f"Pagination cycle detected at {current_url}; "
                        "treating the crawl as incomplete."
                    )
                    success = False
                    break

                visited_urls.add(current_url)
                html_content = await try_get_page_content(current_url, clients, store=store['options'])
                if not html_content:
                    logger.error(f"Failed to get content from {current_url} after 3 attempts")
                    success = False
                    break

                tree = html.fromstring(html_content)
                body = get_body_element(tree)

                page_items, page_parse_complete = await extract_items_with_status(
                    body,
                    store['options'],
                )

                if not page_items:
                    logger.warning(
                        f"No valid products parsed from {current_url}; "
                        "treating the crawl as incomplete."
                    )
                    success = False
                    break

                all_items.extend(page_items)
                page_urls = {item["product_url"] for item in page_items}
                all_product_urls.update(page_urls)

                if not page_parse_complete:
                    logger.warning(
                        f"Some product cards from {current_url} could not be parsed; "
                        "the crawl will remain incomplete."
                    )
                    success = False

                next_url = await get_next_page_url_by_config(body, store['options'])
                if not next_url:
                    break

                current_url = next_url
                await asyncio.sleep(store['options'].get("delay_between_requests", 5) + random.uniform(0, 2))

            except asyncio.CancelledError:
                logger.warning("Task cancelled during page fetching...")
                success = False
                raise
            except Exception as e:
                logger.error(f"Error processing page {current_url}: {e}")
                success = False
                break

        crawl_complete = success and bool(all_product_urls)
        if all_items:
            result = await process_batch(
                database,
                store["name"],
                all_items,
                "from current crawl",
                crawl_complete=crawl_complete,
            )
            all_new_products, all_updated_products = result

        if crawl_complete:
            logger.info(f"All pages processed. Found total of {len(all_product_urls)} products.")

    except Exception as e:
        logger.error(f"Critical error in main_program for {store['name']}: {e}")

    finally:
        # Always return any new products we found, even if there were errors
        if not all_new_products:
            logger.info(f"No new products found for {store['name']}")
        if not all_updated_products:
            logger.info(f"No updated products found for {store['name']}")
        if all_new_products:
            logger.info(f"Returning {len(all_new_products)} new products (including any found before errors)")
        if all_updated_products:
            logger.info(f"Returning {len(all_updated_products)} updated products (including any found before errors)")

    return all_new_products, all_updated_products
