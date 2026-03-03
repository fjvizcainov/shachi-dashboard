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
from datetime import datetime
from pathlib import Path

# Configuration
LOCAL_API = "http://localhost:5002"
REPO_PATH = Path(__file__).parent
DATA_FILE = REPO_PATH / "data.json"
SYNC_INTERVAL = 60  # seconds


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


def save_and_push(data):
    """Save data to file and push to GitHub."""
    # Save JSON
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    # Git commit and push
    try:
        subprocess.run(
            ["git", "add", "data.json"],
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

        print(f"[{data['timestamp'][:19]}] Synced to GitHub")
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

    if data["status"] == "connected":
        print(f"Account: ${data.get('account', {}).get('equity', 0):,.2f}")
        print(f"Positions: {len(data.get('positions', []))}")
        print(f"Orders: {len(data.get('orders', []))}")
    else:
        print(f"Error: {data.get('error', 'Unknown')}")

    save_and_push(data)


def run_daemon():
    """Run sync continuously."""
    print(f"Starting sync daemon (interval: {SYNC_INTERVAL}s)")
    print("Press Ctrl+C to stop\n")

    while True:
        try:
            data = fetch_data()
            save_and_push(data)
            time.sleep(SYNC_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopping sync daemon")
            break


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        run_once()
