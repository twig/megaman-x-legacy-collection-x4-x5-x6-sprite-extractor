"""
Generalised stage renderer for Mega Man X5 (RXC2.exe, MMLC2 PC).

Usage:
    python render_stage.py <path/to/stXXX.omp>

Outputs (written to current working directory):
    {stem}_catalog.png  — raw OMP screen catalog (always produced)
    {stem}_level.png    — full level render using Layer 0 (only when layout is known)

The script derives the OCL and TEX files from the same directory as the OMP.
Layout parameters are looked up from the STAGE_LAYOUT table below, which is
populated from confirmed research into RXC2.exe.  If a stage is absent from the
table the level render is skipped and only the catalog is saved.

== STAGE_LAYOUT status codes ==

  CONFIRMED   — exe file offset verified by exact max(layer0) == n_screens-1
                match against the corresponding OMP, or by 4-point anchor check.

  UNCONFIRMED — offset and dimensions are plausible (layout data is valid for the
                stage group), but the exact per-OMP mapping within block 2 has
                not been verified individually.

  (absent)    — no layout identified yet; catalog-only output produced.

== Unresolved stages (absent from STAGE_LAYOUT) ==

  Block 1 stages whose layout index has not been matched to an OMP:
    st001, st002, st009, st011, st012, st014, st015, st016, st017,
    st020, st021, st022, st023, st024, st025, st027
  OMP files with no block 1 layout match yet:
    st020, st021, st040, st041, st050, st060, st070, st080,
    st170, st180, st220, staff_eng
  Cutscene/ending stages (no layout found anywhere in exe):
    st140_eng, st141_eng, st150

  To resolve these, run debug/verify_x5_heights_omp.py — it cross-references
  every block 1 layout stage against all OMP n_screens values.

== Block 2 boss stages ==

  COPY2_OFFSET = 0x02D9B9A4 (.rdata), SIZE_TABLE_2 = 0x02E8DF71 (.data).
  Stage idx 0 (8×29, max=8) is valid for the group {st090_00, st090_01,
  st100_00, st100_01, st130}.  The exact per-OMP index within block 2 has
  not been individually verified, so these entries are UNCONFIRMED.

== COL palette ==

  All stages currently use col00_0x.col as the default palette for all OCL
  flag values.  Per-stage COL file selection is unresolved; col/stage/ contains
  per-stage files (st0_0.col … stm_0.col) whose mapping to OMP stems is unknown.
"""

import argparse
import sys
from pathlib import Path

from utils.omp import load_omp, render_level, render_omp, load_layout_from_exe, LayerPreset
from utils.ocl import load_ocl
from utils.tex import load_tex
from utils.palette import load_col_palettes

# ── Paths ─────────────────────────────────────────────────────────────────────
EXE_PATH = Path("RXC2.exe")
COL_PATH = Path("PC/X5/col/stage/col00_0x.col")  # default for all stages (unresolved per-stage)
ANIM_COL_PATH = Path("PC/X5/col/stage/st0_0.col")  # animated-tile palette (flag=0x39, e.g. crystals)

# ── STAGE_LAYOUT ──────────────────────────────────────────────────────────────
# Maps OMP stem → (exe_file_offset, width_screens, height_screens)
#
# exe_file_offset : byte offset in RXC2.exe of the first layout byte (layer 0)
# width_screens   : number of screens per row (W in the size table)
# height_screens  : number of screen rows     (H in the size table)
#
# The layout block stores 3 consecutive layers, each W×H bytes.
# load_layout_from_exe() reads all 3 layers and returns the requested layer.
#
# Block 1 size table: SIZE_TABLE_OFF = 0x02F0B7BD
# Block 1 data start: COPY1_OFFSET   = 0x02D98548  (ends at 0x02D9BAA9, 13665 bytes)
# Block 2 data start: COPY2_OFFSET   = 0x02D9B9A4  (overlaps last 261 bytes of block 1)
# Block 2 size table: SIZE_TABLE_2   = 0x02E8DF71  (4-byte entries: w, h, f1, f2)

