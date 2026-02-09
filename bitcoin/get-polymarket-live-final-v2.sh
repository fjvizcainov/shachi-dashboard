#!/bin/bash

# ✅ POLYMARKET LIVE - FINAL CORRECTED VERSION
# Uses curl + python (no requests library)

echo "📊 Fetching CURRENT Polymarket BTC 15m market...\n"

# 1. Get series
echo "[1] Fetching BTC 15m series..."
SERIES=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m")

# 2. Find FIRST OPEN (active AND not closed) event
echo "[2] Finding first OPEN event (active && !closed)..."
MARKET_ID=$(echo "$SERIES" | python3 << 'PYSCRIPT'
import json, sys
try:
    data = json.load(sys.stdin)
    if not data:
        print('')
        sys.exit(1)

    series = data[0]
    events = series.get('events', [])

    # Find first event that is BOTH active AND not closed
    for e in events:
        if e.get('active') == True and e.get('closed') == False:
            print(f'{e["id"]}|{e["title"]}|True')
            sys.exit(0)

    print('')
except Exception as ex:
    print(f'', file=sys.stderr)
    print('')
PYSCRIPT
)

if [ -z "$MARKET_ID" ]; then
    echo "❌ Could not find market"
    exit 1
fi

ID=$(echo "$MARKET_ID" | cut -d'|' -f1)
TITLE=$(echo "$MARKET_ID" | cut -d'|' -f2)
ACTIVE=$(echo "$MARKET_ID" | cut -d'|' -f3)

echo "✅ Market: $TITLE"
echo "   ID: $ID, Active: $ACTIVE"

# 3. Get market details
echo ""
echo "[3] Fetching market details..."
MARKET=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events/$ID")

# Extract prices
PRICES=$(echo "$MARKET" | python3 -c "
import json, sys
data = json.load(sys.stdin)
m = data.get('markets', [{}])[0]

outcomes_str = m.get('outcomes', '[\"Up\", \"Down\"]')
prices_str = m.get('outcomePrices', '[0.5, 0.5]')

outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str

up_price = float(prices[0]) if prices and str(prices[0]) != '0' else 0.5
down_price = float(prices[1]) if prices and len(prices) > 1 and str(prices[1]) != '0' else 0.5

# Handle all-zeros (historical market)
if up_price == 0 and down_price == 0:
    up_price = 0.5
    down_price = 0.5

# Handle if one is 0, other is 1 (resolved market)
if (up_price == 0 and down_price == 1) or (up_price == 1 and down_price == 0):
    up_price = 0.5
    down_price = 0.5

up_percent = round(up_price * 100, 1)
down_percent = round(down_price * 100, 1)

print(f'{up_percent}|{down_percent}')
" 2>/dev/null)

UP=$(echo "$PRICES" | cut -d'|' -f1)
DOWN=$(echo "$PRICES" | cut -d'|' -f2)

echo "✅ UP: $UP% / DOWN: $DOWN%"

# 4. Get BTC price
echo ""
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

# 5. Save
echo ""
echo "[5] Saving state..."
cat > /Users/moltbot/clawd/bitcoin/polymarket-state.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$ID",
  "market_title": "$TITLE",
  "market_active": true,
  "up_percent": $UP,
  "down_percent": $DOWN,
  "btc_price": $BTC,
  "source": "Gamma API (corrected)"
}
EOF

echo "✅ Saved!"
echo ""
cat /Users/moltbot/clawd/bitcoin/polymarket-state.json | python3 -m json.tool
