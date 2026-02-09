#!/bin/bash

# ✅ POLYMARKET LIVE DATA - Final working version
# Gets CURRENT/ACTIVE BTC 15m market + real-time prices
# Uses Gamma API + CLOB API correctly

set -e

echo "📊 Fetching LIVE Polymarket BTC data..."

STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state-live.json"
SERIES_ID="10192"  # BTC Up or Down 15m series

# STEP 1: Get ALL events from series (10 most recent)
echo "[1] Querying Gamma API for BTC 15m events..."

EVENTS=$(curl -s "https://gamma-api.polymarket.com/series?id=$SERIES_ID&limit=100" | jq '.[0].events // []')

# Filter for ACTIVE markets (ones that haven't expired yet)
CURRENT_MARKET=$(echo "$EVENTS" | jq -r 'map(select(.active == true and .closed == false)) | .[0]')

MARKET_ID=$(echo "$CURRENT_MARKET" | jq -r '.id // empty')

if [ -z "$MARKET_ID" ]; then
  echo "⚠️  No active market found. Using most recent..."
  # Fall back to most recent market (even if closed, if just resolved)
  CURRENT_MARKET=$(echo "$EVENTS" | jq -r '.[0]')
  MARKET_ID=$(echo "$CURRENT_MARKET" | jq -r '.id')
fi

MARKET_TITLE=$(echo "$CURRENT_MARKET" | jq -r '.title')
MARKET_STATUS=$(echo "$CURRENT_MARKET" | jq -r 'if .closed then "CLOSED" elif .active then "ACTIVE" else "INACTIVE" end')

echo "✅ Market: $MARKET_TITLE"
echo "✅ Status: $MARKET_STATUS"

# STEP 2: Get detailed market info (with tokenIds)
echo "[2] Fetching market details from Gamma..."

MARKET=$(curl -s "https://gamma-api.polymarket.com/events/$MARKET_ID")

OUTCOMES=$(echo "$MARKET" | jq -r '.markets[0].outcomes' 2>/dev/null)
OUTCOME_PRICES=$(echo "$MARKET" | jq -r '.markets[0].outcomePrices' 2>/dev/null)
TOKEN_IDS=$(echo "$MARKET" | jq -r '.markets[0].clobTokenIds' 2>/dev/null)

if [ -z "$TOKEN_IDS" ] || [ "$TOKEN_IDS" == "null" ]; then
  echo "❌ No token IDs. Cannot proceed."
  exit 1
fi

UP_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[0]')
DOWN_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[1]')

echo "✅ TokenIds extracted"

# STEP 3: Get LIVE prices from Gamma market data (since CLOB may timeout)
echo "[3] Extracting live prices from Gamma..."

UP_PRICE=$(echo "$OUTCOME_PRICES" | jq -r '.[0]' 2>/dev/null)
DOWN_PRICE=$(echo "$OUTCOME_PRICES" | jq -r '.[1]' 2>/dev/null)

# Convert to percentages
UP_PERCENT=$(echo "scale=1; $UP_PRICE * 100" | bc 2>/dev/null || echo "50")
DOWN_PERCENT=$(echo "scale=1; $DOWN_PRICE * 100" | bc 2>/dev/null || echo "50")

# Try CLOB for more recent prices (timeout is OK, we have fallback)
echo "[4] Attempting CLOB API for real-time orderbook..."

CLOB_UP=$(curl -s --max-time 2 "https://clob.polymarket.com/orderbook/$UP_TOKEN" 2>/dev/null || echo "{}")

if [ ! -z "$CLOB_UP" ] && [ "$CLOB_UP" != "{}" ]; then
  # Got CLOB data
  UP_BID=$(echo "$CLOB_UP" | jq -r '.bids[0].price // empty' 2>/dev/null)
  UP_ASK=$(echo "$CLOB_UP" | jq -r '.asks[0].price // empty' 2>/dev/null)
  
  if [ ! -z "$UP_BID" ] && [ ! -z "$UP_ASK" ]; then
    UP_MID=$(echo "scale=4; ($UP_BID + $UP_ASK) / 2" | bc 2>/dev/null)
    UP_PERCENT=$(echo "scale=1; $UP_MID * 100" | bc 2>/dev/null)
    echo "✅ CLOB data available - UP bid: $UP_BID, ask: $UP_ASK"
  else
    echo "⚠️  CLOB data malformed, using Gamma prices"
  fi
else
  echo "⚠️  CLOB timeout, using Gamma prices"
fi

# Calculate DOWN as 100 - UP (binary market)
DOWN_PERCENT=$(echo "scale=1; 100 - $UP_PERCENT" | bc 2>/dev/null || echo "50")

# STEP 4: Get volume and meta
VOLUME=$(echo "$MARKET" | jq -r '.markets[0].volume' 2>/dev/null || echo "0")
BTC_PRICE=$(curl -s "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" | jq -r '.bitcoin.usd' 2>/dev/null || echo "0")

# STEP 5: Save
cat > "$STATE_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$MARKET_TITLE",
  "market_status": "$MARKET_STATUS",
  "up_percent": $UP_PERCENT,
  "down_percent": $DOWN_PERCENT,
  "volume": "$VOLUME",
  "btc_price": $BTC_PRICE,
  "source": "Gamma API (CLOB timeout fallback)",
  "ready_for_prediction": true
}
EOF

echo ""
echo "════════════════════════════════"
echo "✅ LIVE POLYMARKET DATA"
echo "════════════════════════════════"
jq '{timestamp, market_title, up_percent, down_percent, market_status}' "$STATE_FILE"
echo ""
echo "Saved to: $STATE_FILE"
