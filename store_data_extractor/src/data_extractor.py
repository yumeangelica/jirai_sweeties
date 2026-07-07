from typing import List, Optional, Any, Tuple
import random
from lxml import html
from lxml.etree import XPathError
from datetime import datetime
from aiohttp import ClientResponseError, ClientSession
from charset_normalizer import from_bytes
from curl_cffi import requests as curl_requests
from urllib.parse import urljoin
import certifi
import asyncio
import ssl
import logging
import re
from store_data_extractor.src.store_database import StoreDatabase
from store_data_extractor.src.user_agent_manager import next_user_agent
from store_data_extractor.store_types import StoreConfigDataType, StoreOptionsDataType, ProductDataType, ProductPricesDataType

logger = logging.getLogger("DataExtractor")

async def get_page_content(url: str, session: Any, store: StoreOptionsDataType) -> Optional[str]:
    """Fetch the HTML content of a page using a rotating user agent."""
    agent: str = await next_user_agent()
    logger.info(f"Fetching page {url} with user agent: {agent}")

    headers = build_request_headers(agent, store)
    fetch_backend = store.get("fetch_backend", "auto")

    if fetch_backend in ("auto", "aiohttp"):
        content = await get_page_content_with_aiohttp(url, session, store, headers)
        if content or fetch_backend == "aiohttp":
            return content

    if fetch_backend in ("auto", "curl_cffi"):
        return await get_page_content_with_curl_cffi(url, store, headers)

    logger.error(f"Unsupported fetch_backend '{fetch_backend}' for {url}")
    return None

async def get_page_content_with_aiohttp(
    url: str,
    session: Any,
    store: StoreOptionsDataType,
    headers: dict[str, str],
) -> Optional[str]:
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        proxy_url = store.get("proxy_url")

        async with session.get(url, headers=headers, proxy=proxy_url, ssl=context) as response:
            response.raise_for_status()
            return decode_page_content(await response.read(), store)
    except ClientResponseError as e:
        logger.warning(f"aiohttp fetch failed for {url}: {e.status}, message='{e.message}'")
    except Exception as e:
        logger.warning(f"aiohttp fetch failed for {url}: {e}")

    return None

async def get_page_content_with_curl_cffi(
    url: str,
    store: StoreOptionsDataType,
    headers: dict[str, str],
) -> Optional[str]:
    try:
        return await asyncio.to_thread(fetch_page_with_curl_cffi, url, store, headers)
    except Exception as e:
        logger.error(f"curl_cffi fetch failed for {url}: {e}")
        return None

def fetch_page_with_curl_cffi(url: str, store: StoreOptionsDataType, headers: dict[str, str]) -> Optional[str]:
    response = curl_requests.get(
        url,
        headers=headers,
        impersonate=store.get("curl_impersonate", "chrome"),
        proxy=store.get("proxy_url"),
        timeout=store.get("request_timeout", 30),
    )

    if response.status_code >= 400:
        logger.error(f"curl_cffi fetch failed for {url}: HTTP {response.status_code}")
        return None

    return decode_page_content(response.content, store)

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


async def try_get_page_content(url: str, session: Any, store: StoreOptionsDataType, max_retries: int = 3) -> Optional[str]:
    """Try to get page content with retries."""
    for attempt in range(max_retries):
        try:
            content = await get_page_content(url, session, store)
            if content:
                return content
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to get content from {url}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed with error: {e}")

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

async def extract_items_by_config(tree: html.HtmlElement, config: StoreOptionsDataType) -> List[ProductDataType]:
    """Extract product details from the HTML using store-specific configuration."""
    try:
        products = select_values(tree, config["item_container_selector"])
        current_items: List[ProductDataType] = []

        for product in products:
            product_details = parse_product_details(product, config)
            if product_details:
                sold_out = check_sold_out(product, config["sold_out_selector"]) if "sold_out_selector" in config else False
                product_details["archived"] = sold_out
                current_items.append(product_details)

        return current_items
    except Exception as e:
        logger.error(f"Error extracting items: {e}")
        return []

def check_sold_out(product, sold_out_selector) -> bool:
    """Check if a product is sold out."""
    try:
        return bool(select_values(product, sold_out_selector))
    except Exception as e:
        logger.error(f"Invalid sold_out_selector: {e}")
        return False

async def compare_with_database(database: StoreDatabase, store_name: str, current_urls: set[str]) -> set[str]:
    """Compare current products with database and return URLs that should be archived."""
    try:
        db_products = await database.get_products(store_name)
        db_urls = {p["product_url"] for p in db_products if not p.get("archived", False)}
        to_archive = db_urls - current_urls # URLs in DB but not in current URLs
        logger.info(f"Found {len(to_archive)} products to archive")
        return to_archive
    except Exception as e:
        logger.error(f"Error comparing products with database: {e}")
        return set()

async def process_items(database: StoreDatabase, store_name: str, current_items: List[ProductDataType]) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Save the items to the database and check for changes."""
    try:
        result = await database.sync_store_products(store_name, current_items)
        new_products: List[ProductDataType]
        updated_products: List[ProductDataType]
        new_products, updated_products = result
        return new_products, updated_products
    except Exception as e:
        logger.error(f"Error processing items for {store_name}: {e}")
        return [], []

async def process_batch(database: StoreDatabase, store_name: str, items: List[ProductDataType], context: str = "") -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Process a batch of items with error handling."""
    if not items:
        return [], []
    try:
        result = await process_items(database, store_name, items)
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
    try:
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
        full_url = urljoin(store["site_main_url"], next_url)

        return full_url
    except Exception as e:
        logger.error(f"Error finding next page for {store['base_url']}: {e}")
        return None

async def main_program(session: Optional[ClientSession], store: StoreConfigDataType, database: StoreDatabase) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Main program to fetch and process data for a store."""
    url = store['options']['base_url']
    logger.info(f'Fetching data for {store["name"]} from {url} at {datetime.now()}')

    all_product_urls: set[str] = set()
    all_new_products: List[ProductDataType] = []
    all_updated_products: List[ProductDataType] = []
    visited_urls = set()

    try:
        current_url = store['options']["base_url"]
        success = True

        # Phase 1: Process each page immediately and collect URLs
        while current_url:
            try:
                if current_url in visited_urls:
                    logger.info(f"URL already visited: {current_url}")
                    break

                visited_urls.add(current_url)
                html_content = await try_get_page_content(current_url, session, store=store['options'])
                if not html_content:
                    logger.error(f"Failed to get content from {current_url} after 3 attempts")
                    success = False
                    break

                tree = html.fromstring(html_content)
                body = get_body_element(tree)

                # Process items from this page
                page_items = await extract_items_by_config(body, store['options'])

                if page_items:
                    # Update products for this page immediately
                    result = await process_batch(database, store["name"], page_items, "from current page")
                    new_products, updated_products = result
                    if new_products:
                        all_new_products.extend(new_products)
                    if updated_products:
                        all_updated_products.extend(updated_products)

                    # Collect URLs for final comparison
                    page_urls = {item["product_url"] for item in page_items}
                    all_product_urls.update(page_urls)

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

        # Phase 2: Final check - only if all pages were processed successfully
        if success and all_product_urls:
            logger.info(f"All pages processed. Found total of {len(all_product_urls)} products.")
            logger.info("Checking for products to archive...")

            # Compare with database and archive missing products
            to_archive = await compare_with_database(database, store["name"], all_product_urls)
            if to_archive:
                await database.mark_products_as_archived(store["name"], list(to_archive))
                logger.info(f"Marked {len(to_archive)} products as archived in final check")

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
