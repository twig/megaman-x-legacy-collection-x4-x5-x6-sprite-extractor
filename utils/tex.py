from pathlib import Path
from PIL import Image
from PIL.Image import Image as PILImage

from utils.types import TexData, TexFormat, ColourRGBA, Palette
from utils.palette import is_palette_all_black


def parse_tex_header(data: bytes) -> tuple[int, int, int, int]:
    if len(data) < 0x30:
        raise ValueError(f"TEX file too small: {len(data)} bytes")

    # Check magic header
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

    # print(
    #     "header",
    #     {
    #         "format_code": format_code,
    #         "width": width,
    #         "height": height,
    #         "_mip_count": mip_count,
    #     },
    # )

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
        # Python types can't seem to determine whats been filtered out
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

    clut_start = clut_index * 16
    if clut_start + 16 > len(palette):
        raise ValueError(
            f"Clut index {clut_index} out of range for palette size {len(palette)} (clut start {clut_start})"
        )

    if is_palette_all_black(palette[clut_start : clut_start + 16]):
        print(f"skip: Clut index {clut_index} only has black")
        return None

    # Each pixel in TEX data stores a 4-bit colour index (0-15).
    # For 0x07 (32bpp): index is in the alpha channel (byte 3 of each 4-byte pixel).
    # For 0x12 (8bpp palette-indexed): each byte is the index directly? TBC
    # The colour index selects a colour from one 16-entry CLUT block within the palette:
    # final_index = clut_index*16 + colour_index.
    # Index 0 in any CLUT is transparent. clut_index must be supplied externally
    # (it is not encoded in the pixel data).
    pixels: list[ColourRGBA] = []
    for pixel_index in range(width * height):
        if format_code == TexFormat.FORMAT_32BPP:
            # [0-3] RGBA or BGRA, either way A channel is 3
            colour_index = raw_image[pixel_index * 4 + 3]
            final_index = clut_index * 16 + colour_index
        elif format_code == TexFormat.FORMAT_8BPP:
            # TODO: make this work
            colour_index = raw_image[pixel_index]
            final_index = clut_index * 16 + colour_index
        else:
            raise Exception(f"Unsupported TEX format 0x{format_code:02x}")

        # if pixel_index == 272:
        #     print(
        #         "272: format_code",
        #         format_code,
        #         "colour_index",
        #         colour_index,
        #         "final_index",
        #         final_index,
        #         "pixel",
        #         palette[final_index],
        #     )

        if colour_index == 0:
            # Transparent colour, render as Magenta with Alpha 0 for easy debugging
            pixels.append((255, 0, 255, 0))
        else:
            r, g, b = palette[final_index]
            pixels.append((r, g, b, 255))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return image
