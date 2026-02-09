# 📊 TECHNICAL ANALYSIS FOUNDATION FOR BTC PREDICTION

**Research Phase:** Feb 3-4, 2026  
**Goal:** Integrate TA into prediction model (Phase 1 enrichment)  
**Source:** Classic TA methodology + proven indicators

---

## 👨‍🎓 EXPERT SOURCES TO LEARN FROM

### **Foundational Experts**
1. **Richard Wyckoff** (Founder of modern TA)
   - Method: Supply/Demand zones, Smart Money movements
   - Key: Identify where whales accumulate (accumulation phase before rallies)
   - Application: Detect whale positioning in Polymarket

2. **Ralph Elliott** (Elliott Wave Theory)
   - Pattern: 5 waves up, 3 waves down = predictable cycles
   - Key: Identify which wave we're in
   - Application: Determine if we're in wave 3 (strong up) or wave 4-5 (reversal)

3. **Price Action Masters**
   - Concepts: Support/resistance, breakouts, reversals
   - Key: Read candles + volume, not just indicators
   - Application: Identify S/R zones for entries/exits

4. **Modern TA Practitioners**
   - Josh Olszewicz (on-chain + TA combined)
   - Raoul Pal (macro + cycles)
   - CryptoBirb (Elliott waves on crypto)

---

## 📈 KEY TECHNICAL INDICATORS

### **1. Moving Averages (Trend)**

```
Simple MA (SMA):
- 20-day SMA: Short-term trend
- 50-day SMA: Medium trend
- 200-day SMA: Long-term trend (The most important)

Signal:
- Price > 200-SMA → Bullish regime
- Price < 200-SMA → Bearish regime
- Golden Cross (50 crosses above 200) → Strong buy
- Death Cross (50 crosses below 200) → Strong sell

For BTC 15m:
- Use 14-candle MA (≈ 7 minutes)
- Use 50-candle MA (≈ 25 minutes)
- Use 200-candle MA (≈ 100 minutes)

Why: Confirms overall direction
```

### **2. Stochastic Oscillator (Overbought/Oversold)**

```
Formula: (Close - Low14) / (High14 - Low14) × 100

Interpretation:
- >80 = Overbought (likely reversal down soon)
- <20 = Oversold (likely reversal up soon)
- Crossovers = Entry/exit signals

For BTC:
- Period: 14 (standard)
- Smoothing: 3
- Signal line: 3

Practical:
- Stoch >80 + price near resistance = Sell signal
- Stoch <20 + price near support = Buy signal
- Divergence: Price makes new high but Stoch doesn't = Reversal coming

Current use: Fear & Greed is SIMILAR to Stoch
  - Fear Index 17 = Like Stoch <20 = Oversold = Bounce likely
```

### **3. RSI (Relative Strength Index)**

```
Formula: 100 - (100 / (1 + RS))

Interpretation:
- >70 = Overbought (sell pressure)
- <30 = Oversold (buy pressure)
- Divergence: Price high but RSI doesn't = Bearish reversal

For BTC 15m:
- Period: 14
- Threshold: 30/70 (or 40/60 for more sensitive)

Practical:
- RSI >70 at resistance = Short signal
- RSI <30 at support = Long signal
- Hidden divergence (price lower, RSI higher) = Continuation
```

### **4. MACD (Moving Average Convergence Divergence)**

```
Components:
- MACD line: 12-EMA - 26-EMA
- Signal line: 9-EMA of MACD
- Histogram: MACD - Signal

Signals:
- MACD > Signal = Bullish
- MACD < Signal = Bearish
- MACD crosses above Signal = BUY (golden cross)
- MACD crosses below Signal = SELL (death cross)
- Histogram expanding = Momentum increasing

For BTC 15m:
- Standard settings work (12, 26, 9)
- Watch histogram for momentum
```

### **5. Bollinger Bands (Volatility)**

```
Formula:
- Middle: 20-SMA
- Upper: Middle + (2 × StdDev)
- Lower: Middle - (2 × StdDev)

Signals:
- Price touches upper band = Overbought (potential reversal)
- Price touches lower band = Oversold (potential bounce)
- Bands compress = Low volatility (before big move)
- Bands expand = High volatility (trending hard)

For BTC:
- Period: 20
- StdDev: 2 (standard)

Practical:
- Bands compressed + Fear extrema = Setup for big move
  (current situation: Bands tight + Fear 17 = HUGE move coming)
```

