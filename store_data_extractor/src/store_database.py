from sqlite3 import connect, Error, Row
import os
from datetime import datetime
import asyncio
import sys
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) # Add the project root directory to the path
from utils.data_directory_helper import ensure_directory_exists

# Get to the root directory
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')) # Root project directory
DATA_DIR = os.path.join(ROOT_DIR, "data")  # Data directory

ensure_directory_exists(DATA_DIR)  # Ensure that the data directory exists

SQLITE_STORE_DB_FILE = os.path.join(DATA_DIR, "store_db.sqlite")  # SQLite database file


class StoreDatabase:
    """Manage the store data in an SQLite database."""
    def __init__(self):
        self.logger = logging.getLogger("StoreDatabase")
        self.store_db_file_name = SQLITE_STORE_DB_FILE
        self.db_name = "Store Database"
        self.db_lock = asyncio.Lock()

        try:
            self.conn = connect(self.store_db_file_name, isolation_level=None)
            self.conn.row_factory = Row
            self.cursor = self.conn.cursor()
            self.init_database()
        except self.conn.Error as e:
            self.logger.error(f"Failed to connect to the database {self.db_name}")
            self.logger.error(f"An error occurred: {e}")

    def init_database(self) -> None:
        """Initialize the store database."""
        self.logger.info(f"Initializing database {self.db_name}...")
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS Store (
                                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                                name TEXT NOT NULL,
                                initial_fetch TIMESTAMP DEFAULT NULL
                                )""")
            self.cursor.execute("""
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
                                )""")

            self.conn.commit()
            self.logger.info("Database initialized successfully.")
        except Error as e:
            self.logger.error(f"Failing to initialize the database {self.db_name}")
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()
            return

    async def close_connection(self) -> None:
        """Close the database connection."""
        self.logger.info("Closing database connection...")
        if self.conn:
            self.conn.close()


    def add_store(self, name: str) -> int:
        """Add a store to the database if it doesn't exist and return the store ID."""
        try:
            # Check if the store already exists
            store_id = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (name,)).fetchone()
            if store_id:
                return store_id[0]

            logging.info(f"Store '{name}' not found. Creating a new store...")

            # Create store if it doesn't exist
            self.cursor.execute("INSERT INTO Store (name) VALUES (?)", (name,))
            self.conn.commit()

            # Retrieve the newly created store ID
            store_id = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (name,)).fetchone()
            if not store_id:
                self.logger.error(f"Store '{name}' not found after insertion.")
                return None

            return store_id[0]

        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()
            return None


    async def add_or_update_product(self, name: str, product_url: str, image_url: str,
                                price_jpy: float, price_eur: float, archived: bool, store_name: str) -> str:
        """
        Add or update a product in the database.

        Returns:
            str: "new" if the product was created,
                "updated" if the product was updated,
                "error" if an error occurred (e.g. store creation failed).
        """
        async with self.db_lock:
            try:
                store_id: int = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
                if store_id is None:
                    self.logger.error(f"Store '{store_name}' not found.")
                    return "error"
                store_id: int = store_id[0]

                # Check if product already exists
                product = self.cursor.execute(
                    "SELECT id FROM Product WHERE product_url = ? AND store_id = ?",
                    (product_url, store_id)
                ).fetchone()

                if product:
                    # Update existing product: set archived=0 (in case it was archived),
                    product_id = product[0]
                    self.cursor.execute("""
                        UPDATE Product
                        SET name = ?, price_jpy = ?, price_eur = ?, image_url = ?, last_seen = ?, archived = 0
                        WHERE id = ?
                    """, (name, price_jpy, price_eur, image_url, datetime.now(), product_id))
                    self.conn.commit()
                    return "updated"  # Product updated
                else:
                    archived_int = 1 if archived else 0 # Convert bool to int

                    # Insert new product
                    self.cursor.execute("""
                        INSERT INTO Product (name, product_url, image_url, price_jpy, price_eur, archived, store_id, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, product_url, image_url, price_jpy, price_eur, archived_int, store_id, datetime.now(), datetime.now()))
                    self.conn.commit()

                    if not archived:
                        return "new"  # A new product was added

            except self.conn.Error as e:
                self.logger.error(f"An error occurred: {e}")
                self.conn.rollback()
                return "error"


    def get_stores(self) -> list:
        """Get all stores from the database."""
        try:
            stores: list = self.cursor.execute("SELECT * FROM Store").fetchall()
            return [dict(store) for store in stores] # Convert to list of dictionaries
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            return []

    async def get_products(self, store_name: str) -> list:
        """Get all products for a store."""
        try:
            store: int = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
            if store is None:
                self.logger.error(f"Store '{store_name}' not found.")
                return []
            store_id: int = store["id"]
            products: list = self.cursor.execute("SELECT name, product_url, image_url, price_jpy, price_eur FROM Product WHERE store_id = ?", (store_id,)).fetchall()

            return [dict(product) for product in products]  # Convert to list of dictionaries
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            return []

    async def update_and_archive_products(self, store_name: str, current_items: list) -> list:
        """
        Update and archive products in the database.
        1) Archives products that are no longer visible on the site.
        2) Calls add_or_update_product for the current items.
        Returns a list of newly added products (as tuples of (name, product_url)).
        """
        store_id: int = self.add_store(store_name)
        if store_id is None:
            self.logger.error(f"Failed to find or create store {store_name}")
            return []

        # Check if this is the first fetch for the store and is not yet initialized aka None
        initial_fetch: bool = self.cursor.execute(
            "SELECT initial_fetch FROM Store WHERE id = ?", (store_id,)
        ).fetchone()[0] is None

        if initial_fetch:
            # First fetch: update initial_fetch and skip new product notifications
            self.cursor.execute(
                "UPDATE Store SET initial_fetch = ? WHERE id = ?",
                (datetime.now(), store_id)
            )
            self.conn.commit()
            self.logger.info(f"First fetch for {store_name}. Skipping new product notifications.")

        # Set of currently visible product URLs (from the site)
        current_product_urls: set = {item["product_url"] for item in current_items}

        # Get all non-archived product URLs from the DB
        db_product_urls: list = self.cursor.execute(
            "SELECT product_url FROM Product WHERE store_id = ? AND archived = 0",
            (store_id,)
        ).fetchall()
        db_product_urls: set = {row[0] for row in db_product_urls}

        # Archive products that are no longer visible
        to_archive: set = db_product_urls - current_product_urls  # Set difference
        for product_url in to_archive:
            self.cursor.execute(
                "UPDATE Product SET archived = 1 WHERE product_url = ? AND store_id = ?",
                (product_url, store_id)
            )

        # Go through each current item and add or update
        new_products: list = []
        for item in current_items:
            try:
                # Extract product details
                name = item.get("name", "").strip()
                product_url = item.get("product_url", "").strip()
                image_url = item.get("image_url", "").strip()
                prices = item.get("prices", {})
                archived = item.get("archived", False)

                # Force prices to float or set to None if unavailable
                price_jpy = float(prices.get("JPY", 0)) if "JPY" in prices else None
                price_eur = float(prices.get("EUR", 0)) if "EUR" in prices else None

                if not name or not product_url:
                    self.logger.warning(f"Skipping item with missing data: {item}")
                    continue

                # Add or update product in the database
                product_status = await self.add_or_update_product(
                    name=name,
                    product_url=product_url,
                    image_url=image_url,
                    price_jpy=price_jpy,
                    price_eur=price_eur,
                    archived=archived,
                    store_name=store_name
                )
                if product_status == "new" and not initial_fetch:
                    new_products.append(item)
                elif product_status == "error":
                    self.logger.error(f"Error adding/updating product: {product_url} for store {store_name}")
            except Exception as e:
                self.logger.error(f"Error processing item {item}: {e}")

        self.conn.commit()
        return new_products


    def get_new_products(self, store_name: str) -> list:
        """Get new products that have not been updated since first seen."""
        store = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
        if store is None:
            self.logger.error(f"Store '{store_name}' not found.")
            return []
        store_id: int = store["id"]

        # Only new products have first_seen equal to last_seen
        new_products = self.cursor.execute("""
            SELECT name, product_url FROM Product WHERE store_id = ? AND first_seen = last_seen
        """, (store_id,)).fetchall()

        return [dict(product) for product in new_products]  # Convert to list of dictionaries

    def delete_store(self, store_name: str) -> None:
        """Delete a store and its products from the database."""
        try:
            store_id = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
            if store_id is None:
                self.logger.error(f"Store '{store_name}' not found.")
                return
            store_id: int = store_id[0]
            self.cursor.execute("DELETE FROM Product WHERE store_id = ?", (store_id,))
            self.cursor.execute("DELETE FROM Store WHERE id = ?", (store_id,))
            self.conn.commit()
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()

    def delete_product(self, product_name: str) -> None:
        """Delete a product from the database."""
        try:
            self.cursor.execute("DELETE FROM Product WHERE name = ?", (product_name,))
            self.conn.commit()
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()



