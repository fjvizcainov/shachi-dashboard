# 🎯 Claude Prediction Gate - Bitcoin Polymarket

**Purpose:** Take Llama's analysis, make ONE Claude call for final prediction.

**Token Budget:** ~1,300 tokens per prediction (vs 6,500 before)

---

## 📥 Input (from Llama analysis)

```json
{
  "btc_price": 78807,
  "btc_24h_change": 1.08,
  "fear_greed_index": 17,
  "polymarket_up": 51.5,
  "polymarket_down": 48.5,
  "momentum": "bullish",
  "whale_signal": "neutral",
  "sentiment_score": 58,
  "technical_bias": "UP"
}
```

---

## 🤖 Claude Prompt (Minimal)

```
You are a Bitcoin prediction analyst. Given this market summary, predict UP or DOWN for the next 15 minutes.

BTC Price: $78,807 (+1.08% in 24h)
Fear & Greed: 17 (Extreme Fear)
Polymarket Odds: UP 51.5% / DOWN 48.5%
Momentum: Bullish
Sentiment Score: 58/100 (Bullish lean)

Respond ONLY with JSON:
{
  "direction": "UP" or "DOWN",
  "confidence": 55-75,
  "reasoning": "2-3 sentences max",
  "arbitrage": true/false (is Polymarket mispriced?)
}
```

---

## 💾 Output

```json
{
  "timestamp": "2026-02-03T02:08:50Z",
  "prediction": {
    "direction": "UP",
    "confidence": 58,
    "reasoning": "Extreme Fear (17) + positive momentum = contrarian buy signal. Polymarket UP odds (51.5%) slightly undervalue the bullish technicals.",
    "arbitrage": false
  },
  "tokens_used": {
    "input": 450,
    "output": 200,
    "total": 650
  }
}
```

---

## 🔄 Full Workflow

```bash
# 1. Run Llama analysis (LOCAL, FREE)
bash /Users/moltbot/clawd/bitcoin/analyze-polymarket-llama.sh
# Output: polymarket-analysis.json

# 2. Extract summary for Claude (tiny prompt)
SUMMARY=$(jq '.analysis' polymarket-analysis.json)

# 3. Call Claude ONLY with summary (650 tokens)
# Input: $SUMMARY
# Claude task: Generate final direction + confidence

# 4. Save prediction to tracker
# polymarket-72h-tracker.json (update with Claude response)
```

---

## 🎯 When to Use

**Use Llama ONLY:**
- Hourly for data collection/processing
- No external API calls
- Pure computation (80% of work)

**Use Claude ONLY for:**
- Final prediction generation
- Confidence scoring
- Arbitrage assessment
- Novel market conditions

---

## 💰 Cost Example (72 hours)

### Scenario: 7 predictions/hour × 24h × 3 days

**OLD (All Claude):**
```
7 × 24 × 3 × 6,500 tokens = 3,276,000 tokens
≈ $98 USD
```

**NEW (Llama + Claude):**
```
7 × 24 × 3 × 650 tokens = 327,600 tokens
≈ $10 USD

💰 SAVINGS: $88 per 72-hour session (90% reduction)
```

---

## ✅ Implementation Checklist

- [x] Llama analysis script (`analyze-polymarket-llama.sh`)
- [ ] Claude prediction wrapper (`predict-polymarket-claude.sh`)
- [ ] Unified router (`run-prediction-hybrid.sh`)
- [ ] Token tracker (`token-burn-weekly.json`)
- [ ] Validation test (compare old vs new outputs)

---

**Status:** Ready to implement Phase 1 (validation)
