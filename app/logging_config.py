"""
app/logging_config.py - Centralized Loguru configuration for FastAPI, Uvicorn, and background workers.
"""

import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
load_dotenv(BASE_DIR / ".env")


def get_log_formats() -> Tuple[str, str]:
    """
    Build console and file log formats dynamically based on environment variables.
    LOG_SHOW_CALLER: set to 'true' to show '{name}:{function}:{line} - '; defaults to 'false'.
    """
    show_caller = os.getenv("LOG_SHOW_CALLER", "false").strip().lower() in ("1", "true", "yes")

    if show_caller:
        console_fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        )
    else:
        console_fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        )
        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{message}"
        )

    return console_fmt, file_fmt


CONSOLE_FORMAT, FILE_FORMAT = get_log_formats()


class InterceptHandler(logging.Handler):
    """
    Standard logging handler to route messages from standard library loggers
    (uvicorn, fastapi, httpx, sqlalchemy, watchfiles, etc.) into Loguru.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Resolve corresponding Loguru level if it exists
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller frame from where the message originated
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(log_level: Optional[str] = None) -> None:
    """
    Configure Loguru as the application-wide logging system.
    Replaces standard logging root handlers and captures Uvicorn and FastAPI logs.
    """
    # Ensure logs directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove all existing sinks
    logger.remove()

    effective_level = (log_level or os.getenv("LOG_LEVEL", "INFO")).upper()
    rotation = os.getenv("LOG_ROTATION", "10 MB")
    retention_app = os.getenv("LOG_RETENTION_APP", "14 days")
    retention_error = os.getenv("LOG_RETENTION_ERROR", "30 days")
    console_format, file_format = get_log_formats()

    # 1. Add colorized console sink
    logger.add(
        sys.stdout,
        format=console_format,
        level=effective_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # 2. Add rotating and retaining file sink for application logs
    logger.add(
        LOGS_DIR / "app.log",
        format=file_format,
        level=effective_level,
        rotation=rotation,
        retention=retention_app,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 3. Add separate error log sink for WARN/ERROR/CRITICAL
    logger.add(
        LOGS_DIR / "error.log",
        format=file_format,
        level="WARNING",
        rotation=rotation,
        retention=retention_error,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 4. Intercept standard library root logger
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 5. Route specific framework loggers through InterceptHandler
    intercept_loggers = (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "watchfiles",
        "watchfiles.main",
        "sqlalchemy.engine",
    )
    for name in intercept_loggers:
        logging_logger = logging.getLogger(name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False


# Re-export logger for direct import
__all__ = ["logger", "setup_logging", "InterceptHandler"]
