from pathlib import Path
import asyncio
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import store_data_extractor.src.store_database as store_database_module  # noqa: E402


def make_product(index: int) -> dict:
    return {
        "name": f"Product {index}",
        "product_url": f"https://example.com/product-{index}",
        "image_url": f"https://example.com/image-{index}.jpg",
        "prices": {"JPY": 1000.0 + index},
        "archived": False,
    }


async def run_smoke() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store_database_module.SQLITE_STORE_DB_FILE = str(Path(tmp_dir) / "store_db.sqlite")
        db = store_database_module.StoreDatabase()

        try:
            # First sync for a fresh store: nothing may be reported or left unsent
            initial_items = [make_product(i) for i in range(5)]
            new_products, updated_products = await db.sync_store_products("smoke_store", initial_items)
            assert new_products == [], f"First sync must not report new products, got {len(new_products)}"
            assert updated_products == [], f"First sync must not report updated products, got {len(updated_products)}"

            unsent = await db.get_unsent_products()
            assert unsent == [], f"First sync must insert products as sent, got {len(unsent)} unsent"

            sent_flags = db.cursor.execute("SELECT COUNT(*) FROM Product WHERE is_sent = 0").fetchone()[0]
            assert sent_flags == 0, f"Expected 0 rows with is_sent=0 after initial fetch, got {sent_flags}"

            # Second sync with one added product: it is reported and unsent until posted
            second_items = initial_items + [make_product(99)]
            new_products, updated_products = await db.sync_store_products("smoke_store", second_items)
            assert len(new_products) == 1, f"Expected 1 new product on second sync, got {len(new_products)}"
            assert new_products[0]["name"] == "Product 99"

            unsent = await db.get_unsent_products("smoke_store")
            assert len(unsent) == 1, f"Expected 1 unsent product, got {len(unsent)}"

            # Per-store filtering: another store's initial fetch stays invisible and sent
            await db.sync_store_products("other_store", [make_product(500)])
            unsent = await db.get_unsent_products("smoke_store")
            assert len(unsent) == 1, f"Per-store unsent filter leaked, got {len(unsent)}"

            # Marking as sent clears the unsent queue
            await db.mark_product_as_sent(int(unsent[0]["id"]))
            unsent = await db.get_unsent_products()
            assert unsent == [], f"Expected no unsent products after marking sent, got {len(unsent)}"

            print("first run smoke passed: initial fetch fills the database without queuing posts")
        finally:
            await db.close_connection()


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
