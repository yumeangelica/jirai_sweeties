import os

def ensure_directory_exists(directory_path: str) -> None:
    """Ensure that the given directory exists. Create it if it doesn't."""
    os.makedirs(directory_path, exist_ok=True)
