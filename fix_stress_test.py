import re

path = r'C:\Users\Administrator\AppData\Local\hermes\hvos\hvos_v7\v7_stress_test.py'
with open(path, 'rb') as f:
    content = f.read()

# Find the bad line
idx = content.find(b'phase11')
if idx >= 0:
    print("Found phase11 at:", idx)
    print("Context:", repr(content[idx-30:idx+80]))

# Replace with correct line
bad = b'    if health_score >= 85 and len(invested_projects) >= 3 and RESULTS["phase11""]["\x27search\x27"]:\r'
good = b'    if health_score >= 85 and len(invested_projects) >= 3 and RESULTS["phase11"]["search"]:\r'

if bad in content:
    content = content.replace(bad, good)
    print("Fixed!")
else:
    # Try finding by pattern
    pattern = rb'results\["phase11"\s*""'
    m = re.search(pattern, content)
    if m:
        print("Found pattern at:", m.start())
        print("Context:", repr(content[m.start()-20:m.start()+60]))
    else:
        print("Could not find bad pattern")

with open(path, 'wb') as f:
    f.write(content)
