"""
Extract all stage layout tables from the Mega Man X4 PSX executable (SLUS_005.61).

Layout data format (ported from TeheManX4_Editor/Level.cs → ExtractLevelData):
  LayoutDataPointersOffset = 0x1007DC   raw file offset; LE uint32 CPU pointers, one per index
  LayoutSizeOffset         = 0x100864   raw file offset; byte pairs (w, h), one per index
  CpuToOffset(cpu)         = cpu − exe[0x18:0x1C] + 0x800
  Layout                   = w × h × 3 bytes  (3 consecutive layers, each w×h screen IDs)

Index mapping (from GetIndex() in Level.cs):
  index = hex_digit(filename[3]) × 2 + mid
  mid   = 1  if "_01.ARC" or "U1" in filename, else 0
  STD_1_xU.ARC → index 27  (special case)

Output:
  PSX/X4/layouts/{STEM}.bin    raw layout bytes (w*h*3)
  PSX/X4/layouts/index.json    metadata: index, stem, w, h, size, cpu_ptr, file_offset
"""

import json
import struct
from pathlib import Path

PSX_PATH = Path("PSX/X4/SLUS_005.61")
OUT_DIR  = Path("PSX/X4/layouts")

LAYOUT_DATA_PTRS_OFF = 0x1007DC   # table of LE uint32 CPU pointers, one per index
LAYOUT_SIZE_OFF      = 0x100864   # table of (w, h) byte pairs, one per index
MAX_INDICES          = 32

# index → canonical output stem  (derived from GetIndex() / ARC filenames in Level.cs)
INDEX_NAMES: dict[int, str] = {
    0:  "ST00_00",   # Intro main
    1:  "ST00_01",   # Intro mid
    2:  "ST01_00",   # Web Spider main
    3:  "ST01_01",   # Web Spider mid
    4:  "ST02_00",   # Frost Walrus main
    5:  "ST02_01",   # Frost Walrus mid
    6:  "ST03_00",   # Split Mushroom main
    7:  "ST03_01",   # Split Mushroom mid
    8:  "ST04_00",   # Cyber Peacock main
    9:  "ST04_01",   # Cyber Peacock mid
    10: "ST05_00",   # Slash Beast main
    11: "ST05_01",   # Slash Beast mid
    12: "ST06_00",   # Jet Stingray main
    13: "ST06_01",   # Jet Stingray mid
    14: "ST07_00",   # Storm Owl main
    15: "ST07_01",   # Storm Owl mid
    16: "ST08_00",   # Magma Dragoon main
    17: "ST08_01",   # Magma Dragoon mid
    18: "ST09_00",   # Colonel main
    19: "ST09_01",   # Colonel mid
    20: "ST0A_00",   # Space Port main
    21: "ST0A_01",   # Space Port mid
    22: "ST0B_00",   # Final Weapon  (ST0B_0X and ST0B_0Z share this index)
    # 23: unused
    24: "ST0C_00",   # Refights main
    25: "ST0C_01",   # Refights mid
    26: "ST0D_00",   # Stage Select  (ST0D_0X and ST0D_0Z share this index)
    27: "STD_1U",    # Boss Intro
    28: "ST0E_U0",   # Title Screen
    29: "ST0E_U1",   # Player Select
    30: "ST0F_UX",   # Weapon Get    (ST0F_UX and ST0F_UZ share this index)
    31: "ST0F_U1",   # Credits
}


def main() -> None:
    exe = PSX_PATH.read_bytes()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base_addr = struct.unpack_from("<I", exe, 0x18)[0]
    print(f"PSX EXE : {PSX_PATH}  ({len(exe):,} bytes)")
    print(f"Base addr: 0x{base_addr:08X}")
    print()

    col_w = 3 + 2 + 12 + 3 + 3 + 6 + 10 + 10 + 6
    header = f"{'Idx':>3}  {'Stem':<12}  {'W':>3}  {'H':>3}  {'Bytes':>6}  {'CPU ptr':>10}  {'File off':>10}  {'L0 max':>6}"
    print(header)
    print("-" * len(header))

    meta: list[dict] = []
    dumped = 0

    for i in range(MAX_INDICES):
        w   = exe[LAYOUT_SIZE_OFF + i * 2]
        h   = exe[LAYOUT_SIZE_OFF + i * 2 + 1]
        ptr = struct.unpack_from("<I", exe, LAYOUT_DATA_PTRS_OFF + i * 4)[0]
        stem = INDEX_NAMES.get(i, str(i))

        if w == 0 or h == 0 or ptr == 0:
            print(f"{i:>3}  {stem:<12}  {w:>3}  {h:>3}  {'---':>6}  0x{ptr:08X}  {'(skip)':>10}")
            meta.append({"index": i, "stem": stem, "w": w, "h": h,
                          "cpu_ptr": ptr, "file_offset": None})
            continue

        file_off = ptr - base_addr + 0x800
        size     = w * h * 3

        if file_off < 0 or file_off + size > len(exe):
            print(f"{i:>3}  {stem:<12}  {w:>3}  {h:>3}  {size:>6}  0x{ptr:08X}  0x{file_off:08X}  ** OUT OF RANGE **")
            meta.append({"index": i, "stem": stem, "w": w, "h": h,
                          "cpu_ptr": ptr, "file_offset": file_off, "error": "out_of_range"})
            continue

        data    = exe[file_off : file_off + size]
        l0_max  = max(data[: w * h])
        out_bin = OUT_DIR / f"{stem}.bin"
        out_bin.write_bytes(data)

        print(f"{i:>3}  {stem:<12}  {w:>3}  {h:>3}  {size:>6}  0x{ptr:08X}  0x{file_off:08X}  {l0_max:>6}")
        meta.append({
            "index": i, "stem": stem, "w": w, "h": h,
            "cpu_ptr": ptr, "file_offset": file_off,
            "size": size, "l0_max": l0_max,
        })
        dumped += 1

    (OUT_DIR / "index.json").write_text(json.dumps(meta, indent=2))
    print()
    print(f"Dumped {dumped} layout files + index.json to {OUT_DIR}/")


if __name__ == "__main__":
    main()
