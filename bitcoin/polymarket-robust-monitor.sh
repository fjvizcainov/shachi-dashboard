#!/bin/bash

# ✅ POLYMARKET ROBUST MONITOR v2
# Integrates official Polymarket APIs with retries + fallbacks
# Based on: https://docs.polymarket.com/quickstart/fetching-data

set -e

STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/polymarket-robust.log"
CACHE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-cache.json"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "🔄 Polymarket monitor tick..."

# STRATEGY 1: Get active BTC 15m market via OFFICIAL API
# Doc: /events?active=true&closed=false&limit=5

fetch_active_market() {
  log "  → Trying: Query active events for BTC..."
  
  # Try different queries
  EVENTS=$(curl -s --max-time 3 "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100" 2>/dev/null | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
# Find BTC market
for e in data:
    if 'btc' in e.get('slug', '').lower() or 'bitcoin' in e.get('title', '').lower():
        if e.get('active') and not e.get('closed'):
            print(e['id'])
            break
" 2>/dev/null) || echo ""
  
  if [ ! -z "$EVENTS" ]; then
    log "  ✅ Found active BTC market: $EVENTS"
    echo "$EVENTS"
    return 0
  fi
  
  # Fallback: Use series slug (works reliably)
  log "  → Fallback: Using series slug..."
  MARKET=$(curl -s --max-time 3 "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m" 2>/dev/null | \
    python3 -c "
import json, sys
d = json.load(sys.stdin)
events = d[0]['events']
for e in events:
    if not e.get('closed'):
        print(e['id'])
        break
else:
    print(events[0]['id'])
" 2>/dev/null) || echo ""
  
  if [ ! -z "$MARKET" ]; then
    log "  ✅ Found via series: $MARKET"
    echo "$MARKET"
    return 0
  fi
  
  # Final fallback: Use cached market ID
  if [ -f "$CACHE_FILE" ]; then
    CACHED=$(jq -r '.last_market_id // empty' "$CACHE_FILE" 2>/dev/null)
    if [ ! -z "$CACHED" ]; then
      log "  ⚠️  Using cached market: $CACHED"
      echo "$CACHED"
      return 0
    fi
  fi
  
  log "  ❌ Failed to get market"
  return 1
}

# STRATEGY 2: Get market details + outcome prices
# Doc: /events/{id}

fetch_market_prices() {
  local market_id=$1
  
  log "  → Fetching market details for $market_id..."
  
  MARKET=$(curl -s --max-time 3 "https://gamma-api.polymarket.com/events/$market_id" 2>/dev/null) || return 1
  
  # Extract prices
  UP=$(echo "$MARKET" | python3 -c "
import json, sys
d = json.load(sys.stdin)
prices = json.loads(d['markets'][0]['outcomePrices'])
print(round(float(prices[0]) * 100, 1))
" 2>/dev/null) || return 1
  
  DOWN=$(echo "100 - $UP" | bc 2>/dev/null) || DOWN=$((100 - UP))
  
  log "  ✅ Got prices: UP $UP% / DOWN $DOWN%"
  echo "$UP|$DOWN"
  return 0
}

# STRATEGY 3: Get BTC price
# Source: CoinGecko (official)

fetch_btc_price() {
  log "  → Fetching BTC price..."
  
  BTC=$(curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" 2>/dev/null | \
    python3 -c "import json, sys; print(int(json.load(sys.stdin)['bitcoin']['usd']))" 2>/dev/null) || BTC=0
  
  if [ $BTC -gt 0 ]; then
    log "  ✅ BTC: \$$BTC"
    echo "$BTC"
  else
    log "  ⚠️  BTC price unavailable"
    # Use cached
    BTC_CACHED=$(jq -r '.btc_price // 0' "$STATE_FILE" 2>/dev/null)
    echo "$BTC_CACHED"
  fi
}

# MAIN EXECUTION
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Step 1: Get market
MARKET_ID=$(fetch_active_market) || {
  log "❌ Could not fetch market. Exiting."
  exit 1
}

# Step 2: Get prices
PRICES=$(fetch_market_prices "$MARKET_ID") || {
  log "❌ Could not fetch prices. Exiting."
  exit 1
}

UP=$(echo "$PRICES" | cut -d'|' -f1)
DOWN=$(echo "$PRICES" | cut -d'|' -f2)

# Step 3: Get BTC
BTC=$(fetch_btc_price)

# Step 4: Save state
cat > "$STATE_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "up_percent": $UP,
  "down_percent": $DOWN,
  "btc_price": $BTC,
  "source": "Gamma API + CoinGecko",
  "status": "✅ LIVE"
}
EOF

# Save cache for fallback
cat > "$CACHE_FILE" << EOF
{
  "last_market_id": "$MARKET_ID",
  "last_up": $UP,
  "last_down": $DOWN,
  "last_btc": $BTC,
  "cached_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

log "✅ State updated: UP $UP% / DOWN $DOWN% / BTC \$$BTC"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
