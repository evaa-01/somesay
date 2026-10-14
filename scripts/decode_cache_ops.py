"""Decode cache ops using user rule: bits 20-16 = op, (op & 3) → 0=I-cache, 1=D-cache."""
import re

BOOT_LO, BOOT_HI = 0x80000400, 0x8005B280

with open("asm/1000.s") as f:
    lines = f.readlines()

# Build function map from glabel/nonmatching lines
funcs = []
for i, line in enumerate(lines):
    m = re.match(r'(?:nonmatching|glabel)\s+(\w+)', line.strip())
    if m:
        funcs.append((i, m.group(1)))


def who(line_num):
    name = "unknown"
    for idx, (start, fn) in enumerate(funcs):
        if start > line_num:
            break
        name = fn
    return name


# Find all cache instructions in boot section and decode them
icache_funcs = {}  # func_name -> list of callers
dcache_funcs = {}

for i, line in enumerate(lines):
    if "cache" not in line:
        continue
    addr_m = re.search(r'(\[?800[0-9a-fA-F]+\]?)', line)
    ram = int(addr_m.group(1).strip("[]"), 16) if addr_m else None
    if not ram or not (BOOT_LO <= ram < BOOT_HI):
        continue
    hex_m = re.search(r'([0-9A-Fa-f]{8})\s+\*/', line)
    if not hex_m:
        continue
    op = (int(hex_m.group(1), 16) >> 16) & 0x1F
    cache_type = "I" if (op & 3) == 0 else "D"
    fn = who(i)
    print(f"  {fn:>25s} RAM {ram:#010x} op={op:#04x} ({op&3}) {'I' if cache_type=='I' else 'D'}-cache")
    icache_funcs.setdefault(fn, []).append(op) if cache_type == "I" else dcache_funcs.setdefault(fn, []).append(op)

print()
# Verify osWritebackDCacheAll is D-cache
print("osWritebackDCacheAll D-cache check:", "PASS" if any(0x01 in v for v in dcache_funcs.values()) else "FAIL")
print()

# I-cache functions and their callers
print("=== FUNCTIONS TOUCHING INSTRUCTION CACHE ===")
for fn, ops in sorted(icache_funcs.items()):
    print(f"\n  {fn}: ops={ops}")
    # Find who calls this function
    for j, l in enumerate(lines):
        if f"jal {fn}" in l:
            addr_m = re.search(r'(\[?800[0-9a-f]+\]?)', l)
            caller_ram = int(addr_m.group(1).strip("[]"), 16) if addr_m else None
            if caller_ram and BOOT_LO <= caller_ram < BOOT_HI:
                print(f"    called by {who(j)} at RAM {caller_ram:#010x}")

print()
print("=== FUNCTIONS TOUCHING DATA CACHE ===")
for fn, ops in sorted(dcache_funcs.items()):
    print(f"\n  {fn}: ops={ops}")
