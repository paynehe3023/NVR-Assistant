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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nvr_app.exporters import (
    export_camera_lookup_csv,
    export_camera_lookup_xlsx,
)
from nvr_app.services.camera_lookup_service import (
    LOOKUP_CANCELLED,
    load_camera_ips_from_csv,
    lookup_camera_ips,
    parse_camera_ip_text,
    resolve_nvr_csv_path,
)
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


MATCH_COLUMNS = [
    ("摄像头IP", "摄像头IP"),
    ("查询结果", "查询结果"),
    ("NVR地址", "NVR地址"),
    ("NVR名称", "NVR名称"),
    ("通道号", "通道号"),
    ("通道名称", "通道名称"),
    ("序列号", "序列号"),
    ("在线状态", "在线状态"),
]
FAILURE_COLUMNS = [
    ("NVR地址", "NVR地址"),
    ("NVR名称", "NVR名称"),
    ("错误", "错误"),
]

SUMMARY_FILTERS = {
    "camera_count": None,
    "match_count": "已匹配",
    "missing_count": "未匹配",
}

SUMMARY_TOOLTIPS = {
    "camera_count": "点击显示全部匹配结果",
    "match_count": "点击显示已匹配的摄像头",
    "missing_count": "点击显示未匹配的摄像头",
    "failure_count": "点击显示查询异常结果",
}


