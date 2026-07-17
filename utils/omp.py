# OMP file format -- Stage tile-screen catalog
#
# The OMP file is a catalog of screen data for a single stage layer (the main
# platform/collision layer). Each ROW in the OMP represents one complete 16x16
# tile screen (256 tiles). The ROW NUMBER is the screen_id used by the stage's
# map layout data. Each u16 cell is an index into the stage's OCL table.
# Zero entries are transparent/empty.
#
# OMP binary structure:
#   Offset   Size    Content
#   0x0000   4 B     Magic: "OMP\x00"
#   0x0004   4 B     Reserved / version flags (= 0x00000001 LE)
#   0x0008   4 B     n_screens x 256 (LE u32; e.g. 107x256=27392 for st000)
#                    Each screen is 16x16 = 256 tiles.
#                    n_screens = value // 256.
#   0x000C   Nx2 B   Screen data: n_screens x 256 LE u16 OCL indices
#                    Row stride: 256 x 2 = 512 bytes (one row = one screen)
#                    Value 0x0000 = empty/transparent
#
# Screen/tile addressing:
#   To render level tile at position (lx, ly):
#
#     sx = lx // TILES_PER_SCREEN    # level screen x  (TILES_PER_SCREEN == 16)
#     sy = ly // TILES_PER_SCREEN    # level screen y
#     wx = lx % TILES_PER_SCREEN     # within-screen x (0-15)
#     wy = ly % TILES_PER_SCREEN     # within-screen y (0-15)
#
#     screen_id = layout[sy][sx]                   # from LayoutTable (see below)
#     omp_col   = wy * TILES_PER_SCREEN + wx       # within-screen tile index (x fast)
#     ocl_idx   = omp.tiles[screen_id][omp_col]    # OMP row = screen_id
#
# Layout table:
#   The map layout data is NOT stored in the OMP/OCL/TEX files. It lives in
#   the RXC1.exe and RXC2.exe files. LayoutTable maps each level screen
#   position (sx, sy) to a screen_id.
#
#   render_omp() renders the raw OMP screen catalog (no layout needed).
#   Supply a LayoutTable to render_level() for correct level rendering.
#
# Tile rendering pipeline:
#   OMP u16 ocl_idx
#       -> OCL entry [ocl_idx]          (utils/ocl.py)
#               col: int                 palette column; abs_clut = col + 64
#               tile_type: int           collision/behaviour type -> OclPaletteGroup
#               tile_coords (byte2): cordX (low nibble) + cordY (high nibble)
#               page_and_clutbank (byte3): page number (low nibble)
#       -> TEX raw_image  (utils/tex.py)
#               cordX = byte2 & 0xF
#               cordY = (byte2 >> 4) & 0xF
#               page  = byte3 & 0xF
#               gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * 16   # PAGES_PER_ROW == 8
#               gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * 16   # PAGE_SIZE_PX == 256
#
# TEX routing (tex vs tex_bg/chr256)
#   Most stages have two tile TEX files: st*.tex (tilemap1, tex) and
#   st*_chr256.tex (tilemap2/chr256 background, tex_bg).  build_chr256_ocl_indices()
#   computes the frozenset of OCL indices that should read from tex_bg.
#
# OCL tile_type -> palette group mapping
#   OclPaletteGroup.STANDARD          col*.col  standard + hit-flash + fallback
#   OclPaletteGroup.ANIMATED_CRYSTAL  st*.col   animated cycling palette (0x39)
#   OclPaletteGroup.ALT_AREA          col*.col  tileset2
#
#   The mapping is passed in as flags_to_palette: dict[OclPaletteGroup, Palette] so
#   this module stays reusable across stages.
#
# Layer model:
#   The OMP file represents a single stage/level.
#   Most stages are composed of three visual layers (0, 1, 2)
#   Layer 0/1: are usually the platforming and stage decals, not always
#              consistent which one is the foreground.
#   Layer 2: is usually the far background.


import bisect
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PIL.Image import Image as PILImage

from utils.consts import (
    TILE_SIZE, NIBBLE_MASK, NIBBLE_SHIFT, PAGES_PER_ROW, CHR256_PAGE_START, PAGE_SIZE_PX,
    TILES_PER_SCREEN, CLUT_COLORS_PER_ROW, CHR256_PAGE_MAX, OCL_INDEX_MASK, STP_TRANSLUCENT_BIT,
    PAGE_MASK_6bit, CHR256_COL_INDICATOR,
)
from utils.ocl import OclEntry, OclPaletteGroup
from utils.types import ColourRGBA, Palette, TexData

OMP_MAGIC = b"OMP\x00"
OMP_HEADER_SIZE = 12  # magic(4) + reserved(4) + n_rows(4)

# X6 page>=8 (8bpp) pad_hi=0 tiles read the UN-normalized stage CLUT at col+96, not
# col+64 (fixes the page>=8 "inverted shadows"; bypasses normalize's null-keep).
# pad_hi=4 page>=8 tiles are excluded -- they use build_x6_padhi_clut_override's alt bank.
_X6_PAGE8_CLUT_OFFSET = 96


@dataclass
class OmpLayer:
    """
    Each row represents one complete 16x16 tiles screen where screen_id = row index.
    tiles[screen_id][wy * TILES_PER_SCREEN + wx] = OCL index for tile (wx, wy) of that screen.
    Use render_omp() to dump the raw screen catalog for debugging.
    Use render_level() with a LayoutTable for correct level rendering.
    """
    n_screens: int          # total number of screens (OMP row count)
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
            idx = wy * TILES_PER_SCREEN + wx
            return self.tiles[screen_id][idx]
        return 0


