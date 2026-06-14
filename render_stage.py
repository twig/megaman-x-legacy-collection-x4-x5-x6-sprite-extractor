"""
Generalised stage renderer for Mega Man X4 (RXC1.exe, MMLC1 PC), X5 and X6 (RXC2.exe, MMLC2 PC).

Usage:
    python render_stage.py <path/to/stXXX.omp>

Outputs (written to current working directory):
    {stem}_catalog.png  — raw OMP screen catalog (skipped with --skip-catalog)
    {stem}_level.png    — full level render using Layer 0 (only when layout is known; skipped with --skip-stage)

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
  palette groups.  Per-stage COL file selection is unresolved; col/stage/ contains
  per-stage files (st0_0.col … stm_0.col) whose mapping to OMP stems is unknown.
"""

import argparse
import sys
import csv
from pathlib import Path

from PIL import ImageDraw, ImageFont

from utils.omp import load_omp, render_level, render_omp, load_layout_from_exe, LayerPreset, LayoutTable
from utils.ocl import load_ocl, OclPaletteGroup
from utils.tex import load_tex
from utils.palette import load_col_palettes
from utils.types import GameVersion

# Paths
EXE_PATH = Path("RXC2.exe")

# Stage layout
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
    # DONE = accurate render of stage (offset and dimensions look correct)
    # ALMOST = tiles and layout complete, offset/dimensions not quite right
    # IN RANGE = we got some tiles and layout data
    # --- presentable
    # st000 uses a dedicated second copy of the layout at 0x02EC2D4B.
    # Verified by 4 anchor points from omp-to-expected-tiles-x5.csv.
    "st000": (0x02EC2D4B, 15, 24),  # ALMOST (Intro Stage all)
    # "st000": (0x02EC2D78, 15, 17),  # ALMOST (Intro Stage - part 1 flat)
    # "st000": (0x02EC2D5F, 4, 3),  # ALMOST (Intro Stage - part 2 tower)

    "st010": (0x02D98528, 39, 8),  # DONE (Crescent Grizzly)

    "st020": (0x02D9A407, 32, 5), # ALMOST (Dark Necrobat: Area 1)
    "st021": (0x02D9A404, 25, 6), # ALMOST (Dark Necrobat: Area 2)

    "st030": (0x02D9A407, 22, 15),  # ALMOST (Tidal Whale)

    "st040": (0x02D9A3DE, 23, 10), # ALMOST (Burn Dinorex: Area 1)
    "st041": (0x02D9A3DE, 24, 10), # ALMOST (Burn Dinorex: Area 2)

    "st050": (0x02D99508, 44, 7), # ALMOST (Volt Kraken)

    "st060": (0x02D992B3, 29, 15), # ALMOST (Shining Firefly: Area 1)
    "st061": (0x02D9A690, 21, 17), # ALMOST (Shining Firefly: Area 2)

    "st070": (0x02D98548, 24, 14), # IN RANGE (Spike Rosered)

    "st080": (0x02D99A7D, 19, 13), # IN RANGE (Spiral Pegasus)

    "st090_00": (0x02D98697, 2, 3),  # DONE (Dynamo: Enigma Cannon)
    "st090_01": (0x02D98697, 2, 3),  # DONE (Dynamo: Hunter Base 1)
    "st100_00": (0x02D9852F, 2, 4),  # DONE (Dynamo: Space Shuttle)
    "st100_01": (0x02D98697, 2, 3),  # DONE (Dynamo: Hunter Base 2)

    "st160": (0x02D98524, 12, 16), # ALMOST (Zero Space 1: Origin)
    "st170": (0x02D99CBA, 20, 17), # ALMOST (Zero Space 2: Grief)
    "st180": (0x02D99CBA, 19, 24), # ALMOST (Zero Space 3: Awakening)
    "st120": (0x02D9979F, 27, 19), # ALMOST (Zero Space 4: Birth)

    "st130":    (0x02D9869C, 6, 3),  # DONE (Stage Select)
    "st220": (0x02D99F7D, 9, 11), # ALMOST (Training Area)

    "staff_eng": (0x02D9852F, 9, 6), # DONE (End Credits)
    "st140_eng": (0x02D98695, 2, 1), # DONE (Title screen)
    "st141_eng": (0x02D98695, 2, 1), # DONE (Player Select screen)
    "st150": (0x02D98695, 2, 1), # DONE (Gameplay Report screen)
}


# ── Debug overlay helpers ─────────────────────────────────────────────────────

_DEBUG_LINE  = (255, 220, 0, 210)   # yellow-ish grid lines
_DEBUG_TEXT  = (255, 220, 0, 255)   # yellow text
_DEBUG_TEXTBG = (0, 0, 0, 170)      # semi-transparent black text background


