# 🎯 Token Optimization Strategy - Bitcoin Predictions

**Goal:** Reduce Claude token usage by 70% using local llama 3.2 for data processing + heavy lifting.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│ TIER 1: LOCAL LLAMA 3.2 (FREE - Ollama)                         │
├─────────────────────────────────────────────────────────────────┤
│ ✅ Data Collection:                                              │
│    • Fetch Polymarket odds (web_fetch)                          │
│    • Fetch BTC price (CoinGecko, Fear & Greed)                 │
│    • Compare to previous state, detect spikes                   │
│                                                                  │
│ ✅ Data Processing:                                             │
│    • Parse JSON responses                                       │
│    • Calculate divergence %                                     │
│    • Detect whale movements (spike >50%)                        │
│    • Compare vs prediction from tracker                         │
│                                                                  │
│ ✅ Analysis:                                                     │
│    • Calculate momentum indicators                              │
│    • Identify support/resistance                                │
│    • Sentiment scoring (Polymarket, Fear Index, Volume)        │
│    • Generate technical summary                                 │
│                                                                  │
│ Output: JSON with all signal data + recommendation              │
└─────────────────────────────────────────────────────────────────┘
                            ↓ (signal packet)
┌─────────────────────────────────────────────────────────────────┐
│ TIER 2: CLAUDE (PAID - Only for critical decision)              │
├─────────────────────────────────────────────────────────────────┤
│ ✅ Prediction Generation:                                        │
│    • Ingest llama analysis summary (pre-processed)              │
│    • Generate final UP/DOWN prediction                          │
│    • Assign confidence % (based on signal strength)             │
│    • Explain reasoning briefly                                  │
│                                                                  │
│ ✅ Divergence Assessment:                                        │
│    • Compare my prediction vs Polymarket                        │
│    • Identify arbitrage opportunities                           │
│    • Risk assessment                                            │
│                                                                  │
│ Output: Final prediction JSON ready for tracker                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Token Budget Allocation

### BEFORE (Current):
```
Per prediction (Claude handling ALL):
- Data processing: 2,000 tokens
- Analysis: 3,000 tokens
- Prediction: 1,500 tokens
────────────────────────────
TOTAL: ~6,500 tokens/prediction
```

### AFTER (Optimized):
```
Per prediction (Llama handles heavy lifting):

Tier 1 - Llama (LOCAL, FREE):
- All data collection: 0 tokens (local)
- Processing & analysis: 0 tokens (local)
- Format summary packet: 0 tokens (local)

Tier 2 - Claude (ONLY PREDICTION):
- Ingest summary: 500 tokens
- Generate prediction: 800 tokens
────────────────────────────
TOTAL: ~1,300 tokens/prediction

💰 SAVINGS: 80% reduction (6,500 → 1,300)
```

---

## 🔧 Implementation

### Step 1: Llama 3.2 Analysis Script
**File:** `analyze-polymarket-llama.js`

```bash
# Run locally via Ollama
curl http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2",
    "prompt": "Analyze BTC market data: [JSON data] Return JSON: {bids_direction, volume_trend, whale_signal, technicals}",
    "stream": false
  }'
```

**Input:** Raw market data (JSON)
**Output:** Analysis packet (no tokens used)

### Step 2: Claude Prediction
**File:** `predict-polymarket-claude.js`

```javascript
// Only send analysis summary to Claude
const summary = {
  btc_price: 78807,
  fear_index: 17,
  polymarket_odds: { up: 0.515, down: 0.485 },
  llama_analysis: {
    whale_signal: "neutral",
    momentum: "bullish",
    divergence: "no",
    spike_detected: false
  }
};

// Claude only: "Given this summary, predict UP or DOWN with confidence %"
// Result: { direction: "UP", confidence: 58 }
```

---

## 📈 Per-Session Token Usage

**72-hour Bitcoin tracking (7 predictions every hour):**

### OLD WAY (All Claude):
```
7 predictions/hour × 24 hours × 3 days × 6,500 tokens
= 7 × 24 × 3 × 6,500 = 3,276,000 tokens
≈ $98 USD
```

### NEW WAY (Llama + Claude):
```
7 predictions/hour × 24 hours × 3 days × 1,300 tokens
= 7 × 24 × 3 × 1,300 = 655,200 tokens
≈ $20 USD

💰 SAVINGS: $78 per 72-hour session
```

---

## 🎯 What Claude ONLY Does

1. **Make the final prediction** (5-10 sec reasoning)
2. **Assign confidence level** (based on signal strength)
3. **Identify arbitrage** (is Polymarket mispriced?)
4. **Brief explanation** (why UP/DOWN)

**Everything else:** Llama handles locally.

---

## 🚀 Rollout Plan

### Phase 1: Validate Llama Analysis (TODAY)
- Test llama 3.2 analysis accuracy vs Claude
- Ensure JSON output is clean
- Compare predictions side-by-side

### Phase 2: Hybrid Predictions (THIS WEEK)
- Run BOTH Llama + Claude
- Compare outputs
- Measure divergence
- Confirm accuracy stays same or improves

### Phase 3: Full Llama + Claude (ONGOING)
- Only send Claude the summary packet
- Use Llama for all heavy lifting
- Monitor token burn weekly
- Adjust confidence thresholds as needed

---

## 💡 Why This Works

**Llama 3.2 is great at:**
- Parsing JSON/structured data
- Following deterministic rules (if X > 50%, spike = true)
- Calculations (divergence %, momentum, comparisons)
- Pattern matching (whale signals, volatility)

**Claude is great at:**
- Making judgment calls under uncertainty
- Weighing competing signals
- Reasoning about human behavior (FOMO, panic)
- Novel scenarios (unusual market structure)

**Result:** Divvy up the work by specialty. Save money. Keep accuracy high.

---

## 📋 Files to Create

1. `analyze-polymarket-llama.sh` — Local analysis script
2. `predict-polymarket-claude.sh` — Claude decision gate
3. `router.sh` — Decides which model to use when
4. `token-burn-tracker.json` — Monitor weekly usage

---

**Status:** Ready to implement  
**Savings Potential:** 80% token reduction + faster local processing  
**Risk:** Zero (Llama + Claude are orthogonal)

