from typing import List, NotRequired, TypedDict

class BotSettingsDataType(TypedDict):
    embed_color: List[int]
    new_items_channel_name: str
    post_store_updates: NotRequired[bool]
    welcome_channel_name: str


class DiscordUserDataType(TypedDict):
    id: int
    username: str
    created_at: str
