from __future__ import annotations

import argparse
from pathlib import Path
from os import makedirs

from PIL import Image

from utils.types import Palette, CLUT, ColourRGBA, TexData, TexFormat
from utils.debug import debug_palette_png, debug_tex_csv, debug_palette_txt

COL_HEADER_SIZE = 12  # COL file: 4-byte magic + 4-byte unknown + 4-byte entry count
COL_BLOCK_SIZE = 2


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
    # Unused | Blue (5 bits) | Green (5 bits) | Red (5 bits)
    # Bit 15: Unused
    # Bits 10-14: Blue channel (0-31)
    # Bits 5-9:  Green channel (0-31)
    # Bits 0-4:  Red channel (0-31)
    # Scale each 5-bit channel to 8-bit by left-shifting 3 (multiply by 8).
    while offset + COL_BLOCK_SIZE <= max_offset:
        block = palette_data[offset : offset + COL_BLOCK_SIZE]
        value = int.from_bytes(block, byteorder="little")

        # Extract 5-bit channels
        r = value & 0x1F
        g = (value >> 5) & 0x1F
        b = (value >> 10) & 0x1F

        # Scale 0-31 -> 0-255
        r8 = (r << 3) | (r >> 2)
        g8 = (g << 3) | (g >> 2)
        b8 = (b << 3) | (b >> 2)

        palette.append((r8, g8, b8))
        offset += COL_BLOCK_SIZE

    if not palette:
        raise ValueError("No palette blocks found in COL file")

    return palette


def convert_palette_to_clut(palette: Palette) -> CLUT:
    """
    Converts a flat palette to a 2D 16-column table/CLUT (colour lookup table)
    """
    return [palette[i : i + 16] for i in range(0, len(palette), 16)]


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


def is_palette_all_black(palette: Palette) -> bool:
    for swatch in palette:
        if sum(swatch) != 0:
            return False
    return True


def render_tex(
    tex_data: TexData,
    palette: Palette,
    output_path: Path,
    clut_index: int,  # 0-based row index in CLUT table
) -> None:
    raw_image = tex_data["raw_image"]
    width = tex_data["width"]
    height = tex_data["height"]
    format_code = tex_data["format_code"]

    clut_start = clut_index * 16
    if clut_start + 16 > len(palette):
        raise ValueError(
            f"Clut index {clut_index} out of range for palette size {len(palette)} (clut start {clut_start})"
        )

    if is_palette_all_black(palette[clut_start : clut_start + 16]):
        print(f"skip: Clut index {clut_index} only has black")
        return

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
            colour_index = raw_image[pixel_index * 4 + 3]  # a_index == r_index >> 4
        elif format_code == TexFormat.FORMAT_8BPP:
            colour_index = raw_image[pixel_index]
        else:
            raise Exception(f"Unsupported TEX format 0x{format_code:02x}")

        final_index = clut_index * 16 + colour_index

        if colour_index == 0:
            # Transparent colour, render as Magenta with Alpha 0 for easy debugging
            pixels.append((255, 0, 255, 0))
        else:
            r, g, b = palette[final_index]
            pixels.append((r, g, b, 255))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract PNG from a TEX file using given palette file."
    )
    parser.add_argument("input", type=Path, help="Path to the input TEX file")
    parser.add_argument("palette", type=Path, help="Path to a COL palette file.")
    parser.add_argument(
        "--clut",
        type=int,
        default=None,
        help="Render using a specific CLUT index within the palette. Otherwise renders against all CLUTs in the palette (default)",
    )

    args = parser.parse_args()
    input_path: Path = args.input
    output_path: Path = input_path.with_suffix(".png")
    palette_path: Path = args.palette
    clut: int | None = args.clut

    palette = load_col_palettes(palette_path)
    tex_data = load_tex(input_path)

    format_code = tex_data["format_code"]
    width = tex_data["width"]
    height = tex_data["height"]

    # generate debug files
    # debug_palette_png(palette, palette_path.with_name(palette_path.stem + "_debug.png"))
    # debug_tex_csv(tex_data, input_path)
    # debug_palette_txt(palette, palette_path.with_name(palette_path.stem + "_debug.txt"))

    # Render specific palette
    if clut is not None:
        render_tex(
            tex_data,
            palette,
            output_path,
            clut_index=clut,
        )
        print(
            f"Wrote {output_path} ({width}x{height}) with palette ({len(palette)} colors, format: {format_code})"
        )
    # Render all palettes in CLUT
    else:
        makedirs(input_path.parent / input_path.stem, exist_ok=True)

        # Render one image per CLUT block in the palette
        num_rows = len(palette) // 16
        row_str_len = len(f"{num_rows}")

        # Create directory based on input_path.stem
        output_folder = output_path.parent / input_path.stem / palette_path.stem
        if not output_folder.exists():
            makedirs(output_folder, exist_ok=True)

        output_folder = (
            output_path.parent / input_path.stem / palette_path.stem / input_path.stem
        )

        for clut_index in range(num_rows):
            clut_output_path = output_folder.with_name(
                f"{input_path.stem}_clut{clut_index:0{row_str_len}d}.png"
            )
            render_tex(
                tex_data,
                palette,
                clut_output_path,
                clut_index=clut_index,
            )
            print(
                f"Wrote {clut_output_path} ({width}x{height}) with palette ({len(palette)} colors, format: {format_code})"
            )


if __name__ == "__main__":
    main()
