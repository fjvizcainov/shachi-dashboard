#!/usr/bin/env python3
"""
Shachi Dashboard Sync Script

Fetches data from local trading server and pushes to GitHub.
Run this locally to keep the public dashboard updated.

Usage:
    python3 sync.py           # Run once
    python3 sync.py --daemon  # Run every 60 seconds
"""

import json
import subprocess
import requests
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
LOCAL_API = "http://localhost:5002"
REPO_PATH = Path(__file__).parent
DATA_FILE = REPO_PATH / "data.json"
HISTORY_FILE = REPO_PATH / "pnl_history.json"
SYNC_INTERVAL = 60  # seconds
STARTING_EQUITY = 100000  # Initial paper trading balance
MAX_HISTORY_POINTS = 500  # Keep last 500 data points (~8 hours at 1/min)


def load_history():
    """Load existing PnL history."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def update_history(history, data):
    """Update PnL history with current data point."""
    if data.get("status") != "connected":
        return history

    account = data.get("account", {})
    equity = float(account.get("equity", 0) or account.get("portfolio_value", 0))

    if equity <= 0:
        return history

    # Calculate PnL percentage from starting equity
    pnl_pct = ((equity - STARTING_EQUITY) / STARTING_EQUITY) * 100

    # Create new data point
    point = {
        "timestamp": data["timestamp"],
        "equity": equity,
        "pnl_pct": round(pnl_pct, 4),
        "positions": len(data.get("positions", [])),
    }

    # Avoid duplicate timestamps (within same minute)
    if history:
        last_time = history[-1].get("timestamp", "")[:16]
        new_time = point["timestamp"][:16]
        if last_time == new_time:
            # Update existing point
            history[-1] = point
            return history

    # Add new point
    history.append(point)

    # Trim to max points
    if len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]

    return history


def fetch_data():
    """Fetch all data from local trading server."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "status": "connected",
    }

    try:
        # Account
        r = requests.get(f"{LOCAL_API}/api/account", timeout=5)
        if r.ok:
            data["account"] = r.json()

        # Positions
        r = requests.get(f"{LOCAL_API}/api/positions", timeout=5)
        if r.ok:
            data["positions"] = r.json()

        # Orders
        r = requests.get(f"{LOCAL_API}/api/orders", timeout=5)
        if r.ok:
            data["orders"] = r.json()

        # Signals
        r = requests.get(f"{LOCAL_API}/api/signals", timeout=5)
        if r.ok:
            data["signals"] = r.json()

        # Status
        r = requests.get(f"{LOCAL_API}/api/status", timeout=5)
        if r.ok:
            data["system_status"] = r.json()

    except requests.exceptions.RequestException as e:
        data["status"] = "error"
        data["error"] = str(e)

    return data


def save_and_push(data, history):
    """Save data to files and push to GitHub."""
    # Save JSON files
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

    # Git commit and push
    try:
        subprocess.run(
            ["git", "add", "data.json", "pnl_history.json"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True
        )

        subprocess.run(
            ["git", "commit", "-m", f"Update data {data['timestamp'][:19]}"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True
        )

        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True
        )

        equity = data.get('account', {}).get('equity', 0)
        pnl = ((float(equity) - STARTING_EQUITY) / STARTING_EQUITY) * 100 if equity else 0
        print(f"[{data['timestamp'][:19]}] Synced | Equity: ${float(equity):,.2f} | PnL: {pnl:+.2f}%")
        return True

    except subprocess.CalledProcessError as e:
        # No changes to commit is OK
        if b"nothing to commit" in (e.stdout or b"") + (e.stderr or b""):
            print(f"[{data['timestamp'][:19]}] No changes")
            return True
        print(f"[{data['timestamp'][:19]}] Git error: {(e.stderr or b'').decode()}")
        return False


def run_once():
    """Run sync once."""
    print("Fetching data from local server...")
    data = fetch_data()
    history = load_history()

    if data["status"] == "connected":
        equity = data.get('account', {}).get('equity', 0)
        pnl = ((float(equity) - STARTING_EQUITY) / STARTING_EQUITY) * 100 if equity else 0
        print(f"Account: ${float(equity):,.2f} (PnL: {pnl:+.2f}%)")
        print(f"Positions: {len(data.get('positions', []))}")
        print(f"Orders: {len(data.get('orders', []))}")
        print(f"History points: {len(history)}")

        history = update_history(history, data)
    else:
        print(f"Error: {data.get('error', 'Unknown')}")

    save_and_push(data, history)


def run_daemon():
    """Run sync continuously."""
    print(f"Starting sync daemon (interval: {SYNC_INTERVAL}s)")
    print(f"Tracking PnL from starting equity: ${STARTING_EQUITY:,}")
    print("Press Ctrl+C to stop\n")

    history = load_history()
    print(f"Loaded {len(history)} history points")

    while True:
        try:
            data = fetch_data()
            history = update_history(history, data)
            save_and_push(data, history)
            time.sleep(SYNC_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopping sync daemon")
            break


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        run_once()
