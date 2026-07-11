# OCL file format — Object Colour Lookup table
#
# The OCL file is a per-stage flat array of 4-byte entries. Each entry encodes
# both the CLUT (palette row) assignment and the TEX tile coordinates for one
# tile slot in the stage. It is indexed directly by the u16 values stored in the
# OMP file (after stripping any flip flags).
#
# ============================================================
# OCL binary format (confirmed against st000.ocl, 15,120 bytes)
# ============================================================
#
#   Offset   Size    Content
#   ────────────────────────────────────────────────────────
#   0x0000   4 B     Magic: "OCL\x00"
#   0x0004   4 B     Version (LE u32 = 1)
#   0x0008   4 B     Entry count (LE u32; 3777 for st000)
#   0x000C   N×4 B   Entries (one per tile slot):
#
#   Per-entry byte layout (confirmed):
#     byte 0 – tile_type:  collision / behaviour type (X4 editor: "col" / collisionType)
#                           Bits [5:0] = collision type (0–63); bits [7:6] always 0.
#                           Values observed: 0x00–0x3F across X4/X5/X6.
#                           Three values carry palette-variant meaning in X5:
#                             0x00–0x37, 0x3A, 0x3C–0x3F = standard tileset palette
#                             0x38 = alt/hit-flash palette variant (same col file)
#                             0x39 = animated cycling palette (st0_0.col)
#                             0x3B = alt-area tileset palette (col00_0z.col)
#     byte 1 – col:     palette column; abs_clut = col + 64  (confirmed)
#     byte 2 – (named 'clut_base', legacy misnomer):
#                       TEX tile position encoding —
#                         cordX = byte2 & 0x0F   (low  nibble, tile column within page)
#                         cordY = (byte2 >> 4) & 0x0F  (high nibble, tile row within page)
#     byte 3 – (named 'pad', legacy misnomer):
#                       TEX page encoding —
#                         page  = byte3 & 0x0F
#                       Values observed: 0–5, 10, 11, 15, 16 (0x10), 255 (0xFF)
#                       Pages 0..CHR256_PAGE_START-1 (0–7) are 4bpp (the tex sheet);
#                       pages CHR256_PAGE_START.. (8+) are 8bpp and route to chr256
#                       (tex_bg).  See utils/consts.CHR256_PAGE_START.
#                       page=16 (0x10→masked to 0) = player/sprite tiles
#                       page=255 = sentinel/unused entry
#
# ============================================================
# TEX tile coordinate formula (confirmed)
# ============================================================
#
#   Given an OclEntry e, the nibble fields are exposed as properties — prefer
#   e.page / e.cordX / e.cordY over masking pad/clut_base by hand:
#     cordX = e.cordX   # == e.clut_base & 0x0F         (low  nibble)
#     cordY = e.cordY   # == (e.clut_base >> 4) & 0x0F  (high nibble)
#     page  = e.page    # == e.pad & 0x0F
#
#     gx = (e.page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * 16   # pixel X of tile top-left in TEX
#     gy = (e.page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * 16   # pixel Y of tile top-left in TEX
#     (PAGES_PER_ROW == 8: a TEX sheet holds 8 pages across, so page // 8 is the
#      sheet row/band and page % 8 the column within it.  PAGE_SIZE_PX == 256:
#      each page is 256x256 px.)
#
#   tex_x (tile column in TEX) = e.page * 16 + e.cordX
#   tex_y (tile row    in TEX) = e.cordY
#
#   The HIGH nibble of pad — (e.pad >> 4) & 0x0F — is the X6 pad_hi CLUT-bank
#   selector, NOT a tile coordinate; use the e.clut_bank_selector property.
#
# ============================================================
# CLUT formula (confirmed)
# ============================================================
#
#   abs_clut = e.col + 64
#
#   Confirmed against omp-to-expected-tiles.csv cross-check:
#     OCL[1092]: col=3  → abs_clut=67  ✓
#     OCL[715]:  col=26 → abs_clut=90  ✓
#     OCL[1371]: col=4  → abs_clut=68  ✓
#
# ============================================================
# Field name note
# ============================================================
#
#   The OclEntry field names 'clut_base' and 'pad' are legacy misnomers
#   inherited from early reverse engineering. They are kept unchanged to avoid
#   breaking existing callers. See byte layout above for their actual meaning.
#
# ============================================================
# CHR companion files (context only — not OCL format)
# ============================================================
#
#   PC/X5/chr/stage/ per-enemy directory contains:
#     obj00_0a.ctex   — CTEX manifest ("CTEX\x00"); links numbered .tex files
#     obj00_0a_N.cof  — COF colour-offset file ("COF\x00"); TEX path + checksum
#                       CLUT assignments are NOT in .cof; they live in OCL.
#
# ============================================================

import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from utils.consts import NIBBLE_MASK, NIBBLE_SHIFT

OCL_MAGIC = b"OCL\x00"
OCL_HEADER_SIZE = 12  # magic(4) + version(4) + entry_count(4)
OCL_ENTRY_SIZE = 4

