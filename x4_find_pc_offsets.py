"""
Search RXC1.exe (Mega Man X Legacy Collection 1 PC) for Mega Man X4 stage layout
data by binary-matching PSX layout layer-0 bytes against the PC executable.

Verification rule (same as X5 research in RXC2.exe):
  max(exe[offset : offset + w*h]) == n_screens − 1
  where n_screens = struct.unpack_from("<I", omp_data, 8)[0] // 256

Inputs:
  PSX/X4/layouts/*.bin          PSX layout dumps (from x4_extract_psx_layouts.py)
  PSX/X4/layouts/index.json     metadata: index, stem, w, h per stage
  PC/X4/stage/map/SCR*.omp      PC OMP files for n_screens verification
  RXC1.exe                      PC executable to search

Output: printed table; if 2+ verified hits, generates x4_pc_layout_offsets.py
"""

import json
import struct
from pathlib import Path

PC_EXE    = Path("RXC1.exe")
BIN_DIR   = Path("PSX/X4/layouts")
OMP_DIR   = Path("PC/X4/stage/map")
META_PATH = BIN_DIR / "index.json"
OUT_PY    = Path("x4_pc_mmxlc1_layout_offsets.py")

# Minimum layer-0 bytes to attempt a search (small needles get too many false positives)
MIN_SEARCH_BYTES = 50

# Main layout block start in RXC1.exe — hits below this are in a duplicate data region.
# Determined by the confirmed hit for ST00_00 (index 0 = block start).
MAIN_BLOCK_START = 0x00B60000

# Map layout stem → OMP filename stem for n_screens verification.
# OMP naming: SCR{HH}_{NN}[_eng].omp  where HH=hex stage number, NN=00 or 01
STEM_TO_OMP: dict[str, str] = {
    "ST00_00": "SCR00_00",   "ST00_01": "SCR00_01",
    "ST01_00": "SCR01_00",   "ST01_01": "SCR01_01",
    "ST02_00": "SCR02_00",   "ST02_01": "SCR02_01",
    "ST03_00": "SCR03_00",   "ST03_01": "SCR03_01",
    "ST04_00": "SCR04_00",   "ST04_01": "SCR04_01",
    "ST05_00": "SCR05_00",   "ST05_01": "SCR05_01",
    "ST06_00": "SCR06_00",   "ST06_01": "SCR06_01",
    "ST07_00": "SCR07_00",   "ST07_01": "SCR07_01",
    "ST08_00": "SCR08_00",   "ST08_01": "SCR08_01",
    "ST09_00": "SCR09_00",
    "ST0A_00": "SCR0A_00",
    "ST0B_00": "SCR0B_00",
    "ST0C_00": "SCR0C_00",   "ST0C_01": "SCR0C_01",
    "ST0D_00": "SCR0D_00",
    "STD_1U":  "SCR0D_01_eng",
    "ST0E_U0": "SCR0E_00",   "ST0E_U1": "SCR0E_01_eng",
    "ST0F_UX": "SCR0F_00_eng",
}


def omp_n_screens(path: Path) -> int | None:
    try:
        d = path.read_bytes()
        return struct.unpack_from("<I", d, 8)[0] // 256 if len(d) >= 12 else None
    except OSError:
        return None


