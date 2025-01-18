import logging

def configure_logger():
    """
    Configure a root logger with a console handler and optional file handler.
    """
    logger = logging.getLogger()  # Get the root logger
    logger.setLevel(logging.DEBUG)  # Set global log level to DEBUG

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # Console shows INFO and above
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    # Add handlers if not already added
    if not logger.hasHandlers():
        logger.addHandler(console_handler)

    # Adjust logging levels for specific libraries
    logging.getLogger("discord").setLevel(logging.WARNING)  # Suppress discord library logs
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    return logger
