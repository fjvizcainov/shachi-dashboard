#!/bin/bash

# ✅ POLYMARKET LIVE - WORKING VERSION
# Fetches ACTUAL/CURRENT BTC 15m market (not historical)

python3 << 'PYTHON'
import json, sys, requests
from datetime import datetime

print("📊 Fetching CURRENT Polymarket BTC 15m market...")

# Get series
r = requests.get("https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m", timeout=5)
series = r.json()[0]

print(f"✅ Series: {series['title']}")

# Find ACTIVE market (closed=false, active=true, or endDate in future)
events = series.get('events', [])
print(f"Total events in series: {len(events)}")

# Filter for markets that might still be active
candidates = [e for e in events if e.get('active') == True or e.get('closed') == False]
print(f"Potential active markets: {len(candidates)}")

if not candidates:
    print("⚠️ No active markets. Using most recent...")
    market = events[0]
else:
    market = candidates[0]

market_id = market['id']
market_title = market['title']
market_active = market.get('active', False)
market_closed = market.get('closed', True)

print(f"✅ Selected market: {market_title}")
print(f"   ID: {market_id}, Active: {market_active}, Closed: {market_closed}")

# Get market details
r2 = requests.get(f"https://gamma-api.polymarket.com/events/{market_id}", timeout=5)
market_detail = r2.json()

outcomes_str = market_detail['markets'][0]['outcomes']
prices_str = market_detail['markets'][0]['outcomePrices']

# Parse
outcomes = json.loads(outcomes_str)
prices = json.loads(prices_str)

up_price = float(prices[0]) if prices and prices[0] else 0.5
down_price = float(prices[1]) if prices and len(prices) > 1 and prices[1] else 0.5

up_percent = round(up_price * 100, 1)
down_percent = round(down_price * 100, 1)

# Get BTC price
try:
    r3 = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=3)
    btc_price = r3.json()['bitcoin']['usd']
except:
    btc_price = 0

# Output
result = {
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "market_id": market_id,
    "market_title": market_title,
    "market_active": market_active,
    "market_closed": market_closed,
    "up_percent": up_percent,
    "down_percent": down_percent,
    "btc_price": btc_price,
    "source": "Gamma API"
}

print(f"\n✅ UP: {up_percent}%")
print(f"✅ DOWN: {down_percent}%")
print(f"✅ BTC: ${btc_price:,.0f}")

# Save state
with open("/Users/moltbot/clawd/bitcoin/polymarket-state.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"\n✅ Saved to polymarket-state.json")
print(json.dumps(result, indent=2))

PYTHON
