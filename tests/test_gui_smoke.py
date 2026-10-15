# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QStandardPaths, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractSpinBox, QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QStandardPaths.setTestModeEnabled(True)
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_pages_and_manual_input(self):
        from nvr_app.ui.main_window import MainWindow

        window = MainWindow()
        self.assertEqual(window.page_stack.count(), 3)
        self.assertFalse(window.windowIcon().isNull())
        window.navigation.setCurrentRow(1)
        self.assertEqual(window.page_stack.currentIndex(), 1)

        page = window.lookup_page
        page.input_tabs.setCurrentIndex(0)
        page.batch_ip_edit.setPlainText(
            "10.0.0.10\n10.0.0.11, 10.0.0.10"
        )
        self.assertEqual(page._collect_camera_ips(), ["10.0.0.10", "10.0.0.11"])
        window.close()

    def test_lookup_manual_layout_has_room_for_ips(self):
        from nvr_app.ui.main_window import MainWindow

        window = MainWindow()
        page = window.lookup_page

        self.assertGreaterEqual(page.batch_ip_edit.minimumHeight(), 96)
        self.assertGreaterEqual(page.input_tabs.minimumHeight(), 190)
        self.assertGreaterEqual(page.result_tabs.minimumHeight(), 110)
        self.assertEqual(page.input_tabs.count(), 2)
        self.assertEqual(page.input_tabs.tabText(0), "手动输入")
        self.assertEqual(page.input_tabs.tabText(1), "CSV 文件")
        self.assertIn("逐个查询", page.nvr_help_button.toolTip())
        self.assertIn("每行一个", page.batch_ip_edit.placeholderText())
        self.assertEqual(
            page.timeout_spin.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertEqual(
            page.workers_spin.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertEqual(
            page.timeout_spin.up_button.arrowType(),
            Qt.ArrowType.UpArrow,
        )
        self.assertEqual(
            page.workers_spin.down_button.arrowType(),
            Qt.ArrowType.DownArrow,
        )
        page.batch_ip_edit.setPlainText("10.0.0.10")
        page.batch_ip_clear_button.click()
        self.assertEqual(page.batch_ip_edit.toPlainText(), "")
        self.assertFalse(window.log_window.isVisible())
        window.resize(1040, 700)
        window.navigation.setCurrentRow(1)
        window.show()
        self.app.processEvents()
        page.input_tabs.setCurrentIndex(0)
        self.app.processEvents()
        batch_page = page.input_tabs.widget(0)
        self.assertLess(
            page.batch_ip_edit.geometry().bottom(),
            batch_page.rect().bottom(),
        )
        central_size = window.centralWidget().size()
        window.log_action.setChecked(True)
        self.app.processEvents()
        self.assertTrue(window.log_window.isVisible())
        self.assertEqual(window.centralWidget().size(), central_size)
        window.log_action.setChecked(False)
        self.app.processEvents()
        self.assertFalse(window.log_window.isVisible())
        window.close()

    def test_nvr_scan_has_manual_and_csv_modes(self):
        from nvr_app.ui.main_window import MainWindow

        window = MainWindow()
        page = window.scan_page
        self.assertEqual(page.input_tabs.count(), 2)
        self.assertEqual(page.input_tabs.tabText(0), "手动输入")
        self.assertEqual(page.input_tabs.tabText(1), "CSV 批量")
        self.assertGreaterEqual(page.batch_nvr_edit.minimumHeight(), 96)
        self.assertGreaterEqual(page.input_tabs.minimumHeight(), 190)
        self.assertIn("每行一个", page.batch_nvr_edit.placeholderText())
        self.assertEqual(
            page.timeout_spin.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertEqual(
            page.workers_spin.buttonSymbols(),
            QAbstractSpinBox.ButtonSymbols.NoButtons,
        )
        self.assertTrue(page.timeout_spin.up_button.isEnabled())
        self.assertTrue(page.workers_spin.down_button.isEnabled())

        page.input_tabs.setCurrentIndex(0)
        page.batch_nvr_edit.setPlainText(
            "192.168.1.10\n192.168.1.11, 192.168.1.10"
        )
        page.username_edit.setText("admin")
        page.password_edit.setText("secret")
        devices = page._collect_nvr_devices()
        self.assertEqual(
            [device["ip"] for device in devices],
            ["192.168.1.10", "192.168.1.11"],
        )
        page.batch_nvr_clear_button.click()
        self.assertEqual(page.batch_nvr_edit.toPlainText(), "")
        self.assertGreaterEqual(page.result_tabs.minimumHeight(), 110)
        window.resize(1040, 700)
        window.navigation.setCurrentRow(0)
        window.show()
        self.app.processEvents()
        page.input_tabs.setCurrentIndex(0)
        self.app.processEvents()
        batch_page = page.input_tabs.widget(0)
        self.assertLess(
            page.batch_nvr_edit.geometry().bottom(),
            batch_page.rect().bottom(),
        )
        window.close()

    def test_summary_cards_filter_scan_results(self):
        from nvr_app.ui.main_window import MainWindow

        window = MainWindow()
        page = window.scan_page
        payload = {
            "rows": [
                {
                    "所属NVR": "192.168.1.10",
                    "监控设备名称": "大厅",
                    "IP地址": "10.0.0.1",
                    "通道属性": "单通道",
                    "对应/异常通道": "D1",
                    "状态": "正常在线",
                },
                {
                    "所属NVR": "192.168.1.10",
                    "监控设备名称": "仓库",
                    "IP地址": "10.0.0.2",
                    "通道属性": "单通道",
                    "对应/异常通道": "D2",
                    "状态": "网络不可达",
                },
                {
                    "所属NVR": "192.168.1.10",
                    "监控设备名称": "走廊",
                    "IP地址": "10.0.0.3",
                    "通道属性": "单通道",
                    "对应/异常通道": "D3",
                    "状态": "状态未知",
                },
            ],
            "summaries": [
                {"NVR地址": "192.168.1.10", "NVR名称": "总部NVR"},
            ],
        }
        page._payload = payload
        page._device_model.set_rows(payload["rows"])
        page._summary_model.set_rows(payload["summaries"])

        QTest.mouseClick(
            page.summary_cards["normal"],
            Qt.MouseButton.LeftButton,
        )
        self.assertIs(page.result_tabs.currentWidget(), page.device_table)
        self.assertEqual(page._device_model.rowCount(), 1)
        self.assertEqual(
            page._device_model.rows[0]["IP地址"],
            "10.0.0.1",
        )
        self.assertEqual(
            page.summary_cards["normal"].property("active"),
            "true",
        )

        QTest.mouseClick(
            page.summary_cards["offline"],
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(page._device_model.rowCount(), 1)
        self.assertEqual(
            page._device_model.rows[0]["IP地址"],
            "10.0.0.2",
        )

        QTest.mouseClick(
            page.summary_cards["physical"],
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(page._device_model.rowCount(), 3)

        QTest.mouseClick(
            page.summary_cards["channels"],
            Qt.MouseButton.LeftButton,
        )
        self.assertIs(page.result_tabs.currentWidget(), page.summary_table)
        window.close()

    def test_lookup_summary_cards_filter_results(self):
        from nvr_app.ui.main_window import MainWindow

        window = MainWindow()
        page = window.lookup_page
        rows = [
            {
                "摄像头IP": "10.0.0.1",
                "查询结果": "已匹配",
                "NVR地址": "192.168.1.10",
                "NVR名称": "总部NVR",
                "通道号": "1",
                "通道名称": "大厅",
                "序列号": "SN-1",
                "在线状态": "在线",
            },
            {
                "摄像头IP": "10.0.0.2",
                "查询结果": "未匹配",
                "NVR地址": "",
                "NVR名称": "",
                "通道号": "",
                "通道名称": "",
                "序列号": "",
                "在线状态": "",
            },
            {
                "摄像头IP": "10.0.0.3",
                "查询结果": "查询异常",
                "NVR地址": "",
                "NVR名称": "",
                "通道号": "",
                "通道名称": "",
                "序列号": "",
                "在线状态": "",
            },
        ]
        page._result_rows = rows
        page._result_model.set_rows(rows)
        page._failure_model.set_rows(
            [
                {
                    "NVR地址": "192.168.1.11",
                    "NVR名称": "分部NVR",
                    "错误": "连接超时",
                }
            ]
        )

        QTest.mouseClick(
            page.summary_cards["match_count"],
            Qt.MouseButton.LeftButton,
        )
        self.assertIs(page.result_tabs.currentWidget(), page.result_table)
        self.assertEqual(page._result_model.rowCount(), 1)
        self.assertEqual(page._result_model.rows[0]["摄像头IP"], "10.0.0.1")

        QTest.mouseClick(
            page.summary_cards["failure_count"],
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(page._result_model.rowCount(), 1)
        self.assertEqual(page._result_model.rows[0]["摄像头IP"], "10.0.0.3")

        page._result_rows = rows[:2]
        QTest.mouseClick(
            page.summary_cards["failure_count"],
            Qt.MouseButton.LeftButton,
        )
        self.assertIs(page.result_tabs.currentWidget(), page.failure_table)

        QTest.mouseClick(
            page.summary_cards["camera_count"],
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(page._result_model.rowCount(), 2)
        window.close()

    def test_resolve_nvr_csv_path_uses_existing_preferred_file(self):
        from nvr_app.services.camera_lookup_service import resolve_nvr_csv_path

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "NVRdevices.csv"
            path.write_text(
                "ip,username,password\n192.168.1.10,admin,secret\n",
                encoding="utf-8",
            )

            self.assertEqual(str(path.resolve()), resolve_nvr_csv_path(str(path)))


if __name__ == "__main__":
    unittest.main()