class CameraLookupPage(QWidget):
    log_message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task = None
        self._payload = None
        self._result_rows = []
        self._result_model = DataTableModel(MATCH_COLUMNS)
        self._failure_model = DataTableModel(FAILURE_COLUMNS)
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
        title = QLabel("摄像头反查 NVR")
        title.setObjectName("PageTitle")
        hint = QLabel("从摄像头 IP 出发，实时查询 NVR ISAPI 通道")
        hint.setObjectName("PageHint")
        title_box.addWidget(title)
        title_box.addWidget(hint)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        root.addWidget(header)

        controls = QFrame()
        controls.setObjectName("PageHeader")
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.setVerticalSpacing(8)

        controls_layout.addWidget(QLabel("NVR 清单（必需）"), 0, 0)
        self.nvr_help_button = QToolButton()
        self.nvr_help_button.setObjectName("HelpButton")
        self.nvr_help_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MessageBoxQuestion
            )
        )
        self.nvr_help_button.setToolTip(
            "反查需要知道有哪些 NVR，并使用 NVR CSV 中的账号逐个查询。"
            "点击查看详细说明。"
        )
        self.nvr_help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nvr_help_button.clicked.connect(self._show_nvr_csv_help)
        controls_layout.addWidget(self.nvr_help_button, 0, 1)
        self.nvr_selector = PathSelector(
            "选择 NVR 清单",
            "CSV 文件 (*.csv);;所有文件 (*.*)",
        )
        controls_layout.addWidget(self.nvr_selector, 0, 2, 1, 4)

        controls_layout.addWidget(QLabel("输出目录"), 1, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        controls_layout.addWidget(self.output_edit, 1, 1, 1, 4)
        output_button = QPushButton("选择目录")
        output_button.clicked.connect(self._choose_output_dir)
        controls_layout.addWidget(output_button, 1, 5)
        root.addWidget(controls)

        input_panel = QFrame()
        input_panel.setObjectName("PageHeader")
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(14, 12, 14, 12)
        input_layout.setSpacing(8)

        self.input_tabs = QTabWidget()
        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page)
        batch_layout.setContentsMargins(10, 8, 10, 18)

        batch_toolbar = QHBoxLayout()
        batch_hint = QLabel("支持单个或多个摄像头 IP，换行、逗号、分号或空格分隔")
        batch_hint.setObjectName("MutedLabel")
        batch_toolbar.addWidget(batch_hint)
        batch_toolbar.addStretch(1)
        self.batch_ip_clear_button = QPushButton("清空")
        self.batch_ip_clear_button.clicked.connect(
            lambda: self.batch_ip_edit.clear()
        )
        batch_toolbar.addWidget(self.batch_ip_clear_button)
        batch_layout.addLayout(batch_toolbar)

        self.batch_ip_edit = QPlainTextEdit()
        self.batch_ip_edit.setPlaceholderText(
            "每行一个摄像头 IP，也可用逗号、分号或空格分隔\n"
            "例如：\n"
            "10.0.0.10\n"
            "10.0.0.11, 10.0.0.12"
        )
        self.batch_ip_edit.setMinimumHeight(96)
        self.batch_ip_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        batch_layout.addWidget(self.batch_ip_edit)

        csv_page = QWidget()
        csv_form = QFormLayout(csv_page)
        csv_form.setContentsMargins(12, 12, 12, 12)
        self.camera_csv_selector = PathSelector(
            "选择摄像头 IP 清单",
            "CSV 文件 (*.csv);;所有文件 (*.*)",
        )
        csv_form.addRow("摄像头 CSV", self.camera_csv_selector)

        self.input_tabs.addTab(batch_page, "手动输入")
        self.input_tabs.addTab(csv_page, "CSV 文件")
        self.input_tabs.setMinimumHeight(210)

        action_panel = QWidget()
        action_panel.setMinimumWidth(190)
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.timeout_spin = FlatDoubleSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setDecimals(1)
        self.workers_spin = FlatSpinBox()
        self.workers_spin.setRange(1, 32)

        button_row = QHBoxLayout()
        self.query_button = QPushButton("开始查询")
        self.query_button.setObjectName("PrimaryButton")
        self.query_button.clicked.connect(self._start_lookup)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_lookup)
        button_row.addWidget(self.query_button)
        button_row.addWidget(self.cancel_button)
        action_layout.addLayout(button_row)

        settings_form = QFormLayout()
        settings_form.setContentsMargins(0, 0, 0, 0)
        settings_form.addRow("超时", self.timeout_spin)
        settings_form.addRow("并发 NVR", self.workers_spin)
        action_layout.addLayout(settings_form)
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
            ("camera_count", "摄像头 IP"),
            ("match_count", "已匹配"),
            ("missing_count", "未匹配"),
            ("failure_count", "查询异常"),
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
        self.result_table = self._make_table(self._result_model)
        self.failure_table = self._make_table(self._failure_model)
        self.result_tabs.addTab(self.result_table, "匹配结果")
        self.result_tabs.addTab(self.failure_table, "查询异常")
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
        table.horizontalHeader().setDefaultSectionSize(135)
        return table

    def refresh_settings(self) -> None:
        if self._task is not None:
            return
        self.timeout_spin.setValue(get_float("lookup/timeout", 8.0))
        self.workers_spin.setValue(get_int("lookup/workers", 4))
        self.output_edit.setText(
            get_string("lookup/output_dir", str(default_output_dir()))
        )
        preferred_nvr_csv = (
            get_string("lookup/nvr_csv", "")
            or get_string("scan/nvr_csv", "")
        )
        self.nvr_selector.set_path(
            resolve_nvr_csv_path(preferred_nvr_csv)
        )

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            self.output_edit.text().strip() or str(default_output_dir()),
        )
        if path:
            self.output_edit.setText(path)

    def _show_nvr_csv_help(self) -> None:
        QMessageBox.information(
            self,
            "NVR 清单说明",
            "摄像头反查需要 NVR 清单，用于确定查询哪些 NVR，并提供登录 "
            "ISAPI 接口所需的 ip、username、password。\n\n"
            "查询时只实时访问这些 NVR，不读取 NVR 巡检的缓存或历史结果。"
            "摄像头 CSV 不需要填写摄像头密码。",
        )

    def _collect_camera_ips(self) -> list[str]:
        mode = self.input_tabs.currentIndex()
        if mode == 0:
            camera_ips = parse_camera_ip_text(self.batch_ip_edit.toPlainText())
            if not camera_ips:
                raise ValueError("请输入至少一个摄像头 IP 地址")
            return camera_ips

        camera_csv = self.camera_csv_selector.path()
        if not camera_csv:
            raise ValueError("请选择摄像头 IP CSV 文件")
        camera_ips = load_camera_ips_from_csv(camera_csv)
        if not camera_ips:
            raise ValueError("摄像头 CSV 中没有有效 IP 地址")
        return camera_ips

    def _start_lookup(self) -> None:
        if self._task is not None:
            return
        preferred_nvr_csv = (
            self.nvr_selector.path()
            or get_string("scan/nvr_csv", "")
        )
        nvr_csv = resolve_nvr_csv_path(preferred_nvr_csv)
        if not nvr_csv:
            nvr_csv, _ = QFileDialog.getOpenFileName(
                self,
                "选择 NVR 清单",
                str(Path.home()),
                "CSV 文件 (*.csv);;所有文件 (*.*)",
            )
            if not nvr_csv:
                QMessageBox.information(
                    self,
                    "需要 NVR 清单",
                    "反查需要通过 NVR 清单登录 NVR。请选择包含 ip、username、"
                    "password 的 CSV 文件；选择一次后程序会自动记住。",
                )
                return
        self.nvr_selector.set_path(nvr_csv)

        try:
            camera_ips = self._collect_camera_ips()
        except (OSError, ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "输入错误", str(exc))
            return

        output_dir = self.output_edit.text().strip() or str(default_output_dir())
        self.output_edit.setText(output_dir)
        set_string("lookup/nvr_csv", nvr_csv)
        set_string("lookup/output_dir", output_dir)
        set_float("lookup/timeout", self.timeout_spin.value())
        set_int("lookup/workers", self.workers_spin.value())

        self._payload = None
        self._result_rows = []
        self._result_model.clear()
        self._failure_model.clear()
        self._set_active_summary_card(None)
        self.export_csv_button.setEnabled(False)
        self.export_xlsx_button.setEnabled(False)
        self._reset_summary()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备查询")
        self._set_running(True)

        task = ServiceTask(
            lookup_camera_ips,
            camera_ips,
            csv_path=nvr_csv,
            timeout=self.timeout_spin.value(),
            max_workers=self.workers_spin.value(),
            cancel_exceptions=(LOOKUP_CANCELLED,),
        )
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self._task = task
        self.log_message.emit(
            f"开始查询 {len(camera_ips)} 个摄像头 IP",
            "info",
        )
        QThreadPool.globalInstance().start(task)

    def _cancel_lookup(self) -> None:
        if self._task is not None:
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("正在取消，等待当前请求结束")
            self.log_message.emit("已请求取消摄像头反查", "warning")
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

        result_rows = []
        match_count = 0
        query_error_count = 0
        for result in payload.get("results", []):
            camera_ip = result.get("camera_ip", "")
            matches = result.get("matches", [])
            if not matches:
                lookup_status = result.get("status", "not_found")
                if lookup_status == "query_error":
                    query_error_count += 1
                result_rows.append(
                    {
                        "摄像头IP": camera_ip,
                        "查询结果": (
                            "查询异常"
                            if lookup_status == "query_error"
                            else "未匹配"
                        ),
                        "NVR地址": "",
                        "NVR名称": "",
                        "通道号": "",
                        "通道名称": "",
                        "序列号": "",
                        "在线状态": "",
                    }
                )
                continue
            match_count += 1
            for match in matches:
                online = match.get("online")
                result_rows.append(
                    {
                        "摄像头IP": camera_ip,
                        "查询结果": "已匹配",
                        "NVR地址": match.get("nvr_ip", ""),
                        "NVR名称": match.get("nvr_name", ""),
                        "通道号": match.get("channel_id", ""),
                        "通道名称": match.get("channel_name", ""),
                        "序列号": match.get("camera_serial_number", ""),
                        "在线状态": (
                            "在线"
                            if online is True
                            else "离线"
                            if online is False
                            else "未知"
                        ),
                    }
                )

        failure_rows = [
            {
                "NVR地址": item.get("nvr_ip", ""),
                "NVR名称": item.get("nvr_name", ""),
                "错误": item.get("error", ""),
            }
            for item in payload.get("failed_nvrs", [])
        ]
        self._result_model.set_rows(result_rows)
        self._failure_model.set_rows(failure_rows)
        self._result_rows = result_rows
        self._set_active_summary_card(None)

        camera_count = len(payload.get("results", []))
        missing_count = camera_count - match_count - query_error_count
        self.summary_labels["camera_count"].setText(str(camera_count))
        self.summary_labels["match_count"].setText(str(match_count))
        self.summary_labels["missing_count"].setText(str(missing_count))
        self.summary_labels["failure_count"].setText(str(query_error_count))

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_label.setText(f"查询完成：已检查 {camera_count} 个摄像头 IP")
        self.export_csv_button.setEnabled(bool(result_rows))
        self.export_xlsx_button.setEnabled(bool(result_rows))
        self.log_message.emit(
            f"摄像头反查完成，匹配 {match_count}，未匹配 {missing_count}，"
            f"查询异常 {query_error_count}，NVR 接口异常 {len(failure_rows)}",
            "success" if not query_error_count else "warning",
        )

    def _on_failed(self, message: str) -> None:
        self._task = None
        self._set_running(False)
        self.progress_label.setText("查询失败")
        self.log_message.emit(f"摄像头反查失败：{message}", "error")
        QMessageBox.critical(self, "查询失败", message)

    def _on_cancelled(self) -> None:
        self._task = None
        self._set_running(False)
        self.progress_label.setText("查询已取消")
        self.log_message.emit("摄像头反查已取消", "warning")

    def _set_running(self, running: bool) -> None:
        self.query_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.nvr_selector.setEnabled(not running)
        self.input_tabs.setEnabled(not running)
        self.timeout_spin.setEnabled(not running)
        self.workers_spin.setEnabled(not running)

    def _reset_summary(self) -> None:
        for label in self.summary_labels.values():
            label.setText("0")

    def _apply_summary_filter(self, key: str) -> None:
        if key == "failure_count":
            error_rows = [
                row
                for row in self._result_rows
                if str(row.get("查询结果", "")) == "查询异常"
            ]
            if error_rows:
                self._result_model.set_rows(error_rows)
                self.result_tabs.setCurrentWidget(self.result_table)
            else:
                self.result_tabs.setCurrentWidget(self.failure_table)
            self._set_active_summary_card(key)
            return

        rows = list(self._result_rows)
        status = SUMMARY_FILTERS.get(key)
        if status is not None:
            rows = [
                row
                for row in rows
                if str(row.get("查询结果", "")) == status
            ]
        self._result_model.set_rows(rows)
        self.result_tabs.setCurrentWidget(self.result_table)
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
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CSV",
            str(Path(self.output_edit.text()) / "camera_nvr_lookup.csv"),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            output = export_camera_lookup_csv(self._payload, path)
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.log_message.emit(f"已导出 CSV：{output}", "success")

    def _export_xlsx(self) -> None:
        if not self._payload:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Excel",
            str(Path(self.output_edit.text()) / "camera_nvr_lookup.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            output = export_camera_lookup_xlsx(self._payload, path)
        except (OSError, ImportError) as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.log_message.emit(f"已导出 Excel：{output}", "success")

    def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()