def find_all(haystack: bytes, needle: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while (pos := haystack.find(needle, start)) != -1:
        hits.append(pos)
        start = pos + 1
    return hits


def main() -> None:
    print(f"Loading {PC_EXE} …")
    exe = PC_EXE.read_bytes()
    print(f"  {len(exe):,} bytes\n")

    if not META_PATH.exists():
        print(f"Missing {META_PATH} — run x4_extract_psx_layouts.py first.")
        return

    meta: list[dict] = json.loads(META_PATH.read_text())
    meta_by_stem = {m["stem"]: m for m in meta}

    # Build OMP n_screens lookup
    omp_n: dict[str, int] = {}
    for p in sorted(OMP_DIR.glob("*.omp")):
        n = omp_n_screens(p)
        if n is not None:
            omp_n[p.stem] = n
    print(f"OMP files loaded: {len(omp_n)}")
    for k, v in sorted(omp_n.items()):
        print(f"  {k}: n_screens={v}")
    print()

    # Sort so larger layer-0 (more unique) layouts are searched first
    bin_files = sorted(
        BIN_DIR.glob("*.bin"),
        key=lambda p: meta_by_stem.get(p.stem, {}).get("w", 0)
                    * meta_by_stem.get(p.stem, {}).get("h", 0),
        reverse=True,
    )

    header = (f"{'Stem':<14}  {'W':>3}×{'H':<3}  {'L0 bytes':>8}  "
              f"{'Hits':>5}  {'PC offset':>12}  {'n_scrn':>6}  {'L0 max':>6}  Verified")
    print(header)
    print("-" * len(header))

    verified_offsets: dict[str, dict] = {}

    for bin_path in bin_files:
        stem = bin_path.stem
        m = meta_by_stem.get(stem, {})
        w = m.get("w", 0)
        h = m.get("h", 0)
        if w == 0 or h == 0:
            continue

        data   = bin_path.read_bytes()
        layer0 = data[: w * h]
        l0_max = max(layer0)

        if len(layer0) < MIN_SEARCH_BYTES:
            omp_stem  = STEM_TO_OMP.get(stem)
            n_screens = omp_n.get(omp_stem) if omp_stem else None
            n_str = str(n_screens) if n_screens is not None else "  ?"
            print(f"{stem:<14}  {w:>3}×{h:<3}  {w*h:>8}  {'---':>5}  "
                  f"{'(too small)':>12}  {n_str:>6}  {l0_max:>6}  ---")
            continue

        omp_stem  = STEM_TO_OMP.get(stem)
        n_screens = omp_n.get(omp_stem) if omp_stem else None
        hits      = find_all(exe, bytes(layer0))

        # Prefer the hit in the main block (>= MAIN_BLOCK_START) when multiple hits exist.
        # Hits below MAIN_BLOCK_START are in a duplicate data region.
        main_hits = [h for h in hits if h >= MAIN_BLOCK_START]
        chosen_hits = main_hits if main_hits else hits

        verified    = False
        compatible  = False  # hit found, L0_max < n_screens (PC OMP was expanded)
        hit_off     = None
        for h_off in chosen_hits:
            pc_l0 = exe[h_off : h_off + w * h]
            pc_max = max(pc_l0)
            if n_screens is not None and pc_max == n_screens - 1:
                verified = True
                hit_off  = h_off
                verified_offsets[stem] = {
                    "pc_offset": h_off, "w": w, "h": h,
                    "n_screens": n_screens, "verified": True,
                }
                break
            elif n_screens is not None and pc_max < n_screens - 1 and hit_off is None:
                compatible = True
                hit_off    = h_off
                verified_offsets[stem] = {
                    "pc_offset": h_off, "w": w, "h": h,
                    "n_screens": n_screens, "verified": False,
                }
        if hit_off is None and chosen_hits:
            hit_off = chosen_hits[0]

        n_str   = str(n_screens) if n_screens is not None else "  ?"
        ver_str = "YES" if verified else ("compat" if compatible else ("no" if hits else "---"))
        off_str = f"0x{hit_off:08X}" if hit_off is not None else "  (not found)"
        dups    = f" (+{len(hits)-1} dup)" if len(hits) > 1 else ""
        print(f"{stem:<14}  {w:>3}×{h:<3}  {w*h:>8}  {len(hits):>5}  "
              f"{off_str:>12}{dups:<8}  {n_str:>6}  {l0_max:>6}  {ver_str}")

    print()
    strict   = {s: v for s, v in verified_offsets.items() if v.get('verified')}
    compat   = {s: v for s, v in verified_offsets.items() if not v.get('verified')}
    print(f"Strictly verified (max == n_screens-1): {len(strict)}")
    for stem, info in sorted(strict.items()):
        print(f"  {stem}: 0x{info['pc_offset']:08X}  ({info['w']}×{info['h']}, "
              f"n_screens={info['n_screens']})")
    print(f"Compatible (max < n_screens, PC OMP expanded): {len(compat)}")
    for stem, info in sorted(compat.items()):
        print(f"  {stem}: 0x{info['pc_offset']:08X}  ({info['w']}×{info['h']}, "
              f"n_screens={info['n_screens']})")

    if len(strict) + len(compat) >= 2:
        _write_output_py(strict, compat)
    else:
        print(f"\nNeed at least 2 confirmed hits to generate {OUT_PY}.")


def _write_output_py(strict: dict[str, dict], compat: dict[str, dict]) -> None:
    lines = [
        '"""',
        "Mega Man X4 stage layout offsets in RXC1.exe (Mega Man X Legacy Collection 1 PC).",
        "Each offset points to the first byte of layer 0 (the foreground layer).",
        "Full layout block = w * h * 3 bytes (3 consecutive layers, each w*h screen IDs).",
        "",
        "Verification levels:",
        "  verified  — max(exe[pc_offset : pc_offset + w*h]) == n_screens - 1",
        "  compat    — exact PSX bytes found in PC exe; PC OMP has more screens",
        "              (Legacy Collection expanded the OMP but kept the same layout data)",
        "",
        "n_screens comes from PC/X4/stage/map/SCR*.omp (uint32LE @ byte 8 // 256)",
        '"""',
        "",
        "# fmt: off",
        "X4_LAYOUT_OFFSETS: dict[str, dict] = {",
    ]
    for stem in sorted(strict):
        info = strict[stem]
        lines.append(
            f'    "{stem}": {{"pc_offset": 0x{info["pc_offset"]:08X}, '
            f'"w": {info["w"]}, "h": {info["h"]}, '
            f'"n_screens": {info["n_screens"]}}},  # verified'
        )
    for stem in sorted(compat):
        info = compat[stem]
        lines.append(
            f'    "{stem}": {{"pc_offset": 0x{info["pc_offset"]:08X}, '
            f'"w": {info["w"]}, "h": {info["h"]}, '
            f'"n_screens": {info["n_screens"]}}},  # compat (PC OMP expanded)'
        )
    lines += [
        "}",
        "# fmt: on",
        "",
        "# Block byte size per stage = w * h * 3  (layer0 + layer1 + layer2)",
    ]

    OUT_PY.write_text("\n".join(lines) + "\n")
    print(f"\nSaved {OUT_PY}")


if __name__ == "__main__":
    main()
