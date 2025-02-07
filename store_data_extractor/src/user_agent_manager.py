import os
import aiofiles
import asyncio
from typing import List, Optional
import logging

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")

AGENT_LIST_FILE = os.path.join(CONFIG_DIR, "user_agents.txt")
AGENT_INDEX_FILE = os.path.join(CONFIG_DIR, "last_user_agent_index.txt")

class UserAgentManager:
    def __init__(self):
        self.file_lock = asyncio.Lock()
        self.index_lock = asyncio.Lock()
        self.user_agent_list: List[str] = self._load_user_agents()
        self.current_index: Optional[int] = None
        self.highest_used_index: Optional[int] = None  # Track highest used index
        self.dirty = False
        self.logger = logging.getLogger("UserAgentManager")
        self._initialize_index()

    def _initialize_index(self) -> None:
        """Read the current index from file, or default to 0."""
        try:
            with open(AGENT_INDEX_FILE, 'r') as f:
                loaded_index = int(f.read().strip()) + 1 # prevent using the same agent
                if loaded_index > len(self.user_agent_list):
                    self.current_index = 0
                    self.highest_used_index = 0
                else:
                    self.current_index = loaded_index
                    self.highest_used_index = loaded_index
        except (FileNotFoundError, ValueError):
            self.current_index = 0
            self.highest_used_index = 0

    def _load_user_agents(self) -> List[str]:
        """Load user agents from file into a list."""
        try:
            with open(AGENT_LIST_FILE, 'r') as f:
                return [agent.strip() for agent in f if agent.strip()]
        except FileNotFoundError:
            raise RuntimeError(f"User agent file not found at {AGENT_LIST_FILE}")

    async def next_user_agent(self) -> str:
        async with self.index_lock:
            if self.current_index is None:
                self.current_index = 0

            # Select agent based on current_index
            agent = self.user_agent_list[self.current_index % len(self.user_agent_list)]

            # Update highest used index
            if self.highest_used_index is None or self.current_index > self.highest_used_index:
                self.highest_used_index = self.current_index

            # Increment the index
            self.current_index += 1
            self.dirty = True

            return agent

    async def save_index_after_task(self, force: bool = False) -> None:
        """Save the highest used index to file."""
        # Use highest_used_index instead of current_index
        if self.highest_used_index is None:
            return

        if not force and not self.dirty:
            return

        max_retries = 5
        retry_delay = 0.5
        last_error = None

        async with self.index_lock:
            for attempt in range(max_retries):
                try:
                    async with self.file_lock:
                        # Save the highest_used_index instead of current_index
                        async with aiofiles.open(AGENT_INDEX_FILE, 'w') as f:
                            await f.write(str(self.highest_used_index))
                        self.dirty = False
                        return
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2

            self.logger.error(f"Failed to save user agent index after {max_retries} attempts: {last_error}")

# Global instance
user_agent_manager = UserAgentManager()

async def next_user_agent() -> str:
    """Convenience function to get next user agent from the global manager."""
    return await user_agent_manager.next_user_agent()

async def save_user_agent_index_after_task(force: bool = False) -> None:
    """Convenience function to save index from the global manager."""
    await user_agent_manager.save_index_after_task(force=force)

