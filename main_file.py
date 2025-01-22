from dotenv import load_dotenv
import os
import sys
import asyncio
from asyncio import Task
from store_data_extractor.store_manager import StoreManager

from utils.logger import configure_logger

import logging

from bot.discord_bot import DiscordBot

from typing import Optional


# Load .env file
load_dotenv()
BOT_TOKEN: Optional[str] = os.getenv('BOT_TOKEN')
if BOT_TOKEN is None:
    raise ValueError("No bot token provided in .env file.")

async def main_run() -> None:
    configure_logger()
    logger: logging.Logger = logging.getLogger("Main")

    logger.info("Starting application...")

    store_manager: StoreManager = StoreManager()

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

        # Close the bot database connection
        await bot.close_database()
