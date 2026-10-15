from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from nvr_app.exporters import export_scan_csv, export_scan_xlsx
from nvr_app.services.nvr_scan_service import (
    REPORT_FIELDS,
    ScanCancelled,
    build_manual_nvr_devices,
    load_nvr_devices,
    parse_nvr_ip_text,
    scan_nvrs,
)
from nvr_app.services.camera_lookup_service import resolve_nvr_csv_path
from nvr_app.settings import (
    default_output_dir,
    get_float,
    get_int,
    get_string,
    set_float,
    set_int,
    set_string,
)
from nvr_app.ui.widgets import (
    DataTableModel,
    FlatDoubleSpinBox,
    FlatSpinBox,
    PathSelector,
    SummaryCard,
)
from nvr_app.workers import ServiceTask


NVR_SUMMARY_COLUMNS = [
    ("NVR地址", "NVR地址"),
    ("NVR名称", "NVR名称"),
    ("状态", "状态"),
    ("物理设备", "物理设备"),
    ("正常在线", "正常在线"),
    ("部分不可达", "部分不可达"),
    ("完全离线", "完全离线"),
    ("状态未知", "状态未知"),
    ("通道数", "通道数"),
    ("错误", "错误"),
]

SUMMARY_FILTERS = {
    "physical": None,
    "normal": "正常在线",
    "partial": "部分不可达",
    "offline": "网络不可达",
    "unknown": "状态未知",
}

SUMMARY_TOOLTIPS = {
    "physical": "点击显示全部设备结果",
    "normal": "点击显示正常在线的设备",
    "partial": "点击显示部分不可达的设备",
    "offline": "点击显示完全离线的设备",
    "unknown": "点击显示状态未知的设备",
    "channels": "点击查看 NVR 汇总",
}


