from __future__ import annotations

import ctypes
import sys
import traceback

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from nvr_app.logging_utils import configure_file_logging, get_logger
from nvr_app.resources import resource_path
from nvr_app.settings import APP_NAME, APPLICATION_NAME, ORGANIZATION_NAME
from nvr_app.updater import cleanup_update_runners
from nvr_app.ui.main_window import MainWindow
from nvr_app.ui.theme import APP_STYLESHEET


def _install_exception_hook(logger) -> None:
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        details = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        logger.error("未处理异常: %s", details)
        QMessageBox.critical(
            None,
            "程序异常",
            f"发生未处理异常：\n{exc_value}\n\n详细信息已写入日志。",
        )

    sys.excepthook = handle_exception


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "payne.NVRAssistant.Desktop"
        )
    except (AttributeError, OSError):
        pass


def main() -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(
        QIcon(str(resource_path("image/NvrAssistantLogo.ico")))
    )
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_STYLESHEET)

    logger = configure_file_logging()
    _install_exception_hook(logger)
    logger.info("%s 启动", APPLICATION_NAME)

    window = MainWindow()
    window.show()
    QTimer.singleShot(
        2000,
        lambda: cleanup_update_runners(Path(sys.executable).parent),
    )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

