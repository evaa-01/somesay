# Maps between the original game (MIPS addresses) and the generated C code (RecompiledFuncs\funcs_*.c), both ways.
#   python scripts\addr_map.py 0x80001234              MIPS address  -> function + file:line (+ the instruction)
#   python scripts\addr_map.py funcs_3.c:1234          file:line     -> MIPS address + function
#   python scripts\addr_map.py func_80001234           function name -> file:line, first/last MIPS address
#   python scripts\addr_map.py somesay.exe+0x1A2B3     native crash offset (Windows error dialog / Event Viewer
#                                                      "fault offset") -> source file:line (llvm-symbolizer + .pdb)
#                                                      -> MIPS address if the line is in generated code
#   python scripts\addr_map.py --annotate logs\x.txt   prints the text with "[MIPS 0x8...]" after every funcs_N.c:LINE
#                                                      (lldb backtraces, crash logs)
# Options: --funcs <dir> (default: <project>\RecompiledFuncs), --exe <path> (default: the .exe named in the offset,
#          searched in <project>\runtime\build), --symbolizer <path to llvm-symbolizer.exe>.
# How: N64Recomp writes "// 0x8xxxxxxx: <instruction>" above the C line(s) of every instruction and starts every
# function with "RECOMP_FUNC void <name>(". A delay slot can appear twice (once per branch path) - both are listed.
# Generic: no game values. Exit code 0 = found, 1 = not found / error.
import argparse, bisect, glob, os, re, shutil, subprocess, sys

FUNC_RE = re.compile(r'^RECOMP_FUNC\s+void\s+(\w+)\s*\(')
ADDR_RE = re.compile(r'^\s*// 0x([0-9A-Fa-f]{8}):\s*(.*)$')
FILELINE_RE = re.compile(r'((?:[A-Za-z]:)?[\w./\\:-]*?(funcs_\w+\.c)):(\d+)')


class Index:
    """All MIPS-address comments of the generated code: per file the lines, and per address where it appears."""

    def __init__(self, funcs_dir):
        self.funcs_dir = funcs_dir
        self.files = {}      # file name -> list of (line, addr, func, instruction) for every address comment
        self.heads = {}      # file name -> list of (line, func) for every function start
        self.by_addr = {}    # addr -> list of (file, line, func, instruction)
        self.funcs = {}      # func name -> dict(file, line, lo, hi)
        paths = sorted(glob.glob(os.path.join(funcs_dir, '*.c')))
        if not paths:
            raise SystemExit(f'No generated .c files in {funcs_dir} (use --funcs).')
        for path in paths:
            name = os.path.basename(path)
            rows = []
            heads = []
            func = None
            with open(path, encoding='utf-8', errors='replace') as f:
                for n, line in enumerate(f, 1):
                    m = FUNC_RE.match(line)
                    if m:
                        func = m.group(1)
                        heads.append((n, func))
                        self.funcs.setdefault(func, {'file': name, 'line': n, 'lo': None, 'hi': None})
                        continue
                    m = ADDR_RE.match(line)
                    if m and func:
                        addr = int(m.group(1), 16)
                        rows.append((n, addr, func, m.group(2).strip()))
                        self.by_addr.setdefault(addr, []).append((name, n, func, m.group(2).strip()))
                        fi = self.funcs[func]
                        if fi['file'] == name:
                            fi['lo'] = addr if fi['lo'] is None else min(fi['lo'], addr)
                            fi['hi'] = addr if fi['hi'] is None else max(fi['hi'], addr)
            self.files[name] = rows
            self.heads[name] = heads
        # sorted function ranges for "which function contains this address"
        self.ranges = sorted((fi['lo'], fi['hi'], fn) for fn, fi in self.funcs.items() if fi['lo'] is not None)
        self.range_starts = [r[0] for r in self.ranges]

    def at_line(self, file_name, line):
        """MIPS address of a generated C line = the nearest address comment at or above it in the same function.
        Lines between "RECOMP_FUNC" and the first comment (the prologue) belong to the function's first address."""
        name = os.path.basename(file_name)
        rows, heads = self.files.get(name), self.heads.get(name)
        if not rows or not heads:
            return None
        h = bisect.bisect_right([x[0] for x in heads], line) - 1
        if h < 0:
            return None
        head_line, func = heads[h]
        i = bisect.bisect_right([r[0] for r in rows], line) - 1
        if i >= 0 and rows[i][0] > head_line:
            return rows[i]
        first = next((r for r in rows if r[0] > head_line and r[2] == func), None)
        return (head_line, first[1], func, 'function start') if first else None

    def containing(self, addr):
        """Functions whose first..last address range contains addr (more than one = overlays sharing an address)."""
        i = bisect.bisect_right(self.range_starts, addr)
        out = []
        for lo, hi, fn in self.ranges[max(0, i - 50):i]:
            if lo <= addr <= hi:
                out.append(fn)
        return out


def parse_addr(text):
    t = text.strip().lower().replace('_', '')
    if t.startswith('0x'):
        t = t[2:]
    return int(t, 16)


