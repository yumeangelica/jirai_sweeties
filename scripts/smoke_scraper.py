from pathlib import Path
import argparse
import asyncio
import json
import sys

import aiohttp
from lxml import html


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from store_data_extractor.src.data_extractor import (  # noqa: E402
    extract_items_by_config,
    get_body_element,
    get_page_content,
)


STORES_CONFIG_PATH = PROJECT_ROOT / "store_data_extractor" / "config" / "stores.json"


def load_store(store_name: str | None) -> dict:
    stores = json.loads(STORES_CONFIG_PATH.read_text())
    if not stores:
        raise RuntimeError(f"No stores configured in {STORES_CONFIG_PATH}")

    if store_name is None:
        return stores[0]

    for store in stores:
        if store.get("name") == store_name:
            return store

    raise RuntimeError(f"Store '{store_name}' not found in {STORES_CONFIG_PATH}")


async def run_smoke(store_name: str | None) -> None:
    store = load_store(store_name)
    options = store["options"]

    async with aiohttp.ClientSession() as session:
        content = await get_page_content(options["base_url"], session, options)

    if not content:
        raise RuntimeError(f"No content fetched for {store['name']}")

    body = get_body_element(html.fromstring(content))
    items = await extract_items_by_config(body, options)
    if not items:
        raise RuntimeError(f"No items parsed for {store['name']}")

    missing_required_fields = [
        item
        for item in items
        if (
            not item.get("name")
            or not item.get("product_url")
            or not item.get("image_url")
            or not item.get("prices")
        )
    ]
    if missing_required_fields:
        raise RuntimeError(f"{len(missing_required_fields)} items are missing required fields")

    print(f"scraper smoke passed for {store['name']}: parsed {len(items)} items")
    print(items[0]["name"])
    print(items[0]["image_url"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live scraper smoke test without DB writes.")
    parser.add_argument("--store", help="Store name from stores.json. Defaults to the first store.")
    args = parser.parse_args()

    asyncio.run(run_smoke(args.store))


if __name__ == "__main__":
    main()
