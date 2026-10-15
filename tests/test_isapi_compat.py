# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from nvr_app.services.isapi_compat import (
    parse_device_name,
    request_isapi,
)


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class IsapiCompatTests(unittest.TestCase):
    def test_parse_device_name(self):
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            "<deviceName>总部NVR</deviceName>"
            "</DeviceInfo>"
        ).encode("utf-8")

        self.assertEqual(parse_device_name(content), "总部NVR")

    @patch("nvr_app.services.isapi_compat.requests.get")
    def test_falls_back_to_basic_authentication(self, requests_get):
        requests_get.side_effect = [
            FakeResponse(401),
            FakeResponse(200, b"<ok/>"),
        ]

        result = request_isapi(
            "192.168.1.10",
            "/ISAPI/System/deviceInfo",
            "admin",
            "secret",
        )

        self.assertTrue(result.ok)
        self.assertIsInstance(
            requests_get.call_args_list[0].kwargs["auth"],
            HTTPDigestAuth,
        )
        self.assertIsInstance(
            requests_get.call_args_list[1].kwargs["auth"],
            HTTPBasicAuth,
        )

    @patch("nvr_app.services.isapi_compat.requests.get")
    def test_classifies_authentication_and_unsupported_errors(
        self,
        requests_get,
    ):
        requests_get.side_effect = [
            FakeResponse(401),
            FakeResponse(401),
            FakeResponse(404),
        ]

        auth_result = request_isapi(
            "192.168.1.10",
            "/ISAPI/System/deviceInfo",
            "admin",
            "bad-password",
        )
        unsupported_result = request_isapi(
            "192.168.1.10",
            "/ISAPI/Missing",
            "admin",
            "secret",
        )

        self.assertEqual(auth_result.error_code, "auth")
        self.assertEqual(unsupported_result.error_code, "unsupported")


if __name__ == "__main__":
    unittest.main()
