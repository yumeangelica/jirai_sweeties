import asyncio
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from bot.discord_bot import DiscordBot


PRODUCTS = [
    {
        "id": 11,
        "name": "Product One",
        "product_url": "https://example.test/product-1",
        "image_url": None,
        "prices": {"JPY": 1000.0},
    },
    {
        "id": 12,
        "name": "Product Two",
        "product_url": "https://example.test/product-2",
        "image_url": None,
        "prices": {"JPY": 2000.0},
    },
]


class FakeStoreDatabase:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.individual_ids: list[int] = []
        self.batch_ids: list[list[int]] = []

    async def mark_product_as_sent(self, product_id: int) -> None:
        self.individual_ids.append(product_id)
        self.events.append(f"mark:{product_id}")

    async def mark_products_as_sent(self, product_ids: list[int]) -> None:
        self.batch_ids.append(product_ids)
        self.events.append(f"mark-batch:{','.join(map(str, product_ids))}")


class FakeTextChannel:
    def __init__(self, events: list[str], fail_on_send: int | None = None) -> None:
        self.name = "new-items"
        self.guild = SimpleNamespace(name="Test Guild")
        self.events = events
        self.fail_on_send = fail_on_send
        self.send_count = 0

    async def send(self, *, embed, file=None) -> None:
        self.send_count += 1
        event = "send:header" if self.send_count == 1 else f"send:product-{self.send_count - 1}"
        self.events.append(event)
        if self.send_count == self.fail_on_send:
            raise RuntimeError("synthetic Discord send failure")


def make_bot(database: FakeStoreDatabase, channel: FakeTextChannel, *, posting: bool):
    bot = object.__new__(DiscordBot)
    bot.lock = asyncio.Lock()
    bot.bot_settings = {
        "new_items_channel_name": "new-items",
        "post_store_updates": posting,
        "embed_color": [214, 140, 184],
        "welcome_channel_name": "general",
    }
    bot.logger = logging.getLogger("notification-test")
    bot.store_manager = SimpleNamespace(db=database)
    bot.wait_until_ready = AsyncMock()
    bot.get_all_channels = lambda: [channel]
    bot.get_embed_color = lambda: discord.Color.from_rgb(214, 140, 184)
    return bot


class DiscordNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_messages_are_marked_only_after_send(self) -> None:
        events: list[str] = []
        database = FakeStoreDatabase(events)
        channel = FakeTextChannel(events)
        bot = make_bot(database, channel, posting=True)

        with (
            patch.object(discord, "TextChannel", FakeTextChannel),
            patch("bot.discord_bot.asyncio.sleep", new=AsyncMock()),
        ):
            await DiscordBot.send_new_items(bot, "Test Store", PRODUCTS, "new")

        self.assertEqual(
            events,
            ["send:header", "send:product-1", "mark:11", "send:product-2", "mark:12"],
        )

    async def test_failed_message_is_not_marked_as_sent(self) -> None:
        events: list[str] = []
        database = FakeStoreDatabase(events)
        channel = FakeTextChannel(events, fail_on_send=2)
        bot = make_bot(database, channel, posting=True)

        with (
            patch.object(discord, "TextChannel", FakeTextChannel),
            patch("bot.discord_bot.asyncio.sleep", new=AsyncMock()),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic Discord send failure"):
                await DiscordBot.send_new_items(bot, "Test Store", PRODUCTS, "new")

        self.assertEqual(events, ["send:header", "send:product-1"])
        self.assertEqual(database.individual_ids, [])

    async def test_silent_mode_marks_all_products_in_one_batch(self) -> None:
        events: list[str] = []
        database = FakeStoreDatabase(events)
        channel = FakeTextChannel(events)
        bot = make_bot(database, channel, posting=False)
        bot.get_all_channels = lambda: (_ for _ in ()).throw(
            AssertionError("Discord channel lookup must not run in silent mode")
        )

        await DiscordBot.send_new_items(bot, "Test Store", PRODUCTS, "new")

        self.assertEqual(database.batch_ids, [[11, 12]])
        self.assertEqual(database.individual_ids, [])
        self.assertEqual(events, ["mark-batch:11,12"])


if __name__ == "__main__":
    unittest.main()
