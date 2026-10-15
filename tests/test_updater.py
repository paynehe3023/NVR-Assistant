# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from nvr_app.updater import (
    UpdateError,
    _manifest_from_version_json,
    _version_key,
    check_for_update,
    is_newer,
)


class UpdaterTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertEqual(_version_key("v1.2.3"), (1, 2, 3, 0))
        self.assertTrue(is_newer("1.0.1", "1.0.0"))
        self.assertFalse(is_newer("1.0.0", "1.0.0"))
        with self.assertRaises(UpdateError):
            _version_key("not-a-version")

    def test_manifest_fields(self):
        info = _manifest_from_version_json(
            {
                "version": "1.1.0",
                "download_url": "https://example.com/app.zip",
                "notes": "test",
                "published_at": "2026-10-15",
                "sha256": "sha256:" + "a" * 64,
            }
        )
        self.assertEqual(info.version, "1.1.0")
        self.assertEqual(info.sha256, "a" * 64)
        self.assertEqual(info.notes, "test")

    def test_check_for_update_reads_local_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "version.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "1.0.1",
                        "download_url": "https://example.com/app.zip",
                    }
                ),
                encoding="utf-8",
            )
            info = check_for_update("1.0.0", manifest.as_uri())
            self.assertIsNotNone(info)
            self.assertEqual(info.version, "1.0.1")
            self.assertIsNone(
                check_for_update("1.0.1", manifest.as_uri())
            )


if __name__ == "__main__":
    unittest.main()
