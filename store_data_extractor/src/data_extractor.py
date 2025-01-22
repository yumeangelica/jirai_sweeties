from typing import List, Optional, Any
import random
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import ClientSession
import certifi
import asyncio
import ssl
from charset_normalizer import from_bytes
from store_data_extractor.src.store_database import StoreDatabase
import logging
from store_data_extractor.src.agent_helper import next_user_agent
import re
from store_data_extractor.types import StoreConfigDataType, StoreOptionsDataType, ProductDataType

logger = logging.getLogger("DataExtractor")

db = StoreDatabase()

async def get_page_content(url: str, session: Any, store: StoreOptionsDataType) -> Optional[str]:
    """Fetch the HTML content of a page using a rotating user agent."""
    agent: str = await next_user_agent()
    session.headers.update({'User-Agent': agent})  # Rotate user agent
    logger.info(f"Fetching page {url} with user agent: {agent}")

    context = ssl.create_default_context(cafile=certifi.where())

    try:
        async with session.get(url, ssl=context) as response:
            response.raise_for_status()

            # First try with euc_jp
            try:
                return await response.text(encoding=store.get("encoding", "euc_jp"))
            except Exception as e:
                logger.warning(f"Failed to decode using euc_jp. Attempting automatic encoding detection: {e}")

                # Fallback: read raw bytes and use charset-normalizer
                raw_content = await response.read()
                detected = from_bytes(raw_content).best()
                if detected:
                    logger.info(f"Detected encoding: {detected.encoding}")
                    return detected.output  # type: ignore # Use the decoded string
                else:
                    logger.error("Failed to detect encoding. Returning raw content as UTF-8 with errors ignored.")
                    return raw_content.decode("utf-8", errors="ignore")

    except Exception as e:
        logger.error(f"Error fetching page {url}: {e}")
        return None


async def extract_items_by_config(soup: BeautifulSoup, config: StoreOptionsDataType) -> List[ProductDataType]:
    """Extract product details from the HTML using store-specific configuration."""
    try:
        products = soup.select(config["item_container_selector"])  # Use CSS selector for containers

        items = []

        for product in products:
            archived = False
            if "sold_out_selector" in config:
                sold_out_selector = config["sold_out_selector"]

                # 1 Check if the product container itself matches sold_out_selector
                #    (e.g. product might have style="display:none")
                if product in soup.select(sold_out_selector):
                    # Skip this product because it's marked as sold out at the container level
                    archived = True

                # 2 Otherwise, look for any child element that matches sold_out_selector
                if product.select_one(sold_out_selector):
                    # Skip this product because it has a child indicating sold out
                    archived = True

            # Get the product name
            name_tag = product.select_one(config["item_name_selector"])

            name = name_tag.text.strip() if name_tag else None

            # Get the product URL
            link_tag = product.select_one(config["item_link_selector"])
            link = link_tag.get("href") if link_tag else None

            if isinstance(link, list):
                link = link[0] if link else None

            product_url = f"{config['site_main_url']}{link}" if link and not link.startswith("http") else link

            # Get the product image URL
            image_tag = product.select_one(config["item_image_selector"])
            image_url = image_tag.get("src") if image_tag else None

            # Get the product price(s)
            prices = {}
            for price_config in config.get("item_price_selectors", []):
                price_tag = product.select_one(price_config["selector"])
                if price_tag:
                    price_text = price_tag.text.strip()

                    # Process JPY prices
                    if price_config["currency"] == "JPY":
                        try:
                            match = re.search(r"[\d,]+", price_text)
                            if match:
                                cleaned_price = match.group(0).replace(",", "")
                                prices["JPY"] = float(cleaned_price)
                        except ValueError:
                            logger.error(f"Error parsing JPY price: {price_text}")

                    # Process EUR prices
                    elif price_config["currency"] == "EUR":
                        try:
                            match = re.search(r"[\d.,]+", price_text)
                            if match:
                                cleaned_price = match.group(0).replace(",", "").replace(".", "")
                                prices["EUR"] = float(cleaned_price) / 100  # Convert cents to euros
                        except ValueError:
                            logger.error(f"Error parsing EUR price: {price_text}")

            # Add the item to the list if all required details are present
            if name and product_url and prices:
                items.append({
                    "name": name,
                    "product_url": product_url,
                    "image_url": image_url,
                    "prices": prices,
                    "archived": archived
                })

        return items
    except Exception as e:
        logger.error(f"Error extracting items: {e}")
        return []


