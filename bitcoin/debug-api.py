#!/usr/bin/env python3
import json
import sys
import urllib.request

try:
    url = "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-15m"
    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.loads(response.read().decode())
        
    if data and isinstance(data, list) and len(data) > 0:
        series = data[0]
        events = series.get('events', [])
        print(f"Total events: {len(events)}")
        print(f"\nFirst 5 events:")
        for i, e in enumerate(events[:5]):
            status = "OPEN" if (e.get('active') == True and e.get('closed') == False) else "CLOSED/INACTIVE"
            print(f"  [{status}] {e.get('id')}: {e.get('title')[:60]}")
        
        # Find first open
        for e in events:
            if e.get('active') == True and e.get('closed') == False:
                print(f"\n✅ FOUND OPEN EVENT:")
                print(f"   ID: {e.get('id')}")
                print(f"   Title: {e.get('title')}")
                sys.exit(0)
        
        print("\n❌ NO OPEN EVENTS FOUND")
        sys.exit(1)
    else:
        print("❌ No data from API")
        sys.exit(1)
except Exception as ex:
    print(f"❌ Error: {ex}")
    sys.exit(1)
