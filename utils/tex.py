from pathlib import Path
from PIL import Image
from PIL.Image import Image as PILImage

from utils.types import TexData, TexFormat, ColourRGBA, Palette
from utils.palette import is_palette_all_black
from utils.consts import CLUT_COLORS_PER_ROW

# TEX binary format (MT Framework texture)
#   Offset   Size    Content
#   0x0000   4 B     Magic: "TEX\x00"
#   0x0008   4 B     Packed dims (LE u32):
#                      bits 0-5    mip_count   (& 0x3F)
#                      bits 6-18   width       ((& 0x0007FFC0) >> 6)
#                      bits 19-31  height      ((& 0xFFF80000) >> 19)
#   0x000D   1 B     format_code: 0x07 = FORMAT_32BPP, 0x12 = FORMAT_8BPP
#   0x0010   7x4 B   Offset table: 7 LE u32 mip offsets; offset_table[0] = base pixel data
#
# Pixel payload at base_offset:
#   FORMAT_8BPP  (0x12): width*height bytes; each byte is a CLUT palette index.
#   FORMAT_32BPP (0x07): width*height*4 bytes; CLUT index is byte 3 (alpha), bytes 0-2 unused.
# CLUT lookup:
#   final_index = clut_index * CLUT_COLORS_PER_ROW + colour_index (see utils/palette).

def parse_tex_header(data: bytes) -> tuple[int, int, int, int]:
    if len(data) < 0x30:
        raise ValueError(f"TEX file too small: {len(data)} bytes")

    if data[:4] != b"TEX\x00":
        raise ValueError(f"Not a TEX file: {data[:4]!r}")

    packed = int.from_bytes(data[0x08:0x0C], "little")
    format_code = data[0x0D]
    mip_count = packed & 0x3F
    width = (packed & 0x0007FFC0) >> 6
    height = (packed & 0xFFF80000) >> 19

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid dimensions: {width}x{height}")

    return format_code, width, height, mip_count


def load_tex(input_path: Path) -> TexData:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    data = input_path.read_bytes()
    format_code, width, height, mip_count = parse_tex_header(data)

    if format_code == TexFormat.FORMAT_32BPP:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height * 4
        raw_image = data[base_offset : base_offset + expected_size]

    elif format_code == TexFormat.FORMAT_8BPP:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height
        raw_image = data[base_offset : base_offset + expected_size]

    else:
        raise NotImplementedError(
            f"Unsupported TEX format 0x{format_code:02x}. "
            "This extractor currently supports palette-mapped TEX files only."
        )

    if len(raw_image) != expected_size:
        raise ValueError(
            f"Payload size mismatch for {input_path.name}: "
            f"expected {expected_size} bytes, got {len(raw_image)}"
        )

    return {
        "format_code": format_code,  # type: ignore
        "width": width,
        "height": height,
        "mip_count": mip_count,
        "raw_image": raw_image,
    }


def convert_tex_to_image(
    tex_data: TexData,
    palette: Palette,
    clut_index: int,  # 0-based row index in CLUT table
) -> PILImage | None:
    raw_image = tex_data["raw_image"]
    width = tex_data["width"]
    height = tex_data["height"]
    format_code = tex_data["format_code"]

    print("convert_tex_to_image", format_code, width, height, clut_index)

    clut_start = clut_index * CLUT_COLORS_PER_ROW
    if clut_start + CLUT_COLORS_PER_ROW > len(palette):
        raise ValueError(
            f"Clut index {clut_index} out of range for palette size {len(palette)} (clut start {clut_start})"
        )

    if is_palette_all_black(palette[clut_start : clut_start + CLUT_COLORS_PER_ROW]):
        print(f"skip: Clut index {clut_index} only has black")
        return None

    # Pixel = palette index into the active CLUT block; clut_index supplied externally:
    #   final_index = clut_index * CLUT_COLORS_PER_ROW + colour_index
    # Transparency is value-based (matches utils/omp._apply_palette_to_tile): transparent
    # only when the selected CLUT colour is the all-zero sentinel (RGB 0,0,0), NOT whenever
    # the index is 0 -- some CLUTs hold an opaque real colour at index 0.
    # Format layout:
    #   FORMAT_32BPP (0x07): 4 bytes/pixel; palette index in alpha channel (byte 3), bytes 0-2 unused.
    #   FORMAT_8BPP  (0x12): 1 byte/pixel; the byte is the palette index directly.
    pixels: list[ColourRGBA] = []
    for pixel_index in range(width * height):
        if format_code == TexFormat.FORMAT_32BPP:
            colour_index = raw_image[pixel_index * 4 + 3]  # index in alpha byte
            final_index = clut_index * CLUT_COLORS_PER_ROW + colour_index
        elif format_code == TexFormat.FORMAT_8BPP:
            colour_index = raw_image[pixel_index]  # index is the full byte
            final_index = clut_index * CLUT_COLORS_PER_ROW + colour_index
        else:
            raise Exception(f"Unsupported TEX format 0x{format_code:02x}")

        if final_index >= len(palette):
            pixels.append((255, 0, 255, 0))  # out of palette range -- transparent
            continue
        r, g, b, _stp = palette[final_index]
        # The STP bit (stored as alpha) is a polygon-level blend flag, not per-pixel
        # alpha, so every non-sentinel pixel is fully opaque regardless of STP.
        if r == 0 and g == 0 and b == 0:
            pixels.append((255, 0, 255, 0))  # transparent (debug magenta marker)
        else:
            pixels.append((r, g, b, 255))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return image
