import importlib.util
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import paths


def load_quota_module():
    spec = importlib.util.spec_from_file_location(
        "buzz_quota_test", os.path.join(ROOT, "bin", "buzz_quota.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V1WslUtf8Tests(unittest.TestCase):
    @mock.patch("paths.subprocess.run")
    def test_v1_wsl_output_is_always_decoded_as_utf8(self, run):
        paths.wsl_run(["printf", "Tiếng Việt"])

        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")


class V2FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.quota = load_quota_module()

    @mock.patch("paths.wsl_run")
    def test_v2_empty_wsl_dump_is_failure(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        self.assertIsNone(self.quota.fetch_linux_via_wsl())

    @mock.patch("paths.wsl_run")
    def test_v2_invalid_wsl_json_is_failure(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="not-json", stderr="")
        self.assertIsNone(self.quota.fetch_linux_via_wsl())

    @mock.patch("paths.windows_codex_homes", return_value=[])
    @mock.patch("paths.in_windows", return_value=True)
    def test_v2_collect_aborts_instead_of_using_windows_only(self, _win, _homes):
        with mock.patch.object(self.quota, "fetch_linux_via_wsl", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "keeping last-known-good"):
                self.quota.collect_all()


if __name__ == "__main__":
    unittest.main()
