# OMP file format — Stage tile-screen catalog
#
# The OMP file is a catalog of screen data for a single stage layer (the main
# platform/collision layer). Each ROW in the OMP represents one complete 16×16
# tile screen (256 tiles). The ROW NUMBER is the screen_id used by the stage's
# map layout data. Each u16 cell is an index into the stage's OCL table.
# Zero entries are transparent/empty.
#
# ============================================================
# OMP binary structure (st000.omp, 54796 bytes — fully confirmed)
# ============================================================
#
#   Offset   Size    Content
#   ────────────────────────────────────────────────────────
#   0x0000   4 B     Magic: "OMP\x00"
#   0x0004   4 B     Reserved / version flags (= 0x00000001 LE)
#   0x0008   4 B     n_screens × 256 (LE u32; e.g. 107×256=27392 for st000)
#                    Each screen is 16×16 = 256 tiles.
#                    n_screens = value // 256  →  107 screens for st000.
#   0x000C   N×2 B   Screen data: n_screens × 256 LE u16 OCL indices
#                    Row stride: 256 × 2 = 512 bytes (one row = one screen)
#                    Value 0x0000 = empty/transparent
#                    Values are pure OCL indices (max observed = 0x0774 = 1908)
#
# File size check: 12 + 107 × 256 × 2 = 54,796 bytes ✓
#
# ============================================================
# Screen / tile addressing (confirmed against omp-to-expected-tiles.csv)
# ============================================================
#
#   To render level tile at position (lx, ly):
#
#     sx = lx // 16           # level screen x
#     sy = ly // 16           # level screen y
#     wx = lx % 16            # within-screen x (0–15)
#     wy = ly % 16            # within-screen y (0–15)
#
#     screen_id = layout[sy][sx]           # from LayoutTable (see below)
#     omp_row   = screen_id                # OMP row = screen_id
#     omp_col   = wy * 16 + wx             # within-screen tile index (x fast)
#     ocl_idx   = omp.tiles[omp_row][omp_col]
#
#   Confirmed with 4 data points:
#     level(3,69)   → omp_col=83  omp_row=26  layout[4][0]=26
#     level(72,68)  → omp_col=72  omp_row=30  layout[4][4]=30
#     level(0,63)   → omp_col=240 omp_row=11  layout[3][0]=11
#     level(141,64) → omp_col=13  omp_row=34  layout[4][8]=34
#
# ============================================================
# Layout table
# ============================================================
#
#   The map layout data is NOT stored in the OMP/OCL/TEX files. It lives in
#   the RXC1.exe and RXC2.exe files. It maps each level screen
#   position (sx, sy) to a screen_id (= OMP row index).
#
#   Supply a LayoutTable to render_level() for correct level rendering.
#   render_omp() renders the raw OMP screen catalog (no layout needed).
#
# ============================================================
# Tile rendering pipeline
# ============================================================
#
#   OMP u16 ocl_idx
#       └─▶ OCL entry [ocl_idx]          (utils/ocl.py)
#               col: int                 palette column; abs_clut = col + 64
#               tile_type: int           collision/behaviour type — maps to OclPaletteGroup
#               clut_base (byte2): encodes cordX (low nibble) + cordY (high nibble)
#               pad (byte3): encodes page number (low nibble)
#       └─▶ TEX raw_image  (utils/tex.py, FORMAT_8BPP = 0x12)
#               cordX = byte2 & 0xF
#               cordY = (byte2 >> 4) & 0xF
#               page  = byte3 & 0xF
#               gx = (page % 8) * 256 + cordX * 16
#               gy = (page // 8) * 256 + cordY * 16
#
# ============================================================
# TEX routing (tex vs tex_bg / chr256)
# ============================================================
#
#   Each stage has two tile TEX files:
#     stXXX.tex          — standard tileset (tex)
#     stXXX_chr256.tex   — background/chr256 tileset (tex_bg)
#
#   The OCL table for pages 1–7 often contains duplicate entries that share
#   the same texture coordinate (page, clut_base) but carry different col values:
#     - First occurrence  → tex  (standard tileset)
#     - Later occurrences with a different col → tex_bg (chr256 tileset)
#
#   Blocking rule: if any non-first entry at a coordinate has the same col as
#   the first AND tile_type == 0x38 (hit-flash alt-palette variant), all entries
#   at that coordinate belong to tex regardless of col.
#   Same-col entries with other tile_types (0x00, 0x39, etc.) do NOT block.
#
#   _build_chr256_ocl_indices() computes the frozenset of OCL indices that
#   should read from tex_bg.  Pages 8–15 use col==112 to route to tex_bg.
#
# ============================================================
# OCL tile_type → palette group mapping
# ============================================================
#
#   OclPaletteGroup.STANDARD          col00_0x.col  standard + hit-flash (0x00, 0x38, and any
#                                                     unregistered collision type)
#   OclPaletteGroup.ANIMATED_CRYSTAL  st0_0.col     animated cycling palette (0x39)
#   OclPaletteGroup.ALT_AREA          col00_0z.col  alt-area tileset (0x3B — unverified)
#
#   The mapping is passed in as flags_to_palette: dict[OclPaletteGroup, Palette] so
#   this module stays reusable across stages.
#
# ============================================================
# Layer model
# ============================================================
#
#   The OMP file represents a single layer (main/platform layer).
#   Three visual stage layers exist in separate files:
#     Layer 0 – far BG:    st000_chr256.tex  (standalone texture, no tilemap)
#     Layer 1 – mid BG:    st000_ch3.tex     (standalone texture, no tilemap)
#     Layer 2 – platform:  st000.omp + st000.tex + st000.ocl  ← this parser
#
# ============================================================
# Outstanding unknowns
# ============================================================
#
#   1. Tile size — confirmed 16×16 px from binary analysis.
#
#   2. Full layout table — FULLY CONFIRMED for st000 (see LayoutTable.from_exe).
#      Extracted directly from RXC2.exe (Mega Man X Legacy Collection 2).
#
#   3. OCL tile_type → COL file mapping — see OclPaletteGroup in utils/ocl.py.
#      Pass the correct flags_to_palette dict from the caller.
#
#   4. TEX routing for pages 8–15: col==112 was previously confirmed for chr256
#      routing; all other page 8–15 entries currently use tex.  This may be
#      incomplete — further visual verification is needed.
#
# ============================================================


