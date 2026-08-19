# Jirai sweeties discord bot

A custom Discord bot designed for the Jirai sweeties server, combining chat functionality with automated store monitoring and real-time notifications for server members.

## Project Information

- **Version**: 1.9.1
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
├── tests/                              # Offline unittest regression tests
├── .venv/                              # uv-managed Python virtual environment
├── .deployment                         # Deployment configuration
├── .dockerignore                       # Docker ignore file
├── .env                                # Environment variables
├── .gitignore                          # Git ignore file
├── Dockerfile                          # Docker configuration
├── LICENSE.txt                         # Project license
├── main_file.py                        # Main script file
├── pyproject.toml                      # Direct Python dependencies
├── uv.lock                             # Locked dependency graph
├── README.md                           # Project documentation
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

### Raspberry Pi operations

The canonical, copy-pasteable Finnish guide is [Raspberry Pi -ajo-opas](docs/raspberry-pi-runbook.md). It covers backup, safe shutdown, OS reinstall, Docker setup, application restore, verification, later deploys, and manual fallback steps.

The important data rule is simple: the running container's `/app/data` mount is the source of truth. It can be either a legacy Docker named volume or the current `./data:/app/data` bind mount. Both databases use WAL mode, so never copy only a live `.sqlite` file; stop the writer and copy the complete mount.

Set the Pi connection once per Terminal session:

```bash
export PI_HOST=192.168.1.50
export PI_USER=pi
export PI_DIR=programs/jirai_sweeties
```

The normal commands are:

```bash
./scripts/setup_pi_ssh.sh                         # one-time SSH key setup
./scripts/backup_pi_data.sh --update-local        # verified backup; restart the Pi bot
./scripts/backup_pi_data.sh --update-local \
  --leave-stopped                                 # verified backup before shutdown
./scripts/restore_pi_data.sh backups/pi-data-YYYYMMDD-HHMMSS --start
./scripts/deploy_pi.sh --keep-db --logs           # safe/default later deploy
```

> [!WARNING]
> Take a verified `backup_pi_data.sh --update-local` snapshot before the first deploy or any
> reinstall. Never substitute `--replace-db` or `--fresh-db` for the normal `--keep-db` flow:
> those options intentionally replace or remove Pi data.

`backup_pi_data.sh` discovers the real Docker mount, stops the bot during the copy, verifies both databases with `PRAGMA integrity_check`, writes SHA-256 checksums, and only then updates local `data/`. Its snapshot contains `remote-data/`, `SHA256SUMS`, and—when local data was updated—`local-data-before-update/`.

`restore_pi_data.sh` only restores into a stopped container with an empty `/app/data`, verifies the result on the Pi, and starts the bot only after success. `deploy_pi.sh` keeps both Pi databases by default and creates a verified Mac snapshot before replacing an existing container. It refuses an implicit named-volume-to-bind-mount transition; perform that transition through the runbook's backup/reinstall/restore flow.

`--replace-db` and `--fresh-db` are explicit database operations, not normal deploy options. Do not use either unless replacing or deleting the Pi's store database is intentional. Databases, `.env`, production config, and `backups/` are ignored by Git.

### Development Checks

Useful local checks:

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/smoke_compile.py
uv run --locked python scripts/smoke_first_run.py
uv run --locked python scripts/smoke_silent_post.py
uv run --locked python scripts/smoke_scraper.py  # live store request; no DB or Discord writes
```

The production image intentionally excludes tests and scripts. Build it and verify imports
without starting the bot:

```bash
docker buildx build --platform linux/arm64 -t jirai-sweeties:py314-smoke --load .
docker run --rm --entrypoint python jirai-sweeties:py314-smoke -c \
  "import bot.discord_bot, store_data_extractor.src.data_extractor; print('imports passed')"
```

### Technology Stack

- Python 3.14 on Alpine Linux in Docker
- Discord.py for bot functionality
- SQLite3 for data storage
- Lxml for web data extraction
- aiohttp for async HTTP requests
- curl_cffi for scraper requests that need browser impersonation
- uv-managed dependencies declared in `pyproject.toml` and locked in `uv.lock`

## License and Copyright

Copyright (c) 2024-present yumeangelica. All rights reserved.

This project is protected under Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License (CC BY-NC-ND 4.0).

For complete license terms, see LICENSE.txt.
