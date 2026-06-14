from pathlib import Path
import json

from utils.types import GameVersion

X4_PSX_LAYOUT_DUMP_INFO_PATH = Path("PSX/X4/layouts/index.json")

# experimental code: load data from PSX layout table dump
load_x4_from_psx = True
if load_x4_from_psx and game_version == GameVersion.X4:
    print(r"Loading layout from PSX\X4\layouts ...")

    # OMP stems use "SCR" prefix; PSX layout stems use "ST" prefix
    # e.g. SCR00_00 → ST00_00
    psx_stem = omp_stem.replace('SCR', "ST")
    layout_bin_path = Path(f"PSX/X4/layouts/{psx_stem}.bin")

    if X4_PSX_LAYOUT_DUMP_INFO_PATH.exists() and layout_bin_path.exists():
        index_data = {e["stem"]: e for e in json.loads(X4_PSX_LAYOUT_DUMP_INFO_PATH.read_text())}
        layout_meta = index_data.get(psx_stem)
        if layout_meta:
            w, h = layout_meta["w"], layout_meta["h"]
            layout_entry = (layout_bin_path, w, h)
            print(f"  Found {psx_stem}  (w={w}, h={h})")
        else:
            print(f"  WARNING: {psx_stem} not found in index.json")


bin_path_or_offset, w, h = layout_entry

if load_x4_from_psx and game_version == GameVersion.X4:
    # load layout table from MMXLC exe
    print(f"  (bin={bin_path_or_offset}  w={w}  h={h})")
    print()
    print(f"Loading layout from {bin_path_or_offset.name} (layer {args.layer})...")
    layout_bytes = bin_path_or_offset.read_bytes()
    layout = LayoutTable.from_bytes(layout_bytes, w, h, layer=args.layer)
else:
    offset = bin_path_or_offset
    print(f"  (offset=0x{offset:08X}  w={w}  h={h})")
    print()
    print(f"Loading layout from RXC2.exe (layer {args.layer})...")
    layout = load_layout_from_exe(EXE_PATH, offset=offset, width=w, height=h, layer=args.layer)
