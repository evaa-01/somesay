"""Check all jal targets in boot asm — flag any outside boot segment."""
import re, sys

BOOT_END_RAM = 0x8004F180
asm_file = r"asm\1000.s"

# Read function definitions (glabel) to map names → addresses
func_addrs = {}
with open(asm_file, encoding="utf-8") as f:
    for line in f:
        m = re.search(r'glabel\s+func_([0-9A-Fa-f]+)', line)
        if m:
            func_addrs[f"func_{m.group(1)}"] = int(m.group(1), 16)

# Read jal targets with line numbers
jal_lines = []
with open(asm_file, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        m = re.search(r'\bjal\s+(func_[0-9A-Fa-f]+)', line)
        if m:
            name = m.group(1)
            addr = func_addrs.get(name)
            jal_lines.append((i, name, addr))

outside = [(ln, nm, a) for ln, nm, a in jal_lines if a is not None and a > BOOT_END_RAM]
inside_max = max((a for _, _, a in jal_lines if a is not None), default=None)

print(f"Total jal instructions: {len(jal_lines)}")
print(f"Highest RAM target: 0x{inside_max:08X}" if inside_max else "No jal found")
print(f"Boot segment end:   0x{BOOT_END_RAM:08X}")
if outside:
    print(f"\n⚠ {len(outside)} jal targets OUTSIDE boot segment:")
    for ln, nm, a in sorted(set(outside)):
        print(f"  Line {ln}: {nm} → 0x{a:08X}")
else:
    print("\n✓ All jal targets are inside the boot segment.")
