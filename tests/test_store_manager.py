import asyncio
import logging
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from store_data_extractor.store_manager import StoreManager


STORE = {
    "name": "test_store",
    "name_format": "Test Store",
    "options": {
        "base_url": "https://example.test",
        "site_main_url": "https://example.test",
        "item_container_selector": "//article",
        "item_name_selector": ".//h2/text()",
        "item_price_selectors": [],
        "item_link_selector": ".//a/@href",
        "item_image_selector": ".//img/@src",
        "sold_out_selector": ".sold-out",
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
    "run_on_start": True,
}


def make_manager() -> StoreManager:
    manager = object.__new__(StoreManager)
    manager.stores = [STORE]
    manager.logger = logging.getLogger("store-manager-test")
    manager._store_locks = {}
    manager._last_run_slots = {}
    manager._background_batches = set()
    manager.fetch_store_data = AsyncMock()
    manager.user_agent_manager = SimpleNamespace(save_index_after_task=AsyncMock())
    return manager


class StoreManagerScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_run_prevents_same_minute_scheduled_duplicate(self) -> None:
        manager = make_manager()
        bot = SimpleNamespace()
        scheduled_time = datetime(2026, 7, 14, 12, 5, 15)

        await manager.run_startup_tasks(bot, now=scheduled_time)
        scheduled_count = await manager.run_scheduled_tasks(bot, now=scheduled_time)

        self.assertEqual(scheduled_count, 0)
        self.assertEqual(manager.fetch_store_data.await_count, 1)
        self.assertEqual(manager.user_agent_manager.save_index_after_task.await_count, 1)

    async def test_scheduled_store_runs_once_per_minute_slot(self) -> None:
        manager = make_manager()
        bot = SimpleNamespace()
        first_time = datetime(2026, 7, 14, 12, 5, 0)

        first_count = await manager.run_scheduled_tasks(bot, now=first_time)
        await manager.wait_for_background_batches()
        duplicate_count = await manager.run_scheduled_tasks(
            bot,
            now=first_time.replace(second=45),
        )

        self.assertEqual(first_count, 1)
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(manager.fetch_store_data.await_count, 1)
        self.assertEqual(manager.user_agent_manager.save_index_after_task.await_count, 1)

    async def test_locked_store_is_not_queued_for_later(self) -> None:
        manager = make_manager()
        bot = SimpleNamespace()
        store_lock = manager.get_store_lock(STORE["name"])

        await store_lock.acquire()
        try:
            scheduled_count = await manager.run_scheduled_tasks(
                bot,
                now=datetime(2026, 7, 14, 12, 5, 0),
            )
        finally:
            store_lock.release()

        self.assertEqual(scheduled_count, 0)
        manager.fetch_store_data.assert_not_awaited()

    async def test_long_running_store_does_not_block_future_schedule_checks(self) -> None:
        manager = make_manager()
        bot = SimpleNamespace()
        started = asyncio.Event()
        release = asyncio.Event()

        async def long_fetch(discord_bot, store) -> None:
            async with manager.get_store_lock(store["name"]):
                started.set()
                await release.wait()

        manager.fetch_store_data = AsyncMock(side_effect=long_fetch)

        first_count = await manager.run_scheduled_tasks(
            bot,
            now=datetime(2026, 7, 14, 12, 5, 0),
        )
        await started.wait()
        next_count = await manager.run_scheduled_tasks(
            bot,
            now=datetime(2026, 7, 14, 13, 5, 0),
        )
        release.set()
        await manager.wait_for_background_batches()

        self.assertEqual(first_count, 1)
        self.assertEqual(next_count, 0)
        self.assertEqual(manager.fetch_store_data.await_count, 1)

    def test_schedule_matching_is_synchronous_and_exact(self) -> None:
        manager = make_manager()

        self.assertTrue(manager.should_run_now(STORE, datetime(2026, 7, 14, 12, 5)))
        self.assertFalse(manager.should_run_now(STORE, datetime(2026, 7, 14, 12, 6)))


if __name__ == "__main__":
    unittest.main()
