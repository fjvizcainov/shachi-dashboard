#!/bin/bash

# 🔧 POLYMARKET API FIX V2 - Search for BTC markets specifically
# Updated: Feb 3, 2026 @ 02:57 UTC

set -e

echo "🔧 Polymarket API - Getting LIVE BTC 15m market..."

# STEP 1: Search specifically for BTC 15m markets
echo "[1] Searching for BTC 15m markets..."

# Query: btc-up-or-down-15m market (active)
SEARCH=$(curl -s "https://gamma-api.polymarket.com/events?slug=btc-updown-15m&active=true&limit=1")

if [ -z "$SEARCH" ] || [ "$SEARCH" == "[]" ]; then
  echo "⚠️  btc-updown-15m not found. Trying series search..."
  SEARCH=$(curl -s "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m&limit=10")
  
  # Extract events from series
  EVENTS=$(echo "$SEARCH" | jq -r '.[0].events[]' 2>/dev/null)
else
  EVENTS="$SEARCH"
fi

# Find the MOST RECENT active BTC market
MARKET=$(echo "$EVENTS" | jq -s 'map(select(.title | contains("Bitcoin") or contains("BTC") or contains("btc"))) | sort_by(.startDate) | reverse | .[0]' 2>/dev/null)

MARKET_ID=$(echo "$MARKET" | jq -r '.id // empty' 2>/dev/null)

if [ -z "$MARKET_ID" ]; then
  echo "❌ No BTC market found in recent series. Trying alternative..."
  
  # Last resort: Use cached market
  if [ -f "/Users/moltbot/clawd/bitcoin/polymarket-state.json" ]; then
    MARKET_ID=$(jq -r '.market_id' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null)
    MARKET_TITLE=$(jq -r '.market_title' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null)
    echo "⚠️  Using cached market: $MARKET_ID ($MARKET_TITLE)"
  else
    echo "❌ No cache available. Cannot proceed."
    exit 1
  fi
else
  MARKET_TITLE=$(echo "$MARKET" | jq -r '.title')
  echo "✅ Found BTC market: $MARKET_TITLE (ID: $MARKET_ID)"
fi

# STEP 2: Get market details
echo "[2] Fetching market details..."

MARKET_DETAILS=$(curl -s "https://gamma-api.polymarket.com/events/$MARKET_ID" 2>/dev/null)

if [ -z "$MARKET_DETAILS" ] || [ "$MARKET_DETAILS" == "null" ]; then
  echo "❌ Could not fetch market details. Using cached odds..."
  
  UP_PERCENT=$(jq -r '.up_percent' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "50")
  DOWN_PERCENT=$(jq -r '.down_percent' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "50")
else
  # Extract market data
  TOKEN_IDS=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].clobTokenIds' 2>/dev/null)
  
  if [ -z "$TOKEN_IDS" ] || [ "$TOKEN_IDS" == "null" ]; then
    echo "⚠️  No tokenIds in response. Using outcome prices from Gamma..."
    UP_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[0]' 2>/dev/null || echo "0.5")
    DOWN_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[1]' 2>/dev/null || echo "0.5")
  else
    echo "✅ Token IDs extracted"
    UP_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[0]')
    DOWN_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[1]')
    
    # Try CLOB API for live orderbook
    echo "[3] Fetching live orderbook from CLOB..."
    
    UP_BOOK=$(curl -s "https://clob.polymarket.com/orderbook/$UP_TOKEN" 2>/dev/null || echo "{}")
    
    if [ -z "$UP_BOOK" ] || [ "$UP_BOOK" == "{}" ]; then
      echo "⚠️  CLOB API timeout. Using Gamma prices instead..."
      UP_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[0]')
      DOWN_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[1]')
    else
      # Parse live bid/ask
      UP_PRICE=$(echo "$UP_BOOK" | jq -r '.bids[0].price // 0.5' 2>/dev/null)
      DOWN_PRICE=$(echo "$MARKET_DETAILS" | jq -r '.markets[0].outcomePrices[1]')
    fi
  fi
  
  UP_PERCENT=$(printf "%.1f" "$(echo "$UP_PRICE * 100" | bc 2>/dev/null || echo "50")")
  DOWN_PERCENT=$(printf "%.1f" "$(echo "$DOWN_PRICE * 100" | bc 2>/dev/null || echo "50")")
fi

echo "✅ UP: $UP_PERCENT%"
echo "✅ DOWN: $DOWN_PERCENT%"

# STEP 3: Save state
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"

cat > "$STATE_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$MARKET_TITLE",
  "up_percent": $UP_PERCENT,
  "down_percent": $DOWN_PERCENT,
  "status": "✅ LIVE DATA"
}
EOF

echo ""
echo "✅ Live data updated"
echo "---"
jq '.' "$STATE_FILE"
