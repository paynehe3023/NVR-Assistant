# -*- coding: utf-8 -*-
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import requests

from camera_lookup import (
    LookupCancelled,
    fetch_nvr_channels,
    load_camera_ips,
    lookup_camera_ip,
    lookup_camera_ips,
    parse_channel_status,
    parse_input_proxy_channels,
)


CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannel>
    <id>1</id>
    <name>前门摄像头</name>
    <sourceInputPortDescriptor>
      <ipAddress>10.0.0.10</ipAddress>
    </sourceInputPortDescriptor>
    <serialNumber>CAM-001</serialNumber>
  </InputProxyChannel>
</InputProxyChannelList>
"""

STATUS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelStatusList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannelStatus>
    <id>1</id>
    <online>true</online>
    <ipAddress>10.0.0.10</ipAddress>
  </InputProxyChannelStatus>
</InputProxyChannelStatusList>
"""


class CameraLookupParserTests(unittest.TestCase):
    def test_parse_input_proxy_channels(self):
        channels = parse_input_proxy_channels(CONFIG_XML)

        self.assertEqual(channels["1"]["name"], "前门摄像头")
        self.assertEqual(channels["1"]["ips"], ["10.0.0.10"])
        self.assertEqual(channels["1"]["serial_number"], "CAM-001")

    def test_parse_channel_status(self):
        channels = parse_channel_status(STATUS_XML)

        self.assertEqual(channels["1"]["ips"], ["10.0.0.10"])
        self.assertIs(channels["1"]["online"], True)


class CameraLookupTests(unittest.TestCase):
    def test_load_camera_ips_uses_ip_column_and_ignores_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = os.path.join(temp_dir, "cameras.csv")
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as file_obj:
                file_obj.write(
                    "camera_ip,password\n"
                    "10.0.0.10,test-password\n"
                    "10.0.0.11,test-password\n"
                    "invalid-ip,test-password\n"
                )

            self.assertEqual(
                load_camera_ips(csv_path),
                ["10.0.0.10", "10.0.0.11"],
            )

    @patch("camera_lookup.fetch_nvr_channels")
    @patch("camera_lookup.load_nvr_devices")
    def test_lookup_returns_matching_nvr(self, load_devices, fetch_channels):
        load_devices.return_value = [
            {"ip": "192.168.1.10", "username": "admin", "password": "secret"}
        ]
        fetch_channels.return_value = {
            "nvr_ip": "192.168.1.10",
            "nvr_name": "",
            "channels": [
                {
                    "id": "1",
                    "name": "前门摄像头",
                    "ips": ["10.0.0.10"],
                    "serial_number": "CAM-001",
                    "online": True,
                }
            ],
            "error": None,
        }

        result = lookup_camera_ip("10.0.0.10", max_workers=1)

        self.assertEqual(result["camera_ip"], "10.0.0.10")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["nvr_ip"], "192.168.1.10")
        self.assertEqual(result["matches"][0]["channel_id"], "1")

    @patch("camera_lookup.fetch_nvr_channels")
    @patch("camera_lookup.load_nvr_devices")
    def test_lookup_multiple_cameras_queries_nvr_once(self, load_devices, fetch_channels):
        load_devices.return_value = [
            {"ip": "192.168.1.10", "username": "admin", "password": "secret"}
        ]
        fetch_channels.return_value = {
            "nvr_ip": "192.168.1.10",
            "nvr_name": "",
            "channels": [
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
                    "ips": ["10.0.0.11"],
                    "serial_number": "CAM-002",
                    "online": False,
                },
            ],
            "error": None,
        }

        result = lookup_camera_ips(
            ["10.0.0.10", "10.0.0.11"],
            max_workers=1,
        )

        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["matches"][0]["channel_id"], "1")
        self.assertEqual(result["results"][1]["matches"][0]["channel_id"], "2")
        fetch_channels.assert_called_once()

    def test_lookup_rejects_invalid_ip(self):
        with self.assertRaises(ValueError):
            lookup_camera_ip("not-an-ip")

    def test_fetch_nvr_channels_reports_missing_credentials(self):
        result = fetch_nvr_channels(
            {"ip": "192.168.1.10", "username": "admin"}
        )

        self.assertIn("缺少", result["error"])

    @patch("nvr_app.services.isapi_compat.requests.get")
    def test_fetch_nvr_channels_propagates_cancellation(self, requests_get):
        cancel_event = threading.Event()

        class FakeResponse:
            status_code = 503
            content = b""

        def fake_get(*args, **kwargs):
            cancel_event.set()
            return FakeResponse()

        requests_get.side_effect = fake_get

        with self.assertRaises(LookupCancelled):
            fetch_nvr_channels(
                {
                    "ip": "192.168.1.10",
                    "username": "admin",
                    "password": "secret",
                },
                cancel_event=cancel_event,
            )

    @patch(
        "nvr_app.services.isapi_compat.requests.get",
        side_effect=requests.Timeout("timeout"),
    )
    @patch("camera_lookup.load_nvr_devices")
    def test_lookup_reports_nvr_timeout(self, load_devices, requests_get):
        load_devices.return_value = [
            {"ip": "192.168.1.10", "username": "admin", "password": "secret"}
        ]

        result = lookup_camera_ips(["10.0.0.10"], max_workers=1)

        self.assertEqual(len(result["failed_nvrs"]), 1)
        self.assertIn("超时", result["failed_nvrs"][0]["error"])
        self.assertEqual(result["results"][0]["matches"], [])
        self.assertEqual(result["results"][0]["status"], "query_error")


if __name__ == "__main__":
    unittest.main()
