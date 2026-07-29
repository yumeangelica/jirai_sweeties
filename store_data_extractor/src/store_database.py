from sqlite3 import connect, Error, Row
from typing import Optional, List, Dict, Tuple
import os
from datetime import datetime
import asyncio
import sys
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) # Add the project root directory to the path
from utils.helpers import ensure_directory_exists
from store_data_extractor.store_types import ProductDataType, StoreDataType

# Get to the root directory
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')) # Root project directory
DATA_DIR = os.path.join(ROOT_DIR, "data")  # Data directory

ensure_directory_exists(DATA_DIR)  # Ensure that the data directory exists

SQLITE_STORE_DB_FILE = os.path.join(DATA_DIR, "store_db.sqlite")  # SQLite database file

class StoreDatabase:
    """Manage the store data in an SQLite database."""
    def __init__(self) -> None:
        self.logger = logging.getLogger("StoreDatabase")
        self.store_db_file_name = SQLITE_STORE_DB_FILE
        self.db_name = "Store Database"
        self.db_lock = asyncio.Lock()

        try:
            self.conn = connect(self.store_db_file_name, isolation_level=None, check_same_thread=False, timeout=30.0)
            self.conn.row_factory = Row
            self.cursor = self.conn.cursor()
            self.init_database()
            self.logger.info(f"Using SQLite database file: {self.store_db_file_name}")
        except Error as e:
            self.logger.error(f"Failed to connect to the database {self.db_name}: {e}")

    def init_database(self) -> None:
        """Initialize the store database."""
        self.logger.info(f"Initializing database {self.db_name}...")
        try:
            self.cursor.execute("PRAGMA foreign_keys = ON;")
            self.cursor.execute("PRAGMA busy_timeout = 30000;")
            self.cursor.execute("PRAGMA journal_mode=WAL;")
            self.cursor.execute("PRAGMA synchronous=NORMAL;")
            self.cursor.executescript("""
                CREATE TABLE IF NOT EXISTS Store (
                    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                    name TEXT NOT NULL,
                    initial_fetch TIMESTAMP DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS Product (
                    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                    name TEXT NOT NULL,
                    product_url TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    price_jpy REAL,
                    price_eur REAL,
                    archived INTEGER DEFAULT 0,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_sent INTEGER DEFAULT 0,
                    store_id INTEGER NOT NULL,
                    FOREIGN KEY (store_id) REFERENCES Store (id)
                );
                CREATE INDEX IF NOT EXISTS idx_store_name
                    ON Store (name);
                CREATE INDEX IF NOT EXISTS idx_product_store_identity
                    ON Product (store_id, image_url, product_url);
                CREATE INDEX IF NOT EXISTS idx_product_store_url
                    ON Product (store_id, product_url);
                CREATE INDEX IF NOT EXISTS idx_product_unsent_store
                    ON Product (is_sent, store_id);
            """)
            self.logger.info("Database initialized successfully.")
        except Error as e:
            self.logger.error(f"Failed to initialize the database {self.db_name}: {e}")

    async def close_connection(self) -> None:
        """Close the database connection."""
        self.logger.info("Closing database connection...")
        if self.conn:
            self.conn.close()

    def get_stores(self) -> List[StoreDataType]:
        """Get all stores from the database."""
        try:
            rows: List[Row] = self.cursor.execute("SELECT * FROM Store").fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "initial_fetch": row["initial_fetch"]
                }
                for row in rows
            ]
        except Error as e:
            self.logger.error(f"Error fetching stores: {e}")
            return []

    async def get_unsent_products(self, store_name: Optional[str] = None) -> List[ProductDataType]:
        """Get all products that have not been sent, optionally for a single store."""
        try:
            if store_name is not None:
                products: List[Row] = self.cursor.execute(
                    """
                    SELECT p.id, p.name, p.product_url, p.image_url, p.price_jpy, p.price_eur
                    FROM Product p
                    JOIN Store s ON s.id = p.store_id
                    WHERE p.is_sent = 0
                      AND s.name = ?
                      AND s.initial_fetch IS NOT NULL
                    """,
                    (store_name,)
                ).fetchall()
            else:
                products = self.cursor.execute(
                    """
                    SELECT p.id, p.name, p.product_url, p.image_url, p.price_jpy, p.price_eur
                    FROM Product p
                    JOIN Store s ON s.id = p.store_id
                    WHERE p.is_sent = 0 AND s.initial_fetch IS NOT NULL
                    """
                ).fetchall()

            if not products:
                return []

            return [
                {
                    "id": product["id"],
                    "name": product["name"],
                    "product_url": product["product_url"],
                    "image_url": product["image_url"],
                    "prices": {
                        "JPY": product["price_jpy"] if product["price_jpy"] != 0.0 else None,
                        "EUR": product["price_eur"] if product["price_eur"] != 0.0 else None
                    }
                }
                for product in products
            ]
        except Error as e:
            self.logger.error(f"Error fetching unsent products: {e}")
            return []

    async def sync_store_products(
        self,
        store_name: str,
        current_items: List[ProductDataType],
        *,
        crawl_complete: bool = True,
    ) -> Tuple[List[ProductDataType], List[ProductDataType]]:
        """
        Add or update one crawl's products in a single transaction.

        A store remains in first-fetch mode until a non-empty crawl completes.
        Products observed during an incomplete first crawl are persisted as sent,
        preventing a later page or retry from flooding notification channels.
        Returns a tuple of lists: (new_products, updated_products).
        """
        if not current_items:
            return [], []

        async with self.db_lock:
            new_products: List[ProductDataType] = []
            updated_products: List[ProductDataType] = []
            inserted_count = 0
            existing_count = 0
            error_count = 0

            try:
                self.cursor.execute("BEGIN IMMEDIATE")

                store_row: Optional[Row] = self.cursor.execute(
                    "SELECT id, initial_fetch FROM Store WHERE name = ?",
                    (store_name,),
                ).fetchone()
                if store_row is None:
                    self.cursor.execute("INSERT INTO Store (name) VALUES (?)", (store_name,))
                    if self.cursor.lastrowid is None:
                        raise Error(f"Failed to create store {store_name}")
                    store_id = int(self.cursor.lastrowid)
                    initial_fetch = True
                else:
                    store_id = int(store_row["id"])
                    initial_fetch = store_row["initial_fetch"] is None

                existing_rows: List[Row] = self.cursor.execute(
                    """
                    SELECT id, name, product_url, image_url, price_jpy, price_eur
                    FROM Product
                    WHERE store_id = ?
                    """,
                    (store_id,),
                ).fetchall()
                products_by_image: Dict[str, Dict[str, Dict[str, object]]] = {}
                for row in existing_rows:
                    products_by_image.setdefault(str(row["image_url"]), {})[
                        str(row["product_url"])
                    ] = dict(row)

                now = datetime.now().isoformat(sep=" ")
                current_urls: set[str] = set()
                self.logger.info(f"Syncing {len(current_items)} products for store {store_name}.")

                for item in current_items:
                    try:
                        name = item["name"].strip()
                        product_url = item["product_url"].strip()
                        image_url = str(item.get("image_url", "")).strip()
                        if not name or not product_url or not image_url:
                            raise ValueError("Product name, URL, and image URL are required")

                        raw_prices = item.get("prices", {})
                        prices: Dict[str, float] = {
                            key: float(value)
                            for key, value in raw_prices.items()
                            if isinstance(value, (int, float))
                        }
                        archived = int(bool(item.get("archived", False)))
                        price_jpy = prices.get("JPY")
                        price_eur = prices.get("EUR")
                    except (AttributeError, KeyError, TypeError, ValueError) as error:
                        error_count += 1
                        self.logger.error(f"Error processing item {item}: {error}")
                        continue

                    current_urls.add(product_url)
                    matching_by_url = products_by_image.get(image_url, {})
                    matching_product = matching_by_url.get(product_url)
                    product_status = ""
                    product: Optional[ProductDataType] = None

                    if matching_product is None:
                        product_status = "new" if not matching_by_url else "updated"
                        self.cursor.execute(
                            """
                            INSERT INTO Product (
                                name, product_url, image_url, price_jpy, price_eur,
                                archived, store_id, first_seen, last_seen, is_sent
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                name,
                                product_url,
                                image_url,
                                price_jpy,
                                price_eur,
                                archived,
                                store_id,
                                now,
                                now,
                                int(initial_fetch),
                            ),
                        )
                        if self.cursor.lastrowid is None:
                            raise Error(f"Failed to insert product {product_url}")

                        product_id = int(self.cursor.lastrowid)
                        inserted_row = {
                            "id": product_id,
                            "name": name,
                            "product_url": product_url,
                            "image_url": image_url,
                            "price_jpy": price_jpy,
                            "price_eur": price_eur,
                        }
                        products_by_image.setdefault(image_url, {})[product_url] = inserted_row
                        product = {
                            "id": product_id,
                            "name": name,
                            "product_url": product_url,
                            "image_url": image_url,
                            "prices": {"JPY": price_jpy, "EUR": price_eur},
                        }
                        inserted_count += 1
                    else:
                        self.cursor.execute(
                            """
                            UPDATE Product
                            SET price_jpy = ?, price_eur = ?, archived = ?, last_seen = ?
                            WHERE id = ?
                            """,
                            (price_jpy, price_eur, archived, now, matching_product["id"]),
                        )
                        existing_count += 1

                    if not initial_fetch and product is not None:
                        if product_status == "new":
                            new_products.append(product)
                        elif product_status == "updated":
                            updated_products.append(product)

                if crawl_complete and current_urls:
                    placeholders = ",".join("?" for _ in current_urls)
                    self.cursor.execute(
                        f"""
                        UPDATE Product
                        SET archived = 1, last_seen = ?
                        WHERE store_id = ?
                          AND archived = 0
                          AND product_url NOT IN ({placeholders})
                        """,
                        [now, store_id, *current_urls],
                    )

                if initial_fetch:
                    self.cursor.execute(
                        "UPDATE Product SET is_sent = 1 WHERE store_id = ? AND is_sent = 0",
                        (store_id,),
                    )

                if initial_fetch and crawl_complete and current_urls:
                    self.cursor.execute(
                        "UPDATE Store SET initial_fetch = ? WHERE id = ?",
                        (now, store_id),
                    )
                    self.logger.info(
                        f"First complete fetch for {store_name}. Skipping new product notifications."
                    )
                elif initial_fetch:
                    self.logger.error(
                        f"Store {store_name} is still in first-fetch mode after an incomplete crawl; "
                        "notifications stay disabled until a complete crawl succeeds."
                    )

                self.conn.commit()
                self.logger.info(
                    f"Database sync complete for {store_name}: "
                    f"{inserted_count} inserted, {existing_count} existing/updated, "
                    f"{error_count} errors."
                )
                return new_products, updated_products
            except Exception as error:
                self.conn.rollback()
                self.logger.error(f"Error syncing products for store '{store_name}': {error}")
                return [], []

    async def mark_product_as_sent(self, product_id: int) -> None:
        """Mark a product as sent in db when product is posted."""
        # Delegate to the batch path so every "mark sent" write runs under the
        # same db_lock + BEGIN IMMEDIATE transaction.
        await self.mark_products_as_sent([product_id])

    async def mark_products_as_sent(self, product_ids: List[int]) -> None:
        """Mark multiple products as sent in one transaction."""
        unique_ids = list(dict.fromkeys(product_ids))
        if not unique_ids:
            return

        async with self.db_lock:
            try:
                self.cursor.execute("BEGIN IMMEDIATE")
                placeholders = ",".join("?" for _ in unique_ids)
                self.cursor.execute(
                    f"UPDATE Product SET is_sent = 1 WHERE id IN ({placeholders})",
                    unique_ids,
                )
                self.conn.commit()
            except Error as e:
                self.logger.error(f"Error marking products as sent: {e}")
                self.conn.rollback()

    def delete_store(self, store_name: str) -> None:
        """Delete a store and its products from the database."""
        try:
            store_row: Optional[Row] = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
            if store_row is None:
                self.logger.error(f"Store '{store_name}' not found.")
                return

            store_id: int = store_row["id"]
            self.cursor.execute("DELETE FROM Product WHERE store_id = ?", (store_id,))
            self.cursor.execute("DELETE FROM Store WHERE id = ?", (store_id,))
        except Error as e:
            self.logger.error(f"Error deleting store '{store_name}': {e}")

    def delete_product(self, product_name: str) -> None:
        """Delete a product from the database."""
        try:
            self.cursor.execute("DELETE FROM Product WHERE name = ?", (product_name,))
        except Error as e:
            self.logger.error(f"Error deleting product '{product_name}': {e}")
