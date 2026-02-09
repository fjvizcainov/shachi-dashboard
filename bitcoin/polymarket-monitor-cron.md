# Polymarket Bitcoin Monitor - Cron Job Setup

## 📋 APIS INTEGRADAS

### 1. **Gamma API** (Market Discovery)
- **URL:** `https://gamma-api.polymarket.com`
- **Endpoint:** `GET /events?slug=btc-up-or-down-15m`
- **Purpose:** Discover active BTC 15m markets
- **Response:** Market metadata, status, token IDs

### 2. **CLOB API** (Real-time Prices)
- **URL:** `https://clob.polymarket.com`
- **Endpoints:**
  - `GET /prices?market_id=...` — Live odds for both outcomes
  - `GET /orderbook/{tokenId}` — Best bid/ask spread
  - `GET /markets/{id}` — Market details
- **Purpose:** Get live prices, orderbook depth, liquidity
- **Update Frequency:** Real-time (WebSocket available)

### 3. **Data API** (Historical)
- **URL:** `https://data-api.polymarket.com`
- **Endpoint:** `GET /user/{address}` — Position history
- **Purpose:** Track performance, audit trades

### 4. **WebSocket** (Optional - Real-time)
- **URL:** `wss://ws-subscriptions-clob.polymarket.com`
- **Purpose:** Subscribe to orderbook changes, price updates
- **Benefit:** Lower latency than polling

---

## 🚀 CRON JOB CONFIGURATION

### Option A: Node.js Script (Recommended)

```bash
# Run every 30 seconds (tight monitoring for 15m markets)
*/30 * * * * node /Users/moltbot/clawd/bitcoin/polymarket-api-client.js >> /Users/moltbot/clawd/bitcoin/logs/polymarket.log 2>&1
```

### Option B: Clawdbot Cron (Higher-level)

```json
{
  "jobId": "btc-polymarket-monitor",
  "schedule": "*/30 * * * *",
  "text": "Monitor Polymarket BTC 15m odds every 30 seconds. If divergence > 15% from latest prediction, alert. If spike > 50%, trigger immediate analysis.",
  "contextMessages": 5
}
```

---

## 📊 DATA FLOW

```
┌─────────────────────────────────────────┐
│ Cron Job Triggers (every 30 seconds)    │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ Gamma API: Discover active markets      │
│ GET /events?slug=btc-up-or-down-15m    │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ CLOB API: Fetch live odds               │
│ GET /prices?market_id=...               │
│ GET /orderbook/{tokenId}                │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ Parse: UP%, DOWN%, Spread, Liquidity    │
│ Compare vs. last state                  │
└──────────────────┬──────────────────────┘
                   │
                   ▼
        ┌──────────┴──────────┐
        │                     │
   NO CHANGE        SPIKE DETECTED (>50%)
        │                     │
        ▼                     ▼
    Log as OK         ┌────────────────┐
                      │ Alert system   │
                      │ Update tracker │
                      │ Revise pred.   │
                      └────────────────┘
```

---

## 🎯 MONITORING THRESHOLDS

```javascript
const THRESHOLDS = {
  DIVERGENCE_ALERT: 0.15,      // 15% difference from prediction
  SPIKE_THRESHOLD: 0.50,       // 50% movement in one outcome
  LIQUIDITY_MIN: 5000,         // Minimum $5k liquidity to trade
  VOLUME_MONITOR: 50000,       // Alert if volume > $50k spike
  UPDATE_INTERVAL_MS: 30000    // Check every 30 seconds
};
```

---

## 📈 EXPECTED OUTPUT

```
[2026-02-03 02:06:39] ✅ Polymarket Monitor Started
[2026-02-03 02:07:09] 🔍 Fetching BTC 15m markets...
[2026-02-03 02:07:10] ✅ Found: Bitcoin Up or Down - 7:15-7:30 PM ET
[2026-02-03 02:07:11] 💹 UP: 52.5% (bid: 0.52, ask: 0.53)
[2026-02-03 02:07:11] 💹 DOWN: 47.5% (bid: 0.47, ask: 0.48)
[2026-02-03 02:07:11] 📊 Liquidity: $12,800.28 | Volume: $6,579.54
[2026-02-03 02:07:11] ✓ No divergence. Prediction UP (58%) aligned with odds.
[2026-02-03 02:07:40] ⚡ SPIKE DETECTED! UP +179% → Down -30%
[2026-02-03 02:07:41] 🚨 ALERT: Whale accumulation detected. 
[2026-02-03 02:07:42] 📤 Prediction updated: DOWN (72% confidence)
[2026-02-03 02:07:42] 💾 Saved to ~/clawd/bitcoin/predictions/active.json
```

---

## 🔌 INTEGRATION WITH CLAWDBOT

### Via web_fetch (simple)

```bash
# Fetch market list
curl "https://gamma-api.polymarket.com/events?slug=btc-up-or-down-15m" | jq '.[0].markets[0] | {outcomes, outcomePrices, volume, liquidity}'

# Fetch prices
curl "https://clob.polymarket.com/prices?market_id=1316252" | jq '.prices'
```

### Via Node.js Client (recommended)

```javascript
const { PolymarketClient } = require('./polymarket-api-client.js');
const client = new PolymarketClient();
const markets = await client.fetchMarketsGamma('btc-up-or-down-15m');
const odds = JSON.parse(markets[0].markets[0].outcomePrices);
// Process odds...
```

---

## 🧹 CLEANUP & LOGGING

Create log directory:
```bash
mkdir -p /Users/moltbot/clawd/bitcoin/logs
touch /Users/moltbot/clawd/bitcoin/logs/polymarket.log
```

Log rotation (keep last 7 days):
```bash
# Add to crontab
0 0 * * * find /Users/moltbot/clawd/bitcoin/logs -name "polymarket.*.log" -mtime +7 -delete
```

---

## ✅ READY TO DEPLOY

1. **Test the API client:**
   ```bash
   node /Users/moltbot/clawd/bitcoin/polymarket-api-client.js
   ```

2. **Add to crontab:**
   ```bash
   crontab -e
   # Add: */30 * * * * node /Users/moltbot/clawd/bitcoin/polymarket-api-client.js
   ```

3. **Monitor logs:**
   ```bash
   tail -f /Users/moltbot/clawd/bitcoin/logs/polymarket.log
   ```

---

**Status:** Ready for deployment  
**Last Updated:** 2026-02-03 02:06:39 UTC
