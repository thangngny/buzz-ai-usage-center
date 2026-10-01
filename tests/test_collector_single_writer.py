import importlib.util
import os
import re
import shlex
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import ledger
import paths


def load_collector_module():
    spec = importlib.util.spec_from_file_location(
        "buzz_collector_test", os.path.join(ROOT, "bin", "buzz_collector.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wsl_to_win(path):
    m = re.match(r"^/mnt/([a-z])/(.*)$", path)
    return m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")


def make_live_db(path):
    with mock.patch.object(ledger, "DB_PATH", path):
        ledger.init_db()
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO agents(agent_id, agent_pubkey, display_name, backend_kind) "
        "VALUES ('old-cli', NULL, 'Old', 'claude-cli')")
    conn.execute(
        "INSERT INTO requests(request_id, community_id, channel_id, trigger_event_id,"
        " agent_id, started_at, status) VALUES ('stale', 'c', 'ch', 'ev', 'old-cli', 1, 'completed')")
    conn.commit()
    conn.close()


def scratch_from_script(script):
    env = dict(tok.split("=", 1) for tok in shlex.split(script) if "=" in tok and tok.split("=", 1)[0].isupper())
    return env


class V4SingleWriterTests(unittest.TestCase):
    def setUp(self):
        self.collector = load_collector_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.live = os.path.join(self.tmp.name, "usage.db")
        make_live_db(self.live)

    def tearDown(self):
        self.tmp.cleanup()

    def run_collector(self, fake_wsl, args=("--no-backup",)):
        with mock.patch("paths.wsl_bash", side_effect=fake_wsl):
            return self.collector.run_via_wsl(list(args), db_path=self.live)

    def live_rows(self, sql):
        conn = sqlite3.connect(self.live)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def test_v4_wsl_never_receives_live_db_path(self):
        seen = {}

        def fake_wsl(script, timeout=180):
            seen.update(scratch_from_script(script))
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.assertEqual(self.run_collector(fake_wsl), 0)
        self.assertEqual(seen.get("BUZZ_COLLECT_SCRATCH"), "1")
        self.assertNotEqual(seen["BUZZ_USAGE_DB"], paths.win_to_wsl(self.live))
        self.assertFalse(os.path.exists(wsl_to_win(seen["BUZZ_USAGE_DB"])), "scratch must be removed")

    def test_v4_scratch_uses_rollback_journal_not_wal(self):
        modes = []

        def fake_wsl(script, timeout=180):
            conn = sqlite3.connect(wsl_to_win(scratch_from_script(script)["BUZZ_USAGE_DB"]))
            modes.append(conn.execute("PRAGMA journal_mode").fetchone()[0])
            conn.close()
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.run_collector(fake_wsl)
        self.assertEqual(modes, ["delete"])

    def test_v4_windows_merges_collector_tables_only(self):
        def fake_wsl(script, timeout=180):
            conn = sqlite3.connect(wsl_to_win(scratch_from_script(script)["BUZZ_USAGE_DB"]))
            conn.execute("DELETE FROM requests")
            conn.execute("DELETE FROM agents WHERE backend_kind='claude-cli'")
            conn.execute(
                "INSERT INTO agents(agent_id, agent_pubkey, display_name, backend_kind) "
                "VALUES ('abc', 'abcpk', 'Agent', 'codex-openai')")
            conn.execute(
                "INSERT INTO requests(request_id, community_id, channel_id, trigger_event_id,"
                " principal_pubkey, agent_id, started_at, status) "
                "VALUES ('new', 'c', 'ch', 'ev2', 'userpk', 'abc', 2, 'completed')")
            conn.execute(
                "INSERT INTO principals VALUES ('userpk', 'c', 'User', 2, 2)")
            conn.execute("UPDATE settings SET value='HACKED' WHERE key='mode'")
            conn.commit()
            conn.close()
            return mock.Mock(returncode=0, stdout="requests moi   : 1\n", stderr="")

        self.assertEqual(self.run_collector(fake_wsl), 0)
        self.assertEqual(self.live_rows("SELECT request_id FROM requests"), [("new",)])
        self.assertEqual(self.live_rows("SELECT agent_id FROM agents WHERE backend_kind='claude-cli'"), [])
        self.assertIn(("abc",), self.live_rows("SELECT agent_id FROM agents"))
        self.assertEqual(self.live_rows("SELECT display_name FROM principals"), [("User",)])
        self.assertEqual(self.live_rows("SELECT value FROM settings WHERE key='mode'"), [("METER_ONLY",)])
        self.assertEqual(self.live_rows("PRAGMA quick_check"), [("ok",)])

    def test_v4_failed_wsl_run_keeps_live_db(self):
        def fake_wsl(script, timeout=180):
            conn = sqlite3.connect(wsl_to_win(scratch_from_script(script)["BUZZ_USAGE_DB"]))
            conn.execute("DELETE FROM requests")
            conn.commit()
            conn.close()
            return mock.Mock(returncode=1, stdout="", stderr="boom")

        self.assertEqual(self.run_collector(fake_wsl), 1)
        self.assertEqual(self.live_rows("SELECT request_id FROM requests"), [("stale",)])

    def test_v4_corrupt_scratch_is_not_merged(self):
        def fake_wsl(script, timeout=180):
            with open(wsl_to_win(scratch_from_script(script)["BUZZ_USAGE_DB"]), "r+b") as f:
                f.seek(0)
                f.write(b"\0" * 4096)
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.assertNotEqual(self.run_collector(fake_wsl), 0)
        self.assertEqual(self.live_rows("SELECT request_id FROM requests"), [("stale",)])

    def test_v4_non_cp1252_output_still_merges(self):
        # Watchdog-started dashboards have no PYTHONIOENCODING: the collector's
        # stdout is a strict cp1252 pipe while WSL prints Vietnamese names.
        import io

        def fake_wsl(script, timeout=180):
            conn = sqlite3.connect(wsl_to_win(scratch_from_script(script)["BUZZ_USAGE_DB"]))
            conn.execute("DELETE FROM requests")
            conn.commit()
            conn.close()
            return mock.Mock(returncode=0, stdout="NGUOI DUNG: Đức Hà Giang\n", stderr="cảnh báo\n")

        out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            rc = self.run_collector(fake_wsl)
        self.assertEqual(rc, 0)
        self.assertEqual(self.live_rows("SELECT count(*) FROM requests"), [(0,)])

    def test_v4_live_writes_during_run_survive(self):
        def fake_wsl(script, timeout=180):
            live = sqlite3.connect(self.live)
            live.execute("UPDATE settings SET value='WARN_ONLY' WHERE key='mode'")
            live.execute("INSERT INTO principals VALUES ('late', 'c', 'Late User', 5, 5)")
            live.commit()
            live.close()
            return mock.Mock(returncode=0, stdout="", stderr="")

        self.assertEqual(self.run_collector(fake_wsl), 0)
        self.assertEqual(self.live_rows("SELECT value FROM settings WHERE key='mode'"), [("WARN_ONLY",)])
        self.assertEqual(self.live_rows("SELECT display_name FROM principals WHERE principal_pubkey='late'"),
                         [("Late User",)])

    def test_v4_wsl_timeout_fits_dashboard_budget(self):
        import dashboard

        # snapshot + merge each wait up to 60 s for locks; the dashboard kill must
        # never land before the collector's own timeout (it would skip `finally`).
        self.assertGreater(dashboard.COLLECT_TIMEOUT, self.collector.WSL_TIMEOUT + 2 * 60)

    def test_v4_dashboard_children_use_utf8(self):
        import dashboard

        with mock.patch.object(dashboard.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="requests moi   : 1\n", stderr="")
            dashboard.refresh_collect("test")
            dashboard.refresh_quota("test")
        for call in run.call_args_list:
            self.assertEqual(call.kwargs.get("encoding"), "utf-8")
            self.assertEqual(call.kwargs.get("errors"), "replace")
            self.assertEqual(call.kwargs["env"].get("PYTHONIOENCODING"), "utf-8")

    def test_v4_quota_refuses_windows_drive_from_wsl(self):
        spec = importlib.util.spec_from_file_location(
            "buzz_quota_v4", os.path.join(ROOT, "bin", "buzz_quota.py"))
        quota = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(quota)
        with mock.patch("paths.in_wsl", return_value=True), \
                mock.patch.object(quota, "DB_PATH", "/mnt/d/Manh/buzz-ai-usage-center/usage.db"), \
                mock.patch.object(quota, "DUMP_JSON", False), \
                mock.patch.object(quota, "DRY", False), \
                mock.patch.object(quota, "collect_all") as collect:
            self.assertEqual(quota.main(), 2)
            collect.assert_not_called()

    def test_v4_wsl_side_refuses_to_write_windows_drive_db(self):
        with mock.patch("paths.in_wsl", return_value=True), \
                mock.patch.object(self.collector, "DB_PATH", "/mnt/d/Manh/buzz-ai-usage-center/usage.db"), \
                mock.patch.object(self.collector, "SCRATCH", False), \
                mock.patch.object(self.collector, "DRY", False), \
                mock.patch.object(self.collector, "load_harnesses") as harness:
            self.assertEqual(self.collector.main(), 2)
            harness.assert_not_called()


class V5SingleDashboardTests(unittest.TestCase):
    def test_v5_second_dashboard_cannot_bind_same_port(self):
        import dashboard

        first = dashboard.DashboardServer(("127.0.0.1", 0), dashboard.Handler)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                dashboard.DashboardServer(("127.0.0.1", port), dashboard.Handler)
        finally:
            first.server_close()


if __name__ == "__main__":
    unittest.main()
