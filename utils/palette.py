"""
COL palette file loader for Mega Man X4/X5/X6 (PC, MMLC).

== VRAM CLUT layout ==

Palette data is a flat CLUT table. Each CLUT row is CLUT_COLORS_PER_ROW (16)
entries wide (16 x 2 bytes in PSX VRAM, or 16 x 4 bytes RGBA8 decoded). Rows:

    Rows   0-63  : player / sprite / object palettes
    Rows  64-82  : stage animation tile palette   (col 0-18 -> col+64 = 64-82)
    Rows  83-?   : further stage tile palettes    (col 19+  -> col+64)

The formula `abs_clut = col + 64` (ocl.py) addresses stage tile data starting
at CLUT row 64, after the 64-row player palette block.

== COL file types ==

  col/pl/plXX/plXX.col   (player palette): ~83 CLUTs, rows 0-82; rows 64-82 =
      static stage animation colours shared with the stage.
  col/stage/stXX/stXX.col (X6) / col/stage/stX.col (X5/X4): 19 CLUTs, same as
      plXX.col rows 64-82 (standalone export of the stage animation region).
  stage/col/colXX.col (X6) / col/stage/colX.col (X5): full VRAM
      dump, rows 0-82 + all stage tile CLUTs (rows 83+), 256+ rows. Primary
      palette source for render_stage.py.

X5/X4 COL files are stage-only exports; col+64 addresses real stage tile data
directly. X6's colX.col is a full VRAM snapshot: rows 64-82 are polluted by
live cycling frames and the real static stage colours live at col+96 (rows
96-114). normalize_x6_stage_palette() relocates col+96 -> col+64 (whole-CLUT),
except null col+96 rows (max brightness < NULL_CLUT_MAX_BRIGHTNESS) which carry
no stage data (road tiles col=43, all-zero col=89-95 band) -> keep col+64.
"""
from pathlib import Path

from utils.types import Palette, CLUT
from utils.ocl import STAGE_CLUT_BASE_ROW
from utils.consts import CLUT_COLORS_PER_ROW

COL_HEADER_SIZE = 12  # COL file: 4-byte magic + 4-byte unknown + 4-byte entry count
COL_BLOCK_SIZE = 2

# X6 palette normalization: relocate col+96 static stage CLUTs onto col+64 at
# load time so the renderer keeps the universal col+64 lookup (null rows excepted).
X6_STAGE_CLUT_OFFSET = 96     # X6 true static stage CLUT base (vs col+64 for X4/X5)
NULL_CLUT_MAX_BRIGHTNESS = 30  # a CLUT whose max channel < this is treated as null


def convert_palette_to_clut(palette: Palette) -> CLUT:
    """
    Converts a flat palette to a 2D CLUT_COLORS_PER_ROW-column table/CLUT (colour lookup table)
    """
    return [palette[i : i + CLUT_COLORS_PER_ROW] for i in range(0, len(palette), CLUT_COLORS_PER_ROW)]


def load_col_palettes(palette_path: Path, stp_as_alpha: bool = False) -> Palette:
    """Load a COL file into a flat Palette of (r,g,b,a) tuples.

    stp_as_alpha: by default the PSX STP (semi-transparency) bit is dropped and every
    colour is opaque (alpha=255) -- STP only blends under a semi-transparent draw
    primitive, which we don't track per tile, and ~90% of stage entries set it, so
    honouring it globally would wrongly make almost everything translucent.  When True,
    a non-black STP-flagged entry gets alpha=128 (PSX 50% blend).  Use this ONLY for the
    animated-COL rows substituted into known semi-transparent effects (e.g. waterfalls);
    see render_stage.CLUT_ANIM_STILL_FRAMES."""
    if not palette_path.exists():
        raise FileNotFoundError(f"Palette file does not exist: {palette_path}")

    palette_data = palette_path.read_bytes()

    if len(palette_data) < COL_HEADER_SIZE + 1:
        raise ValueError(f"Palette file too small: {len(palette_data)} bytes")

    # magic header
    if palette_data[:4] != b"COL\x00":
        raise ValueError(f"Not a COL file: {palette_data[:4]!r}")

    entry_count = int.from_bytes(palette_data[8:12], byteorder="little")
    max_offset = COL_HEADER_SIZE + entry_count * COL_BLOCK_SIZE

    if max_offset > len(palette_data):
        raise ValueError(
            f"COL entry count {entry_count} exceeds file size "
            f"(expected {max_offset} bytes, got {len(palette_data)})"
        )

    palette: Palette = []
    offset = COL_HEADER_SIZE
    # BGR555 palette data. Each 2-byte little-endian value encodes one colour:
    # MSB 15 -> 0 LSB:  STP | Blue (5 bits) | Green (5 bits) | Red (5 bits)
    # Bit 15:     STP (semi-transparency flag; 0=opaque, 1=semi-transparent,
    #             approximated as alpha=128 for software rendering)
    # Bits 10-14: Blue channel (0-31)
    # Bits 5-9:   Green channel (0-31)
    # Bits 0-4:   Red channel (0-31)
    # Scale each 5-bit channel to 8-bit by left-shifting 3 (multiply by 8).
    while offset + COL_BLOCK_SIZE <= max_offset:
        block = palette_data[offset : offset + COL_BLOCK_SIZE]
        value = int.from_bytes(block, byteorder="little")

        # Extract STP flag and 5-bit colour channels
        stp = (value >> 15) & 0x1
        r = value & 0x1F
        g = (value >> 5) & 0x1F
        b = (value >> 10) & 0x1F

        # Scale 0-31 -> 0-255
        r8 = (r << 3) | (r >> 2)
        g8 = (g << 3) | (g >> 2)
        b8 = (b << 3) | (b >> 2)

        # STP normally ignored (full opacity; see stp_as_alpha docstring). Per-pixel
        # transparency is decided in _apply_palette_to_tile: a CLUT entry is transparent
        # only when its colour is the all-zero sentinel (RGB 0,0,0), NOT merely when the
        # tile index is 0 (some CLUTs store an opaque real colour at index 0).
        # With stp_as_alpha, a non-black STP entry becomes 50% translucent (alpha=128).
        alpha = 128 if (stp_as_alpha and stp and (r8 or g8 or b8)) else 255

        palette.append((r8, g8, b8, alpha))
        offset += COL_BLOCK_SIZE

    if not palette:
        raise ValueError("No palette blocks found in COL file")

    return palette


