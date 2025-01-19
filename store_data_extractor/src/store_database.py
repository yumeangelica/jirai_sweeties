from sqlite3 import connect, Error
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
        self.store_db_name = SQLITE_STORE_DB_FILE
        self.db_lock = asyncio.Lock()

        try:
            self.conn = connect(self.store_db_name, isolation_level=None)
            self.cursor = self.conn.cursor()
            self.init_database()
        except Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.logger.error("Failed to initialize database.")

    def init_database(self) -> None:
        """Initialize the store database."""
        self.logger.info("Initializing database...")
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS Store (
                                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                                name TEXT NOT NULL
                                )""")
            self.cursor.execute("""
                                CREATE TABLE IF NOT EXISTS Product (
                                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                                name TEXT NOT NULL,
                                url TEXT NOT NULL,
                                price REAL,
                                archived BOOLEAN DEFAULT 0,
                                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                store_id INTEGER NOT NULL,
                                FOREIGN KEY (store_id) REFERENCES Store (id)
                                )""")

            self.conn.commit()
            self.logger.info("Database initialized successfully.")
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()
            return

    async def close_connection(self) -> None:
        """Close the database connection."""
        self.logger.info("Closing database connection...")
        print("Closing database connection...")
        if self.conn:
            self.conn.close()

    def add_store(self, name: str) -> int:
        """Add a store to the database if it doesn't exist and return the store ID."""
        try:
            # Create store if it doesn't exist
            self.cursor.execute("INSERT OR IGNORE INTO Store (name) VALUES (?)", (name,))
            self.conn.commit()

            # Retrieve the store ID
            store_id = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (name,)).fetchone()

            if not store_id:
                self.logger.error(f"Store '{name}' not found.")
                return None

            store_id: int = store_id[0]

            return store_id

        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            self.conn.rollback()
            return None

    async def add_or_update_product(self, name: str, url: str, price: float, store_name: str) -> None:
        """Add or update a product in the database."""
        async with self.db_lock:
            try:
                # Get or create the store ID
                store_id: int = self.add_store(store_name)

                if store_id is None:
                    self.logger.error(f"Store '{store_name}' creation failed.")
                    return

                # Check if the product exists by URL
                product = self.cursor.execute(
                    "SELECT id, archived FROM Product WHERE url = ? AND store_id = ?",
                    (url, store_id)
                ).fetchone()

                if product:
                    # Update existing product
                    product_id, archived = product
                    self.cursor.execute("""
                        UPDATE Product
                        SET name = ?, price = ?, last_seen = ?, archived = 0
                        WHERE id = ?
                    """, (name, price, datetime.now(), product_id))
                else:
                    # Add new product
                    self.cursor.execute("""
                        INSERT INTO Product (name, url, price, store_id, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (name, url, price, store_id, datetime.now(), datetime.now()))

                self.conn.commit()
            except self.conn.Error as e:
                self.logger.error(f"An error occurred: {e}")
                self.conn.rollback()


    def get_stores(self) -> list:
        """Get all stores from the database."""
        try:
            stores: list = self.cursor.execute("SELECT * FROM Store").fetchall()
            return stores
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            return []

    def get_products(self, store_name: str) -> list:
        """Get all products for a store."""
        try:
            store_id: int = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
            if store_id is None:
                self.logger.error(f"Store '{store_name}' not found.")
                return []
            store_id: int = store_id[0]
            products: list = self.cursor.execute("SELECT * FROM Product WHERE store_id = ?", (store_id,)).fetchall()
            return products
        except self.conn.Error as e:
            self.logger.error(f"An error occurred: {e}")
            return []

    async def update_and_archive_products(self, store_name: str, current_items: list) -> list:
        """Update and archive products in the database."""
        store_id: int = self.add_store(store_name)

        if store_id is None:
            self.logger.error(f"Failed to find or create store {store_name}")
            return []

        current_urls: set = {item[1] for item in current_items}
        db_urls: list = self.cursor.execute(
            "SELECT url FROM Product WHERE store_id = ? AND archived = 0",
            (store_id,)
        ).fetchall()
        db_urls: set = {row[0] for row in db_urls}

        # Archive products that are no longer visible
        to_archive: set = db_urls - current_urls
        for url in to_archive:
            self.cursor.execute("UPDATE Product SET archived = 1 WHERE url = ?", (url,))

        new_products: list = []  # List of new products

        # Add or activate visible products
        for name, url, price in current_items:
            product: tuple = self.cursor.execute(
                "SELECT id, name, price FROM Product WHERE url = ? AND store_id = ?",
                (url, store_id)
            ).fetchone()

            if product:
                # Product found, update details
                product_id, existing_name, existing_price = product
                if existing_name != name or existing_price != price:
                    self.cursor.execute(
                        "UPDATE Product SET archived = 0, last_seen = ? WHERE id = ?",
                        (datetime.now(), product_id)
                    )
            else:
                # Add new product
                await self.add_or_update_product(name, url, price, store_name)
                new_products.append((name, url))

        self.conn.commit()

        return new_products


    def get_new_products(self, store_name: str) -> list:
        """Get new products that have not been updated since first seen."""
        store_id = self.cursor.execute("SELECT id FROM Store WHERE name = ?", (store_name,)).fetchone()
        if store_id is None:
            self.logger.error(f"Store '{store_name}' not found.")
            return []
        store_id: int = store_id[0]

        # Only new products have first_seen equal to last_seen
        new_products = self.cursor.execute("""
            SELECT name, url FROM Product WHERE store_id = ? AND first_seen = last_seen
        """, (store_id,)).fetchall()

        return new_products

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



