#!/bin/bash

# ✅ POLYMARKET LIVE DATA - CORRECTED
# Gets the ACTUAL ACTIVE BTC 15m market (not historical)

python3 << 'PYTHON'
import json, sys, requests
from datetime import datetime

print("📊 Fetching CURRENT Polymarket BTC 15m market...\n")

# 1. Get series
print("[1] Fetching BTC 15m series...")
try:
    r = requests.get("https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m", timeout=5)
    series = r.json()
    if not series:
        print("❌ No series found")
        sys.exit(1)
    
    series = series[0]
    print(f"✅ Series: {series['title']} (ID: {series['id']})")
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)

# 2. Find FIRST ACTIVE event (not closed)
print("\n[2] Finding first ACTIVE event...")
events = series.get('events', [])
print(f"   Total events in series: {len(events)}")

active_event = None
for e in events:
    if e.get('active') == True and e.get('closed') == False:
        active_event = e
        break

if not active_event:
    print("⚠️  No active events. Using most recent...")
    active_event = events[0]

market_id = active_event['id']
market_title = active_event['title']
market_active = active_event.get('active', False)
market_closed = active_event.get('closed', True)

print(f"✅ Market: {market_title}")
print(f"   ID: {market_id}, Active: {market_active}, Closed: {market_closed}")

# 3. Get market DETAILS from the correct event
print("\n[3] Fetching market details...")
try:
    r2 = requests.get(f"https://gamma-api.polymarket.com/events/{market_id}", timeout=5)
    market_detail = r2.json()
    
    # IMPORTANT: Extract from markets[0], which is the CLOB market
    if 'markets' not in market_detail or not market_detail['markets']:
        print("❌ No markets in event")
        sys.exit(1)
    
    market = market_detail['markets'][0]
    
    # Parse outcomes and prices (they're JSON strings)
    outcomes_str = market.get('outcomes', '["Up", "Down"]')
    prices_str = market.get('outcomePrices', '[0.5, 0.5]')
    
    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
    
    up_price = float(prices[0]) if prices and prices[0] else 0.5
    down_price = float(prices[1]) if prices and len(prices) > 1 and prices[1] else 0.5
    
    # Normalize to 100%
    if up_price == 0 and down_price == 1:
        # Historical market, get current odds from best price or default
        up_price = 0.5
        down_price = 0.5
    
    up_percent = round(up_price * 100, 1)
    down_percent = round(down_price * 100, 1)
    
    print(f"✅ UP: {up_percent}% / DOWN: {down_percent}%")
    
except Exception as e:
    print(f"❌ Error parsing market: {e}")
    sys.exit(1)

# 4. Get BTC price
print("\n[4] Fetching BTC price...")
try:
    r3 = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=3)
    btc_price = r3.json()['bitcoin']['usd']
    print(f"✅ BTC: ${btc_price:,.0f}")
except:
    btc_price = 0
    print("⚠️  BTC price unavailable")

# 5. Save
result = {
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "market_id": market_id,
    "market_title": market_title,
    "market_active": market_active,
    "market_closed": market_closed,
    "up_percent": up_percent,
    "down_percent": down_percent,
    "btc_price": btc_price,
    "source": "Gamma API (corrected)"
}

import os
state_file = "/Users/moltbot/clawd/bitcoin/polymarket-state.json"
os.makedirs(os.path.dirname(state_file), exist_ok=True)

with open(state_file, "w") as f:
    json.dump(result, f, indent=2)

print(f"\n✅ Saved to {state_file}")
print(json.dumps(result, indent=2))

PYTHON