def _debug_overlay_catalog(img, n_screens: int, tile_size: int = 16) -> None:
    """Draw per-screen boundary lines and screen-id labels on the catalog image."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default()
    for sid in range(n_screens):
        y = sid * tile_size
        draw.line([(0, y), (img.width - 1, y)], fill=_DEBUG_LINE, width=1)
        label = f"scr {sid}"
        tw = len(label) * 6 + 2
        draw.rectangle([0, y, tw, y + 9], fill=_DEBUG_TEXTBG)
        draw.text((1, y), label, fill=_DEBUG_TEXT, font=font)


def _debug_overlay_level(
    img,
    layout: LayoutTable,
    level_width_screens: int,
    level_height_screens: int,
    tile_size: int = 16,
) -> None:
    """Draw screen boundary grid lines and (sx,sy)/id labels on the level image."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default()
    screen_px = 16 * tile_size  # pixels per screen edge

    # Grid lines
    for sx in range(level_width_screens + 1):
        x = sx * screen_px
        draw.line([(x, 0), (x, img.height - 1)], fill=_DEBUG_LINE, width=1)
    for sy in range(level_height_screens + 1):
        y = sy * screen_px
        draw.line([(0, y), (img.width - 1, y)], fill=_DEBUG_LINE, width=1)

    # Per-screen labels
    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            screen_id = layout.get(sx, sy)
            px = sx * screen_px + 2
            py = sy * screen_px + 2
            sid_str = str(screen_id) if screen_id is not None else "?"
            lines = [f"Screen ({sx},{sy}), ID #{sid_str}"]
            tw = max(len(l) for l in lines) * 6 + 2
            draw.rectangle([px - 1, py - 1, px + tw, py + 19], fill=_DEBUG_TEXTBG)
            for i, line in enumerate(lines):
                draw.text((px, py + i * 10), line, fill=_DEBUG_TEXT, font=font)


def get_game_files(game_version: GameVersion, omp_path: Path):
    omp_filename = omp_path.name
    found_row = None

    # headers: game, stage, col, col_animate, ocl, tex, tex256, texch3
    with open('game-files.csv', 'r') as csvfile:
        reader = csv.reader(csvfile)

        for row in reader:
            if row[0] == str(game_version) and str(row[1]).endswith(omp_filename):
                found_row = row
                break

    if not found_row:
        return None

    [game, stage, col, col_animate, ocl, tex, tex256, texch3] = found_row

    return [
        Path(f".\\PC\\X{game_version}\\{ocl}"),
        Path(f".\\PC\\X{game_version}\\{tex}"),
        Path(f".\\PC\\X{game_version}\\{tex256}") if tex256 else None,
        Path(f".\\PC\\X{game_version}\\{col}"),
        Path(f".\\PC\\X{game_version}\\{col_animate}") if col_animate else None,
    ]

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a stage OMP to PNG (level + catalog)."
    )
    parser.add_argument("omp_file", type=Path, help="Path to the .omp file")
    parser.add_argument(
        "--layer", type=int, default=0, choices=[0, 1, 2],
        help="Layout layer to render (0=foreground, 1=BG1, 2=BG2; default: 0)",
    )
    parser.add_argument(
        "--skip-stage", action="store_true",
        help="Only produce the catalog PNG, skip level render",
    )
    parser.add_argument(
        "--skip-catalog", action="store_true",
        help="Skip catalog PNG generation",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Directory to save output images (default: current working directory)",
        default=Path.cwd(),
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Overlay screen/layer boundaries and (sx,sy)/screen-id labels on output images",
    )
    args = parser.parse_args()

    omp_path: Path = args.omp_file.resolve()
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    omp_stem = omp_path.stem
    [omp, ocl, tex, tex_background, flags_to_palette] = preload_related_files(omp_path)

    # Catalog render
    if not args.skip_catalog:
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
        if args.debug:
            _debug_overlay_catalog(catalog_img, omp.n_screens)
        catalog_out = output_dir / f"{omp_stem}_catalog.png"
        catalog_img.save(catalog_out)
        print(f"  Saved {catalog_out}  ({catalog_img.width}×{catalog_img.height} px)")

    layout_entry = STAGE_LAYOUT.get(omp_stem)

    # Level render (when layout is known and not suppressed)
    if layout_entry and not args.skip_stage:
        offset, w, h = layout_entry
        print(f"  (offset=0x{offset:08X}  w={w}  h={h})")
        print()

        print()
        print(f"Loading layout from RXC2.exe (layer {args.layer})...")
        layout = load_layout_from_exe(EXE_PATH, offset=offset, width=w, height=h, layer=args.layer)

        #---
        # offset = 2486
        # w = 24
        # h = 8

        # exe_path = Path('layouts_rxc2.bin')
        # layer_size = w * h
        # total_size = layer_size * 3
        # data = exe_path.read_bytes()
        # if offset + total_size > len(data):
        #     raise ValueError(
        #         f"EXE too small for layout at {hex(offset)}: "
        #         f"need {total_size} bytes, file has {len(data) - offset}"
        #     )
        # layout_bytes = data[offset : offset + total_size]
        # layout = LayoutTable.from_bytes(layout_bytes, w, h, args.layer)
        # print(f"total size {total_size} > {offset+total_size}")
        #---

        n_sx = len(layout.screens[0]) if layout.screens else 0
        n_sy = len(layout.screens)
        print(f"  {n_sx} screens wide × {n_sy} screens tall")

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
        if args.debug:
            _debug_overlay_level(level_img, layout, n_sx, n_sy)
        level_out = output_dir / Path(f"{omp_stem}_level.png")
        level_img.save(level_out)
        print(f"  Saved {level_out}  ({level_img.width}×{level_img.height} px)")


