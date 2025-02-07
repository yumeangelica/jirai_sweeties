from sqlite3 import connect, Error, Row
import os
from datetime import datetime
import asyncio
import sys
import logging
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(__file__))) # Add the project root directory to the path
from utils.helpers import ensure_directory_exists
from bot.discord_types import DiscordUserDataType

# Get to the root directory
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) # Root project directory
DATA_DIR = os.path.join(ROOT_DIR, "data")  # Data directory

ensure_directory_exists(DATA_DIR)  # Ensure that the data directory exists

SQLITE_DISCORD_DB_FILE = os.path.join(DATA_DIR, "discord_db.sqlite")  # SQLite database file

class DiscordDatabase:
    """Manage the bot database."""
    def __init__(self) -> None:
        self.logger = logging.getLogger("BotDatabase")
        self.store_db_file_path = SQLITE_DISCORD_DB_FILE
        self.db_name = "Discord Database"
        self.db_lock = asyncio.Lock()

        try:
            self.conn = connect(self.store_db_file_path, isolation_level=None)
            self.conn.row_factory = Row
            self.cursor = self.conn.cursor()
            self.init_database()
        except self.conn.Error as e:
            self.logger.error(f"Failed to connect to the database: {e}")
            self.logger.error(f"Error connecting to the database: {e}")


    def init_database(self) -> None:
        """Initialize the database."""
        try:
            self.logger.info(f"Initializing database {self.db_name}...")
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS Users (
                    id INTEGER PRIMARY KEY NOT NULL,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")

            self.conn.commit()
            self.logger.info("Database initialized.")
        except Error as e:
            self.logger.error(f"Failed to initialize the database {self.db_name}")
            self.logger.error(f"Error initializing the database: {e}")
            self.conn.rollback()
            return


    async def close_connection(self) -> None:
        """Close the database connection."""
        self.logger.info("Closing database connection...")
        if self.conn:
            self.conn.close()


    async def add_user(self, user_id: int, username: str) -> None:
        """Add a user to the database."""
        try:
            self.logger.info(f"Adding user {username} to the database...")
            self.cursor.execute("""
                INSERT INTO Users (id, username, created_at) VALUES (?, ?, ?)
                """, (user_id, username, datetime.now()))
            self.conn.commit()
            self.logger.info(f"User {username} ({user_id}) added to the database.")

        except Error as e:
            self.logger.error(f"Failed to add user {username} to the database: {e}")
            self.conn.rollback()
            return


    async def get_user(self, user_id: int, username: str) -> Optional[DiscordUserDataType]:
        """Get a user from the database."""
        try:
            self.logger.info(f"Getting user {user_id} from the database...")
            user: DiscordUserDataType = self.cursor.execute("""
                SELECT * FROM Users WHERE id = ?
                """, (user_id,)).fetchone()

            if not user:
                self.logger.info(f"User {user_id} not found in the database.")
                return None

            # Update username if it has changed
            if user["username"] != username:
                self.logger.info(f"Updating username for user {user_id} in the database...")
                self.cursor.execute("""
                    UPDATE Users SET username = ? WHERE id = ?
                    """, (username, user_id))
                self.conn.commit()
                user["username"] = username

            user_dict: Optional[DiscordUserDataType] = user

            self.logger.info(f"User {user_id} retrieved from the database.")
            return user_dict
        except Error as e:
            self.logger.error(f"Failed to get user {user_id} from the database: {e}")
            return None
