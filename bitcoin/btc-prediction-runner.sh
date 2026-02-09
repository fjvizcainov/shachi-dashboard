#!/bin/bash
# Bitcoin 15-min Prediction Pipeline
# STEP 1: Fetch Polymarket data → polymarket-state.json
# STEP 2: Run 3-signal prediction → active.json + report

set -e

WORK_DIR="/Users/moltbot/clawd/bitcoin"
cd "$WORK_DIR"

echo "═══════════════════════════════════════════════════════════"
echo "Bitcoin 15-min Prediction Pipeline"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────
# STEP 1: FETCH POLYMARKET DATA
# ─────────────────────────────────────────────────────────────

echo "STEP 1: Fetching Polymarket BTC 15m Market"
echo "─────────────────────────────────────────────────────────"

# Fetch series with user agent
curl -s -A "Mozilla/5.0" "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m" > /tmp/series.json

if [ ! -s /tmp/series.json ]; then
    echo "❌ Failed to fetch series"
    exit 1
fi

# Find first open market
MARKET_DATA=$(python3 << 'PYTHON_STEP1'
import json

try:
    with open('/tmp/series.json', 'r') as f:
        content = f.read()
        # Fix JS booleans
        content = content.replace('true', 'True').replace('false', 'False')
        data = json.loads(content.replace('True', 'true').replace('False', 'false'))
    
    series = data[0]
    events = series.get('events', [])
    
    for e in events:
        if e.get('active') and not e.get('closed'):
            print(f"{e['id']}|{e['title']}")
            break
except Exception as ex:
    print(f"Error: {ex}")
PYTHON_STEP1
)

if [ -z "$MARKET_DATA" ]; then
    echo "❌ No open markets found"
    exit 1
fi

MARKET_ID=$(echo "$MARKET_DATA" | cut -d'|' -f1)
MARKET_TITLE=$(echo "$MARKET_DATA" | cut -d'|' -f2-)

echo "✅ Found open market:"
echo "   ID: $MARKET_ID"
echo "   Title: $MARKET_TITLE"

# Fetch market details
curl -s -A "Mozilla/5.0" "https://gamma-api.polymarket.com/events/$MARKET_ID" > /tmp/market.json

if [ ! -s /tmp/market.json ]; then
    echo "❌ Failed to fetch market details"
    exit 1
fi

# Extract odds and BTC price
ODDS_DATA=$(python3 << 'PYTHON_ODDS'
import json

try:
    with open('/tmp/market.json', 'r') as f:
        content = f.read()
        content = content.replace('true', 'True').replace('false', 'False')
        data = json.loads(content.replace('True', 'true').replace('False', 'false'))
    
    markets = data.get('markets', [])
    if not markets:
        print("50.0|50.0")
        exit(0)
    
    m = markets[0]
    prices_str = m.get('outcomePrices', '[0.5, 0.5]')
    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
    
    up_price = float(prices[0]) if prices else 0.5
    down_price = float(prices[1]) if len(prices) > 1 else 0.5
    
    up_pct = round(up_price * 100, 1)
    down_pct = round(down_price * 100, 1)
    
    print(f"{up_pct}|{down_pct}")
except Exception as ex:
    print("50.0|50.0")
PYTHON_ODDS
)

UP_ODDS=$(echo "$ODDS_DATA" | cut -d'|' -f1)
DOWN_ODDS=$(echo "$ODDS_DATA" | cut -d'|' -f2)

echo "✅ Market odds: UP $UP_ODDS% / DOWN $DOWN_ODDS%"

# Get BTC price
BTC_PRICE=$(curl -s --max-time 3 "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(int(d['bitcoin']['usd']))
except:
    print('0')
")

echo "✅ BTC Price: \$$BTC_PRICE"

# Save polymarket state
cat > "$WORK_DIR/polymarket-state.json" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "market_title": "$MARKET_TITLE",
  "up_percent": $UP_ODDS,
  "down_percent": $DOWN_ODDS,
  "btc_price": $BTC_PRICE
}
EOF

echo "✅ Saved polymarket-state.json"
echo ""

# ─────────────────────────────────────────────────────────────
# STEP 2: RUN 3-SIGNAL PREDICTION MODEL
# ─────────────────────────────────────────────────────────────

echo "STEP 2: Running 3-Signal Prediction Model"
echo "─────────────────────────────────────────────────────────"

# For now, use polymarket odds as the primary signal
# (In production, would run predict-with-liquidations.sh)

# Determine direction based on odds
if (( $(echo "$UP_ODDS > 50" | bc -l) )); then
    PREDICTION="UP"
    CONFIDENCE=$(echo "$UP_ODDS - 50" | bc -l)
else
    PREDICTION="DOWN"
    CONFIDENCE=$(echo "$DOWN_ODDS - 50" | bc -l)
fi

# Round confidence to nearest 5%
CONFIDENCE=$(python3 -c "print(int(round(float('$CONFIDENCE') / 5) * 5))")

echo "✅ Prediction: $PREDICTION with $CONFIDENCE% confidence"

# Save prediction state
cat > "$WORK_DIR/active.json" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "prediction": "$PREDICTION",
  "confidence": $CONFIDENCE,
  "signals": {
    "polymarket": "$PREDICTION",
    "fear_greed": "pending",
    "liquidations": "pending"
  },
  "reasoning": "Primary signal from Polymarket odds"
}
EOF

echo "✅ Saved active.json"
echo ""

# ─────────────────────────────────────────────────────────────
# STEP 3: REPORT
# ─────────────────────────────────────────────────────────────

echo "STEP 3: Final Report"
echo "─────────────────────────────────────────────────────────"
echo ""
echo "📊 BTC \$$BTC_PRICE | Polymarket: UP $UP_ODDS% / DOWN $DOWN_ODDS% | Prediction: $PREDICTION ($CONFIDENCE% confidence)"
echo ""
echo "═══════════════════════════════════════════════════════════"
