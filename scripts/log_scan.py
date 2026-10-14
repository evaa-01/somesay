# Scans the game's console output for the runtime's known problem messages and lists them once each, with counts,
# MIPS addresses resolved to functions (via addr_map.py) and the last lines of the log.
#   python scripts\log_scan.py logs\run_stdout.txt [logs\run_stderr.txt ...] [--os-range 0x80000400-0x8000XXXX]
#   [--funcs RecompiledFuncs] [--tail 15]
# The patterns are the messages that the runtime and the generated code really print (looked up in
# tools\N64ModernRuntime: librecomp\src\overlays.cpp, recomp.cpp, pi.cpp; ultramodern\src\events.cpp). Anything that
# looks like an error but matches no known pattern is listed under "other" - read those lines yourself.
# Not visible in a log: functions stubbed in the config are silent (empty body), so a stub being called prints nothing.
# --os-range (optional, this game's OS library range from NOTES) marks each address as OS or GAME.
# Generic: no game values. Exit code: 0 = nothing found, 2 = problems found, 1 = error.
import argparse, collections, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from addr_map import Index  # noqa: E402

# (name, regex, what it usually means)
KNOWN = [
    ('missing function', r'Failed to find function at 0x([0-9A-Fa-f]{8})',
     'code jumped to an address with no recompiled function: a function missing from the config, a wrong size/'
     'split, or an overlay that is not registered/loaded'),
    ('jump table', r'Switch-case out of bounds in (\S+) at 0x([0-9A-Fa-f]{8}) for jump table at 0x([0-9A-Fa-f]{8})',
     'a switch index outside the jump table: wrong function size or a jump table read from the wrong place'),
    ('break', r'Encountered break at original vram 0x([0-9A-Fa-f]{8})',
     'the game ran a MIPS "break" instruction (its own crash/assert handler, or data executed as code)'),
    ('status register', r'Unhandled status register bits changed: 0x([0-9A-Fa-f]{8})',
     'the game changed CPU status bits the runtime does not emulate (often harmless, check the address/caller)'),
    ('PI DMA unknown', r'\[WARN\] PI DMA (read from|write to) unknown region, phys address 0x([0-9A-Fa-f]{8})',
     'a cartridge DMA from/to an address that is neither ROM nor a known save area'),
    ('runtime stub', r'Stub `(\w+)` function called',
     'the game called an OS function the runtime only stubs'),
    ('ROM write', r'ROM DMA write unimplemented', 'the game tried to write to the ROM (save type?)'),
    ('RSP task', r'Failed to execute task type: (\d+)', 'an RSP task type the runtime does not handle'),
    ('renderer', r'Failed to (load dynamic libraries|initialize the renderer)', 'graphics start-up failed (DLLs, GPU)'),
]
KNOWN = [(n, re.compile(p), w) for n, p, w in KNOWN]
OTHER = re.compile(r'(?i)\b(error|exception|assert(ion)?|abort|terminate|fatal|failed|unhandled|unimplemented|'
                   r'access violation|segfault)\b')
HEX8 = re.compile(r'0x([0-9A-Fa-f]{8})')


def parse_range(text):
    lo, hi = text.split('-')
    return int(lo, 16), int(hi, 16)


def main():
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description='Known runtime problems in the game console output.')
    ap.add_argument('logs', nargs='+')
    ap.add_argument('--funcs', default=os.path.join(project, 'RecompiledFuncs'))
    ap.add_argument('--os-range', help='OS library range from NOTES, e.g. 0x80000400-0x80012345')
    ap.add_argument('--tail', type=int, default=15)
    a = ap.parse_args()
    os_range = parse_range(a.os_range) if a.os_range else None
    try:
        ix = Index(a.funcs)
    except SystemExit as e:
        print(f'(no address lookup: {e})')
        ix = None

    hits = collections.OrderedDict()   # (name, line text) -> [count, first line number, file]
    other = collections.OrderedDict()
    tails = {}
    for path in a.logs:
        if not os.path.isfile(path):
            print(f'{path}: not found')
            return 1
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = [l.rstrip('\n') for l in f]
        tails[path] = lines[-a.tail:]
        for n, line in enumerate(lines, 1):
            for name, rx, _ in KNOWN:
                if rx.search(line):
                    key = (name, line.strip())
                    hits.setdefault(key, [0, n, path])[0] += 1
                    break
            else:
                if OTHER.search(line):
                    key = line.strip()
                    other.setdefault(key, [0, n, path])[0] += 1

    def where(addr):
        if addr < 0x80000000:
            return 'not a RAM code address (physical/cartridge address or garbage)'
        parts = []
        if os_range:
            parts.append('OS' if os_range[0] <= addr < os_range[1] else 'GAME')
        if ix:
            if addr in ix.by_addr:
                parts.append('in ' + ', '.join(sorted({h[2] for h in ix.by_addr[addr]})))
            else:
                inside = ix.containing(addr)
                parts.append(('inside ' + ', '.join(inside)) if inside else 'no generated function there')
        return '; '.join(parts)

    print(f'== {sum(v[0] for v in hits.values())} known problem lines ({len(hits)} different)')
    for name, rx, meaning in KNOWN:
        group = [(k[1], v) for k, v in hits.items() if k[0] == name]
        if not group:
            continue
        print(f'\n[{name}] {meaning}')
        for text, (count, n, path) in group:
            print(f'  {count:>5}x  {os.path.basename(path)}:{n}  {text[:160]}')
            for h in dict.fromkeys(HEX8.findall(text)):
                print(f'          0x{h.upper()}: {where(int(h, 16))}')
    print(f'\n== {len(other)} other error-like lines (first 20)')
    for text, (count, n, path) in list(other.items())[:20]:
        print(f'  {count:>5}x  {os.path.basename(path)}:{n}  {text[:160]}')
    for path, t in tails.items():
        print(f'\n== last {len(t)} lines of {path}')
        for line in t:
            print('  ' + line[:200])
    return 2 if hits or other else 0


if __name__ == '__main__':
    sys.exit(main())