import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from PIL import Image
from PIL.Image import Image as PILImage

from utils.ocl import OclEntry, OclPaletteGroup
from utils.types import ColourRGBA, Palette, TexData

OMP_MAGIC = b"OMP\x00"
OMP_HEADER_SIZE = 12  # magic(4) + reserved(4) + n_rows(4)
TILE_SIZE = 16  # pixels per tile edge (assumed 16×16)

# LayerPreset row boundaries — estimated, adjust after visual confirmation
_BACKGROUND_MAX_ROW = 25    # rows 0–24 = sparse sky / upper stage area
_PLATFORM_MIN_ROW = 25      # rows 25–106 = main platforms + ground


class LayerPreset(IntEnum):
    """
    Named row-range presets for render_omp().

    MAIN:       All rows — full stage map.
    BACKGROUND: Upper sparse rows (sky / decorative tiles).
    PLATFORM:   Lower denser rows (platforms, ground, fill).
    """
    MAIN = 0
    BACKGROUND = 1
    PLATFORM = 2


@dataclass
class OmpLayer:
    """
    Parsed contents of an OMP file.

    Each row represents one complete 16×16-tile screen (screen_id = row index).
    tiles[screen_id][wy * 16 + wx] = OCL index for tile (wx, wy) of that screen.
    Use render_level() with a LayoutTable for correct level rendering.
    Use render_omp() to dump the raw screen catalog for debugging.
    """
    n_screens: int          # number of screens (= OMP row count; 107 for st000)
    tiles: list[list[int]]  # tiles[screen_id][within_screen_idx] = OCL index (0 = empty)

    # Convenience aliases kept for compatibility
    @property
    def width(self) -> int:
        return 256  # always 256 entries per screen row

    @property
    def height(self) -> int:
        return self.n_screens

    def tile_at(self, screen_id: int, wx: int, wy: int) -> int:
        """Return the OCL index for tile (wx, wy) within the given screen_id."""
        if 0 <= screen_id < self.n_screens:
            idx = wy * 16 + wx
            return self.tiles[screen_id][idx]
        return 0


