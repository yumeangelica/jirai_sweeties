import discord
from discord.ext import commands
import certifi
import logging
import ssl
import asyncio
import json
import os
import random
from bot.discord_database import DiscordDatabase

# Path to the config directory
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config")

# Path to the bot setting file
SETTINGS_FILE_PATH = os.path.join(CONFIG_PATH, "settings.json")

# Path to the welcome messages file
WELCOME_MESSAGES_FILE_PATH = os.path.join(CONFIG_PATH, "welcome_messages.txt")

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
        self.discord_db = DiscordDatabase() # Discord database instance
        self.logger = logging.getLogger("DiscordBot") # Logger instance for the bot with the name "DiscordBot"

        self.lock = asyncio.Lock() # Async lock to prevent concurrent message sending
        self.bot_settings = None # Bot configuration settings
        with open(SETTINGS_FILE_PATH, 'r') as f:
            self.bot_settings = json.load(f)


    async def close_database(self) -> None:
        """Close the database connection."""
        await self.discord_db.close_connection()


    async def on_message(self, message: str) -> None:
        """Respond to messages that mention the bot."""
        if message.author == self.user:
            return

        bot_name = self.user.name.lower()

        if message.content.lower().startswith(f'{bot_name}:'):
            await message.channel.send(f"Hello {message.author.mention}! How can I help you today?")


        if message.content.lower().startswith("!help"):
            await self.show_help(message)
            return

        await self.process_commands(message)


    async def on_ready(self) -> None:
        """Log information when the bot is ready."""
        await self.change_presence(
            status=discord.Status.online,  # Set the bot status to online
            activity=discord.CustomActivity(name="Welcoming new members and checking for new products from stores") # Set the bot activity
        )

        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')



    def get_embed_color(self):
        """Fetch and validate embed color from bot settings."""
        embed_color = self.bot_settings.get('embed_color', (214, 140, 184))
        if isinstance(embed_color, list) and len(embed_color) == 3:
            return discord.Color.from_rgb(*embed_color)
        else:
            self.logger.warning("Invalid embed color in configuration, using default muted pink.")
            return discord.Color.from_rgb(214, 140, 184)  # Default color



    async def send_new_items(self, store_name_format: str, new_products: list) -> None:
        """Send new products to a specific Discord channel."""
        async with self.lock: # Ensure only one task can send messages at a time

            new_items_channel = None # Channel to send new items

            for channel in self.get_all_channels():
                if isinstance(channel, discord.TextChannel) and self.bot_settings['new_items_channel_name'].lower() in channel.name.lower():
                    new_items_channel = channel
                    break

            if not new_items_channel:
                self.logger.warning(f"Channel '{self.bot_settings['new_items_channel_name']}' not found.")
                return

            if not new_products:
                return


            # Fetch and validate embed color from settings
            embed_color = self.get_embed_color()

            # Create the embed message for section title
            embed = discord.Embed(
                title=f"New products from {store_name_format}!",
                description=f"Found {len(new_products)} new items",
                color=embed_color
            )

            # Send section title
            await new_items_channel.send(embed=embed)
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

                await new_items_channel.send(embed=embed) # Send the message with the product details and image

                # Wait 0.5 sec between messages
                await asyncio.sleep(0.5)


    async def load_welcome_messages(self) -> list[str]:
        """Methdod to load welcome messages from a text file."""
        try:
            with open(WELCOME_MESSAGES_FILE_PATH, 'r', encoding='utf-8') as file:
                return [line.strip() for line in file if line.strip()] # Returns a list of non-empty lines
        except FileNotFoundError:
            self.logger.error(f"Welcome messages file not found: {WELCOME_MESSAGES_FILE_PATH}")
            return []
        except Exception as e:
            self.logger.error(f"An error occurred while loading welcome messages: {e}")
            return []


    async def on_member_join(self, member: discord.Member) -> None:
        """Send a welcome message when a new member joins the server."""
        guild = member.guild
        welcome_channel = None

        user = await self.discord_db.get_user(member.id, member.name) # Check if user is already in the database

        if not user:
            await self.discord_db.add_user(member.id, member.name) # Add user to the database if not found

        # Load welcome messages list from the file
        welcome_messages = await self.load_welcome_messages()

        if not welcome_messages or len(welcome_messages) == 0:
            self.logger.warning("No welcome messages found from the file.")
            welcome_messages = [f"Welcome to the Jirai Sweeties server, {member.mention}! We're glad to have you here!"]

        for channel in guild.text_channels:
            if self.bot_settings["welcome_channel_name"].lower() in channel.name.lower():
                welcome_channel = channel
                break

        if welcome_channel:
            try:
                if user: # In case of returning user
                    await welcome_channel.send(f"Welcome back, {member.mention}! We're glad to see you again!")
                    return
                # Select a random welcome message and format it with the member mention
                base_message = random.choice(welcome_messages)
                welcome_message = base_message.format(member=member.mention)
                await asyncio.sleep(3)
                await welcome_channel.send(welcome_message)
            except discord.Forbidden:
                self.logger.warning(f"Bot does not have permission to send messages in the channel: {welcome_channel.name}")
            except Exception as e:
                self.logger.error(f"An error occurred while sending a welcome message: {e}")
        else:
            self.logger.warning("Welcome channel not found.")


    async def show_help(self, message: discord.Message) -> None:
        """Send a detailed help message to the user with commands and bot features."""

        # Fetch and validate embed color from settings
        embed_color = self.get_embed_color()

        # Create the base embed for the help message
        embed = discord.Embed(
            title="Pien-chan bot - Commands & Features",
            description="Here are the commands and features you can use to interact with me:",
            color=embed_color
        )

        # Define available commands and their descriptions
        commands = {
            "!help": "Shows this help message."
        }

        # Define key bot features
        features = {
            "Real-time Updates": "Get notified about new items available in stores.",
            "Welcome Messages": "Friendly messages for new members joining the server.",
            "Custom Features": "I'm constantly learning new things, so stay tuned for updates!"
        }

        # Add commands to the embed
        embed.add_field(
            name="Commands:",
            value="\n".join([f"**{cmd}**: {desc}" for cmd, desc in commands.items()]),
            inline=False
        )

        # Add a visual separator with hearts
        embed.add_field(
            name="\u200B",  # Invisible field title
            value="♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡ ⋆ ♡",
            inline=False
        )

        # Add features to the embed
        embed.add_field(
            name="Features:",
            value="\n".join([f"**{feature}**: {desc}" for feature, desc in features.items()]),
            inline=False
        )

        # Add final note to the embed
        embed.set_footer(text="More commands and features coming soon! Stay tuned and send your suggestions to the suggestions channel. 💖")

        # Send the embed as a message
        await message.channel.send(embed=embed)
