from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from nvr_app.logging_utils import get_logger
from nvr_app.resources import resource_path
from nvr_app.ui.camera_lookup_page import CameraLookupPage
from nvr_app.ui.nvr_scan_page import NvrScanPage
from nvr_app.ui.settings_page import SettingsPage


class LogWindow(QDialog):
    closed = Signal()

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NVR Assistant")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 700)
        self._app_icon = QIcon(
            str(resource_path("image/NvrAssistantLogo.ico"))
        )
        self.setWindowIcon(self._app_icon)
        self._logger = get_logger()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        brand_box = QWidget()
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(18, 20, 18, 18)
        brand_layout.setSpacing(10)

        brand_icon = QLabel()
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setFixedSize(36, 36)
        brand_icon.setPixmap(self._app_icon.pixmap(36, 36))
        brand_layout.addWidget(
            brand_icon,
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(3)
        brand = QLabel("NVR Assistant")
        brand.setObjectName("BrandTitle")
        subtitle = QLabel("本地巡检与反查工具")
        subtitle.setObjectName("BrandSubtitle")
        brand_text.addWidget(brand)
        brand_text.addWidget(subtitle)
        brand_layout.addLayout(brand_text, 1)
        sidebar_layout.addWidget(brand_box)

        self.navigation = QListWidget()
        self.navigation.setObjectName("Navigation")
        self.navigation.setSpacing(2)
        self.navigation.currentRowChanged.connect(self._switch_page)
        sidebar_layout.addWidget(self.navigation, 1)
        root_layout.addWidget(sidebar)

        self.page_stack = QStackedWidget()
        self.scan_page = NvrScanPage()
        self.lookup_page = CameraLookupPage()
        self.settings_page = SettingsPage()
        self.page_stack.addWidget(self.scan_page)
        self.page_stack.addWidget(self.lookup_page)
        self.page_stack.addWidget(self.settings_page)
        root_layout.addWidget(self.page_stack, 1)
        self.setCentralWidget(root)

        style = self.style()
        self._add_navigation_item(
            "NVR 巡检",
            style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
        )
        self._add_navigation_item(
            "摄像头反查",
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
        )
        self._add_navigation_item(
            "设置",
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
        )
        self.navigation.setCurrentRow(0)

        self.scan_page.log_message.connect(self.append_log)
        self.lookup_page.log_message.connect(self.append_log)
        self.settings_page.log_message.connect(self.append_log)
        self.settings_page.settings_saved.connect(self._refresh_pages)
        self._build_log_window()
        view_menu = self.menuBar().addMenu("视图")
        self.log_action = QAction("运行日志", self)
        self.log_action.setCheckable(True)
        self.log_action.toggled.connect(self._toggle_log_window)
        view_menu.addAction(self.log_action)
        self.log_window.hide()
        self.statusBar().showMessage("就绪")

    def _add_navigation_item(self, text: str, icon) -> None:
        item = QListWidgetItem(icon, text)
        item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
        self.navigation.addItem(item)

    def _switch_page(self, index: int) -> None:
        if index >= 0:
            self.page_stack.setCurrentIndex(index)

    def _build_log_window(self) -> None:
        self.log_window = LogWindow(self)
        self.log_window.setWindowTitle("运行日志")
        self.log_window.setWindowIcon(self._app_icon)
        self.log_window.setMinimumSize(560, 180)
        self.log_window.resize(780, 260)
        self.log_window.closed.connect(
            lambda: self.log_action.setChecked(False)
        )
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        toolbar = QFrame()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.addStretch(1)
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(lambda: self.log_view.clear())
        toolbar_layout.addWidget(clear_button)
        log_layout.addWidget(toolbar)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        log_layout.addWidget(self.log_view)
        window_layout = QVBoxLayout(self.log_window)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.addWidget(log_widget)

    def _toggle_log_window(self, visible: bool) -> None:
        if visible:
            self.log_window.show()
            self.log_window.raise_()
            self.log_window.activateWindow()
        else:
            self.log_window.hide()

    def append_log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")
        log_method = getattr(self._logger, level, self._logger.info)
        log_method(message)
        self.statusBar().showMessage(message, 5000)

    def _refresh_pages(self) -> None:
        self.scan_page.refresh_settings()
        self.lookup_page.refresh_settings()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.scan_page.shutdown()
        self.lookup_page.shutdown()
        self.settings_page.shutdown()
        self._logger.info("应用关闭")
        event.accept()

