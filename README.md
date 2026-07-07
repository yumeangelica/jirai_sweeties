# Jirai sweeties discord bot

A custom Discord bot designed for the Jirai sweeties server, combining chat functionality with automated store monitoring and real-time notifications for server members.

## Project Information

- **Version**: 1.9.0
- **Author**: [yumeangelica](https://github.com/yumeangelica)
- **License**: [CC BY-NC-ND 4.0](LICENSE.txt)
- **Repository**: [Jirai sweeties](https://github.com/yumeangelica/jirai_sweeties)

## Project Overview

This project consists of two main components:

### 1. Discord Bot

- Custom chat commands and interactions
- Integration with store monitoring system
- Real-time notifications for server members

### 2. Store Data Extractor

- Automated monitoring of specified online stores
- Product tracking and price change detection
- New item notifications
- Database storage for historical data

### Deployment Environment

The bot is containerized using Docker and is intended to run on a Raspberry Pi with 64-bit Linux.

The current Docker runtime is `python:3.14-alpine`. The scraper uses `curl_cffi`, which works in the tested `linux/arm64` image but does not currently build for `linux/arm/v7`. For Raspberry Pi 3 deployments, use a 64-bit OS and confirm the device reports `aarch64` with:

```bash
uname -m
```

## Technical Implementation

### Project Structure

```
jirai_sweeties/
├── bot/
│   ├── config/                         # Configuration files for Discord bot
│   │   ├── settings.json               # Bot settings
│   │   └── welcome_messages.txt        # Welcome message templates
│   ├── discord_bot.py                  # Main Discord bot logic
│   ├── discord_database.py             # Database handling for Discord data
│   └── discord_types.py                # Type definitions for Discord bot
├── data/
│   ├── discord_db.sqlite               # SQLite database for Discord bot
│   └── store_db.sqlite                 # SQLite database for store data
├── store_data_extractor/
│   ├── config/                         # Configuration files for store data extractor
│   │   ├── last_user_agent_index.txt   # User agent index tracking
│   │   ├── stores.json                 # Store configurations
│   │   └── user_agents.txt             # List of user agents
│   ├── src/                            # Core functionality for data extraction
│   │   ├── user_agent_manager.py       # Helper for managing user agents
│   │   ├── data_extractor.py           # Data extraction logic
│   │   └── store_database.py           # Database logic for stores
│   ├── store_manager.py                # Store monitor entry point
│   └── store_types.py                  # Type definitions for store data extractor
├── utils/
│   ├── helpers.py                      # Helper functions for data directories
│   └── logger.py                       # Logging functionality
├── venv/                               # Python virtual environment
├── .deployment                         # Deployment configuration
├── .dockerignore                       # Docker ignore file
├── .env                                # Environment variables
├── .gitignore                          # Git ignore file
├── Dockerfile                          # Docker configuration
├── LICENSE.txt                         # Project license
├── main_file.py                        # Main script file
├── README.md                           # Project documentation
├── requirements.txt                    # Python dependencies
└── run.py                              # Discord bot entry point
```

### Required Configuration Files

The project needs these configuration files in store_data_extractor/config/:

#### stores.json (required)

- Store configurations and monitoring schedules. Determines which stores to monitor and how often.
- Must be created manually
- Defines store URLs, HTML selectors, and update intervals

Structure:
stores.json

```json
[
  {
    "name": "store_name",
    "name_format": "Formatted Store Name",
    "run_on_start": true,
    "options": {
      "base_url": "base_url_for_data_extraction",
      "site_main_url": "main_site_url",
      "item_container_selector": "HTML_selector_for_item_containers",
      "item_name_selector": "HTML_selector_for_item_names",
      "item_price_selectors": [
        {
          "currency": "currency_code",
          "selector": "HTML_selector_for_price"
        }
      ],
      "item_link_selector": "HTML_selector_for_item_links",
      "item_image_selector": "HTML_selector_for_item_images",
      "sold_out_selector": "HTML_selector_for_sold_out_items",
      "next_page_selector": "HTML_selector_for_next_page",
      "next_page_selector_text": "Text_for_next_page_element",
      "next_page_attribute": "attribute_containing_next_page_url",
      "delay_between_requests": "time_in_seconds_between_requests",
      "encoding": "character_encoding_used",
      "fetch_backend": "curl_cffi"
    },
    "schedule": {
      "minutes": "list_of_minutes_for_execution",
      "hours": "list_of_hours_or_*",
      "days": "list_of_days_or_*",
      "months": "list_of_months_or_*",
      "years": "list_of_years_or_*"
    }
  }
]
```

settings.json

```json
{
  "new_items_channel_name": "channel_name_for_new_items",
  "post_store_updates": true,
  "embed_color": "list of rgb values in format [R, G, B]",
  "welcome_channel_name": "channel_name_for_welcome_messages"
}
```

#### stores.json (required)
Explanation of the fields in the stores.json file:
- **name**: Unique identifier for the store.
- **name_format**: User-friendly name for the store.
- **run_on_start**: Optional. Runs the store fetch once when the process starts. Useful for backfills.
- **options**: Configuration options for data extraction.
  - **base_url**: Starting URL for extracting data.
  - **site_main_url**: Main website URL.
  - **item_container_selector**: HTML selector for locating items.
  - **item_name_selector**: Selector for item names.
  - **item_price_selectors**: List of price selectors.
    - **currency**: Currency type (e.g., EUR, JPY).
    - **selector**: HTML selector for price.
  - **item_link_selector**: Selector for item links.
  - **item_image_selector**: Selector for item images.
  - **sold_out_selector**: Selector to identify sold-out items.
  - **next_page_selector**: Selector for pagination element.
  - **next_page_selector_text**: Text identifying the next page link.
  - **next_page_attribute**: Attribute containing the next page URL.
  - **delay_between_requests**: Delay (in seconds) between requests.
  - **encoding**: Website's character encoding.
  - **fetch_backend**: Optional. `auto`, `aiohttp`, or `curl_cffi`. Use `curl_cffi` for sites that block normal HTTP clients.
  - **request_headers**: Optional. Additional HTTP headers to merge into scraper requests.
  - **proxy_url**: Optional. Proxy URL for scraper requests.
  - **curl_impersonate**: Optional. Browser profile for `curl_cffi`; defaults to `chrome`.
  - **request_timeout**: Optional. Request timeout in seconds for `curl_cffi`; defaults to `30`.
- **schedule**: Monitoring schedule.
  - **minutes**: Minute intervals.
  - **hours**: Hour intervals or `*` for every hour.
  - **days**: Day intervals or `*` for every day.
  - **months**: Month intervals or `*` for every month.
  - **years**: Year intervals or `*` for every year.

#### settings.json (required)
Explanation of the fields in the settings.json file:
- **new_items_channel_name**: Name of the channel where new items will be posted.
- **post_store_updates**: Whether store update notifications should be posted to Discord. Defaults to `true` when omitted. Set to `false` for silent backfill/test runs; products are still marked as sent.
- **embed_color**: RGB color for embedded messages (format: [R, G, B]).
- **welcome_channel_name**: Name of the channel for welcome messages.

### Silent Store Backfill

Use silent backfill mode when testing scraper changes or filling the store database without posting product embeds to Discord.

Set this in `bot/config/settings.json`:

```json
{
  "post_store_updates": false
}
```

When `post_store_updates` is `false`, store products are still saved to SQLite and marked as sent. This prevents a backlog from being posted later when Discord posting is enabled again.

In addition, the very first fetch for a store (an empty or fresh `store_db.sqlite`) always inserts products as already sent, regardless of `post_store_updates`. A wiped database can therefore never flood the Discord channel with hundreds of old products — only products that appear after the initial fetch are posted.

Set `run_on_start` to `true` in `store_data_extractor/config/stores.json` when the store should be fetched immediately on startup.

#### user_agents.txt (required)

- List of browser user agents for web data extraction
- Must be created manually
- One user agent per line
- Used to prevent request blocking

#### last_user_agent_index.txt (auto-generated)

- Tracks the current user agent rotation
- Created automatically by the system
- Do not modify manually

### Product images

Product notifications include the item image. The store's image CDN blocks plain HTTP clients (including Discord's own image proxy) by TLS fingerprint, so a direct image URL in an embed renders empty. The bot therefore downloads each image with a browser impersonation (`curl_cffi`) and attaches the bytes to the message, so Discord hosts the image itself. If an image cannot be fetched, the product is still posted without an image.

### Store database

SQLite database is automatically created in the data directory, storing:

- Store information
- Product details
- Price history
- Update timestamps

### Discord database

SQLite database is automatically created in the data directory, storing:

- User information

### Running with Docker

Create a `.env` file with the bot token:

```bash
BOT_TOKEN=your_discord_bot_token
```

Build and run:

```bash
docker compose build
docker compose up -d
```

The compose file targets `linux/arm64` for Raspberry Pi deployment. If the Raspberry Pi reports `armv7l`, install a 64-bit OS before deploying this version.

### Deploying to Raspberry Pi

The bot runs on a Raspberry Pi 3 with a 64-bit OS (verify with `uname -m` → `aarch64`). The image is built on the development machine and shipped to the Pi, because config files (`bot/config/`, `store_data_extractor/config/`) are intentionally not in Git and are baked into the image at build time.

Before building, set production values in `bot/config/settings.json`: the real notification channel name and `"post_store_updates": true`. Changing these later requires a rebuild — only `./data` is volume-mounted. Make sure the bot role has View Channel, Send Messages and Embed Links permissions in the notification channel.

Deployment steps (the local `raspberry_deploy.sh` script automates 1–4):

1. Build the arm64 image locally: `docker buildx build --platform linux/arm64 -t discord-bot:latest --load .`
2. Save it: `docker save discord-bot:latest | gzip > discord-bot.tar.gz`
3. Copy the archive and `.env` to the Pi (`scp` into the project directory that contains `docker-compose.yml`).
4. On the Pi: `gunzip -f discord-bot.tar.gz && docker image load -i discord-bot.tar`, then `docker compose up -d --no-build --pull never`.
5. Follow the logs: `docker compose logs -f`.

Handling `data/` on the Pi:

- **Keep the Pi's `discord_db.sqlite`** — it contains the server's member records.
- **Replace the Pi's `store_db.sqlite`** with an up-to-date copy from the development machine (`scp data/store_db.sqlite` into the Pi's `data/` while the container is stopped). This avoids re-posting products that were already announced.
- Back up the old `data/` directory before replacing anything.
- If `store_db.sqlite` is missing or empty, the first fetch fills it silently without posting (see Silent Store Backfill above) — the channel cannot be flooded.
- Optional smoke test after deployment: delete one product row from `store_db.sqlite` and restart — exactly that product should be re-announced.

### Development Checks

Useful local checks:

```bash
python scripts/smoke_compile.py
python scripts/smoke_first_run.py
python scripts/smoke_scraper.py
python scripts/smoke_silent_post.py
python scripts/smoke_image_post.py
```

Docker smoke checks used for this version:

```bash
docker build -t jirai-sweeties:py314-smoke .
docker run --rm jirai-sweeties:py314-smoke python scripts/smoke_compile.py
docker run --rm jirai-sweeties:py314-smoke python scripts/smoke_scraper.py
docker run --rm jirai-sweeties:py314-smoke python scripts/smoke_silent_post.py
```

### Technology Stack

- Python 3.14 on Alpine Linux in Docker
- Discord.py for bot functionality
- SQLite3 for data storage
- Lxml for web data extraction
- aiohttp for async HTTP requests
- curl_cffi for scraper requests that need browser impersonation
- Additional dependencies listed in requirements.txt

## License and Copyright

Copyright (c) 2024-present yumeangelica. All rights reserved.

This project is protected under Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License (CC BY-NC-ND 4.0).

For complete license terms, see LICENSE.txt.
