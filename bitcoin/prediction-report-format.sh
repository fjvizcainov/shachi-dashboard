#!/bin/bash

# 📊 PREDICTION REPORT FORMAT v2
# Shows: My prediction + Polymarket reference + Divergence

STATE_FILE="/Users/moltbot/clawd/bitcoin/polymarket-state.json"
ACTIVE_PRED="/Users/moltbot/clawd/bitcoin/predictions/active.json"

if [ ! -f "$STATE_FILE" ]; then
  echo "No market data available"
  exit 1
fi

# Extract data
BTC=$(jq -r '.btc_price' "$STATE_FILE")
PM_UP=$(jq -r '.up_percent' "$STATE_FILE")
PM_DOWN=$(jq -r '.down_percent' "$STATE_FILE")
MARKET_ID=$(jq -r '.market_id' "$STATE_FILE")

# Get my prediction (from active.json if available, otherwise calculate)
if [ -f "$ACTIVE_PRED" ]; then
  MY_PRED=$(jq -r '.prediction // "NEUTRAL"' "$ACTIVE_PRED")
  MY_CONF=$(jq -r '.confidence // 50' "$ACTIVE_PRED")
  MY_REASON=$(jq -r '.reasoning // "Awaiting signals"' "$ACTIVE_PRED")
else
  # Fallback: quick calculation
  MY_PRED="PENDING"
  MY_CONF=50
  MY_REASON="Prediction not yet calculated"
fi

# Calculate divergence
python3 << PYTHON
import json

# My prediction
my_pred = "$MY_PRED"
my_conf = $MY_CONF
pm_up = $PM_UP
pm_down = $PM_DOWN

# Determine polymarket direction
pm_pred = "UP" if pm_up > pm_down else "DOWN" if pm_down > pm_up else "NEUTRAL"
pm_conf = max(pm_up, pm_down)

# Calculate divergence
if my_pred == pm_pred:
    divergence = abs(my_conf - pm_conf)
    alignment = "✅ ALIGNED"
else:
    divergence = abs(my_conf - pm_conf)
    alignment = "🔄 DIVERGENT"

# Format output
print(f"
═══════════════════════════════════════════════════════════
📊 BITCOIN 15-MINUTE PREDICTION REPORT
═══════════════════════════════════════════════════════════

⏱️  TIME: $(date '+%Y-%m-%d %H:%M:%S %Z')
📍 MARKET ID: $MARKET_ID (Bitcoin Up or Down)

💰 BTC PRICE: \${BTC:->8}

───────────────────────────────────────────────────────────
🎯 MY PREDICTION (Independent Analysis)
───────────────────────────────────────────────────────────

Direction: {my_pred}
Confidence: {my_conf}%
Reasoning: $MY_REASON

───────────────────────────────────────────────────────────
📊 POLYMARKET REFERENCE (Market Consensus)
───────────────────────────────────────────────────────────

Market sees: UP {pm_up}% / DOWN {pm_down}%
Consensus: {pm_pred}
Odds confidence: {pm_conf}%

───────────────────────────────────────────────────────────
🔍 DIVERGENCE ANALYSIS
───────────────────────────────────────────────────────────

Alignment: {alignment}
Divergence: {divergence}%

{'IF I\\'m RIGHT on this divergence:' if divergence > 15 else ''}
→ Contrarian win against market consensus

───────────────────────────────────────────────────────────

✅ Report generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
")
PYTHON
