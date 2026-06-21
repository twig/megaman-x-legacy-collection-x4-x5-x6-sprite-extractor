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

  Each STAGE_LAYOUT entry carries an inline status tag (the comment after the
  tuple), which is the source of truth for that stage's confidence:

    DONE        — renders accurately.
    FOUND       — layout located, but still has visual defects rendering the stage.
    ALMOST      — tiles look complete, but offset/dimensions not quite right.
    IN RANGE    — most tiles displayed and recognisable, but definitely not the right offset.
    UNCONFIRMED — offset/dimensions resulted from a script, usually wrong but could be close by.
    GUESS       — offset/dimensions based on guesstimates within boundaries.

  Stages absent from STAGE_LAYOUT have no layout identified yet (catalog-only
  output).  Treat absent / GUESS / UNCONFIRMED entries as unresolved.  To hunt for
  unresolved X5 offsets see docs/finding-stage-layout-offsets.md and
  experimental/verify_x5_heights_omp.py.

== Block 2 boss stages ==

  COPY2_OFFSET = 0x02D9B9A4 (.rdata), SIZE_TABLE_2 = 0x02E8DF71 (.data).
  The X5 group {st090_00, st090_01, st100_00, st100_01, st130} draws from block 2;
  see each entry's inline status tag for its current confidence.

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

from utils.omp import load_omp, render_level, render_omp, load_layout_from_exe, LayerPreset, LayoutTable, _build_chr256_ocl_indices
from utils.ocl import load_ocl, OclEntry, OclPaletteGroup
from utils.tex import load_tex
from utils.palette import load_col_palettes, normalize_x6_stage_palette
from utils.types import GameVersion, TexData
from x4_pc_mmxlc1_layout_offsets import X4_LAYOUT_OFFSETS

# Paths
EXE_PATH_X4 = Path("RXC1.exe")
EXE_PATH = Path("RXC2.exe")

# Tile geometry / palette constants
TILE_SIZE = 16                    # pixels per tile edge
X6_BG_INDICATOR_COLS = (0, 112)   # page>=8 OCL cols that mark chr256 background tiles
X6_PALETTE_FAN_MIN_COLS = 4       # >= this many distinct cols at one atlas coord ⇒ a recolored
                                  # tile fanned into palette variants (only stsel/st02/st05 have any)
X6_CHR256_COL_MIN = 112           # within such a fan, col >= this is the chr256 background variant;
                                  # lower cols are foreground recolors (read tex)

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

STAGE_LAYOUT: dict[str,dict[str, tuple[int, int, int]]] = {
    "X4": dict([
        (key, (
        data["pc_offset"], data["w"], data["h"]))
        for key, data
        in X4_LAYOUT_OFFSETS.items()
    ]),
    # st000 (intro stage) layout is NOT in the 0x02d9xxxx region with st010+;
    # It sits in a separate block near the ORIGINAL guess 0x02EC2D4B.
    #
    # Found by match_layout_to_map.py
    # - recovering the screen-id grid from X5_ST00_00_INTRO_combined.png
    # - then Hough-voting it across the whole EXE
    #
    # st010 found by trial and error.
    # the others were within range, good enough to start debugging tile rendering.
    "X5": {
        # garbled at bottom
        "st000":     (0x02EC2B18, 24, 21), # LAYOUT DONE, TILES ALMOST (Intro stage)
        "st010":     (0x02D98528, 39, 8),  # LAYOUT DONE, TILES DONE (Crescent Grizzly)
        "st020":     (0x02EC2EB8, 22, 12), # LAYOUT DONE, TILES DONE (Dark Necrobat: Area 1)
        # inverted highlights
        "st021":     (0x02EC2FC0, 22, 12), # LAYOUT DONE, TILES ALMOST (Dark Necrobat: Area 2)
        # black box, garbled mini boss
        "st030":     (0x02D98D88, 24, 23), # LAYOUT DONE, TILES ALMOST (Tidal Whale)
        # garbled dragon heads
        "st040":     (0x02EC3398, 18, 36), # LAYOUT DONE, TILES ALMOST (Burn Dinorex: Area 1)
        # garbled background
        "st041":     (0x02EC36A0, 20, 12), # LAYOUT DONE, TILES ALMOST (Burn Dinorex: Area 2)
        "st050":     (0x02D98890, 36, 21), # LAYOUT DONE, TILES DONE (Volt Kraken)
        "st060":     (0x02EC3C70, 34, 9),  # LAYOUT DONE, TILES DONE (Shining Firefly: Area 1)
        "st061":     (0x02D99058, 21, 33), # LAYOUT DONE, TILES MOST (Shining Firefly: Area 2)
        # mismatched tiles, black box or missing tiles, rope near vines partially missing?,
        # mystery block near capsule, garbled green at bottom, incorrect palette
        "st070":     (0x02D98B88, 34, 15), # LAYOUT DONE, TILES MOST (Spike Rosered)
        "st080":     (0x02D98688, 19, 27), # LAYOUT DONE, TILES DONE (Spiral Pegasus)
        "st090_00":  (0x02D98697, 2, 3),   # LAYOUT DONE, TILES DONE (Dynamo: Enigma Cannon)
        "st090_01":  (0x02D98697, 2, 3),   # LAYOUT DONE, TILES DONE (Dynamo: Hunter Base 1)
        "st100_00":  (0x02D9852F, 2, 4),   # LAYOUT DONE, TILES DONE (Dynamo: Space Shuttle)
        "st100_01":  (0x02D98697, 2, 3),   # LAYOUT DONE, TILES DONE (Dynamo: Hunter Base 2)
        "st160":     (0x02EC5390, 12, 57), # LAYOUT DONE, TILES DONE (Zero Space 1: Origin)
        # black boxes
        "st170":     (0x02EC5660, 21, 30), # LAYOUT DONE, TILES ALMOST (Zero Space 2: Grief)
        "st180":     (0x02D99310, 28, 18), # LAYOUT DONE, TILES DONE (Zero Space 3: Awakening)
        "st120":     (0x02D99508, 21, 33), # LAYOUT DONE, TILES DONE (Zero Space 4: Birth)
        "st130":     (0x02D9869C, 6, 3),   # LAYOUT DONE, TILES DONE (Stage Select)
        # missing tiles (lots)
        "st220":     (0x02D97FDA, 25, 11), # LAYOUT LIKELY, TILES SOME (Training Area)
        "staff_eng": (0x02D9852F, 9, 6),   # LAYOUT DONE, TILES DONE (End Credits)
        "st140_eng": (0x02D98695, 2, 1),   # LAYOUT DONE, TILES DONE (Title screen)
        "st141_eng": (0x02D98695, 2, 1),   # LAYOUT DONE, TILES DONE (Player Select screen)
        "st150":     (0x02D98695, 2, 1),   # LAYOUT DONE, TILES DONE (Gameplay Report screen)
    },
    # Offsets read from RXC2.exe's per-stage LAYOUT POINTER TABLE (file 0x0307E898),
    # each entry is a virtual-address located + decoded by extract_layout_offsets.py
    # layout_file_offset = VA - 0x400e00
    #
    # These are the offsets the GAME uses and verified to be correct after
    # width/height guesses using explore_layout.py
    "X6": {
        # garbled
        "st00":      (0x02DD3FF0, 26, 17),  # LAYOUT DONE, TILES ALMOST (Intro - Eurasia Ruins)
        "st01":      (0x02DD41E0, 26, 23),  # LAYOUT DONE, TILES DONE (Commander Yammark; Amazon Area)
        # inverted shadows
        "st01x":     (0x02DD6A18, 26, 20),  # LAYOUT DONE, TILES ALMOST (Commander Yammark; sub stage)
        "st02":      (0x02DD44A0, 27, 15),  # LAYOUT DONE, TILES DONE (Blizzard Wolfang; North Pole Area)
        # missing tile?
        "st02x":     (0x02DD6CD8, 15, 33),  # LAYOUT DONE, TILES ALMOST sub stage
        # grey box, black box, inverted shadow, wrong palette, missing tile?
        "st03":      (0x02DD46D8, 18, 39),  # LAYOUT DONE, TILES MOST (Blaze Heatnix; Magma Area)
        # inverted shadow, missing tiles
        "st03x":     (0x02DD6F80, 15, 20),  # LAYOUT DONE, TILES MOST sub stage
        # garbled
        "st04a":     (0x02DD4998, 22, 23),  # LAYOUT DONE, TILES ALMOST (Recycle Lab: Area 1)
        # inverted shadows
        "st04b":     (0x02DD4BA8, 26, 15),  # LAYOUT DONE, TILES ALMOST (Recycle Lab: Area 2)
        # inverted shadows
        "st04x":     (0x02DD7118, 15, 14),  # LAYOUT DONE, TILES ALMOST sub-stage
        # garbled, maybe missing tiles?
        "st05":      (0x02DD4D30, 16, 36),  # LAYOUT DONE, TILES ALMOST (Ground Scaravich; Central Museum)
        # inverted shadows
        "st05x":     (0x02DD7228,  6, 16),  # LAYOUT DONE, TILES ALMOST sub stage
        # garbled, black box, missing tiles?
        "st06a":     (0x02DD5030, 37, 16),  # LAYOUT DONE, TILES ALMOST (Rainy Turtloid; Inami Temple)
        # black box, missing tile?
        "st06x":     (0x02DD7300,  8, 14),  # LAYOUT DONE, TILES ALMOST sub stage
        # black box
        "st07":      (0x02DD52E7, 24, 19),  # LAYOUT DONE, TILES DONE (Shield Sheldon; Laser Institute)
        # inverted highlight
        "st07x":     (0x02DD7378, 26,  8),  # LAYOUT DONE, TILES ALMOST sub stage
        "st08":      (0x02DD5540, 24, 19),  # LAYOUT DONE, TILES DONE (Infinity Mijinion; Weapons Facility)
        "st08x":     (0x02DD7468, 10, 11),  # LAYOUT DONE, TILES DONE sub stage
        "st0ca":     (0x02DD5750, 12, 34),  # LAYOUT DONE, TILES ALMOST (Secret Lab 3: Area 1)
        "st0cb":     (0x02DD5948, 16, 10),  # LAYOUT DONE, TILES ALMOST (Secret Lab 3: Area 2)
        "st0g":      (0x02DD61D0, 40, 14),  # LAYOUT DONE, TILES MOST (Secret Lab 1)
        "st0h":      (0x02DD64A0, 24, 21),  # LAYOUT DONE, TILES ALMOST (Secret Lab 2)
        "st0i":      (0x02DD6728, 25, 23),  # LAYOUT DONE, TILES ALMOST sub-stage
        # tiles missing?
        "stsel_eng": (0x02DD6110,  7,  4),  # LAYOUT DONE, TILES DONE (Stage Select screen)
    }
}