STAGE_LAYOUT: dict[str, tuple[int, int, int]] = {
    # ── Block 1 — CONFIRMED ──────────────────────────────────────────────────
    # st000 uses a dedicated second copy of the layout at 0x02EC2D4B.
    # Verified by 4 anchor points from omp-to-expected-tiles.csv.
    "st000": (0x02EC2D4B, 15, 24),  # CONFIRMED — 4-anchor verified (Intro Stage)

    # Block 1 idx 0  (15×24): max(layer0) == 97  → st010 n_screens=98
    "st010": (0x02D98548, 15, 24),  # CONFIRMED — block 1 idx 0, exact max match (Crescent Grizzly)

    # Block 1 idx 8  (5×29):  max(layer0) == 109 → st030/st160 n_screens=110
    "st030": (0x02D98F7A,  5, 29),  # CONFIRMED — block 1 idx 8, exact max match (Tidal Whale)
    "st160": (0x02D98F7A,  5, 29),  # CONFIRMED — block 1 idx 8, shared layout with st030 (Zero Space 1: Origin)

    # Block 1 idx 10 (5×29):  max(layer0) == 164 → st061 n_screens=165
    "st061": (0x02D992B3,  5, 29),  # CONFIRMED — block 1 idx 10, exact max match (Shining Firefly: Area 2)

    # Block 1 idx 13 (5×26):  max(layer0) == 208 → st120 n_screens=209
    "st120": (0x02D9979F,  5, 26),  # CONFIRMED — block 1 idx 13, exact max match (Zero Space 4: Birth)

    # ── Block 2 — UNCONFIRMED ────────────────────────────────────────────────
    # COPY2 = 0x02D9B9A4, stage idx 0 (8×29), max=8.
    # Valid for the group: st090_00/01, st100_00/01, st130 (all n_screens=9 or 16,
    # max 8 ≤ n_screens-1).  The exact per-OMP index within block 2 has not been
    # individually verified.
    "st090_00": (0x02D9B9A4, 8, 29),  # UNCONFIRMED — block 2 idx 0 (8×29), group valid (Dynamo: Enigma Cannon)
    "st090_01": (0x02D9B9A4, 8, 29),  # UNCONFIRMED — block 2 idx 0 (8×29), group valid (Dynamo: Hunter Base 1)
    "st100_00": (0x02D9B9A4, 8, 29),  # UNCONFIRMED — block 2 idx 0 (8×29), group valid (Dynamo: Space Shuttle)
    "st100_01": (0x02D9B9A4, 8, 29),  # UNCONFIRMED — block 2 idx 0 (8×29), group valid (Dynamo: Hunter Base 2)
    "st130":    (0x02D9B9A4, 8, 29),  # UNCONFIRMED — block 2 idx 0 (8×29), group valid (Stage Select)

    # ── To add when resolved ─────────────────────────────────────────────────
    # Block 1 unverified stages (index, offset, dimensions from layouts/index.txt):
    #   idx  1  (10×25)  0x02D98980 — unverified
    #   idx  2  (10×26)  0x02D98C6E — unverified
    #   idx  9  (5×26)   0x02D9912D — unverified
    #   idx 11  (5×26)   0x02D99466 — unverified
    #   idx 12  (5×29)   0x02D995EC — unverified
    #   idx 14  (5×29)   0x02D99925 — unverified
    #   idx 15  (5×28)   0x02D99AD8 — unverified
    #   idx 16  (5×27)   0x02D99C7C — unverified
    #   idx 17  (5×26)   0x02D99E11 — unverified
    #   idx 20  (5×25)   0x02D99F97 — unverified
    #   idx 21  (10×24)  0x02D9A10E — unverified
    #   idx 22  (10×23)  0x02D9A3DE — unverified
    #   idx 23  (15×22)  0x02D9A690 — unverified
    #   idx 24  (20×21)  0x02D9AA6E — unverified
    #   idx 25  (20×20)  0x02D9AF5A — unverified
    #   idx 27  (5×18)   0x02D9B99B — unverified
    # Unmatched OMP files awaiting slot assignment (run debug/verify_x5_heights_omp.py):
    #   st020  Dark Necrobat: Area 1
    #   st021  Dark Necrobat: Area 2
    #   st040  Burn Dinorex: Area 1
    #   st041  Burn Dinorex: Area 2
    #   st050  Volt Kraken
    #   st060  Shining Firefly: Area 1
    #   st070  Spike Rosered
    #   st080  Spiral Pegasus
    #   st170  Zero Space 2: Grief
    #   st180  Zero Space 3: Awakening
    #   st220  Training Area
    #   staff_eng  End Credits
}

# Status strings for reporting
_CONFIRMED_STEMS = {"st000", "st010", "st030", "st160", "st061", "st120"}


