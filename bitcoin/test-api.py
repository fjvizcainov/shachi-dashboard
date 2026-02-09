#!/usr/bin/env python3
import json
import sys

try:
    data = json.load(sys.stdin)
    print("✅ JSON loaded successfully")
    print(f"Type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
except Exception as e:
    print(f"❌ JSON parse error: {e}")
    sys.exit(1)

if not data:
    print("❌ Data is empty")
    sys.exit(1)

series = data[0]
events = series.get('events', [])
print(f"Found {len(events)} events")

# Find first open
for i, e in enumerate(events):
    active = e.get('active')
    closed = e.get('closed')
    if active == True and closed == False:
        print(f"✅ Found open event at index {i}: {e['id']}")
        print(f'{e["id"]}|{e["title"]}|True')
        sys.exit(0)

print("❌ No open events found")
