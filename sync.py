#!/usr/bin/env python3
"""
Shachi Dashboard Sync Script

Fetches all dashboard data from the local trading server (localhost:5002)
and pushes individual JSON snapshots to GitHub so GitHub Pages always shows
the same data as the live localhost dashboard.

Each endpoint is saved as a separate file under data/ so the static HTML
can load them independently (same structure as the live Flask API).

Usage:
    python3 sync.py           # Export once and push
    python3 sync.py --daemon  # Export every 60 s (run after market open)
"""

import json
import subprocess
import requests
import time
import sys
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
LOCAL_API      = "http://localhost:5002"
REPO_PATH      = Path(__file__).parent
DATA_DIR       = REPO_PATH / "data"
SYNC_INTERVAL  = 60   # seconds between syncs in daemon mode
MAX_RETRIES    = 3    # retries per endpoint on failure

DATA_DIR.mkdir(exist_ok=True)

# Endpoint → filename mapping (must match paths used in index.html)
ENDPOINTS = [
    ("/api/status",              "status.json"),
    ("/api/account",             "account.json"),
    ("/api/portfolio",           "portfolio.json"),
    ("/api/positions",           "positions.json"),
    ("/api/orders",              "orders.json"),
    ("/api/trade_history",       "trade_history.json"),
    ("/api/equity",              "equity.json"),
    ("/api/signals",             "signals.json"),
    ("/api/metrics",             "metrics.json"),
    ("/api/live",                "live.json"),
    # legacy / supplemental
    ("/api/daily_metrics",       "daily_metrics.json"),
    ("/api/market/SPY",          "market.json"),
    ("/api/chart/SPY",           "chart.json"),
    ("/api/daily_pnl_reconcile", "reconcile.json"),
]


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_endpoint(path, retries=MAX_RETRIES):
    """Fetch one API endpoint with retries. Returns parsed JSON or None."""
    for attempt in range(retries):
        try:
            r = requests.get(LOCAL_API + path, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  WARN  {path}: {e}")
            else:
                time.sleep(1)
    return None


def export_all():
    """
    Fetch all endpoints and write to data/*.json.
    Returns (ok_count, error_count, equity).
    """
    ok, errors = 0, 0
    equity = None

    for path, filename in ENDPOINTS:
        data = fetch_endpoint(path)
        if data is None:
            errors += 1
            continue
        try:
            with open(DATA_DIR / filename, "w") as f:
                json.dump(data, f, separators=(",", ":"), default=str)
            ok += 1
            if filename == "account.json":
                equity = float(data.get("equity") or data.get("portfolio_value") or 0)
        except Exception as e:
            print(f"  ERR  write {filename}: {e}")
            errors += 1

    # Write metadata (last_updated for the snapshot banner in index.html)
    meta = {
        "last_updated": datetime.now().isoformat(),
        "date":         datetime.now().strftime("%Y-%m-%d"),
        "ok":           ok,
        "errors":       errors,
    }
    with open(DATA_DIR / "meta.json", "w") as f:
        json.dump(meta, f, separators=(",", ":"))

    return ok, errors, equity


# ── Git push ──────────────────────────────────────────────────────────────────

def git_push(timestamp_str):
    """Stage data/ changes, commit if any, and push. Returns True on success."""
    try:
        subprocess.run(
            ["git", "add", "data/", "index.html", "login.html",
             "_headers", "_redirects", "404.html"],
            cwd=REPO_PATH, check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "commit", "-m", f"Snapshot {timestamp_str}"],
            cwd=REPO_PATH, capture_output=True,
        )
        if result.returncode not in (0, 1):  # 1 = nothing to commit
            stderr = (result.stderr or b"").decode()
            if "nothing to commit" not in stderr:
                print(f"  WARN  git commit: {stderr.strip()}")

        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_PATH, check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode()
        if "nothing to commit" in stderr or "Everything up-to-date" in stderr:
            return True
        print(f"  ERR  git push: {stderr.strip()}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

STARTING_EQUITY = 100_000.0  # Initial paper trading balance


def run_once():
    now = datetime.now()
    ts  = now.isoformat()[:19]

    ok, errors, equity = export_all()

    pnl_str = ""
    if equity:
        pnl = (equity - STARTING_EQUITY) / STARTING_EQUITY * 100
        pnl_str = f" | equity=${equity:,.0f} ({pnl:+.2f}%)"

    pushed = git_push(ts)
    status = "OK" if pushed else "PUSH_ERR"
    print(f"[{ts}] {status} | {ok}/{len(ENDPOINTS)} endpoints{pnl_str}")
    sys.stdout.flush()


def run_daemon():
    print(f"Shachi sync daemon — interval: {SYNC_INTERVAL}s")
    print(f"Writing to: {DATA_DIR}")
    print("Press Ctrl+C to stop\n")
    sys.stdout.flush()

    while True:
        try:
            run_once()
            time.sleep(SYNC_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        run_once()
