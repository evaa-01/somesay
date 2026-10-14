"""Decode lui/addiu arguments around OS calls in 1000.s."""
import re

ASM = r"asm\1000.s"

with open(ASM) as f:
    lines = f.readlines()

# --- 1. Unique D_ labels sorted by address -----------------------------------
d_labels_set = set()
for line in lines:
    for m in re.finditer(r'D_(80[0-9A-Fa-f]+)', line):
        d_labels_set.add(m.group(1))

print("=" * 120)
print("ALL UNIQUE D_ LABELS (sorted by address):")
print("=" * 120)
for label in sorted(d_labels_set):
    print(f"0x{int(label, 16):08X}  D_{label}")

# --- 2. Scan for lui+addiu pairs near OS calls --------------------------------
OS_FUNCS = {"osCreateMesgQueue", "osSetEventMesg", "osViSetEvent",
            "osSendMesg", "osRecvMesg"}

print()
print("=" * 120)
print("JAL CALLS with lui+addiu arguments (queue/event/flag operations):")
print("=" * 120)

for i, line in enumerate(lines):
    stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', line).strip()

    if not stripped.startswith("jal"):
        continue

    func_called = re.search(r'jal\s+(\w+)', stripped)
    called_name = func_called.group(1) if func_called else None

    if called_name not in OS_FUNCS and not ('D_' in stripped):
        continue

    # Look back up to 12 lines for argument setup. Track ALL $a0 values seen.
    a0_chain = []   # list of (label_or_imm)
    arg_imms = {}   # reg_num -> last immediate value
    arg_labels = {} # reg_num -> last D_ label

    for j in range(max(0, i - 12), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        # lui $aX, %hi(D_XXXXXX)
        m = re.match(r'lui\s+\$a(\d),\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m:
            reg_num = int(m.group(1))
            arg_labels[reg_num] = m.group(2)
            a0_chain.append(('label', m.group(2))) if reg_num == 0 else None

        # addiu $aX, ..., %lo(D_XXXXXX) — confirms label
        m = re.match(r'addiu\s+\$a(\d),.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m:
            reg_num = int(m.group(1))
            arg_labels[reg_num] = m.group(2)

        # addiu $aX, $zero, 0xNNNN or decimal NNNN (immediate values)
        m = re.match(r'addiu\s+\$a(\d),\s*\$zero,\s*(\S+)', prev_stripped)
        if m:
            reg_num = int(m.group(1))
            val_str = m.group(2)
            try:
                val = int(val_str, 16) if val_str.startswith('0x') else int(val_str)
                arg_imms[reg_num] = val
                a0_chain.append(('imm', val)) if reg_num == 0 else None
            except ValueError:
                pass

    # Build resolved args string — last value per register wins for address,
    # but show all $a0 values for event registration analysis
    resolved_parts = []
    for rn in range(4):
        if rn in arg_labels:
            label = arg_labels[rn]
            try:
                ram_addr = f"0x{int(label, 16):08X}"
                resolved_parts.append(f"a{rn}={ram_addr}")
            except ValueError:
                resolved_parts.append(f"a{rn}=D_{label}")
        if rn in arg_imms:
            resolved_parts.append(f"a{rn}_imm=0x{arg_imms[rn]:X}" if arg_imms[rn] > 9 else f"a{rn}_imm={arg_imms[rn]}")

    args_str = ", ".join(resolved_parts)

    # Show $a0 chain for osSetEventMesg to see event ID + queue addr
    a0_chain_str = ""
    if called_name in ("osSetEventMesg", "osViSetEvent"):
        vals = [f"{'D_'+v[1] if v[0]=='label' else 'imm='+str(v[1])}" for v in a0_chain]
        a0_chain_str = f" [$a0_seq={', '.join(vals)}]"

    # Find parent function name
    func_name = "?"
    for k in range(i, max(0, i - 50), -1):
        lm = re.match(r'\s*glabel\s+(\w+)', lines[k])
        if lm:
            func_name = lm.group(1)
            break

    has_d_label = any('D_' in p for p in resolved_parts) or called_name in OS_FUNCS

    if args_str and has_d_label:
        print(f"L{i+1:6d} [{func_name}] {called_name:<25} {args_str}{a0_chain_str}")

# --- 3. Detailed osCreateMesgQueue listing ------------------------------------
print()
print("=" * 120)
print("osCreateMesgQueue calls (a0=queue_addr, a1=buf_addr, a2=size):")
print("=" * 120)

for i, line in enumerate(lines):
    stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', line).strip()

    if "osCreateMesgQueue" not in stripped:
        continue

    func_name = "?"
    for k in range(i, max(0, i - 50), -1):
        lm = re.match(r'\s*glabel\s+(\w+)', lines[k])
        if lm:
            func_name = lm.group(1)
            break

    a0_label = None
    a1_label = None
    a2_val = None

    for j in range(max(0, i - 8), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        m = re.match(r'lui\s+\$a0,\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m: a0_label = int(m.group(1), 16)

        m = re.match(r'addiu\s+\$a0.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m and a0_label is None: a0_label = int(m.group(1), 16)

        m = re.match(r'lui\s+\$a1,\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m: a1_label = int(m.group(1), 16)

        m = re.match(r'addiu\s+\$a1.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m and a1_label is None: a1_label = int(m.group(1), 16)

        m = re.match(r'addiu\s+\$a2,\s*\$zero,\s*0x([0-9A-Fa-f]+)', prev_stripped)
        if m: a2_val = int(m.group(1), 16)

    a0_str = f"0x{a0_label:08X}" if a0_label is not None else "?"
    a1_str = f"0x{a1_label:08X}" if a1_label is not None else "?"
    a2_hex = f"{a2_val:X}" if a2_val is not None else "0"
    print(f"  L{i+1} [{func_name}] osCreateMesgQueue(a0={a0_str}, a1={a1_str}, a2=0x{a2_hex})")

# --- 4. osSetEventMesg / osViSetEvent listing ----------------------------------
print()
print("=" * 120)
print("osSetEventMesg / osViSetEvent calls (event_id -> queue):")
print("=" * 120)

for i, line in enumerate(lines):
    stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', line).strip()

    if "osSetEventMesg" not in stripped and "osViSetEvent" not in stripped:
        continue

    func_name = "?"
    for k in range(i, max(0, i - 50), -1):
        lm = re.match(r'\s*glabel\s+(\w+)', lines[k])
        if lm:
            func_name = lm.group(1)
            break

    # Collect ALL $a0 assignments from preceding instructions (event ID first, then queue addr)
    a0_vals = []  # list of ("imm", decimal_val) or ("label", hex_addr)
    for j in range(max(0, i - 8), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        # Event ID: addiu $a0, $zero, N (decimal)
        m = re.match(r'addiu\s+\$a0,\s*\$zero,\s*(\d+)', prev_stripped)
        if m:
            a0_vals.append(("imm", int(m.group(1))))

        # Queue address: lui $a0, %hi(D_XXXXXX) or addiu ... %lo(...)
        m = re.match(r'lui\s+\$a0,\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m:
            a0_vals.append(("label", int(m.group(1), 16)))

        m = re.match(r'addiu\s+\$a0.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m and not any(v[0] == "label" for v in a0_vals):
            a0_vals.append(("label", int(m.group(1), 16)))

    # Also check $a1 (third arg — message buffer pointer)
    a1_label = None
    for j in range(max(0, i - 8), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        m = re.match(r'lui\s+\$a1,\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m: a1_label = int(m.group(1), 16)

        m = re.match(r'addiu\s+\$a1.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m and a1_label is None: a1_label = int(m.group(1), 16)

    label_addrs = [v[1] for v in a0_vals if v[0] == "label"]
    queue_str = f"0x{label_addrs[-1]:08X}" if label_addrs else "?"
    event_id = str(a0_vals[0][1]) if a0_vals and a0_vals[0][0] == "imm" else "?"
    a1_str = f"0x{a1_label:08X}" if a1_label else "?"

    print(f"  L{i+1} [{func_name}] {stripped[:70]}")
    print(f"         event_id={event_id}, queue_addr={queue_str}, buf_ptr={a1_str}")

# --- 5. osSendMesg / osRecvMesg calls ----------------------------------------
print()
print("=" * 120)
print("osSendMesg / osRecvMesg calls (queue_addr, msg_buf, flags):")
print("=" * 120)

for i, line in enumerate(lines):
    stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', line).strip()

    if "osSendMesg" not in stripped and "osRecvMesg" not in stripped:
        continue

    func_name = "?"
    for k in range(i, max(0, i - 50), -1):
        lm = re.match(r'\s*glabel\s+(\w+)', lines[k])
        if lm:
            func_name = lm.group(1)
            break

    queue_label = None
    flags_val = "?"

    for j in range(max(0, i - 8), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        m = re.match(r'lui\s+\$a0,\s*%hi\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m: queue_label = int(m.group(1), 16)

        m = re.match(r'addiu\s+\$a0.*%lo\(D_(80[0-9A-Fa-f]+)\)', prev_stripped)
        if m and queue_label is None: queue_label = int(m.group(1), 16)

    # Flags from $a2 or $a3
    for j in range(max(0, i - 8), i + 1):
        prev_stripped = re.sub(r'\s*/\*\s+[0-9A-F]+\s+80[0-9A-F]+\s+[0-9A-F]{8}\s*\*/\s*', '', lines[j]).strip()

        m = re.match(r'addiu\s+\$a(\d),\s*\$zero,\s*(\S+)', prev_stripped)
        if m and int(m.group(1)) in (2, 3):
            val_str = m.group(2)
            try:
                flags_val = str(int(val_str, 16)) if val_str.startswith('0x') else val_str
            except ValueError:
                pass

    queue_str = f"0x{queue_label:08X}" if queue_label else "?"

    print(f"  L{i+1} [{func_name}] {stripped[:70]}")
    print(f"         queue={queue_str}, flags={flags_val}")
