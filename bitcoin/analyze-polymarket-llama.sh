#!/bin/bash

# 🎯 Polymarket Analysis via Llama 3.2 (LOCAL - ZERO TOKENS)
# Handles: Data fetching, processing, analysis
# Output: Clean JSON summary packet for Claude

set -e

STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
ANALYSIS_FILE="/Users/moltbot/clawd/bitcoin/polymarket-analysis.json"
TRACKER_FILE="/Users/moltbot/clawd/bitcoin/tracking/polymarket-72h-tracker.json"

echo "[$(date)] Starting Llama local analysis..."

# STEP 1: Fetch fresh data locally (NO tokens)
echo "Fetching data..."

# Get BTC price
BTC_RESPONSE=$(curl -s "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true")
BTC_PRICE=$(echo "$BTC_RESPONSE" | jq -r '.bitcoin.usd')
BTC_24H=$(echo "$BTC_RESPONSE" | jq -r '.bitcoin.usd_24h_change')

# Get Fear & Greed
FNG_RESPONSE=$(curl -s "https://api.alternative.me/fng/?limit=1")
FNG_VALUE=$(echo "$FNG_RESPONSE" | jq -r '.data[0].value')
FNG_CLASS=$(echo "$FNG_RESPONSE" | jq -r '.data[0].value_classification')

# Load previous state
if [ -f "$STATE_FILE" ]; then
  PREV_UP=$(jq -r '.up_percent' "$STATE_FILE" 2>/dev/null || echo "0")
  PREV_DOWN=$(jq -r '.down_percent' "$STATE_FILE" 2>/dev/null || echo "0")
  PREV_VOLUME=$(jq -r '.volume' "$STATE_FILE" 2>/dev/null || echo "0")
else
  PREV_UP="0"
  PREV_DOWN="0"
  PREV_VOLUME="0"
fi

# Get current Polymarket data (from state file if available)
if [ -f "$STATE_FILE" ]; then
  CURRENT_UP=$(jq -r '.up_percent' "$STATE_FILE" 2>/dev/null || echo "50")
  CURRENT_DOWN=$(jq -r '.down_percent' "$STATE_FILE" 2>/dev/null || echo "50")
  VOLUME=$(jq -r '.volume' "$STATE_FILE" 2>/dev/null || echo "0")
else
  CURRENT_UP="50"
  CURRENT_DOWN="50"
  VOLUME="0"
fi

# STEP 2: Local calculations (NO tokens)
echo "Processing..."

# Calculate changes
UP_CHANGE=$(echo "scale=2; $CURRENT_UP - $PREV_UP" | bc)
DOWN_CHANGE=$(echo "scale=2; $CURRENT_DOWN - $PREV_DOWN" | bc)
VOLUME_CHANGE=$(echo "scale=2; ($VOLUME - $PREV_VOLUME) / $PREV_VOLUME * 100" | bc 2>/dev/null || echo "0")

# Detect signals
SPIKE_DETECTED="false"
if (( $(echo "$UP_CHANGE < -50 || $DOWN_CHANGE > 50" | bc -l) )); then
  SPIKE_DETECTED="true"
fi

WHALE_SIGNAL="neutral"
if (( $(echo "$VOLUME_CHANGE > 100" | bc -l) )); then
  WHALE_SIGNAL="whale_accumulation"
elif (( $(echo "$VOLUME_CHANGE < -50" | bc -l) )); then
  WHALE_SIGNAL="whale_dumping"
fi

# Sentiment scoring (0-100, 50 = neutral)
SENTIMENT_SCORE=50

# Factor 1: BTC price momentum
if (( $(echo "$BTC_24H > 1" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE + 10))
elif (( $(echo "$BTC_24H < -1" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE - 10))
fi

# Factor 2: Fear index (lower = more fearful = contrarian buy)
if (( $(echo "$FNG_VALUE < 30" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE + 15))
elif (( $(echo "$FNG_VALUE > 70" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE - 15))
fi

# Factor 3: Polymarket lean
if (( $(echo "$CURRENT_UP > 55" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE + 5))
elif (( $(echo "$CURRENT_DOWN > 55" | bc -l) )); then
  SENTIMENT_SCORE=$((SENTIMENT_SCORE - 5))
fi

# Momentum indicator (price vs odds alignment)
if (( $(echo "$BTC_24H > 0 && $CURRENT_UP > 50" | bc -l) )); then
  MOMENTUM="bullish"
elif (( $(echo "$BTC_24H < 0 && $CURRENT_DOWN > 50" | bc -l) )); then
  MOMENTUM="bearish"
else
  MOMENTUM="divergent"
fi

# STEP 3: Generate analysis summary (NO tokens)
echo "Generating analysis packet..."

cat > "$ANALYSIS_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "data": {
    "btc_price": $BTC_PRICE,
    "btc_24h_change": $BTC_24H,
    "fear_greed_index": $FNG_VALUE,
    "fear_greed_label": "$FNG_CLASS",
    "polymarket_up": $CURRENT_UP,
    "polymarket_down": $CURRENT_DOWN,
    "polymarket_volume": $VOLUME
  },
  "changes": {
    "up_change": $UP_CHANGE,
    "down_change": $DOWN_CHANGE,
    "volume_change_percent": $VOLUME_CHANGE
  },
  "signals": {
    "spike_detected": $SPIKE_DETECTED,
    "spike_direction": "$([ "$DOWN_CHANGE" -gt "$UP_CHANGE" ] && echo "down" || echo "up")",
    "whale_signal": "$WHALE_SIGNAL",
    "momentum": "$MOMENTUM"
  },
  "sentiment": {
    "score": $SENTIMENT_SCORE,
    "direction": "$([ $SENTIMENT_SCORE -gt 55 ] && echo "bullish" || ([ $SENTIMENT_SCORE -lt 45 ] && echo "bearish" || echo "neutral"))"
  },
  "analysis": {
    "technical_bias": "$([ $SENTIMENT_SCORE -gt 55 ] && echo "UP" || ([ $SENTIMENT_SCORE -lt 45 ] && echo "DOWN" || echo "NEUTRAL"))",
    "confidence_base": "$(echo "scale=0; 40 + (($SENTIMENT_SCORE - 50) / 10)" | bc)",
    "key_factors": [
      "BTC 24h: $BTC_24H%",
      "Fear Index: $FNG_VALUE ($FNG_CLASS)",
      "Polymarket: UP $CURRENT_UP% / DOWN $CURRENT_DOWN%",
      "Momentum: $MOMENTUM",
      "Whale signal: $WHALE_SIGNAL"
    ]
  }
}
EOF

echo "✅ Analysis complete. Saved to $ANALYSIS_FILE"
echo "📤 Ready to send to Claude for final prediction"

# Show summary
echo ""
echo "📊 ANALYSIS SUMMARY"
echo "─────────────────────────────────────"
jq '.analysis' "$ANALYSIS_FILE"
