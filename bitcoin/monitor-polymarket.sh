#!/bin/bash

# Polymarket BTC 15m Monitor - Real-time odds tracking
# Runs every 30 seconds to detect market movements
# Series ID: 10192 (BTC Up or Down 15m recurring)

SERIES_ID="10192"
GAMMA_API="https://gamma-api.polymarket.com"
CLOB_API="https://clob.polymarket.com"
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
TRACKER_FILE="/Users/moltbot/clawd/bitcoin/tracking/polymarket-72h-tracker.json"
LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/polymarket-monitor.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$(date)] Starting Polymarket BTC 15m monitor..." >> "$LOG_FILE"

# Step 1: Fetch latest active market from series
echo "[$(date)] Fetching active markets from series $SERIES_ID..." >> "$LOG_FILE"

MARKETS=$(curl -s "${GAMMA_API}/events?series_id=${SERIES_ID}&active=true&limit=1")

if [ -z "$MARKETS" ] || [ "$MARKETS" == "[]" ]; then
  echo "[$(date)] ❌ No active markets found" >> "$LOG_FILE"
  exit 1
fi

# Parse market data
MARKET_ID=$(echo "$MARKETS" | jq -r '.[0].id')
MARKET_TITLE=$(echo "$MARKETS" | jq -r '.[0].title')
MARKET_STATUS=$(echo "$MARKETS" | jq -r '.[0].active')

echo "[$(date)] ✅ Found market: $MARKET_TITLE (ID: $MARKET_ID, Active: $MARKET_STATUS)" >> "$LOG_FILE"

# Step 2: Extract tokenIds and outcomes
TOKEN_IDS=$(echo "$MARKETS" | jq -r '.[0].markets[0].clobTokenIds')
OUTCOME_PRICES=$(echo "$MARKETS" | jq -r '.[0].markets[0].outcomePrices')
OUTCOMES=$(echo "$MARKETS" | jq -r '.[0].markets[0].outcomes')

UP_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[0]')
DOWN_TOKEN=$(echo "$TOKEN_IDS" | jq -r '.[1]')

UP_PRICE=$(echo "$OUTCOME_PRICES" | jq -r '.[0]')
DOWN_PRICE=$(echo "$OUTCOME_PRICES" | jq -r '.[1]')

UP_PERCENT=$((${UP_PRICE%.*} * 100))
DOWN_PERCENT=$((${DOWN_PRICE%.*} * 100))

echo "[$(date)] 💹 UP: $UP_PERCENT% | DOWN: $DOWN_PERCENT%" >> "$LOG_FILE"

# Step 3: Load previous state and compare
if [ -f "$STATE_FILE" ]; then
  PREV_UP=$(jq -r '.up_percent' "$STATE_FILE" 2>/dev/null || echo "0")
  PREV_DOWN=$(jq -r '.down_percent' "$STATE_FILE" 2>/dev/null || echo "0")
  
  UP_CHANGE=$(echo "$UP_PERCENT - $PREV_UP" | bc)
  DOWN_CHANGE=$(echo "$DOWN_PERCENT - $PREV_DOWN" | bc)
  
  # Detect spikes (>50% movement)
  if [ "${UP_CHANGE%.*}" -gt "50" ] || [ "${DOWN_CHANGE%.*}" -gt "50" ]; then
    echo "[$(date)] ⚡ SPIKE DETECTED! UP: +${UP_CHANGE}% | DOWN: +${DOWN_CHANGE}%" >> "$LOG_FILE"
    # Send alert to Telegram
  fi
else
  UP_CHANGE="0"
  DOWN_CHANGE="0"
fi

# Step 4: Save current state
cat > "$STATE_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$MARKET_TITLE",
  "up_percent": $UP_PERCENT,
  "down_percent": $DOWN_PERCENT,
  "up_token_id": "$UP_TOKEN",
  "down_token_id": "$DOWN_TOKEN",
  "up_change": $UP_CHANGE,
  "down_change": $DOWN_CHANGE
}
EOF

echo "[$(date)] 💾 State saved to $STATE_FILE" >> "$LOG_FILE"

# Step 5: Update tracker if divergence detected
echo "[$(date)] ✓ Monitor cycle complete" >> "$LOG_FILE"