@dataclass
class LayoutTable:
    """
    Maps level screen coordinates (sx, sy) to OMP screen_ids.

    screens[sy][sx] = screen_id  (= row index into OmpLayer.tiles)

    This data lives in the stage DAT file inside the game's ARC archive.
    It is NOT stored in the OMP/OCL/TEX files.

    Partial layout for st000 (confirmed from omp-to-expected-tiles.csv):
        layout[4][0] = 26
        layout[4][4] = 30
        layout[3][0] = 11
        layout[4][8] = 34
    """
    screens: list[list[int]]  # screens[sy][sx] = screen_id

    def get(self, sx: int, sy: int) -> int | None:
        """Return the screen_id for level screen (sx, sy), or None if unknown."""
        if 0 <= sy < len(self.screens) and 0 <= sx < len(self.screens[sy]):
            val = self.screens[sy][sx]
            return val if val >= 0 else None
        return None

    @staticmethod
    def from_partial(entries: dict[tuple[int, int], int]) -> "LayoutTable":
        """
        Build a LayoutTable from a sparse {(sx, sy): screen_id} dict.
        Unknown entries are stored as -1 and return None from get().

        Example (confirmed for st000):
            LayoutTable.from_partial({
                (0, 4): 26,
                (4, 4): 30,
                (0, 3): 11,
                (8, 4): 34,
            })
        """
        if not entries:
            return LayoutTable(screens=[])
        max_sy = max(sy for _, sy in entries) + 1
        max_sx = max(sx for sx, _ in entries) + 1
        grid = [[-1] * max_sx for _ in range(max_sy)]
        for (sx, sy), sid in entries.items():
            grid[sy][sx] = sid
        return LayoutTable(screens=grid)

    @staticmethod
    def from_bytes(data: bytes, width: int, height: int, layer: int = 0) -> "LayoutTable":
        """
        Parse a LayoutTable from raw layout binary data.

        Layout format (confirmed from TeheManX4_Editor and st000 analysis):
          - 3 layers stored consecutively, each layer_size = width * height bytes
          - Each byte is one u8 screen_id (0 = empty)
          - Indexed row-major: data[sy * width + sx + layer * width * height]

        Args:
            data:   raw bytes containing the layout data (all 3 layers)
            width:  number of screens per row (st000: 15)
            height: number of screen rows (st000: 24)
            layer:  which layer to extract (0=foreground, 1=BG1, 2=BG2)
        """
        layer_size = width * height
        layer_start = layer * layer_size
        if layer_start + layer_size > len(data):
            raise ValueError(
                f"Layout data too small: need {layer_start + layer_size} bytes, "
                f"got {len(data)}"
            )
        grid: list[list[int]] = []
        for sy in range(height):
            row = [
                data[layer_start + sy * width + sx]
                for sx in range(width)
            ]
            grid.append(row)
        return LayoutTable(screens=grid)


def load_omp(omp_path: Path) -> OmpLayer:
    """
    Parse an OMP file and return an OmpLayer.

    Each row in the parsed data is one screen (screen_id = row index).
    tiles[screen_id] has 256 entries; index wy*16+wx is tile (wx,wy) of that screen.
    """
    if not omp_path.exists():
        raise FileNotFoundError(f"OMP file does not exist: {omp_path}")

    data = omp_path.read_bytes()

    if len(data) < OMP_HEADER_SIZE:
        raise ValueError(f"OMP file too small: {len(data)} bytes")

    if data[:4] != OMP_MAGIC:
        raise ValueError(f"Not an OMP file (bad magic): {data[:4]!r}")

    # The u32 at offset 8 stores n_screens × 256.
    ENTRIES_PER_SCREEN = 256
    packed = struct.unpack_from("<I", data, 8)[0]
    if packed == 0:
        raise ValueError("OMP header value at offset 8 is 0")
    if packed % ENTRIES_PER_SCREEN != 0:
        raise ValueError(
            f"OMP header value {packed} is not a multiple of {ENTRIES_PER_SCREEN}"
        )

    n_screens = packed // ENTRIES_PER_SCREEN
    row_size = ENTRIES_PER_SCREEN * 2  # bytes per screen row

    tile_data_size = len(data) - OMP_HEADER_SIZE
    expected = n_screens * row_size
    if tile_data_size != expected:
        raise ValueError(
            f"OMP tile data size {tile_data_size} != expected {expected} "
            f"(n_screens={n_screens})"
        )

    tiles: list[list[int]] = []
    offset = OMP_HEADER_SIZE
    for _ in range(n_screens):
        row = list(struct.unpack_from(f"<{ENTRIES_PER_SCREEN}H", data, offset))
        tiles.append(row)
        offset += row_size

    return OmpLayer(n_screens=n_screens, tiles=tiles)


