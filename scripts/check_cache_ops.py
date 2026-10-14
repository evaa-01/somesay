"""Classify ALL cache ops in the .s file using bit-0 (D-bit) decoder, verified against known ops.

Verified: osWritebackDCacheAll (cache 0x19)=D ✅, func_80049F90 (cache 0x10, 0x00)=I ✅
"""

import re
from collections import defaultdict

SFILE = "asm/1000.s"
CACHE_PAT = re.compile(r'cache\s+0x([0-9A-Fa-f]+)')
GLABEL_PAT = re.compile(r'^\s*glabel\s+(func_\S+)')

# Read file once
with open(SFILE, "r") as f:
    lines = f.readlines()

# Walk through, tracking current function and cache instructions
current_func = None
cache_entries = []  # (func_name, caller, rt_val)

for i, line in enumerate(lines):
    m = GLABEL_PAT.match(line)
    if m:
        current_func = m.group(1)
        continue

    cm = CACHE_PAT.search(line)
    if not cm or not current_func:
        continue

    rt_val = int(cm.group(1), 16)
    ctype = "D-cache" if (rt_val & 1) else "I-cache"

    # Find caller: last jal instruction before this cache op
    caller = "?"
    for j in range(i - 1, max(0, i - 50), -1):
        jm = re.search(r'jal\s+(func_\w+|0x[0-9A-Fa-f]+)', lines[j])
        if jm:
            caller = jm.group(1)
            break

    cache_entries.append((current_func, caller, rt_val, ctype))

# Verify against known ops
KNOWN = {0x19: "D", 0x10: "I", 0x00: "I"}
for op, expected in KNOWN.items():
    actual = "D" if (op & 1) else "I"
    assert actual == expected, f"Decoder FAIL: 0x{op:x} expected {expected} got {actual}"
print("✅ Decoder bit-0 verified against known ops\n")

# Group by function
by_func = defaultdict(list)
for e in cache_entries:
    by_func[e[0]].append(e)

i_total = sum(1 for e in cache_entries if e[3] == "I-cache")
d_total = sum(1 for e in cache_entries if e[3] == "D-cache")
print(f"Total: {len(cache_entries)} cache instructions | I-cache: {i_total}, D-cache: {d_total}\n")

for func, ops in sorted(by_func.items()):
    types = set(o[3] for o in ops)
    rts = ", ".join(f"0x{o[2]:x}" for o in ops)
    callers = list(set(o[1] for o in ops if o[1] != "?"))
    print(f"{func}: [{rts}] → {', '.join(types)}")
    if len(callers) <= 8:
        print(f"  Called by: {', '.join(sorted(callers))}")
    else:
        print(f"  Called by ({len(callers)} callers): ...")
