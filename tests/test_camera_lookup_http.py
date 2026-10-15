# -*- coding: utf-8 -*-
import csv
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from camera_lookup import lookup_camera_ips


CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannel>
    <id>1</id>
    <name>测试摄像头</name>
    <ipAddress>10.9.9.10</ipAddress>
    <serialNumber>CAM-TEST</serialNumber>
  </InputProxyChannel>
</InputProxyChannelList>
"""

STATUS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelStatusList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannelStatus>
    <id>1</id>
    <online>true</online>
  </InputProxyChannelStatus>
</InputProxyChannelStatusList>
"""


class FakeIsapiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/channels/status"):
            content = STATUS_XML.encode("utf-8")
        else:
            content = CONFIG_XML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        return


class CameraLookupHttpTests(unittest.TestCase):
    def test_lookup_uses_live_isapi_without_local_history(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeIsapiHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                nvr_csv = os.path.join(temp_dir, "nvr.csv")
                with open(nvr_csv, "w", encoding="utf-8-sig", newline="") as file_obj:
                    writer = csv.writer(file_obj)
                    writer.writerow(["ip", "username", "password"])
                    writer.writerow(
                        [f"127.0.0.1:{server.server_port}", "admin", "secret"]
                    )

                events = []
                result = lookup_camera_ips(
                    ["10.9.9.10"],
                    csv_path=nvr_csv,
                    timeout=2,
                    max_workers=1,
                    progress=events.append,
                )
        finally:
            server.shutdown()
            server.server_close()

        self.assertTrue(
            result["results"][0]["matches"][0]["nvr_ip"].startswith("127.0.0.1:")
        )
        self.assertEqual(events[-1]["phase"], "finished")


if __name__ == "__main__":
    unittest.main()

