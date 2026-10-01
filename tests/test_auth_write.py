# -*- coding: utf-8 -*-
"""Kiem tra ham ghi auth.json cua buzz_quota.

Ba dieu phai dung, vi sai bat ky dieu nao cung lam ca dan agent chet lang:
  1. last_refresh phai co hau to "Z" (RFC3339) — thieu thi Codex coi file la hong.
  2. Quyen file phai giu nguyen 0600 — file chua refresh_token.
  3. Khong de lai file tam.
"""
import json
import os
import re
import stat
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, BIN)

import buzz_quota  # noqa: E402

RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class WriteAuthTokensTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "auth.json")
        blob = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {"access_token": "cu", "refresh_token": "rt-cu", "id_token": "id-cu"},
            "last_refresh": "2026-09-01T00:00:00Z",
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(blob, fh)
        os.chmod(self.path, 0o600)

    def test_giu_hau_to_Z_trong_last_refresh(self):
        buzz_quota.write_auth_tokens(self.path, {"access_token": "moi", "refresh_token": "rt-moi"})
        got = json.load(open(self.path, encoding="utf-8"))
        self.assertRegex(got["last_refresh"], RFC3339_Z,
                         "last_refresh thieu hau to Z -> Codex se coi auth.json la hong")

    def test_giu_quyen_0600(self):
        buzz_quota.write_auth_tokens(self.path, {"access_token": "moi", "refresh_token": "rt-moi"})
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        if os.name == "nt":
            self.skipTest("Windows khong ap quyen POSIX")
        self.assertEqual(mode, 0o600, "auth.json bi noi quyen -> lo refresh_token")

    def test_ghi_dung_token_moi_va_khong_de_lai_file_tam(self):
        buzz_quota.write_auth_tokens(self.path, {"access_token": "moi", "refresh_token": "rt-moi"})
        got = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual(got["tokens"]["access_token"], "moi")
        self.assertEqual(got["tokens"]["refresh_token"], "rt-moi")
        self.assertEqual(got["auth_mode"], "chatgpt", "cac truong khac phai giu nguyen")
        rac = [f for f in os.listdir(self.dir) if ".tmp-refresh" in f]
        self.assertEqual(rac, [], "con file tam sau khi ghi")


if __name__ == "__main__":
    unittest.main()