def preload_related_files(omp_path: Path):
    if not omp_path.exists():
        raise FileNotFoundError(f"ERROR: OMP file not found: {omp_path}")

    omp_stem = omp_path.stem

    # Validate magic
    raw_magic = omp_path.read_bytes()[:4]
    if raw_magic != b"OMP\x00":
        raise ValueError(f"ERROR: Not an OMP file (bad magic {raw_magic!r}): {omp_path}")

    game_version = None

    if 'X4' in str(omp_path):
        game_version = GameVersion.X4
    elif 'X5' in str(omp_path):
        game_version = GameVersion.X5
    elif 'X6' in str(omp_path):
        game_version = GameVersion.X6
    else:
        raise ValueError(f"ERROR: Cant determine which game the OMP is from")

    game_files = get_game_files(game_version, omp_path)

    if game_files is None:
        raise ValueError(f"ERROR: No file mapping for {omp_stem} in game-files.csv")

    ocl_path, tex_path, tex_bg_path, col_path, col_path_animated = game_files

    for p in (ocl_path, tex_path):
        if not p.exists():
            raise FileNotFoundError(f"ERROR: Required sibling file not found: {p}")
    if not EXE_PATH.exists():
        raise FileNotFoundError(f"ERROR: RXC2.exe not found at {EXE_PATH} (run from workspace root)")
    if not col_path.exists():
        raise FileNotFoundError(f"ERROR: COL palette not found at {col_path}")

    print(f"Stage:  {omp_stem}")
    print(f"OMP:    {omp_path}")
    print(f"OCL:    {ocl_path}")
    print(f"TEX:    {tex_path}")
    print(f"TEX BG: {tex_bg_path}")
    print(f"COL:    {col_path}")
    print(f"COL_A:  {col_path_animated}")

    # Load assets
    print("Loading OMP...")
    omp = load_omp(omp_path)
    print(f"  n_screens={omp.n_screens}")

    print("Loading OCL...")
    ocl = load_ocl(ocl_path)
    print(f"  n_entries={len(ocl)}")

    print("Loading TEX...")
    tex = load_tex(tex_path)
    # tex_foreground = load_tex(tex_fg_path)
    if tex_bg_path and tex_bg_path.exists():
        tex_background = load_tex(tex_bg_path)
    else:
        print(f"  WARNING: background TEX not found at {tex_bg_path}, using main TEX as fallback.")
        tex_background = tex

    print(f"  width={tex['width']}  height={tex['height']}  format={tex.get('format')}")

    print("Loading COL palette...")
    col = load_col_palettes(col_path)
    print(f"  {col_path.name}  ({type(col).__name__})")

    # OclPaletteGroup.ANIMATED_CRYSTAL (tile_type=0x39) tiles use st0_0.col in X5,
    # but all groups currently map to col00_0x.col pending per-stage COL resolution.
    # In a combined render, crystal placeholder tiles (tile_type=0x39, col=0) are
    # suppressed inside omp.py; the background layer shows through instead.
    if col_path_animated and col_path_animated.exists():
        anim_col = load_col_palettes(col_path_animated)
        # print(f"  {col_path_animated.name}  ({len(anim_col)//16} CLUTs, animated tiles)")
    else:
        print(f"  WARNING: animated COL palette not found at {col_path_animated}, using static palette as fallback.")
        anim_col = None

    # OclEntry.palette_group() maps any unregistered collision type to STANDARD,
    # so all tiles are rendered even if their tile_type is not listed above.
    flags_to_palette = {
        OclPaletteGroup.STANDARD:         col,
        OclPaletteGroup.ALT_PALETTE:      col,
        OclPaletteGroup.ANIMATED_CRYSTAL: col,
        OclPaletteGroup.ALT_AREA:         col,
    }

    return [omp, ocl, tex, tex_background, flags_to_palette]


if __name__ == "__main__":
    main()
