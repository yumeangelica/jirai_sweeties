import os
import aiofiles
import asyncio
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")

AGENT_LIST_FILE = os.path.join(CONFIG_DIR, "user_agents.txt")
AGENT_INDEX_FILE = os.path.join(CONFIG_DIR, "last_user_agent_index.txt")

file_lock = asyncio.Lock()
user_agent_list = [agent.rstrip() for agent in open(AGENT_LIST_FILE, 'r').readlines()]
user_agent_index = None


def get_last_user_agent_index() -> int:
    """Get the last used user agent index from file (synchronously)."""
    try:
        with open(AGENT_INDEX_FILE, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0

async def save_last_user_agent_index(index: int) -> None:
    """Save the last used user agent index with file locking."""
    async with file_lock:
        async with aiofiles.open(AGENT_INDEX_FILE, 'w') as f:
            await f.write(str(index))

async def next_user_agent() -> str:
    """Return the next User-Agent string, increment index, and save it safely."""
    global user_agent_index


    # Initialize if needed
    if user_agent_index is None:
        user_agent_index = get_last_user_agent_index()

    # Get the current agent
    agent = user_agent_list[user_agent_index]

    # Increment index and wrap around
    user_agent_index += 1
    if user_agent_index >= len(user_agent_list):
        user_agent_index = 0

    # Persist the updated index
    await save_last_user_agent_index(user_agent_index)

    return agent
