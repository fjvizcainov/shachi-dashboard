#!/bin/bash

# 🚀 INDEPENDENT BTC PREDICTION MODEL
# My own prediction based on ALL available signals
# Then compare vs Polymarket as a market data point (not arbiter)

echo "🚀 Independent Bitcoin Prediction (NOT tied to Polymarket)..."

# Load market data
STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"

if [ ! -f "$STATE_FILE" ]; then
  echo "❌ No market data"
  exit 1
fi

BTC=$(jq -r '.btc_price' "$STATE_FILE")
PM_UP=$(jq -r '.up_percent' "$STATE_FILE")
PM_DOWN=$(jq -r '.down_percent' "$STATE_FILE")
MARKET_ID=$(jq -r '.market_id' "$STATE_FILE")

echo "📊 Available Data:"
echo "  BTC: \$$BTC"
echo "  Polymarket: UP $PM_UP% / DOWN $PM_DOWN%"

# ============================================================================
# MY OWN SIGNALS (Independent of Polymarket)
# ============================================================================

echo ""
echo "🔍 ANALYZING MY OWN SIGNALS:"

# SIGNAL 1: Fear & Greed Index
echo ""
echo "[1] Fear & Greed Index:"
FGI=$(curl -s --max-time 3 "https://api.alternative.me/fng/?limit=1&format=json" | \
  python3 -c "import json, sys; d=json.load(sys.stdin); print(d['data'][0]['value'])" 2>/dev/null || echo "50")

echo "  F&G: $FGI"

if (( $(echo "$FGI < 25" | bc -l) )); then
  FGI_SIGNAL="BEARISH"
  FGI_STRENGTH=3  # Strong signal
  echo "  → Extreme Fear = Bearish cascade likely"
elif (( $(echo "$FGI > 75" | bc -l) )); then
  FGI_SIGNAL="BULLISH"
  FGI_STRENGTH=3
  echo "  → Extreme Greed = Pullback likely"
elif (( $(echo "$FGI < 45" | bc -l) )); then
  FGI_SIGNAL="BEARISH"
  FGI_STRENGTH=2
  echo "  → Fear = Mild bearish bias"
else
  FGI_SIGNAL="BULLISH"
  FGI_STRENGTH=2
  echo "  → Greed = Mild bullish bias"
fi

# SIGNAL 2: Volume Spike Detection
echo ""
echo "[2] Volume Spike Analysis (Liquidation Proxy):"

VOL_DATA=$(curl -s --max-time 3 "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=3" 2>/dev/null)

if [ ! -z "$VOL_DATA" ]; then
  python3 << 'PYTHON'
import json, sys

