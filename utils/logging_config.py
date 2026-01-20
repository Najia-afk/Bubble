#logging_config.py
import logging
import os

def setup_logging(log_filename, log_level=logging.INFO):
    # Use relative path or Docker volume mount
    logs_dir_path = os.path.join(os.getcwd(), 'logs')
    if not os.path.exists(logs_dir_path):
        os.makedirs(logs_dir_path)

    log_file_path = os.path.join(logs_dir_path, log_filename)
    logger = logging.getLogger(log_filename)
    logger.setLevel(log_level)
    logger.propagate = False

    if not any(isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file_path for handler in logger.handlers):
        file_handler = logging.FileHandler(log_file_path)
        formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:%(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.info("Logging setup complete for %s", log_filename)
    return logger