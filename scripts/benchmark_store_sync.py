"""Offline benchmark for the SQLite store synchronization hot path."""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import store_data_extractor.src.store_database as store_database_module


PRODUCT_COUNT = 353


def make_products() -> list[dict]:
    return [
        {
            "name": f"Product {index}",
            "product_url": f"https://example.test/product-{index}",
            "image_url": f"https://images.example.test/product-{index}.jpg",
            "prices": {"JPY": float(1000 + index)},
            "archived": False,
        }
        for index in range(PRODUCT_COUNT)
    ]


async def run_benchmark() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store_database_module.SQLITE_STORE_DB_FILE = str(Path(directory) / "store.sqlite")
        database = store_database_module.StoreDatabase()
        products = make_products()

        try:
            started = time.perf_counter()
            await database.sync_store_products(
                "benchmark",
                products,
                crawl_complete=True,
            )
            initial_seconds = time.perf_counter() - started

            statements: list[str] = []
            database.conn.set_trace_callback(statements.append)
            started = time.perf_counter()
            await database.sync_store_products(
                "benchmark",
                products,
                crawl_complete=True,
            )
            repeat_seconds = time.perf_counter() - started
            database.conn.set_trace_callback(None)

            normalized = [" ".join(statement.upper().split()) for statement in statements]
            begin_count = sum(statement.startswith("BEGIN") for statement in normalized)
            commit_count = sum(statement == "COMMIT" for statement in normalized)
            store_lookup_count = sum(
                "FROM STORE WHERE NAME" in statement for statement in normalized
            )

            print(
                f"items={PRODUCT_COUNT} "
                f"initial_seconds={initial_seconds:.6f} "
                f"repeat_seconds={repeat_seconds:.6f} "
                f"statements={len(statements)} "
                f"begins={begin_count} commits={commit_count} "
                f"store_lookups={store_lookup_count}"
            )
        finally:
            await database.close_connection()


def main() -> None:
    asyncio.run(run_benchmark())


if __name__ == "__main__":
    main()
