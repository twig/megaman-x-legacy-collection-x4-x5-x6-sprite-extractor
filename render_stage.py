"""
Generalised stage renderer for Mega Man X4 (MMLC1 PC), X5 and X6 (MMLC2 PC).

Usage:
    python render_stage.py <path/to/stXXX.omp>

Outputs (to current working directory):
    {stem}_level.png    -- full level render, all 3 layers as-is (only when layout is known; skip with --skip-stage)
    {stem}_composed.png -- full level render, all 3 layers stacked (with --composed)
    {stem}_catalog.png  -- raw OMP screen catalog (skipped by default with --skip-catalog)

The script derives the OCL and TEX files from `game-files.csv`.
Layout parameters are looked up from the STAGE_LAYOUT table below.  If a stage is
absent from the table the level render is skipped and only the catalog is rendered.

== Block 2 stages ==

  COPY2_OFFSET = 0x02D9B9A4 (.rdata), SIZE_TABLE_2 = 0x02E8DF71 (.data).
  The X5 group {st090_00, st090_01, st100_00, st100_01, st130} draws from block 2.

== COL palette ==

  All stages currently use col*.col as the default palette for all OCL
  palette groups.  Most stages also have a secondary st*.col palette.
"""

import argparse
import csv
from pathlib import Path

from PIL import ImageChops, Image
from PIL.Image import Image as PILImage

from utils.consts import COMPOSED_ORDER_BASIC, COMPOSED_ORDER_REVERSED, EXE_PATH_LC1, EXE_PATH_LC2, CLUT_COLORS_PER_ROW
from utils.omp import load_omp, render_level, render_omp, load_layout_from_exe
from utils.ocl import load_ocl, OclPaletteGroup
from utils.tex import load_tex
from utils.palette import load_col_palettes, normalize_x6_stage_palette, x6_palette_is_vram_snapshot
from utils.types import GameVersion
from utils.fixes_common import CLUT_ANIM_STILL_FRAMES
from utils.fixes_x5 import build_x5_chr256_bg_override, build_x5_sheet_override, build_x5_pg8_empty_bg_override, build_x5_clut_row_override, x5_additive_water
from utils.fixes_x6 import build_x6_chr256_override, build_x6_padhi_clut_override, build_x6_clut_row_override
from utils.debug import debug_overlay_catalog, debug_overlay_level
from x4_pc_mmxlc1_layout_offsets import X4_LAYOUT_OFFSETS


# Stage layout maps OMP stem -> (exe_file_offset, width_screens, height_screens)
#
# exe_file_offset : byte offset in RXC*.exe of the first layout byte (layer 0)
# width_screens   : number of screens per row (W in the size table)
# height_screens  : number of screen rows     (H in the size table of all 3 layers)
#
# The layout block stores 3 consecutive layers, each WxH bytes.
# load_layout_from_exe() reads all 3 layers and returns the requested layer.
#
# Block 1 size table: SIZE_TABLE_OFF = 0x02F0B7BD
# Block 1 data start: COPY1_OFFSET   = 0x02D98548  (ends at 0x02D9BAA9, 13665 bytes)
# Block 2 data start: COPY2_OFFSET   = 0x02D9B9A4  (overlaps last 261 bytes of block 1)
# Block 2 size table: SIZE_TABLE_2   = 0x02E8DF71  (4-byte entries: w, h, f1, f2)