### **6. Volume Profile**

```
What: Where volume occurred at each price level

Signals:
- High volume at price level = Support/Resistance
- Volume increasing with direction = Momentum
- Volume decreasing with direction = Weak move (reversal risk)

For BTC:
- Check Binance 15m volume
- If volume >40% above average = Likely cascade (whale move)
- Direction of volume = Direction of next move
```

---

## 🎯 ENRICHED PREDICTION MODEL (V2)

### **Currently we use (3 signals):**
1. Fear & Greed Index
2. Polymarket odds
3. Volume spikes (proxy for liquidations)

### **Add (6 new technical signals):**
4. **Trend (MA200):** Is BTC above 200-day moving average?
5. **Momentum (MACD):** Is MACD above signal line? Positive histogram?
6. **Overbought/Oversold (RSI + Stoch):** Where are we in the cycle?
7. **Volatility (Bollinger Bands):** Bands wide or compressed?
8. **Support/Resistance:** Are we near key price levels?
9. **Volume Momentum:** Is volume confirming the direction?

---

## 📊 NEW DECISION LOGIC (V2)

```
Score = 0 (neutral start)

IF Trend (MA200):
  Price > MA200 → +1 (bullish regime)
  Price < MA200 → -1 (bearish regime)

IF Momentum (MACD):
  MACD > Signal → +1
  MACD < Signal → -1
  Histogram expanding → +0.5

IF Overbought/Oversold:
  RSI >70 → -1 (sell pressure)
  RSI <30 → +1 (buy pressure)
  Stoch >80 → -1
  Stoch <20 → +1

IF Volatility:
  Bands compressed (rarely happens) → +1 (move coming)
  Price near upper band → -1 (overbought)
  Price near lower band → +1 (oversold)

IF Volume:
  Volume confirming direction → +0.5
  Volume declining with move → -0.5

IF Support/Resistance:
  Price near resistance → -0.5
  Price near support → +0.5

FINAL SCORE:
  -4 to -2: Strong DOWN signal (confidence 70-80%)
  -1.5 to 0: Weak DOWN signal (confidence 55-65%)
  0 to +1.5: Weak UP signal (confidence 55-65%)
  +2 to +4: Strong UP signal (confidence 70-80%)

Then cross-check with:
  - Fear & Greed Index (confirm or diverge)
  - Polymarket odds (what's the market saying)
  - Liquidation pressure (which way will cascade)
```

---

## 🔧 IMPLEMENTATION PLAN

### **Phase 1 Enrichment (Feb 4-5):**
1. ✅ Get BTC 15m OHLCV data from Binance
2. ✅ Calculate all 6 technical indicators
3. ✅ Test new scoring logic on historical data
4. ✅ Validate: Do technical signals improve accuracy?

### **Phase 2 Integration (Feb 10-28):**
5. Add technical signals to cron job
6. Track technical score separately
7. Combine with Fear & Greed + Polymarket
8. Measure if accuracy improves >85%

---

## 💡 KEY INSIGHTS FOR BTC RIGHT NOW

**Current situation (Feb 3):**
- Fear & Greed: 17 (EXTREME oversold)
- Polymarket: Oscillating (confusion)
- Volume: High + volatility
- TA expectation: STRONG reversal likely

**What TA tells us:**
1. RSI/Stoch <20 = Oversold = Bounce imminent
2. Bollinger Bands: Likely compressed (big move coming)
3. MACD: Probably oversold divergence setup
4. MA200: Probably still above current price (bullish long-term)

**Prediction:** Bounce to $80K-$85K likely within 24-48h

---

## 📚 REFERENCES TO STUDY

1. **Wyckoff Method:**
   - Identify accumulation vs distribution phases
   - Smart money always acts before retail

2. **Elliott Wave:**
   - Identify cycle waves (1,2,3,4,5 up then A,B,C down)
   - Wave 3 is usually the strongest

3. **Price Action:**
   - Support/resistance more important than indicators
   - Volume confirms price movement
   - Candle patterns tell the story

4. **On-Chain + TA (Modern):**
   - Whale wallet movements (accumulation)
   - Exchange flows (selling pressure)
   - Funding rates (leverage extremes)

---

**Status:** Research phase complete. Ready to integrate Feb 4. 🚀
