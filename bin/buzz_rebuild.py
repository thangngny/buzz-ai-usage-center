#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dung lai usage.db TU SO 0, chi bang du lieu that cua he nay.

Vi sao can: usage.db di kem repo la CSDL cua tac gia. Xoa dan tung phan van con
sot lai nhung thu kho thay:
    settings.owner_pubkeys  = pubkey cua NcThang  -> dashboard coi anh ay la chu
    settings.base_units_daily = 3.000.000         -> con so tuy chon, khong lien
                                                     quan han muc that cua ban
    owner_alerts, audit_events, request_idempotency ... con ban ghi cu
    agents: claude-cli + agy-1..4 tu moc lai moi lan dashboard khoi dong

Nen dung lai tu dau la cach duy nhat chac chan sach.

base_units_daily KHONG con la con so bia. No duoc SUY RA tu han muc that:
    tong token da dung trong cua so / (used_percent/100) = ngan sach ca cua so
    chia cho so ngay cua cua so                          = ngan sach moi ngay

Chay:  python3 bin/buzz_rebuild.py
"""
import datetime, glob, json, os, shutil, sqlite3, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
DB_PATH = os.environ.get("BUZZ_USAGE_DB", os.path.join(ROOT, "usage.db"))
HOME = os.path.expanduser("~")

# Chu so huu that cua he nay = identity cua buzz-desktop
# (log buzz-desktop: "persisted identity pubkey 4af51eb8...")
OWNER_PUBKEY = "4af51eb83e2b29b149154e94280b0585cad2e3d32ef4c2a3572663ab359a81f6"


def log(m):
    print(m, flush=True)


def run(script, *args):
    env = dict(os.environ)
    env["BUZZ_USAGE_DB"] = DB_PATH
    env["BUZZ_OWNER_PUBKEY"] = OWNER_PUBKEY
    r = subprocess.run([sys.executable, os.path.join(BIN, script)] + list(args),
                       capture_output=True, text=True, env=env)
    return r


def derive_base_units(conn):
    """Suy ra ngan sach ngay tu han muc THAT, thay vi dung con so 3.000.000.

    Cach tinh: doc used_percent moi nhat cua nha cung cap, doi chieu voi so token
    da tieu trong dung cua so do. Neu 89% cua so 7 ngay ung voi N token thi ca
    cua so la N/0.89, chia 7 ra ngan sach mot ngay.

    Tra ve (base_units_daily, giai_thich) hoac (None, ly_do) neu chua du du lieu.
    """
    row = conn.execute(
        "SELECT agent_id, remaining_percent, reset_at FROM account_capacity_snapshots"
        " WHERE remaining_percent IS NOT NULL ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None, "chua co snapshot han muc"
    agent_id, remaining, _ = row
    used_pct = 100.0 - float(remaining)
    if used_pct <= 0:
        return None, "used_percent = 0, khong suy ra duoc"

    # Cua so 7 ngay: cong token cua chinh harness do trong 7 ngay qua.
    since = int(datetime.datetime.now().timestamp()) - 7 * 86400
    tok = conn.execute(
        "SELECT COALESCE(SUM(r.normalized_units),0) FROM requests r"
        " JOIN agents a ON a.agent_id = r.agent_id"
        " WHERE a.backend_kind = ? AND r.started_at >= ?",
        (agent_id, since)).fetchone()[0]
    if not tok:
        return None, "khong co token nao cua %s trong 7 ngay" % agent_id

    window_total = tok / (used_pct / 100.0)
    daily = int(window_total / 7.0)
    return daily, ("%s: %s token = %.1f%% cua so 7 ngay -> ca cua so ~%s -> ngay ~%s"
                   % (agent_id, "{:,.0f}".format(tok), used_pct,
                      "{:,.0f}".format(window_total), "{:,}".format(daily)))


def main():
    if os.name != "nt" and os.path.realpath(DB_PATH).startswith("/mnt/"):
        # SPEC V4: chi tien trinh Windows ghi usage.db (WAL khong dong bo khoa qua /mnt).
        log("TU CHOI dung lai %s tu WSL. Chay tu Windows: python bin\\buzz_rebuild.py" % DB_PATH)
        return 2
    log("=== DUNG LAI usage.db TU SO 0 ===\n")

    if os.path.exists(DB_PATH):
        bak = DB_PATH + ".truoc-khi-dung-lai-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.move(DB_PATH, bak)
        log("CSDL cu doi ten thanh: %s" % os.path.basename(bak))
    for junk in glob.glob(DB_PATH + "-wal") + glob.glob(DB_PATH + "-shm"):
        os.remove(junk)

    # Tao luoc do trong, khong gieo agent nao
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    os.environ["BUZZ_USAGE_DB"] = DB_PATH
    os.environ["BUZZ_OWNER_PUBKEY"] = OWNER_PUBKEY
    import importlib
    import ledger
    importlib.reload(ledger)
    ledger.DB_PATH = DB_PATH
    ledger.init_db()
    log("Da tao luoc do trong (0 agent, 0 request)\n")

    log("--- Thu thap usage that ---")
    r = run("buzz_collector.py")
    for line in (r.stdout or "").splitlines():
        if line.strip():
            log("  " + line)
    if r.returncode != 0:
        log("  LOI: " + (r.stderr or "")[-400:])
        return 1

    log("\n--- Doc han muc that ---")
    r = run("buzz_quota.py")
    for line in (r.stdout or "").splitlines():
        if line.strip():
            log("  " + line)

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    try:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('owner_pubkeys',?)",
                     (OWNER_PUBKEY,))
        base, why = derive_base_units(conn)
        if base:
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('base_units_daily',?)",
                         (str(base),))
            log("\nbase_units_daily suy ra tu han muc that: %s" % "{:,}".format(base))
            log("   %s" % why)
        else:
            log("\nGiu base_units_daily mac dinh — %s" % why)
        conn.commit()

        log("\n=== KIEM CHUNG ===")
        for t in ("agents", "principals", "requests", "usage_events",
                  "account_capacity_snapshots", "owner_alerts", "audit_events"):
            n = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            log("  %-28s %s dong" % (t, n))
        la = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE backend_kind IN ('claude-cli','agy')").fetchone()[0]
        log("  %-28s %s  <- phai la 0" % ("agent cua he khac", la))
        own = conn.execute("SELECT value FROM settings WHERE key='owner_pubkeys'").fetchone()[0]
        log("  %-28s %s..." % ("chu so huu", own[:16]))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