# print("Stage layout offsets loaded:", STAGE_LAYOUT["X4"])

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

    # X6's col00_0x.col is a VRAM snapshot whose stage CLUTs are relocated to
    # col+96; normalize_x6_stage_palette() relocates them back onto col+64 so the
    # renderer can use the universal col+64 lookup.  X4/X5 store stage CLUTs at
    # col+64 directly, so their palette is used unchanged.
    stage_palette = normalize_x6_stage_palette(col) if game_version == GameVersion.X6 else col
    flags_to_palette = {group: stage_palette for group in OclPaletteGroup}

    # NOTE: animated-crystal tiles (tile_type 0x39) are left on the static stage
    # palette.  An earlier attempt routed them to the per-stage animated COL indexed
    # by `col`, but those COL files are per-stage palette banks of wildly varying
    # size (1-645 rows) — col-direct indexing runs out of range (lost tiles) and, even
    # in range, yields wrong colours on most stages (st00/st04b/st05 lost tiles;
    # st04a/st06a/st07 wrong colours).  The correct animated-palette mapping needs the
    # COL format reverse-engineered; until then the static palette is the safe default.

    return [omp, ocl, tex, tex_background, flags_to_palette, game_version]


# ── X6 per-stage chr256 routing overrides, by explicit OCL INDEX ─────────────────
#
# Companion to the (col, page, pad_hi) group table X6_SHEET_OVERRIDE_BY_STAGE below, for
# tiles the content heuristic mis-routes that do NOT form a clean group — their
# (col, page, pad_hi) group also contains correctly-routed sibling tiles, so only specific
# OCL indices can be corrected.  ``"bg"`` forces the index INTO chr256 (read tex_bg),
# ``"tex"`` forces it OUT (read tex).  Each index was ground-truth-confirmed (no counter-
# examples among its placements); see the scrapbook per-index salvage analysis.
#
# st04a "tex": the hydraulic-press / Metal-Shark machinery TOP band (col=0, page=10, pad_hi=4)
#   — genuinely FOREGROUND, but the col=0 chr256 indicator sweeps it into tex_bg where it draws
#   chains/mesh.  868-883 skips 874/879 (col=64 left-edge, already tex).  NOT the whole
#   (0,10,4) class — the separate 1505-1612 structure IS background — hence per-index.
# "bg" runs: page>=8 (and a few page<8) background tiles left on tex by the heuristic, in
#   mixed groups (st00 col4/pg9, st06a col240/pg11, st03 col21/pg4, st07 col123/pg6,
#   st08 col3/pg5, st01, st02).
X6_SHEET_OVERRIDE_INDICES: dict[str, "dict[int, str]"] = {
    "st04a": {i: "tex" for i in (set(range(868, 884)) - {874, 879}) | {920, 921, 922}},
    "st00":  {i: "bg" for i in (3025, 3026, 3027, 3028, 3029, 3030, 3031, 3032, 3033,
                                3034, 3035, 3036, 3037, 3039, 3042, 3044)},
    "st01":  {2627: "bg"},
    "st02":  {2628: "bg"},
    "st03":  {i: "bg" for i in range(2444, 2452)},
    "st06a": {i: "bg" for i in (2190, 2191, 2194, 2195, 2196, 2198, 2199, 2200, 2201, 2202,
                                2203, 2204, 2205, 2206, 2207, 2208, 2209, 2210, 2211, 2212,
                                2213, 2214, 2215, 2218, 2219, 2220, 2221, 2222, 2223, 2224,
                                2225, 2226, 2227, 2230, 2231, 2232)},
    "st08":  {i: "bg" for i in range(2578, 2584)},
}


# ── X6 per-stage tile-sheet overrides ────────────────────────────────────────────
#
# Per-stage (col, page, pad_hi) -> sheet corrections for tiles the content heuristic in
# build_x6_chr256_override mis-routes.  tex-vs-tex_bg is NOT a function of any single OCL/OMP
# field — the same (col, page, pad_hi) reads tex_bg in one stage and tex in another — so these
# groups are listed per stage and each was validated against ground truth (in-game captures).
# ``"bg"`` forces the group INTO chr256 (read tex_bg); ``"tex"`` forces it OUT (read tex).
# A group is listed only when ALL of its visibly-affected placements were confirmed correct
# (zero counter-examples) — see the scrapbook salvage analysis.  This (col,page,pad_hi) table
# is consulted regardless of pad_hi, so it cleanly handles both the pad_hi=4 alt-bank machinery
# and ordinary pad_hi=0 background groups in one mechanism.
#
#   st0g  (48,10/11,4)->bg     dormant-mechaniloid armour; RMS 9.9 vs st0g-goal.png (tex 63.8).
#   st06a (16/32/48,11,4)->bg  same pad_hi=4 machinery class as st0g.
#   st00  (96,9,0)->bg / st0h (80,11,0)->bg / st0i (64,10,0)->bg
#                              page>=8 background groups the heuristic left on tex.
#   st04a (40/47/50/51,1,0)->tex   page-1 foreground tiles the duplicate-pair rule over-routed
#                                  to chr256.
# (st04a's page-10 col=0 sub-batch is handled per-index in X6_SHEET_OVERRIDE_INDICES above:
# other (0,10,4) tiles in that stage ARE genuine background, so it is not a clean
# (col,page,pad_hi) group.)
X6_SHEET_OVERRIDE_BY_STAGE: dict[str, "dict[tuple[int, int, int], str]"] = {
    # stem -> {(col, page, pad_hi): "bg" | "tex"}
    "st0g":  {(48, 10, 4): "bg", (48, 11, 4): "bg"},
    "st00":  {(96, 9, 0): "bg"},
    "st0h":  {(80, 11, 0): "bg"},
    "st06a": {(16, 11, 4): "bg", (32, 11, 4): "bg", (48, 11, 4): "bg"},
    "st0i":  {(64, 10, 0): "bg"},
    "st04a": {(40, 1, 0): "tex", (47, 1, 0): "tex", (50, 1, 0): "tex", (51, 1, 0): "tex"},
}


