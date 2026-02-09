#!/bin/bash

echo "📊 Fetching CURRENT Polymarket BTC 15m market..."
echo ""

# 1. Fetch series to temp file
echo "[1] Fetching BTC 15m series..."
TEMP_SERIES="/tmp/polymarket-series-$$.json"
curl -s --max-time 5 "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m" > "$TEMP_SERIES"

if [ ! -s "$TEMP_SERIES" ]; then
    echo "❌ Failed to fetch series"
    rm -f "$TEMP_SERIES"
    exit 1
fi

# 2. Find first OPEN event using Python on the file
echo "[2] Finding first OPEN event..."
MARKET_DATA=$(python3 << 'PYTHON_SCRIPT'
import json
import sys

try:
    with open('/tmp/polymarket-series-' + str(sys.argv[1]), 'r') as f:
        data = json.load(f)
    
    series = data[0]
    events = series.get('events', [])
    
    for e in events:
        if e.get('active') and not e.get('closed'):
            print(f'{e["id"]}|{e["title"]}')
            sys.exit(0)
    
    print('')
except Exception as ex:
    print(f'Error: {ex}', file=sys.stderr)
    print('')
PYTHON_SCRIPT
$$ 2>/dev/null)

if [ -z "$MARKET_DATA" ]; then
    echo "❌ Could not find open market"
    rm -f "$TEMP_SERIES"
    exit 1
fi

ID=$(echo "$MARKET_DATA" | cut -d'|' -f1)
TITLE=$(echo "$MARKET_DATA" | cut -d'|' -f2-)

echo "✅ Found: $TITLE"
echo "   ID: $ID"
echo ""

# 3. Fetch market details
echo "[3] Fetching market details..."
TEMP_MARKET="/tmp/polymarket-event-$$.json"
curl -s --max-time 5 "https://gamma-api.polymarket.com/events/$ID" > "$TEMP_MARKET"

if [ ! -s "$TEMP_MARKET" ]; then
    echo "❌ Failed to fetch market"
    rm -f "$TEMP_SERIES" "$TEMP_MARKET"
    exit 1
fi

# Extract prices from market
PRICES=$(python3 << 'PYTHON_PRICES'
import json
import sys

try:
    with open(sys.argv[1], 'r') as f:
        data = json.load(f)
    
    markets = data.get('markets', [])
    if not markets:
        print('50.0|50.0')
        sys.exit(0)
    
    m = markets[0]
    outcomes_str = m.get('outcomes', '["Up", "Down"]')
    prices_str = m.get('outcomePrices', '[0.5, 0.5]')
    
    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
    
    up_price = float(prices[0]) if prices else 0.5
    down_price = float(prices[1]) if len(prices) > 1 else 0.5
    
    if up_price == 0 and down_price == 0:
        up_price = down_price = 0.5
    
    up_percent = round(up_price * 100, 1)
    down_percent = round(down_price * 100, 1)
    
    print(f'{up_percent}|{down_percent}')
except Exception as ex:
    print(f'Error: {ex}', file=sys.stderr)
    print('50.0|50.0')
PYTHON_PRICES
$TEMP_MARKET 2>/dev/null)

UP=$(echo "$PRICES" | cut -d'|' -f1)
DOWN=$(echo "$PRICES" | cut -d'|' -f2)

echo "✅ Market odds: UP $UP% / DOWN $DOWN%"
echo ""

# 4. Get BTC price
echo "[4] Fetching BTC price..."
TEMP_BTC="/tmp/btc-price-$$.json"
curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" > "$TEMP_BTC"

BTC=$(python3 << 'PYTHON_BTC'
import json
import sys

try:
    with open(sys.argv[1], 'r') as f:
        d = json.load(f)
    print(int(d['bitcoin']['usd']))
except:
    print('0')
PYTHON_BTC
$TEMP_BTC 2>/dev/null)

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
cat /Users/moltbot/clawd/bitcoin/polymarket-state.json

# Cleanup
rm -f "$TEMP_SERIES" "$TEMP_MARKET" "$TEMP_BTC"