class NvrScanPage(QWidget):
    log_message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task = None
        self._payload = None
        self._device_model = DataTableModel(
            [(field, field) for field in REPORT_FIELDS]
        )
        self._summary_model = DataTableModel(NVR_SUMMARY_COLUMNS)
        self._build_ui()
        self.refresh_settings()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("PageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title = QLabel("NVR 巡检")
        title.setObjectName("PageTitle")
        hint = QLabel("读取 NVR 清单并实时扫描 ISAPI 通道")
        hint.setObjectName("PageHint")
        title_box.addWidget(title)
        title_box.addWidget(hint)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        root.addWidget(header)

        controls = QFrame()
        controls.setObjectName("PageHeader")
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(14, 10, 14, 10)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.addWidget(QLabel("输出目录"), 0, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        controls_layout.addWidget(self.output_edit, 0, 1)
        self.output_button = QPushButton("选择目录")
        self.output_button.clicked.connect(self._choose_output_dir)
        controls_layout.addWidget(self.output_button, 0, 2)
        controls_layout.setColumnStretch(1, 1)
        root.addWidget(controls)

        input_panel = QFrame()
        input_panel.setObjectName("PageHeader")
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(14, 10, 14, 10)
        input_layout.setSpacing(8)

        self.input_tabs = QTabWidget()
        csv_page = QWidget()
        csv_form = QFormLayout(csv_page)
        csv_form.setContentsMargins(12, 10, 12, 10)
        self.nvr_selector = PathSelector(
            "选择 NVR 清单",
            "CSV 文件 (*.csv);;所有文件 (*.*)",
        )
        csv_form.addRow("NVR CSV", self.nvr_selector)

        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page)
        batch_layout.setContentsMargins(10, 8, 10, 18)

        batch_toolbar = QHBoxLayout()
        batch_hint = QLabel(
            "支持单个或多个 NVR 管理地址，可用换行、逗号、分号或空格分隔"
        )
        batch_hint.setObjectName("MutedLabel")
        batch_toolbar.addWidget(batch_hint)
        batch_toolbar.addStretch(1)
        self.batch_nvr_clear_button = QPushButton("清空")
        self.batch_nvr_clear_button.clicked.connect(
            lambda: self.batch_nvr_edit.clear()
        )
        batch_toolbar.addWidget(self.batch_nvr_clear_button)
        batch_layout.addLayout(batch_toolbar)

        self.batch_nvr_edit = QPlainTextEdit()
        self.batch_nvr_edit.setPlaceholderText(
            "每行一个 NVR 管理地址，也可用逗号、分号或空格分隔\n"
            "例如：\n"
            "192.168.1.10\n"
            "192.168.1.11, 192.168.1.12"
        )
        self.batch_nvr_edit.setMinimumHeight(96)
        self.batch_nvr_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        batch_layout.addWidget(self.batch_nvr_edit)

        self.input_tabs.addTab(batch_page, "手动输入")
        self.input_tabs.addTab(csv_page, "CSV 批量")
        self.input_tabs.setMinimumHeight(210)

        action_panel = QWidget()
        action_panel.setMinimumWidth(230)
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.timeout_spin = FlatDoubleSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setDecimals(1)
        self.workers_spin = FlatSpinBox()
        self.workers_spin.setRange(1, 32)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("手动查询时填写")
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("手动查询时填写")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        settings_form = QFormLayout()
        settings_form.setContentsMargins(0, 0, 0, 0)
        settings_form.addRow("用户名", self.username_edit)
        settings_form.addRow("密码", self.password_edit)
        settings_form.addRow("超时", self.timeout_spin)
        settings_form.addRow("并发 NVR", self.workers_spin)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("开始扫描")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_scan)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_scan)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        action_layout.addLayout(settings_form)
        action_layout.addLayout(button_row)
        action_layout.addStretch(1)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_tabs, 1)
        input_row.addWidget(action_panel, 0)
        input_layout.addLayout(input_row)

        progress_row = QHBoxLayout()
        self.progress_label = QLabel("等待任务")
        self.progress_label.setObjectName("MutedLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        progress_row.addWidget(self.progress_label)
        progress_row.addWidget(self.progress_bar, 1)

        summary_row = QHBoxLayout()
        self.summary_labels = {}
        self.summary_cards = {}
        for key, label in [
            ("physical", "物理设备"),
            ("normal", "正常在线"),
            ("partial", "部分不可达"),
            ("offline", "完全离线"),
            ("unknown", "状态未知"),
            ("channels", "通道数"),
        ]:
            card = SummaryCard(
                key,
                label,
                SUMMARY_TOOLTIPS.get(key, ""),
            )
            card.clicked.connect(self._apply_summary_filter)
            self.summary_labels[key] = card.value_label
            self.summary_cards[key] = card
            summary_row.addWidget(card, 1)

        self.result_tabs = QTabWidget()
        self.device_table = self._make_table(self._device_model)
        self.summary_table = self._make_table(self._summary_model)
        self.result_tabs.addTab(self.device_table, "设备结果")
        self.result_tabs.addTab(self.summary_table, "NVR 汇总")
        self.result_tabs.setMinimumHeight(160)

        top_panel = QWidget()
        top_panel.setMinimumHeight(335)
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(input_panel)
        top_layout.addLayout(progress_row)
        top_layout.addLayout(summary_row)

        workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        workspace_splitter.addWidget(top_panel)
        workspace_splitter.addWidget(self.result_tabs)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.setStretchFactor(0, 0)
        workspace_splitter.setStretchFactor(1, 1)
        workspace_splitter.setSizes([340, 250])
        root.addWidget(workspace_splitter, 1)

        export_row = QHBoxLayout()
        export_row.addStretch(1)
        self.export_csv_button = QPushButton("导出 CSV")
        self.export_xlsx_button = QPushButton("导出 Excel")
        self.export_csv_button.setEnabled(False)
        self.export_xlsx_button.setEnabled(False)
        self.export_csv_button.clicked.connect(self._export_csv)
        self.export_xlsx_button.clicked.connect(self._export_xlsx)
        export_row.addWidget(self.export_csv_button)
        export_row.addWidget(self.export_xlsx_button)
        root.addLayout(export_row)

    @staticmethod
    def _make_table(model: DataTableModel) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setDefaultSectionSize(130)
        return table

    def refresh_settings(self) -> None:
        if self._task is not None:
            return
        self.timeout_spin.setValue(get_float("scan/timeout", 8.0))
        self.workers_spin.setValue(get_int("scan/workers", 4))
        output = get_string("scan/output_dir", str(default_output_dir()))
        self.output_edit.setText(output)
        nvr_csv = get_string("scan/nvr_csv", "")
        if not nvr_csv:
            for candidate in ("NVRdevices.csv", "NVRdevicesTest.csv"):
                path = Path.cwd() / candidate
                if path.exists():
                    nvr_csv = str(path)
                    break
        self.nvr_selector.set_path(nvr_csv)

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            self.output_edit.text().strip() or str(default_output_dir()),
        )
        if path:
            self.output_edit.setText(path)

    def _collect_nvr_devices(self) -> list[dict]:
        mode = self.input_tabs.currentIndex()
        if mode == 0:
            text = self.batch_nvr_edit.toPlainText()
            if not text.strip():
                raise ValueError("请输入至少一个 NVR 管理地址")
        else:
            nvr_csv = self.nvr_selector.path()
            if not nvr_csv:
                raise ValueError("请选择 NVR 清单 CSV 文件")
            return load_nvr_devices(nvr_csv)

        nvr_ips = parse_nvr_ip_text(text)
        if not nvr_ips:
            raise ValueError("请输入至少一个 NVR 管理地址")

        username = self.username_edit.text()
        password = self.password_edit.text()
        credential_devices = []
        if not username.strip() or not password:
            preferred_csv = (
                self.nvr_selector.path()
                or get_string("scan/nvr_csv", "")
            )
            resolved_csv = resolve_nvr_csv_path(preferred_csv)
            if resolved_csv:
                try:
                    credential_devices = load_nvr_devices(resolved_csv)
                except (OSError, ValueError):
                    credential_devices = []
                else:
                    self.nvr_selector.set_path(resolved_csv)

        return build_manual_nvr_devices(
            nvr_ips,
            username=username,
            password=password,
            credential_devices=credential_devices,
        )

    def _start_scan(self) -> None:
        if self._task is not None:
            return

        try:
            devices = self._collect_nvr_devices()
        except (OSError, ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "输入错误", str(exc))
            return

        output_dir = self.output_edit.text().strip() or str(default_output_dir())
        self.output_edit.setText(output_dir)
        if self.nvr_selector.path():
            set_string("scan/nvr_csv", self.nvr_selector.path())
        set_string("scan/output_dir", output_dir)
        set_float("scan/timeout", self.timeout_spin.value())
        set_int("scan/workers", self.workers_spin.value())

        self._payload = None
        self._device_model.clear()
        self._summary_model.clear()
        self._set_active_summary_card(None)
        self.export_csv_button.setEnabled(False)
        self.export_xlsx_button.setEnabled(False)
        self._reset_summary()
        self.progress_bar.setRange(0, len(devices))
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备扫描")
        self._set_running(True)

        task = ServiceTask(
            scan_nvrs,
            devices,
            timeout=self.timeout_spin.value(),
            max_workers=self.workers_spin.value(),
            cancel_exceptions=(ScanCancelled,),
        )
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self._task = task
        self.log_message.emit(f"开始扫描 {len(devices)} 台 NVR", "info")
        QThreadPool.globalInstance().start(task)

    def _cancel_scan(self) -> None:
        if self._task is not None:
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("正在取消，等待当前请求结束")
            self.log_message.emit("已请求取消 NVR 扫描", "warning")
            self._task.cancel()

    def _on_progress(self, event: dict) -> None:
        total = int(event.get("total", 0) or 0)
        completed = int(event.get("completed", 0) or 0)
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(completed, total))
        self.progress_label.setText(str(event.get("message", "处理中")))

    def _on_finished(self, payload: dict) -> None:
        self._task = None
        self._payload = payload
        self._set_running(False)
        self._device_model.set_rows(payload.get("rows", []))
        self._summary_model.set_rows(payload.get("summaries", []))
        self._set_active_summary_card(None)
        counts = payload.get("counts", {})
        for key, label in self.summary_labels.items():
            label.setText(str(counts.get(key, 0)))

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_label.setText(
            f"扫描完成：{payload.get('checked_nvr_count', 0)} 台 NVR，"
            f"{len(payload.get('rows', []))} 台物理设备"
        )
        self.export_csv_button.setEnabled(bool(payload.get("rows")))
        self.export_xlsx_button.setEnabled(bool(payload.get("summaries")))
        self.log_message.emit(
            f"NVR 扫描完成，发现 {len(payload.get('failures', []))} 个异常",
            "success" if not payload.get("failures") else "warning",
        )
        for duplicate in payload.get("duplicate_ips", []):
            names = "、".join(duplicate.get("names", []))
            self.log_message.emit(
                f"重复 IP：{duplicate.get('ip')} 对应 {names}",
                "warning",
            )

    def _on_failed(self, message: str) -> None:
        self._task = None
        self._set_running(False)
        self.progress_label.setText("扫描失败")
        self.log_message.emit(f"NVR 扫描失败：{message}", "error")
        QMessageBox.critical(self, "扫描失败", message)

    def _on_cancelled(self) -> None:
        self._task = None
        self._set_running(False)
        self.progress_label.setText("扫描已取消")
        self.log_message.emit("NVR 扫描已取消", "warning")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.input_tabs.setEnabled(not running)
        self.output_button.setEnabled(not running)
        self.username_edit.setEnabled(not running)
        self.password_edit.setEnabled(not running)
        self.timeout_spin.setEnabled(not running)
        self.workers_spin.setEnabled(not running)

    def _reset_summary(self) -> None:
        for label in self.summary_labels.values():
            label.setText("0")

    def _apply_summary_filter(self, key: str) -> None:
        payload = self._payload or {}
        if key == "channels":
            self.result_tabs.setCurrentWidget(self.summary_table)
            self._set_active_summary_card(key)
            return

        rows = list(payload.get("rows", []))
        status = SUMMARY_FILTERS.get(key)
        if status is not None:
            rows = [
                row
                for row in rows
                if str(row.get("状态", "")) == status
            ]
        self._device_model.set_rows(rows)
        self.result_tabs.setCurrentWidget(self.device_table)
        self._set_active_summary_card(key)

    def _set_active_summary_card(self, active_key: str | None) -> None:
        for key, card in self.summary_cards.items():
            card.setProperty("active", "true" if key == active_key else "false")
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def _export_csv(self) -> None:
        if not self._payload:
            return
        default_path = Path(self.output_edit.text()) / "nvr_scan.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CSV",
            str(default_path),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            output = export_scan_csv(self._payload, path)
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.log_message.emit(f"已导出 CSV：{output}", "success")

    def _export_xlsx(self) -> None:
        if not self._payload:
            return
        default_path = Path(self.output_edit.text()) / "nvr_scan.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Excel",
            str(default_path),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            output = export_scan_xlsx(self._payload, path)
        except (OSError, ImportError) as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.log_message.emit(f"已导出 Excel：{output}", "success")

    def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()

