from sqlite3 import connect, Error, Row
from typing import Optional, List, Dict
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
            self.conn = connect(self.store_db_file_name, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = Row
            self.cursor = self.conn.cursor()
            self.init_database()
        except Error as e:
            self.logger.error(f"Failed to connect to the database {self.db_name}: {e}")

    def init_database(self) -> None:
        """Initialize the store database."""
        self.logger.info(f"Initializing database {self.db_name}...")
        try:
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
                    store_id INTEGER NOT NULL,
                    FOREIGN KEY (store_id) REFERENCES Store (id)
                );
            """)
            self.logger.info("Database initialized successfully.")
        except Error as e:
            self.logger.error(f"Failed to initialize the database {self.db_name}: {e}")

    async def close_connection(self) -> None:
        """Close the database connection."""
        self.logger.info("Closing database connection...")
        if self.conn:
            self.conn.close()

    def add_store(self, name: str) -> Optional[int]:
        """Add a store to the database if it doesn't exist and return the store ID."""
        try:
            store: Optional[Row] = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (name,)).fetchone()
            if store:
                return int(store["id"])

            self.logger.info(f"Store '{name}' not found. Creating a new store...")
            self.cursor.execute("INSERT INTO Store (name) VALUES (?)", (name,))

            store_row: Optional[Row] = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (name,)).fetchone()
            return int(store_row["id"]) if store_row else None

        except Error as e:
            self.logger.error(f"Error adding store '{name}': {e}")
            return None

    async def add_or_update_product(self, name: str, product_url: str, image_url: Optional[str],
                                     price_jpy: Optional[float], price_eur: Optional[float],
                                     archived: int, store_name: str) -> Optional[str]:
        """
        Add or update a product in the database.
        Always updates last_seen and archived status.
        Checks both URL and name to determine if product exists.
        """
        store_id: Optional[int] = self.add_store(store_name)
        if store_id is None:
            self.logger.error(f"Failed to find or create store {store_name}")
            return "error"

        async with self.db_lock:
            try:
                now = datetime.now()
                # Check both URL and name
                product: Optional[Row] = self.cursor.execute(
                    """
                    SELECT id FROM Product
                    WHERE (product_url = ? OR name = ?)
                    AND store_id = ?
                    """,
                    (product_url, name, store_id)
                ).fetchone()

                if product:
                    product_id = product["id"]
                    self.cursor.execute("""
                        UPDATE Product
                        SET price_jpy = ?, price_eur = ?, image_url = ?,
                            last_seen = ?, archived = ?
                        WHERE id = ?
                    """, (price_jpy, price_eur, image_url, now, archived, product_id))
                    return "updated"

                self.cursor.execute("""
                    INSERT INTO Product (name, product_url, image_url, price_jpy, price_eur,
                                      archived, store_id, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, product_url, image_url, price_jpy, price_eur, archived,
                     store_id, now, now))
                return "new"

            except Error as e:
                self.logger.error(f"Error adding/updating product '{product_url}': {e}")
                return "error"

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

    async def get_products(self, store_name: str) -> List[ProductDataType]:
        """Get all products for a store."""
        try:
            store: Optional[Row] = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
            if store is None:
                self.logger.error(f"Store '{store_name}' not found.")
                return []

            store_id: int = store["id"]
            products: List[Row] = self.cursor.execute(
                "SELECT id, name, product_url, image_url, price_jpy, price_eur, archived FROM Product WHERE store_id = ?",
                (store_id,)
            ).fetchall()

            return [
                {
                    "id": product["id"],
                    "name": product["name"],
                    "product_url": product["product_url"],
                    "image_url": product["image_url"],
                    "prices": {
                        "JPY": product["price_jpy"] if product["price_jpy"] != 0.0 else None,
                        "EUR": product["price_eur"] if product["price_eur"] != 0.0 else None
                    },
                    "archived": bool(product["archived"])
                }
                for product in products
            ]
        except Error as e:
            self.logger.error(f"Error fetching products for store '{store_name}': {e}")
            return []

    async def sync_store_products(self, store_name: str, current_items: List[ProductDataType]) -> List[ProductDataType]:
        """
        Update products in the database.
        The archived status comes directly from the data.
        Returns a list of newly added products.
        """
        store_id: Optional[int] = self.add_store(store_name)
        if store_id is None:
            self.logger.error(f"Failed to find or create store {store_name}")
            return []

        # Check if this is the first fetch for the store
        initial_fetch: bool = self.cursor.execute(
            "SELECT initial_fetch FROM Store WHERE id = ?", (store_id,)
        ).fetchone()[0] is None

        if initial_fetch:
            self.cursor.execute(
                "UPDATE Store SET initial_fetch = ? WHERE id = ?",
                (datetime.now(), store_id)
            )
            self.logger.info(f"First fetch for {store_name}. Skipping new product notifications.")

        new_products: List[ProductDataType] = []
        for item in current_items:
            try:
                name = item["name"].strip()
                product_url = item["product_url"].strip()
                image_url = str(item.get("image_url", "")).strip()

                raw_prices = item.get("prices", {})
                prices: Dict[str, float] = {
                    key: float(value)
                    for key, value in raw_prices.items()
                    if isinstance(value, (int, float))
                }

                archived: bool = bool(item.get("archived", False))
                price_jpy = prices.get("JPY", None)
                price_eur = prices.get("EUR", None)

                if not name or not product_url:
                    self.logger.warning(f"Skipping item with missing data: {item}")
                    continue

                product_status = await self.add_or_update_product(
                    name=name,
                    product_url=product_url,
                    image_url=image_url,
                    price_jpy=price_jpy,
                    price_eur=price_eur,
                    archived=int(archived),
                    store_name=store_name
                )

                # Check if the product is new and not from the initial fetch
                if product_status == "new" and not initial_fetch:
                    new_item: ProductDataType = {
                        "name": name,
                        "product_url": product_url,
                        "image_url": image_url,
                        "prices": {
                            "JPY": price_jpy if price_jpy is not None else None,
                            "EUR": price_eur if price_eur is not None else None
                        },
                        "archived": archived
                    }
                    new_products.append(new_item)

            except Exception as e:
                self.logger.error(f"Error processing item {item}: {e}")

        return new_products

    async def mark_products_as_archived(self, store_name: str, urls: List[str]) -> None:
        """Mark specific products as archived based on their URLs."""
        if not urls:
            return

        try:
            store_id = self.add_store(store_name)
            if store_id is None:
                return

            placeholders = ','.join('?' * len(urls))
            query = f"""
                UPDATE Product
                SET archived = 1, last_seen = ?
                WHERE store_id = ? AND product_url IN ({placeholders})
            """

            params = [datetime.now(), store_id] + urls
            self.cursor.execute(query, params)
            self.conn.commit()

            rows_affected = self.cursor.rowcount
            if rows_affected > 0:
                self.logger.info(f"Marked {rows_affected} products as archived for store {store_name}")

        except Error as e:
            self.logger.error(f"Error marking products as archived: {e}")
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