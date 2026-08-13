# -*- coding: utf-8 -*-
"""Shared helpers for main.py and dashboard.py (DRY).

Contains: logging setup (console + rotating file), config loading
with a windows-1250 fallback, and shared constants.
"""

import configparser
import logging
import logging.handlers
import os

LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
DEFAULT_LOG_FILE = 'printer_monitor.log'
LOCK_MAX_AGE_SECONDS = 3600
WEB_WORKERS_DEFAULT = 3


def load_config(config_file):
    """Load configuration from the given config.ini path (empty config on failure)."""
    config = configparser.ConfigParser()
    try:
        config.read(config_file, encoding='utf-8')
    except UnicodeDecodeError:
        logging.warning("Failed to read %s as UTF-8. Trying 'windows-1250'...", config_file)
        config.read(config_file, encoding='windows-1250')
    except Exception:
        logging.error("Failed to read config file: %s", config_file)
    return config


def setup_logging(log_dir, config_file):
    """Console logging + rotating file (1 MB x 3 backups)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
        return
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(stream)
    config = load_config(config_file)
    log_file = DEFAULT_LOG_FILE
    if config.has_option('MONITORING', 'log_file'):
        log_file = config.get('MONITORING', 'log_file')
    try:
        rotating = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, log_file), maxBytes=1024 * 1024, backupCount=3,
            encoding='utf-8')
        rotating.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(rotating)
    except OSError:
        pass