async def get_next_page_url_by_config(soup: BeautifulSoup, store: StoreOptionsDataType) -> Optional[str]:
    """Identify the URL of the last 'next' button based on the site configuration."""
    try:
        next_links = soup.select(store["next_page_selector"])

        if not next_links:
            logger.info(f"No next page link found for {store['base_url']}. Stopping pagination.")
            return None

        next_links_filtered = [
            link for link in next_links if store.get("next_page_selector_text", "").lower() in link.text.strip().lower()
        ]

        if not next_links_filtered:

            logger.info(f"No 'Next' link with text '{store.get('next_page_selector_text')}' found in {store['base_url']}. Stopping pagination.")
            return None

        last_next_link = next_links_filtered[-1]  # Select the last matching element
        relative_url = last_next_link.get(store["next_page_attribute"], "")

        # Check if relative_url is a list
        if isinstance(relative_url, list):
            # Combine list elements into a single string or take the first element
            relative_url = relative_url[0] if relative_url else ""

        if not relative_url or not isinstance(relative_url, str):
            logger.info(f"No href attribute found in the last next page link for {store["base_url"]}.")
            return None

        full_url = f"{store['site_main_url']}{relative_url}" if not relative_url.startswith("http") else relative_url
        return full_url

    except Exception as e:
        logger.error(f"Error finding next page for {store['base_url']}: {e}")
        return None


async def process_items(store_name: str, current_items: List[ProductDataType]) -> List[ProductDataType]:
    """Save the items to the database and check for changes."""
    # Update the details of existing products and archive the missing ones
    try:
        new_products: List[ProductDataType] = await db.update_and_archive_products(store_name, current_items)
        if not new_products:
            logger.info(f"No new items found in {store_name}")
            return []

        # Print the new products
        logger.info(f'{len(new_products)} new items added to {store_name}')
        return new_products

    except Exception as e:
        logger.error(f"Error processing items for {store_name}: {e}")
        return []


async def main_program(session: Optional[ClientSession], store: StoreConfigDataType) -> List[ProductDataType]:
    """Main program to fetch and process data for a store."""

    url = store['options']['base_url']
    logger.info(f'Fetching data for {store["name"]} from {url} at {datetime.now()}')

    try:
        logger.info(f"Checking for new items at {store['name']}...")
        current_url = store['options']["base_url"]
        current_items = []
        visited_urls = set()

        # Start data extraction
        while current_url:

            if current_url in visited_urls:
                logger.info(f"URL already visited: {current_url}")
                break

            visited_urls.add(current_url)
            max_retries = 3
            retries = 0
            html = None

            while retries < max_retries:
                html = await get_page_content(current_url, session, store['options'])

                if html:
                    break
                retries += 1
                logger.warning(f"Retry {retries}/{max_retries} for {current_url}")
                await asyncio.sleep(2)

            if not html:
                logger.warning(f"Max retries reached for {current_url}.")
                if current_items:
                    logger.info("Processing collected items before exiting due to retries.")
                    return await process_items(store["name"], current_items)
                else:
                    logger.info("No items collected. Exiting program.")
                    break

            soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

            page_items = await extract_items_by_config(soup, store['options'])

            current_items.extend(page_items)

            # Find the next page URL
            next_url = await get_next_page_url_by_config(soup, store['options'])

            # Check if the next page URL is valid and has not been visited
            if not next_url:
                logger.info(f"Pagination complete for {store['name']}")
                break

            current_url = next_url

            # Delay before the next request, with some randomness
            await asyncio.sleep(store['options'].get("delay_between_requests", 5) + random.uniform(0, 2))

        if current_items:
            # Save the items to the database and check for changes
            return await process_items(store["name"], current_items)
        logger.info(f"No items found for {store['name']}")
        return []
    except Exception as e:
        logger.error(f"Error fetching data for {store['name']}: {e}")
        if current_items:
            logger.info("Processing collected items before exiting due to error.")
            return await process_items(store["name"], current_items)
        return []
