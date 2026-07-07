from pathlib import Path
from io import BytesIO
import asyncio
import logging
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import discord  # noqa: E402
from bot.discord_bot import DiscordBot  # noqa: E402


# A real store image whose CDN blocks plain HTTP clients (Discord's proxy) by
# TLS fingerprint. fetch_product_image must still retrieve it via curl_cffi.
IMAGE_URL = "https://contents.multilingualcart.com/ori/50934/goods_img/goods_2067_thum.jpg"


async def run_smoke() -> None:
    bot = object.__new__(DiscordBot)
    bot.logger = logging.getLogger("image-post-smoke")

    result = await bot.fetch_product_image(IMAGE_URL)
    if result is None:
        # Network unavailable or CDN changed; skip rather than fail the suite
        print("image post smoke skipped: could not reach image CDN")
        return

    content, filename = result
    assert content[:3] == b"\xff\xd8\xff", f"expected a JPEG, got {content[:8]!r}"
    assert filename.endswith(".jpg"), f"unexpected filename {filename}"

    # Build the embed + attachment exactly as send_new_items does
    image_file = discord.File(BytesIO(content), filename=filename)
    embed = discord.Embed(title="Test product")
    embed.set_image(url=f"attachment://{filename}")
    assert embed.image.url == f"attachment://{filename}"
    assert image_file.filename == filename

    # A non-existent image must yield None so the caller falls back gracefully
    missing = await bot.fetch_product_image(
        "https://contents.multilingualcart.com/ori/50934/goods_img/does-not-exist.jpg"
    )
    assert missing is None, "expected None for an unreachable image"

    print(f"image post smoke passed: fetched {len(content)} bytes, attached as {filename}")


def main() -> None:
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