STAGE_LAYOUT: dict[str,dict[str, tuple[int, int, int]]] = {
    # SCR01_01 (Web Spider Area 2) LAYOUT ALMOST, TILES DONE
    "X4": dict([
        (key, (
        data["pc_offset"], data["w"],  data["h"] * 3))
        for key, data
        in X4_LAYOUT_OFFSETS.items()
    ]),
    "X5": {
        "st000":     (0x02EC2B18, 24, 24), # LAYOUT DONE, TILES DONE (Intro stage)
        "st010":     (0x02D98528, 39, 9),  # LAYOUT DONE, TILES DONE (Crescent Grizzly)
        "st020":     (0x02EC2EB8, 22, 12), # LAYOUT DONE, TILES DONE (Dark Necrobat: Area 1)
        "st021":     (0x02EC2FC0, 22, 12), # LAYOUT DONE, TILES DONE (Dark Necrobat: Area 2)
        "st030":     (0x02D98D88, 24, 30), # LAYOUT DONE, TILES DONE (Tidal Whale)
        "st040":     (0x02EC3398, 18, 42), # LAYOUT DONE, TILES DONE (Burn Dinorex: Area 1)
        "st041":     (0x02EC36A0, 20, 33), # LAYOUT DONE, TILES DONE (Burn Dinorex: Area 2)
        "st050":     (0x02D98890, 36, 21), # LAYOUT DONE, TILES DONE (Volt Kraken)
        "st060":     (0x02EC3C70, 34, 9),  # LAYOUT DONE, TILES DONE (Shining Firefly: Area 1)
        "st061":     (0x02D99058, 21, 33), # LAYOUT DONE, TILES DONE (Shining Firefly: Area 2)
        "st070":     (0x02D98B88, 34, 15), # LAYOUT DONE, TILES ALMOST (Spike Rosered)
        "st080":     (0x02D98688, 19, 27), # LAYOUT DONE, TILES DONE (Spiral Pegasus)
        "st090_00":  (0x02D98695, 2, 6),   # LAYOUT DONE, TILES DONE (Dynamo: Enigma Cannon)
        "st090_01":  (0x02D98695, 2, 6),   # LAYOUT DONE, TILES DONE (Dynamo: Hunter Base 1)
        "st100_00":  (0x02D9852F, 2, 6),   # LAYOUT DONE, TILES DONE (Dynamo: Space Shuttle)
        "st100_01":  (0x02D98695, 2, 6),   # LAYOUT DONE, TILES DONE (Dynamo: Hunter Base 2)
        "st160":     (0x02EC5390, 12, 57), # LAYOUT DONE, TILES DONE (Zero Space 1: Origin)
        "st170":     (0x02EC5660, 21, 30), # LAYOUT DONE, TILES DONE (Zero Space 2: Grief)
        "st180":     (0x02D99310, 28, 18), # LAYOUT DONE, TILES ALMOST (Zero Space 3: Awakening)
        "st120":     (0x02D99508, 21, 33), # LAYOUT DONE, TILES DONE (Zero Space 4: Birth)
        "st130":     (0x02D9869C, 6, 3),   # LAYOUT DONE, TILES DONE (Stage Select)
        "st220":     (0x02D97FDA, 25, 12), # LAYOUT ALMOST, TILES SOME (Training Area)
        "staff_eng": (0x02D9852F, 9, 6),   # LAYOUT DONE, TILES DONE (End Credits)
        "st140_eng": (0x02D98695, 2, 3),   # LAYOUT DONE, TILES DONE (Title screen)
        "st141_eng": (0x02D98695, 2, 3),   # LAYOUT DONE, TILES DONE (Player Select screen)
        "st150":     (0x02D98695, 2, 3),   # LAYOUT DONE, TILES DONE (Gameplay Report screen)
    },
    "X6": {
        "st00":      (0x02DD3FF0, 26, 18),  # LAYOUT DONE, TILES DONE (Intro - Eurasia Ruins)
        "st01":      (0x02DD41E0, 26, 27),  # LAYOUT DONE, TILES DONE (Commander Yammark; Amazon Area)
        "st01x":     (0x02DD6A18, 26, 27),  # LAYOUT DONE, TILES DONE (Commander Yammark; sub stage)
        "st02":      (0x02DD44A0, 27, 21),  # LAYOUT DONE, TILES DONE (Blizzard Wolfang; North Pole Area)
        "st02x":     (0x02DD6CD8, 15, 45),  # LAYOUT DONE, TILES DONE sub stage
        "st03":      (0x02DD46D8, 18, 39),  # LAYOUT DONE, TILES DONE (Blaze Heatnix; Magma Area)
        "st03x":     (0x02DD6F80, 15, 21),  # LAYOUT DONE, TILES DONE sub stage
        "st04a":     (0x02DD4998, 22, 24),  # LAYOUT DONE, TILES DONE (Recycle Lab: Area 1)
        "st04b":     (0x02DD4BA8, 26, 15),  # LAYOUT DONE, TILES DONE (Recycle Lab: Area 2)
        "st04x":     (0x02DD7118, 15, 18),  # LAYOUT DONE, TILES DONE sub-stage
        "st05":      (0x02DD4D30, 16, 48),  # LAYOUT DONE, TILES DONE (Ground Scaravich; Central Museum)
        "st05x":     (0x02DD7228,  6, 18),  # LAYOUT DONE, TILES DONE sub stage
        "st06a":     (0x02DD5030, 37, 18),  # LAYOUT DONE, TILES DONE (Rainy Turtloid; Inami Temple)
        "st06x":     (0x02DD7300,  8, 15),  # LAYOUT DONE, TILES DONE sub stage
        "st07":      (0x02DD52E7, 24, 21),  # LAYOUT DONE, TILES DONE (Shield Sheldon; Laser Institute)
        "st07x":     (0x02DD7378, 26,  9),  # LAYOUT DONE, TILES DONE sub stage
        "st08":      (0x02DD5540, 24, 18),  # LAYOUT DONE, TILES DONE (Infinity Mijinion; Weapons Facility)
        "st08x":     (0x02DD7468, 10, 12),  # LAYOUT DONE, TILES DONE sub stage
        "st0ca":     (0x02DD5750, 12, 42),  # LAYOUT DONE, TILES DONE (Secret Lab 3: Area 1)
        "st0cb":     (0x02DD5948, 16, 12),  # LAYOUT DONE, TILES DONE (Secret Lab 3: Area 2)
        "st0g":      (0x02DD61D0, 40, 18),  # LAYOUT DONE, TILES DONE (Secret Lab 1)
        "st0h":      (0x02DD64A0, 24, 27),  # LAYOUT DONE, TILES DONE (Secret Lab 2)
        "st0i":      (0x02DD6728, 25, 30),  # LAYOUT DONE, TILES DONE sub-stage
        "stsel_eng": (0x02DD6110,  7,  6),  # LAYOUT DONE, TILES DONE (Stage Select screen)
    }
}


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

    # Background tilemap (chr256): prefer tex256, fall back to texch3 when tex256 is
    # empty; fixes X5 st170 (Rangda Bangda W boss bg).
    tex_bg = tex256 or texch3
    # A texch3-sourced bg is opaque boss art, not a PSX semi-transparent effect, so
    # the caller renders it with stp_alpha=False
    bg_from_texch3 = not tex256 and bool(texch3)

    return [
        Path(f".\\PC\\X{game_version}\\{ocl}"),
        Path(f".\\PC\\X{game_version}\\{tex}"),
        Path(f".\\PC\\X{game_version}\\{tex_bg}") if tex_bg else None,
        Path(f".\\PC\\X{game_version}\\{col}"),
        Path(f".\\PC\\X{game_version}\\{col_animate}") if col_animate else None,
        bg_from_texch3,
    ]


