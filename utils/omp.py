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


import bisect
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

# X6 page>=8 (8bpp) tiles index the UN-normalized stage CLUT at col + this offset, not
# col+64: normalize_x6_stage_palette's col+96->col+64 relocation has a null-keep that
# treats dark-but-real stage CLUTs as empty and leaves the polluted col+64 VRAM snapshot
# (the page>=8 "inverted shadows"), so these tiles read raw col+96 directly instead.
# pad_hi=4 page>=8 tiles are excluded — they use build_x6_padhi_clut_override's alt bank.
_X6_PAGE8_CLUT_OFFSET = 96

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
    # total_size = layer_size * 3
    total_size = layer_size
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
                                          share the base tile's pixel data and palette;
                                          these always lie within the same OCL batch
                                          as the first occurrence).
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
      - Sole entry, tex empty:            reads from tex_bg.
      - Sole entry, tex has data matching tex_bg (same=True):
                                          reads from tex (routing doesn't matter).
      - Sole entry, tex has data differing from tex_bg AND index within the
        chr256-batch region (within CHR256_INDEX_GAP_THRESHOLD of any no-large-gap
        group entry):                     reads from tex_bg (the canonical pixels
                                          for this background tile live there).
      - Sole entry, tex has data differing from tex_bg AND index OUTSIDE the
        chr256-batch region:              reads from tex.  These are foreground-only
                                          palette variants that follow the last
                                          multi-entry group in the OCL table and
                                          are never part of the chr256 batch.
      - Page ≥ 8, col ≠ 0/112:           reads from tex (handled entirely in
                                          _resolve_tile; _build_chr256_ocl_indices
                                          does not process pages ≥ 8).
                                          col=0 and col=112 → tex_bg in _resolve_tile.

    Index-span rationale (confirmed for X5 st010, st030, st050, st000):
      All-chr256 groups have a total index span (last − first) well under 500.
      Stage-palette (tex) groups with multiple palette variants spread across a
      large span even when no single consecutive pair exceeds 500 (e.g. a 4-entry
      group [1100, 1400, 1689, 2155] has max consecutive gap 466 but span 1055).
      Using total span ≥ CHR256_INDEX_GAP_THRESHOLD = 500 cleanly separates the
      two kinds of group.

    Algorithm (three passes):
      Pass 0: count occurrences per (page, clut_base) key.
      Pass 1: record the first col seen per key and collect all OCL indices per key.
      Pass 1b: for each multi-entry key, determine whether the group contains a
               large-gap entry (max consecutive-index gap ≥ CHR256_INDEX_GAP_THRESHOLD).
      Pass 1c: compute the chr256-batch region from no-large-gap group indices
               (used to gate the sole-entry tex≠tex_bg rule).
      Pass 2: mark chr256 for —
                sole entries where tex is empty;
                sole entries where tex ≠ tex_bg AND index within chr256-batch region;
                all entries of no-large-gap groups (first and non-first, any col);
                non-first different-col entries in large-gap groups whose gap from
                first ≥ THRESHOLD.
              Pages ≥ 8 are skipped here; their routing is done in _resolve_tile
              via col=0/112 indicators.

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

    def _tex_fill(raw: bytes, w: int, gx: int, gy: int) -> int:
        """Return the count of non-zero (opaque) pixels in the 16×16 tile block."""
        return sum(
            1
            for dy in range(tile_size)
            for dx in range(tile_size)
            if raw[(gy + dy) * w + gx + dx]
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

    # Pass 1b: for each multi-entry group, determine if the total index span
    # (last index − first index) ≥ CHR256_INDEX_GAP_THRESHOLD.
    #
    # Using total span (rather than max consecutive gap) correctly handles groups
    # with many entries where each consecutive pair is close but the overall range
    # is large (e.g. [1100, 1400, 1689, 2155]: max_consec_gap=466 but span=1055).
    # All confirmed chr256 groups have total span < CHR256_INDEX_GAP_THRESHOLD;
    # tex groups with multiple palette variants have much larger spans.
    group_has_large_gap: dict[tuple[int, int], bool] = {}
    for key, idxs in group_indices.items():
        if len(idxs) < 2:
            group_has_large_gap[key] = False
            continue
        sorted_idxs = sorted(idxs)
        group_has_large_gap[key] = (
            sorted_idxs[-1] - sorted_idxs[0] >= CHR256_INDEX_GAP_THRESHOLD
        )

    # Pass 1b½: for each group, check whether the chr256 (tex_bg) texture has tile
    # data at the group's coordinates.  Groups where tex_bg is empty at those
    # coordinates are foreground tile batches — they must not be routed to tex_bg
    # even if their OCL indices form a close cluster (no-LG group by span alone).
    group_bg_has_data: dict[tuple[int, int], bool] = {}
    for key in group_indices:
        page_k, clut_k = key
        cordX_k = clut_k & 0xF; cordY_k = (clut_k >> 4) & 0xF
        gx_k = (page_k % 8) * 256 + cordX_k * tile_size
        gy_k = (page_k // 8) * 256 + cordY_k * tile_size
        group_bg_has_data[key] = not _tex_is_empty(raw_bg, w_bg, gx_k, gy_k)

    # Pass 1c: compute the overall index range spanned by all no-large-gap groups.
    # This range [no_lg_min − THRESHOLD, no_lg_max + THRESHOLD] defines the
    # "chr256 batch region".  Sole entries where tex≠tex_bg are only chr256 when
    # their OCL index falls inside this region; sole entries outside it (e.g. a run
    # of foreground-only palette variants that follow the last large-span group's
    # first occurrence) stay in tex.
    _no_lg_indices: set[int] = set()
    for key, idxs in group_indices.items():
        if len(idxs) >= 2 and not group_has_large_gap[key] and group_bg_has_data[key]:
            _no_lg_indices.update(idxs)
    if _no_lg_indices:
        _no_lg_min = min(_no_lg_indices)
        _no_lg_max = max(_no_lg_indices)
    else:
        _no_lg_min = _no_lg_max = -1

    def _in_chr256_region(idx: int) -> bool:
        """Return True if idx is within CHR256_INDEX_GAP_THRESHOLD of the no-LG group range."""
        if _no_lg_min < 0:
            return False
        return _no_lg_min - CHR256_INDEX_GAP_THRESHOLD <= idx <= _no_lg_max + CHR256_INDEX_GAP_THRESHOLD

    # Pass 1d: compute the set of texture pages that host at least one no-large-gap
    # group member.  Sole entries where tex!=tex_bg are only classified as chr256 when
    # their texture page belongs to this set.
    #
    # Rationale: the chr256 background batch occupies a contiguous block of OCL
    # indices; its tile coordinates spread across specific pages (e.g. pages 0-2 in
    # st041).  Sole entries on OTHER pages are foreground tiles that merely happen to
    # differ from the background texture at the same coordinates.  Gating by page
    # membership cleanly separates the two classes without requiring a tighter
    # CHR256_INDEX_GAP_THRESHOLD that could break other stages.
    #
    # Stages with no no-LG groups have _pages_with_no_lg = set(), but those stages
    # also have _in_chr256_region always returning False, so the page gate is moot.
    _pages_with_no_lg: set[int] = {
        key[0]
        for key, idxs in group_indices.items()
        if len(idxs) >= 2 and not group_has_large_gap[key] and group_bg_has_data[key]
    }

    # Pass 2: mark chr256 for entries that belong to the chr256 batch.
    h_tex = len(raw_tex) // w_tex
    h_bg  = len(raw_bg)  // w_bg

    def _tiles_differ(gx: int, gy: int) -> bool:
        """Return True if the two textures contain different pixels in this tile."""
        if (gx + tile_size > w_tex or gy + tile_size > h_tex or
                gx + tile_size > w_bg  or gy + tile_size > h_bg):
            return False
        return not all(
            raw_tex[(gy + dy) * w_tex + gx + dx] ==
            raw_bg [(gy + dy) * w_bg  + gx + dx]
            for dy in range(tile_size)
            for dx in range(tile_size)
        )

    # Gate for the tex_empty sole-entry rule.
    #
    # When a stage has BOTH no-LG groups (giving a well-defined chr256 region) AND
    # sole entries where tex≠tex_bg (sole_diff entries), the tex_empty check must
    # also be restricted to the chr256 region.  Without the gate, transparent
    # foreground slots that happen to share a tex_bg coordinate with unrelated
    # background data would incorrectly read from tex_bg.
    #
    # Stages with no sole_diff entries (e.g. st050, st010) have tex_empty sole
    # entries only in the chr256 batch, so no gating is needed.  Stages with no
    # no-LG groups (e.g. st000) have no defined region, so no gating either.
    _has_sole_diff = _no_lg_min >= 0 and any(
        (e.pad & 0xF) < 8
        and key_count.get((e.pad & 0xF, e.clut_base), 0) == 1
        and not _tex_is_empty(
            raw_tex, w_tex,
            (e.pad & 0xF) % 8 * 256 + (e.clut_base & 0xF) * tile_size,
            (e.pad & 0xF) // 8 * 256 + ((e.clut_base >> 4) & 0xF) * tile_size,
        )
        and _tiles_differ(
            (e.pad & 0xF) % 8 * 256 + (e.clut_base & 0xF) * tile_size,
            (e.pad & 0xF) // 8 * 256 + ((e.clut_base >> 4) & 0xF) * tile_size,
        )
        for e in ocl_entries
    )
    # If both conditions are met, sole-entry tex_empty is gated by _in_chr256_region.
    _gate_tex_empty = _has_sole_diff

    # Pass 1e: identify same-col large-gap groups whose first occurrence (fi) is
    # immediately adjacent to a confirmed no-LG chr256 group on the same page.
    # When a large-gap same-col group sits right next to the chr256 batch (distance
    # from fi to nearest no-LG index ≤ _NOLG_DIST_THRESHOLD), both normal and
    # hit-flash variants belong to the background batch (e.g. st061 page=0 groups).
    # Empirically verified: adds 61 entries for st061 and 0 for all other stages.
    _NOLG_DIST_THRESHOLD = 20
    _per_page_nolg_sorted: dict[int, list[int]] = {}
    for _key, _idxs in group_indices.items():
        if len(_idxs) >= 2 and not group_has_large_gap[_key] and group_bg_has_data[_key]:
            _per_page_nolg_sorted.setdefault(_key[0], []).extend(_idxs)
    for _pg in _per_page_nolg_sorted:
        _per_page_nolg_sorted[_pg] = sorted(set(_per_page_nolg_sorted[_pg]))

    def _min_dist_to_nolg(fi: int, page: int) -> int:
        """Min OCL-index distance from fi to the nearest no-LG member on the same page."""
        _pg_idxs = _per_page_nolg_sorted.get(page)
        if not _pg_idxs:
            return 2 ** 31
        pos = bisect.bisect_left(_pg_idxs, fi)
        d: list[int] = []
        if pos < len(_pg_idxs):
            d.append(abs(_pg_idxs[pos] - fi))
        if pos > 0:
            d.append(abs(_pg_idxs[pos - 1] - fi))
        return min(d)

    _lg_samecol_chr256_keys: set[tuple[int, int]] = set()
    for _key, _idxs in group_indices.items():
        _sorted_g = sorted(_idxs)
        if _sorted_g[-1] - _sorted_g[0] < CHR256_INDEX_GAP_THRESHOLD:
            continue  # not a large-gap group
        if len({ocl_entries[j].col for j in _idxs}) > 1:
            continue  # mixed-col group — handled by different-col rule
        _page_k, _clut_k = _key
        _cordX_k = _clut_k & 0xF
        _cordY_k = (_clut_k >> 4) & 0xF
        _gx_k = (_page_k % 8) * 256 + _cordX_k * tile_size
        _gy_k = (_page_k // 8) * 256 + _cordY_k * tile_size
        if _tex_is_empty(raw_bg, w_bg, _gx_k, _gy_k):
            continue  # tex_bg empty — not a background tile
        if not _tiles_differ(_gx_k, _gy_k):
            continue  # identical pixels in both textures — routing is irrelevant
        if _min_dist_to_nolg(_sorted_g[0], _page_k) <= _NOLG_DIST_THRESHOLD:
            _lg_samecol_chr256_keys.add(_key)

    def _nolg_first_is_fg_pair(key: tuple[int, int]) -> bool:
        """
        True when a no-large-gap group is actually a foreground/background DUPLICATE
        pair whose FIRST occurrence is a foreground tile (belongs on tex), rather than
        a chr256 palette-variant background batch.

        Confirmed for X6 st0h's pole/chain columns (OCL 463-515): each is the first
        occurrence of a 2-entry group with a SMALL index gap (243-257 < THRESHOLD),
        so it lands in the "whole group is chr256" branch and the foreground pole was
        wrongly read from tex_bg (unrelated solid background → orange blobs).

        Signature distinguishing the pair from a genuine background batch:
          - the first occurrence is NOT a 0x38 hit-flash/alt-palette variant. A 0x38
            entry shares its base tile's pixel data and lives inside the chr256 batch
            by definition — it is never an independent foreground tile (X5 st030
            page-4 entries 2905-2917 are 0x38 palette variants that must stay on
            tex_bg; flipping them to tex showed the wrong solid-foreground tile); AND
          - first occurrence's col differs from a later member's col (mixed col →
            fg/bg pair, like the large-gap different-col rule — NOT a same-palette
            hit-flash/variant batch, which stays chr256); AND
          - the first occurrence's tex coordinate holds a SPARSE foreground sprite
            (fg_fill > 0 and fg_fill*3 <= bg_fill — covers at most ~1/3 of the tile)
            over an essentially SOLID tex_bg tile (bg_fill >= 3/4 area) whose pixels
            differ. This is a tighter variant of the large-gap same-col rule's
            "fg fragment vs bg solid" gate (fg_fill*2 <= bg_fill): the *2 form admits
            exactly-half-filled tiles (fg_fill == 128/256), which are dense vertical-
            bar / stipple palette variants belonging to the chr256 batch, NOT sparse
            foreground sprites (X5 st061 page-3 OCL 1995-1999 and X6 st03 page-4 OCL
            2576-2590 are such half-fill tiles that must stay on tex_bg; genuine
            foreground poles/vines/edges in st0h/st160/st04b cover <= 68/256).

        Only the FIRST occurrence is foreground; later occurrences remain chr256.
        """
        idxs = group_indices[key]
        if len(idxs) < 2:
            return False
        s = sorted(idxs)
        fi = s[0]
        if ocl_entries[fi].tile_type == OclPaletteGroup.ALT_PALETTE:
            return False  # 0x38 hit-flash variant: shares batch pixel data, never fg
        if all(ocl_entries[j].col == ocl_entries[fi].col for j in s):
            return False  # same col → palette/hit-flash variant batch, keep as chr256
        page_k, clut_k = key
        cordX_k = clut_k & 0xF; cordY_k = (clut_k >> 4) & 0xF
        gx_k = (page_k % 8) * 256 + cordX_k * tile_size
        gy_k = (page_k // 8) * 256 + cordY_k * tile_size
        fg = _tex_fill(raw_tex, w_tex, gx_k, gy_k)
        bg = _tex_fill(raw_bg, w_bg, gx_k, gy_k)
        return (fg > 0 and bg >= (tile_size * tile_size * 3) // 4
                and fg * 3 <= bg and _tiles_differ(gx_k, gy_k))

    seen: set[tuple[int, int]] = set()
    chr256: set[int] = set()
    for i, e in enumerate(ocl_entries):
        page = e.pad & 0xF
        if page >= 8:
            continue
        key = (page, e.clut_base)
        if key_count[key] == 1:
            # Sole entry: route to tex_bg when tex is empty at this coordinate,
            # and to tex_bg when tex has data that differs from tex_bg but only
            # within the chr256-batch region.
            # When _gate_tex_empty is active (stage has both no-LG groups and
            # sole_diff entries), the tex_empty rule is also restricted to the
            # chr256 region to avoid routing transparent foreground slots to tex_bg.
            cordX = e.clut_base & 0xF; cordY = (e.clut_base >> 4) & 0xF
            gx = (page % 8) * 256 + cordX * tile_size
            gy = (page // 8) * 256 + cordY * tile_size
            if _tex_is_empty(raw_tex, w_tex, gx, gy):
                if not _gate_tex_empty or _in_chr256_region(i):
                    chr256.add(i)
            elif _tiles_differ(gx, gy) and _in_chr256_region(i) and page in _pages_with_no_lg and not _tex_is_empty(raw_bg, w_bg, gx, gy):
                chr256.add(i)
            continue
        if key in seen:
            if not group_has_large_gap[key]:
                # All entries in this group are in the same close batch → the
                # whole group is chr256, but only when tex_bg has tile data here
                # (foreground groups can also form close-index clusters).
                if group_bg_has_data[key]:
                    chr256.add(i)
            elif e.col != first_col[key]:
                # Large-gap group, different col: check whether this entry is
                # in the chr256 batch (large gap) or the tex batch (small gap).
                fi = group_indices[key][0]
                if (i - fi) >= CHR256_INDEX_GAP_THRESHOLD:
                    chr256.add(i)
            else:
                # Same-col entries in large-gap groups normally remain in tex (they
                # are hit-flash/palette variants that share pixel data with the first
                # occurrence and lie within the tex OCL batch).  Two exceptions
                # promote a non-first entry to the chr256 background batch:
                #   (a) Pass 1e flagged the group as adjacent to the no-LG chr256
                #       batch on the same page, so the whole group is background
                #       (e.g. st061 page=0 col=3/4/5/6/7/10 groups); or
                #   (b) this is a later occurrence at a large index gap whose tex_bg
                #       coordinate holds a SOLID tile while tex holds only a sparse,
                #       differing fragment — a genuine same-col background duplicate
                #       where the foreground version is missing/incomplete.  The first
                #       occurrence is the real foreground tile (tex); the far, same-col
                #       duplicate is the chr256 background variant.  This mirrors the
                #       page>=8 rule in Pass 3c for the page<8 case the different-col
                #       rule above (col != first_col) cannot reach when the whole group
                #       shares one col.  Example: X6 st01's tree/rock objects (OCL
                #       2484-2487 / 2605-2608), whose tex holds fragmentary pixels and
                #       chr256 holds the coherent rock tile.
                #
                #       The fill gate (tex_bg solid AND tex fragment ≤ half of it) is
                #       what keeps genuine FOREGROUND objects in tex: a coherent fg
                #       tile (turret housing, foliage) fills its block, so tex_fill is
                #       not far below tex_bg_fill and the entry stays on tex even when
                #       tex_bg happens to hold unrelated data at the same coordinate
                #       (e.g. st01 OCL 2627 fg-rock/bg-near-empty, correctly left on
                #       tex — its OCL neighbours jump to another page, so it is not an
                #       interior strip member).  NOTE: this gate misfires on fully-
                #       painted background TRANSITION tiles (dense tex pixels read as a
                #       foreground object), e.g. st01 OCL 2702, the lone gap in the
                #       page-3 moss strip 2695-2719.  Those are recovered by the
                #       contiguous-strip gap-fill pass in render_stage.build_x6_chr256_override.
                if key in _lg_samecol_chr256_keys:
                    chr256.add(i)
                else:
                    fi = group_indices[key][0]
                    cordX = e.clut_base & 0xF; cordY = (e.clut_base >> 4) & 0xF
                    gx = (page % 8) * 256 + cordX * tile_size
                    gy = (page // 8) * 256 + cordY * tile_size
                    if (i - fi) >= CHR256_INDEX_GAP_THRESHOLD and group_bg_has_data[key]:
                        bg_fill = _tex_fill(raw_bg, w_bg, gx, gy)
                        fg_fill = _tex_fill(raw_tex, w_tex, gx, gy)
                        # tex_bg essentially solid (continuous background) and the tex
                        # fragment covers at most half of it → fg version is missing.
                        if (bg_fill >= (tile_size * tile_size * 3) // 4
                                and fg_fill * 2 <= bg_fill
                                and _tiles_differ(gx, gy)):
                            chr256.add(i)
        else:
            seen.add(key)
            if not group_has_large_gap[key]:
                # First occurrence of an all-close (no-large-gap) group: the whole
                # group belongs to the chr256 batch, including this first entry —
                # but only when tex_bg has tile data at these coordinates.
                # EXCEPTION: a foreground/background duplicate pair (mixed col, sparse
                # fg sprite over a solid bg tile) keeps its first occurrence on tex;
                # only the later occurrence(s) are the chr256 background variant.
                if group_bg_has_data[key] and not _nolg_first_is_fg_pair(key):
                    chr256.add(i)
            elif key in _lg_samecol_chr256_keys:
                # First occurrence of a same-col large-gap group identified in
                # Pass 1e as adjacent to the no-LG chr256 batch on the same page:
                # this entry belongs to the background batch, not the tex batch.
                chr256.add(i)
    # Record the page<8 chr256 maximum index before adding any page>=8 entries.
    # Used by Pass 3b as the proximity anchor so that page>=8 sole-entry proximity
    # is always measured against the page<8 batch max (not inflated by Pass 3a).
    _chr256_max_pg_lt8 = max(chr256) if chr256 else -1

    # Pass 3a: page>=8 multi-member small-span groups.
    # When a (page, clut_base) group on page>=8 has:
    #   - 2+ OCL entries
    #   - total span (max_idx - min_idx) < CHR256_INDEX_GAP_THRESHOLD
    #   - at least one member with col in (0, 112)  [chr256 palette indicator]
    #   - tex_bg has non-empty pixel data at those coordinates
    # then ALL members of the group belong to the chr256 (background) batch.
    #
    # This handles stages like st041 where page>=8 chr256 tiles come in pairs:
    # a col=0 normal-palette entry and a col=16 alt-palette entry pointing to the
    # same pixel coordinates.  The col=32/96 groups in st030 are excluded because
    # they contain no col=0/112 member (they are foreground palette variants).
    _pg8_groups: dict[tuple[int, int], list[int]] = {}
    for i, e in enumerate(ocl_entries):
        page = e.pad & 0xF
        if page < 8:
            continue
        key = (page, e.clut_base)
        if key not in _pg8_groups:
            _pg8_groups[key] = []
        _pg8_groups[key].append(i)

    for key, idxs in _pg8_groups.items():
        if len(idxs) < 2:
            continue
        sorted_g = sorted(idxs)
        if sorted_g[-1] - sorted_g[0] >= CHR256_INDEX_GAP_THRESHOLD:
            continue
        if not any(ocl_entries[j].col in (0, 112) for j in idxs):
            continue
        page_k, clut_k = key
        cordX_k = clut_k & 0xF; cordY_k = (clut_k >> 4) & 0xF
        gx_k = (page_k % 8) * 256 + cordX_k * tile_size
        gy_k = (page_k // 8) * 256 + cordY_k * tile_size
        if _tex_is_empty(raw_bg, w_bg, gx_k, gy_k):
            continue
        # Only add members whose col is NOT the standard-palette marker (0 or 112).
        # In groups with mixed col values (e.g. col=0 foreground + col=16 background),
        # the col=0 member is the foreground tile sharing the same pixel coordinates;
        # it must stay in tex.  The col=0/112 members are handled independently by
        # Pass 3b's proximity check.
        chr256.update(j for j in idxs if ocl_entries[j].col not in (0, 112))

    # Pass 3b: page>=8 sole entries — col=0/112 proximity check.
    # A sole page>=8 col-0/112 entry is chr256 when:
    #   (a) no chr256 batch region was detected (_no_lg_min < 0, e.g. st000), OR
    #   (b) the entry's OCL index is within CHR256_INDEX_GAP_THRESHOLD of the
    #       highest page<8 chr256 index (_chr256_max_pg_lt8).
    # Using the page<8-only max (not the post-3a max) keeps the proximity anchor
    # stable and avoids unintended cascading additions.
    #
    # The proximity check uses abs() (bilateral) rather than a one-sided comparison.
    # A one-sided check (i - max <= THRESHOLD) would admit foreground col=112 tiles
    # that happen to appear far BEFORE the chr256 batch — their small OCL index
    # satisfies the one-sided inequality even when they are thousands of positions
    # away from the batch maximum (e.g. st070 page=11 col=112 tiles at OCL 1392–1460
    # with _chr256_max_pg_lt8=5101: 1392 - 5101 = -3709 ≤ 500, incorrectly included).
    # The bilateral check rejects any entry whose distance to the batch max exceeds
    # THRESHOLD from either side, ensuring only tiles genuinely adjacent to the
    # end of the chr256 batch are included.
    for i, e in enumerate(ocl_entries):
        if (e.pad & 0xF) < 8:
            continue
        if e.col not in (0, 112):
            continue
        if _no_lg_min < 0 or (_chr256_max_pg_lt8 >= 0 and abs(i - _chr256_max_pg_lt8) <= CHR256_INDEX_GAP_THRESHOLD):
            chr256.add(i)

    # Pass 3c: page>=8 large-span different-col groups.
    # When a (page, clut_base) group on page>=8 has:
    #   - 2+ OCL entries
    #   - total span (max_idx - min_idx) >= CHR256_INDEX_GAP_THRESHOLD (large gap)
    #   - mixed cols: at least one entry has a col different from the first occurrence
    #   - tex_bg has non-empty pixel data at those coordinates
    # then entries whose gap from the first occurrence >= CHR256_INDEX_GAP_THRESHOLD
    # AND whose col differs from the first col belong to the chr256 background batch.
    #
    # Mirrors the page<8 large-gap different-col rule from Pass 2 (applied to page>=8).
    # When a tile coordinate appears twice with a large index gap, the first
    # occurrence is the foreground (tex) tile and the later, different-col occurrence
    # is the chr256 background variant (tex_bg) — exactly as Pass 2 does for page<8
    # using `col != first_col`.
    #
    # The later/background col may be either HIGHER than the first col (e.g. st080
    # page=11: foreground col=32/64, background col=80/96) or LOWER than it (e.g.
    # st02 page=11: foreground col=224, background col=96).  Both are background
    # entries, so the test is `cv != fc`, not `cv > fc` — a one-sided `cv > fc`
    # check left st02's col=96 background tiles reading the foreground texture,
    # producing garbled output.
    #
    # Same-col entries in large-span page>=8 groups are left in tex regardless of
    # their gap (they are hit-flash/palette variants sharing the tex tile data).
    for key, idxs in _pg8_groups.items():
        if len(idxs) < 2:
            continue
        sorted_g = sorted(idxs)
        if sorted_g[-1] - sorted_g[0] < CHR256_INDEX_GAP_THRESHOLD:
            continue  # small span — already handled by Pass 3a
        fi = sorted_g[0]
        fc = ocl_entries[fi].col
        if all(ocl_entries[j].col == fc for j in sorted_g):
            continue  # all same col — no chr256 batch split
        page_k, clut_k = key
        cordX_k = clut_k & 0xF; cordY_k = (clut_k >> 4) & 0xF
        gx_k = (page_k % 8) * 256 + cordX_k * tile_size
        gy_k = (page_k // 8) * 256 + cordY_k * tile_size
        if _tex_is_empty(raw_bg, w_bg, gx_k, gy_k):
            continue  # no background pixel data — not a chr256 tile
        for j in sorted_g:
            cv = ocl_entries[j].col
            if (j - fi) >= CHR256_INDEX_GAP_THRESHOLD and cv != fc:
                chr256.add(j)

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

    Returns tile_size×tile_size raw CLUT indices (0–255), row-major; transparency is
    decided later in _apply_palette_to_tile (value-based, not index-0-based).
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
    Each pixel value v selects palette[clut_base * 16 + v].

    Transparency is value-based (PSX rule): a pixel is transparent only when the CLUT
    colour it selects is the all-zero sentinel (RGB 0,0,0), not merely when the index is
    0 — some tiles store an opaque colour (e.g. a near-white highlight) at index 0.
    Out-of-range indices are transparent.  (load_col_palettes drops the STP bit, so PSX
    opaque-black 0x8000 reads as transparent here too; identical over the black canvas,
    so only genuinely-coloured index-0 pixels differ.)
    """
    result: list[ColourRGBA] = []
    base = clut_base * 16
    pal_size = len(palette)
    for v in raw_tile:
        idx = base + v
        if idx >= pal_size:
            result.append((0, 0, 0, 0))  # out of palette range — transparent
            continue
        r, g, b, a = palette[idx]
        if r == 0 and g == 0 and b == 0:
            result.append((0, 0, 0, 0))  # all-zero CLUT colour — transparent sentinel
        else:
            result.append((r, g, b, a))   # honour stored alpha (255 unless STP-derived)
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
    chr256_override: "frozenset[int] | None" = None,
    clut_row_override: "dict[int, int] | None" = None,
    x6_page8_palette: "Palette | None" = None,
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
    chr256_indices = chr256_override if chr256_override is not None else _build_chr256_ocl_indices(ocl_entries, tex, tex_bg, tile_size)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        # OCL byte2 (stored as field 'clut_base'): encodes TEX tile coordinates
        #   cordX = byte2 & 0x0F  (low nibble)
        #   cordY = (byte2 >> 4) & 0x0F  (high nibble)
        # OCL byte3 (stored as field 'pad'): low nibble = page number
        #   gx = (page % 8) * 256 + cordX * tile_size
        #   gy = (page // 8) * 256 + cordY * tile_size
        cordX = entry.clut_base & 0xF
        cordY = (entry.clut_base >> 4) & 0xF
        # page is the low SIX bits of pad, not the low four.  Bit 0x10 is a page-band
        # selector (pad=0x10 → page 16 → the third 256px band, gy=512: the X5 rose /
        # st000 / st170 / stsel background tilesets live there).  Bit 0x40 is the X6
        # pad_hi=4 alt-CLUT-bank marker and is NOT part of the page, so it is masked off
        # — keeping X6's 0x49/0x4a/0x4b machinery tiles on pages 9/10/11 exactly as
        # before (0x4b & 0x3F == 0x4b & 0xF == 11).  pad=0xFF is filtered by the
        # page>0xB skip in the caller before reaching here.
        page = entry.pad & 0x3F

        # Texture routing:
        #   Pages 0–7: _build_chr256_ocl_indices() decides; chr256 entries use tex_bg.
        #   Pages 8–15, col=112: always tex_bg (standard chr256 palette indicator).
        #   Pages 8–15, col=0: tex_bg (col=0 is the chr256 indicator used in stages
        #     that do not use col=112, e.g. st040).
        #   Pages 8–15, other col: tex.
        if page < 8:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif ocl_idx in chr256_indices:
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

            # Bits 14-15 are flags used by the game engine (e.g. collision layer
            # selection, animation triggers). They are NOT visual flip flags —
            # OCL entries already contain pre-oriented pixel data.  Mask them off
            # to get the true OCL index (consistent with TeheManX4_Editor's
            # `id &= 0x3FFF` in Draw16xTile).
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

            # Skip the crystal sky-fill sentinel (pad=0xFF — "no TEX data").
            # TeheManX4_Editor's Draw16xTile bails for ANY page nibble > 0xB, but that
            # is an editor-preview limit (it only loads 8bpp bitmap pages 8–11), not a
            # game-draw rule.  pad=0x0F (page nibble 15, pad_hi 0) addresses real art in
            # TEX page band 1 (page & 0x3F == 15): the X5 st070 boss-room background
            # machinery.  These are the ONLY two pad bytes with a page nibble > 0xB, so
            # the slots split cleanly: pad=0xFF sky-fill (always skipped) vs pad=0x0F art
            # (drawn ONLY when its resolved block holds pixels — guard below).
            # NOTE: pad=0x10 is also drawn — page nibble 0, bit 0x10 selects page band 2
            # (the rose / st000 background tiles).
            pad_lo = entry.pad & 0xF
            if entry.pad == 0xFF:
                continue

            raw_tile = _resolve_tile(entry, tile_id)
            if raw_tile is None:
                continue  # tile not found in TEX
            if pad_lo > 0xB and not any(raw_tile):
                # page-nibble>0xB slot resolving to an all-zero block = sky-fill sentinel
                # (st000/st170 sky), not dropped art.  Skip so it stays transparent rather
                # than painting CLUT index 0 (dark-but-non-black on some stage rows).
                continue
            active_palette = palette
            clut_row = entry.abs_clut_stage()
            if clut_row_override is not None and tile_id in clut_row_override:
                clut_row = clut_row_override[tile_id]   # explicit per-index wins
            elif (x6_page8_palette is not None
                  and (entry.pad >> 4) & 0xF == 0 and 8 <= (entry.pad & 0xF) <= 0xB):
                # X6 page>=8 pad_hi=0 8bpp tile: read the raw stage CLUT at col+96.
                active_palette = x6_page8_palette
                clut_row = entry.col + _X6_PAGE8_CLUT_OFFSET
            rgba_pixels = _apply_palette_to_tile(raw_tile, clut_row, active_palette)

            tile_img = Image.new("RGBA", (tile_size, tile_size))
            tile_img.putdata(rgba_pixels)

            px = col_idx * tile_size
            py = canvas_row * tile_size
            canvas.alpha_composite(tile_img, (px, py))  # see render_level note

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
    chr256_override: "frozenset[int] | None" = None,
    clut_row_override: "dict[int, int] | None" = None,
    x6_page8_palette: "Palette | None" = None,
    bg_is_texch3: bool = False,
) -> PILImage:
    """
    Render the level using the correct screen-based addressing.

    clut_row_override (optional): maps an OCL index to a CLUT row that replaces the
    entry's default ``abs_clut_stage()``.  Used by the X6 per-stage palette-fix table
    (see render_stage.build_x6_clut_row_override) to relocate page>=8 tiles whose true
    static palette lives at a different CLUT row than ``col + 64``.  None = no override.

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
    chr256_indices = chr256_override if chr256_override is not None else _build_chr256_ocl_indices(ocl_entries, tex, tex_bg, tile_size)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        cordX = entry.clut_base & 0xF
        cordY = (entry.clut_base >> 4) & 0xF
        # See render_omp's _resolve_tile: page is pad's low SIX bits.  Bit 0x10 is a
        # page-band selector (pad=0x10 → page 16, gy=512 — the X5 rose / st000 / st170 /
        # stsel background tilesets); bit 0x40 (X6 pad_hi=4 alt-CLUT-bank) is masked off
        # so X6 machinery pages are unchanged.  pad=0xFF is filtered by the caller.
        page = entry.pad & 0x3F

        # Texture routing: see render_omp for full explanation.
        if page < 8:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif ocl_idx in chr256_indices:
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

                    # Bits 14-15 are engine flags, not visual flip signals — mask off.
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

                    # Skip the crystal sky-fill sentinel (pad=0xFF — "no TEX data").
                    # The editor's Draw16xTile bails for ANY page nibble > 0xB, but that
                    # is an editor-preview limit (it only loads 8bpp bitmap pages 8–11),
                    # not a game-draw rule.  pad=0x0F (page nibble 15, pad_hi 0) addresses
                    # real art in TEX page band 1 (page & 0x3F == 15): the X5 st070
                    # boss-room background machinery.  pad=0xFF and pad=0x0F are the ONLY
                    # two pad bytes with a page nibble > 0xB, so the slots split cleanly:
                    # pad=0xFF sky-fill (always skipped) vs pad=0x0F art (drawn ONLY when
                    # its resolved block holds pixels — guard below).  pad=0x10 is also
                    # drawn (page nibble 0, bit 0x10 selects page band 2).
                    pad_lo = entry.pad & 0xF
                    if entry.pad == 0xFF:
                        continue

                    raw_tile = _resolve_tile(entry, ocl_idx)
                    if raw_tile is None:
                        continue
                    if pad_lo > 0xB and not any(raw_tile):
                        # page-nibble>0xB slot with an all-zero block = sky-fill sentinel
                        # (st000/st170 sky), not dropped art.  Skip so it stays transparent
                        # rather than painting CLUT index 0 (dark-but-non-black on some rows).
                        continue

                    active_palette = palette
                    clut_row = entry.abs_clut_stage()
                    if clut_row_override is not None and ocl_idx in clut_row_override:
                        clut_row = clut_row_override[ocl_idx]   # explicit per-index wins
                    elif (x6_page8_palette is not None
                          and (entry.pad >> 4) & 0xF == 0 and 8 <= (entry.pad & 0xF) <= 0xB):
                        # X6 page>=8 pad_hi=0 8bpp tile: read the raw stage CLUT at col+96
                        # (bypasses normalize's null-keep — the 'inverted shadows' fix).
                        active_palette = x6_page8_palette
                        clut_row = entry.col + _X6_PAGE8_CLUT_OFFSET
                    rgba_pixels = _apply_palette_to_tile(raw_tile, clut_row, active_palette)

                    # Bit 0x4000 of the raw OMP cell marks a PSX semi-transparency tile
                    # (e.g. X5 st070's layer-0 "water wall" tiles).  Honour it by halving
                    # each opaque pixel's alpha so the tile renders as translucent water
                    # rather than the opaque block produced when the flag is ignored.
                    # Fully-transparent pixels stay transparent; non-flagged tiles are
                    # untouched (output byte-identical), so settled baselines don't move.
                    #
                    # Per-tile exemption: the 0x4000 bit is set on ~30% of placements in most
                    # stages (it doubles as an engine flag), so a stage cannot be judged
                    # opaque wholesale.  A tile resolved from a texch3 background sheet
                    # (bg_is_texch3 + routed to tex_bg) is opaque boss art (st170's Rangda
                    # Bangda W), NOT a translucent effect, so it opts out — while same-stage
                    # tiles on the main sheet (e.g. st170's honeycomb, col=5 page=1) keep STP.
                    on_texch3 = bg_is_texch3 and ocl_idx in chr256_indices
                    if raw_id & 0x4000 and not on_texch3:
                        rgba_pixels = [
                            (r, g, b, a >> 1) if a else (r, g, b, a)
                            for (r, g, b, a) in rgba_pixels
                        ]

                    tile_img = Image.new("RGBA", (tile_size, tile_size))
                    tile_img.putdata(rgba_pixels)

                    # level tile position (lx, ly)
                    lx = sx * 16 + wx
                    ly = sy * 16 + wy
                    px = lx * tile_size
                    py = ly * tile_size
                    # alpha_composite (not paste+mask) so semi-transparent pixels keep an
                    # un-premultiplied (r,g,b,a) — paste blends RGB by alpha, corrupting
                    # translucent tiles (e.g. STP waterfalls).  Tiles never overlap and the
                    # canvas under each is transparent, so opaque output is byte-identical.
                    canvas.alpha_composite(tile_img, (px, py))

    return canvas
