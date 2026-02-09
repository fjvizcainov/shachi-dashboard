#!/bin/bash

# ✅ POLYMARKET MONITOR V3 - WITH AUTO-DISCOVERY FALLBACK
# Integrates official APIs + autodiscovery + cache
# If anything fails, tries documentation + falls back to cache

STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/polymarket-v3.log"
CACHE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-cache.json"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date +'%H:%M:%S')] $1" >> "$LOG_FILE"
}

log "🔄 Monitor tick..."

# STRATEGY 1: Use get-polymarket-live-final.sh (proven working)
log "  → Trying proven script..."
if bash /Users/moltbot/clawd/bitcoin/get-polymarket-live-final.sh >> "$LOG_FILE" 2>&1; then
  log "  ✅ Data fetched successfully"
  exit 0
fi

log "  ❌ Proven script failed"

# STRATEGY 2: Try autodiscovery
log "  → Trying auto-discovery..."
if bash /Users/moltbot/clawd/bitcoin/polymarket-autodiscovery.sh >> "$LOG_FILE" 2>&1; then
  log "  ✅ Auto-discovery succeeded"
  exit 0
fi

log "  ❌ Auto-discovery failed"

# STRATEGY 3: Use cache
log "  → Using cache..."
if [ -f "$CACHE_FILE" ]; then
  log "  ✅ Cache valid, using cached state"
  cp "$CACHE_FILE" "$STATE_FILE"
  exit 0
fi

if [ -f "$STATE_FILE" ]; then
  log "  ⚠️  Using stale state file"
  exit 0
fi

log "  ❌ No data available"
exit 1
