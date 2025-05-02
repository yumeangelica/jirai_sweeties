from typing import List, Optional, Any, Tuple
import random
from lxml import html
from datetime import datetime
from aiohttp import ClientSession
from charset_normalizer import from_bytes
import certifi
import asyncio
import ssl
import logging
import re
from store_data_extractor.src.store_database import StoreDatabase
from store_data_extractor.src.user_agent_manager import next_user_agent
from store_data_extractor.store_types import StoreConfigDataType, StoreOptionsDataType, ProductDataType, ProductPricesDataType

logger = logging.getLogger("DataExtractor")

db = StoreDatabase()

async def get_page_content(url: str, session: Any, store: StoreOptionsDataType) -> Optional[str]:
    """Fetch the HTML content of a page using a rotating user agent."""
    agent: str = await next_user_agent()
    try:
        session.headers.update({'User-Agent': agent})  # Rotate user agent
        logger.info(f"Fetching page {url} with user agent: {agent}")

        context = ssl.create_default_context(cafile=certifi.where())

        async with session.get(url, ssl=context) as response:
            response.raise_for_status()

            try:
                return await response.text(encoding=store.get("encoding", "utf-8"))
            except Exception as e:
                logger.warning(f"Failed to decode using specified encoding. Attempting automatic encoding detection: {e}")

                raw_content = await response.read()
                detected = from_bytes(raw_content).best()
                if detected:
                    logger.info(f"Detected encoding: {detected.encoding}")
                    return detected.output  # type: ignore
                else:
                    logger.error("Failed to detect encoding. Returning raw content as UTF-8 with errors ignored.")
                    return raw_content.decode("utf-8", errors="ignore")

    except Exception as e:
        logger.error(f"Network error fetching page {url}: {e}")
        return None


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

def parse_product_details(product, config) -> Optional[ProductDataType]:
    """Extract product details from a product element using XPath."""
    try:
        name = product.xpath(config["item_name_selector"])
        name = name[0].text_content().strip() if name else None

        link = product.xpath(config["item_link_selector"])
        link = link[0] if link else None
        product_url = f"{config['site_main_url']}{link}" if link and not link.startswith("http") else link

        image_url = product.xpath(config["item_image_selector"])
        image_url = image_url[0] if image_url else None

        prices: ProductPricesDataType = {}
        for price_config in config.get("item_price_selectors", []):
            price_tag = product.xpath(price_config["selector"])
            if price_tag:
                prices.update(parse_prices(price_tag[0].text_content(), price_config))

        return {
            "name": name,
            "product_url": product_url,
            "image_url": image_url,
            "prices": prices,
            "archived": False
        } if (name and product_url and image_url and prices) else None

    except Exception as e:
        logger.error(f"Error parsing product details: {e}")
        return None

async def extract_items_by_config(tree: html.HtmlElement, config: StoreOptionsDataType) -> List[ProductDataType]:
    """Extract product details from the HTML using store-specific configuration."""
    try:
        products = tree.xpath(config["item_container_selector"])
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
        return bool(product.xpath(sold_out_selector))
    except Exception as e:
        logger.error(f"Invalid sold_out_selector XPath: {e}")
        return False

async def compare_with_database(store_name: str, current_urls: set[str]) -> set[str]:
    """Compare current products with database and return URLs that should be archived."""
    try:
        db_products = await db.get_products(store_name)
        db_urls = {p["product_url"] for p in db_products if not p.get("archived", False)}
        to_archive = db_urls - current_urls
        logger.info(f"Found {len(to_archive)} products to archive")
        return to_archive
    except Exception as e:
        logger.error(f"Error comparing products with database: {e}")
        return set()

async def process_items(store_name: str, current_items: List[ProductDataType]) -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Save the items to the database and check for changes."""
    try:
        result = await db.sync_store_products(store_name, current_items)
        new_products: List[ProductDataType]
        updated_products: List[ProductDataType]
        new_products, updated_products = result
        return new_products, updated_products
    except Exception as e:
        logger.error(f"Error processing items for {store_name}: {e}")
        return [], []

async def process_batch(store_name: str, items: List[ProductDataType], context: str = "") -> Tuple[List[ProductDataType], List[ProductDataType]]:
    """Process a batch of items with error handling."""
    if not items:
        return [], []
    try:
        result = await process_items(store_name, items)
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
        next_links = tree.xpath(store["next_page_selector"])
        if not next_links:
            logger.info(f"No next page link found for {store['base_url']}. Stopping pagination.")
            return None
        next_url = next_links[-1]  # Skip the last link
        full_url = f"{store['site_main_url']}{next_url}" if not next_url.startswith("http") else next_url

        return full_url
    except Exception as e:
        logger.error(f"Error finding next page for {store['base_url']}: {e}")
        return None

async def main_program(session: Optional[ClientSession], store: StoreConfigDataType) -> Tuple[List[ProductDataType], List[ProductDataType]]:
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
                body = tree.find("body")

                if body is None:
                    logger.error("No <body> element found in the HTML.")
                    success = False
                    break

                # Process items from this page
                page_items = await extract_items_by_config(body, store['options'])

                if page_items:
                    # Update products for this page immediately
                    result = await process_batch(store["name"], page_items, "from current page")
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
            to_archive = await compare_with_database(store["name"], all_product_urls)
            if to_archive:
                await db.mark_products_as_archived(store["name"], list(to_archive))
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
            logger.info(f"Returning {len(all_new_products)} new products for {store['name']} (including any found before errors)")
        if all_updated_products:
            logger.info(f"Returning {len(all_updated_products)} updated products for {store['name']} (including any found before errors)")
        return all_new_products, all_updated_products