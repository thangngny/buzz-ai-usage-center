import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "bin"))


def load_dashboard_module():
    spec = importlib.util.spec_from_file_location(
        "buzz_dashboard_test", os.path.join(ROOT, "bin", "dashboard.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGtmFunnelBehavioral(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set PYTEST_CURRENT_TEST to prevent slow 10GB archive background scans
        os.environ["PYTEST_CURRENT_TEST"] = "1"
        cls.dashboard = load_dashboard_module()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.db_path = self.test_dir / "marketing.db"
        self.artifacts_dir = self.test_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        os.environ["BUZZ_MARKETING_DB"] = str(self.db_path)
        os.environ["BUZZ_ARTIFACTS_DIR"] = str(self.artifacts_dir)
        os.environ["BUZZ_DASHBOARD_MODE"] = "real"

    def tearDown(self):
        self.temp_dir.cleanup()
        for k in ("BUZZ_MARKETING_DB", "BUZZ_ARTIFACTS_DIR", "BUZZ_DASHBOARD_MODE", "BUZZ_VAT_CACHE", "BUZZ_TOKEN_CACHE"):
            os.environ.pop(k, None)

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE business_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                synthetic INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE canonical_records (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                environment TEXT NOT NULL,
                synthetic INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def test_demo_mode_returns_demo_dataset(self):
        res = self.dashboard.get_gtm_funnel_data(mode="demo")
        self.assertTrue(res["is_demo"])
        self.assertEqual(res["mode"], "DEMO")
        self.assertIn("banner_warning", res)
        self.assertIn("MÔ PHỎNG", res["banner_warning"])
        self.assertEqual(res["funnel"]["raw_discovered"], 524)
        self.assertEqual(res["funnel"]["verified_facts"], 412)

    def test_no_data_mode_when_db_missing(self):
        if self.db_path.exists():
            self.db_path.unlink()
        res = self.dashboard.get_gtm_funnel_data(mode="auto")
        self.assertFalse(res["is_demo"])
        self.assertEqual(res["status"], "NO_DATA")
        self.assertEqual(res["funnel"]["raw_discovered"], 0)
        self.assertEqual(res["funnel"]["verified_facts"], 0)
        self.assertEqual(res["funnel"]["deduped"], 0)
        self.assertEqual(res["funnel"]["duplicate_confirmed"], 0)

    def test_event_filtering_outcome_dedupe_and_deal_distinction(self):
        self._init_db()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 1. Real discovered: 2 real, 1 mock (ignored), 1 synthetic (ignored)
        cur.execute("INSERT INTO business_events VALUES ('ev1', 'lead.discovered', 'Lead', 'ent1', 'sandbox', 0, '{}', '2026-11-13T10:00:00Z')")
        cur.execute("INSERT INTO business_events VALUES ('ev2', 'lead.discovered', 'Lead', 'ent2', 'production', 0, '{}', '2026-11-13T10:01:00Z')")
        cur.execute("INSERT INTO business_events VALUES ('ev3', 'lead.discovered', 'Lead', 'ent_mock', 'mock', 0, '{}', '2026-11-13T10:02:00Z')")
        cur.execute("INSERT INTO business_events VALUES ('ev4', 'lead.discovered', 'Lead', 'ent_synth', 'sandbox', 1, '{}', '2026-11-13T10:03:00Z')")

        # 2. Verified: 1 real legal_verified
        cur.execute("INSERT INTO business_events VALUES ('ev5', 'lead.legal_verified', 'Lead', 'ent1', 'sandbox', 0, '{}', '2026-11-13T10:05:00Z')")

        # 3. Dedupe: ent1 cleared (outcome='SUCCESS'), ent2 duplicate confirmed (outcome='DUPLICATE_CONFIRMED')
        cur.execute("INSERT INTO business_events VALUES ('ev6', 'lead.crm_dedupe_completed', 'Lead', 'ent1', 'sandbox', 0, '{\"outcome\": \"SUCCESS\"}', '2026-11-13T10:10:00Z')")
        cur.execute("INSERT INTO business_events VALUES ('ev7', 'lead.crm_dedupe_completed', 'Lead', 'ent2', 'sandbox', 0, '{\"outcome\": \"DUPLICATE_CONFIRMED\", \"dedupe_status\": \"DUPLICATE_CONFIRMED\"}', '2026-11-13T10:11:00Z')")

        # 4. Scored: ent1 scored
        cur.execute("INSERT INTO business_events VALUES ('ev8', 'lead.icp_scored', 'Lead', 'ent1', 'sandbox', 0, '{\"score\": 85}', '2026-11-13T10:15:00Z')")

        # 5. Deals: 1 real deal.created, 1 opportunity.created (which must be EXCLUDED)
        cur.execute("INSERT INTO business_events VALUES ('ev9', 'deal.created', 'Deal', 'deal1', 'sandbox', 0, '{}', '2026-11-13T10:20:00Z')")
        cur.execute("INSERT INTO business_events VALUES ('ev10', 'opportunity.created', 'Deal', 'opp1', 'sandbox', 0, '{}', '2026-11-13T10:21:00Z')")

        conn.commit()
        conn.close()

        res = self.dashboard.get_gtm_funnel_data(mode="auto")
        self.assertFalse(res["is_demo"])
        self.assertEqual(res["status"], "ACTIVE_LEDGER")

        funnel = res["funnel"]
        kpis = res["kpis"]

        # Discovered: only 2 real distinct entities
        self.assertEqual(funnel["raw_discovered"], 2)
        # Verified: 1
        self.assertEqual(funnel["verified_facts"], 1)
        # Deduped (V10-007): only ent1 cleared
        self.assertEqual(funnel["deduped"], 1)
        # Duplicates prevented (V10-007): ent2 duplicate confirmed
        self.assertEqual(funnel["duplicate_confirmed"], 1)
        self.assertEqual(kpis["duplicates_prevented"], 1)
        # Scored: 1
        self.assertEqual(funnel["icp_scored"], 1)
        # Replied deals: strictly 1 (deal.created), opportunity.created is excluded
        self.assertEqual(funnel["replied_deals"], 1)

    def test_database_locked_error_handling(self):
        self._init_db()
        with mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")):
            res = self.dashboard.get_gtm_funnel_data(mode="auto")
            self.assertEqual(res["status"], "DATABASE_LOCKED")
            self.assertIn("locked", res["error_detail"].lower())

    def test_schema_mismatch_error_handling(self):
        self._init_db()
        with mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("no such table: corrupted")):
            res = self.dashboard.get_gtm_funnel_data(mode="auto")
            self.assertEqual(res["status"], "SCHEMA_MISMATCH")
            self.assertIn("no such table", res["error_detail"].lower())

    def test_vat_and_dpapi_cache_reporting(self):
        vat_file = self.test_dir / "zoho_live_vat_cache.json"
        vat_file.write_text(json.dumps({"vats": ["0101234567", "0309876543"], "names": ["A", "B"]}), encoding="utf-8")
        os.environ["BUZZ_VAT_CACHE"] = str(vat_file)

        token_file = self.test_dir / "zoho_token_cache.json"
        token_file.write_bytes(b"BUZZ_DPAPI_V1_ENCRYPTED_DATA_BYTES")
        os.environ["BUZZ_TOKEN_CACHE"] = str(token_file)

        res = self.dashboard.get_gtm_funnel_data(mode="demo")
        self.assertEqual(res["kpis"]["crm_protected_vats"], 2)
        self.assertTrue(res["crm_security"]["token_encrypted_dpapi"])


if __name__ == "__main__":
    unittest.main()