def _layout_status(stem: str) -> str:
    if stem in _CONFIRMED_STEMS:
        return "CONFIRMED"
    if stem in STAGE_LAYOUT:
        return "UNCONFIRMED"
    return "UNKNOWN"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an X5 stage OMP to PNG (level + catalog)."
    )
    parser.add_argument("omp_file", type=Path, help="Path to the .omp file")
    parser.add_argument(
        "--layer", type=int, default=0, choices=[0, 1, 2],
        help="Layout layer to render (0=foreground, 1=BG1, 2=BG2; default: 0)",
    )
    parser.add_argument(
        "--catalog-only", action="store_true",
        help="Only produce the catalog PNG, skip level render",
    )
    args = parser.parse_args()

    omp_path: Path = args.omp_file.resolve()
    if not omp_path.exists():
        sys.exit(f"ERROR: OMP file not found: {omp_path}")

    stem = omp_path.stem

    # Validate magic
    raw_magic = omp_path.read_bytes()[:4]
    if raw_magic != b"OMP\x00":
        sys.exit(f"ERROR: Not an OMP file (bad magic {raw_magic!r}): {omp_path}")

    if 'X5' in str(omp_path):
        stage_dir = omp_path.parent
        ocl_path = stage_dir / f"{stem}.ocl"
        tex_path = stage_dir / f"{stem}.tex"
        # tex_fg_path = stage_dir.parent / f"{stem}_ch3" / f"{stem}_ch3.tex"
        tex_bg_path = stage_dir.parent / f"{stem}_chr256" / f"{stem}_chr256.tex"
    elif 'X6' in str(omp_path):
        stage_dir = omp_path.parent
        ocl_path = stage_dir.parent / 'cel' / f"{stem}.ocl"
        tex_path = stage_dir.parent / 'dds' / f"{stem}.tex"
        tex_bg_path = tex_path.with_stem(f"{stem}_chr256")
        # tex_fg_path = tex_bg_path # missing??? stage_dir.parent / "f{stem}_ch3" / "f{stem}_ch3.tex"
    else:
        sys.exit(f"ERROR: Cant determine which game the OMP is from")

    for p in (ocl_path, tex_path, tex_bg_path):
        if not p.exists():
            sys.exit(f"ERROR: Required sibling file not found: {p}")
    if not EXE_PATH.exists():
        sys.exit(f"ERROR: RXC2.exe not found at {EXE_PATH} (run from workspace root)")
    if not COL_PATH.exists():
        sys.exit(f"ERROR: COL palette not found at {COL_PATH}")

    status = _layout_status(stem)
    layout_entry = STAGE_LAYOUT.get(stem)

    print(f"Stage:  {stem}")
    print(f"OMP:    {omp_path}")
    print(f"Layout: {status}", end="")
    if layout_entry:
        offset, w, h = layout_entry
        print(f"  (offset=0x{offset:08X}  w={w}  h={h})")
    else:
        print("  (no layout — catalog only)")
    print()

    # ── Load assets ───────────────────────────────────────────────────────────
    print("Loading OMP...")
    omp = load_omp(omp_path)
    print(f"  n_screens={omp.n_screens}")

    print("Loading OCL...")
    ocl = load_ocl(ocl_path)
    print(f"  n_entries={len(ocl)}")

    print("Loading TEX...")
    tex = load_tex(tex_path)
    # tex_foreground = load_tex(tex_fg_path)
    tex_background = load_tex(tex_bg_path)
    print(f"  width={tex['width']}  height={tex['height']}  format={tex.get('format')}")

    print("Loading COL palette...")
    col = load_col_palettes(COL_PATH)
    print(f"  {COL_PATH.name}  ({type(col).__name__})")

    # animated-tile palette: flag=0x39 tiles (crystals/energy orbs) use st0_0.col
    # with abs_clut=col (no +64 offset).  In a combined render these tiles are
    # typically invisible in the foreground because the background layer shows
    # through.  We still load the palette so the catalog render shows them.
    anim_col = load_col_palettes(ANIM_COL_PATH)
    print(f"  {ANIM_COL_PATH.name}  ({len(anim_col)//16} CLUTs, animated tiles)")

    flags_to_palette = {0x00: col, 0x38: col, 0x39: col, 0x3B: col}
    # Note: flag=0x39 uses col00_0x.col (same as 0x00/0x38) with abs_clut=col+64.
    # Sky-fill crystal tiles (OCL index 1, col==0) are suppressed inside omp.py.

    # ── Catalog render (always) ───────────────────────────────────────────────
    print()
    print("Rendering OMP catalog...")
    catalog_img = render_omp(
        omp,
        ocl,
        tex,
        # tex_foreground,
        tex_background,
        flags_to_palette=flags_to_palette,
        preset=LayerPreset.MAIN,
    )
    catalog_out = Path(f"{stem}_catalog.png")
    catalog_img.save(catalog_out)
    print(f"  Saved {catalog_out}  ({catalog_img.width}×{catalog_img.height} px)")

    # ── Level render (when layout is known and not suppressed) ────────────────
    if layout_entry and not args.catalog_only:
        offset, w, h = layout_entry

        print()
        print(f"Loading layout from RXC2.exe (layer {args.layer})...")
        layout = load_layout_from_exe(EXE_PATH, offset=offset, width=w, height=h, layer=args.layer)
        n_sx = len(layout.screens[0]) if layout.screens else 0
        n_sy = len(layout.screens)
        print(f"  {n_sx} screens wide × {n_sy} screens tall")
        if status == "UNCONFIRMED":
            print(f"  WARNING: layout offset is UNCONFIRMED for {stem}; visual result may be incorrect.")

        print()
        print("Rendering full level...")
        level_img = render_level(
            omp,
            ocl,
            layout,
            level_width_screens=n_sx,
            level_height_screens=n_sy,
            tex=tex,
            tex_bg=tex_background,
            # tex_fg=tex_foreground,
            flags_to_palette=flags_to_palette,
        )
        level_out = Path(f"{stem}_level.png")
        level_img.save(level_out)
        print(f"  Saved {level_out}  ({level_img.width}×{level_img.height} px)")

    elif not layout_entry:
        print()
        print(f"  Skipping level render: no layout entry for '{stem}'.")
        print("  To add one, update STAGE_LAYOUT in render_stage.py.")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