def preload_related_files(omp_path: Path):
    if not omp_path.exists():
        raise FileNotFoundError(f"ERROR: OMP file not found: {omp_path}")

    omp_stem = omp_path.stem

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

    ocl_path, tex_path, tex_bg_path, col_path, col_path_animated, bg_from_texch3 = game_files

    for p in (ocl_path, tex_path):
        if not p.exists():
            raise FileNotFoundError(f"ERROR: Required sibling file not found: {p}")

    if not col_path.exists():
        raise FileNotFoundError(f"ERROR: COL palette not found at {col_path}")

    if game_version == GameVersion.X4:
        if not EXE_PATH_LC1.exists():
            raise FileNotFoundError(f"ERROR: RXC1.exe not found at {EXE_PATH_LC2}")
    else:
        if not EXE_PATH_LC2.exists():
            raise FileNotFoundError(f"ERROR: RXC2.exe not found at {EXE_PATH_LC2}")

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
    if tex_bg_path and tex_bg_path.exists():
        tex_background = load_tex(tex_bg_path)
    else:
        print(f"  WARNING: background TEX not found at {tex_bg_path}, using main TEX as fallback.")
        tex_background = tex

    print(f"  width={tex['width']}  height={tex['height']}  format={tex.get('format')}")

    print("Loading COL palette...")
    col = load_col_palettes(col_path)
    print(f"  {col_path.name}  ({type(col).__name__})")

    # All palette groups map to col*.col pending per-stage COL resolution.
    # Palette-swap tiles (tile_type=0x39, col=0) are suppressed in omp.py so
    # the background layer shows through instead.
    if col_path_animated and col_path_animated.exists():
        # stp_as_alpha: carry STP->alpha so the still-frame substitution below renders a
        # translucent effect (e.g. X4 SCR01_00 waterfall) while STP=0 effects stay opaque.
        anim_col = load_col_palettes(col_path_animated, stp_as_alpha=True)
    else:
        print(f"  WARNING: animated COL palette not found at {col_path_animated}, using static palette as fallback.")
        anim_col = None

    # OclEntry.palette_group() maps any unregistered collision type to STANDARD,
    # so all tiles are rendered even if their tile_type is not listed above.

    # X6's col*.col is a VRAM snapshot whose stage CLUTs sit at col+96;
    # normalize_x6_stage_palette() relocates them back onto col+64 for the universal
    # col+64 lookup.  X4/X5 store stage CLUTs at col+64 directly, so used unchanged.
    stage_palette = normalize_x6_stage_palette(col) if game_version == GameVersion.X6 else col

    # Palette-swap CLUT-animation substitution.  Some animated effects (e.g. waterfalls, glowing lights)
    # point their tiles at a CLUT row the engine fills at runtime from a per-stage animated
    # COL; the static palette holds a stale placeholder frame there.  Since we render a still
    # PNG, copy frame-0 of the animation range from the animated COL into those CLUT rows.
    # CLUT_ANIM_STILL_FRAMES gives (source-COL filename | None, frames); the named COL is
    # resolved next to the game-files col_animate path, else the default col_animate is used.
    still_entry = CLUT_ANIM_STILL_FRAMES.get(omp_stem)
    if still_entry is not None:
        src_name, frames = still_entry[0], still_entry[1]
        opaque = len(still_entry) > 2 and still_entry[2]
        src_col = anim_col
        if src_name and col_path_animated is not None:
            src_path = col_path_animated.with_name(src_name)
            src_col = load_col_palettes(src_path, stp_as_alpha=True) if src_path.exists() else None
        if src_col is not None:
            stage_palette = list(stage_palette)
            n_anim = len(src_col) // CLUT_COLORS_PER_ROW
            applied = 0
            for dest, src, length in frames:
                for k in range(length):
                    if src + k >= n_anim or dest + k < 0:
                        continue
                    row = src_col[(src + k) * CLUT_COLORS_PER_ROW:(src + k + 1) * CLUT_COLORS_PER_ROW]
                    if opaque:
                        # slot is opaque in-game; drop STP-derived alpha to match baseline.
                        row = [(r, g, b, 255) for (r, g, b, _a) in row]
                    stage_palette[(dest + k) * CLUT_COLORS_PER_ROW:(dest + k + 1) * CLUT_COLORS_PER_ROW] = row
                    applied += 1
            print(f"  CLUT-anime still-frame: {applied} row(s) from {src_name or col_path_animated.name}")

    flags_to_palette = {group: stage_palette for group in OclPaletteGroup}

    # Palette-swap tiles are left on the static stage palette;
    # the per-stage animated-COL mapping is unresolved (COL format not reversed).

    return [omp, ocl, tex, tex_background, flags_to_palette, game_version, bg_from_texch3]





