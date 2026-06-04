from pathlib import Path

from utils.types import Palette, CLUT

COL_HEADER_SIZE = 12  # COL file: 4-byte magic + 4-byte unknown + 4-byte entry count
COL_BLOCK_SIZE = 2


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

        # Alpha encodes STP: 128 = semi-transparent, 255 = fully opaque.
        # Note: STP=1 with R=G=B=0 (raw value 0x8000) is a special PSX case
        # meaning transparent black; the pixel-level transparency check
        # (colour_index == 0) in tex.py handles that separately.
        alpha = 128 if stp else 255

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
