from dotenv import load_dotenv
import os
import sys
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
shutdown_event = asyncio.Event()

# Load .env file
load_dotenv()
BOT_TOKEN: Optional[str] = os.getenv('BOT_TOKEN')
if BOT_TOKEN is None:
    raise ValueError("No bot token provided in .env file.")

async def graceful_shutdown():
    """Handle graceful shutdown once."""
    if not shutdown_event.is_set():
        logger.info("Setting shutdown event...")
        shutdown_event.set()
        if store_manager:
            logger.info("Shutting down StoreManager...")
            await store_manager.graceful_shutdown()
            logger.info("StoreManager shutdown complete")

def signal_handler(signum, frame):
    """Handle termination signals by scheduling async handler."""
    logger.info(f"Received signal {signum}")

    try:
        loop = asyncio.get_running_loop()
        # Create task for graceful shutdown
        loop.create_task(graceful_shutdown())
    except RuntimeError:
        # If we're not in an event loop, create a new loop and run the shutdown
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(graceful_shutdown())
    finally:
        # Force exit after shutdown
        sys.exit(0)

async def main_run() -> None:
    configure_logger()

    if platform.system() != "Windows":
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting application...")
    global store_manager
    store_manager = StoreManager()

    bot: DiscordBot = DiscordBot()

    store_task = None
    try:
        store_task: Optional[Task[None]] = asyncio.create_task(store_manager.schedule_runner(bot))
        logger.info("Starting store manager...")

        bot_task: Task[None] = asyncio.create_task(bot.start(str(BOT_TOKEN)))
        logger.info("Starting bot...")

        # Let bot run with priority by awaiting it first
        await bot_task

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise
    finally:
        logger.info("Shutting down...")

        if store_task is not None and not store_task.cancelled():
            store_task.cancel()
            try:
                await store_task
            except asyncio.CancelledError:
                pass

        # Close the bot database connection
        await bot.close_database()

        await graceful_shutdown()

        sys.exit(1)