# Stages whose layer fold ADDs the PSX semi-transparency (STP / OMP bit 0x4000) tiles
# (additive light effects: glows, light shafts, reflective glass = B+F over the bg)
# instead of alpha-blending them.  Gated per stage because the same 0x4000 bit marks
# translucent effects elsewhere (e.g. intro glass, SCR01 waterfalls) that must stay alpha-blended.
X4_ADDITIVE_STP_STAGES: frozenset[str] = frozenset({
    "SCR00_00", "SCR01_00", "SCR01_01", "SCR02_01",
})


def _additive_layer_fold(
    crop_layer, order: list[int], composed_width: int, composed_height: int
) -> PILImage:
    """
    Stacks layers based on order, ADDING PSX semi-transparency (STP) pixels.

    render_level() composes STP pixels by halving their alpha (opaque=255, STP=127,
    transparent=0), so alpha alone tells the fold how to blend each pixel:
      - a == 255 : opaque tile pixel  -> replace the accumulated colour
      - 0 < a < 255 : STP tile pixel  -> ADD its colour (clamped) to the background
      - a == 0   : transparent        -> leave the accumulator untouched
    This makes additive glow effects brighten the scene behind them,
    matching the in-game render. `order` lists which layer is rendered first.
    """
    acc = Image.new("RGB", (composed_width, composed_height), (0, 0, 0))
    painted = Image.new("L", (composed_width, composed_height), 0)
    for layer_index in order:
        layer = crop_layer(layer_index).convert("RGBA")
        rgb = layer.convert("RGB")
        a = layer.getchannel("A")
        opaque_mask = a.point(lambda v: 255 if v == 255 else 0)
        stp_mask = a.point(lambda v: 255 if 0 < v < 255 else 0)
        # Opaque pixels replace the accumulator; STP pixels add (ImageChops.add clamps
        # at 255).  The two masks are disjoint within a layer, so order is irrelevant.
        acc = Image.composite(rgb, acc, opaque_mask)
        acc = Image.composite(ImageChops.add(acc, rgb), acc, stp_mask)
        painted = ImageChops.lighter(painted, a.point(lambda v: 255 if v > 0 else 0))
    acc = acc.convert("RGBA")
    acc.putalpha(painted)
    return acc

