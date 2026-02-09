#!/bin/bash

# 🔍 VERIFY PREDICTION OUTCOMES
# Runs 15 minutes after prediction to measure if correct
# Updates tracker with actual outcome and accuracy

TRACKER="/Users/moltbot/clawd/bitcoin/tracking/phase1-predictions.json"
LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/phase1-verification.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🔍 VERIFICATION LOOP STARTING"

if [ ! -f "$TRACKER" ]; then
  log "❌ No tracker file found"
  exit 1
fi

# Find unverified predictions (those with null outcome)
UNVERIFIED=$(jq '.predictions[] | select(.actual_outcome == null)' "$TRACKER" | wc -l)

log "Found $UNVERIFIED unverified predictions"

if [ "$UNVERIFIED" -eq 0 ]; then
  log "✅ All predictions verified. Exiting."
  exit 0
fi

# Process each unverified prediction
jq -r '.predictions[] | select(.actual_outcome == null) | .id' "$TRACKER" | while read ID; do
  log ""
  log "Processing prediction ID: $ID"
  
  # Get prediction data
  PRED=$(jq ".predictions[] | select(.id == $ID)" "$TRACKER")
  PRED_DIR=$(echo "$PRED" | jq -r '.prediction')
  PRED_CONF=$(echo "$PRED" | jq -r '.confidence')
  MARKET_ID=$(echo "$PRED" | jq -r '.market_id')
  TIMESTAMP=$(echo "$PRED" | jq -r '.timestamp_prediction')
  
  log "  Predicted: $PRED_DIR ($PRED_CONF%)"
  
  # Fetch current market to see if closed
  CURRENT=$(curl -s "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1" 2>/dev/null)
  
  if [ -z "$CURRENT" ]; then
    log "  ⚠️ Could not fetch market data. Skipping for now."
    continue
  fi
  
  # Get current BTC price
  CURRENT_PRICE=$(echo "$CURRENT" | python3 -c "import json, sys; d=json.load(sys.stdin); print(float(d[0][4]))" 2>/dev/null)
  PREV_PRICE=$(echo "$PRED" | jq -r '.btc_price')
  
  # Determine outcome
  if (( $(echo "$CURRENT_PRICE > $PREV_PRICE" | bc -l) )); then
    ACTUAL="UP"
    PRICE_CHANGE="+$(echo "$CURRENT_PRICE - $PREV_PRICE" | bc -l | cut -d. -f1)"
  elif (( $(echo "$CURRENT_PRICE < $PREV_PRICE" | bc -l) )); then
    ACTUAL="DOWN"
    PRICE_CHANGE="-$(echo "$PREV_PRICE - $CURRENT_PRICE" | bc -l | cut -d. -f1)"
  else
    ACTUAL="NEUTRAL"
    PRICE_CHANGE="0"
  fi
  
  log "  Actual outcome: $ACTUAL (BTC: $PRICE_CHANGE)"
  
  # Determine if correct
  if [ "$PRED_DIR" == "$ACTUAL" ]; then
    CORRECT="true"
    SYMBOL="✅"
  else
    CORRECT="false"
    SYMBOL="❌"
  fi
  
  log "  Result: $SYMBOL CORRECT=$CORRECT"
  
  # Update tracker with outcome
  jq ".predictions[$ID].timestamp_outcome = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" | 
      .predictions[$ID].actual_outcome = \"$ACTUAL\" | 
      .predictions[$ID].correct = $CORRECT" "$TRACKER" > "$TRACKER.tmp" && mv "$TRACKER.tmp" "$TRACKER"
  
done

# Recalculate accuracy
log ""
log "📊 CALCULATING ACCURACY..."

ACCURACY=$(python3 << 'PYTHON'
import json

with open("/Users/moltbot/clawd/bitcoin/tracking/phase1-predictions.json") as f:
    data = json.load(f)

predictions = data["predictions"]
verified = [p for p in predictions if p["actual_outcome"] is not None]

if not verified:
    print("0|0|0|0")
else:
    total = len(verified)
    correct = len([p for p in verified if p["correct"]])
    incorrect = total - correct
    accuracy = (correct / total * 100) if total > 0 else 0
    avg_conf = sum([p["confidence"] for p in verified]) / total
    
    print(f"{total}|{correct}|{incorrect}|{accuracy:.1f}|{avg_conf:.1f}")

PYTHON
)

TOTAL=$(echo "$ACCURACY" | cut -d'|' -f1)
CORRECT=$(echo "$ACCURACY" | cut -d'|' -f2)
INCORRECT=$(echo "$ACCURACY" | cut -d'|' -f3)
ACC_PERCENT=$(echo "$ACCURACY" | cut -d'|' -f4)
AVG_CONF=$(echo "$ACCURACY" | cut -d'|' -f5)

log "  Total verified: $TOTAL"
log "  Correct: $CORRECT"
log "  Incorrect: $INCORRECT"
log "  Accuracy: $ACC_PERCENT%"
log "  Avg Confidence: $AVG_CONF%"

# Update accuracy data in tracker
jq ".accuracy_data.total = $TOTAL | 
    .accuracy_data.correct = $CORRECT | 
    .accuracy_data.incorrect = $INCORRECT | 
    .accuracy_data.accuracy_percent = $ACC_PERCENT | 
    .accuracy_data.avg_confidence = $AVG_CONF" "$TRACKER" > "$TRACKER.tmp" && mv "$TRACKER.tmp" "$TRACKER"

log ""
log "✅ VERIFICATION COMPLETE"
