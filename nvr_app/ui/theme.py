APP_STYLESHEET = """
QWidget {
    color: #223142;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#AppRoot {
    background: #F3F6F8;
}
QFrame#Sidebar {
    background: #1F3448;
    border: none;
}
QLabel#BrandTitle {
    color: #FFFFFF;
    font-size: 18px;
    font-weight: 700;
}
QLabel#BrandSubtitle {
    color: #AFC1D1;
    font-size: 11px;
}
QLabel#BrandIcon {
    background: transparent;
}
QListWidget#Navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 6px 10px;
}
QListWidget#Navigation::item {
    color: #D7E3EC;
    border-radius: 6px;
    padding: 11px 12px;
    margin: 3px 0;
}
QListWidget#Navigation::item:selected {
    background: #2F6F91;
    color: #FFFFFF;
}
QListWidget#Navigation::item:hover:!selected {
    background: #2A465E;
}
QFrame#PageHeader {
    background: #FFFFFF;
    border: 1px solid #DCE4EA;
    border-radius: 6px;
}
QLabel#PageTitle {
    font-size: 20px;
    font-weight: 700;
    color: #172B3A;
}
QLabel#SectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #172B3A;
}
QLabel#PageHint, QLabel#MutedLabel {
    color: #607587;
}
QLabel#SummaryValue {
    color: #1F5E83;
    font-size: 18px;
    font-weight: 700;
}
QLabel#SummaryName {
    color: #6B7E8D;
    font-size: 11px;
}
QFrame#SummaryItem {
    background: #F8FAFB;
    border: 1px solid #DCE4EA;
    border-radius: 6px;
}
QFrame#SummaryItem:hover {
    background: #F1F7FA;
    border-color: #8FB4C8;
}
QFrame#SummaryItem[active="true"] {
    background: #E6F2F8;
    border-color: #2F789C;
}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF;
    border: 1px solid #C9D5DE;
    border-radius: 5px;
    padding: 6px 8px;
    selection-background-color: #2F6F91;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #2F6F91;
}
QSpinBox, QDoubleSpinBox {
    min-height: 24px;
}
QSpinBox#FlatSpinInput, QDoubleSpinBox#FlatSpinInput {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}
QWidget#SpinArrowBox {
    background: transparent;
}
QToolButton#SpinArrowButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 15px;
    max-height: 15px;
    padding: 0;
    border: 1px solid #C9D5DE;
    background: #F7FAFC;
    color: #30495C;
}
QToolButton#SpinArrowButton:hover {
    background: #E4EFF5;
    border-color: #8FB4C8;
}
QToolButton#SpinArrowButton:pressed {
    background: #D4E6EF;
}
QLineEdit[readOnly="true"] {
    background: #F6F8F9;
    color: #4F6373;
}
QPushButton {
    min-height: 30px;
    padding: 0 14px;
    border: 1px solid #C5D1DA;
    border-radius: 5px;
    background: #FFFFFF;
}
QPushButton:hover {
    background: #F2F7FA;
    border-color: #92A9BA;
}
QPushButton:pressed {
    background: #E7EFF4;
}
QPushButton:disabled {
    color: #9AA9B4;
    background: #F1F3F5;
    border-color: #DCE2E7;
}
QPushButton#PrimaryButton {
    color: #FFFFFF;
    background: #236B91;
    border-color: #236B91;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background: #1C5D80;
}
QPushButton#DangerButton {
    color: #9C2F2F;
    border-color: #E3B7B7;
    background: #FFF8F8;
}
QToolButton#HelpButton {
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
    border: 1px solid #C5D1DA;
    border-radius: 11px;
    background: #FFFFFF;
}
QToolButton#HelpButton:hover {
    background: #F2F7FA;
    border-color: #92A9BA;
}
QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #DCE4EA;
    border-radius: 5px;
    top: -1px;
}
QTabBar::tab {
    background: #E8EEF2;
    color: #536979;
    border: 1px solid #D7E0E6;
    border-bottom: none;
    padding: 7px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1C5D80;
    font-weight: 600;
}
QTableView {
    background: #FFFFFF;
    alternate-background-color: #F7F9FA;
    border: 1px solid #DCE4EA;
    border-radius: 5px;
    gridline-color: #E6ECF0;
    selection-background-color: #D8EAF4;
    selection-color: #172B3A;
}
QHeaderView::section {
    background: #EAF0F4;
    color: #30495C;
    border: none;
    border-right: 1px solid #D6E0E6;
    border-bottom: 1px solid #D6E0E6;
    padding: 7px 6px;
    font-weight: 600;
}
QProgressBar {
    min-height: 8px;
    max-height: 8px;
    border: none;
    border-radius: 4px;
    background: #E3E9ED;
    text-align: center;
}
QProgressBar::chunk {
    border-radius: 4px;
    background: #2F789C;
}
QDockWidget {
    color: #30495C;
    font-weight: 600;
}
QDockWidget::title {
    background: #E8EEF2;
    padding: 7px;
}
QPlainTextEdit#LogView {
    background: #182632;
    color: #DCE7EC;
    border: none;
    border-radius: 0;
    font-family: Consolas, monospace;
    font-size: 12px;
}
QStatusBar {
    background: #FFFFFF;
    border-top: 1px solid #DCE4EA;
}
"""

