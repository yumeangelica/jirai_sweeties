# Jirai sweeties discord bot

A custom Discord bot designed for the Jirai Sweeties server, combining chat functionality with automated store monitoring.

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
├── data/                   # SQLite database location
├── store_data_extractor/
│   ├── config/             # Configuration files
│   ├── src/                # Core functionality
│   └── store_manager.py    # Store monitor entry point
├── utils/                  # Utility functions
└── run.py                  # Discord bot entry point
```

### Required Configuration Files

The project needs these configuration files in store_data_extractor/config/:

#### stores.json (required)
- Store configurations and monitoring schedules. Determines which stores to monitor and how often.
- Must be created manually
- Defines store URLs, HTML selectors, and update intervals

Structure:
```json
[
  {
    "name": "store_name",
    "options": {
      "base_url": "store_url",
      "site_main_url": "main_site_url",
      "data_file": "previous_items_file.txt",
      "item_container_class": "container_class",
      "item_name_selector": "name_selector",
      "item_price_selector": "price_selector",
      "item_link_selector": "link_selector",
      "sold_out_style": "sold_out_indicator",
      "next_page_selector": "next_page_element",
      "next_page_attribute": "attribute_name",
      "delay_between_requests": "delay_in_seconds"
    },
    "schedule": {
      "minutes": ["list_of_minutes"],
      "hours": "* or list of hours",
      "days": "* or list of days",
      "months": "* or list of months",
      "years": "* or list of years"
    }
  }
]
```

Each store configuration contains:
- `name`: Identifier for the store
- `options`: Data extraction configuration
  - `base_url`: Starting URL for data extraction
  - `site_main_url`: Main website URL
  - `data_file`: File to store previous items
  - `item_container_class`: HTML class for item containers
  - `item_name_selector`: Selector for item names
  - `item_price_selector`: Selector for prices
  - `item_link_selector`: Selector for item links
  - `sold_out_style`: Style indicating sold out items
  - `next_page_selector`: Element for pagination
  - `next_page_attribute`: Attribute containing next page URL
  - `delay_between_requests`: Time between requests in seconds
- `schedule`: Monitoring schedule using cron-style patterns

#### user_agents.txt (required)
- List of browser user agents for web data extraction
- Must be created manually
- One user agent per line
- Used to prevent request blocking

#### last_user_agent_index.txt (auto-generated)
- Tracks the current user agent rotation
- Created automatically by the system
- Do not modify manually

### Database
SQLite database is automatically created in the data directory, storing:
- Store information
- Product details
- Price history
- Update timestamps

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