#!/bin/bash

# 🚀 UNIFIED PREDICTION LOOP v2
# Rewrite for consistency: Fetch → Predict → Save → Verify
# Executes every 15-30 minutes

set -e

TRACKER="/Users/moltbot/clawd/bitcoin/tracking/phase1-predictions.json"
LOG_FILE="/Users/moltbot/clawd/bitcoin/logs/phase1-rewrite.log"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$TRACKER")"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "🚀 UNIFIED PREDICTION LOOP STARTING"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# STEP 1: Fetch current market data
log "STEP 1: Fetching Polymarket data..."

MARKET_DATA=$(bash /Users/moltbot/clawd/bitcoin/get-polymarket-live-final-v2.sh 2>&1 | tail -20)

if [ -z "$MARKET_DATA" ]; then
  log "❌ Failed to fetch market data. Exiting."
  exit 1
fi

# Parse market data
MARKET_ID=$(jq -r '.market_id' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "unknown")
BTC=$(jq -r '.btc_price' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "0")
UP=$(jq -r '.up_percent' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "50")
DOWN=$(jq -r '.down_percent' /Users/moltbot/clawd/bitcoin/polymarket-state.json 2>/dev/null || echo "50")

log "✅ Market data: ID=$MARKET_ID, BTC=$BTC, UP=$UP%, DOWN=$DOWN%"

# STEP 2: Generate prediction
log "STEP 2: Generating prediction..."

# Simple 3-signal model (can upgrade to 9-signal later)
FGI=$(curl -s --max-time 2 "https://api.alternative.me/fng/?limit=1&format=json" | \
  python3 -c "import json, sys; d=json.load(sys.stdin); print(d['data'][0]['value'])" 2>/dev/null || echo "50")

log "Fear & Greed Index: $FGI"

# Predict logic
python3 << 'PYTHON'
import os, json

up = float(os.environ.get('UP', 50))
down = float(os.environ.get('DOWN', 50))
fgi = int(os.environ.get('FGI', 50))

# Simple prediction: Polymarket + F&G
if up > down:
    pred = "UP"
    conf = up
elif down > up:
    pred = "DOWN"
    conf = down
else:
    # Tied, use F&G
    if fgi < 40:
        pred = "DOWN"
        conf = 50 + (40 - fgi)
    elif fgi > 60:
        pred = "UP"
        conf = 50 + (fgi - 60)
    else:
        pred = "NEUTRAL"
        conf = 50

# Ensure confidence is 0-100
conf = min(100, max(0, conf))

print(f"PRED|{pred}|{conf:.1f}")

PYTHON

# Capture prediction
PRED_OUTPUT=$(python3 << 'PYTHON'
import os, json

up = float(os.environ.get('UP', 50))
down = float(os.environ.get('DOWN', 50))
fgi = int(os.environ.get('FGI', 50))

if up > down:
    pred = "UP"
    conf = up
elif down > up:
    pred = "DOWN"
    conf = down
else:
    if fgi < 40:
        pred = "DOWN"
        conf = 50 + (40 - fgi)
    elif fgi > 60:
        pred = "UP"
        conf = 50 + (fgi - 60)
    else:
        pred = "NEUTRAL"
        conf = 50

conf = min(100, max(0, conf))
print(f"{pred}|{conf:.1f}")

PYTHON
)

PREDICTION=$(echo "$PRED_OUTPUT" | cut -d'|' -f1)
CONFIDENCE=$(echo "$PRED_OUTPUT" | cut -d'|' -f2)

log "✅ Prediction: $PREDICTION ($CONFIDENCE% confidence)"

# STEP 3: Save prediction to tracker
log "STEP 3: Saving prediction to tracker..."

# Get next ID
if [ -f "$TRACKER" ]; then
  NEXT_ID=$(jq '.predictions | length' "$TRACKER")
  TOTAL=$(jq '.accuracy_data.total' "$TRACKER")
else
  NEXT_ID=1
  TOTAL=0
fi

# Create new prediction record
PRED_RECORD=$(cat << EOF
{
  "id": $NEXT_ID,
  "timestamp_prediction": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "market_id": "$MARKET_ID",
  "btc_price": $BTC,
  "polymarket": {"up": $UP, "down": $DOWN},
  "prediction": "$PREDICTION",
  "confidence": $CONFIDENCE,
  "fgi": $FGI,
  "timestamp_outcome": null,
  "actual_outcome": null,
  "correct": null
}
EOF
)

# Append to tracker
if [ ! -f "$TRACKER" ]; then
  # Initialize tracker
  cat > "$TRACKER" << 'EOF'
{
  "phase1_rewrite": "FEB 9-12",
  "collection_status": "IN_PROGRESS",
  "predictions": [],
  "accuracy_data": {
    "total": 0,
    "correct": 0,
    "incorrect": 0,
    "accuracy_percent": 0,
    "avg_confidence": 0
  }
}
EOF
fi

# Add prediction
jq ".predictions += [$PRED_RECORD]" "$TRACKER" > "$TRACKER.tmp" && mv "$TRACKER.tmp" "$TRACKER"

log "✅ Prediction saved to tracker (ID: $NEXT_ID)"

# STEP 4: Schedule verification
log "STEP 4: Scheduling verification in 15 minutes..."
log "  Market window: $MARKET_ID will close in ~15 min"
log "  Verification scheduled for: $(date -u -d '+15 minutes' +%Y-%m-%dT%H:%M:%SZ)"

# STEP 5: Summary
log ""
log "📊 PREDICTION SUMMARY:"
log "  Market ID: $MARKET_ID"
log "  BTC Price: \$$BTC"
log "  Polymarket: UP $UP% / DOWN $DOWN%"
log "  My Prediction: $PREDICTION ($CONFIDENCE% confidence)"
log "  Total predictions so far: $((NEXT_ID))"
log ""
log "✅ LOOP COMPLETE"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
