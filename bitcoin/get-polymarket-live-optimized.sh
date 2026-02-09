#!/bin/bash

# ✅ POLYMARKET LIVE - OPTIMIZED (Avoids 25MB Series Bloat)
# Uses direct market endpoint to fetch current odds

echo "📊 Fetching CURRENT Polymarket BTC 15m market...\n"

# 1. Get the market directly (known IDs from monitoring log)
# BTC 15m markets are in series 10192, cycling through different event IDs

echo "[1] Querying recent markets from series 10192..."

# Fetch recent markets from the series - limit to 5 to avoid bloat
MARKETS=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events?series_id=10192&limit=5&active=true" 2>/dev/null)

# Extract first active market
MARKET_ID=$(echo "$MARKETS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if isinstance(data, list) and len(data) > 0:
        for m in data:
            if m.get('active') == True and m.get('closed') == False:
                print(m['id'])
                break
except:
    pass
" 2>/dev/null)

if [ -z "$MARKET_ID" ]; then
    echo "❌ No active markets found in series 10192, fallback to market list"
    # Fallback: search by title
    MARKET_ID=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events?search=Bitcoin%20Up%20or%20Down%2015&limit=1&active=true" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if isinstance(data, list) and len(data) > 0:
        print(data[0]['id'])
except:
    pass
" 2>/dev/null)
fi

if [ -z "$MARKET_ID" ]; then
    echo "❌ Could not find market"
    exit 1
fi

echo "✅ Found Market ID: $MARKET_ID"

# 2. Fetch market detail
echo ""
echo "[2] Fetching market details..."
MARKET=$(curl -s --max-time 5 "https://gamma-api.polymarket.com/events/$MARKET_ID" 2>/dev/null)

# Extract title, active status, and prices
DATA=$(echo "$MARKET" | python3 -c "
import json, sys
try:
    m = json.load(sys.stdin)
    title = m.get('title', 'Unknown')
    active = m.get('active', False)
    
    # Get market prices
    markets = m.get('markets', [])
    if markets:
        market = markets[0]
        outcomes = market.get('outcomes', ['Up', 'Down'])
        prices = market.get('outcomePrices', [0.5, 0.5])
        
        up_price = float(prices[0]) if prices else 0.5
        down_price = float(prices[1]) if len(prices) > 1 else 0.5
        
        # Normalize dead markets
        if up_price == 0 and down_price == 0:
            up_price = 0.5
            down_price = 0.5
        if (up_price == 0 and down_price == 1) or (up_price == 1 and down_price == 0):
            up_price = 0.5
            down_price = 0.5
        
        up_percent = round(up_price * 100, 1)
        down_percent = round(down_price * 100, 1)
        
        print(f'{title}|{active}|{up_percent}|{down_percent}')
except Exception as e:
    print(f'|||')
" 2>/dev/null)

TITLE=$(echo "$DATA" | cut -d'|' -f1)
ACTIVE=$(echo "$DATA" | cut -d'|' -f2)
UP=$(echo "$DATA" | cut -d'|' -f3)
DOWN=$(echo "$DATA" | cut -d'|' -f4)

if [ -z "$UP" ] || [ "$UP" = "" ]; then
    echo "❌ Failed to extract prices"
    exit 1
fi

echo "✅ Market: $TITLE"
echo "   Active: $ACTIVE | UP: $UP% / DOWN: $DOWN%"

# 3. Get BTC price
echo ""
echo "[3] Fetching BTC price..."
BTC=$(curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(int(d['bitcoin']['usd']))
except:
    print('0')
" 2>/dev/null)

echo "✅ BTC: \$$BTC"

# 4. Save state
echo ""
echo "[4] Saving state..."
cat > /Users/moltbot/clawd/bitcoin/polymarket-state.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$TITLE",
  "market_active": true,
  "up_percent": $UP,
  "down_percent": $DOWN,
  "btc_price": $BTC,
  "source": "Gamma API (optimized)"
}
EOF

echo "✅ Saved!"
echo ""
cat /Users/moltbot/clawd/bitcoin/polymarket-state.json
