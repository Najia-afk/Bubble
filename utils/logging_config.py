# =============================================================================
# Bubble - Blockchain Analytics Platform
# Logging Configuration
# =============================================================================

import logging
import os
import sys


LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(log_filename, log_level=None):
    """
    Configure logging with both file and stdout handlers.
    
    In Docker, stdout is captured by the container runtime.
    File logs are written to the configured LOG_DIR for persistence.
    
    Args:
        log_filename: Name of the log file (e.g. 'application.log')
        log_level: Logging level (defaults to LOG_LEVEL env var or INFO)
    
    Returns:
        Configured logger instance
    """
    if log_level is None:
        level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_level = getattr(logging, level_name, logging.INFO)
    
    logs_dir = os.getenv('LOG_DIR', os.path.join(os.getcwd(), 'logs'))
    os.makedirs(logs_dir, exist_ok=True)

    log_file_path = os.path.join(logs_dir, log_filename)
    logger = logging.getLogger(log_filename)
    logger.setLevel(log_level)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # File handler (only add if not already present)
    has_file = any(
        isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(log_file_path)
        for h in logger.handlers
    )
    if not has_file:
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        logger.addHandler(file_handler)

    # Stdout handler (for Docker log collection)
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers)
    if not has_stream:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(log_level)
        logger.addHandler(stream_handler)

    return logger