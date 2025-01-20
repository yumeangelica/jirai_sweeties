import discord
from discord.ext import commands
import certifi
import logging
import ssl
import asyncio
import json
import os

# Path to the bot configuration file
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "settings.json")

# Load the bot configuration from json
bot_config = None
with open(CONFIG_PATH, 'r') as f:
    bot_config = json.load(f)


class DiscordBot(commands.Bot):
    """Discord bot class to interact with the Discord API."""
    def __init__(self, store_manager):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True # Enable the members intent for member join events
        super().__init__(command_prefix='!', intents=intents)

        # Create SSL context with certifi
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        self.ssl_context.check_hostname = True

        self.store_manager = store_manager # Store manager instance
        self.logger = logging.getLogger("DiscordBot") # Logger instance for the bot with the name "DiscordBot"

        self.lock = asyncio.Lock() # Async lock to prevent concurrent message sending
        self.bot_config = bot_config # Bot configuration settings

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


    async def send_new_items(self, store_name_format: str, new_products: list) -> None:
        """Send new products to a specific Discord channel."""

        async with self.lock: # Ensure only one task can send messages at a time
            channel = discord.utils.get(self.get_all_channels(), name=self.bot_config['new_items_channel_name'])
            if not channel:
                self.logger.warning(f"Channel '{self.bot_config['new_items_channel_name']}' not found.")
                return

            if not new_products:
                return

            # Get the embed color from the configuration
            embed_color = self.bot_config.get('embed_color', (214, 140, 184))

            if isinstance(embed_color, list) and len(embed_color) == 3:
                embed_color = discord.Color.from_rgb(*embed_color)
            else:
                self.logger.warning("Invalid embed color in configuration, using default default color.")
                embed_color = discord.Color.from_rgb(214, 140, 184)  # Default color, muted pink

            # Create the embed message for section title
            embed = discord.Embed(
                title=f"New products from {store_name_format}!",
                description=f"Found {len(new_products)} new items",
                color=embed_color
            )

            # Send section title
            await channel.send(embed=embed)
            await asyncio.sleep(0.5)

            # Send each product as a separate message
            for product in new_products:
                name = product.get('name', 'No name available')
                product_url = product.get('product_url', '#')
                image_url = product.get('image_url', None)
                prices = product.get('prices', {})

                price_text = []
                if prices.get('JPY'):
                    price_text.append(f"¥{prices['JPY']:,.0f}")
                if prices.get('EUR'):
                    price_text.append(f"€{prices['EUR']:.2f}")

                price_str = " / ".join(price_text) if price_text else "No price available"

                embed = discord.Embed(
                    title=name,
                    description=f"💰 {price_str}\n🔗 [View product]({product_url})",
                    color=embed_color
                )

                if image_url:
                    embed.set_image(url=image_url)  # Set the product image

                await channel.send(embed=embed) # Send the message with the product details and image

                # Wait 0.5 sec between messages
                await asyncio.sleep(0.5)