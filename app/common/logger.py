import logging
from logging.handlers import RotatingFileHandler

log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

general_handler = RotatingFileHandler("general.log", maxBytes=5*1024*1024, backupCount=3)
general_handler.setLevel(logging.INFO)
general_handler.setFormatter(log_format)

error_handler = RotatingFileHandler("errors.log", maxBytes=5*1024*1024, backupCount=3)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(log_format)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

root_logger.addHandler(general_handler)
root_logger.addHandler(error_handler)
root_logger.addHandler(console_handler)

def get_logger(module_name):
    return logging.getLogger(module_name)