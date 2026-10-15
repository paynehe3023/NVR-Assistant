# -*- coding: utf-8 -*-
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from nvr_app.services.nvr_scan_service import (
    ScanCancelled,
    build_manual_nvr_devices,
    group_channels,
    load_nvr_devices,
    parse_channel_config,
    parse_channel_status,
    parse_nvr_ip_text,
    scan_nvr,
    scan_nvrs,
)


CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannel>
    <id>1</id>
    <name>前门摄像头</name>
    <ipAddress>10.0.0.10</ipAddress>
    <serialNumber>CAM-001</serialNumber>
  </InputProxyChannel>
  <InputProxyChannel>
    <id>2</id>
    <name>后门摄像头</name>
    <ipAddress>10.0.0.11</ipAddress>
    <serialNumber>CAM-002</serialNumber>
  </InputProxyChannel>
</InputProxyChannelList>
"""

STATUS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelStatusList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannelStatus>
    <id>1</id>
    <online>true</online>
  </InputProxyChannelStatus>
  <InputProxyChannelStatus>
    <id>2</id>
    <online>false</online>
  </InputProxyChannelStatus>
</InputProxyChannelStatusList>
"""

DEVICE_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <deviceName>总部NVR</deviceName>
</DeviceInfo>
"""


class FakeResponse:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content


class NvrScanParserTests(unittest.TestCase):
    def test_parse_config_and_status(self):
        channels = parse_channel_config(CONFIG_XML)
        for channel in parse_channel_status(STATUS_XML).values():
            channels[channel["id"]].update({"online": channel["online"]})

        self.assertEqual(channels["1"]["name"], "前门摄像头")
        self.assertEqual(channels["1"]["ips"], ["10.0.0.10"])
        self.assertTrue(channels["1"]["online"])
        self.assertFalse(channels["2"]["online"])

    def test_group_channels_detects_partial_status_and_duplicate_ip(self):
        rows, duplicates = group_channels(
            "192.168.1.10",
            [
                {
                    "id": "1",
                    "name": "前门摄像头",
                    "ips": ["10.0.0.10"],
                    "serial_number": "CAM-001",
                    "online": True,
                },
                {
                    "id": "2",
                    "name": "后门摄像头",
                    "ips": ["10.0.0.10"],
                    "serial_number": "CAM-001",
                    "online": False,
                },
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["通道属性"], "双通道")
        self.assertEqual(rows[0]["状态"], "部分不可达")
        self.assertEqual(duplicates[0]["ip"], "10.0.0.10")

    @patch("nvr_app.services.isapi_compat.requests.get")
    def test_scan_nvr_returns_report_rows(self, requests_get):
        requests_get.side_effect = [
            FakeResponse(200, CONFIG_XML.encode("utf-8")),
            FakeResponse(200, STATUS_XML.encode("utf-8")),
            FakeResponse(200, DEVICE_INFO_XML.encode("utf-8")),
        ]

        result = scan_nvr(
            {
                "ip": "192.168.1.10",
                "username": "admin",
                "password": "secret",
            }
        )

        self.assertEqual(result["counts"]["physical"], 2)
        self.assertEqual(result["counts"]["normal"], 1)
        self.assertEqual(result["counts"]["offline"], 1)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["nvr_name"], "总部NVR")
        self.assertNotIn("password", result["rows"][0])

    def test_scan_nvr_rejects_missing_credentials(self):
        result = scan_nvr({"ip": "192.168.1.10"})
        self.assertIn("缺少字段", result["error"])

    @patch(
        "nvr_app.services.isapi_compat.requests.get",
        side_effect=requests.Timeout("timeout"),
    )
    def test_scan_nvr_reports_timeout_in_chinese(self, requests_get):
        result = scan_nvr(
            {
                "ip": "192.168.1.10",
                "username": "admin",
                "password": "secret",
            }
        )

        self.assertIn("请求超时", result["error"])

    @patch("nvr_app.services.isapi_compat.requests.get")
    def test_scan_nvr_marks_unknown_when_status_endpoint_fails(
        self,
        requests_get,
    ):
        requests_get.side_effect = [
            FakeResponse(200, CONFIG_XML.encode("utf-8")),
            FakeResponse(404, b""),
        ]

        result = scan_nvr(
            {
                "ip": "192.168.1.10",
                "name": "总部NVR",
                "username": "admin",
                "password": "secret",
            }
        )

        self.assertEqual(result["counts"]["unknown"], 2)
        self.assertEqual(result["rows"][0]["状态"], "状态未知")
        self.assertIn("不支持", result["error"])

    def test_scan_nvr_honors_cancelled_event(self):
        cancel_event = threading.Event()
        cancel_event.set()
        with self.assertRaises(ScanCancelled):
            scan_nvr(
                {
                    "ip": "192.168.1.10",
                    "username": "admin",
                    "password": "secret",
                },
                cancel_event=cancel_event,
            )

    def test_load_nvr_devices_accepts_chinese_headers_and_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "NVRdevices.csv"
            path.write_text(
                "NVR名称,管理地址,用户名,密码\n"
                "总部NVR,192.168.1.10,admin,secret\n",
                encoding="utf-8",
            )

            devices = load_nvr_devices(str(path))

        self.assertEqual(devices[0]["ip"], "192.168.1.10")
        self.assertEqual(devices[0]["name"], "总部NVR")
        self.assertEqual(devices[0]["username"], "admin")

    def test_parse_nvr_ip_text_deduplicates_and_validates(self):
        self.assertEqual(
            parse_nvr_ip_text("192.168.1.10\n192.168.1.11, 192.168.1.10"),
            ["192.168.1.10", "192.168.1.11"],
        )
        with self.assertRaisesRegex(ValueError, "格式不正确"):
            parse_nvr_ip_text("not-an-ip")

    def test_build_manual_nvr_devices_uses_csv_credentials(self):
        devices = build_manual_nvr_devices(
            ["192.168.1.10"],
            credential_devices=[
                {
                    "ip": "192.168.1.10",
                    "username": "admin",
                    "password": "secret",
                    "name": "总部NVR",
                }
            ],
        )

        self.assertEqual(devices[0]["name"], "总部NVR")
        self.assertEqual(devices[0]["username"], "admin")
        self.assertEqual(devices[0]["password"], "secret")

    @patch("nvr_app.services.nvr_scan_service.scan_nvr")
    def test_scan_nvrs_reports_progress(self, scan_one):
        def fake_scan(nvr, timeout=8, cancel_event=None):
            return {
                "nvr_ip": nvr["ip"],
                "nvr_name": nvr.get("name", ""),
                "rows": [],
                "duplicate_ips": [],
                "error": "",
                "counts": {
                    "normal": 0,
                    "partial": 0,
                    "offline": 0,
                    "unknown": 0,
                    "physical": 0,
                    "channels": 0,
                },
            }

        scan_one.side_effect = fake_scan
        events = []
        payload = scan_nvrs(
            [
                {
                    "ip": "192.168.1.10",
                    "name": "总部NVR",
                    "username": "a",
                    "password": "b",
                },
                {
                    "ip": "192.168.1.11",
                    "name": "分部NVR",
                    "username": "a",
                    "password": "b",
                },
            ],
            max_workers=2,
            progress=events.append,
        )

        self.assertEqual(payload["checked_nvr_count"], 2)
        self.assertEqual(events[-1]["phase"], "finished")
        self.assertEqual(payload["summaries"][0]["NVR名称"], "总部NVR")
        self.assertEqual(payload["summaries"][1]["NVR名称"], "分部NVR")


if __name__ == "__main__":
    unittest.main()

