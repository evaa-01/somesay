# Converts splat/spimdisasm output into an N64Recomp symbols file.
# Reads: splat\asm\*.s, scripts\size_overrides.txt   Writes: symbols.splat.toml
import re, glob, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project folder (scripts\..)
ASM = BASE + r"\asm"
OUT = BASE + r"\symbols.splat.toml"
OV = BASE + r"\scripts\size_overrides.txt"
# Phase 1: boot segment only. Size 0x4ED80 covers ROM 0x1000–0x4FD80 (from splat config).
SECTIONS = [(".text", 0x1000, 0x80000400, 0x4ED80, "")]

HEAD = re.compile(r"^\s*nonmatching\s+([\w.$]+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)")
INSN = re.compile(r"/\*\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+[0-9A-Fa-f]{8}\s*\*/")

def section_of(path):
    try:
        rom = int(os.path.splitext(os.path.basename(path))[0], 16)
    except ValueError:
        return None
    for sec in SECTIONS:
        if sec[1] <= rom < sec[1] + sec[3]:
            return sec
    return None

funcs = {}   # (section name, vram) -> (name, size)
for path in glob.glob(os.path.join(ASM, "**", "*.s"), recursive=True):
    sec = section_of(path)
    if sec is None:
        continue
    pending = None
    for line in open(path, errors="ignore"):
        m = HEAD.match(line)
        if m:
            name = m.group(1)
            if sec[4] and not name.startswith(sec[4]):
                name = sec[4] + name
            pending = (name, int(m.group(2), 0))
            continue
        if pending:
            m = INSN.search(line)
            if m:
                funcs[(sec[0], int(m.group(1), 16))] = pending
                pending = None

if os.path.exists(OV):
    for line in open(OV):
        parts = line.split("#")[0].split()
        if len(parts) != 2:
            continue
        hit = False
        for v, (n, s) in list(funcs.items()):
            if n == parts[0]:
                funcs[v] = (n, int(parts[1], 0))
                hit = True
                print(f"override: {n} size 0x{s:X} -> {parts[1]}")
        if not hit:
            print(f"WARNING: override for unknown function {parts[0]}")

SA = BASE + r"\scripts\symbol_addrs.txt"
if os.path.exists(SA):
    for line in open(SA):
        parts = line.split("#")[0].split()
        if len(parts) != 3:
            continue
        v, n, s = int(parts[0], 16), parts[1], int(parts[2], 16)
        # Find which section this vram belongs to
        sec_name = None
        for sn, sr, sv, ss, _ in SECTIONS:
            if sv <= v < sv + ss:
                sec_name = sn; break
        if sec_name is None:
            print(f"WARNING: {n} @ 0x{v:X} not in any section")
            continue
        key = (sec_name, v)
        if key in funcs:
            print(f"NOTE: replacing existing entry at vram=0x{v:X} with {n}")
        funcs[key] = (n, s)
        print(f"added: {n} at vram=0x{v:X} size=0x{s:X}")

with open(OUT, "w") as fh:
    for name, rom, vram, size, prefix in SECTIONS:
        fs = sorted((v, n, s) for (sn, v), (n, s) in funcs.items() if sn == name and vram <= v < vram + size)
        bad = [f for f in fs if f[2] < 4 or f[2] % 4]
        fh.write(f'[[section]]\nname = "{name}"\nrom = 0x{rom:08X}\nvram = 0x{vram:08X}\nsize = 0x{size:X}\nfunctions = [\n')
        for v, n, s in fs:
            fh.write(f'    {{ name = "{n}", vram = 0x{v:08X}, size = 0x{s:X} }},\n')
        fh.write("]\n\n")
        print(f"{name}: {len(fs)} functions, {len(bad)} with odd sizes")