# Return ordering of layer indices for a given stage.
# None means "no composition", returns the original image.
COMPOSED_ORDER_OVERRIDES: dict[GameVersion, dict[str, list[int] | None]] = {
    GameVersion.X4: {
        "SCR00_00": COMPOSED_ORDER_REVERSED,
        "SCR0E_00": None,
        "SCR0F_00_eng": None,
        "SCR01_00": COMPOSED_ORDER_REVERSED,
        "SCR01_01": COMPOSED_ORDER_REVERSED,
    },
    GameVersion.X5: {
        "st041": COMPOSED_ORDER_REVERSED,
        "st130": None,
        "staff_eng": None,
    },
    GameVersion.X6: {
        "st04a": COMPOSED_ORDER_REVERSED,
        "st04b": COMPOSED_ORDER_REVERSED,
        "st04x": COMPOSED_ORDER_REVERSED,
        "stsel_eng": None,
    },
}

def compose_stage_image(full_render: PILImage, layout_columns: int, layout_rows: int, game_version: GameVersion, omp_stem: str) -> PILImage:
    """
    Returns an image of the stage with all 3 layers composed together.

    The layers of stages are usually "layout_rows / 3" to get
    - layer 0: top layer
    - layer 1: middle layer
    - layer 2: background layer

    Except in the cases of stages like ending credits or stage select.

    Layouts are measured in screens. Each screen is 16x16 tiles, so 256x256 pixels.
    """
    layer_rows = layout_rows // 3
    composed_width = layout_columns * 256
    composed_height = layer_rows * 256

    def crop_layer(layer_index: int) -> PILImage:
        return full_render.crop((0, layer_index * composed_height, composed_width, (layer_index + 1) * composed_height))

    # Layer order, back-to-front by default
    order = COMPOSED_ORDER_OVERRIDES.get(game_version, {}).get(omp_stem, COMPOSED_ORDER_BASIC)

    if order is None:
        # No composition for this stage, return the full render as-is.
        print(f"  Composition None override for {game_version} {omp_stem}, returning full render.")
        return full_render

    # Additive compose for stages whose STP tiles are additive light effects.
    # Everything else keeps the plain alpha merge
    if omp_stem in X4_ADDITIVE_STP_STAGES:
        return _additive_layer_fold(crop_layer, order, composed_width, composed_height)

    # take the background layer of full_render to create the composed image while maintaining transparency
    composed_image = Image.new("RGBA", (composed_width, composed_height), (0, 0, 0, 0))
    for layer_index in order:
        layer = crop_layer(layer_index)
        composed_image.paste(layer, (0, 0), mask=layer)

    return composed_image


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a stage OMP to PNG (level + catalog)."
    )
    parser.add_argument("omp_file", type=Path, help="Path to the .omp file")
    parser.add_argument(
        "--composed", action=argparse.BooleanOptionalAction, default=False,
        help="Render composed stage or as seperate layers (layer 0=front, 1=middle, 2=background)",
    )
    parser.add_argument(
        "--split-layers", action=argparse.BooleanOptionalAction, default=False,
        help="Render each layer out to a different file",
    )
    parser.add_argument(
        "--skip-stage", action=argparse.BooleanOptionalAction,
        help="Only produce the catalog PNG, skip level render",
    )
    parser.add_argument(
        "--skip-catalog", action=argparse.BooleanOptionalAction, default=True,
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
    [omp, ocl, tex, tex_background, flags_to_palette, game_version, bg_from_texch3] = preload_related_files(omp_path)

    chr256_extra: "frozenset[int] | None" = None
    clut_row_fix: "dict[int, int] | None" = None
    x6_page8_palette = None
    if game_version == GameVersion.X6:
        chr256_extra = build_x6_chr256_override(ocl, tex, tex_background, omp_stem)
        # X6 "inverted shadows" fix: page>=8 pad_hi=0 8bpp tiles read the RAW
        # (un-normalized) stage CLUT at col+96, bypassing normalize_x6_stage_palette's
        # null-keep (which leaves the polluted col+64 VRAM snapshot on dark CLUTs).
        # Gated to VRAM-snapshot COL files; static menu palettes (col+64 already correct)
        # are skipped.  See utils/omp render_level + _X6_PAGE8_CLUT_OFFSET.
        _gf = get_game_files(game_version, omp_path)
        if _gf is not None:
            _raw_col = load_col_palettes(_gf[3])
            if x6_palette_is_vram_snapshot(_raw_col):
                x6_page8_palette = _raw_col
        # pad_hi CLUT-bank rule with the explicit per-index X6_CLUT_ROW_FIXES merged ON TOP
        # so validated rows win on any conflict (e.g. st04a OCL 202).
        # Result: st04a's validated tiles are unchanged; only newly
        # covered pad_hi=4 tiles (declined page-10 col=0 batch, st04b, ...) move.
        padhi_fix = build_x6_padhi_clut_override(ocl, omp_stem)
        explicit_fix = build_x6_clut_row_override(omp_stem, ocl, chr256_extra or frozenset()) or {}
        merged = {**padhi_fix, **explicit_fix}
        clut_row_fix = merged or None
        n_padhi_only = len(set(padhi_fix) - set(explicit_fix))
        print(f"  CLUT-row overrides: {len(padhi_fix)} pad_hi + {len(explicit_fix)} explicit "
              f"= {len(merged)} ({n_padhi_only} from pad_hi rule alone)")

    # X5 background-tileset chr256 recovery is computed in the level-render block below,
    # where the layout (needed for the background-exclusive signal) is available.

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
            chr256_override=chr256_extra,
            clut_row_override=clut_row_fix,
            x6_page8_palette=x6_page8_palette,
        )
        if args.debug:
            debug_overlay_catalog(catalog_img, omp.n_screens)
        catalog_out = output_dir / f"{omp_stem}_catalog.png"
        catalog_img.save(catalog_out)
        print(f"  Saved {catalog_out}  ({catalog_img.width}x{catalog_img.height} px)")

    layout_entry = STAGE_LAYOUT.get(f"X{game_version}", {}).get(omp_stem)

    # Level render (when layout is known)
    if layout_entry and not args.skip_stage:
        offset, w, h = layout_entry

        print(f"  (offset=0x{offset:08X}  w={w}  h={h})")
        print()

        print()

        EXE_PATH = EXE_PATH_LC1 if game_version == GameVersion.X4 else EXE_PATH_LC2
        print(f"Loading layout from {EXE_PATH}...")
        layout = load_layout_from_exe(EXE_PATH, offset=offset, width=w, height=h)

        n_sx = len(layout.screens[0]) if layout.screens else 0
        n_sy = len(layout.screens)
        print(f"  {n_sx} screens wide x {n_sy} screens tall")

        level_chr256 = chr256_extra
        if game_version == GameVersion.X5:
            # Recover background tilesets the base router leaves on tex as garbled tiles
            # (st061 sky, st070 jungle, st160 scanline plasma, st000 skyline, ...)
            level_chr256, n_moved = build_x5_chr256_bg_override(
                ocl, tex, tex_background, layout,
                omp.n_screens, omp.tiles, n_sx, n_sy,
            )
            print(f"  X5 chr256 bg-recovery: +{n_moved} tiles routed to tex_bg")
            # Per-stage tex/tex_bg sheet corrections for page>=8 tiles which the
            # PC port re-packed onto the opposite sheet (eg. dragon-head flamethrowers.
            n_before = len(level_chr256)
            level_chr256 = build_x5_sheet_override(omp_stem, ocl, level_chr256)
            if len(level_chr256) != n_before:
                print(f"  X5 sheet override: {len(level_chr256) - n_before:+d} tiles re-routed")
            # Generic recovery of page>=8 art the PC port re-packed onto tex_bg under a
            # non-indicator col, where tex is blank (eg. st120 Sigma room X/Zero pods).
            level_chr256, n_pg8 = build_x5_pg8_empty_bg_override(ocl, tex, tex_background, level_chr256)
            if n_pg8:
                print(f"  X5 page>=8 tex-empty recovery: +{n_pg8} tiles routed to tex_bg")
            # Per-stage CLUT-row corrections for background batches on the wrong palette
            clut_row_fix = build_x5_clut_row_override(omp_stem, ocl, level_chr256)
            if clut_row_fix:
                print(f"  X5 CLUT-row fixes: {len(clut_row_fix)} tiles relocated")

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
            flags_to_palette=flags_to_palette,
            chr256_override=level_chr256,
            clut_row_override=clut_row_fix,
            x6_page8_palette=x6_page8_palette,
            # texch3-sourced background tiles are opaque boss art, not PSX STP effects;
            # render_level exempts only those tiles (per-tile), leaving same-stage
            # main-sheet tiles (e.g. st170's honeycomb) translucent.
            bg_is_texch3=bg_from_texch3,
        )
        if game_version == GameVersion.X5:
            # Bake the additive water onto X5 st070 STP water tiles.
            n_water = x5_additive_water(level_img, omp, ocl, layout, n_sx, n_sy, omp_stem)
            if n_water:
                print(f"  X5 additive-water bake: {n_water} tiles composited")
        if args.debug:
            debug_overlay_level(level_img, layout, n_sx, n_sy)

        level_out = output_dir / Path(f"{omp_stem}.png")

        if args.split_layers:
            for layer_index in range(3):
                layer_img = level_img.crop((0, layer_index * (level_img.height // 3), level_img.width, (layer_index + 1) * (level_img.height // 3)))
                layer_out = level_out.with_stem(f"{level_out.stem}_layer{layer_index}")
                layer_img.save(layer_out)
                print(f"  Saved {layer_out}")

        if args.composed:
            level_img = compose_stage_image(level_img, w, h, game_version, omp_stem)
            level_out = level_out.with_stem(f"{level_out.stem}_composed")
            level_img.save(level_out)
            print(f"  Saved {level_out}  ({level_img.width}x{level_img.height} px)")
        else:
            level_out = level_out.with_stem(f"{level_out.stem}_level")
            level_img.save(level_out)
            print(f"  Saved {level_out}  ({level_img.width}x{level_img.height} px)")

    else:
        print()
        print(f"Stage layout unknown for {omp_stem}, skipping level render.")


if __name__ == "__main__":
    main()
