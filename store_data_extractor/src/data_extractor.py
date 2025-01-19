import random
from bs4 import BeautifulSoup
from datetime import datetime
import certifi
import asyncio
import ssl
from store_data_extractor.src.store_database import StoreDatabase
import logging
from store_data_extractor.src.agent_helper import next_user_agent

logger = logging.getLogger("DataExtractor")

db = StoreDatabase()

async def get_page_content(url, session) -> str:
    """Fetch the HTML content of a page using a rotating user agent."""

    agent: str = await next_user_agent()
    session.headers.update({'User-Agent': agent})  # Rotate user agent
    logger.info(f"Fetching page {url} with user agent: {agent}")

    context = ssl.create_default_context(cafile=certifi.where())

    try:
        async with session.get(url, ssl=context) as response:
            response.raise_for_status()
            return await response.text()
    except Exception as e:
        logger.error(f"Error fetching page {url}: {e}")
        return None


async def extract_items_by_config(html, config) -> list:
    """Extract product details from the HTML using store-specific configuration."""
    soup = BeautifulSoup(html, "html.parser")
    products = soup.find_all("div", class_=config["item_container_class"])
    items = []

    for product in products:
        if "sold_out_style" in config and 'style' in product.attrs:
            if config["sold_out_style"] in product.attrs["style"]:
                continue

        name_tag = product.find("span", class_=config["item_name_selector"])  # Extract product name
        link_tag = product.find(config["item_link_selector"]) # Extract product link

        price_container = product.find("span", class_=config["item_price_selector"])  # Extract price container

        # Find the price in EUR
        price_in_eur_tag = price_container.find("span", class_="p_conv") if price_container else None
        price_in_eur = None

        if price_in_eur_tag:
            # Remove all extra characters and take only the price (EUR)
            price_in_eur = price_in_eur_tag.text.strip().split("≈")[-1].strip().split(" ")[0]

        if name_tag and link_tag and price_in_eur:
            name = name_tag.text.strip()
            link = link_tag.get("href")
            full_link = f"{config['base_url']}{link}" if not link.startswith("http") else link

            items.append((name, full_link, price_in_eur))
    return items


async def get_new_items(current_items, previous_items) -> list:
    """Identify and return items that are new."""
    previous_set = set(previous_items)  # Use a set for faster lookups
    new_items = [item for item in current_items if item not in previous_set]
    return new_items


async def get_next_page_url_by_config(soup, config) -> str:
    """Identify the URL of the next page, if it exists."""
    next_link = soup.find("a", string=config["next_page_selector"])
    if next_link:
        relative_url = next_link.get(config["next_page_attribute"], "")
        return f"{config['site_main_url']}{relative_url}" if relative_url else None

    logger.info(f"No next page link found for {config['base_url']}. Stopping pagination.")
    return None

async def process_items(store_name, current_items) -> list:
    """Save the items to the database and check for changes."""

    # Update the details of existing products and archive the missing ones
    new_products = await db.update_and_archive_products(store_name, current_items)

    # Print the new products
    if new_products:
        logger.info(f'{len(new_products)} new items added to {store_name}')
        return new_products
    else:
        logger.info(f"No new items found in {store_name}")


async def main_program(session, store) -> list:
    """Main program to fetch and process data for a store."""

    url = store['options']['base_url']
    logger.info(f'Fetching data for {store["name"]} from {url} at {datetime.now()}')

    try:
        logger.info(f"Checking for new items at {store['name']}...")
        current_url = store['options']["base_url"]
        current_items = []

        # Start data extraction
        while current_url:
            max_retries = 3
            retries = 0

            while retries < max_retries:
                html = await get_page_content(current_url, session)
                if html:
                    break
                retries += 1
                logger.warning(f"Retry {retries}/{max_retries} for {current_url}")
                await asyncio.sleep(2)

            if retries == max_retries:
                logger.warning(f"Max retries reached for {current_url}. Skipping.")
                break

            soup = BeautifulSoup(html, "html.parser")
            page_items = await extract_items_by_config(html, store['options'])

            # Add the current page's items to the total list
            current_items.extend(page_items)

            # Find the next page URL
            current_url = await get_next_page_url_by_config(soup, store['options'])

            # Delay before the next request, with some randomness
            await asyncio.sleep(store['options'].get("delay_between_requests", 5) + random.uniform(0, 2))

        if current_items:
            # Save the items to the database and check for changes
            return await process_items(store["name"], current_items)
        logger.info(f"No items found for {store['name']}")
        return []
    except Exception as e:
        logger.error(f"Error processing store {store['name']}: {e}")
        return
