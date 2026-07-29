import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import store_data_extractor.src.data_extractor as data_extractor
import store_data_extractor.src.store_database as store_database_module


PAGE_ONE = """
<html><body>
  <article class="product">
    <h2>Product One</h2>
    <a class="product-link" href="/product-1">View</a>
    <img src="https://images.example.test/product-1.jpg">
    <span class="price">¥1,000</span>
  </article>
  <a rel="next" href="/page-2">Next</a>
</body></html>
"""

PAGE_TWO = """
<html><body>
  <article class="product">
    <h2>Product Two</h2>
    <a class="product-link" href="/product-2">View</a>
    <img src="https://images.example.test/product-2.jpg">
    <span class="price">¥2,000</span>
  </article>
</body></html>
"""

PAGE_TWO_WITH_NEW_PRODUCT = """
<html><body>
  <article class="product">
    <h2>Product Two</h2>
    <a class="product-link" href="/product-2">View</a>
    <img src="https://images.example.test/product-2.jpg">
    <span class="price">¥2,000</span>
  </article>
  <article class="product">
    <h2>Product Three</h2>
    <a class="product-link" href="/product-3">View</a>
    <img src="https://images.example.test/product-3.jpg">
    <span class="price">¥3,000</span>
  </article>
</body></html>
"""

PARTIAL_PAGE_TWO = """
<html><body>
  <article class="product">
    <h2>Product Two</h2>
    <a class="product-link" href="/product-2">View</a>
    <img src="https://images.example.test/product-2.jpg">
    <span class="price">¥2,000</span>
  </article>
  <article class="product">
    <h2>Product Three</h2>
    <a class="product-link" href="/product-3">View</a>
    <img src="https://images.example.test/product-3.jpg">
  </article>
</body></html>
"""

PAGE_TWO_WITH_CYCLE = """
<html><body>
  <article class="product">
    <h2>Product Two</h2>
    <a class="product-link" href="/product-2">View</a>
    <img src="https://images.example.test/product-2.jpg">
    <span class="price">¥2,000</span>
  </article>
  <a rel="next" href="/page-1">Next</a>
</body></html>
"""

EMPTY_PAGE = """
<html><body>
  <p>No products could be parsed from this response.</p>
</body></html>
"""

STORE = {
    "name": "test_store",
    "name_format": "Test Store",
    "options": {
        "base_url": "https://example.test/page-1",
        "site_main_url": "https://example.test",
        "item_container_selector": "//article[@class='product']",
        "item_name_selector": ".//h2/text()",
        "item_price_selectors": [
            {"currency": "JPY", "selector": ".//span[@class='price']/text()"}
        ],
        "item_link_selector": ".//a[@class='product-link']/@href",
        "item_image_selector": ".//img/@src",
        "sold_out_selector": ".//*[contains(@class, 'sold-out')]",
        "next_page_selector": "//a[@rel='next']",
        "next_page_selector_text": "Next",
        "next_page_attribute": "href",
        "delay_between_requests": 0,
        "encoding": "utf-8",
        "fetch_backend": "curl_cffi",
    },
    "schedule": {
        "minutes": [5],
        "hours": "*",
        "days": "*",
        "months": "*",
        "years": "*",
    },
}


class StorePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_patch = patch.object(
            store_database_module,
            "SQLITE_STORE_DB_FILE",
            str(Path(self.temp_directory.name) / "store.sqlite"),
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.database = store_database_module.StoreDatabase()
        self.addAsyncCleanup(self.database.close_connection)

    async def run_crawl(self, *pages: str | None, store=STORE):
        fetch = AsyncMock(side_effect=pages)
        with (
            patch.object(data_extractor, "try_get_page_content", fetch),
            patch.object(data_extractor.asyncio, "sleep", new=AsyncMock()),
            patch.object(data_extractor.random, "uniform", return_value=0),
        ):
            result = await data_extractor.main_program(None, store, self.database)
        return result

    async def test_fresh_multi_page_crawl_is_fully_silent(self) -> None:
        new_products, updated_products = await self.run_crawl(PAGE_ONE, PAGE_TWO)

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        self.assertEqual(await self.database.get_unsent_products(), [])
        product_count = self.database.cursor.execute(
            "SELECT COUNT(*) FROM Product"
        ).fetchone()[0]
        self.assertEqual(product_count, 2)

    async def test_incomplete_first_crawl_stays_silent_until_complete(self) -> None:
        new_products, updated_products = await self.run_crawl(PAGE_ONE, None)

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        self.assertEqual(await self.database.get_unsent_products(), [])
        initial_fetch = self.database.cursor.execute(
            "SELECT initial_fetch FROM Store WHERE name = ?",
            (STORE["name"],),
        ).fetchone()[0]
        self.assertIsNone(initial_fetch)

        new_products, updated_products = await self.run_crawl(PAGE_ONE, PAGE_TWO)

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        self.assertEqual(await self.database.get_unsent_products(), [])
        initial_fetch = self.database.cursor.execute(
            "SELECT initial_fetch FROM Store WHERE name = ?",
            (STORE["name"],),
        ).fetchone()[0]
        self.assertIsNotNone(initial_fetch)

    async def test_legacy_unsent_rows_stay_hidden_during_incomplete_first_fetch(self) -> None:
        self.database.cursor.execute(
            "INSERT INTO Store (name, initial_fetch) VALUES (?, NULL)",
            (STORE["name"],),
        )
        store_id = self.database.cursor.lastrowid
        self.database.cursor.execute(
            """
            INSERT INTO Product (
                name, product_url, image_url, price_jpy, archived, is_sent, store_id
            ) VALUES (?, ?, ?, ?, 0, 0, ?)
            """,
            (
                "Product One",
                "https://example.test/product-1",
                "https://images.example.test/product-1.jpg",
                1000.0,
                store_id,
            ),
        )

        self.assertEqual(await self.database.get_unsent_products(STORE["name"]), [])

        new_products, updated_products = await self.run_crawl(PAGE_ONE, PAGE_TWO)

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        remaining_unsent = self.database.cursor.execute(
            "SELECT COUNT(*) FROM Product WHERE store_id = ? AND is_sent = 0",
            (store_id,),
        ).fetchone()[0]
        self.assertEqual(remaining_unsent, 0)

    async def test_established_store_reports_only_the_new_product(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO)

        new_products, updated_products = await self.run_crawl(
            PAGE_ONE,
            PAGE_TWO_WITH_NEW_PRODUCT,
        )

        self.assertEqual([product["name"] for product in new_products], ["Product Three"])
        self.assertEqual(updated_products, [])
        unsent_products = await self.database.get_unsent_products(STORE["name"])
        self.assertEqual([product["name"] for product in unsent_products], ["Product Three"])

    async def test_incomplete_established_crawl_does_not_archive_missing_page(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO)

        await self.run_crawl(PAGE_ONE, None)

        archived = self.database.cursor.execute(
            "SELECT archived FROM Product WHERE product_url = ?",
            ("https://example.test/product-2",),
        ).fetchone()[0]
        self.assertEqual(archived, 0)

    async def test_empty_later_page_does_not_archive_missing_products(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO)

        await self.run_crawl(PAGE_ONE, EMPTY_PAGE)

        archived = self.database.cursor.execute(
            "SELECT archived FROM Product WHERE product_url = ?",
            ("https://example.test/product-2",),
        ).fetchone()[0]
        self.assertEqual(archived, 0)

    async def test_partial_product_parse_keeps_first_fetch_silent(self) -> None:
        new_products, updated_products = await self.run_crawl(
            PAGE_ONE,
            PARTIAL_PAGE_TWO,
        )

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        initial_fetch = self.database.cursor.execute(
            "SELECT initial_fetch FROM Store WHERE name = ?",
            (STORE["name"],),
        ).fetchone()[0]
        self.assertIsNone(initial_fetch)

        new_products, updated_products = await self.run_crawl(
            PAGE_ONE,
            PAGE_TWO_WITH_NEW_PRODUCT,
        )

        self.assertEqual(new_products, [])
        self.assertEqual(updated_products, [])
        self.assertEqual(await self.database.get_unsent_products(), [])

    async def test_partial_product_parse_does_not_archive_existing_product(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO_WITH_NEW_PRODUCT)

        await self.run_crawl(PAGE_ONE, PARTIAL_PAGE_TWO)

        archived = self.database.cursor.execute(
            "SELECT archived FROM Product WHERE product_url = ?",
            ("https://example.test/product-3",),
        ).fetchone()[0]
        self.assertEqual(archived, 0)

    async def test_pagination_cycle_does_not_archive_missing_products(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO_WITH_NEW_PRODUCT)

        await self.run_crawl(PAGE_ONE, PAGE_TWO_WITH_CYCLE)

        archived = self.database.cursor.execute(
            "SELECT archived FROM Product WHERE product_url = ?",
            ("https://example.test/product-3",),
        ).fetchone()[0]
        self.assertEqual(archived, 0)

    async def test_invalid_pagination_selector_does_not_complete_or_archive_crawl(self) -> None:
        await self.run_crawl(PAGE_ONE, PAGE_TWO)
        invalid_store = deepcopy(STORE)
        invalid_store["options"]["next_page_selector"] = "css:["

        await self.run_crawl(PAGE_ONE, store=invalid_store)

        archived = self.database.cursor.execute(
            "SELECT archived FROM Product WHERE product_url = ?",
            ("https://example.test/product-2",),
        ).fetchone()[0]
        self.assertEqual(archived, 0)


class StoreDatabaseOptimizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_patch = patch.object(
            store_database_module,
            "SQLITE_STORE_DB_FILE",
            str(Path(self.temp_directory.name) / "store.sqlite"),
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.database = store_database_module.StoreDatabase()
        self.addAsyncCleanup(self.database.close_connection)

    async def test_sync_uses_one_transaction_and_one_store_lookup(self) -> None:
        statements: list[str] = []
        self.database.conn.set_trace_callback(statements.append)
        products = [
            {
                "name": f"Product {index}",
                "product_url": f"https://example.test/product-{index}",
                "image_url": f"https://images.example.test/product-{index}.jpg",
                "prices": {"JPY": float(index)},
                "archived": False,
            }
            for index in range(20)
        ]

        await self.database.sync_store_products(
            "test_store",
            products,
            crawl_complete=True,
        )

        normalized = [" ".join(statement.upper().split()) for statement in statements]
        self.assertEqual(sum(statement.startswith("BEGIN") for statement in normalized), 1)
        self.assertEqual(sum(statement == "COMMIT" for statement in normalized), 1)
        self.assertEqual(
            sum("FROM STORE WHERE NAME" in statement for statement in normalized),
            1,
        )
        self.assertEqual(
            sum("FROM PRODUCT" in statement and "WHERE STORE_ID" in statement for statement in normalized),
            1,
        )

    async def test_expected_indexes_are_created_and_used(self) -> None:
        index_names = {
            row[1]
            for row in self.database.cursor.execute("PRAGMA index_list('Product')").fetchall()
        }
        self.assertTrue(
            {
                "idx_product_store_identity",
                "idx_product_store_url",
                "idx_product_unsent_store",
            }.issubset(index_names)
        )

        store_indexes = {
            row[1]
            for row in self.database.cursor.execute("PRAGMA index_list('Store')").fetchall()
        }
        self.assertIn("idx_store_name", store_indexes)

        identity_plan = " ".join(
            row[3]
            for row in self.database.cursor.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM Product "
                "WHERE store_id = ? AND image_url = ? AND product_url = ?",
                (1, "image", "product"),
            ).fetchall()
        )
        self.assertIn("idx_product_store_identity", identity_plan)

        store_plan = " ".join(
            row[3]
            for row in self.database.cursor.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM Store WHERE name = ?",
                ("test_store",),
            ).fetchall()
        )
        self.assertIn("idx_store_name", store_plan)

        url_plan = " ".join(
            row[3]
            for row in self.database.cursor.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM Product "
                "WHERE store_id = ? AND product_url = ?",
                (1, "product"),
            ).fetchall()
        )
        self.assertIn("idx_product_store_url", url_plan)

        unsent_plan = " ".join(
            row[3]
            for row in self.database.cursor.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM Product "
                "WHERE is_sent = 0 AND store_id = ?",
                (1,),
            ).fetchall()
        )
        self.assertIn("idx_product_unsent_store", unsent_plan)


if __name__ == "__main__":
    unittest.main()