def build_x6_chr256_override(
    ocl: list[OclEntry],
    tex: TexData,
    tex_background: TexData,
    stage_stem: "str | None" = None,
    gap_fill: bool = True,
    palette_fan_guard: bool = True,
    fg_pair_fix: bool = True,
    pg8_empty_bg: bool = True,
    garbage_page_flip: bool = True,
    strip_tail_extend: bool = True,
    interior_gap_bridge: bool = True,
    fg_strip_recover: bool = True,
    bg_empty_hole_fill: bool = True,
    pg8_garbage_hole_suppress: bool = True,
) -> frozenset[int]:
    """
    Return the chr256 (tex_background) OCL-index set for an X6 stage.

    Starts from the game-agnostic _build_chr256_ocl_indices() routing and adds a
    trailing batch of background tiles on pages >= 8 that have no foreground
    counterpart in the OCL table — the base routing handles foreground/background
    duplicate pairs (page<8 and page>=8, via its Pass 3a-3c) but leaves these
    unpaired sole background tiles on tex because nothing pairs them.

    A page>=8 tile is added when its (page, col) matches a col already confirmed as
    background by the base routing, and tex / tex_background hold different non-empty
    pixel data at its coordinate (so the routing actually matters).

    Sole-entry gate: a (page, clut_base) coordinate that appears MORE THAN ONCE is a
    foreground/background duplicate pair, not an unpaired sole background tile.  Its
    first occurrence is the foreground tile (tex) and any background variant is the
    later occurrence, already routed by _build_chr256_ocl_indices (Pass 3c).  Adding
    the first occurrence here would read the foreground texture for a background slot
    — e.g. st02's page=11 col=29 ice-incline tiles rendered as jagged foreground
    fragments instead of the smooth chr256 hill.  Background indicator cols (0/112)
    are exempt: a same-indicator-col duplicate (e.g. st04a page>=8 col=0 pairs) is
    genuinely background and must still be added.

    Per-stage sheet overrides close out (no-op when stage_stem is None/absent): the
    (col, page, pad_hi) groups in X6_SHEET_OVERRIDE_BY_STAGE[stage_stem] and the explicit OCL
    indices in X6_SHEET_OVERRIDE_INDICES[stage_stem] are each forced to their named sheet —
    ``"bg"`` ADDS the tile to chr256 (art the content passes leave on tex but really lives in
    tex_bg), ``"tex"`` REMOVES it.  Index entries take precedence over group entries.
    """
    base_chr256 = _build_chr256_ocl_indices(ocl, tex, tex_background)
    extra = set(base_chr256)

    bg_raw = tex_background["raw_image"]
    bg_w = tex_background["width"]

    # Count occurrences per page>=8 (page, clut_base) coordinate for the sole-entry gate.
    pg8_coord_count: dict[tuple, int] = {}
    for entry in ocl:
        if (entry.pad & 0xF) >= 8:
            key = (entry.pad & 0xF, entry.clut_base)
            pg8_coord_count[key] = pg8_coord_count.get(key, 0) + 1

    # Cols already confirmed as background by the base routing.
    confirmed_bg_page_col: set[tuple] = set()
    for idx in extra:
        entry = ocl[idx]
        page = entry.pad & 0xF
        if page >= 8:
            confirmed_bg_page_col.add((page, entry.col))

    tx_raw = tex["raw_image"]
    tx_w = tex["width"]
    tx_h = len(tx_raw) // tx_w
    bg_h = len(bg_raw) // bg_w

    # Unpaired sole-background tiles (only runs when the base routing confirmed at
    # least one page>=8 background col; otherwise there is nothing to anchor to).
    if confirmed_bg_page_col:
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            page = entry.pad & 0xF
            if page < 8:
                continue
            if (page, entry.col) not in confirmed_bg_page_col:
                continue
            # Sole-entry gate (see docstring): skip non-indicator duplicates.
            if (pg8_coord_count.get((page, entry.clut_base), 0) > 1
                    and entry.col not in X6_BG_INDICATOR_COLS):
                continue
            cordX = entry.clut_base & 0xF
            cordY = (entry.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h or
                    gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h):
                continue
            # Both textures must have non-empty, differing pixel data.
            if not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if all(tx_raw[(gy + dy) * tx_w + gx + dx] ==
                   bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Page>=8 empty-foreground background recovery ──────────────────────────
    #
    # The base routing classifies page>=8 background tiles using the col=0/112
    # chr256 palette indicators (omp.py Pass 3a/3b/3c) or large-span different-col
    # duplicate pairs.  A stage whose page>=8 background tileset uses NEITHER — sole
    # entries at distinct coordinates carrying ordinary palette cols (st0h's pages
    # 10-11 use cols 6/32/48/80/96) — is invisible to all of those passes, and the
    # "unpaired sole-background" pass above also skips it because that pass requires
    # an already-confirmed background (page, col) anchor AND a non-empty foreground
    # tile.  Result: st0h drew none of its ~160 page>=8 background tiles (the museum
    # walls/floors), leaving large holes.
    #
    # The unambiguous, anchor-free signal for these is: the FOREGROUND sheet (tex) is
    # EMPTY at the tile's coordinate while the chr256 sheet (tex_background) holds
    # real pixels.  A placed tile (non-zero OMP cell) whose foreground texture is
    # blank can only have come from the background sheet — there is nothing else to
    # draw.  Route every such page>=8 entry to tex_background.
    #
    # Regression safety: this is provably pixel-additive.  It only adds entries whose
    # tex tile is entirely empty, so before the change those tiles rendered NOTHING
    # (a fully-transparent paste).  Each level cell maps to exactly one OCL index, so
    # filling a previously-blank cell can neither alter nor occlude any pixel already
    # drawn by another tile.  It never removes an index from the set and never touches
    # page<8 routing, so X4/X5 (which don't call this) and every page<8 tile are
    # byte-identical.  Across the settled X6 stages the only tiles it adds are
    # OMP-referenced background tiles previously missing as holes (st00 +7, st04b +42,
    # st05 +33, st06a +18, st0h +160) — recoveries, not regressions.
    if pg8_empty_bg:
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            page = entry.pad & 0xF
            if page < 8:
                continue
            cordX = entry.clut_base & 0xF
            cordY = (entry.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h or
                    gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h):
                continue
            # Foreground must be empty (tile would otherwise render nothing) and the
            # chr256 sheet must hold real pixels to draw instead.
            if any(tx_raw[(gy + dy) * tx_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Gap-fill pass: interior holes in a contiguous background strip ─────────
    #
    # A chr256 background tileset is laid out as horizontal strips: a run of
    # consecutive OCL indices that map to consecutive (page, clut_base) tile
    # coordinates.  The base routing's per-tile fill heuristic occasionally drops
    # a single fully-painted tile out of such a strip (it mistakes the dense pixel
    # data for a foreground object — e.g. st01's green-moss ridge transition tile
    # at OCL 2702, the lone gap in the 2695-2719 page-3 strip).
    #
    # An entry currently routed to tex whose immediate index neighbours (idx-1 and
    # idx+1) are BOTH background, on the SAME page, with clut_base forming a
    # consecutive triple (cb-1, cb, cb+1), is itself an interior strip member and
    # belongs on tex_bg.  Two guards keep genuine foreground tiles out:
    #   - The consecutive-clut_base requirement: a foreground tile interrupting the
    #     OCL order (e.g. st01 OCL 2627, whose neighbour jumps to another page)
    #     breaks the run and is never considered.
    #   - MIN_STRIP_RUN: the lockstep chr256 strip through idx must span at least
    #     this many tiles.  A genuine background tilemap strip (sky ridge, moss
    #     line, ice ridge, machinery wall) runs for dozens of tiles; a 2-4 tile
    #     run of background fragments inside a foreground-heavy region is NOT a
    #     strip.  Confirmed across X6: genuine strip gaps span >= 31 tiles
    #     (st01 2702→115, 2677→31; st02 2373→35; st04b 1116→112, 1132→40) while
    #     the foreground pole/chain region in st0h yields only 4-11 (470→4,
    #     505→11), which a threshold of 20 cleanly excludes.
    # tex_bg must hold pixel data at the coordinate for the swap to be meaningful.
    MIN_STRIP_RUN = 20
    pre_gap = frozenset(extra)  # snapshot: measure runs/neighbours order-independently

    def _strip_run(idx: int, page: int, cb: int) -> int:
        """Length of the lockstep chr256 strip (consecutive index + clut_base) through idx."""
        n = 1
        k = idx - 1
        while k >= 0 and k in pre_gap and (ocl[k].pad & 0xF) == page and ocl[k].clut_base == cb - (idx - k):
            n += 1; k -= 1
        k = idx + 1
        while k < len(ocl) and k in pre_gap and (ocl[k].pad & 0xF) == page and ocl[k].clut_base == cb + (k - idx):
            n += 1; k += 1
        return n

    for idx in range(1, len(ocl) - 1) if gap_fill else ():
        if idx in pre_gap:
            continue
        entry = ocl[idx]
        page = entry.pad & 0xF
        if page >= 8:
            continue
        if (idx - 1) not in pre_gap or (idx + 1) not in pre_gap:
            continue
        prev_e, next_e = ocl[idx - 1], ocl[idx + 1]
        if (prev_e.pad & 0xF) != page or (next_e.pad & 0xF) != page:
            continue
        if prev_e.clut_base != entry.clut_base - 1 or next_e.clut_base != entry.clut_base + 1:
            continue
        if _strip_run(idx, page, entry.clut_base) < MIN_STRIP_RUN:
            continue
        cordX = entry.clut_base & 0xF
        cordY = (entry.clut_base >> 4) & 0xF
        gx = (page % 8) * 256 + cordX * TILE_SIZE
        gy = (page // 8) * 256 + cordY * TILE_SIZE
        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
            continue
        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
            continue
        extra.add(idx)

    # ── Background-strip interior gap bridge (multi-tile) ─────────────────────
    #
    # The single-hole gap-fill above only bridges a ONE-tile hole (both immediate
    # OCL neighbours are tex_bg).  A chr256 background strip can instead lose a SHORT
    # RUN of interior tiles to tex: a contiguous lockstep clut_base sequence on one
    # page is routed to tex_bg except for a 2-4 tile stretch in its middle, which the
    # base routing pinned to tex.  This happens when those interior tiles are reused
    # foreground/background duplicates whose later (background) occurrence carries the
    # same col as the foreground first occurrence (col=0) plus a 0x38 hit-flash type:
    # the same-col 0x38 blocking rule forces the whole coordinate to tex, even though
    # in THIS placement the tile is an interior member of a tex_bg strip.  Confirmed
    # in st01 (OCL 2605-2606, clut_base 0xD6-0xD7): a 2-tile gap inside the lockstep
    # background run 2600-2615 (clut_base 0xD1-0xE0), drawn as a diagonal "smear"
    # interrupting the mossy-rock cluster wherever those two slots are placed.
    #
    # Bridge a maximal run of tex-routed tiles when it is a genuine interior gap of a
    # long lockstep tex_bg strip:
    #   - the run lies on one page with clut_base advancing in lockstep with the OCL
    #     index (idx+1 ↔ clut_base+1), and the SAME lockstep continues unbroken across
    #     the brackets on both sides;
    #   - the tile immediately before the run and immediately after it are BOTH already
    #     tex_bg (the run is interior, not a strip end — strip ends are handled by
    #     strip_tail_extend);
    #   - the gap is at most _GAP_MAX tiles wide (a short dropout, not a foreground
    #     object spanning the strip);
    #   - the combined bracketing tex_bg run (left + right lockstep members) spans at
    #     least _GAP_MIN_BRACKET tiles (a real background strip, not a stray pair); and
    #   - tex_bg holds real pixels at every gap tile (background art to draw).
    # The lockstep-continuity + both-sides-bracketed + bracket-length gates make this
    # provably confined to interior dropouts of a continuous background strip; verified
    # across every X6 stage to add only st01's 2 tiles and touch nothing else.
    _GAP_MAX = 4
    _GAP_MIN_BRACKET = 12
    pre_bridge = frozenset(extra)

    def _bg_run_len(start: int, step: int, page: int, cb0: int) -> int:
        """Length of the lockstep tex_bg run from `start` going by `step` (±1)."""
        n = 0
        k = start
        want = cb0
        while (0 <= k < len(ocl) and k in pre_bridge and (ocl[k].pad & 0xF) == page
               and ocl[k].clut_base == want):
            n += 1; k += step; want += step
        return n

    if interior_gap_bridge:
        idx = 1
        while idx < len(ocl):
            if idx in pre_bridge:
                idx += 1; continue
            entry = ocl[idx]
            page = entry.pad & 0xF
            # Left bracket: previous index must be a tex_bg lockstep predecessor.
            prev = ocl[idx - 1]
            if (page >= 8 or (idx - 1) not in pre_bridge
                    or (prev.pad & 0xF) != page
                    or prev.clut_base != entry.clut_base - 1):
                idx += 1; continue
            # Collect the maximal run of tex (not-bg) lockstep tiles starting at idx.
            run = [idx]
            j = idx + 1
            while (j < len(ocl) and j not in pre_bridge and (ocl[j].pad & 0xF) == page
                   and ocl[j].clut_base == ocl[j - 1].clut_base + 1
                   and len(run) <= _GAP_MAX):
                run.append(j); j += 1
            # Right bracket: tile after the run must be a tex_bg lockstep successor.
            nxt = ocl[j] if j < len(ocl) else None
            ok = (len(run) <= _GAP_MAX and nxt is not None and j in pre_bridge
                  and (nxt.pad & 0xF) == page
                  and nxt.clut_base == ocl[j - 1].clut_base + 1)
            if ok:
                left_len = _bg_run_len(idx - 1, -1, page, entry.clut_base - 1)
                right_len = _bg_run_len(j, +1, page, nxt.clut_base)
                if left_len + right_len >= _GAP_MIN_BRACKET:
                    for g in run:
                        e = ocl[g]
                        cordX = e.clut_base & 0xF
                        cordY = (e.clut_base >> 4) & 0xF
                        gx = (page % 8) * 256 + cordX * TILE_SIZE
                        gy = (page // 8) * 256 + cordY * TILE_SIZE
                        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                            continue
                        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                            continue
                        extra.add(g)
            idx = j + 1 if ok else idx + 1

    # ── Palette-fan col split ─────────────────────────────────────────────────
    #
    # A texture coordinate shared by MANY distinct `col` (palette) values is a tile
    # that has been recolored into several palette variants: the foreground
    # variants (the stage-select boss panels, the st05/st02 recolored objects) plus
    # ONE chr256 background variant at the same coordinate.  The base routing's
    # large-gap different-col rules route ALL the far/different-col occurrences to
    # chr256, so the intermediate FOREGROUND recolors get wrongly read from the
    # (often fragmentary) background sheet.
    #
    # Within such a fan, the chr256 background variant is the one whose col sits in
    # the high band (col >= X6_CHR256_COL_MIN — the 0x70/0xA0/0xB0 chr256 palette
    # rows seen as col 112/121/126/160/176 in stsel/st02/st05); the lower-col
    # variants are foreground recolors and read tex.  Per-col (not per-coordinate)
    # is essential: an earlier per-coordinate version moved the whole group and so
    # also dragged the genuine col>=112 background onto tex (the st02/st05
    # regressions).
    #
    # The split only fires where a coordinate is fanned across
    # >= X6_PALETTE_FAN_MIN_COLS distinct cols.  Empirically that occurs ONLY on
    # stsel_eng / st02 / st05 — every settled gameplay stage has zero chr256
    # entries at such coords — so they are provably untouched.  Requiring BOTH a
    # high-band and a low-band member confines it to genuine mixed fg/bg fans and
    # avoids inverting same-band groups (e.g. st00's col=112 foreground over a
    # col=24 background, which never reaches >= 4 cols anyway).
    #
    # An all-low-band fan (NO col>=X6_CHR256_COL_MIN member, e.g. stsel's page-0
    # stage-name text, cols 35-40) has no background variant to anchor the split.
    # It is routed entirely to tex when tex_background is NOT a solid tile there
    # (bg_fill < 3/4 area) and tex holds some pixel data — i.e. the chr256 slot is
    # only fragments while the real glyph art lives in tex.  The solid-bg gate is
    # what keeps real all-low-band chr256 backgrounds on tex_bg: st05's page-0/1/2
    # recolor fans are fully painted (bg_fill == 256), so they are left alone.
    # Verified: among all X6 stages, only stsel_eng has all-low-band fans whose
    # background is non-solid, so no settled gameplay stage is affected.
    SOLID_FILL = (TILE_SIZE * TILE_SIZE * 3) // 4
    if palette_fan_guard:
        members_by_coord: dict[tuple, list[int]] = {}
        for i, entry in enumerate(ocl):
            members_by_coord.setdefault((entry.pad & 0xF, entry.clut_base), []).append(i)
        # Cols confirmed as foreground "text/recolor" palettes by the all-low-band
        # fan rule below; used to recover narrower (2-3 col) members of the same
        # recolored glyph set that fall under X6_PALETTE_FAN_MIN_COLS.  Empty for
        # every settled stage (none has such fans), so this never affects gameplay.
        fg_text_cols: set[int] = set()
        for (page, clut_base), idxs in members_by_coord.items():
            cols = {ocl[i].col for i in idxs}
            if len(cols) < X6_PALETTE_FAN_MIN_COLS:
                continue
            cordX = clut_base & 0xF
            cordY = (clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # Routing only matters where the two sheets actually differ here.
            if all(tx_raw[(gy + dy) * tx_w + gx + dx] == bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            has_hi = any(c >= X6_CHR256_COL_MIN for c in cols)
            has_lo = any(c < X6_CHR256_COL_MIN for c in cols)
            if has_hi and has_lo:
                # Mixed fan: the lower-col variants are foreground recolors — remove
                # them from chr256.  The high-band variant's placement is LEFT TO THE
                # BASE ROUTING: it already routes genuine chr256 backgrounds (st05
                # col126, st02 col160/176) to tex_bg, and correctly keeps stsel's
                # col112 panel palette on tex.  Forcing high-band entries into chr256
                # here wrongly dragged those stsel panels onto the sparse background.
                for i in idxs:
                    if ocl[i].col < X6_CHR256_COL_MIN:
                        extra.discard(i)    # low-band variant → foreground (tex)
            elif not has_hi:
                # All-low-band fan: foreground when the chr256 slot is only
                # fragments (not a solid tile) and tex actually holds art.
                fg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if tx_raw[(gy + dy) * tx_w + gx + dx])
                bg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if bg_raw[(gy + dy) * bg_w + gx + dx])
                if bg_fill < SOLID_FILL and fg_fill > 0:
                    for i in idxs:
                        extra.discard(i)
                    fg_text_cols |= cols   # remember these recolor palettes

        # Recovery pass: a recolored glyph set may also appear with FEWER palette
        # variants (e.g. stsel's stage-name text at cb 0x12-0x15 uses only cols
        # 39/40, below X6_PALETTE_FAN_MIN_COLS).  Promote any remaining chr256 tile
        # whose col belongs to a confirmed text/recolor palette set, on an all-low
        # coordinate whose background is non-solid and whose foreground holds art.
        # Gated by fg_text_cols, which is empty on every gameplay stage.
        if fg_text_cols:
            for (page, clut_base), idxs in members_by_coord.items():
                if any(ocl[i].col >= X6_CHR256_COL_MIN for i in idxs):
                    continue
                if not any(i in extra and ocl[i].col in fg_text_cols for i in idxs):
                    continue
                cordX = clut_base & 0xF
                cordY = (clut_base >> 4) & 0xF
                gx = (page % 8) * 256 + cordX * TILE_SIZE
                gy = (page // 8) * 256 + cordY * TILE_SIZE
                if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                        gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                    continue
                bg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if bg_raw[(gy + dy) * bg_w + gx + dx])
                fg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if tx_raw[(gy + dy) * tx_w + gx + dx])
                if bg_fill < SOLID_FILL and fg_fill > 0:
                    for i in idxs:
                        if ocl[i].col in fg_text_cols:
                            extra.discard(i)

    # ── Foreground/background pair recovery ───────────────────────────────────
    # A small-span (< CHR256_PAIR_GAP) page<8 group whose members were ALL routed to
    # chr256 by the base "no-large-gap whole-group" rule is sometimes really a
    # foreground/background DUPLICATE pair: the FIRST occurrence is the foreground
    # tile (its art lives in tex) and the later occurrence(s) are the chr256
    # background variant.  _build_chr256_ocl_indices._nolg_first_is_fg_pair catches
    # only the sparse-fragment form (fg*3 <= bg over a solid bg) and skips 0x38
    # first occurrences, so fully-painted foreground tiles (e.g. st0h's pole/chain
    # columns, tex_fill ~256) slip through and read the background sheet.
    #
    # Recover the first occurrence to tex when its coordinate holds non-empty tex
    # pixels that DIFFER from tex_bg (a genuine distinct foreground tile).
    if fg_pair_fix:
        # The chr256 background variant sits within this many OCL indices of the
        # foreground first occurrence for a genuine TIGHT fg/bg pair — st0h's
        # pole/chain pairs span at most 261.  Stages whose near-threshold no-large-gap
        # groups are real recolor batches (first occurrence correctly chr256
        # background) keep their second member farther away: st04a 307, st04b 347+,
        # st03 430.  This empirically-derived bound isolates the st0h pole case and
        # leaves every other X6 stage byte-identical; a looser bound regressed st03
        # (its dark-metal first occurrences turned to garbage when forced onto tex).
        CHR256_PAIR_MAX_GAP = 280
        groups: dict[tuple, list[int]] = {}
        for i, entry in enumerate(ocl):
            if (entry.pad & 0xF) < 8:
                groups.setdefault((entry.pad & 0xF, entry.clut_base), []).append(i)
        for (page, clut_base), idxs in groups.items():
            if len(idxs) < 2:
                continue
            s = sorted(idxs)
            if (s[1] - s[0]) >= CHR256_PAIR_MAX_GAP:
                continue                       # background variant too far → not a tight pair
            if not all(i in extra for i in s):
                continue                       # only the "whole group → chr256" case
            cordX = clut_base & 0xF
            cordY = (clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            fg_nonempty = any(tx_raw[(gy + dy) * tx_w + gx + dx]
                              for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            differs = any(tx_raw[(gy + dy) * tx_w + gx + dx] != bg_raw[(gy + dy) * bg_w + gx + dx]
                          for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            if fg_nonempty and differs:
                extra.discard(s[0])            # first occurrence → foreground (tex)

    # ── Foreground duplicate-strip recovery (seam-continuity vote) ────────────
    #
    # fg_pair_fix above recovers TIGHT foreground/background pairs (second member
    # within CHR256_PAIR_MAX_GAP=280 of the first).  A foreground tilemap stored as a
    # long contiguous strip whose every tile ALSO has a recolored duplicate FARTHER
    # away slips through: each (page, clut_base) is a no-large-gap group (span < 500,
    # so the base routing sends the whole group to tex_bg) but the second occurrence
    # sits 300-450 indices out — past the 280 bound that fg_pair_fix uses to avoid
    # regressing st03 (gap 430) and st04a (307).  Confirmed in st04b: OCL 1020-1156
    # (page 1, col=9, clut_base 0x48-0xD0) is the Recycle-Lab floor/machinery strip,
    # each tile reused in other areas as a col 5/16/21/22 recolor; all 137 first
    # occurrences were pinned to tex_bg and the floor rendered as scrambled garbage.
    #
    # The gap bound can't be widened without regressing st03/st04a (their first
    # occurrences ARE the background and belong on tex_bg), and within-tile coherence
    # does not separate them.  The decisive signal is SEAM CONTINUITY along the strip:
    # the CORRECT sheet renders texture-adjacent tiles (clut_base, clut_base+1) with a
    # continuous shared edge, the wrong sheet with a discontinuity.  Aggregated over a
    # whole lockstep run this cleanly separates the cases — mean seam |Δ| ratio
    # (tex_bg / tex): st04b 1.8 (tex continuous → foreground) vs st03 0.3, st04a 0.8,
    # st08x 1.0 (tex_bg continuous → stay background).
    #
    # For each maximal lockstep run (consecutive OCL index + clut_base, same page) of
    # FIRST occurrences of multi-col duplicate groups that are STILL wholly routed to
    # tex_bg at this point (so stsel/st0i/st0h, already moved to tex by the palette-fan
    # and fg_pair_fix passes above, are not candidates), route the whole run to tex
    # when the run spans >= _FGSTRIP_MIN_RUN tiles and the tex seams are clearly more
    # continuous than tex_bg (ratio >= _FGSTRIP_SEAM_RATIO).  Verified across every X6
    # stage to fire on st04b's strip alone and leave all other stages byte-identical.
    _FGSTRIP_MIN_RUN = 8
    _FGSTRIP_SEAM_RATIO = 1.4

    def _seam(raw: bytes, w: int, h: int, gx0: int, gy0: int, gx1: int, gy1: int) -> float:
        """Mean |Δ| down the vertical seam between tile0's right edge and tile1's left edge."""
        if (max(gy0, gy1) + TILE_SIZE > h or gx0 + TILE_SIZE > w or gx1 + TILE_SIZE > w):
            return -1.0
        tot = cnt = 0
        for dy in range(TILE_SIZE):
            a = raw[(gy0 + dy) * w + gx0 + TILE_SIZE - 1]
            b = raw[(gy1 + dy) * w + gx1]
            if a or b:
                tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    if fg_strip_recover:
        groups_fs: dict[tuple, list[int]] = {}
        for i, e in enumerate(ocl):
            groups_fs.setdefault((e.pad & 0xF, e.clut_base), []).append(i)

        def _is_fg_strip_cand(i: int) -> bool:
            e = ocl[i]
            page = e.pad & 0xF
            if page >= 8 or i not in extra:
                return False
            idxs = groups_fs[(page, e.clut_base)]
            if len(idxs) < 2 or min(idxs) != i:
                return False                       # only a group's first occurrence
            return len({ocl[j].col for j in idxs}) >= 2   # mixed-col duplicate (fg/bg pair shape)

        def _xy(e: OclEntry) -> tuple[int, int]:
            page = e.pad & 0xF
            cordX = e.clut_base & 0xF
            cordY = (e.clut_base >> 4) & 0xF
            return (page % 8) * 256 + cordX * TILE_SIZE, (page // 8) * 256 + cordY * TILE_SIZE

        i = 0
        nocl = len(ocl)
        while i < nocl:
            if not _is_fg_strip_cand(i):
                i += 1; continue
            run = [i]
            j = i + 1
            while (j < nocl and _is_fg_strip_cand(j)
                   and (ocl[j].pad & 0xF) == (ocl[j - 1].pad & 0xF)
                   and ocl[j].clut_base == ocl[j - 1].clut_base + 1):
                run.append(j); j += 1
            if len(run) >= _FGSTRIP_MIN_RUN:
                sum_t = sum_b = 0.0
                ns = 0
                for k in range(len(run) - 1):
                    gx0, gy0 = _xy(ocl[run[k]])
                    gx1, gy1 = _xy(ocl[run[k + 1]])
                    s_t = _seam(tx_raw, tx_w, tx_h, gx0, gy0, gx1, gy1)
                    s_b = _seam(bg_raw, bg_w, bg_h, gx0, gy0, gx1, gy1)
                    if s_t >= 0 and s_b >= 0:
                        sum_t += s_t; sum_b += s_b; ns += 1
                if ns and sum_t > 0 and (sum_b / sum_t) >= _FGSTRIP_SEAM_RATIO:
                    for g in run:
                        extra.discard(g)           # whole strip → foreground (tex)
            i = j

    # ── Garbage-foreground whole-page flip ────────────────────────────────────
    #
    # Some X6 stages store a background tileset across an ENTIRE page<8 as sole
    # entries (each (page, clut_base) coordinate appears exactly once, so there
    # are no multi-entry groups for the base routing's group rules to act on),
    # while that page's FOREGROUND sheet (tex) is corrupt — high-frequency striped
    # garbage — and the chr256 sheet (tex_bg) holds the real, coherent tile art.
    # Because the entries are sole and tex is non-empty (it is garbage, not blank),
    # none of the chr256 routing reaches them and the whole page renders as the
    # striped/garbled mess reported on st04a (pages 2 & 3) and st03 (page 5).
    #
    # The distinguishing signal is NOT fill or tex≠tex_bg difference — those also
    # match pages where tex is the CORRECT sheet and tex_bg is the garbage one
    # (st05 pages 4-7, st08 page 7) or where tex_bg is simply EMPTY (st0g pages
    # 2-3); routing those to tex_bg would regress them.  The only reliable
    # discriminator is COHERENCE: striped garbage has a high mean absolute
    # horizontal-neighbour difference of raw 8bpp indices (≈3.6-6.4 across the
    # corrupt pages), while coherent tile art has smooth runs (≈0.5-1.2).
    #
    # Flip a page tex→tex_bg only when ALL hold (verified across every X6 stage to
    # fire on exactly st03 p5, st04a p2, st04a p3 and nothing else):
    #   - page<8 and ≥95% of its entries are sole (no group rules apply);
    #   - ≥ _GPF_MIN_SOLE of those sole entries are still on tex;
    #   - tex_bg is non-empty over the page (it has real art to draw);
    #   - coh_tex ≥ _GPF_GARBAGE_MIN (tex is striped garbage); and
    #   - coh_bg ≤ coh_tex × _GPF_CLEAN_RATIO (tex_bg is clearly more coherent).
    # The ratio gate also excludes identical-sheet pages (coh_tex == coh_bg, e.g.
    # st06a/st06x, where routing is irrelevant anyway).
    _GPF_GARBAGE_MIN = 2.5
    _GPF_CLEAN_RATIO = 0.5
    _GPF_FRAC_SOLE = 0.95
    _GPF_MIN_SOLE = 40
    _GPF_BGFILL_MIN = 0.05

    def _page_coherence(raw: bytes, w: int, h: int, clut_bases, page: int) -> float:
        """Mean |horizontal-neighbour diff| of nonzero raw px over a page's tiles."""
        tot = cnt = 0
        for cb in clut_bases:
            cordX = cb & 0xF; cordY = (cb >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if gx + TILE_SIZE > w or gy + TILE_SIZE > h:
                continue
            for dy in range(TILE_SIZE):
                base = (gy + dy) * w + gx
                for dx in range(TILE_SIZE - 1):
                    a = raw[base + dx]; b = raw[base + dx + 1]
                    if a or b:
                        tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    def _page_bg_fill(clut_bases, page: int) -> float:
        """Fraction of nonzero tex_bg pixels over a page's tiles."""
        nz = total = 0
        for cb in clut_bases:
            cordX = cb & 0xF; cordY = (cb >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                continue
            for dy in range(TILE_SIZE):
                base = (gy + dy) * bg_w + gx
                for dx in range(TILE_SIZE):
                    if bg_raw[base + dx]:
                        nz += 1
                    total += 1
        return nz / total if total else 0.0

    if garbage_page_flip:
        # Per page<8: collect entry indices and coordinate occurrence counts.
        pg_entries: dict[int, list[int]] = {}
        pg_coord_count: dict[tuple, int] = {}
        for idx, entry in enumerate(ocl):
            page = entry.pad & 0xF
            if page >= 8:
                continue
            pg_entries.setdefault(page, []).append(idx)
            k = (page, entry.clut_base)
            pg_coord_count[k] = pg_coord_count.get(k, 0) + 1

        for page, idxs in pg_entries.items():
            sole = [i for i in idxs
                    if pg_coord_count[(page, ocl[i].clut_base)] == 1]
            if len(sole) / len(idxs) < _GPF_FRAC_SOLE:
                continue
            sole_on_tex = [i for i in sole if i not in extra]
            if len(sole_on_tex) < _GPF_MIN_SOLE:
                continue
            distinct_cb = {ocl[i].clut_base for i in idxs}
            if _page_bg_fill(distinct_cb, page) < _GPF_BGFILL_MIN:
                continue
            coh_tex = _page_coherence(tx_raw, tx_w, tx_h, distinct_cb, page)
            coh_bg = _page_coherence(bg_raw, bg_w, bg_h, distinct_cb, page)
            if coh_tex < _GPF_GARBAGE_MIN or coh_bg > coh_tex * _GPF_CLEAN_RATIO:
                continue
            # tex is striped garbage, tex_bg holds the coherent art: route every
            # entry on this page whose tex_bg coordinate is non-empty to tex_bg.
            for i in idxs:
                cordX = ocl[i].clut_base & 0xF
                cordY = (ocl[i].clut_base >> 4) & 0xF
                gx = (page % 8) * 256 + cordX * TILE_SIZE
                gy = (page // 8) * 256 + cordY * TILE_SIZE
                if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                    continue
                if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                    extra.add(i)

    # ── Background-strip tail extension ───────────────────────────────────────
    #
    # A chr256 background tileset is sometimes stored as a foreground/background
    # DUPLICATE-PAIR batch: each (page, clut_base) coordinate appears twice — the
    # first occurrence (low OCL index) is the foreground tile (tex) and the second
    # (high index, different col) is the chr256 background variant (tex_bg), routed
    # by the base large-gap different-col rule (omp.py Pass 2 / Pass 3c).  The
    # second-occurrence halves form ONE contiguous OCL run whose indices and
    # clut_base advance in lockstep on a single page (e.g. st01 page-7 OCL
    # 3763-3827 ↔ clut_base 0x00-0x40, the Amazon river/ground background row).
    #
    # When the TAIL of such a strip loses its foreground partners, those coordinates
    # exist only as SOLE entries (n=1) — they continue the very same contiguous run
    # (st01 OCL 3828-3838 ↔ clut_base 0x41-0x4B, same page 7) but, having no
    # duplicate, the pair rule never fires and they default to tex.  Page 7's tex
    # sheet there is the corrupt striped foreground (coh ≈ 4.5-6.2) while tex_bg
    # holds the coherent art (coh ≈ 0.6-2.0), so they render as the garbled tiles
    # reported at level (176-179, 358-360).  The per-page garbage flip can't help
    # (page 7 is 92% paired, not a garbage page) and the single-hole gap-fill can't
    # bridge a contiguous run (each tile's idx+1 neighbour is also still on tex).
    #
    # Extend the strip: a tex-routed entry whose immediate index predecessor (idx-1)
    # is a confirmed tex_bg tile on the SAME page with clut_base exactly one less is
    # the next member of that background strip.  Route it to tex_bg when —
    #   - the backward lockstep tex_bg run through idx-1 spans ≥ _STE_MIN_RUN tiles
    #     (a genuine strip, not a stray pair);
    #   - tex_bg holds real pixels at the coordinate (background art to draw); and
    #   - the tex tile is EITHER empty (would render a transparent hole) OR striped
    #     garbage (coh ≥ _STE_GARBAGE_MIN and tex_bg clearly more coherent).  A
    #     coherent foreground tile fails this content gate and halts the extension,
    #     so the run can never bleed past the end of the real background strip.
    # Iterating index-ascending carries the flip down the whole tail (each freshly
    # flipped tile becomes the predecessor anchor for the next).
    #
    # Regression safety: structurally this only ever appends to the END of an
    # already-confirmed background strip (lockstep index+clut_base on one page), and
    # the content gate restricts it to empty or striped-garbage tex tiles — exactly
    # the tiles that rendered nothing or garbage before.  Each level cell maps to one
    # OCL index, so a flip can neither move nor occlude any other tile.  Verified
    # across every X6 stage to add only such strip-tail tiles (st01 +11) and touch
    # nothing on the settled stages.
    _STE_GARBAGE_MIN = 2.5
    _STE_CLEAN_RATIO = 0.5
    _STE_MIN_RUN = 8

    def _tile_coh(raw: bytes, w: int, gx: int, gy: int) -> float:
        """Mean |horizontal-neighbour diff| of nonzero raw px over one tile."""
        tot = cnt = 0
        for dy in range(TILE_SIZE):
            base = (gy + dy) * w + gx
            for dx in range(TILE_SIZE - 1):
                a = raw[base + dx]; b = raw[base + dx + 1]
                if a or b:
                    tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    def _bg_strip_run_back(idx: int, page: int, cb: int) -> int:
        """Length of the lockstep tex_bg strip ending at idx-1 (consecutive index + clut_base)."""
        n = 0
        k = idx - 1
        want_cb = cb - 1
        while (k >= 0 and k in extra and (ocl[k].pad & 0xF) == page
               and ocl[k].clut_base == want_cb):
            n += 1; k -= 1; want_cb -= 1
        return n

    if strip_tail_extend:
        for idx in range(1, len(ocl)):
            if idx in extra:
                continue
            entry = ocl[idx]
            page = entry.pad & 0xF
            if page >= 8:
                continue
            if (idx - 1) not in extra:
                continue
            prev = ocl[idx - 1]
            if (prev.pad & 0xF) != page or prev.clut_base != entry.clut_base - 1:
                continue
            cordX = entry.clut_base & 0xF
            cordY = (entry.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if _bg_strip_run_back(idx, page, entry.clut_base) < _STE_MIN_RUN:
                continue
            # Content gate: empty tex (transparent hole) or striped garbage tex.
            fg_empty = not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                               for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            if not fg_empty:
                coh_tex = _tile_coh(tx_raw, tx_w, gx, gy)
                coh_bg = _tile_coh(bg_raw, bg_w, gx, gy)
                if coh_tex < _STE_GARBAGE_MIN or coh_bg > coh_tex * _STE_CLEAN_RATIO:
                    continue
            extra.add(idx)

    # ── Background-batch empty-hole suppression ───────────────────────────────
    #
    # After all routing (including the garbage-page flip above), a few tiles can
    # remain on tex as INTERIOR stragglers inside a chr256 background batch: both
    # their OCL-index neighbours route to tex_bg on the same page, but the tile's
    # OWN tex_bg slot is empty, so the base/flip routing left it on tex.  When that
    # tile's tex slot holds the corrupt striped-garbage foreground, it renders as a
    # garbage box surrounded by clean background (st03's two remaining holes:
    # ocl 2676 page 4, ocl 2747 page 5).  There is no real art for the tile in
    # EITHER sheet, so the correct render is transparent — route it to the empty
    # tex_bg slot (all-zero pixels → fully transparent paste) instead of drawing
    # the garbage.
    #
    # Gates (verified to touch EXACTLY these 2 placed tiles across all X6 stages —
    # zero impact elsewhere):
    #   - tile currently on tex (not already chr256), page<8;
    #   - both OCL neighbours (idx-1, idx+1) route to tex_bg, on the SAME page
    #     (interior to a contiguous background batch — not a lone foreground tile);
    #   - tex_bg is fully empty at the tile's coordinate (no background art); and
    #   - tex is non-empty (there is garbage to suppress; an already-empty tex tile
    #     renders nothing regardless, so adding it would be a redundant no-op).
    # The neighbour gate is what keeps genuine sparse foreground tiles (sparkles,
    # edges, glyph pixels with high coherence but no surrounding bg batch) on tex.
    if bg_empty_hole_fill:
        for idx in range(1, len(ocl) - 1):
            if idx in extra:
                continue
            entry = ocl[idx]
            page = entry.pad & 0xF
            if page >= 8:
                continue
            if (idx - 1) not in extra or (idx + 1) not in extra:
                continue
            if (ocl[idx - 1].pad & 0xF) != page or (ocl[idx + 1].pad & 0xF) != page:
                continue
            cordX = entry.clut_base & 0xF
            cordY = (entry.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # tex_bg fully empty (no real art) and tex non-empty (garbage to hide).
            if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Page>=8 background-strip garbage-hole suppression ─────────────────────
    #
    # bg_empty_hole_fill suppresses garbage holes interior to a page<8 background
    # batch, keyed on OCL-index neighbours.  The page>=8 chr256 strips are ordered
    # by clut_base WITHIN a (page, col), not by OCL index, so an interior empty-tex_bg
    # hole there is invisible to index-neighbour logic.  st08's machinery gap (page
    # 11, col 10, clut_base 0xF1-0xF4) is such a block: 4 placed tiles whose tex_bg
    # slot is empty sit inside the clut_base span of the 136-tile (page 11, col 10)
    # background strip, with tex_bg-routed members at both lower and higher clut_base.
    # Their tex holds striped garbage (coh 8-70), drawn as colourful streaks in the
    # dark machinery.  No art exists in either sheet for these slots, so the correct
    # render is transparent — route them to the empty tex_bg.
    #
    # Gated to fire on exactly these tiles (verified zero elsewhere across X6):
    #   - page in 8..0xB, tile currently on tex, tex_bg fully empty at its coordinate;
    #   - tex holds striped garbage (coh_tex >= _PG8H_GARBAGE_MIN); and
    #   - the tile's (page, col) strip has a tex_bg-routed member at BOTH a smaller and
    #     a larger clut_base (the hole is interior to a real background strip, not a
    #     lone foreground tile).
    # Like bg_empty_hole_fill this is pixel-additive: it only routes already-garbage
    # placed tiles to an empty (transparent) slot, never altering any other tile.
    _PG8H_GARBAGE_MIN = 5.0
    if pg8_garbage_hole_suppress:
        bg_cb_by_pagecol: dict[tuple, list[int]] = {}
        for i, e in enumerate(ocl):
            if (e.pad & 0xF) >= 8 and i in extra:
                bg_cb_by_pagecol.setdefault((e.pad & 0xF, e.col), []).append(e.clut_base)
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            page = entry.pad & 0xF
            if page < 8 or page > 0xB:
                continue
            members = bg_cb_by_pagecol.get((page, entry.col))
            if not members:
                continue
            cb = entry.clut_base
            if not (any(c < cb for c in members) and any(c > cb for c in members)):
                continue
            cordX = cb & 0xF
            cordY = (cb >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * TILE_SIZE
            gy = (page // 8) * 256 + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # tex_bg fully empty (no background art).
            if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            # tex is striped garbage (otherwise it may be a legitimate sparse tile).
            if _tile_coh(tx_raw, tx_w, gx, gy) < _PG8H_GARBAGE_MIN:
                continue
            extra.add(idx)

    if stage_stem:
        # Per-stage sheet overrides: (col, page, pad_hi) GROUP table, plus a per-OCL-index
        # table for fixes that don't form a clean group.  Index entries win (more specific).
        # "bg" forces a tile INTO chr256 (read tex_bg); "tex" forces it OUT (read tex).
        group_ov = X6_SHEET_OVERRIDE_BY_STAGE.get(stage_stem, {})
        idx_ov = X6_SHEET_OVERRIDE_INDICES.get(stage_stem, {})
        if group_ov or idx_ov:
            for idx, entry in enumerate(ocl):
                sheet = idx_ov.get(idx) or group_ov.get(
                    (entry.col, entry.pad & 0xF, (entry.pad >> 4) & 0xF))
                if sheet == "bg":
                    extra.add(idx)
                elif sheet == "tex":
                    extra.discard(idx)
    return frozenset(extra)


# ── X6 per-stage CLUT-row fixes ─────────────────────────────────────────────────
#
# Some X6 page>=8 (second-VRAM-half) tiles render with the wrong colours because
# their true static palette is NOT at the universal ``col + 64`` CLUT row.  The
# shared colXX.col VRAM dump does hold the correct colours, but at a different row.
#
# The correction is genuinely PER-TILE, NOT per-col: tiles that share the same ``col``
# can need different CLUT rows.  In st04a the hydraulic-press tiles (OCL 923-952, col=16)
# need row 192, yet HUNDREDS of OTHER col=16 page>=8 tiles (OCL 436-652, 968+) are
# already correct at row 80 — keying a fix by abs_clut/col remaps all of them and
# regresses those regions.  Fixes are therefore keyed by explicit OCL INDEX, each
# range validated against an in-game screenshot (experimental/diag_groundtruth_match.py
# + diag_align_recover.py).  page<8 tiles are unaffected — their ``col + 64`` is correct.
#
# Keyed by OMP stem -> {ocl_idx : corrected CLUT row}.
def _rows(*ranges_or_idx):
    out: dict[int, int] = {}
    for r in ranges_or_idx:
        idxs, row = r
        for i in (idxs if isinstance(idxs, range) else idxs):
            out[i] = row
    return out


X6_CLUT_ROW_FIXES: dict[str, dict[int, int]] = {
    # st04a (Recycle Lab Area 1): the hydraulic-press / scrap-machinery tiles at OCL
    # 923-952 (col=16) render muddy red-brown at row 80; their real grey-steel palette
    # is at row 192 (raw shared row 224).  Validated vs screenshots/x6-metal-shark.png
    # (err 1.8) and the in-game ST04A-B capture (grey steel + orange rust).  Other col=16
    # page>=8 tiles (e.g. OCL 436-652, 968+) are correct as-is and must NOT be remapped.
    #
    # OCL 152 + 179-201 (page 11, col=0) are the grey-steel scrap-machinery tileset; at
    # their col+64 row 64 they render orange-rust, but their true palette is row 288 — the
    # same grey-steel CLUT the col=224 machinery tiles already use.  Confirmed tiles
    # (152, 179-191, 195-201) validated by matching the four x6-st04a-patch-*.png ground-
    # truth captures (per-tile RMS over opaque pixels, layer-1/2 red background excluded):
    # error drops from ~80-190 at row 64 to ~3-10 at row 288.  193-194 are inferred — they
    # sit inside the same clut_base-contiguous col=0 strip between confirmed members; no
    # capture covers them.  Scoped to these indices only: col=0 -> row 64 is CORRECT for
    # the hundreds of page 9-10 background tiles, so this is NOT generalised.
    #
    # Deliberately EXCLUDED (no confident fix yet):
    #   - page-11 col=0 tiles 523-530 (placed up to 768x): tex and chr256 hold IDENTICAL
    #     coherent index data here (not a routing bug, not corrupt; 527 is a flat fill),
    #     but no CLUT row tested — incl. 64 and 288 — gives clearly-correct colours, so
    #     their true palette is unknown without a ground-truth capture.  Left at col+64.
    #   - patch-4 top tiles 869-882 / 920-922 are sprite-occluded in the capture.
    #
    # A SECOND col=16 machinery batch (OCL 202 + a 1516-1615 subset, page 10/11) was
    # flagged "too orange": identical class to 923-952 (col=16 renders orange-rust at row
    # 80, grey-steel at row 192).  Discriminator confirmed by adjacent tiles that render
    # fine (col=128 -> 192, col=208 -> 272 via col+64) and a row-80-vs-192 contact sheet
    # (every flagged index turns clean grey-steel at 192).  Inference from the validated
    # col=16->192 precedent, not a per-pixel capture — none covers these.  Kept as an
    # explicit index list because OTHER col=16 page>=8 tiles (436-652, 968+) ARE correct
    # at row 80, so col=16 must never be blanket-remapped.
    "st04a": _rows(
        (range(923, 953), 192),
        ([152], 288),
        (range(179, 192), 288),   # 179-191 (confirmed)
        (range(193, 202), 288),   # 193-201 (195-201 confirmed; 193-194 inferred)
        # Machinery-TOP band (col=0, page=10, pad_hi=4): the grey-steel armor plating
        # above the col=16 body (923-952 -> 192).  Routed back to tex by
        # X6_SHEET_OVERRIDE_INDICES; at the pad_hi (0,10)->192 default it renders rusty-brown,
        # so pin it to row 288 — the same col=0 grey-steel CLUT as the page-11 scrap tiles
        # (152/179-201).  RMS-validated vs x6-st04a-patch-x3136_y304-x3199_y431.png:
        # mean 7.1 @288 vs 81.2 @192 (experimental/diag_top_palette_st04a.py).  Skips
        # 874/879 (col=64 pad_hi=0 left-edge tiles).  NOT applied to the col=0/page-10
        # batch 1505-1612 (separate structure, no capture) — hence per-index, not (0,10).
        (sorted((set(range(868, 884)) - {874, 879}) | {920, 921, 922}), 288),
        ([202, 1516, 1517, 1520, 1521, 1522, 1525, 1526, 1527, 1536, 1537, 1538, 1539,
          1543, 1544, 1545, 1546, 1547, 1548, 1549, 1550, 1551, 1552, 1565, 1566, 1567,
          1568, 1569, 1570, 1571, 1574, 1575, 1576, 1577, 1578, 1579, 1580, 1581, 1582,
          1583, 1584, 1587, 1588, 1589, 1611, 1613, 1614, 1615], 192),  # user-flagged "too orange"
    ),
    # st04b col=0 pad_hi=4 tiles split by tile_type into two palettes (whole-tile matched
    # to the user's reference tiles): type 0x3A → col=6 light-grey ref (row 70); type 0x3F
    # → col=3 mid-grey ref (row 67).  Per-index because the (col,page) pad_hi table can't
    # key on tile_type.
    # st04b col=0 pad_hi=4 tiles → row 320 (same col=0 alt-bank row as st02/st06a/st0g).
    # These are 8bpp tiles whose pixels are 0xE0-0xFF (high-nibble 14/15), so the 8bpp
    # decode reads base+14/15.  clut_finder "clut 102" only matches a tile's LOW-nibble
    # pixels; for these high-nibble tiles clut-102-base reads raw rows 116/117 (dark) — NOT
    # row 102 — which is why row 70 (=clut102) rendered dark.  Matched to x6-st04b-right.png:
    # row 320 gives 684 (104,97,89)~(99,92,85), 686 (155,147,138)~(144,136,128).
    "st04b": _rows(
        ([684, 686, 967, 968, 969, 970, 971, 972, 973, 974, 975, 976, 977, 978, 979, 980], 320),
    ),
}


def build_x6_clut_row_override(
    stage_stem: str,
    ocl: list[OclEntry],
    chr256_set: "frozenset[int]",
) -> "dict[int, int] | None":
    """
    Return {ocl_idx: corrected_clut_row} for an X6 stage from X6_CLUT_ROW_FIXES, or
    None when the stage has no fixes.  Fixes are keyed by explicit OCL index (see
    X6_CLUT_ROW_FIXES) so only the validated tiles are relocated.  Indices beyond the
    stage's OCL table are dropped.  The chr256_set argument is accepted for signature
    stability but is not used (the CLUT row is texture-routing-independent).
    """
    fixes = X6_CLUT_ROW_FIXES.get(stage_stem)
    if not fixes:
        return None
    override = {idx: row for idx, row in fixes.items() if 0 <= idx < len(ocl)}
    return override or None


# ── X6 CLUT-bank rule (pad_hi) ───────────────────────────────────────────────────
#
# ROOT CAUSE of the page>=8 "wrong colour" machinery tiles: the OCL ``pad`` byte's
# HIGH nibble ``(pad >> 4) & 0xF`` is an X6 CLUT-bank selector that the universal
# ``col + 64`` lookup ignores — both this renderer and the game's own TeheManX4
# Draw16xTile discard it via ``page = (val >> 24) & 0xF``.  ``pad_hi == 0`` is correct
# at col+64 for all cols; ``pad_hi == 4`` occurs ONLY on the machinery tiles and needs
# an alternate CLUT bank in the BOTTOM half of VRAM.
#
# DATA-DERIVED DEFAULT: ``alt_row = X6_PADHI_DEFAULT_BANK + col`` (= 320 + col).  This is
# the +96 stage-CLUT offset (X6_STAGE_CLUT_OFFSET) mirrored into VRAM's bottom half: in
# normalized-palette space the page>=8 CLUTs sit at row 320+col.  Verified exact for st02
# (col0→320, col16→336), st06a col0→320, st04b col0→320, and st0g col0/16/80/96
# (→320/336/400/416).  See experimental/diag_bank_table_search.py for the reconciliation
# (full RXC2.exe survey found no separate per-stage bank table; the clut-anime tables hold
# only crystal dests 64-127).
#
# Per-stage EXCEPTIONS (X6_PADHI_ROW_BY_STAGE) override the default where a stage uploaded
# its alt CLUTs to a different bottom-half row.  These are genuine deviations (re-confirmed
# vs the rule, not mis-pins): st04a (whole stage, lower bank), st04b col=16, st0g col=32.
# A wrong row shows as a slight hue shift (right col band, wrong row) or a gross mismatch
# (wrong col entirely).  Validated by RMS (st04a) and ground-truth match (st04b, st0g).
# X6_CLUT_ROW_FIXES is still merged ON TOP in main() (takes precedence) for per-index cases
# the (col,page) table can't express (st04b col=0 tile_type split).
X6_PADHI_ALT_BANK = 4
X6_PADHI_DEFAULT_BANK = 320  # alt_row = 320 + col  (+96 stage-CLUT offset, bottom VRAM half)
X6_PADHI_ROW_BY_STAGE: dict[str, dict[tuple[int, int], int]] = {
    # stage -> {(col, page): alt_clut_row} for groups that DEVIATE from the 320+col default.
    # Everything not listed uses 320 + col.
    # st04a: whole-stage lower bank (col0→288, col16→192).  RMS-validated (err ~3-7);
    # (0,10)→192 is contact-sheet-only.
    "st04a": {(16, 9): 192, (16, 10): 192, (16, 11): 192, (0, 10): 192, (0, 11): 288},
    # st04b col=16: silver spikes at 368 (default 336 renders garbage — coherence-confirmed).
    "st04b": {(16, 10): 368},
    # st0g col=32: both pages → 288 (default 352 disagrees).  Verified vs ref OCL1813.
    "st0g":  {(32, 10): 288, (32, 11): 288},
}


def build_x6_padhi_clut_override(ocl: list[OclEntry], stage_stem: str) -> "dict[int, int]":
    """
    Return {ocl_idx: alt_clut_row} for every page>=8 tile whose ``pad`` high nibble is
    the alternate-bank selector (X6_PADHI_ALT_BANK).  The default row is the data-derived
    ``X6_PADHI_DEFAULT_BANK + col`` (320 + col); a per-(col, page) entry in
    X6_PADHI_ROW_BY_STAGE overrides it for stages whose alt CLUTs live elsewhere.
    Game-version-agnostic input; only meaningful for X6.
    """
    by_col_page = X6_PADHI_ROW_BY_STAGE.get(stage_stem, {})
    out: dict[int, int] = {}
    for idx, entry in enumerate(ocl):
        if (entry.pad >> 4) & 0xF != X6_PADHI_ALT_BANK:
            continue
        page = entry.pad & 0xF
        # Per-stage deviation wins; otherwise the universal 320 + col rule.
        out[idx] = by_col_page.get((entry.col, page), X6_PADHI_DEFAULT_BANK + entry.col)
    return out


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
        "--skip-catalog", action="store_true", default=True,
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
    [omp, ocl, tex, tex_background, flags_to_palette, game_version] = preload_related_files(omp_path)

    chr256_extra: "frozenset[int] | None" = None
    clut_row_fix: "dict[int, int] | None" = None
    if game_version == GameVersion.X6:
        chr256_extra = build_x6_chr256_override(ocl, tex, tex_background, omp_stem)
        # pad_hi CLUT-bank rule (data-driven, all stages) with the explicit per-index
        # X6_CLUT_ROW_FIXES merged ON TOP so validated rows win on any conflict (e.g.
        # st04a OCL 202).  Result: st04a's validated tiles are unchanged; only newly
        # covered pad_hi=4 tiles (declined page-10 col=0 batch, st04b, …) move.
        padhi_fix = build_x6_padhi_clut_override(ocl, omp_stem)
        explicit_fix = build_x6_clut_row_override(omp_stem, ocl, chr256_extra or frozenset()) or {}
        merged = {**padhi_fix, **explicit_fix}
        clut_row_fix = merged or None
        n_padhi_only = len(set(padhi_fix) - set(explicit_fix))
        print(f"  CLUT-row overrides: {len(padhi_fix)} pad_hi + {len(explicit_fix)} explicit "
              f"= {len(merged)} ({n_padhi_only} from pad_hi rule alone)")

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
            chr256_override=chr256_extra,
            clut_row_override=clut_row_fix,
        )
        if args.debug:
            _debug_overlay_catalog(catalog_img, omp.n_screens)
        catalog_out = output_dir / f"{omp_stem}_catalog.png"
        catalog_img.save(catalog_out)
        print(f"  Saved {catalog_out}  ({catalog_img.width}×{catalog_img.height} px)")

    layout_entry = STAGE_LAYOUT.get(f"X{game_version}", {}).get(omp_stem)

    # Level render (when layout is known)
    if layout_entry and not args.skip_stage:
        offset, w, h = layout_entry

        print(f"  (offset=0x{offset:08X}  w={w}  h={h})")
        print()

        print()

        if game_version == GameVersion.X4:
            print(f"Loading layout from RXC1.exe (layer {args.layer})...")
            layout = load_layout_from_exe(EXE_PATH_X4, offset=offset, width=w, height=h, layer=args.layer)
        else:
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
            chr256_override=chr256_extra,
            clut_row_override=clut_row_fix,
        )
        if args.debug:
            _debug_overlay_level(level_img, layout, n_sx, n_sy)
        level_out = output_dir / Path(f"{omp_stem}_level.png")
        level_img.save(level_out)
        print(f"  Saved {level_out}  ({level_img.width}×{level_img.height} px)")
    else:
        print()
        print(f"Stage layout unknown for {omp_stem}, skipping level render.")


if __name__ == "__main__":
    main()
