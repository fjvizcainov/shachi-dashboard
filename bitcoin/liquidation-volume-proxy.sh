#!/bin/bash

# 🔥 LIQUIDATION DETECTION VIA VOLUME SPIKE PROXY
# Since direct liquidation APIs are restricted, use volume spike as proxy
# High volume + price move = cascade liquidations

echo "🔥 Detecting Liquidation Pressure (Volume Proxy Method)..."

# Fetch last 2 candles (15m) to detect volume spike
VOLUME_DATA=$(curl -s --max-time 3 "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=2" 2>/dev/null)

if [ -z "$VOLUME_DATA" ]; then
  echo "  ❌ Binance data unavailable"
  echo "NEUTRAL"
  exit 1
fi

# Parse volumes and price movement
python3 << 'PYTHON'
import json, sys

try:
    data = json.loads('VOLUME_DATA')
    
    if len(data) < 2:
        print("NEUTRAL")
        sys.exit(0)
    
    current = data[-1]
    previous = data[-2]
    
    # Extract data
    curr_open = float(current[1])
    curr_close = float(current[4])
    curr_volume = float(current[7])  # Quote asset volume (USDT)
    
    prev_close = float(previous[4])
    prev_volume = float(previous[7])
    
    # Calculate metrics
    vol_change_pct = ((curr_volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0
    price_change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close > 0 else 0
    
    # Logic: Liquidations detected if...
    # 1. Volume spike >40% AND
    # 2. Price moved significantly (>1%)
    
    print(f'Current volume: \${curr_volume/1e9:.2f}B')
    print(f'Previous volume: \${prev_volume/1e9:.2f}B')
    print(f'Volume change: {vol_change_pct:+.1f}%')
    print(f'Price change: {price_change_pct:+.2f}%')
    
    if vol_change_pct > 40 and abs(price_change_pct) > 1:
        # Liquidation cascade detected
        if price_change_pct < 0:
            print('Signal: DOWN (High volume selling + price drop = long liquidations)')
            print('DOWN')
        else:
            print('Signal: UP (High volume buying + price rise = short liquidations)')
            print('UP')
    elif vol_change_pct > 25:
        # Medium spike
        if price_change_pct < 0:
            print('Signal: DOWN (Elevated volume selling)')
            print('DOWN')
        else:
            print('Signal: UP (Elevated volume buying)')
            print('UP')
    else:
        print('Signal: NEUTRAL (No significant volume spike)')
        print('NEUTRAL')
        
except Exception as e:
    print(f'Error: {e}')
    print('NEUTRAL')
PYTHON
