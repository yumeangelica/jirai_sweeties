from dotenv import load_dotenv
import os
import asyncio
import signal
import platform
from asyncio import Task
from store_data_extractor.store_manager import StoreManager

from utils.logger import configure_logger

import logging

from bot.discord_bot import DiscordBot

from typing import Optional

logger: logging.Logger = logging.getLogger("Main")
store_manager: Optional[StoreManager] = None
bot: Optional[DiscordBot] = None
shutdown_event = asyncio.Event()
shutdown_started = False

# Load .env file
load_dotenv()
BOT_TOKEN: Optional[str] = os.getenv('BOT_TOKEN')
if BOT_TOKEN is None:
    raise ValueError("No bot token provided in .env file.")

async def graceful_shutdown():
    """Handle graceful shutdown once."""
    global shutdown_started
    if shutdown_started:
        return

    shutdown_started = True
    logger.info("Setting shutdown event...")
    if not shutdown_event.is_set():
        shutdown_event.set()

    if store_manager:
        logger.info("Shutting down StoreManager...")
        await store_manager.graceful_shutdown()
        logger.info("StoreManager shutdown complete")

    if bot and not bot.is_closed():
        logger.info("Closing Discord bot...")
        await bot.close()
        logger.info("Discord bot closed")

def signal_handler(signum, frame):
    """Handle termination signals by scheduling async handler."""
    logger.info(f"Received signal {signum}")
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(shutdown_event.set)
    except RuntimeError:
        shutdown_event.set()

async def main_run() -> None:
    configure_logger()

    if platform.system() != "Windows":
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler, signal.SIGINT, None)
            loop.add_signal_handler(signal.SIGTERM, signal_handler, signal.SIGTERM, None)
        except NotImplementedError:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting application...")
    global store_manager, bot
    store_manager = StoreManager()

    bot = DiscordBot(store_manager=store_manager)

    store_task: Optional[Task[None]] = None
    bot_task: Optional[Task[None]] = None
    shutdown_task: Optional[Task[bool]] = None
    try:
        store_task = asyncio.create_task(store_manager.schedule_runner(bot))
        logger.info("Starting store manager...")

        bot_task = asyncio.create_task(bot.start(str(BOT_TOKEN)))
        logger.info("Starting bot...")

        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, _ = await asyncio.wait(
            {bot_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        if bot_task in done:
            await bot_task
        else:
            logger.info("Shutdown requested.")

    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
        await graceful_shutdown()
        raise
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise
    finally:
        logger.info("Shutting down...")

        await graceful_shutdown()

        if shutdown_task is not None and not shutdown_task.done():
            shutdown_task.cancel()

        if bot_task is not None and not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass

        if store_task is not None and not store_task.done():
            store_task.cancel()
            try:
                await store_task
            except asyncio.CancelledError:
                pass

        if bot is not None:
            await bot.close_database()