def is_palette_all_black(palette: Palette) -> bool:
    for swatch in palette:
        r, g, b, _a = swatch
        if r != 0 or g != 0 or b != 0:
            return False
    return True


def _clut_max_brightness(palette: Palette, clut_row: int) -> int:
    """Return the maximum RGB channel value across one 16-entry CLUT row."""
    base = clut_row * CLUT_COLORS_PER_ROW
    return max(max(palette[base + j][:3]) for j in range(CLUT_COLORS_PER_ROW))


def x6_palette_is_vram_snapshot(col: Palette) -> bool:
    """
    True if an X6 COL file is a runtime VRAM snapshot (colX-style full dump used by
    gameplay stages) rather than a static menu palette (e.g. stage-select col0d_00.col).

    Detected by live player-animation cycling markers -- the bright-green sentinel
    ~(0,231,33) -- present across the player/animation CLUT region (rows 64-82) of a
    snapshot but not a static palette.

    Gates the page>=8 raw-col+96 stage-CLUT rule (utils/omp), which exists ONLY to undo
    the col+64 snapshot pollution -- so it must not touch non-snapshot (menu) palettes,
    whose col+64 rows already hold the correct static colours.
    """
    GREEN_SENTINELS_MIN = 4
    n = 0
    for row in range(STAGE_CLUT_BASE_ROW, STAGE_CLUT_BASE_ROW + 19):  # rows 64-82
        base = row * CLUT_COLORS_PER_ROW
        if base + CLUT_COLORS_PER_ROW > len(col):
            break
        for r, g, b, _a in col[base:base + CLUT_COLORS_PER_ROW]:
            if r < 40 and g > 180 and b < 90:   # bright-green sentinel ~(0,231,33)
                n += 1
                if n >= GREEN_SENTINELS_MIN:
                    return True
    return False


def normalize_x6_stage_palette(col: Palette) -> Palette:
    """
    Produce an X6 stage palette whose col+64 rows hold the correct static stage
    colours, so the renderer can use the universal col+64 lookup.

    X6's colX.col stores the real static stage CLUTs at col+96
    (X6_STAGE_CLUT_OFFSET); the col+64 rows are a VRAM snapshot polluted by live
    cycling frames. Relocate each col+96 row onto its col+64 row, except:
      - null fallback: a col+96 row that is effectively empty (max brightness <
        NULL_CLUT_MAX_BRIGHTNESS) carries no stage data; keep col+64. Covers road
        tiles (col=43) and the all-zero col=89-95 band.

    This normalized col+64 lookup is for page<8 (4bpp) tiles only. page>=8 (8bpp) tiles
    read their stage CLUT from the RAW palette at col+96 directly (see render_level's
    ``x6_page8_palette`` and utils/omp._X6_PAGE8_CLUT_OFFSET) and bypass this relocation.

    The input is not mutated; a new list is returned.
    """
    out: Palette = list(col)
    n_cluts = len(col) // CLUT_COLORS_PER_ROW
    for c in range(n_cluts - X6_STAGE_CLUT_OFFSET):
        dst = c + STAGE_CLUT_BASE_ROW
        src = c + X6_STAGE_CLUT_OFFSET
        if _clut_max_brightness(col, src) < NULL_CLUT_MAX_BRIGHTNESS:
            continue  # null col+96 row -- keep col+64
        for j in range(CLUT_COLORS_PER_ROW):
            out[dst * CLUT_COLORS_PER_ROW + j] = col[src * CLUT_COLORS_PER_ROW + j]
    return out