@dataclass
class LayoutTable:
    """
    Maps level screen coordinates (sx, sy) to OMP screen_ids.

    screens[sy][sx] = screen_id  (= row index into OmpLayer.tiles)

    This data is NOT stored in the OMP/OCL/TEX files, but instead
    lives in the game EXE file.
    """
    screens: list[list[int]]  # screens[sy][sx] = screen_id

    @property
    def width(self) -> int:
        return len(self.screens[0]) if self.screens else 0

    @property
    def height(self) -> int:
        return len(self.screens)

    def get(self, sx: int, sy: int) -> int | None:
        """Return the screen_id for level screen (sx, sy), or None if unknown."""
        if 0 <= sy < len(self.screens) and 0 <= sx < len(self.screens[sy]):
            val = self.screens[sy][sx]
            return val if val >= 0 else None
        return None

    @staticmethod
    def from_partial(entries: dict[tuple[int, int], int]) -> "LayoutTable":
        """
        Only used by match_layout_to_map.py
        Builds a LayoutTable from a sparse {(sx, sy): screen_id} dict.
        Unknown entries are stored as -1 and return None from get().
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
    def from_bytes(data: bytes, width: int, height: int) -> "LayoutTable":
        """
        Parse a LayoutTable from raw layout binary data.

        Layout format: single layer, width * height bytes, each a u8 screen_id
        (0 = empty), row-major: data[sy * width + sx].

        Args:
            data:   raw bytes containing the layout data
            width:  number of screens per row
            height: number of screen rows
        """
        layer_size = width * height
        grid: list[list[int]] = []
        if layer_size > len(data):
            raise ValueError(f"Layout data too small: need {layer_size} bytes, got {len(data)}")
        for sy in range(height):
            row = [
                data[sy * width + sx]
                for sx in range(width)
            ]
            grid.append(row)
        return LayoutTable(screens=grid)


# Parse an OMP file and return an OmpLayer.
def load_omp(omp_path: Path) -> OmpLayer:
    if not omp_path.exists():
        raise FileNotFoundError(f"OMP file does not exist: {omp_path}")

    data = omp_path.read_bytes()

    if len(data) < OMP_HEADER_SIZE:
        raise ValueError(f"OMP file too small: {len(data)} bytes")

    if data[:4] != OMP_MAGIC:
        raise ValueError(f"Not an OMP file (bad magic): {data[:4]!r}")

    # The u32 at offset 8 stores n_screens x 256.
    ENTRIES_PER_SCREEN = 256
    packed = struct.unpack_from("<I", data, 8)[0]
    if packed == 0:
        raise ValueError("OMP header value at offset 8 is 0")
    if packed % ENTRIES_PER_SCREEN != 0:
        raise ValueError(f"OMP header value {packed} is not a multiple of {ENTRIES_PER_SCREEN}")

    n_screens = packed // ENTRIES_PER_SCREEN
    row_size = ENTRIES_PER_SCREEN * 2  # bytes per screen row

    tile_data_size = len(data) - OMP_HEADER_SIZE
    expected = n_screens * row_size
    if tile_data_size != expected:
        raise ValueError(f"OMP tile data size {tile_data_size} != expected {expected} (n_screens={n_screens})")

    tiles: list[list[int]] = []
    offset = OMP_HEADER_SIZE
    for _ in range(n_screens):
        row = list(struct.unpack_from(f"<{ENTRIES_PER_SCREEN}H", data, offset))
        tiles.append(row)
        offset += row_size

    return OmpLayer(n_screens=n_screens, tiles=tiles)


def load_layout_from_exe(
    exe_path: Path,
    offset: int,
    width: int,
    height: int,
) -> LayoutTable:
    """
    Load a LayoutTable from the game executable.

    @param exe_path path to EXE
    @param offset   file offset of the first layout byte for stage
    @param width    screens per row
    @param height   screen rows
    """
    layer_size = width * height
    total_size = layer_size
    data = exe_path.read_bytes()
    if offset + total_size > len(data):
        raise ValueError(f"EXE too small for layout at {hex(offset)}: need {total_size} bytes, file has {len(data) - offset}")
    layout_bytes = data[offset : offset + total_size]
    return LayoutTable.from_bytes(layout_bytes, width, height)


def build_chr256_ocl_indices(
    ocl_entries: list[OclEntry],
    tex: "TexData",
    tex_bg: "TexData",
) -> frozenset[int]:
    """
    Return a frozenset of OCL indices that should read pixel data from tex_bg
    rather than from tex.

    Pages 1-7: the OCL table groups entries sharing a texture coordinate
    (page, tile_coords).  Routing per entry within a group:
      - First occurrence (any col):       tex.
      - Non-first, same col as first:     tex (hit-flash variants).
      - Non-first, different col, group HAS a large-gap member:
            gap from first >= THRESHOLD -> tex_bg (chr256 batch); else -> tex.
      - Non-first, different col, group has NO large-gap member -> tex_bg.
      - Sole entry, tex empty:            tex_bg.
      - Sole entry, tex == tex_bg:        tex (routing irrelevant).
      - Sole entry, tex != tex_bg, index inside the chr256-batch region -> tex_bg;
        outside it -> tex (foreground-only palette variants).

    Note: a group is "large-gap" iff its total index span (last-first) >=
    CHR256_INDEX_GAP_THRESHOLD; this separates close chr256 batches from
    stage-palette groups whose variants spread across a wide OCL span.

    Pages >= 8 are handled here in Passes 3a-3c: col==0 or col==112 are the chr256
    palette indicators (-> tex_bg); other cols -> tex.

    Fix anchors (page<8 refinements): _nolg_first_is_fg_pair keeps X6 st0h ziplines on
    tex; the Pass 1e no-LG adjacency rule recovers X6 st061 same-col bg groups; the
    same-col large-gap fill gate recovers st01 rock/tree bg duplicates.
    """
    # Minimum index-span within a group that splits the stage-palette batch (tex)
    # from the chr256 background batch (tex_bg).
    CHR256_INDEX_GAP_THRESHOLD = 500

    raw_tex  = tex["raw_image"];    w_tex = tex["width"]
    raw_bg   = tex_bg["raw_image"]; w_bg  = tex_bg["width"]

    def _tex_is_empty(raw: bytes, w: int, gx: int, gy: int) -> bool:
        """Return True if all pixels in the 16x16 tile block are zero."""
        return not any(
            raw[(gy + dy) * w + gx + dx]
            for dy in range(TILE_SIZE)
            for dx in range(TILE_SIZE)
        )

    def _tex_fill(raw: bytes, w: int, gx: int, gy: int) -> int:
        """Return the count of non-zero (opaque) pixels in the 16x16 tile block."""
        return sum(
            1
            for dy in range(TILE_SIZE)
            for dx in range(TILE_SIZE)
            if raw[(gy + dy) * w + gx + dx]
        )

    # Pass 0: count occurrences per key so standalone entries can be detected
    key_count: dict[tuple[int, int], int] = {}
    for e in ocl_entries:
        if e.tex_page >= CHR256_PAGE_START:
            continue
        key = (e.tex_page, e.tile_coords)
        key_count[key] = key_count.get(key, 0) + 1

    # Pass 1: record first col per key and collect all OCL indices per key.
    first_col: dict[tuple[int, int], int] = {}
    group_indices: dict[tuple[int, int], list[int]] = {}
    for i, e in enumerate(ocl_entries):
        if e.tex_page >= CHR256_PAGE_START:
            continue
        key = (e.tex_page, e.tile_coords)
        if key not in first_col:
            first_col[key] = e.col
            group_indices[key] = []
        group_indices[key].append(i)

    # Pass 1b: for each multi-entry group, determine if the total index span
    # (last - first) >= CHR256_INDEX_GAP_THRESHOLD.  Total span (not max
    # consecutive gap) handles groups whose consecutive pairs are close but whose
    # overall range is large.
    group_has_large_gap: dict[tuple[int, int], bool] = {}
    for key, idxs in group_indices.items():
        if len(idxs) < 2:
            group_has_large_gap[key] = False
            continue
        sorted_idxs = sorted(idxs)
        group_has_large_gap[key] = (
            sorted_idxs[-1] - sorted_idxs[0] >= CHR256_INDEX_GAP_THRESHOLD
        )

    # Pass 1b2: check whether tex_bg has tile data at each group's coordinates.
    # Groups where tex_bg is empty are foreground batches -- never route to tex_bg
    # even if their OCL indices form a close cluster.
    group_bg_has_data: dict[tuple[int, int], bool] = {}
    for key in group_indices:
        page_k, clut_k = key
        cordX_k = clut_k & NIBBLE_MASK; cordY_k = (clut_k >> NIBBLE_SHIFT) & NIBBLE_MASK
        gx_k = (page_k % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX_k * TILE_SIZE
        gy_k = (page_k // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY_k * TILE_SIZE
        group_bg_has_data[key] = not _tex_is_empty(raw_bg, w_bg, gx_k, gy_k)

    # Pass 1c: compute the index range spanned by all no-large-gap groups.  The
    # range [no_lg_min - THRESHOLD, no_lg_max + THRESHOLD] is the "chr256 batch
    # region"; sole tex!=tex_bg entries are chr256 only when their index falls inside.
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
        """True if idx is within CHR256_INDEX_GAP_THRESHOLD of the no-LG group range."""
        if _no_lg_min < 0:
            return False
        return _no_lg_min - CHR256_INDEX_GAP_THRESHOLD <= idx <= _no_lg_max + CHR256_INDEX_GAP_THRESHOLD

    # Pass 1d: the set of texture pages hosting at least one no-large-gap group
    # member.  Sole tex!=tex_bg entries are chr256 only when their page is in this
    # set (entries on OTHER pages are foreground tiles that merely differ from the
    # bg texture at the same coordinate).
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
        if (gx + TILE_SIZE > w_tex or gy + TILE_SIZE > h_tex or
                gx + TILE_SIZE > w_bg  or gy + TILE_SIZE > h_bg):
            return False
        return not all(
            raw_tex[(gy + dy) * w_tex + gx + dx] ==
            raw_bg [(gy + dy) * w_bg  + gx + dx]
            for dy in range(TILE_SIZE)
            for dx in range(TILE_SIZE)
        )

    # Gate for the tex_empty sole-entry rule.
    # When a stage has BOTH no-LG groups (a defined chr256 region) AND sole
    # tex!=tex_bg entries, restrict the tex_empty check to the chr256 region too,
    # else transparent fg slots sharing a tex_bg coordinate would wrongly read tex_bg.
    _has_sole_diff = _no_lg_min >= 0 and any(
        e.tex_page < CHR256_PAGE_START
        and key_count.get((e.tex_page, e.tile_coords), 0) == 1
        and not _tex_is_empty(
            raw_tex, w_tex,
            e.tex_page % PAGES_PER_ROW * PAGE_SIZE_PX + e.cordX * TILE_SIZE,
            e.tex_page // PAGES_PER_ROW * PAGE_SIZE_PX + e.cordY * TILE_SIZE,
        )
        and _tiles_differ(
            e.tex_page % PAGES_PER_ROW * PAGE_SIZE_PX + e.cordX * TILE_SIZE,
            e.tex_page // PAGES_PER_ROW * PAGE_SIZE_PX + e.cordY * TILE_SIZE,
        )
        for e in ocl_entries
    )
    # If both conditions are met, sole-entry tex_empty is gated by _in_chr256_region.
    _gate_tex_empty = _has_sole_diff

    # Pass 1e: same-col large-gap groups whose first occurrence (fi) is immediately
    # adjacent (distance <= _NOLG_DIST_THRESHOLD) to a no-LG chr256 group on the same
    # page -> whole group is background batch.
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
            continue  # mixed-col group -- handled by different-col rule
        _page_k, _clut_k = _key
        _cordX_k = _clut_k & NIBBLE_MASK
        _cordY_k = (_clut_k >> NIBBLE_SHIFT) & NIBBLE_MASK
        _gx_k = (_page_k % PAGES_PER_ROW) * PAGE_SIZE_PX + _cordX_k * TILE_SIZE
        _gy_k = (_page_k // PAGES_PER_ROW) * PAGE_SIZE_PX + _cordY_k * TILE_SIZE
        if _tex_is_empty(raw_bg, w_bg, _gx_k, _gy_k):
            continue  # tex_bg empty -- not a background tile
        if not _tiles_differ(_gx_k, _gy_k):
            continue  # identical pixels in both textures -- routing is irrelevant
        if _min_dist_to_nolg(_sorted_g[0], _page_k) <= _NOLG_DIST_THRESHOLD:
            _lg_samecol_chr256_keys.add(_key)

    def _nolg_first_is_fg_pair(key: tuple[int, int]) -> bool:
        """
        True when a no-large-gap group is a foreground/background DUPLICATE pair whose
        FIRST occurrence is a foreground tile (belongs on tex), not a chr256 batch.
        Only the FIRST occurrence is foreground; later occurrences remain chr256.

        Signature (all three required):
          - first occurrence is NOT a 0x38 hit-flash variant (a 0x38 always shares
            its base tile's pixel data and stays chr256); AND
          - first col differs from a later member's col (mixed col -> fg/bg pair); AND
          - first occurrence holds a SPARSE fg sprite (fg_fill>0, fg_fill*3 <= bg_fill,
            i.e. <= ~1/3 of the tile) over an essentially SOLID differing tex_bg tile
            (bg_fill >= 3/4 area).  The *3 form (vs the large-gap rule's *2) excludes
            half-filled dense-stipple palette variants that must stay on tex_bg.
        """
        idxs = group_indices[key]
        if len(idxs) < 2:
            return False
        s = sorted(idxs)
        fi = s[0]
        if ocl_entries[fi].tile_type == OclPaletteGroup.ALT_PALETTE:
            return False  # hit-flash variant: shares batch pixel data, never fg
        if all(ocl_entries[j].col == ocl_entries[fi].col for j in s):
            return False  # same col -> palette/hit-flash variant batch, keep as chr256
        page_k, clut_k = key
        cordX_k = clut_k & NIBBLE_MASK; cordY_k = (clut_k >> NIBBLE_SHIFT) & NIBBLE_MASK
        gx_k = (page_k % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX_k * TILE_SIZE
        gy_k = (page_k // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY_k * TILE_SIZE
        fg = _tex_fill(raw_tex, w_tex, gx_k, gy_k)
        bg = _tex_fill(raw_bg, w_bg, gx_k, gy_k)
        return (fg > 0 and bg >= (TILE_SIZE * TILE_SIZE * 3) // 4
                and fg * 3 <= bg and _tiles_differ(gx_k, gy_k))

    seen: set[tuple[int, int]] = set()
    chr256: set[int] = set()
    for i, e in enumerate(ocl_entries):
        if e.tex_page >= CHR256_PAGE_START:
            continue
        key = (e.tex_page, e.tile_coords)
        if key_count[key] == 1:
            # Sole entry: tex_bg when tex is empty here, or when tex differs from
            # tex_bg but only within the chr256-batch region.  When _gate_tex_empty
            # is active, the tex_empty rule is also restricted to that region.
            gx = (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
            gy = (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
            if _tex_is_empty(raw_tex, w_tex, gx, gy):
                if not _gate_tex_empty or _in_chr256_region(i):
                    chr256.add(i)
            elif _tiles_differ(gx, gy) and _in_chr256_region(i) and e.tex_page in _pages_with_no_lg and not _tex_is_empty(raw_bg, w_bg, gx, gy):
                chr256.add(i)
            continue
        if key in seen:
            if not group_has_large_gap[key]:
                # All entries in this group are in the same close batch -> the
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
                #       batch on the same page, so the whole group is background; or
                #   (b) this is a later occurrence at a large index gap whose tex_bg
                #       coordinate holds a SOLID tile while tex holds only a sparse,
                #       differing fragment -- a genuine same-col background duplicate
                #       where the foreground version is missing/incomplete.  The first
                #       occurrence is the real foreground tile (tex); the far, same-col
                #       duplicate is the chr256 background variant.  This mirrors the
                #       page>=8 rule in Pass 3c for the page<8 case the different-col
                #       rule above (col != first_col) cannot reach when the whole group
                #       shares one col.
                #
                #       The fill gate (tex_bg solid AND tex fragment <= half of it) is
                #       what keeps genuine FOREGROUND objects in tex: a coherent fg
                #       tile fills its block, so tex_fill is not far below tex_bg_fill
                #       and the entry stays on tex even when tex_bg happens to hold
                #       unrelated data at the same coordinate
                #
                #       NOTE: this gate misfires on fully-painted background TRANSITION
                #       tiles (dense tex pixels read as a foreground object).
                #       Those are recovered by the contiguous-strip gap-fill pass in
                #        render_stage.build_x6_chr256_override.
                if key in _lg_samecol_chr256_keys:
                    chr256.add(i)
                else:
                    fi = group_indices[key][0]
                    gx = (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
                    gy = (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
                    if (i - fi) >= CHR256_INDEX_GAP_THRESHOLD and group_bg_has_data[key]:
                        bg_fill = _tex_fill(raw_bg, w_bg, gx, gy)
                        fg_fill = _tex_fill(raw_tex, w_tex, gx, gy)
                        # tex_bg essentially solid (continuous background) and the tex
                        # fragment covers at most half of it -> fg version is missing.
                        if (bg_fill >= (TILE_SIZE * TILE_SIZE * 3) // 4
                                and fg_fill * 2 <= bg_fill
                                and _tiles_differ(gx, gy)):
                            chr256.add(i)
        else:
            seen.add(key)
            if not group_has_large_gap[key]:
                # First occurrence of an all-close (no-large-gap) group: the whole
                # group belongs to the chr256 batch, including this first entry --
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
    # When a (page, tile_coords) group on page>=8 has:
    #   - 2+ OCL entries
    #   - total span (max_idx - min_idx) < CHR256_INDEX_GAP_THRESHOLD
    #   - at least one member with col in (0, CHR256_COL_INDICATOR)  [chr256 palette indicator]
    #   - tex_bg has non-empty pixel data at those coordinates
    # then ALL members of the group belong to the chr256 (background) batch.
    _pg8_groups: dict[tuple[int, int], list[int]] = {}
    for i, e in enumerate(ocl_entries):
        if e.tex_page < CHR256_PAGE_START:
            continue
        key = (e.tex_page, e.tile_coords)
        if key not in _pg8_groups:
            _pg8_groups[key] = []
        _pg8_groups[key].append(i)

    for key, idxs in _pg8_groups.items():
        if len(idxs) < 2:
            continue
        sorted_g = sorted(idxs)
        if sorted_g[-1] - sorted_g[0] >= CHR256_INDEX_GAP_THRESHOLD:
            continue
        if not any(ocl_entries[j].col in (0, CHR256_COL_INDICATOR) for j in idxs):
            continue
        page_k, clut_k = key
        cordX_k = clut_k & NIBBLE_MASK; cordY_k = (clut_k >> NIBBLE_SHIFT) & NIBBLE_MASK
        gx_k = (page_k % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX_k * TILE_SIZE
        gy_k = (page_k // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY_k * TILE_SIZE
        if _tex_is_empty(raw_bg, w_bg, gx_k, gy_k):
            continue
        # Only add members whose col is NOT the standard-palette marker (0 or 112).
        # In groups with mixed col values (e.g. col=0 foreground + col=16 background),
        # the col=0 member is the foreground tile sharing the same pixel coordinates;
        # it must stay in tex.  The col=0/112 members are handled independently by
        # Pass 3b's proximity check.
        chr256.update(j for j in idxs if ocl_entries[j].col not in (0, CHR256_COL_INDICATOR))

    # Pass 3b: page>=8 sole entries -- col=0/112 proximity check.
    # A sole page>=8 col-0/112 entry is chr256 when:
    #   (a) no chr256 batch region was detected (_no_lg_min < 0, e.g. st000), OR
    #   (b) the entry's OCL index is within CHR256_INDEX_GAP_THRESHOLD of the
    #       highest page<8 chr256 index (_chr256_max_pg_lt8).
    # Using the page<8-only max (not the post-3a max) keeps the proximity anchor
    # stable and avoids unintended cascading additions.
    #
    # The proximity check uses abs() (bilateral) rather than a one-sided comparison.
    # A one-sided check (i - max <= THRESHOLD) would admit foreground col=112 tiles
    # that happen to appear far BEFORE the chr256 batch -- their small OCL index
    # satisfies the one-sided inequality even when they are thousands of positions
    # away from the batch maximum.
    # The bilateral check rejects any entry whose distance to the batch max exceeds
    # THRESHOLD from either side, ensuring only tiles genuinely adjacent to the
    # end of the chr256 batch are included.
    for i, e in enumerate(ocl_entries):
        if e.tex_page < CHR256_PAGE_START:
            continue
        if e.col not in (0, CHR256_COL_INDICATOR):
            continue
        if _no_lg_min < 0 or (_chr256_max_pg_lt8 >= 0 and abs(i - _chr256_max_pg_lt8) <= CHR256_INDEX_GAP_THRESHOLD):
            chr256.add(i)

    # Pass 3c: page>=8 large-span different-col groups.
    # When a (page, tile_coords) group on page>=8 has:
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
    # is the chr256 background variant (tex_bg) -- exactly as Pass 2 does for page<8
    # using `col != first_col`.
    #
    # The later/background col may be either HIGHER than the first col or LOWER
    # than it.  Both are background entries, so the test is `cv != fc`,
    # not `cv > fc` -- a one-sided `cv > fc` check left st02's col=96
    # background tiles reading the foreground texture, producing garbled output.
    #
    # Same-col entries in large-span page>=8 groups are left in tex regardless of
    # their gap (they are hit-flash/palette variants sharing the tex tile data).
    for key, idxs in _pg8_groups.items():
        if len(idxs) < 2:
            continue
        sorted_g = sorted(idxs)
        if sorted_g[-1] - sorted_g[0] < CHR256_INDEX_GAP_THRESHOLD:
            continue  # small span -- already handled by Pass 3a
        fi = sorted_g[0]
        fc = ocl_entries[fi].col
        if all(ocl_entries[j].col == fc for j in sorted_g):
            continue  # all same col -- no chr256 batch split
        page_k, clut_k = key
        cordX_k = clut_k & NIBBLE_MASK; cordY_k = (clut_k >> NIBBLE_SHIFT) & NIBBLE_MASK
        gx_k = (page_k % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX_k * TILE_SIZE
        gy_k = (page_k // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY_k * TILE_SIZE
        if _tex_is_empty(raw_bg, w_bg, gx_k, gy_k):
            continue  # no background pixel data -- not a chr256 tile
        for j in sorted_g:
            cv = ocl_entries[j].col
            if (j - fi) >= CHR256_INDEX_GAP_THRESHOLD and cv != fc:
                chr256.add(j)

    return frozenset(chr256)



def _apply_palette_to_tile(
    raw_tile: list[int],
    clut_base: int,
    palette: Palette,
) -> list[ColourRGBA]:
    """
    Convert a list of raw 8bpp tile pixel values to RGBA colours using a palette.
    Each pixel value v selects palette[clut_base * CLUT_COLORS_PER_ROW + v].

    Transparency is value-based (PSX rule): a pixel is transparent only when the CLUT
    colour it selects is the all-zero sentinel (RGB 0,0,0), not merely when the index is
    0 -- some tiles store an opaque colour (e.g. a near-white highlight) at index 0.
    Out-of-range indices are transparent.  (load_col_palettes drops the STP bit, so PSX
    opaque-black 0x8000 reads as transparent here too; identical over the black canvas,
    so only genuinely-coloured index-0 pixels differ.)
    """
    result: list[ColourRGBA] = []
    base = clut_base * CLUT_COLORS_PER_ROW
    pal_size = len(palette)
    for v in raw_tile:
        idx = base + v
        if idx >= pal_size:
            result.append((0, 0, 0, 0))  # out of palette range -- transparent
            continue
        r, g, b, a = palette[idx]
        if r == 0 and g == 0 and b == 0:
            result.append((0, 0, 0, 0))  # all-zero CLUT colour -- transparent sentinel
        else:
            result.append((r, g, b, a))   # honour stored alpha (255 unless STP-derived)
    return result


def render_omp(
    layer: OmpLayer,
    ocl_entries: list[OclEntry],
    tex: TexData,
    tex_bg: TexData,
    flags_to_palette: dict[OclPaletteGroup, Palette],
    chr256_override: "frozenset[int] | None" = None,
    clut_row_override: "dict[int, int] | None" = None,
    x6_page8_palette: "Palette | None" = None,
) -> PILImage:
    """
    Render the raw OMP screen catalog to a PIL RGBA image for debugging.

    This renders screen_ids as sequential rows, so the output is a grid of
    all 256 within-screen slots laid out flat -- NOT the actual level layout.
    To render the level correctly, use render_level() with a LayoutTable instead.

    layer:             parsed OmpLayer from load_omp()
    ocl_entries:       list of OclEntry from load_ocl() for this stage
    tex:               TexData from the stage tileset1
    tex_bg:            TexData from the stage tileset2
    flags_to_palette:  maps OclPaletteGroup -> Palette. OclEntry.palette_group() maps
                       any tile_type to one of the named groups; unregistered collision
                       types fall back to STANDARD so no tile is silently dropped.

    Returns an RGBA PIL Image with dimensions (256 * tile_size, n_screens * tile_size).
    """
    r_start = 0
    r_end = layer.height

    canvas_w = layer.width * TILE_SIZE
    canvas_h = layer.height * TILE_SIZE
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    chr256_indices = chr256_override if chr256_override is not None else build_chr256_ocl_indices(ocl_entries, tex, tex_bg)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        page = entry.page_and_clutbank & PAGE_MASK_6bit

        # Texture routing:
        #   Pages 0-7: build_chr256_ocl_indices() decides; chr256 entries use tex_bg.
        #   Pages 8-15, col=112: always tex_bg (standard chr256 palette indicator).
        #   Pages 8-15, col=0: tex_bg (col=0 is the chr256 indicator used in stages
        #     that do not use col=112, e.g. st040).
        #   Pages 8-15, other col: tex.
        if page < CHR256_PAGE_START:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif ocl_idx in chr256_indices:
            active_tex = tex_bg
        else:
            active_tex = tex

        raw_pixels = active_tex["raw_image"]
        active_width = active_tex["width"]
        active_height = len(raw_pixels) // active_width if active_width > 0 else 0


        gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
        gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
        if gx + TILE_SIZE > active_width or gy + TILE_SIZE > active_height:
            return None
        result: list[int] = []
        for row in range(TILE_SIZE):
            row_start = (gy + row) * active_width + gx
            result.extend(raw_pixels[row_start : row_start + TILE_SIZE])
        return result

    for row_idx in range(r_start, r_end):
        canvas_row = row_idx - r_start
        for col_idx in range(layer.width):
            raw_id = layer.tiles[row_idx][col_idx]
            if raw_id == 0:
                continue  # transparent

            # Bits 14-15 are flags used by the game engine (e.g. collision layer
            # selection, animation triggers). They are NOT visual flip flags --
            # OCL entries already contain pre-oriented pixel data.  Mask them off
            # to get the true OCL index.
            tile_id = raw_id & OCL_INDEX_MASK

            if tile_id >= len(ocl_entries):
                continue  # out of range -- skip silently

            entry = ocl_entries[tile_id]
            palette = flags_to_palette.get(
                entry.palette_group(),
                flags_to_palette.get(OclPaletteGroup.STANDARD),
            )
            if palette is None:
                continue  # no palette registered at all -- skip

            # Skip the empty sentinel.
            # page_and_clutbank=0x0F (page nibble 15, pad_hi 0) addresses real art in
            # TEX page band 1 (page & PAGE_MASK_6bit == 15): the X5 st070 boss-room background
            # machinery.  These are the ONLY two pad bytes with a page nibble > 0xB, so
            # the slots split cleanly: is_empty vs page_and_clutbank=0x0F art
            # (drawn ONLY when its resolved block holds pixels -- guard below).
            # NOTE: page_and_clutbank=0x10 is also drawn -- page nibble 0, bit 0x10 selects page band 2
            # (the rose / st000 background tiles).
            if entry.is_empty:
                continue

            raw_tile = _resolve_tile(entry, tile_id)
            if raw_tile is None:
                continue  # tile not found in TEX
            if entry.tex_page > CHR256_PAGE_MAX and not any(raw_tile):
                # page-nibble>0xB slot resolving to an all-zero block = empty sentinel
                # (st000/st170 sky), not dropped art.  Skip so it stays transparent rather
                # than painting CLUT index 0.
                continue
            active_palette = palette
            clut_row = entry.abs_clut_stage()
            if clut_row_override is not None and tile_id in clut_row_override:
                clut_row = clut_row_override[tile_id]   # explicit per-index wins
            elif (x6_page8_palette is not None
                  and entry.clut_bank_selector == 0 and CHR256_PAGE_START <= entry.tex_page <= CHR256_PAGE_MAX):
                # X6 page>=8 pad_hi=0 8bpp tile: read the raw stage CLUT at col+96.
                active_palette = x6_page8_palette
                clut_row = entry.col + _X6_PAGE8_CLUT_OFFSET
            rgba_pixels = _apply_palette_to_tile(raw_tile, clut_row, active_palette)

            tile_img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE))
            tile_img.putdata(rgba_pixels)

            px = col_idx * TILE_SIZE
            py = canvas_row * TILE_SIZE
            canvas.alpha_composite(tile_img, (px, py))

    return canvas


def render_level(
    layer: OmpLayer,
    ocl_entries: list[OclEntry],
    layout: LayoutTable,
    level_width_screens: int,
    level_height_screens: int,
    tex: TexData,
    tex_bg: TexData,
    flags_to_palette: dict[OclPaletteGroup, Palette],
    chr256_override: "frozenset[int] | None" = None,
    clut_row_override: "dict[int, int] | None" = None,
    x6_page8_palette: "Palette | None" = None,
    bg_is_texch3: bool = False,
) -> PILImage:
    """
    Render the level using the correct screen-based layout addressing.

    layout:               LayoutTable mapping (sx, sy) -> screen_id
    level_width_screens:  number of screens horizontally
    level_height_screens: number of screens vertically
    clut_row_override (optional): maps an OCL index to a CLUT row that replaces the
    entry's default ``abs_clut_stage()``.  Used by the X6 per-stage palette-fix table
    (see render_stage.build_x6_clut_row_override) to relocate page>=8 tiles whose true
    static palette lives at a different CLUT row than ``col + 64``.  None = no override.

    Unlike render_omp(), this function uses the LayoutTable to map level tile positions
    to the correct OMP screens.

    Addressing:
        screen_id = layout.get(sx, sy)
        omp_col   = wy * TILES_PER_SCREEN + wx   (within-screen index, x fast)
        ocl_idx   = layer.tiles[screen_id][omp_col]
    """
    canvas_w = level_width_screens * TILES_PER_SCREEN * TILE_SIZE
    canvas_h = level_height_screens * TILES_PER_SCREEN * TILE_SIZE
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    chr256_indices = chr256_override if chr256_override is not None else build_chr256_ocl_indices(ocl_entries, tex, tex_bg)

    def _resolve_tile(entry: OclEntry, ocl_idx: int) -> list[int] | None:
        # Identical to _resolve_tile() in render_omp()
        page = entry.page_and_clutbank & PAGE_MASK_6bit

        if page < CHR256_PAGE_START:
            active_tex = tex_bg if ocl_idx in chr256_indices else tex
        elif ocl_idx in chr256_indices:
            active_tex = tex_bg
        else:
            active_tex = tex

        raw_pixels = active_tex["raw_image"]
        active_width = active_tex["width"]
        active_height = len(raw_pixels) // active_width if active_width > 0 else 0

        gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
        gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
        if gx + TILE_SIZE > active_width or gy + TILE_SIZE > active_height:
            return None
        result: list[int] = []
        for row in range(TILE_SIZE):
            row_start = (gy + row) * active_width + gx
            result.extend(raw_pixels[row_start : row_start + TILE_SIZE])
        return result

    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            screen_id = layout.get(sx, sy)
            if screen_id is None or screen_id >= layer.n_screens:
                continue  # screen not in layout table -- skip

            screen_tiles = layer.tiles[screen_id]

            for wy in range(TILES_PER_SCREEN):
                for wx in range(TILES_PER_SCREEN):
                    omp_col = wy * TILES_PER_SCREEN + wx
                    raw_id = screen_tiles[omp_col]
                    if raw_id == 0:
                        continue  # transparent

                    # Bits 14-15 are flags used by the game engine (e.g. collision layer
                    # selection, animation triggers). They are NOT visual flip flags --
                    # OCL entries already contain pre-oriented pixel data.  Mask them off
                    # to get the true OCL index.
                    ocl_idx = raw_id & OCL_INDEX_MASK

                    if ocl_idx >= len(ocl_entries):
                        continue

                    entry = ocl_entries[ocl_idx]
                    palette = flags_to_palette.get(
                        entry.palette_group(),
                        flags_to_palette.get(OclPaletteGroup.STANDARD),
                    )
                    if palette is None:
                        continue  # no palette registered at all -- skip

                    # Skip the empty sentinel.
                    # page_and_clutbank=0x0F (page nibble 15, pad_hi 0) addresses real art in
                    # TEX page band 1 (page & PAGE_MASK_6bit == 15): the X5 st070 boss-room background
                    # machinery.  These are the ONLY two pad bytes with a page nibble > 0xB, so
                    # the slots split cleanly: is_empty vs page_and_clutbank=0x0F art
                    # (drawn ONLY when its resolved block holds pixels -- guard below).
                    # NOTE: page_and_clutbank=0x10 is also drawn -- page nibble 0, bit 0x10 selects page band 2
                    # (the rose / st000 background tiles).
                    if entry.is_empty:
                        continue

                    raw_tile = _resolve_tile(entry, ocl_idx)
                    if raw_tile is None:
                        continue
                    if entry.tex_page > CHR256_PAGE_MAX and not any(raw_tile):
                        # page-nibble>0xB slot with an all-zero block = sky-fill sentinel
                        # (st000/st170 sky), not dropped art.  Skip so it stays transparent
                        # rather than painting CLUT index 0 (dark-but-non-black on some rows).
                        continue

                    active_palette = palette
                    clut_row = entry.abs_clut_stage()
                    if clut_row_override is not None and ocl_idx in clut_row_override:
                        clut_row = clut_row_override[ocl_idx]   # explicit per-index wins
                    elif (x6_page8_palette is not None
                          and entry.clut_bank_selector == 0 and CHR256_PAGE_START <= entry.tex_page <= CHR256_PAGE_MAX):
                        # X6 page>=8 pad_hi=0 8bpp tile: read the raw stage CLUT at col+96
                        # (bypasses normalize's null-keep -- the 'inverted shadows' fix).
                        active_palette = x6_page8_palette
                        clut_row = entry.col + _X6_PAGE8_CLUT_OFFSET
                    rgba_pixels = _apply_palette_to_tile(raw_tile, clut_row, active_palette)

                    # Bit STP_TRANSLUCENT_BIT of the raw OMP cell marks a PSX semi-transparency tile
                    # (e.g. X5 st070's layer-0 "water wall" tiles).  Honour it by halving
                    # each opaque pixel's alpha so the tile renders as translucent water
                    # rather than the opaque block produced when the flag is ignored.
                    # Fully-transparent pixels stay transparent; non-flagged tiles are
                    # untouched (output byte-identical), so settled baselines don't move.
                    #
                    # Per-tile exemption: the STP_TRANSLUCENT_BIT is set on ~30% of placements in most
                    # stages (it doubles as an engine flag), so a stage cannot be judged
                    # opaque wholesale.  A tile resolved from a texch3 background sheet
                    # (bg_is_texch3 + routed to tex_bg) is opaque boss art (st170's Rangda
                    # Bangda W), NOT a translucent effect, so it opts out -- while same-stage
                    # tiles on the main sheet (e.g. st170's honeycomb, col=5 page=1) keep STP.
                    on_texch3 = bg_is_texch3 and ocl_idx in chr256_indices
                    if raw_id & STP_TRANSLUCENT_BIT and not on_texch3:
                        rgba_pixels = [
                            (r, g, b, a >> 1) if a else (r, g, b, a)
                            for (r, g, b, a) in rgba_pixels
                        ]

                    tile_img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE))
                    tile_img.putdata(rgba_pixels)

                    # level tile position (lx, ly)
                    lx = sx * TILES_PER_SCREEN + wx
                    ly = sy * TILES_PER_SCREEN + wy
                    px = lx * TILE_SIZE
                    py = ly * TILE_SIZE
                    # alpha_composite (not paste+mask) so semi-transparent pixels keep an
                    # un-premultiplied (r,g,b,a) -- paste blends RGB by alpha, corrupting
                    # translucent tiles (e.g. STP waterfalls).  Tiles never overlap and the
                    # canvas under each is transparent, so opaque output is byte-identical.
                    canvas.alpha_composite(tile_img, (px, py))

    return canvas
