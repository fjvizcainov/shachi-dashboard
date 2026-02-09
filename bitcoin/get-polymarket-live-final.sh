#!/bin/bash

# ✅ POLYMARKET LIVE DATA - FINAL SIMPLE VERSION
# No dependencies, just curl + jq

echo "📊 Fetching CURRENT Polymarket BTC..."

# Get series with events
DATA=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m")

# Extract first (most recent) event
EVENT_ID=$(echo "$DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
events = d[0]['events']
# Find event that's NOT closed
for e in events:
    if not e.get('closed', False):
        print(e['id'])
        break
else:
    # Fallback: just use most recent
    print(events[0]['id'])
" 2>/dev/null)

echo "✅ Event ID: $EVENT_ID"

# Get market details
MARKET=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events/$EVENT_ID")

# Extract outcomes
UP=$(echo "$MARKET" | python3 -c "
import json, sys
d = json.load(sys.stdin)
prices = json.loads(d['markets'][0]['outcomePrices'])
print(round(float(prices[0]) * 100, 1))
" 2>/dev/null || echo "50")

DOWN=$(echo "100 - $UP" | bc)

# Get BTC price
BTC=$(curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(int(d['bitcoin']['usd']))
" 2>/dev/null || echo "78000")

# Save
cat > /Users/moltbot/clawd/bitcoin/polymarket-state.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$EVENT_ID",
  "up_percent": $UP,
  "down_percent": $DOWN,
  "btc_price": $BTC,
  "status": "✅ LIVE"
}
EOF

echo "✅ UP: $UP%"
echo "✅ DOWN: $DOWN%"
echo "✅ BTC: \$$BTC"
echo ""
cat /Users/moltbot/clawd/bitcoin/polymarket-state.json