# Stage tile CLUTs begin at VRAM row 64, immediately after the 64-row player /
# sprite palette block.  abs_clut = col + STAGE_CLUT_BASE_ROW.  This is the single
# source of truth for the stage CLUT base; see utils/palette.py for the VRAM layout.
STAGE_CLUT_BASE_ROW = 64


class OclPaletteGroup(IntEnum):
    """
    Palette variant group derived from an OCL entry's tile_type byte.

    In X4/X5/X6, byte 0 of each OCL entry is the tile collision/behaviour type
    (the X4 editor labels it "col" and extracts it as ``collisionType = val & 0x3F``
    in Draw16xTile).  Only three tile_type values select a different palette source
    in X5; all other collision types use STANDARD.

    Use OclEntry.palette_group() to map an arbitrary tile_type to one of these.
    """
    STANDARD          = 0x00  # standard tileset (col00_0x.col)
    ALT_PALETTE       = 0x38  # alt/hit-flash variant — same COL file, kept distinct
    ANIMATED_CRYSTAL  = 0x39  # animated cycling palette (st0_0.col in X5)
    ALT_AREA          = 0x3B  # alt-area tileset (col00_0z.col in X5)
    UNKNOWN           = 0xFF  # sentinel for unregistered collision types (never a real tile_type)


@dataclass
class OclEntry:
    tile_type: int  # byte 0: collision / behaviour type (X4 editor: "col", Draw16xTile: collisionType)
                    #   bits [5:0] = collision type; bits [7:6] always 0.
                    #   Three values carry X5 palette-variant meaning — see OclPaletteGroup.
    col: int        # byte 1: palette column; abs_clut = col + 64  (confirmed)
    clut_base: int  # byte 2: TEX tile coords (legacy field name — NOT a CLUT index)
                    #   low nibble  -> cordX
                    #   high nibble -> cordY
    pad: int        # byte 3: TEX page (legacy field name — NOT padding)
                    #   low nibble  -> page
                    #   high nibble -> clut_bank_selector (X6)

    @property
    def page(self) -> int:
        """TEX page index (low nibble of pad)."""
        return self.pad & NIBBLE_MASK

    @property
    def clut_bank_selector(self) -> int:
        """X6 CLUT-bank selector (high nibble of pad, a.k.a. pad_hi).

        NOT a tile coordinate. 0 = default bank; 4 selects the alt CLUT bank
        (see fixes_x6.X6_PADHI_ALT_BANK). Ignored on X4/X5.
        """
        return (self.pad >> NIBBLE_SHIFT) & NIBBLE_MASK

    @property
    def cordX(self) -> int:
        """Tile column within the TEX page (low nibble of clut_base)."""
        return self.clut_base & NIBBLE_MASK

    @property
    def cordY(self) -> int:
        """Tile row within the TEX page (high nibble of clut_base)."""
        return (self.clut_base >> NIBBLE_SHIFT) & NIBBLE_MASK

    def abs_clut_stage(self) -> int:
        """
        Return the absolute CLUT row index for this stage tile entry.
        Formula confirmed against omp-to-expected-tiles.csv: abs_clut = col + 64.

        This is the base row.  The renderer may relocate it for X6: pad_hi=4 alt-bank
        tiles (render_stage.build_x6_padhi_clut_override, 320+col) and page>=8 8bpp tiles
        (which read the raw palette at col+96; see utils/omp._X6_PAGE8_CLUT_OFFSET).
        """
        return self.col + STAGE_CLUT_BASE_ROW

    def palette_group(self) -> OclPaletteGroup:
        """
        Return the OclPaletteGroup for this entry's tile_type.

        All tile_type values not explicitly listed in OclPaletteGroup map to
        STANDARD.  This ensures every tile is rendered rather than silently
        dropped when an unregistered collision type is encountered.
        """
        try:
            return OclPaletteGroup(self.tile_type)
        except ValueError:
            return OclPaletteGroup.UNKNOWN


def load_ocl(ocl_path: Path) -> list[OclEntry]:
    if not ocl_path.exists():
        raise FileNotFoundError(f"OCL file does not exist: {ocl_path}")

    data = ocl_path.read_bytes()

    if len(data) < OCL_HEADER_SIZE:
        raise ValueError(f"OCL file too small: {len(data)} bytes")

    if data[:4] != OCL_MAGIC:
        raise ValueError(f"Not an OCL file: {data[:4]!r}")

    _version = struct.unpack_from("<I", data, 4)[0]
    entry_count = struct.unpack_from("<I", data, 8)[0]

    expected_size = OCL_HEADER_SIZE + entry_count * OCL_ENTRY_SIZE
    if len(data) < expected_size:
        raise ValueError(
            f"OCL entry count {entry_count} exceeds file size "
            f"(expected {expected_size} bytes, got {len(data)})"
        )

    entries: list[OclEntry] = []
    for i in range(entry_count):
        offset = OCL_HEADER_SIZE + i * OCL_ENTRY_SIZE
        flags, col, clut_base, pad = data[offset : offset + OCL_ENTRY_SIZE]
        entries.append(OclEntry(tile_type=flags, col=col, clut_base=clut_base, pad=pad))

    return entries
