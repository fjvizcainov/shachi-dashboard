# 📋 PHASE 1 VALIDATION - Detailed Plan

**Goal:** Verify Llama 3.2 analysis produces same quality predictions as Claude (old way)  
**Timeline:** This week (Feb 3-7, 2026)  
**Success Criteria:** Accuracy match or better, token savings confirmed

---

## 🎯 Test Plan

### Day 1-2: Setup & Historical Test
**Tuesday-Wednesday**

```bash
# 1. Collect historical market data
# Use: Previous predictions from tracker + actual outcomes

# 2. Run Llama analysis on 10 historical snapshots
bash /Users/moltbot/clawd/bitcoin/analyze-polymarket-llama.sh

# 3. Manually generate Claude predictions from Llama summaries
# (simulate what Claude would do with just the summary)

# 4. Compare outputs:
#    • Direction match? (UP vs DOWN)
#    • Confidence within 10%?
#    • Reasoning quality similar?
```

### Day 3-4: Live A/B Testing
**Thursday-Friday**

```bash
# 1. Run BOTH systems simultaneously on live markets
# • Llama analysis: every 30 min (local)
# • Claude prediction: on Llama summary (minimal tokens)
# • Old Claude path: full analysis (for comparison)

# 2. Log everything:
#    • Timestamps
#    • Directions
#    • Confidence scores
#    • Tokens used
#    • Market outcomes (when available)

# 3. Measure:
#    • Prediction agreement %
#    • Confidence correlation
#    • Token usage reduction
```

### Day 5: Analysis & Report
**Saturday**

```bash
# 1. Compile results
# 2. Generate accuracy metrics
# 3. Create final report
# 4. Decision: Proceed to Phase 2 or adjust
```

---

## 🔍 Validation Metrics

### Accuracy
```
✓ Direction Match: Do both predict same UP/DOWN?
  Target: >90% agreement

✓ Confidence Correlation: How close are % scores?
  Target: Within ±10%

✓ Reasoning Quality: Is Llama summary clear for Claude?
  Target: Claude can make decision from summary alone
```

### Efficiency
```
✓ Token Reduction: 
  Expected: 6,500 → 650 per prediction (90%)
  Target: Confirm in real usage

✓ Speed:
  Llama local: <5 sec per analysis
  Claude remote: <10 sec per prediction
  Total: <15 sec (same as before)
```

### Reliability
```
✓ No JSON errors: Llama output always valid?
  Target: 100%

✓ Claude acceptance: Can Claude parse summary?
  Target: 100%

✓ No edge case failures: Market extremes handled?
  Target: All cases work
```

---

## 📊 Test Data Set

Using 10 historical predictions from tracker:

| # | Date | BTC $ | Polymarket | Actual | Result |
|---|------|-------|-----------|--------|--------|
| 1 | 2/2 7:30PM | 78,407 | UP 52.5% | UP $78,889 | ✅ CORRECT |
| 2 | 2/2 7:45PM | 78,797 | UP 45.5% | ? | ⏳ PENDING |
| 3 | 2/2 8:05PM | 78,941 | UP 46.5% | ? | ⏳ PENDING |
| ... | ... | ... | ... | ... | ... |

---

## 🛠️ Scripts to Run

### Script 1: Validate Historical Data
**File:** `validate-historical.sh`

```bash
#!/bin/bash

TRACKER_FILE="/Users/moltbot/clawd/bitcoin/tracking/polymarket-72h-tracker.json"
TEST_OUTPUT="/Users/moltbot/clawd/bitcoin/validation-results.json"

echo "Extracting historical predictions..."

jq '.predictions[] | {
  id: .id,
  prediction: .prediction.direction,
  confidence: .prediction.confidence,
  outcome: .outcome,
  market_result: .market_result
}' "$TRACKER_FILE" > "$TEST_OUTPUT"

echo "✅ Data extracted. Ready for Llama analysis."
```

### Script 2: Run Llama on Test Data
**File:** `validate-llama-accuracy.sh`