def show_mips(ix, addr):
    hits = ix.by_addr.get(addr)
    if hits:
        print(f'0x{addr:08X}:')
        for file, line, func, instr in hits:
            print(f'  {func:<28} {file}:{line}   {instr}')
        return True
    funcs = ix.containing(addr)
    if funcs:
        print(f'0x{addr:08X}: no instruction comment at exactly this address (not a 4-byte step, or not code), '
              f'but it lies inside: {", ".join(funcs)}')
        return True
    print(f'0x{addr:08X}: not in the generated code (data, an address outside the recompiled sections, '
          f'or a function that is missing from the config).')
    return False


def show_fileline(ix, file_name, line):
    row = ix.at_line(file_name, line)
    if not row:
        print(f'{file_name}:{line}: no MIPS address comment at or above this line (file unknown or line before the '
              f'first function).')
        return False
    n, addr, func, instr = row
    how = f'function start on line {n}' if instr == 'function start' else f'{instr}; comment on line {n}'
    print(f'{os.path.basename(file_name)}:{line} -> 0x{addr:08X} in {func}   ({how})')
    return True


def show_func(ix, name):
    fi = ix.funcs.get(name)
    if not fi:
        close = [f for f in ix.funcs if name.lower() in f.lower()][:10]
        print(f'{name}: no such function in the generated code.' + (f' Similar: {", ".join(close)}' if close else ''))
        return False
    rng = f'0x{fi["lo"]:08X}..0x{fi["hi"]:08X}' if fi['lo'] is not None else '(no instructions)'
    print(f'{name}: {fi["file"]}:{fi["line"]}  MIPS {rng}')
    return True


def find_symbolizer(arg):
    for c in [arg, shutil.which('llvm-symbolizer'), r'C:\Program Files\LLVM\bin\llvm-symbolizer.exe']:
        if c and os.path.isfile(c):
            return c
    return None


def image_base(exe):
    """Preferred image base from the PE header (llvm-symbolizer wants base + offset for .exe files)."""
    with open(exe, 'rb') as f:
        data = f.read(4096)
    pe = int.from_bytes(data[0x3C:0x40], 'little')
    magic = int.from_bytes(data[pe + 24:pe + 26], 'little')
    if magic == 0x20B:   # PE32+
        return int.from_bytes(data[pe + 24 + 24:pe + 24 + 32], 'little')
    return int.from_bytes(data[pe + 24 + 28:pe + 24 + 32], 'little')


def show_native(ix, spec, exe_arg, sym_arg, project):
    module, off = spec.split('+', 1)
    offset = parse_addr(off)
    exe = exe_arg or os.path.join(project, 'runtime', 'build', module)
    if not os.path.isfile(exe):
        print(f'{exe} not found (use --exe).')
        return False
    sym = find_symbolizer(sym_arg)
    if not sym:
        print('llvm-symbolizer not found (install LLVM or use --symbolizer).')
        return False
    addr = image_base(exe) + offset
    r = subprocess.run([sym, f'--obj={exe}', '--inlining', '--relative-address', f'0x{offset:X}'],
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or all(l.startswith('??') for l in lines):
        # older llvm-symbolizer without --relative-address: give it the absolute address
        r = subprocess.run([sym, f'--obj={exe}', '--inlining', f'0x{addr:X}'], capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or all(l.startswith('??') for l in lines):
        print(f'{spec}: no source line found (is the .pdb next to the .exe and from the same build?).')
        return False
    print(f'{spec}:')
    ok = True
    for i in range(0, len(lines) - 1, 2):
        func, where = lines[i], lines[i + 1]
        print(f'  {func}  at {where}')
        m = re.match(r'(.*?):(\d+)(?::\d+)?$', where)
        if m and re.search(r'funcs_\w+\.c$', m.group(1)):
            ok = show_fileline(ix, m.group(1), int(m.group(2))) and ok
    return ok


def annotate(ix, path):
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            extra = []
            for m in FILELINE_RE.finditer(line):
                row = ix.at_line(m.group(2), int(m.group(3)))
                if row:
                    extra.append(f'0x{row[1]:08X}')
            print(line + (f'   [MIPS {", ".join(extra)}]' if extra else ''))
    return True


def main():
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description='MIPS address <-> generated C code <-> native crash offset.')
    ap.add_argument('what', nargs='?', help='0x8..., funcs_N.c:LINE, func name, or module.exe+0xOFFSET')
    ap.add_argument('--annotate', metavar='FILE', help='add MIPS addresses to every funcs_N.c:LINE in a text file')
    ap.add_argument('--funcs', default=os.path.join(project, 'RecompiledFuncs'))
    ap.add_argument('--exe')
    ap.add_argument('--symbolizer')
    a = ap.parse_args()
    if not a.what and not a.annotate:
        ap.print_help()
        return 1
    ix = Index(a.funcs)
    if a.annotate:
        ok = annotate(ix, a.annotate)
    elif '+' in a.what:
        ok = show_native(ix, a.what, a.exe, a.symbolizer, project)
    elif re.search(r'\.c:\d+$', a.what):
        f, l = a.what.rsplit(':', 1)
        ok = show_fileline(ix, f, int(l))
    elif re.fullmatch(r'(0x)?[0-9A-Fa-f_]{8,10}', a.what):
        ok = show_mips(ix, parse_addr(a.what))
    else:
        ok = show_func(ix, a.what)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