data = json.loads(VOL_DATA)
if len(data) >= 2:
    current = data[-1]
    previous = data[-2]
    
    curr_vol = float(current[7])
    prev_vol = float(previous[7])
    
    curr_close = float(current[4])
    prev_close = float(previous[4])
    
    vol_change = ((curr_vol - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0
    price_change = ((curr_close - prev_close) / prev_close * 100) if prev_close > 0 else 0
    
    print(f"  Volume change: {vol_change:+.1f}%")
    print(f"  Price change: {price_change:+.2f}%")
    
    if vol_change > 40 and abs(price_change) > 1:
        if price_change < 0:
            print("  → HIGH VOLUME SELLING: Long liquidations (bearish)")
            print("BEARISH|3")
        else:
            print("  → HIGH VOLUME BUYING: Short liquidations (bullish)")
            print("BULLISH|3")
    elif vol_change > 20:
        if price_change < 0:
            print("  → Moderate volume selling (mild bearish)")
            print("BEARISH|1")
        else:
            print("  → Moderate volume buying (mild bullish)")
            print("BULLISH|1")
    else:
        print("  → Balanced volume (neutral)")
        print("NEUTRAL|0")
PYTHON
else
  echo "  ⚠️  Volume data unavailable"
  echo "NEUTRAL|0"
fi

# Extract signal
VOL_RESULT=$(curl -s --max-time 3 "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=3" 2>/dev/null | \
  python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
if len(data) >= 2:
    curr_vol = float(data[-1][7])
    prev_vol = float(data[-2][7])
    vol_change = ((curr_vol - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0
    print('HIGH' if vol_change > 40 else 'MEDIUM' if vol_change > 20 else 'LOW')
else:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

case $VOL_RESULT in
  HIGH)
    VOL_SIGNAL="BULLISH"  # Assuming buying volume
    VOL_STRENGTH=3
    ;;
  MEDIUM)
    VOL_SIGNAL="NEUTRAL"
    VOL_STRENGTH=1
    ;;
  *)
    VOL_SIGNAL="NEUTRAL"
    VOL_STRENGTH=0
    ;;
esac

# SIGNAL 3: On-Chain (placeholder for future)
echo ""
echo "[3] Additional Context:"
echo "  • Polymarket current odds: UP $PM_UP% / DOWN $PM_DOWN%"
echo "  • (This is market demand, not 'ground truth')"

# ============================================================================
# MY CONSENSUS
# ============================================================================

echo ""
echo "🎯 MY INDEPENDENT ANALYSIS:"

# Count votes
MY_UP_VOTES=0
MY_DOWN_VOTES=0

[ "$FGI_SIGNAL" == "BULLISH" ] && ((MY_UP_VOTES++)) || ([ "$FGI_SIGNAL" == "BEARISH" ] && ((MY_DOWN_VOTES++)))
[ "$VOL_SIGNAL" == "BULLISH" ] && ((MY_UP_VOTES++)) || ([ "$VOL_SIGNAL" == "BEARISH" ] && ((MY_DOWN_VOTES++)))

if [ $MY_UP_VOTES -ge 1 ] && [ $MY_DOWN_VOTES -eq 0 ]; then
  MY_PREDICTION="UP"
  MY_CONFIDENCE=65
  MY_REASON="Fear index + volume suggest bullish setup"
elif [ $MY_DOWN_VOTES -ge 1 ] && [ $MY_UP_VOTES -eq 0 ]; then
  MY_PREDICTION="DOWN"
  MY_CONFIDENCE=65
  MY_REASON="Fear index + volume suggest bearish cascade"
else
  # Split decision
  if (( $(echo "$FGI < 45" | bc -l) )); then
    MY_PREDICTION="DOWN"
    MY_CONFIDENCE=60
    MY_REASON="Extreme fear typically precedes selloff"
  else
    MY_PREDICTION="UP"
    MY_CONFIDENCE=55
    MY_REASON="Market in mild greed, but need confirmation"
  fi
fi

echo "  My prediction: $MY_PREDICTION ($MY_CONFIDENCE% confidence)"
echo "  Reasoning: $MY_REASON"

# ============================================================================
# COMPARE WITH POLYMARKET
# ============================================================================

echo ""
echo "📊 COMPARE WITH POLYMARKET:"

if [ "$MY_PREDICTION" == "UP" ] && (( $(echo "$PM_UP > 55" | bc -l) )); then
  echo "  ✅ Aligned: Both predict UP"
  DIVERGENCE=0
elif [ "$MY_PREDICTION" == "DOWN" ] && (( $(echo "$PM_DOWN > 55" | bc -l) )); then
  echo "  ✅ Aligned: Both predict DOWN"
  DIVERGENCE=0
else
  DIVERGENCE_PCT=$(python3 -c "
if '$MY_PREDICTION' == 'UP':
    div = abs($MY_CONFIDENCE - $PM_UP)
else:
    div = abs($MY_CONFIDENCE - $PM_DOWN)
print(div)
" 2>/dev/null || echo "15")
  
  echo "  🔄 DIVERGENCE: My $MY_PREDICTION ($MY_CONFIDENCE%) vs Market $PM_UP% UP / $PM_DOWN% DOWN"
  echo "  Divergence: $DIVERGENCE_PCT%"
  DIVERGENCE=$DIVERGENCE_PCT
  
  if [ "$MY_PREDICTION" == "UP" ] && (( $(echo "$PM_DOWN > 60" | bc -l) )); then
    echo "  💡 Market is bearish while I'm bullish → CONTRARIAN opportunity if I'm right"
  elif [ "$MY_PREDICTION" == "DOWN" ] && (( $(echo "$PM_UP > 60" | bc -l) )); then
    echo "  💡 Market is bullish while I'm bearish → CONTRARIAN opportunity if I'm right"
  fi
fi

# Save full analysis
cat > /Users/moltbot/clawd/bitcoin/predictions/active-independent.json << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "btc_price": $BTC,
  "my_prediction": {
    "direction": "$MY_PREDICTION",
    "confidence": $MY_CONFIDENCE,
    "reasoning": "$MY_REASON",
    "signals_voted": {
      "up": $MY_UP_VOTES,
      "down": $MY_DOWN_VOTES
    }
  },
  "signals": {
    "fear_greed": {
      "value": $FGI,
      "signal": "$FGI_SIGNAL",
      "strength": $FGI_STRENGTH
    },
    "volume_spike": {
      "signal": "$VOL_SIGNAL",
      "strength": $VOL_STRENGTH
    }
  },
  "polymarket_reference": {
    "up_percent": $PM_UP,
    "down_percent": $PM_DOWN,
    "note": "Market data, not ground truth"
  },
  "divergence_analysis": {
    "divergence_percent": $DIVERGENCE,
    "my_prediction_vs_market": "$MY_PREDICTION vs Market $([ $PM_UP -gt 50 ] && echo 'UP' || echo 'DOWN')",
    "opportunity": "$([ $DIVERGENCE -gt 15 ] && echo 'Contrarian play if I\\'m right' || echo 'Market largely agrees')"
  }
}
EOF

echo ""
echo "✅ Analysis saved to predictions/active-independent.json"
echo ""
echo "🎯 FINAL:"
echo "  My prediction: $MY_PREDICTION ($MY_CONFIDENCE%)"
echo "  Polymarket: UP $PM_UP% / DOWN $PM_DOWN%"
echo "  Divergence: $DIVERGENCE%"
