from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nvr_app import __version__
from nvr_app.settings import (
    default_output_dir,
    get_float,
    get_int,
    get_string,
    local_data_dir,
    set_float,
    set_int,
    set_string,
)
from nvr_app.ui.widgets import FlatDoubleSpinBox, FlatSpinBox
from nvr_app.updater import (
    UpdateCancelled,
    UpdateError,
    UpdateInfo,
    check_for_update,
    download_update,
    launch_update,
)
from nvr_app.workers import ServiceTask


class SettingsPage(QWidget):
    settings_saved = Signal()
    log_message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._update_task = None
        self._download_task = None
        self._active_update_operation = ""
        self._update_info: UpdateInfo | None = None
        self._downloaded_archive: Path | None = None
        self._build_ui()
        self.refresh_settings()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 12)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("PageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        hint = QLabel("保存运行偏好并检查软件更新")
        hint.setObjectName("PageHint")
        title_box.addWidget(title)
        title_box.addWidget(hint)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        root.addWidget(header)

        panel = QFrame()
        panel.setObjectName("PageHeader")
        form = QFormLayout(panel)
        form.setContentsMargins(18, 18, 18, 18)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_button = QPushButton("选择目录")
        output_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(output_button)
        form.addRow("默认输出目录", output_row)

        self.timeout_spin = FlatDoubleSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSuffix(" 秒")
        form.addRow("默认超时", self.timeout_spin)

        self.workers_spin = FlatSpinBox()
        self.workers_spin.setRange(1, 32)
        form.addRow("默认并发 NVR", self.workers_spin)

        save_button = QPushButton("保存设置")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save)
        form.addRow("", save_button)
        root.addWidget(panel)

        update_panel = QFrame()
        update_panel.setObjectName("PageHeader")
        update_layout = QVBoxLayout(update_panel)
        update_layout.setContentsMargins(18, 16, 18, 16)
        update_layout.setSpacing(8)

        update_title = QLabel("软件更新")
        update_title.setObjectName("SectionTitle")
        update_layout.addWidget(update_title)
        update_layout.addWidget(QLabel(f"当前版本：v{__version__}"))

        self.update_status = QLabel("点击“检查更新”获取最新版本")
        self.update_status.setObjectName("MutedLabel")
        self.update_status.setWordWrap(True)
        update_layout.addWidget(self.update_status)

        self.update_details = QLabel("")
        self.update_details.setObjectName("MutedLabel")
        self.update_details.setWordWrap(True)
        self.update_details.hide()
        update_layout.addWidget(self.update_details)

        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 1)
        self.update_progress.setValue(0)
        self.update_progress.hide()
        update_layout.addWidget(self.update_progress)

        update_buttons = QHBoxLayout()
        self.check_update_button = QPushButton("检查更新")
        self.check_update_button.setObjectName("PrimaryButton")
        self.check_update_button.clicked.connect(self._check_update)
        self.download_update_button = QPushButton("下载更新")
        self.download_update_button.setEnabled(False)
        self.download_update_button.clicked.connect(self._download_update)
        self.install_update_button = QPushButton("安装更新")
        self.install_update_button.setEnabled(False)
        self.install_update_button.clicked.connect(self._install_downloaded)
        self.cancel_update_button = QPushButton("取消")
        self.cancel_update_button.setObjectName("DangerButton")
        self.cancel_update_button.setEnabled(False)
        self.cancel_update_button.clicked.connect(self._cancel_update)
        update_buttons.addWidget(self.check_update_button)
        update_buttons.addWidget(self.download_update_button)
        update_buttons.addWidget(self.install_update_button)
        update_buttons.addWidget(self.cancel_update_button)
        update_buttons.addStretch(1)
        update_layout.addLayout(update_buttons)
        root.addWidget(update_panel)

        info_panel = QFrame()
        info_panel.setObjectName("PageHeader")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.addWidget(QLabel(f"日志目录：{local_data_dir() / 'logs'}"))
        open_logs_button = QPushButton("打开日志目录")
        open_logs_button.clicked.connect(self._open_logs)
        info_layout.addWidget(open_logs_button, 0)
        info_layout.addStretch(1)
        root.addWidget(info_panel)
        root.addStretch(1)

    def refresh_settings(self) -> None:
        self.output_edit.setText(
            get_string("general/output_dir", str(default_output_dir()))
        )
        self.timeout_spin.setValue(get_float("general/timeout", 8.0))
        self.workers_spin.setValue(get_int("general/workers", 4))

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择默认输出目录",
            self.output_edit.text().strip() or str(default_output_dir()),
        )
        if path:
            self.output_edit.setText(path)

    def _save(self) -> None:
        set_string("general/output_dir", self.output_edit.text().strip())
        set_float("general/timeout", self.timeout_spin.value())
        set_int("general/workers", self.workers_spin.value())
        set_string("scan/output_dir", self.output_edit.text().strip())
        set_float("scan/timeout", self.timeout_spin.value())
        set_int("scan/workers", self.workers_spin.value())
        set_string("lookup/output_dir", self.output_edit.text().strip())
        set_float("lookup/timeout", self.timeout_spin.value())
        set_int("lookup/workers", self.workers_spin.value())
        self.settings_saved.emit()
        self.log_message.emit("设置已保存", "success")

    def _check_update(self) -> None:
        if self._update_task is not None or self._download_task is not None:
            return
        self._active_update_operation = "check"
        self._update_info = None
        self._downloaded_archive = None
        self.download_update_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        self.update_details.hide()
        self.update_progress.setRange(0, 0)
        self.update_progress.show()
        self.update_status.setText("正在检查更新...")
        self._set_update_busy(True)

        task = ServiceTask(
            check_for_update,
            __version__,
            cancel_exceptions=(UpdateCancelled,),
        )
        task.signals.progress.connect(self._on_update_progress)
        task.signals.finished.connect(self._on_update_checked)
        task.signals.failed.connect(self._on_update_failed)
        task.signals.cancelled.connect(self._on_update_cancelled)
        self._update_task = task
        QThreadPool.globalInstance().start(task)

    def _on_update_checked(self, info: UpdateInfo | None) -> None:
        self._update_task = None
        self._set_update_busy(False)
        self.update_progress.hide()
        if info is None:
            self.update_status.setText(f"已是最新版本 v{__version__}")
            self.log_message.emit("检查更新：已是最新版本", "success")
            return

        self._update_info = info
        self.update_status.setText(f"发现新版本 v{info.version}")
        details = []
        if info.published_at:
            details.append(f"发布时间：{info.published_at}")
        if info.notes:
            details.append(info.notes)
        self.update_details.setText("\n".join(details))
        self.update_details.show()
        self.download_update_button.setEnabled(True)
        self.log_message.emit(f"发现新版本 v{info.version}", "info")

    def _on_update_failed(self, message: str) -> None:
        self._finish_update_task()
        self.update_status.setText(f"检查更新失败：{message}")
        self.log_message.emit(f"检查更新失败：{message}", "error")

    def _on_update_cancelled(self) -> None:
        self._finish_update_task()
        self.update_status.setText("更新操作已取消")
        self.log_message.emit("更新操作已取消", "warning")

    def _download_update(self) -> None:
        if (
            self._update_info is None
            or self._update_task is not None
            or self._download_task is not None
        ):
            return
        self._active_update_operation = "download"
        self.update_progress.setRange(0, 0)
        self.update_progress.setValue(0)
        self.update_progress.show()
        self.update_status.setText("正在下载更新...")
        self._set_update_busy(True)

        task = ServiceTask(
            download_update,
            self._update_info.download_url,
            self._update_info.sha256,
            cancel_exceptions=(UpdateCancelled,),
        )
        task.signals.progress.connect(self._on_update_progress)
        task.signals.finished.connect(self._on_update_downloaded)
        task.signals.failed.connect(self._on_update_failed)
        task.signals.cancelled.connect(self._on_update_cancelled)
        self._download_task = task
        QThreadPool.globalInstance().start(task)

    def _on_update_progress(self, event: dict) -> None:
        message = str(event.get("message") or "处理中")
        self.update_status.setText(message)
        if event.get("indeterminate"):
            self.update_progress.setRange(0, 0)
            return
        total = int(event.get("total", 0) or 0)
        downloaded = int(event.get("downloaded", 0) or 0)
        if total:
            self.update_progress.setRange(0, total)
            self.update_progress.setValue(min(downloaded, total))
        else:
            percent = int(event.get("percent", 0) or 0)
            self.update_progress.setRange(0, 100)
            self.update_progress.setValue(percent)

    def _on_update_downloaded(self, archive_path: Path) -> None:
        self._download_task = None
        self._downloaded_archive = Path(archive_path)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(100)
        self._set_update_busy(False, download_complete=True)
        self.update_status.setText("更新包已下载，可以安装更新")
        self.log_message.emit("更新包下载完成", "success")
        self._install_downloaded()

    def _install_downloaded(self) -> None:
        if self._downloaded_archive is None:
            return
        answer = QMessageBox.question(
            self,
            "安装更新",
            "安装时程序会自动关闭，完成后重新启动。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            helper = launch_update(self._downloaded_archive)
        except UpdateError as exc:
            QMessageBox.critical(self, "更新失败", str(exc))
            self.update_status.setText(f"更新失败：{exc}")
            return

        if helper is None:
            self.update_status.setText("开发模式：已打开更新包所在目录")
            self.log_message.emit(
                "开发模式不会自动替换程序，已打开更新包目录",
                "info",
            )
            return
        self.update_status.setText("内置更新器已启动，程序即将重启")
        self.log_message.emit("内置更新器已启动，程序即将重启", "success")
        QTimer.singleShot(600, QApplication.instance().quit)

    def _cancel_update(self) -> None:
        task = self._update_task or self._download_task
        if task is not None:
            task.cancel()
            self.cancel_update_button.setEnabled(False)
            self.update_status.setText("正在取消...")

    def _finish_update_task(self) -> None:
        self._update_task = None
        self._download_task = None
        self._set_update_busy(False)
        self.update_progress.hide()

    def _set_update_busy(
        self,
        busy: bool,
        *,
        download_complete: bool = False,
    ) -> None:
        self.check_update_button.setEnabled(not busy)
        self.download_update_button.setEnabled(
            not busy
            and not download_complete
            and self._update_info is not None
        )
        self.install_update_button.setEnabled(
            not busy and self._downloaded_archive is not None
        )
        self.cancel_update_button.setEnabled(busy)

    def _open_logs(self) -> None:
        path = local_data_dir() / "logs"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def shutdown(self) -> None:
        for task in (self._update_task, self._download_task):
            if task is not None:
                task.cancel()
