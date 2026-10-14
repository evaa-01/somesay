# Detailed scan of specific ROM ranges — every 4 bytes, CODE or DATA.
import struct, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_PATH = BASE + r"\rom\game.z64"

VALID_OPS = {0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
             16, 17, 18, 19, 20, 21, 24, 25, 28, 32, 33, 34, 35,
             36, 37}

rom = open(ROM_PATH, "rb").read()

def scan_range(label, start, end):
    print("=== {} (ROM 0x{:X}-0x{:X}) ===".format(label, start, end))
    i = start
    consecutive_data = 0
    while i < end - 3:
        w = struct.unpack(">I", rom[i:i+4])[0]
        op = w >> 26
        if op in VALID_OPS:
            if consecutive_data > 0:
                print("  ...{} data words before...".format(consecutive_data))
                consecutive_data = 0
            # Print short form for code words
            print("  0x{:06X}: 0x{:08X} OP=0x{:02X}".format(i, w, op))
        else:
            if consecutive_data == 0:
                data_start = i
            consecutive_data += 1
            if consecutive_data % 16 == 0 or i + 4 >= end - 3:
                print("  ...{} consecutive DATA words (0x{:X}-0x{:X})...".format(
                    consecutive_data, data_start, i))
        i += 4
    print()

# Key zones to check for boot segment boundary
scan_range("Boot gap 1", 0x3780, 0x4080)
scan_range("ROM ~0x2E00-0x3200 area", 0x2D80, 0x3280)

# Also check what's after the last dense region (potential microcode/data area)
scan_range("End of scanned area", 0x3F000, 0x40400)
