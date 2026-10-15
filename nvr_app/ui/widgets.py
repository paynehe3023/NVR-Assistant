from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class DataTableModel(QAbstractTableModel):
    def __init__(self, columns: list[tuple[str, str]], rows=None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = list(rows or [])

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = self.columns[index.column()][1]
        value = row.get(key, "")

        if role == Qt.ItemDataRole.DisplayRole:
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            status = str(row.get("状态") or row.get("查询结果", ""))
            if status in {"正常在线", "正常", "在线", "已匹配"}:
                return QBrush(QColor("#246B45"))
            if status in {"部分不可达", "状态未知", "异常", "未知"}:
                return QBrush(QColor("#9A6200"))
            if status in {"网络不可达", "离线", "查询异常"}:
                return QBrush(QColor("#A22E2E"))
        if role == Qt.ItemDataRole.BackgroundRole:
            status = str(row.get("状态", row.get("查询结果", "")))
            if status in {"正常在线", "正常", "在线", "已匹配"}:
                return QBrush(QColor("#E5F5EB"))
            if status in {"部分不可达", "状态未知", "异常", "未知"}:
                return QBrush(QColor("#FFF3D6"))
            if status in {"网络不可达", "离线", "查询异常"}:
                return QBrush(QColor("#FBE3E3"))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.columns[section][0]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])


class SummaryCard(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        label: str,
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.key = key
        self.setObjectName("SummaryItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(tooltip or "点击查看查询结果")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("SummaryValue")
        self.name_label = QLabel(label)
        self.name_label.setObjectName("SummaryName")
        for child in (self.value_label, self.name_label):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                True,
            )
        layout.addWidget(self.value_label)
        layout.addWidget(self.name_label)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        }:
            self.clicked.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)


class PathSelector(QWidget):
    def __init__(self, dialog_title: str, file_filter: str, parent=None):
        super().__init__(parent)
        self.dialog_title = dialog_title
        self.file_filter = file_filter
        self.line_edit = QLineEdit()
        self.line_edit.setReadOnly(True)
        self.button = QPushButton("浏览")
        self.button.clicked.connect(self.browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.button)

    def browse(self) -> None:
        start = self.line_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.dialog_title,
            start,
            self.file_filter,
        )
        if path:
            self.line_edit.setText(path)

    def path(self) -> str:
        return self.line_edit.text().strip()

    def set_path(self, path: str) -> None:
        self.line_edit.setText(path or "")


class _FlatSpinBoxBase(QWidget):
    """Spin box with consistently visible flat step buttons."""

    def __init__(
        self,
        spin_box: QSpinBox | QDoubleSpinBox,
        parent=None,
    ):
        super().__init__(parent)
        self._spin_box = spin_box
        self._spin_box.setObjectName("FlatSpinInput")
        self._spin_box.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self._spin_box.setMinimumHeight(30)
        self._spin_box.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        arrow_box = QWidget(self)
        arrow_box.setObjectName("SpinArrowBox")
        arrow_box.setFixedWidth(24)
        arrow_layout = QVBoxLayout(arrow_box)
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        arrow_layout.setSpacing(0)

        self.up_button = self._make_arrow_button(
            Qt.ArrowType.UpArrow,
            "增加",
        )
        self.down_button = self._make_arrow_button(
            Qt.ArrowType.DownArrow,
            "减少",
        )
        self.up_button.clicked.connect(self._spin_box.stepUp)
        self.down_button.clicked.connect(self._spin_box.stepDown)
        arrow_layout.addWidget(self.up_button)
        arrow_layout.addWidget(self.down_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._spin_box, 1)
        layout.addWidget(arrow_box, 0)

    @staticmethod
    def _make_arrow_button(
        arrow: Qt.ArrowType,
        tooltip: str,
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("SpinArrowButton")
        button.setArrowType(arrow)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(False)
        button.setFixedSize(24, 15)
        return button

    def value(self):
        return self._spin_box.value()

    def setValue(self, value) -> None:
        self._spin_box.setValue(value)

    def setRange(self, minimum, maximum) -> None:
        self._spin_box.setRange(minimum, maximum)

    def setSingleStep(self, step) -> None:
        self._spin_box.setSingleStep(step)

    def setSuffix(self, suffix: str) -> None:
        self._spin_box.setSuffix(suffix)

    def setDecimals(self, decimals: int) -> None:
        setter = getattr(self._spin_box, "setDecimals", None)
        if setter is not None:
            setter(decimals)

    def buttonSymbols(self):
        return QAbstractSpinBox.ButtonSymbols.NoButtons

    def stepUp(self) -> None:
        self._spin_box.stepUp()

    def stepDown(self) -> None:
        self._spin_box.stepDown()


class FlatSpinBox(_FlatSpinBoxBase):
    def __init__(self, parent=None):
        super().__init__(QSpinBox(), parent)


class FlatDoubleSpinBox(_FlatSpinBoxBase):
    def __init__(self, parent=None):
        super().__init__(QDoubleSpinBox(), parent)

