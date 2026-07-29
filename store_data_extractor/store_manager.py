from datetime import datetime
import asyncio
import logging
import os
import json
from store_data_extractor.src.data_extractor import main_program
from bot.discord_bot import DiscordBot
from typing import Dict, Optional, List
from store_data_extractor.store_types import StoreConfigDataType, ProductDataType
from store_data_extractor.src.http_client import HttpClientPool

# Path to the stores configuration file
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "stores.json")

store_config: Optional[List[StoreConfigDataType]] = None
with open(CONFIG_PATH, 'r') as f:
    store_config = json.load(f)

SEMAPHORE = asyncio.Semaphore(3) # Limit the number of concurrent requests

# Import the global instance instead of the class
from store_data_extractor.src.user_agent_manager import user_agent_manager

class StoreManager:
    """Manage the stores and their data."""
    def __init__(self) -> None:
        self.stores: Optional[List[StoreConfigDataType]] = store_config
        self.http_clients = HttpClientPool(max_clients=3)
        self.logger = logging.getLogger("StoreManager")
        from store_data_extractor.src.store_database import StoreDatabase
        self.db: StoreDatabase = StoreDatabase()
        self.user_agent_manager = user_agent_manager # only one instance of UserAgentManager, prevent multiple instances
        self._shutdown_event = asyncio.Event() # Event to signal shutdown
        self._shutdown_started = False
        self._stopped = False
        self.current_tasks: List[asyncio.Task] = []
        self._store_locks: Dict[str, asyncio.Lock] = {} # Prevent concurrent runs for the same store
        self._last_run_slots: Dict[str, str] = {}
        self._background_batches: set[asyncio.Task[None]] = set()

    def get_store_lock(self, store_name: str) -> asyncio.Lock:
        """Get (or create) the lock that serializes runs for a single store."""
        if store_name not in self._store_locks:
            self._store_locks[store_name] = asyncio.Lock()
        return self._store_locks[store_name]

    async def start_session(self) -> None:
        """Start a new session."""
        self.logger.info("Starting session...")
        self._stopped = False
        await self.http_clients.start(self.stores or [])


    async def stop_session(self) -> None:
        """Close the session."""
        if self._stopped:
            return

        self._stopped = True
        self.logger.info("Stopping session...")
        await self.http_clients.close()
        await self.db.close_connection() # Close the database connection


    async def schedule_runner(self, discord_bot: DiscordBot) -> None:
        """Manage store updates based on schedule."""
        await self.start_session()
        try:
            await self.run_startup_tasks(discord_bot)
            while not self._shutdown_event.is_set():
                scheduled_count = await self.run_scheduled_tasks(discord_bot)
                if scheduled_count == 0:
                    self.logger.debug("No stores scheduled at current time.")
                try:
                    now = datetime.now()
                    seconds_to_next_minute = max(
                        0.05,
                        60 - now.second - (now.microsecond / 1_000_000),
                    )
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=seconds_to_next_minute,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            self.logger.warning("Schedule runner task was cancelled.")
            raise
        except Exception as e:
            self.logger.exception(f"Error in schedule runner: {e}")
            raise
        finally:
            await self.graceful_shutdown()

    @staticmethod
    def get_run_slot(now: datetime) -> str:
        return now.strftime("%Y%m%d%H%M")

    async def run_startup_tasks(
        self,
        discord_bot: DiscordBot,
        now: Optional[datetime] = None,
    ) -> None:
        """Run stores configured to fetch immediately when the process starts."""
        current_time = now or datetime.now()
        run_slot = self.get_run_slot(current_time)
        tasks = []
        for store in self.stores or []:
            if store.get("run_on_start", False):
                self.logger.info(f"Running startup task for {store['name']}")
                self._last_run_slots[store["name"]] = run_slot
                tasks.append(asyncio.create_task(self.fetch_store_data(discord_bot, store)))

        try:
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            if tasks:
                await self.user_agent_manager.save_index_after_task()

    async def run_scheduled_tasks(
        self,
        discord_bot: DiscordBot,
        now: Optional[datetime] = None,
    ) -> int:
        """Run the scheduled tasks for all stores."""
        current_time = now or datetime.now()
        run_slot = self.get_run_slot(current_time)
        stores_to_run: List[StoreConfigDataType] = []
        for store in self.stores or []:
            store_name = store["name"]
            if not self.should_run_now(store, current_time):
                continue
            if self._last_run_slots.get(store_name) == run_slot:
                self.logger.debug(f"Store {store_name} already ran in slot {run_slot}.")
                continue
            if self.get_store_lock(store_name).locked():
                self.logger.warning(f"Store {store_name} is still running; skipping slot {run_slot}.")
                continue

            self._last_run_slots[store_name] = run_slot
            self.logger.info(f"Scheduling task for {store_name}")
            stores_to_run.append(store)

        if stores_to_run:
            batch = asyncio.create_task(
                self._run_scheduled_batch(discord_bot, stores_to_run)
            )
            self._background_batches.add(batch)
            batch.add_done_callback(self._background_batches.discard)

        return len(stores_to_run)

    async def _run_scheduled_batch(
        self,
        discord_bot: DiscordBot,
        stores: List[StoreConfigDataType],
    ) -> None:
        try:
            await asyncio.gather(
                *(self.fetch_store_data(discord_bot, store) for store in stores)
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.exception(f"Unexpected scheduled batch failure: {e}")
        finally:
            try:
                await self.user_agent_manager.save_index_after_task()
            except Exception as e:
                self.logger.error(f"Failed to save user agent index: {e}")

    async def wait_for_background_batches(self) -> None:
        """Wait for currently scheduled batches; used by shutdown and tests."""
        batches = list(self._background_batches)
        if batches:
            await asyncio.gather(*batches)


    def should_run_now(
        self,
        store: StoreConfigDataType,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check if the store should be updated now."""
        current_time = now or datetime.now()

        schedule = store["schedule"]
        minutes = schedule["minutes"]   # "*" not allowed
        hours = schedule["hours"]       # "*" allowed
        days = schedule["days"]         # "*" allowed
        months = schedule["months"]     # "*" allowed
        years = schedule["years"]       # "*" allowed

        if str(current_time.minute) not in map(str, minutes):
            return False

        if hours != "*" and str(current_time.hour) not in map(str, hours):
            return False

        if days != "*" and str(current_time.day) not in map(str, days):
            return False

        if months != "*" and str(current_time.month) not in map(str, months):
            return False

        if years != "*" and str(current_time.year) not in map(str, years):
            return False

        return True


    async def fetch_unsent_products(self, store_name: str) -> Optional[List[ProductDataType]]:
        """Fetch unsent products for a store from the database."""
        products = await self.db.get_unsent_products(store_name)
        if not products or len(products) == 0:
            return None
        return products

    def should_post_store_updates(self, discord_bot: DiscordBot) -> bool:
        """Check whether store updates should be posted to Discord."""
        bot_settings = getattr(discord_bot, "bot_settings", None)
        if not bot_settings:
            return True
        return bot_settings.get("post_store_updates", True)


    async def fetch_store_data(self, discord_bot: DiscordBot, store: StoreConfigDataType) -> None:
        """Fetch and process store data with improved error handling."""
        async with self.get_store_lock(store['name']):
            await self._fetch_store_data_locked(discord_bot, store)

    async def _fetch_store_data_locked(self, discord_bot: DiscordBot, store: StoreConfigDataType) -> None:
        """Fetch and process store data; caller must hold the store lock."""
        task = asyncio.current_task()
        if task:
            self.current_tasks.append(task)

        try:
            try:
                unsent_products = await self.fetch_unsent_products(store['name'])
                if unsent_products is not None:
                    await discord_bot.send_new_items(store['name_format'], unsent_products, "unsent")
            except Exception as e:
                self.logger.error(f"Error sending unsent products for {store['name']}: {e}")

            async with SEMAPHORE:
                result = await main_program(self.http_clients, store, self.db)
            new_products, updated_products = result

            if new_products:
                await discord_bot.send_new_items(store['name_format'], new_products, "new")
            if updated_products:
                await discord_bot.send_new_items(store['name_format'], updated_products, "updated")

        except asyncio.CancelledError:
            self.logger.warning(f"Task cancelled for {store['name']}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching data for {store['name']}: {e}")
        finally:
            if task and task in self.current_tasks:
                self.current_tasks.remove(task)

    async def graceful_shutdown(self) -> None:
        """Initiate graceful shutdown of all operations."""
        if self._shutdown_started:
            return

        self._shutdown_started = True
        self._shutdown_event.set()
        self.logger.info("Initiating graceful shutdown...")

        background_batches = list(self._background_batches)
        for batch in background_batches:
            if not batch.done():
                batch.cancel()
        if background_batches:
            await asyncio.gather(*background_batches, return_exceptions=True)

        # Cancel and wait for current tasks to complete
        current_task = asyncio.current_task()
        for task in list(self.current_tasks):
            if task is current_task:
                continue
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        try:
            await self.user_agent_manager.save_index_after_task()
        except Exception as e:
            self.logger.error(f"Failed to save user agent index during shutdown: {e}")

        await self.stop_session()


    async def run_all_stores(self, discord_bot: DiscordBot) -> None:
        """Fetch data for all stores."""
        try:
            for store in self.stores or []:
                await self.fetch_store_data(discord_bot, store)
        finally:
            await self.user_agent_manager.save_index_after_task()
