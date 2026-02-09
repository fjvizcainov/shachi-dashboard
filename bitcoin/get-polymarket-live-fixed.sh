#!/bin/bash

# ✅ POLYMARKET LIVE - FIXED VERSION
# Fixed: Actually finds OPEN (active=true, closed=false) events

echo "📊 Fetching CURRENT Polymarket BTC 15m market..."
echo ""

# 1. Get series
echo "[1] Fetching BTC 15m series..."
SERIES=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m")

if [ -z "$SERIES" ]; then
    echo "❌ Failed to fetch series"
    exit 1
fi

# 2. Find FIRST OPEN event (active=true, closed=false)
echo "[2] Finding first OPEN event..."
MARKET_DATA=$(echo "$SERIES" | python3 -c "
import json, sys
data = json.load(sys.stdin)
series = data[0]
events = series.get('events', [])

for e in events:
    if e.get('active') and not e.get('closed'):
        print(f'{e[\"id\"]}|{e[\"title\"]}')
        sys.exit(0)
print('')
" 2>/dev/null)

if [ -z "$MARKET_DATA" ]; then
    echo "❌ Could not find open market"
    exit 1
fi

ID=$(echo "$MARKET_DATA" | cut -d'|' -f1)
TITLE=$(echo "$MARKET_DATA" | cut -d'|' -f2)

echo "✅ Found: $TITLE (ID: $ID)"
echo ""

# 3. Get market details + prices
echo "[3] Fetching market details..."
MARKET=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events/$ID")

if [ -z "$MARKET" ]; then
    echo "❌ Failed to fetch market"
    exit 1
fi

# Extract prices
PRICES=$(echo "$MARKET" | python3 -c "
import json, sys
data = json.load(sys.stdin)
markets = data.get('markets', [])

if not markets:
    print('50.0|50.0')
    sys.exit(0)

m = markets[0]
outcomes_str = m.get('outcomes', '[\"Up\", \"Down\"]')
prices_str = m.get('outcomePrices', '[0.5, 0.5]')

try:
    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
    
    up_price = float(prices[0]) if prices else 0.5
    down_price = float(prices[1]) if len(prices) > 1 else 0.5
    
    # Sanity check
    if up_price == 0 and down_price == 0:
        up_price = down_price = 0.5
    
    up_percent = round(up_price * 100, 1)
    down_percent = round(down_price * 100, 1)
    
    print(f'{up_percent}|{down_percent}')
except:
    print('50.0|50.0')
" 2>/dev/null)

UP=$(echo "$PRICES" | cut -d'|' -f1)
DOWN=$(echo "$PRICES" | cut -d'|' -f2)

echo "✅ Market odds: UP $UP% / DOWN $DOWN%"
echo ""

# 4. Get BTC price
echo "[4] Fetching BTC price..."
BTC=$(curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(int(d['bitcoin']['usd']))
except:
    print('0')
" 2>/dev/null)

echo "✅ BTC: \$$BTC"
echo ""

# 5. Save state
echo "[5] Saving state..."
cat > /Users/moltbot/clawd/bitcoin/polymarket-state.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$ID",
  "market_title": "$TITLE",
  "up_percent": $UP,
  "down_percent": $DOWN,
  "btc_price": $BTC
}
EOF

echo "✅ Saved!"
echo ""
cat /Users/moltbot/clawd/bitcoin/polymarket-state.json | python3 -m json.tool
