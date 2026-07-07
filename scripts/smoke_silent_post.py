from pathlib import Path
from types import SimpleNamespace
import asyncio
import logging
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bot.discord_bot import DiscordBot  # noqa: E402


class FakeStoreDatabase:
    def __init__(self) -> None:
        self.sent_ids: list[int] = []

    async def mark_product_as_sent(self, product_id: int) -> None:
        self.sent_ids.append(product_id)


async def run_smoke() -> None:
    fake_db = FakeStoreDatabase()
    bot = object.__new__(DiscordBot)
    bot.lock = asyncio.Lock()
    bot.bot_settings = {
        "new_items_channel_name": "developer",
        "post_store_updates": False,
        "embed_color": [214, 140, 184],
        "welcome_channel_name": "general",
    }
    bot.logger = logging.getLogger("silent-post-smoke")
    bot.store_manager = SimpleNamespace(db=fake_db)
    bot.get_all_channels = lambda: (_ for _ in ()).throw(
        AssertionError("Discord channel lookup should not run")
    )

    await DiscordBot.send_new_items(
        bot,
        "Liz Lisa",
        [
            {
                "id": 123,
                "name": "Test product",
                "product_url": "https://example.com/product",
                "image_url": "https://example.com/image.jpg",
                "prices": {"JPY": 1000.0},
            }
        ],
        "new",
    )

    if fake_db.sent_ids != [123]:
        raise RuntimeError(f"Expected product 123 to be marked sent, got {fake_db.sent_ids}")

    print(f"silent post smoke passed: marked sent ids {fake_db.sent_ids}")


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
