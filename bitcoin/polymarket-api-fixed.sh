#!/bin/bash

# 🔧 POLYMARKET API FIX - Correct endpoints for live data
# Updated: Feb 3, 2026
# Issues fixed: 404 errors, incorrect endpoints

set -e

echo "🔧 Polymarket API - Getting live market data..."

# STEP 1: Discover active BTC 15m market via Gamma API
echo "[1] Fetching series 10192 (BTC Up or Down 15m) from Gamma..."

SERIES_RESPONSE=$(curl -s "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m&limit=1")

if [ -z "$SERIES_RESPONSE" ] || [ "$SERIES_RESPONSE" == "[]" ]; then
  echo "❌ No series found. Trying alternative endpoint..."
  
  # Alternative: Get all active markets and filter
  SERIES_RESPONSE=$(curl -s "https://gamma-api.polymarket.com/events?tag=15M&active=true&limit=10")
fi

echo "$SERIES_RESPONSE" | jq '.' > /tmp/series-response.json

# Extract first event (most recent market)
MARKET_ID=$(echo "$SERIES_RESPONSE" | jq -r '.[0].id // empty' 2>/dev/null)

if [ -z "$MARKET_ID" ]; then
  echo "❌ Could not find active market. Checking stored state..."
  if [ -f "/Users/moltbot/clawd/bitcoin/polymarket-state.json" ]; then
    MARKET_ID=$(jq -r '.market_id' /Users/moltbot/clawd/bitcoin/polymarket-state.json)
    echo "Using cached market: $MARKET_ID"
  else
    echo "❌ No cached market either. Exiting."
    exit 1
  fi
fi

echo "✅ Market ID: $MARKET_ID"

# STEP 2: Get market details (includes tokenIds for CLOB API)
echo "[2] Fetching market details from Gamma..."

MARKET_DETAILS=$(curl -s "https://gamma-api.polymarket.com/events/$MARKET_ID")

MARKET_TITLE=$(echo "$MARKET_DETAILS" | jq -r '.title' 2>/dev/null)
TOKEN_IDS=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].clobTokenIds' 2>/dev/null)

if [ -z "$TOKEN_IDS" ] || [ "$TOKEN_IDS" == "null" ]; then
  echo "❌ Could not extract tokenIds. Response:"
  echo "$MARKET_DETAILS" | jq '.'
  exit 1
fi

UP_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[0]')
DOWN_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[1]')

echo "✅ Market: $MARKET_TITLE"
echo "✅ UP Token: $UP_TOKEN"
echo "✅ DOWN Token: $DOWN_TOKEN"

# STEP 3: Get LIVE ORDERBOOK from CLOB API (THIS IS THE KEY ENDPOINT)
echo "[3] Fetching orderbook from CLOB API (real-time prices)..."

UP_BOOK=$(curl -s "https://clob.polymarket.com/orderbook/$UP_TOKEN" 2>/dev/null)
DOWN_BOOK=$(curl -s "https://clob.polymarket.com/orderbook/$DOWN_TOKEN" 2>/dev/null)

if [ -z "$UP_BOOK" ] || [ "$UP_BOOK" == "null" ]; then
  echo "⚠️  CLOB API not returning data. Trying fallback to Gamma prices..."
  
  UP_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[0]' 2>/dev/null)
  DOWN_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[1]' 2>/dev/null)
else
  # Parse CLOB orderbook
  UP_BEST_BID=$(echo "$UP_BOOK" | jq -r '.bids[0].price // 0' 2>/dev/null)
  UP_BEST_ASK=$(echo "$UP_BOOK" | jq -r '.asks[0].price // 1' 2>/dev/null)
  UP_PRICE=$(echo "($UP_BEST_BID + $UP_BEST_ASK) / 2" | bc -l)
  
  DOWN_BEST_BID=$(echo "$DOWN_BOOK" | jq -r '.bids[0].price // 0' 2>/dev/null)
  DOWN_BEST_ASK=$(echo "$DOWN_BOOK" | jq -r '.asks[0].price // 1' 2>/dev/null)
  DOWN_PRICE=$(echo "($DOWN_BEST_BID + $DOWN_BEST_ASK) / 2" | bc -l)
fi

UP_PERCENT=$(echo "scale=1; $UP_PRICE * 100" | bc)
DOWN_PERCENT=$(echo "scale=1; $DOWN_PRICE * 100" | bc)

echo "✅ UP: $UP_PERCENT% (best bid: $UP_BEST_BID, ask: $UP_BEST_ASK)"
echo "✅ DOWN: $DOWN_PERCENT% (best bid: $DOWN_BEST_BID, ask: $DOWN_BEST_ASK)"

# STEP 4: Save current state
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"

cat > "$STATE_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$MARKET_TITLE",
  "up_price": $UP_PRICE,
  "down_price": $DOWN_PRICE,
  "up_percent": $UP_PERCENT,
  "down_percent": $DOWN_PERCENT,
  "up_token_id": "$UP_TOKEN",
  "down_token_id": "$DOWN_TOKEN",
  "up_bid": $UP_BEST_BID,
  "up_ask": $UP_BEST_ASK,
  "down_bid": $DOWN_BEST_BID,
  "down_ask": $DOWN_BEST_ASK,
  "volume": "$(echo "$MARKET_DETAILS" | jq -r '.markets[0].volume' 2>/dev/null)"
}
EOF

echo ""
echo "✅ State saved to $STATE_FILE"
echo ""
echo "📊 SUMMARY"
echo "─────────────────────────────────────"
jq '{timestamp, up_percent, down_percent, volume}' "$STATE_FILE"
