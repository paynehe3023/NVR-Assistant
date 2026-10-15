from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths


APP_NAME = "NVR Assistant"
ORGANIZATION_NAME = "NvrAssistant"
APPLICATION_NAME = "NvrAssistant"


def app_settings() -> QSettings:
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        ORGANIZATION_NAME,
        APPLICATION_NAME,
    )


def local_data_dir() -> Path:
    root = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not root:
        root = os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), APPLICATION_NAME)
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> Path:
    documents = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    root = Path(documents) if documents else Path.home()
    path = root / APP_NAME / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_string(key: str, default: str = "") -> str:
    value = app_settings().value(key, default)
    return str(value) if value is not None else default


def set_string(key: str, value: str) -> None:
    app_settings().setValue(key, value)
    app_settings().sync()


def get_int(key: str, default: int) -> int:
    value = app_settings().value(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def set_int(key: str, value: int) -> None:
    app_settings().setValue(key, int(value))
    app_settings().sync()


def get_float(key: str, default: float) -> float:
    value = app_settings().value(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def set_float(key: str, value: float) -> None:
    app_settings().setValue(key, float(value))
    app_settings().sync()

