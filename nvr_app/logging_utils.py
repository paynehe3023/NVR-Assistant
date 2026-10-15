from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from nvr_app.settings import local_data_dir


LOGGER_NAME = "nvr_app"
_PASSWORD_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token)\b(\s*[:=]\s*)([^\s,;]+)"
)


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    return _PASSWORD_PATTERN.sub(r"\1\2***", text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.msg)
        if record.args:
            record.args = tuple(redact_sensitive_text(arg) for arg in record.args)
        return True


def configure_file_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = local_data_dir() / "logs" / "nvr-assistant.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)

