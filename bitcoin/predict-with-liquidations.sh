#!/bin/bash

# 🚀 IMPROVED BTC PREDICTION MODEL
# Incorporates 3 signals:
# 1. Polymarket odds (market consensus)
# 2. Fear & Greed Index (sentiment)
# 3. Liquidation heatmap (technical pressure)

echo "🚀 Bitcoin 15-Minute Prediction (with Liquidations)..."

# Load current market data
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"

if [ ! -f "$STATE_FILE" ]; then
  echo "❌ No market data. Run get-polymarket-live-final-v2.sh first"
  exit 1
fi

# Extract market data
BTC=$(jq -r '.btc_price' "$STATE_FILE")
UP=$(jq -r '.up_percent' "$STATE_FILE")
DOWN=$(jq -r '.down_percent' "$STATE_FILE")
MARKET_ID=$(jq -r '.market_id' "$STATE_FILE")

echo "📊 Current Market:"
echo "  BTC: \$$BTC"
echo "  Polymarket: UP $UP% / DOWN $DOWN%"
echo "  Market ID: $MARKET_ID"

# SIGNAL 1: Polymarket odds (base signal)
echo ""
echo "📈 SIGNAL 1: Polymarket Odds"

if (( $(echo "$UP > 60" | bc -l) )); then
  SIG1="UP"
  SIG1_CONF=$UP
  echo "  → Strong UP signal ($UP%)"
elif (( $(echo "$DOWN > 60" | bc -l) )); then
  SIG1="DOWN"
  SIG1_CONF=$DOWN
  echo "  → Strong DOWN signal ($DOWN%)"
else
  SIG1="NEUTRAL"
  SIG1_CONF=50
  echo "  → Neutral/Tied ($UP% vs $DOWN%)"
fi

# SIGNAL 2: Fear & Greed Index
echo ""
echo "😨 SIGNAL 2: Fear & Greed Index"

FGI=$(curl -s --max-time 3 "https://api.alternative.me/fng/?limit=1&format=json" | \
  python3 -c "import json, sys; d=json.load(sys.stdin); print(d['data'][0]['value'])" 2>/dev/null || echo "50")

echo "  F&G Index: $FGI"

if (( $(echo "$FGI < 25" | bc -l) )); then
  SIG2="DOWN"
  SIG2_CONF=$((100 - FGI))
  echo "  → Extreme Fear ($FGI) = Bearish pressure"
elif (( $(echo "$FGI > 75" | bc -l) )); then
  SIG2="UP"
  SIG2_CONF=$FGI
  echo "  → Greed ($FGI) = Bullish signal"
else
  SIG2="NEUTRAL"
  SIG2_CONF=50
  echo "  → Neutral sentiment ($FGI)"
fi

# SIGNAL 3: Liquidation Heatmap
echo ""
echo "🔥 SIGNAL 3: Liquidation Pressure"

# Fetch liquidations from Bybit
LIQDATA=$(curl -s --max-time 3 \
  "https://api.bybit.com/v5/public/liquidation?category=linear&symbol=BTCUSDT&limit=50" 2>/dev/null)

if [ ! -z "$LIQDATA" ]; then
  SIG3=$(echo "$LIQDATA" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    liq_list = d.get('result', {}).get('list', [])
    
    # Count by side
    buy_liq = len([x for x in liq_list if x.get('side') == 'Buy'])
    sell_liq = len([x for x in liq_list if x.get('side') == 'Sell'])
    
    if buy_liq > sell_liq * 1.5:
        print('DOWN|LONG_LIQUIDATIONS')  # Longs getting liquidated = bearish
    elif sell_liq > buy_liq * 1.5:
        print('UP|SHORT_LIQUIDATIONS')   # Shorts getting liquidated = bullish
    else:
        print('NEUTRAL|BALANCED')
except:
    print('NEUTRAL|DATA_ERROR')
" 2>/dev/null)
  
  SIG3_DIR=$(echo "$SIG3" | cut -d'|' -f1)
  SIG3_TYPE=$(echo "$SIG3" | cut -d'|' -f2)
  
  echo "  Liquidations: $SIG3_TYPE"
  echo "  Signal: $SIG3_DIR"
else
  echo "  ⚠️  Liquidation data unavailable (API timeout)"
  SIG3="NEUTRAL"
  SIG3_TYPE="UNAVAILABLE"
fi

# SIGNAL CONSENSUS
echo ""
echo "🎯 SIGNAL CONSENSUS"
echo "  1. Polymarket: $SIG1 ($SIG1_CONF%)"
echo "  2. F&G Index: $SIG2 ($FGI)"
echo "  3. Liquidations: $SIG3 ($SIG3_TYPE)"

# Decision logic: 2 or 3 signals agreeing = strong prediction
UP_VOTES=0
DOWN_VOTES=0

[ "$SIG1" == "UP" ] && ((UP_VOTES++)) || ([ "$SIG1" == "DOWN" ] && ((DOWN_VOTES++)))
[ "$SIG2" == "UP" ] && ((UP_VOTES++)) || ([ "$SIG2" == "DOWN" ] && ((DOWN_VOTES++)))
[ "$SIG3" == "UP" ] && ((UP_VOTES++)) || ([ "$SIG3" == "DOWN" ] && ((DOWN_VOTES++)))

if [ $UP_VOTES -ge 2 ]; then
  PREDICTION="UP"
  CONFIDENCE=$(( (SIG1_CONF + FGI) / 2 ))
  CONFIDENCE=$(( CONFIDENCE > 75 ? 75 : CONFIDENCE ))
  REASONING="2+ signals align on UP (Polymarket + Market sentiment)"
elif [ $DOWN_VOTES -ge 2 ]; then
  PREDICTION="DOWN"
  # Confidence = combined bearish signals
  CONFIDENCE=$(( 100 - ((SIG1_CONF + FGI) / 2) ))
  CONFIDENCE=$(( CONFIDENCE > 75 ? 75 : CONFIDENCE ))
  REASONING="2+ signals align on DOWN (Fear + Liquidations)"
else
  # Split decision: use Polymarket as tiebreaker
  if (( $(echo "$UP > $DOWN" | bc -l) )); then
    PREDICTION="UP"
    CONFIDENCE=$UP
    REASONING="Signals split, Polymarket UP edge breaks tie"
  else
    PREDICTION="DOWN"
    CONFIDENCE=$DOWN
    REASONING="Signals split, Polymarket DOWN edge breaks tie"
  fi
fi

echo ""
echo "✅ FINAL PREDICTION: $PREDICTION ($CONFIDENCE% confidence)"
echo "   Reasoning: $REASONING"

# Save prediction
cat > /Users/moltbot/clawd/bitcoin/predictions/active.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "btc_price": $BTC,
  "polymarket": {
    "up": $UP,
    "down": $DOWN,
    "signal": "$SIG1",
    "confidence": $SIG1_CONF
  },
  "fear_greed": {
    "index": $FGI,
    "signal": "$SIG2"
  },
  "liquidations": {
    "signal": "$SIG3",
    "type": "$SIG3_TYPE"
  },
  "prediction": "$PREDICTION",
  "confidence": $CONFIDENCE,
  "reasoning": "$REASONING",
  "signal_votes": {
    "up": $UP_VOTES,
    "down": $DOWN_VOTES
  }
}
EOF

echo ""
echo "✅ Saved to ~/clawd/bitcoin/predictions/active.json"
