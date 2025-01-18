from dotenv import load_dotenv
import os
import asyncio
from store_data_extractor.store_manager import StoreManager
from utils.logger import configure_logger
import logging
from bot.discord_bot import DiscordBot


# Load .env file
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

async def main():
    configure_logger()
    logger = logging.getLogger("Main")

    logger.info("Starting application...")

    store_manager = StoreManager()

    bot = DiscordBot(store_manager=store_manager)

    try:
        store_task = asyncio.create_task(store_manager.schedule_runner(bot))
        logger.info("Starting store manager...")

        bot_task = asyncio.create_task(bot.start(BOT_TOKEN))
        logger.info("Starting bot...")

        # Let bot run with priority by awaiting it first
        await bot_task

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return
    finally:
        store_task.cancel()
