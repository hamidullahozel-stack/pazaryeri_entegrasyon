# ==========================================
# Dosya Yolu: entegrator54/app_logging.py
# ==========================================
import os
import logging
from datetime import datetime

LOG_DIR = "logs"

def setup_logging():
    logging.basicConfig(level=logging.INFO)

def get_logger(name):
    return logging.getLogger(name)