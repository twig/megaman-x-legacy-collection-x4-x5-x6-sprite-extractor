# OCL file format -- Object Colour Lookup table
#
# The OCL file is a per-stage flat array of 4-byte entries. Each entry encodes
# both the CLUT (palette row) assignment and the TEX tile coordinates for one
# tile slot in the stage. It is indexed directly by the u16 values stored in the
# OMP file.
#
# OCL binary format:
#   Offset   Size    Content
#   0x0000   4 B     Magic: "OCL\x00"
#   0x0004   4 B     Version (LE u32 = 1)
#   0x0008   4 B     Entry count (LE u32)
#   0x000C   Nx4 B   Entries (one per tile slot):
#
#   Per-entry byte layout:
#     byte 0 - tile_type:  collision / behaviour type (X4 editor: "col" / collisionType)
#                           Bits [5:0] = collision type (0-63); bits [7:6] always 0.
#                           Three values carry palette-variant meaning in X5:
#                             0x38 = alt/hit-flash palette variant (same col file)
#                             0x39 = animated cycling palette (st0_0.col)
#                             0x3B = alt-area tileset palette (col00_0z.col)
#                             all others = standard tileset palette
#     byte 1 - col:     palette column; abs_clut = col + 64
#     byte 2 - tile_coords: TEX tile position encoding
#                      cordX = byte2 & 0x0F   (low  nibble, tile column within page)
#                      cordY = (byte2 >> 4) & 0x0F  (high nibble, tile row within page)
#     byte 3 - page_and_clutbank:  low nibble = TEX page; high nibble = X6 CLUT-bank
#                       selector (pad_hi).
#                         page  = byte3 & 0x0F
#                       Pages 0..CHR256_PAGE_START-1 (0-7) are 4bpp (the tex sheet);
#                       pages CHR256_PAGE_START.. (8+) are 8bpp and route to chr256
#                       (tex_bg).
#                       page=16 (0x10->masked to 0) = player/sprite tiles
#                       page=255 = sentinel/unused entry (OCL_EMPTY_TILE; OclEntry.is_empty)
#
# TEX tile coordinate formula:
#   gx = (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * 16   # pixel X of tile top-left in TEX
#   gy = (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * 16  # pixel Y of tile top-left in TEX
#
#   tex_x (tile column in TEX) = e.tex_page * 16 + e.cordX
#   tex_y (tile row    in TEX) = e.cordY
#
#   clut_bank_selector is the X6 pad_hi CLUT-bank selector, NOT a tile coordinate.
#
# CLUT formula:
#   abs_clut = e.col + 64

import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from utils.consts import NIBBLE_MASK, NIBBLE_SHIFT, OCL_EMPTY_TILE

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

    Byte 0 of each OCL entry is the tile collision/behaviour type (X4 editor "col",
    extracted as collisionType = val & 0x3F in Draw16xTile).  Only three tile_type
    values select a different palette source in X5; all others use STANDARD.

    Use OclEntry.palette_group() to map an arbitrary tile_type to one of these.
    """
    STANDARD          = 0x00  # standard tileset (col*.col)
    ALT_PALETTE       = 0x38  # alt/hit-flash variant -- same COL file, kept distinct
    ANIMATED_CRYSTAL  = 0x39  # animated cycling palette (st*.col in X5)
    ALT_AREA          = 0x3B  # alt-area tileset (col*.col in X5)
    UNKNOWN           = 0xFF  # sentinel for unregistered collision types (never a real tile_type)


@dataclass
class OclEntry:
    tile_type: int  # byte 0: collision / behaviour type (X4 editor: "col", Draw16xTile: collisionType)
                    #   bits [5:0] = collision type; bits [7:6] always 0.
                    #   Three values carry X5 palette-variant meaning -- see OclPaletteGroup.
    col: int        # byte 1: palette column; abs_clut = col + 64
    tile_coords: int  # byte 2: TEX tile coords
                    #   low nibble  -> cordX
                    #   high nibble -> cordY
    page_and_clutbank: int  # byte 3: TEX page (low nibble) + X6 CLUT-bank selector (high nibble)
                    #   low nibble  -> page (see tex_page)
                    #   high nibble -> clut_bank_selector (X6 pad_hi)

    @property
    def is_empty(self) -> bool:
        """True if this is an empty/unused tile slot -- page_and_clutbank equals
        OCL_EMPTY_TILE (0xFF), the sky-fill sentinel meaning "no TEX data" (never real art).
        """
        return self.page_and_clutbank == OCL_EMPTY_TILE

    @property
    def tex_page(self) -> int:
        """TEX page index (low nibble of page_and_clutbank)."""
        return self.page_and_clutbank & NIBBLE_MASK

    @property
    def clut_bank_selector(self) -> int:
        """X6 CLUT-bank selector (high nibble of page_and_clutbank, a.k.a. pad_hi).

        NOT a tile coordinate. 0 = default bank; 4 selects the alt CLUT bank
        (see fixes_x6.X6_PADHI_ALT_BANK). Ignored on X4/X5.
        """
        return (self.page_and_clutbank >> NIBBLE_SHIFT) & NIBBLE_MASK

    @property
    def cordX(self) -> int:
        """Tile column within the TEX page (low nibble of tile_coords)."""
        return self.tile_coords & NIBBLE_MASK

    @property
    def cordY(self) -> int:
        """Tile row within the TEX page (high nibble of tile_coords)."""
        return (self.tile_coords >> NIBBLE_SHIFT) & NIBBLE_MASK

    def abs_clut_stage(self) -> int:
        """
        Return the absolute CLUT row index for this stage tile entry: col + 64.

        This is the base row.  The renderer may relocate it for X6: pad_hi=4 alt-bank
        tiles (render_stage.build_x6_padhi_clut_override, 320+col) and page>=8 8bpp tiles
        (which read the raw palette at col+96; see utils/omp._X6_PAGE8_CLUT_OFFSET).
        """
        return self.col + STAGE_CLUT_BASE_ROW

    def palette_group(self) -> OclPaletteGroup:
        """
        Return the OclPaletteGroup for this entry's tile_type; unlisted values map
        to STANDARD so every tile renders rather than being silently dropped.
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
        flags, col, tile_coords, pad = data[offset : offset + OCL_ENTRY_SIZE]
        entries.append(OclEntry(tile_type=flags, col=col, tile_coords=tile_coords, page_and_clutbank=pad))

    return entries
