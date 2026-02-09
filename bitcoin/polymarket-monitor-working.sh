#!/bin/bash

# ✅ POLYMARKET MONITOR - WORKING VERSION
# Runs every 30 seconds via cron to get live market data

bash /Users/moltbot/clawd/bitcoin/get-polymarket-live-final.sh >> /Users/moltbot/clawd/bitcoin/logs/polymarket-monitor.log 2>&1

# Optional: Compare to previous state and detect spikes
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"

if [ -f "$STATE_FILE" ]; then
  UP=$(jq -r '.up_percent' "$STATE_FILE")
  DOWN=$(jq -r '.down_percent' "$STATE_FILE")
  echo "[$(date)] ✅ Data: UP $UP% / DOWN $DOWN%" >> /Users/moltbot/clawd/bitcoin/logs/polymarket-monitor.log
fi
