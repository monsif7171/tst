"""Logging configuration for the pharmacy system."""
import os
import logging
from logging.handlers import RotatingFileHandler
from config import BASE_DIR, DEBUG

# Log directory
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logging(app=None):
    """Configure logging for the application."""
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    console_handler.setFormatter(formatter)

    # Application log file with rotation
    app_log = os.path.join(LOG_DIR, 'pharmacy_app.log')
    file_handler = RotatingFileHandler(
        app_log, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    file_handler.setFormatter(formatter)

    # Error log file
    error_log = os.path.join(LOG_DIR, 'pharmacy_error.log')
    error_handler = RotatingFileHandler(
        error_log, maxBytes=10 * 1024 * 1024, backupCount=10, encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.removeHandler(root_logger.handlers[0])
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    # Audit logger
    audit_logger = logging.getLogger('pharmacy.audit')
    audit_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'pharmacy_audit.log'),
        maxBytes=50 * 1024 * 1024, backupCount=30, encoding='utf-8'
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(formatter)
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    # Security logger
    security_logger = logging.getLogger('pharmacy.security')
    security_logger.addHandler(audit_handler)
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False

    if app:
        app.logger.addHandler(console_handler)
        app.logger.addHandler(file_handler)
        app.logger.addHandler(error_handler)
        app.logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    return {
        'app': logging.getLogger('pharmacy.app'),
        'audit': audit_logger,
        'security': security_logger,
        'error': logging.getLogger('pharmacy.error')
    }


def get_loggers():
    """Get logger instances."""
    return {
        'app': logging.getLogger('pharmacy.app'),
        'audit': logging.getLogger('pharmacy.audit'),
        'security': logging.getLogger('pharmacy.security'),
        'error': logging.getLogger('pharmacy.error')
    }
