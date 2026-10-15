# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from nvr_app.updater import (
    UpdateError,
    _manifest_from_version_json,
    _version_key,
    apply_update,
    check_for_update,
    cleanup_update_runners,
    is_newer,
    launch_update,
    prepare_update_runner,
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

    def test_apply_update_replaces_legacy_onedir_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "NVR Assistant"
            target.mkdir()
            (target / "NVR Assistant.exe").write_bytes(b"old")
            (target / "_internal").mkdir()
            (target / "_internal" / "old.dll").write_bytes(b"old")
            (target / "old.txt").write_text("old", encoding="utf-8")

            payload = root / "payload"
            (payload / "NVR Assistant").mkdir(parents=True)
            (payload / "NVR Assistant" / "NVR Assistant.exe").write_bytes(
                b"new"
            )
            (payload / "NVR Assistant" / "_internal").mkdir()
            (payload / "NVR Assistant" / "_internal" / "new.dll").write_bytes(
                b"new"
            )
            (payload / "NVR Assistant" / "new.txt").write_text(
                "new",
                encoding="utf-8",
            )
            archive = root / "update.zip"
            payload_root = payload / "NVR Assistant"
            with ZipFile(archive, "w") as zip_file:
                for file_path in payload_root.rglob("*"):
                    if not file_path.is_file():
                        continue
                    zip_file.write(
                        file_path,
                        (
                            Path("NVR Assistant")
                            / file_path.relative_to(payload_root)
                        ).as_posix(),
                    )

            apply_update(
                archive,
                target,
                parent_pid=0,
                restart=False,
                mode="onedir",
            )

            self.assertEqual(
                (target / "NVR Assistant.exe").read_bytes(),
                b"new",
            )
            self.assertTrue((target / "new.txt").is_file())
            self.assertTrue((target / "_internal" / "new.dll").is_file())
            self.assertFalse((target / "_internal" / "old.dll").exists())
            self.assertFalse((target / "old.txt").exists())
            self.assertFalse((target / "NVRUpdater.exe").exists())

    def test_apply_update_replaces_only_onefile_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "Desktop"
            target.mkdir()
            target_exe = target / "NVR Assistant.exe"
            target_exe.write_bytes(b"old")
            (target / "user-notes.txt").write_text(
                "keep",
                encoding="utf-8",
            )

            archive = root / "update.zip"
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("NVR Assistant.exe", b"new")
                zip_file.writestr("README.txt", b"do not install")
                zip_file.writestr("_internal/runtime.dll", b"do not install")

            apply_update(
                archive,
                target,
                parent_pid=0,
                restart=False,
                mode="onefile",
            )

            self.assertEqual(target_exe.read_bytes(), b"new")
            self.assertEqual(
                (target / "user-notes.txt").read_text(encoding="utf-8"),
                "keep",
            )
            self.assertFalse((target / "README.txt").exists())
            self.assertFalse((target / "_internal").exists())
            self.assertFalse((target / "NVRUpdater.exe").exists())

    def test_apply_update_finds_onefile_executable_in_subdirectory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "Tools"
            target.mkdir()
            target_exe = target / "NVR Assistant.exe"
            target_exe.write_bytes(b"old")

            archive = root / "update.zip"
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "release/NVR Assistant.exe",
                    b"new",
                )

            apply_update(
                archive,
                target,
                parent_pid=0,
                restart=False,
                mode="onefile",
            )

            self.assertEqual(target_exe.read_bytes(), b"new")

    def test_prepare_update_runner_copies_legacy_onedir_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "NVR Assistant"
            target.mkdir()
            (target / "NVR Assistant.exe").write_bytes(b"app")
            (target / "_internal").mkdir()

            current_exe = root / "current.exe"
            current_exe.write_bytes(b"runner")
            internal = root / "_internal"
            internal.mkdir()
            (internal / "runtime.dll").write_bytes(b"runtime")
            (internal / "nested").mkdir()
            (internal / "nested" / "data.bin").write_bytes(b"data")

            with (
                patch.object(sys, "executable", str(current_exe)),
                patch.object(
                    sys,
                    "_MEIPASS",
                    str(internal),
                    create=True,
                ),
            ):
                runner = prepare_update_runner(target, "onedir")

            self.assertEqual(runner.read_bytes(), b"runner")
            self.assertEqual(
                (runner.parent / "_internal" / "runtime.dll").read_bytes(),
                b"runtime",
            )
            self.assertTrue(
                (runner.parent / "_internal" / "nested" / "data.bin")
                .is_file()
            )

    def test_prepare_onefile_update_runner_copies_only_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "Desktop"
            target.mkdir()
            (target / "NVR Assistant.exe").write_bytes(b"app")

            current_exe = root / "current.exe"
            current_exe.write_bytes(b"runner")
            extracted_runtime = root / "_MEI12345"
            extracted_runtime.mkdir()
            (extracted_runtime / "runtime.dll").write_bytes(b"runtime")

            with (
                patch.object(sys, "executable", str(current_exe)),
                patch.object(
                    sys,
                    "_MEIPASS",
                    str(extracted_runtime),
                    create=True,
                ),
            ):
                runner = prepare_update_runner(target, "onefile")

            self.assertEqual(runner.read_bytes(), b"runner")
            self.assertFalse((runner.parent / "_internal").exists())
            self.assertFalse((runner.parent / "runtime.dll").exists())

    def test_launch_update_uses_temporary_main_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "NVR Assistant"
            target.mkdir()
            target_exe = target / "NVR Assistant.exe"
            target_exe.write_bytes(b"app")
            runner = root / ".NVR Assistant.runner-test" / "NVR Assistant.exe"
            archive = root / "update.zip"
            archive.write_bytes(b"zip")

            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(target_exe)),
                patch(
                    "nvr_app.updater.prepare_update_runner",
                    return_value=runner,
                ) as prepare_mock,
                patch("nvr_app.updater.subprocess.Popen") as popen_mock,
            ):
                result = launch_update(archive)

            self.assertEqual(result, runner)
            prepare_mock.assert_called_once_with(target, "onefile")
            command = popen_mock.call_args.args[0]
            self.assertEqual(command[0], str(runner))
            self.assertEqual(command[1], "--apply-update")
            self.assertEqual(command[2], str(archive))
            self.assertEqual(command[3], str(target))
            self.assertEqual(command[-1], "onefile")
            self.assertNotIn("NVRUpdater.exe", " ".join(command))

    def test_cleanup_update_runners_removes_only_runner_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "NVR Assistant"
            target.mkdir()
            runner_a = root / ".NVR Assistant.runner-a"
            runner_b = root / ".NVR Assistant.runner-b"
            unrelated = root / "keep"
            runner_a.mkdir()
            runner_b.mkdir()
            unrelated.mkdir()

            cleanup_update_runners(target)

            self.assertFalse(runner_a.exists())
            self.assertFalse(runner_b.exists())
            self.assertTrue(unrelated.is_dir())


if __name__ == "__main__":
    unittest.main()