# ============================================================
# st000 layout constants (Mega Man X Legacy Collection 2, RXC2.exe)
# ============================================================
# Confirmed by scanning the EXE for the 9-byte linear run 0x1A..0x22 (layer 0,
# sy=4) and verifying all 4 known anchor entries from omp-to-expected-tiles.csv.
#
# Three identical copies exist in the EXE (offsets below are all valid):
#   Copy 1:  0x02D98548  (relative offset from start of file)
#   Copy 2:  0x02EC2D4B  ← primary (used by load_layout_from_exe default)
#   Copy 3:  0x02ECA8B0
#
# Layout dimensions confirmed:
#   width  = 15  (screens per row)
#   height = 24  (screen rows, sy=0..23)
#   3 layers (foreground + 2 BG), stored consecutively, each 15×24 = 360 bytes
#
# Anchor verification (all 4 entries confirmed from CSV):
#   Layer 0, sy=3, sx=0 → screen_id = 11 (0x0B)  ✓
#   Layer 0, sy=4, sx=0 → screen_id = 26 (0x1A)  ✓
#   Layer 0, sy=4, sx=4 → screen_id = 30 (0x1E)  ✓
#   Layer 0, sy=4, sx=8 → screen_id = 34 (0x22)  ✓

ST000_LAYOUT_OFFSET = 0x02EC2D4B   # EXE file offset of the first layout byte
ST000_LAYOUT_WIDTH  = 15
ST000_LAYOUT_HEIGHT = 24
ST000_LAYOUT_LAYERS = 3            # 0=foreground, 1=BG1, 2=BG2


def load_layout_from_exe(
    exe_path: Path,
    offset: int = ST000_LAYOUT_OFFSET,
    width: int = ST000_LAYOUT_WIDTH,
    height: int = ST000_LAYOUT_HEIGHT,
    layer: int = 0,
) -> "LayoutTable":
    """
    Load a LayoutTable from the game executable (RXC2.exe for MMLC2).

    Uses the confirmed st000 constants by default.  Pass different ``offset``,
    ``width``, ``height`` to load a different stage's table.

    Args:
        exe_path: path to RXC2.exe (or the PSX EXE for other versions)
        offset:   file offset of the first layout byte (all 3 layers)
        width:    screens per row
        height:   screen rows
        layer:    0 = foreground layer (default), 1 = BG1, 2 = BG2
    """
    layer_size = width * height
    total_size = layer_size * 3
    data = exe_path.read_bytes()
    if offset + total_size > len(data):
        raise ValueError(
            f"EXE too small for layout at {hex(offset)}: "
            f"need {total_size} bytes, file has {len(data) - offset}"
        )
    layout_bytes = data[offset : offset + total_size]
    return LayoutTable.from_bytes(layout_bytes, width, height, layer)


