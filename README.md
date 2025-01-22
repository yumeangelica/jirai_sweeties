# Jirai sweeties discord bot

A custom Discord bot designed for the Jirai sweeties server, combining chat functionality with automated store monitoring and real-time notifications for server members.

## Project Information
- **Version**: 1.6.0
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
│   └── types.py                        # Type definitions for Discord bot
├── data/
│   ├── discord_db.sqlite               # SQLite database for Discord bot
│   └── store_db.sqlite                 # SQLite database for store data
├── store_data_extractor/
│   ├── config/                         # Configuration files for store data extractor
│   │   ├── last_user_agent_index.txt   # User agent index tracking
│   │   ├── stores.json                 # Store configurations
│   │   └── user_agents.txt             # List of user agents
│   ├── src/                            # Core functionality for data extraction
│   │   ├── agent_helper.py             # Helper for managing user agents
│   │   ├── data_extractor.py           # Data extraction logic
│   │   └── store_database.py           # Database logic for stores
│   ├── store_manager.py                # Store monitor entry point
│   └── types.py                        # Type definitions for store data extractor
├── utils/
│   ├── data_directory_helper.py        # Helper functions for data directories
│   └── logger.py                       # Logging functionality
├── venv/                               # Python virtual environment
├── .env                                # Environment variables
├── .gitignore                          # Git ignore file
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
    "name": "store_name",  // Unique identifier for the store.
    "name_format": "Formatted Store Name",  // User-friendly name for the store.
    "options": {
      "base_url": "base_url_for_data_extraction",  // Starting URL for extracting data.
      "site_main_url": "main_site_url",  // Main website URL.
      "item_container_selector": "HTML_selector_for_item_containers",  // HTML selector for locating items.
      "item_name_selector": "HTML_selector_for_item_names",  // Selector for item names.
      "item_price_selectors": [
        {
          "currency": "currency_code",  // Currency type (e.g., EUR, JPY).
          "selector": "HTML_selector_for_price"  // HTML selector for price.
        }
      ],
      "item_link_selector": "HTML_selector_for_item_links",  // Selector for item links.
      "item_image_selector": "HTML_selector_for_item_images",  // Selector for item images.
      "sold_out_selector": "HTML_selector_for_sold_out_items",  // Selector to identify sold-out items.
      "next_page_selector": "HTML_selector_for_next_page",  // Selector for pagination element.
      "next_page_selector_text": "Text_for_next_page_element",  // Text identifying the next page link.
      "next_page_attribute": "attribute_containing_next_page_url",  // Attribute containing the next page URL.
      "delay_between_requests": "time_in_seconds_between_requests",  // Delay (in seconds) between requests.
      "encoding": "character_encoding_used"  // Website's character encoding.
    },
    "schedule": {
      "minutes": "list_of_minutes_for_execution",  // Minute intervals
      "hours": "list_of_hours_or_*",  // Hour intervals or `*` for every hour.
      "days": "list_of_days_or_*",  // Day intervals or `*` for every day.
      "months": "list_of_months_or_*",  // Month intervals or `*` for every month.
      "years": "list_of_years_or_*"  // Year intervals or `*` for every year.
    }
  }
]
```
settings.json
```json
{
  "new_items_channel_name": "channel_name_for_new_items",  // Name of the channel where new items will be posted.
  "embed_color": [R, G, B],  // RGB color for embedded messages (format: [R, G, B]).
  "welcome_channel_name": "channel_name_for_welcome_messages"  // Name of the channel for welcome messages.
}
```

#### user_agents.txt (required)
- List of browser user agents for web data extraction
- Must be created manually
- One user agent per line
- Used to prevent request blocking

#### last_user_agent_index.txt (auto-generated)
- Tracks the current user agent rotation
- Created automatically by the system
- Do not modify manually

### Store database
SQLite database is automatically created in the data directory, storing:
- Store information
- Product details
- Price history
- Update timestamps

### Discord database
SQLite database is automatically created in the data directory, storing:
- User information


### Technology Stack
- Python 3.13.0
- Discord.py for bot functionality
- SQLite3 for data storage
- Beautiful Soup 4 for web data extraction
- aiohttp for async HTTP requests
- Additional dependencies listed in requirements.txt

## License and Copyright

Copyright (c) 2024-present yumeangelica. All rights reserved.

This project is protected under Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License (CC BY-NC-ND 4.0).

For complete license terms, see LICENSE.txt.