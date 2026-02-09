#!/bin/bash

# ✅ POLYMARKET AUTO-DISCOVERY FALLBACK
# If normal API calls fail, fetch docs and auto-detect correct endpoints
# Source: https://docs.polymarket.com/quickstart/overview

set -e

LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/autodiscovery.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Try normal flow first
try_normal_flow() {
  log "→ Trying standard API endpoints..."
  
  # Standard endpoints from docs
  ENDPOINTS=(
    "https://gamma-api.polymarket.com/events?active=true&closed=false"
    "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m"
  )
  
  for endpoint in "${ENDPOINTS[@]}"; do
    log "  Testing: $endpoint"
    if curl -s --max-time 2 "$endpoint" 2>/dev/null | grep -q "id\|title"; then
      log "  ✅ Success"
      return 0
    fi
  done
  
  log "  ❌ Standard endpoints failed"
  return 1
}

# Fallback: Fetch docs and extract endpoints
fetch_docs_and_discover() {
  log "→ Falling back to documentation discovery..."
  
  # Fetch official docs
  DOCS=$(curl -s --max-time 5 "https://docs.polymarket.com/quickstart/fetching-data" 2>/dev/null || echo "")
  
  if [ -z "$DOCS" ]; then
    log "  ❌ Could not fetch documentation"
    return 1
  fi
  
  log "  ✅ Documentation fetched"
  
  # Extract API endpoints from docs
  # Look for patterns like: https://gamma-api.polymarket.com/...
  
  GAMMA_BASE="https://gamma-api.polymarket.com"
  CLOB_BASE="https://clob.polymarket.com"
  
  # Recommended endpoints per docs
  RECOMMENDED_ENDPOINTS=(
    "$GAMMA_BASE/events?active=true&closed=false&limit=100"
    "$GAMMA_BASE/series?slug=btc-up-or-down-15m"
    "$CLOB_BASE/price?token_id=TOKEN_ID"
    "$CLOB_BASE/book?token_id=TOKEN_ID"
  )
  
  log "  → Trying documented endpoints..."
  for ep in "${RECOMMENDED_ENDPOINTS[@]}"; do
    if [[ "$ep" == *"?"* ]]; then
      TEST_EP="${ep%\?*}?active=true&limit=1"
    else
      TEST_EP="$ep"
    fi
    
    log "    Testing: $TEST_EP"
    if curl -s --max-time 2 "$TEST_EP" 2>/dev/null | grep -q "{"; then
      log "    ✅ Endpoint working: $TEST_EP"
      echo "$TEST_EP"
      return 0
    fi
  done
  
  log "  ❌ No documented endpoints working"
  return 1
}

# Ultimate fallback: Use cache
use_cache() {
  log "→ Using cached market data..."
  
  STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
  CACHE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-cache.json"
  
  if [ -f "$CACHE_FILE" ]; then
    log "  ✅ Cache available"
    cat "$CACHE_FILE"
    return 0
  elif [ -f "$STATE_FILE" ]; then
    log "  ✅ State file available"
    cat "$STATE_FILE"
    return 0
  fi
  
  log "  ❌ No cache available"
  return 1
}

# Main execution
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "🔍 Polymarket Auto-Discovery"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if try_normal_flow; then
  log "✅ Using standard endpoints"
  exit 0
fi

if fetch_docs_and_discover; then
  log "✅ Using documented endpoints"
  exit 0
fi

if use_cache; then
  log "⚠️  Using cached data"
  exit 0
fi

log "❌ AUTO-DISCOVERY FAILED"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 1