def _build_chr256_ocl_indices(
    ocl_entries: list[OclEntry],
    tex: "TexData",
    tex_bg: "TexData",
    tile_size: int = TILE_SIZE,
) -> frozenset[int]:
    """
    Return a frozenset of OCL indices that should read pixel data from tex_bg
    (the chr256 background tileset) rather than from tex.

    Across all TEX pages 1–7 and all cordY rows, the OCL table contains groups
    of entries that share a texture coordinate (page, clut_base):
      - First occurrence (any col):       reads from tex.
      - Non-first, same col as first:     reads from tex (hit-flash 0x38 variants
                                          share the base tile's pixel data and palette).
      - Non-first, different col, group HAS a large-gap entry (≥ THRESHOLD):
          - This entry's gap from first < THRESHOLD:  reads from tex (stage-palette
            variant in the same OCL batch as the first occurrence; shares pixel data).
          - This entry's gap from first ≥ THRESHOLD:  reads from tex_bg (chr256
            entry in a separate, later OCL batch).
      - Non-first, different col, group has NO large-gap entry:
                                          reads from tex_bg.  When all entries in a
                                          group are close together (no large-gap chr256
                                          variant exists), the whole group represents
                                          a chr256 background tile with palette variants.
      - Sole entry at its coordinate,
        tex empty at that coordinate:     reads from tex_bg (pixel data lives there
                                          rather than in tex for this entry).
      - Sole entry, tex has data:         reads from tex as normal.

    Index-gap rationale (confirmed for X5 st050, st030, st000):
      Groups with both a stage-palette batch AND a chr256 batch always have a large
      index gap (≥ 500) separating the two batches.  Groups whose entries are all
      close together belong entirely to chr256.  A threshold of
      CHR256_INDEX_GAP_THRESHOLD = 500 cleanly separates the two kinds of group.

    Algorithm (three passes):
      Pass 0: count occurrences per (page, clut_base) key.
      Pass 1: record the first col seen per key and collect all OCL indices per key.
      Pass 1b: for each multi-entry key, determine whether the group contains a
               large-gap entry (max consecutive-index gap ≥ CHR256_INDEX_GAP_THRESHOLD).
      Pass 2: mark chr256 for —
                sole entries where tex is all-zero at the coordinate;
                non-first different-col entries whose gap from first ≥ THRESHOLD; and
                non-first different-col entries in groups that have NO large-gap entry.
              Same-col non-first entries are always left in tex.

    Pages ≥ 8 are handled separately via col==112 in _resolve_tile.
    """
    # Minimum index gap within a group that signals a split between the stage-palette
    # batch (tex) and the chr256 background batch (tex_bg).
    # Confirmed for X5 st050, st030, st000: stage-palette max gap ≤ 341;
    # chr256 batch min gap ≥ 739.  500 gives a safe margin between the two.
    CHR256_INDEX_GAP_THRESHOLD = 500

    raw_tex  = tex["raw_image"];    w_tex = tex["width"]
    raw_bg   = tex_bg["raw_image"]; w_bg  = tex_bg["width"]

    def _tex_is_empty(raw: bytes, w: int, gx: int, gy: int) -> bool:
        """Return True if all pixels in the 16×16 tile block are zero."""
        return not any(
            raw[(gy + dy) * w + gx + dx]
            for dy in range(tile_size)
            for dx in range(tile_size)
        )

    # Pass 0: count occurrences per key so standalone entries can be detected
    key_count: dict[tuple[int, int], int] = {}
    for e in ocl_entries:
        page = e.pad & 0xF
        if page >= 8:
            continue
        key = (page, e.clut_base)
        key_count[key] = key_count.get(key, 0) + 1

    # Pass 1: record first col per key and collect all OCL indices per key.
    first_col: dict[tuple[int, int], int] = {}
    group_indices: dict[tuple[int, int], list[int]] = {}
    for i, e in enumerate(ocl_entries):
        page = e.pad & 0xF
        if page >= 8:
            continue
        key = (page, e.clut_base)
        if key not in first_col:
            first_col[key] = e.col
            group_indices[key] = []
        group_indices[key].append(i)

    # Pass 1b: for each multi-entry group, determine if any consecutive pair of
    # indices spans ≥ CHR256_INDEX_GAP_THRESHOLD (indicating a tex/chr256 split).
    group_has_large_gap: dict[tuple[int, int], bool] = {}
    for key, idxs in group_indices.items():
        if len(idxs) < 2:
            group_has_large_gap[key] = False
            continue
        sorted_idxs = sorted(idxs)
        group_has_large_gap[key] = any(
            b - a >= CHR256_INDEX_GAP_THRESHOLD
            for a, b in zip(sorted_idxs, sorted_idxs[1:])
        )

    # Pass 2: mark chr256 for sole entries with empty tex and non-first different-col
    # entries that belong to the chr256 batch.
    seen: set[tuple[int, int]] = set()
    chr256: set[int] = set()
    for i, e in enumerate(ocl_entries):
        page = e.pad & 0xF
        if page >= 8:
            continue
        key = (page, e.clut_base)
        if key_count[key] == 1:
            # Sole entry: route to tex_bg only when tex is empty at this coordinate.
            cordX = e.clut_base & 0xF; cordY = (e.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * tile_size
            gy = (page // 8) * 256 + cordY * tile_size
            if _tex_is_empty(raw_tex, w_tex, gx, gy):
                chr256.add(i)
            continue
        if key in seen:
            if e.col != first_col[key]:
                if not group_has_large_gap[key]:
                    # All entries are in the same close batch → whole group is chr256.
                    chr256.add(i)
                else:
                    # Group is split: large-gap entries are chr256, small-gap are tex.
                    fi = group_indices[key][0]
                    if (i - fi) >= CHR256_INDEX_GAP_THRESHOLD:
                        chr256.add(i)
        else:
            seen.add(key)
    return frozenset(chr256)


def extract_tile_pixels(
    raw_pixels: bytes | bytearray,
    tex_width: int,
    tile_id: int,
    tile_size: int = TILE_SIZE,
) -> list[int]:
    """
    Extract a flat list of raw 8bpp pixel values for one tile from the TEX pixel array.

    raw_pixels: the raw_image bytes from TexData (row-major, 8bpp = 1 byte/pixel)
    tex_width:  full texture width in pixels (from TexData["width"])
    tile_id:    tile index (from OMP, after confirming it is non-zero)
    tile_size:  pixels per tile edge (default 16)

    Returns tile_size×tile_size values (0–255 each), row-major top-to-bottom.
    Pixel value 0 is conventionally transparent.
    """
    tiles_per_row = tex_width // tile_size
    tile_col = tile_id % tiles_per_row
    tile_row = tile_id // tiles_per_row

    ox = tile_col * tile_size  # pixel X of top-left corner in TEX sheet
    oy = tile_row * tile_size  # pixel Y of top-left corner in TEX sheet

    pixels: list[int] = []
    for y in range(tile_size):
        row_start = (oy + y) * tex_width + ox
        pixels.extend(raw_pixels[row_start : row_start + tile_size])
    return pixels


def _apply_palette_to_tile(
    raw_tile: list[int],
    clut_base: int,
    palette: Palette,
) -> list[ColourRGBA]:
    """
    Convert a list of raw 8bpp tile pixel values to RGBA colours using a palette.

    Each pixel value v selects: palette[clut_base * 16 + v]
    v == 0 is transparent (alpha=0); all other values are fully opaque.
    """
    result: list[ColourRGBA] = []
    base = clut_base * 16
    pal_size = len(palette)
    for v in raw_tile:
        if v == 0:
            result.append((0, 0, 0, 0))
        elif base + v >= pal_size:
            result.append((0, 0, 0, 0))  # out of palette range — transparent
        else:
            r, g, b, _a = palette[base + v]
            result.append((r, g, b, 255))
    return result


def render_omp(
    layer: OmpLayer,
    ocl_entries: list[OclEntry],
    tex: TexData,
    # tex_fg: TexData,
    tex_bg: TexData,
    flags_to_palette: dict[OclPaletteGroup, Palette],
    preset: LayerPreset = LayerPreset.MAIN,
    row_start: int = 0,
    row_end: int | None = None,
    tile_size: int = TILE_SIZE,
) -> PILImage:
    """
    Render the raw OMP screen catalog to a PIL RGBA image for debugging.

    This renders screen_ids as sequential rows, so the output is a grid of
    all 256 within-screen slots laid out flat — NOT the actual level layout.
    To render the level correctly, use render_level() with a LayoutTable instead.

    layer:             parsed OmpLayer from load_omp()
    raw_pixels:        TexData["raw_image"] from the stage tileset TEX
    tex_width:         TexData["width"] from the stage tileset TEX
    fallback_tilesets: optional list of (raw_pixels, tex_width) pairs (unused currently)
    ocl_entries:       list of OclEntry from load_ocl() for this stage
    flags_to_palette:  maps OclPaletteGroup → Palette. OclEntry.palette_group() maps
                       any tile_type to one of the named groups; unregistered collision
                       types fall back to STANDARD so no tile is silently dropped.
    row_start:         first screen_id to render (inclusive). Ignored when preset != MAIN.
    row_end:           one-past-last screen_id. None = layer.n_screens.
                       Ignored when preset != MAIN.
    preset:            LayerPreset controlling which screen rows to render.
    tile_size:         pixels per tile edge (default 16).

    Returns an RGBA PIL Image with dimensions (256 * tile_size, n_screens * tile_size).
    """
    # Resolve row range from preset
    if preset == LayerPreset.BACKGROUND:
        r_start, r_end = 0, _BACKGROUND_MAX_ROW
    elif preset == LayerPreset.PLATFORM:
        r_start, r_end = _PLATFORM_MIN_ROW, layer.height
    else:  # MAIN
        r_start = row_start
        r_end = layer.height if row_end is None else row_end

    r_start = max(0, r_start)
    r_end = min(layer.height, r_end)
    n_rows = r_end - r_start

    canvas_w = layer.width * tile_size
    canvas_h = n_rows * tile_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    chr256_indices = _build_chr256_ocl_indices(ocl_entries, tex, tex_bg, tile_size)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        # OCL byte2 (stored as field 'clut_base'): encodes TEX tile coordinates
        #   cordX = byte2 & 0x0F  (low nibble)
        #   cordY = (byte2 >> 4) & 0x0F  (high nibble)
        # OCL byte3 (stored as field 'pad'): low nibble = page number
        #   gx = (page % 8) * 256 + cordX * tile_size
        #   gy = (page // 8) * 256 + cordY * tile_size
        cordX = entry.clut_base & 0xF
        cordY = (entry.clut_base >> 4) & 0xF
        page = entry.pad & 0xF

        # Texture routing:
        #   Pages 0–7: tex holds valid 8bpp tile data in general.
        #     Exception: at cordY==15 (the last tile row of a page), some OCL
        #     entries are "second occurrences" that share coordinates with an
        #     earlier entry but come from the chr256 background tileset instead.
        #     These are identified by _build_chr256_ocl_indices() and use tex_bg.
        #   Pages 8–15, col=112: tex_bg (chr256) — values 0–30 land in palette
        #     rows 176–177 which are correct for those tiles.
        #   Pages 8–15, col≠112: tex has the correct 8bpp values for those tiles.
        if page < 8:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif entry.col == 112:
            active_tex = tex_bg
        else:
            active_tex = tex

        raw_pixels = active_tex["raw_image"]
        active_width = active_tex["width"]
        active_height = len(raw_pixels) // active_width if active_width > 0 else 0

        gx = (page % 8) * 256 + cordX * tile_size
        gy = (page // 8) * 256 + cordY * tile_size
        if gx + tile_size > active_width or gy + tile_size > active_height:
            return None
        result: list[int] = []
        for row in range(tile_size):
            row_start = (gy + row) * active_width + gx
            result.extend(raw_pixels[row_start : row_start + tile_size])
        return result

    for row_idx in range(r_start, r_end):
        canvas_row = row_idx - r_start
        for col_idx in range(layer.width):
            raw_id = layer.tiles[row_idx][col_idx]
            if raw_id == 0:
                continue  # transparent

            # Bit 15 = flip_h flag; bits [0:13] = actual tile/OCL index
            flip_h = bool(raw_id & 0x8000)
            tile_id = raw_id & 0x3FFF

            if tile_id >= len(ocl_entries):
                continue  # out of range — skip silently

            entry = ocl_entries[tile_id]
            palette = flags_to_palette.get(
                entry.palette_group(),
                flags_to_palette.get(OclPaletteGroup.STANDARD),
            )
            if palette is None:
                continue  # no palette registered at all — skip

            # pad=0xFF is the OCL sentinel value for "no TEX data" — these slots
            # (crystal sky-fill placeholders) are transparent in the foreground pass;
            # the background layer is meant to show through.
            if entry.pad == 0xFF:
                continue

            raw_tile = _resolve_tile(entry, tile_id)
            if raw_tile is None:
                continue  # tile not found in TEX
            rgba_pixels = _apply_palette_to_tile(raw_tile, entry.col + 64, palette)

            tile_img = Image.new("RGBA", (tile_size, tile_size))
            tile_img.putdata(rgba_pixels)

            if flip_h:
                tile_img = tile_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

            px = col_idx * tile_size
            py = canvas_row * tile_size
            canvas.paste(tile_img, (px, py), mask=tile_img)

    return canvas


def render_level(
    layer: OmpLayer,
    ocl_entries: list[OclEntry],
    layout: LayoutTable,
    level_width_screens: int,
    level_height_screens: int,
    tex: TexData,
    tex_bg: TexData,
    # tex_fg: TexData,
    flags_to_palette: dict[OclPaletteGroup, Palette],
    tile_size: int = TILE_SIZE,
) -> PILImage:
    """
    Render the level using the correct screen-based addressing.

    Unlike render_omp() (which dumps the raw screen catalog), this function
    uses the LayoutTable to map level tile positions to the correct OMP screens.

    level_width_screens:  number of screens horizontally (e.g. 16 for a 256-tile-wide level)
    level_height_screens: number of screens vertically
    layout:               LayoutTable mapping (sx, sy) → screen_id

    Addressing:
        screen_id = layout.get(sx, sy)
        omp_col   = wy * 16 + wx          (within-screen index, x fast)
        ocl_idx   = layer.tiles[screen_id][omp_col]
    """
    canvas_w = level_width_screens * 16 * tile_size
    canvas_h = level_height_screens * 16 * tile_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    chr256_indices = _build_chr256_ocl_indices(ocl_entries, tex, tex_bg, tile_size)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        cordX = entry.clut_base & 0xF
        cordY = (entry.clut_base >> 4) & 0xF
        page = entry.pad & 0xF

        # Texture routing: see render_omp for full explanation.
        if page < 8:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif entry.col == 112:
            active_tex = tex_bg
        else:
            active_tex = tex

        raw_pixels = active_tex["raw_image"]
        active_width = active_tex["width"]
        active_height = len(raw_pixels) // active_width if active_width > 0 else 0

        gx = (page % 8) * 256 + cordX * tile_size
        gy = (page // 8) * 256 + cordY * tile_size
        if gx + tile_size > active_width or gy + tile_size > active_height:
            return None
        result: list[int] = []
        for row in range(tile_size):
            row_start = (gy + row) * active_width + gx
            result.extend(raw_pixels[row_start : row_start + tile_size])
        return result

    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            screen_id = layout.get(sx, sy)
            if screen_id is None or screen_id >= layer.n_screens:
                continue  # screen not in layout table — skip

            screen_tiles = layer.tiles[screen_id]

            for wy in range(16):
                for wx in range(16):
                    omp_col = wy * 16 + wx
                    raw_id = screen_tiles[omp_col]
                    if raw_id == 0:
                        continue  # transparent

                    flip_h = bool(raw_id & 0x8000)
                    ocl_idx = raw_id & 0x3FFF

                    if ocl_idx >= len(ocl_entries):
                        continue

                    entry = ocl_entries[ocl_idx]
                    palette = flags_to_palette.get(
                        entry.palette_group(),
                        flags_to_palette.get(OclPaletteGroup.STANDARD),
                    )
                    if palette is None:
                        continue  # no palette registered at all — skip

                    # pad=0xFF is the OCL sentinel value for "no TEX data" — these slots
                    # (crystal sky-fill placeholders) are transparent in the foreground pass;
                    # the background layer is meant to show through.
                    if entry.pad == 0xFF:
                        continue

                    raw_tile = _resolve_tile(entry, ocl_idx)
                    if raw_tile is None:
                        continue

                    rgba_pixels = _apply_palette_to_tile(raw_tile, entry.col + 64, palette)

                    tile_img = Image.new("RGBA", (tile_size, tile_size))
                    tile_img.putdata(rgba_pixels)

                    if flip_h:
                        tile_img = tile_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

                    # level tile position (lx, ly)
                    lx = sx * 16 + wx
                    ly = sy * 16 + wy
                    px = lx * tile_size
                    py = ly * tile_size
                    canvas.paste(tile_img, (px, py), mask=tile_img)

    return canvas
