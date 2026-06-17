"""
COL palette file loader for Mega Man X4/X5/X6 (PC, MMLC).

== VRAM CLUT layout ==

At runtime the game writes palette data into a flat CLUT table in VRAM.
Each CLUT row is 16 entries wide (16 × 2 bytes = 32 bytes in PSX VRAM, or
16 × 4 bytes as RGBA8 after decoding).  Rows are grouped by function:

    Rows   0–63  : player / sprite / object palettes
    Rows  64–82  : stage animation tile palette   (col 0–18 → col+64 = 64–82)
    Rows  83–?   : further stage tile palettes    (col 19+  → col+64)

The formula `abs_clut = col + 64` used throughout ocl.py therefore addresses
stage tile data starting at CLUT row 64, which is exactly where stage CLUTs
begin after the 64-row player palette block.

== COL file types and their CLUT coverage ==

Three distinct COL file types exist across the games:

  col/pl/plXX/plXX.col   (player palette)
      ~83 CLUTs.  Rows 0–82.  Rows 64–82 hold the *static* stage animation
      colours that the player art happens to share with the stage at load time.

  col/stage/stXX/stXX.col  (X6) / col/stage/stX_0.col  (X5/X4)   (animation palette)
      19 CLUTs (X6 st00 example).  These are exactly the same 19 rows as
      plXX.col rows 64–82 — they are a standalone export of the stage
      animation region.

  stage/col/eng/col00_0x.col  (X6) / col/stage/col00_0x_eng.col  (X5)
      Full VRAM dump — player palette (rows 0–82) + all stage tile CLUTs
      (rows 83+), totalling 256+ rows.  Used as the primary palette source
      by render_stage.py.

== Why X6 needs palette patching but X5/X4 do not ==

X5 and X4 COL files are *stage-only* exports (player rows are absent or
zeroed).  col+64 therefore addresses real stage tile data directly, and no
fixup is required.

X6's col00_0x.col is a full in-memory VRAM snapshot.  During gameplay the
engine writes live player animation cycling frames into rows 64–82, and the
snapshot captures those cycling frames (bright-green sentinel ~(0,231,33),
near-white ~(230,230,230)) at the col+64 positions instead of the correct
static stage colours.  The real stage colours for col 0–18 are stored a
second time at col+96 (rows 96–114).

normalize_x6_stage_palette() (in this module) compensates by relocating each
col+96 CLUT row onto its col+64 row, so the renderer can keep the universal
col+64 lookup.  The relocation is whole-CLUT (not per-entry), with one exception:
  • Null col+96 rows (max brightness < NULL_CLUT_MAX_BRIGHTNESS): carry no
    stage data (e.g. road tiles col=43, the all-zero col=89–95 band), so the
    original col+64 row is kept.
"""
from pathlib import Path

from utils.types import Palette, CLUT
from utils.ocl import STAGE_CLUT_BASE_ROW

COL_HEADER_SIZE = 12  # COL file: 4-byte magic + 4-byte unknown + 4-byte entry count
COL_BLOCK_SIZE = 2

# ── X6 palette normalization ──────────────────────────────────────────────────
# X6's col00_0x.col is a runtime VRAM snapshot: the stage-palette region at the
# col+64 rows is partly clobbered by live player/animation cycling frames (or is
# null), and the real static stage palette is relocated to col+96.  To keep the
# renderer game-agnostic (always addressing col+64), we relocate the col+96 rows
# into the col+64 rows at load time, with one structural exception (null rows).
X6_STAGE_CLUT_OFFSET = 96     # X6 true static stage CLUT base (vs col+64 for X4/X5)
NULL_CLUT_MAX_BRIGHTNESS = 30  # a CLUT whose max channel < this is treated as null


def convert_palette_to_clut(palette: Palette) -> CLUT:
    """
    Converts a flat palette to a 2D 16-column table/CLUT (colour lookup table)
    """
    return [palette[i : i + 16] for i in range(0, len(palette), 16)]


def load_col_palettes(palette_path: Path) -> Palette:
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
    # Read BGR555 palette data from the start of the file.
    # Each 2-byte little-endian value encodes one colour:
    # MSB 15 -> 0 LSB
    # STP    | Blue (5 bits) | Green (5 bits) | Red (5 bits)
    # Bit 15: STP (semi-transparency processing flag)
    #           0 = fully opaque
    #           1 = semi-transparent (blend mode determined by the GPU primitive;
    #               approximated as alpha=128 for software rendering)
    # Bits 10-14: Blue channel (0-31)
    # Bits 5-9:  Green channel (0-31)
    # Bits 0-4:  Red channel (0-31)
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

        # STP is a PSX semi-transparency flag; for PC rendering we always use
        # full opacity.  Transparency is handled at the pixel level (index 0
        # in the palette is treated as transparent in _apply_palette_to_tile).
        alpha = 255

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
    base = clut_row * 16
    return max(max(palette[base + j][:3]) for j in range(16))


def normalize_x6_stage_palette(col: Palette) -> Palette:
    """
    Produce an X6 stage palette whose col+64 rows hold the correct static stage
    colours, so the renderer can use the universal col+64 lookup.

    X6's col00_0x.col stores the real static stage CLUTs at col+96
    (X6_STAGE_CLUT_OFFSET); the col+64 rows are a VRAM snapshot polluted by live
    player/animation cycling frames.  We relocate each col+96 row onto its col+64
    row, except:
      • null fallback — a col+96 row that is effectively empty
        (max brightness < NULL_CLUT_MAX_BRIGHTNESS) carries no stage data; keep
        col+64.  This covers road tiles (col=43) and the all-zero col=89-95 band.

    Note: an earlier "enemy bank" exception also kept the col+64 rows for col+96
    sources in rows 192-207.  It was dropped because in per-stage COL files (e.g.
    col07_0x.col) those rows are legitimate stage CLUTs — the absolute-row guard
    wrongly suppressed relocation and left polluted snapshot colours (see col=104 /
    CLUT #198 region in st07).

    KNOWN GAP: the fixed +32-row relocation is wrong for stage CLUTs whose col has
    bit 6 set (col 64/80/96 → dst rows 128/144/160 ← src rows 160/176/192).  In the
    shared col0g_0x.col VRAM dump those src rows are the "enemy bank", not stage data,
    so X6 page-10/11 tiles using those cols render with the wrong CLUT (e.g. st0g's
    blue band).  Left unresolved by choice — see docs/unconfirmed/issues.md
    ("X6 page-10/11 tiles with col bit 6 set render with wrong CLUT").

    The input is not mutated; a new list is returned.
    """
    out: Palette = list(col)
    n_cluts = len(col) // 16
    for c in range(n_cluts - X6_STAGE_CLUT_OFFSET):
        dst = c + STAGE_CLUT_BASE_ROW
        src = c + X6_STAGE_CLUT_OFFSET
        if _clut_max_brightness(col, src) < NULL_CLUT_MAX_BRIGHTNESS:
            continue  # null col+96 row — keep col+64
        for j in range(16):
            out[dst * 16 + j] = col[src * 16 + j]
    return out
