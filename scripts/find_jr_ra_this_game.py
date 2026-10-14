# Find jr $ra (0x27BDxxxx) instructions — these mark function ends.
# Also find jal instructions — these mark function starts.
# This helps identify the boot code region's extent.
import struct, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_PATH = BASE + r"\rom\game.z64"

rom = open(ROM_PATH, "rb").read()

print("=== jr $ra (function ends) in ROM 0x1000-0x5000 ===")
addr = 0x1000
while addr < min(0x5000, len(rom) - 3):
    w = struct.unpack(">I", rom[addr:addr+4])[0]
    if (w >> 6) == 0x27BD:  # jr $ra mask
        delay = struct.unpack(">I", rom[addr+4:addr+8])[0]
        # Check delay slot is a valid use of result (and/or/xor with $v0/$v1/$a0-$a3)
        op = delay >> 26
        print("  ROM 0x{:06X}: jr $ra (delay=0x{:08X} OP=0x{:02X})".format(addr, delay, op))
    addr += 4

print("\n=== jal instructions in ROM 0x1000-0x5000 ===")
addr = 0x1000
while addr < min(0x5000, len(rom) - 3):
    w = struct.unpack(">I", rom[addr:addr+4])[0]
    if (w >> 26) == 8:  # jal opcode
        target = (w & 0x3FFFFFF) << 2
        # RAM address (boot code, so 0x80000400 + (rom - 0x1000))
        ram = 0x80000400 + (addr - 0x1000)
        print("  ROM 0x{:06X}: jal 0x{:08X} (RAM 0x{:08X})".format(addr, target, ram))
    addr += 4

print("\n=== jal in boot section only (ROM 0x1000-0x4000) ===")
addr = 0x1000
while addr < min(0x4000, len(rom) - 3):
    w = struct.unpack(">I", rom[addr:addr+4])[0]
    if (w >> 26) == 8:
        target = (w & 0x3FFFFFF) << 2
        ram = 0x80000400 + (addr - 0x1000)
        print("  ROM 0x{:06X}: jal 0x{:08X} -> RAM 0x{:08X}".format(addr, target, ram))
    addr += 4
