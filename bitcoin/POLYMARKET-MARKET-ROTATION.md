# 🔄 Polymarket Market Rotation - Every 15 Minutes

**CRITICAL:** Market ID changes every 15 minutes when the auction expires.

---

## 🎯 Key Points

1. **Series ID is STATIC:** `10192` (BTC Up or Down 15m)
2. **Market ID is DYNAMIC:** Changes every 15 min when previous market closes
3. **Current market:** Always the first event where `active=true AND closed=false`
4. **Previous markets:** Close immediately after 15-minute window expires

---

## 📋 What the Script Does (Correctly)

```bash
# Every 15 minutes:
1. Query: /series?slug=btc-up-or-down-15m
2. Get events array (ordered by most recent first)
3. Find: First event where active=true AND closed=false
4. Extract: Market prices from that event
5. Save: State JSON with NEW market ID
```

**This means NO caching of market ID** — always find the current one.

---

## ⏱️ CRON SCHEDULE CORRECTION

**OLD (WRONG):** Every 30 seconds
```bash
* * * * * /path/to/monitor.sh       # Runs 2x per minute
```

**NEW (CORRECT):** Every 15 minutes
```bash
*/15 * * * * /path/to/polymarket-monitor-v3.sh
```

This ensures:
- ✅ Captures each new market as it opens
- ✅ Gets prices from active auction
- ✅ No wasted API calls between rotations
- ✅ Aligns with Polymarket 15-min cycle

---

## 📊 Example Timeline

```
2:30-2:45 AM ET
  Market ID: 196375
  Status: ACTIVE
  Prices: UP 50.5% / DOWN 49.5%

2:45-3:00 AM ET (NEW MARKET OPENS)
  Market ID: 196376 (NEW)
  Status: ACTIVE
  Prices: UP 48.2% / DOWN 51.8%

Previous market (196375):
  Status: CLOSED
  Prices: locked at 50.5/49.5
```

---

## 🔍 How to Verify It Works

Run the script twice, 15 minutes apart:

```bash
# 2:30 AM
./get-polymarket-live-final-v2.sh
# Output: Market ID 196375

# 2:45 AM (exactly 15 min later)
./get-polymarket-live-final-v2.sh
# Output: Market ID 196376 (DIFFERENT)
```

If market ID changed → **Script working correctly** ✅

---

## 🛡️ Resilience for Market Rotations

The 3-tier system handles:

**Tier 1:** Standard query finds new market immediately
**Tier 2:** If API slow, auto-discovery finds it
**Tier 3:** If everything fails, use cached data (from 15 min ago)

---

## 📁 Updated Cron Job

**File:** (wherever cron job is set up)

```bash
# Every 15 minutes (aligned with market rotation)
*/15 * * * * /Users/moltbot/clawd/bitcoin/polymarket-monitor-v3.sh >> /Users/moltbot/clawd/bitcoin/logs/polymarket-cron.log 2>&1
```

---

## ✅ IMPLEMENTATION CHECKLIST

- [x] Script finds active market dynamically (doesn't cache ID)
- [x] Script runs every 15 minutes (not 30s)
- [x] Logs show new market ID each rotation
- [x] State file updates with fresh market
- [ ] Cron job configured for `*/15 * * * *`

---

**Status:** Script is ready, just need to confirm cron frequency is 15-minute intervals.
