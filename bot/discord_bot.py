import discord
from discord.ext import commands
import certifi
import logging
import ssl

class DiscordBot(commands.Bot):
    def __init__(self, store_manager):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True # Enable the members intent for member join events
        super().__init__(command_prefix='!', intents=intents)

        # Create SSL context with certifi
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        self.ssl_context.check_hostname = True

        self.store_manager = store_manager
        self.logger = logging.getLogger("DiscordBot")


    async def on_message(self, message: str) -> None:
        """Respond to messages that mention the bot."""
        if message.author == self.user:
            return

        bot_name = self.user.name.lower()

        if message.content.lower().startswith(f'{bot_name}:'):

            await message.channel.send(f"Hello {message.author.mention}! How can I help you today?")

        await self.process_commands(message)


    async def on_ready(self) -> None:
        """Log information when the bot is ready."""
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')

