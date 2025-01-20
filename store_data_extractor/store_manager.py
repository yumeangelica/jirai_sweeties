from datetime import datetime
from store_data_extractor.src.data_extractor import main_program
from store_data_extractor.src.store_database import StoreDatabase
import asyncio
import aiohttp
import logging
import os
import json

# Path to the stores configuration file
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "stores.json")

store_config = None
with open(CONFIG_PATH, 'r') as f:
    store_config = json.load(f)

SEMAPHORE = asyncio.Semaphore(3) # Limit the number of concurrent requests

class StoreManager:
    """Manage the stores and their data."""
    def __init__(self):
        self.stores = store_config
        self.session = None # aiohttp session
        self.logger = logging.getLogger("StoreManager")
        self.db = StoreDatabase()

    async def start_session(self) -> None:
        """Start a new session."""
        self.logger.info("Starting session...")
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def stop_session(self) -> None:
        """Close the session."""
        self.logger.info("Stopping session...")
        if self.session:
            await self.session.close()
            self.session = None
        await self.db.close_connection() # Close the database connection

    async def schedule_runner(self, discord_bot) -> None:
        """Manage store updates based on schedule."""
        await self.start_session()
        try:
            while True:
                await self.run_scheduled_tasks(discord_bot)
                await asyncio.sleep(60)  # Scheduling interval
        finally:
            await self.stop_session()
            await asyncio.sleep(0.1)
            logging.shutdown()


    async def run_scheduled_tasks(self, discord_bot) -> None:
        """Run the scheduled tasks for all stores."""
        tasks = []
        for store in self.stores:
            if await self.should_run_now(store):
                self.logger.info(f"Scheduling task for {store['name']}")
                tasks.append(asyncio.create_task(self.fetch_store_data(discord_bot, store)))

        # Run all tasks in parallel
        if tasks:
            await asyncio.gather(*tasks)

    async def should_run_now(self, store: dict) -> bool:
        """Check if the store should be updated now."""

        now = datetime.now()

        schedule = store["schedule"]
        minutes = schedule["minutes"]   # "*" not allowed
        hours = schedule["hours"]       # "*" allowed
        days = schedule["days"]         # "*" allowed
        months = schedule["months"]     # "*" allowed
        years = schedule["years"]       # "*" allowed

        if str(now.minute) not in map(str, minutes):
            return False

        if hours != "*" and str(now.hour) not in map(str, hours):
            return False

        if days != "*" and str(now.day) not in map(str, days):
            return False

        if months != "*" and str(now.month) not in map(str, months):
            return False

        if years != "*" and str(now.year) not in map(str, years):
            return False

        return True

    async def fetch_store_data(self, discord_bot, store: dict) -> None:
        """Fetch and process store data, then notify DiscordBot."""
        try:
            async with SEMAPHORE: # Limit the number of concurrent requests
                new_products = await main_program(self.session, store) # List of objects

                if new_products:
                    await discord_bot.send_new_items(store['name_format'], new_products)
        except Exception as e:
            self.logger.error(f"Error fetching data for {store['name']}: {e}")

    async def run_all_stores(self, discord_bot) -> None:
        """Fetch data for all stores."""
        for store in self.stores:
            await self.fetch_store_data(discord_bot, store)