```bash
#!/bin/bash

TEST_DATA="/Users/moltbot/clawd/bitcoin/validation-results.json"
LLAMA_RESULTS="/Users/moltbot/clawd/bitcoin/llama-validation-results.json"

echo "Running Llama analysis on historical data..."

# For each historical prediction
jq -r '.[] | @json' "$TEST_DATA" | while read -r line; do
  
  # Extract market data
  ID=$(echo "$line" | jq -r '.id')
  BTC_PRICE=$(echo "$line" | jq -r '.btc_price')
  POLYMARKET=$(echo "$line" | jq -r '.polymarket_odds')
  
  echo "Processing prediction #$ID..."
  
  # Run Llama analysis
  bash /Users/moltbot/clawd/bitcoin/analyze-polymarket-llama.sh
  
  # Capture result
  ANALYSIS=$(cat /Users/moltbot/clawd/bitcoin/polymarket-analysis.json)
  
  # Store comparison
  echo "{
    \"test_id\": $ID,
    \"original_direction\": \"$(echo "$line" | jq -r '.prediction')\",
    \"llama_direction\": \"$(echo "$ANALYSIS" | jq -r '.analysis.technical_bias')\",
    \"llama_confidence\": $(echo "$ANALYSIS" | jq -r '.sentiment.score'),
    \"match\": $([ "$(echo "$line" | jq -r '.prediction')" = "$(echo "$ANALYSIS" | jq -r '.analysis.technical_bias')" ] && echo "true" || echo "false")
  }" >> "$LLAMA_RESULTS"
  
done

echo "✅ Llama validation complete. Results in $LLAMA_RESULTS"
```

### Script 3: Generate Report
**File:** `validate-generate-report.sh`

```bash
#!/bin/bash

LLAMA_RESULTS="/Users/moltbot/clawd/bitcoin/llama-validation-results.json"
REPORT="/Users/moltbot/clawd/bitcoin/VALIDATION-REPORT-PHASE1.md"

TOTAL=$(jq 'length' "$LLAMA_RESULTS")
MATCHES=$(jq '[.[] | select(.match == true)] | length' "$LLAMA_RESULTS")
ACCURACY=$(echo "scale=1; ($MATCHES / $TOTAL) * 100" | bc)

cat > "$REPORT" << EOF
# Phase 1 Validation Report

**Date:** $(date)
**Tests Run:** $TOTAL
**Predictions Matched:** $MATCHES
**Accuracy:** $ACCURACY%

## Results by Prediction

EOF

jq -r '.[] | "- Test #\(.test_id): \(.original_direction) → \(.llama_direction) [\(.match)]"' "$LLAMA_RESULTS" >> "$REPORT"

echo ""
echo "✅ Report generated: $REPORT"
```

---

## 📈 Expected Results

### Best Case (Target)
```
✓ Accuracy: >90% match between old & new
✓ Tokens: 90% reduction confirmed
✓ Speed: <15 sec per full prediction
✓ Reliability: 100% JSON success rate

Result: APPROVE Phase 2 immediately
```

### Good Case (Acceptable)
```
✓ Accuracy: 80-90% match
✓ Tokens: 85%+ reduction
✓ Speed: <20 sec per prediction
✓ Reliability: 99% JSON success rate

Result: APPROVE Phase 2 with minor adjustments
```

### Problem Case (Investigate)
```
✗ Accuracy: <80% match
✗ Tokens: <80% reduction
✗ Reliability: JSON failures >1%

Result: Debug + iterate on Phase 1
```

---

## 🎯 Decision Gate

**After Friday's analysis, decision tree:**

```
Accuracy >85% AND Tokens >80% reduction?
│
├─ YES → Approve Phase 2 (Live A/B testing)
│
└─ NO → 
    ├─ Adjust Llama analysis thresholds
    ├─ Refine Claude summary format
    └─ Re-run validation
```

---

## 📝 Daily Checklist

### Tuesday (Feb 4)
- [ ] Extract historical data from tracker
- [ ] Set up Llama test environment
- [ ] Run first 5 test predictions

### Wednesday (Feb 5)
- [ ] Complete 10 historical tests
- [ ] Manual Claude predictions from Llama summaries
- [ ] Compare accuracy

### Thursday (Feb 6)
- [ ] Set up live A/B testing
- [ ] Deploy both systems simultaneously
- [ ] Start logging results

### Friday (Feb 7)
- [ ] Collect 24h of live data
- [ ] Run analysis scripts
- [ ] Generate final report

### Saturday (Feb 8)
- [ ] Review results with Fran
- [ ] Make Phase 2 decision
- [ ] Update roadmap if needed

---

## 💾 Files to Monitor

```
/Users/moltbot/clawd/bitcoin/
├── polymarket-analysis.json          (Llama output, each run)
├── llama-validation-results.json     (Comparison matrix)
├── VALIDATION-REPORT-PHASE1.md       (Final report)
├── validation-live-ab.json           (A/B test logs)
└── token-burn-validation-week.json   (Usage tracking)
```

---

## 🚀 Success = Phase 2 Approval

If validation passes:
- Proceed to live A/B testing
- Run both systems in parallel for real markets
- Measure real-world accuracy
- Then full rollout Phase 3

---

**Status:** Ready to start Tuesday Feb 4  
**Estimated Effort:** 5 hours  
**Risk:** Zero (validation only, no production changes)
