from __future__ import annotations

import argparse
from pathlib import Path
from os import makedirs

from PIL import Image, ImageDraw

PAL_HEADER_SIZE = 12  # COL file: 4-byte magic + 4-byte unknown + 4-byte entry count
PAL_BLOCK_SIZE = 2


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


def load_col_palette(palette_path: Path) -> list[tuple[int, int, int]]:
    if not palette_path.exists():
        raise FileNotFoundError(f"Palette file does not exist: {palette_path}")

    palette_data = palette_path.read_bytes()

    if len(palette_data) < PAL_HEADER_SIZE + 1:
        raise ValueError(f"Palette file too small: {len(palette_data)} bytes")

    if palette_data[:4] != b"COL\x00":
        raise ValueError(f"Not a COL file: {palette_data[:4]!r}")

    entry_count = int.from_bytes(palette_data[8:12], byteorder="little")
    max_offset = PAL_HEADER_SIZE + entry_count * PAL_BLOCK_SIZE
    if max_offset > len(palette_data):
        raise ValueError(
            f"COL entry count {entry_count} exceeds file size "
            f"(expected {max_offset} bytes, got {len(palette_data)})"
        )

    blocks: list[tuple[int, int, int]] = []
    offset = PAL_HEADER_SIZE
    # Read BGR555 palette data from the start of the file.
    # Each 2-byte little-endian value encodes one colour:
    # MSB 15 -> 0 LSB
    # Unused | Blue (5 bits) | Green (5 bits) | Red (5 bits)
    # Bit 15: Unused
    # Bits 10-14: Blue channel (0-31)
    # Bits 5-9:  Green channel (0-31)
    # Bits 0-4:  Red channel (0-31)
    # Scale each 5-bit channel to 8-bit by left-shifting 3 (multiply by 8).
    while offset + PAL_BLOCK_SIZE <= max_offset:
        block = palette_data[offset : offset + PAL_BLOCK_SIZE]
        value = int.from_bytes(block, byteorder="little")

        # Currently "close enough", potential slight miscalculations on the colours
        # Extract 5-bit channels
        r = value & 0x1F
        g = (value >> 5) & 0x1F
        b = (value >> 10) & 0x1F

        # Scale 0-31 -> 0-255
        r8 = (r << 3) | (r >> 2)
        g8 = (g << 3) | (g >> 2)
        b8 = (b << 3) | (b >> 2)

        blocks.append((r8, g8, b8))
        offset += PAL_BLOCK_SIZE

    if not blocks:
        raise ValueError("No palette blocks found in COL file")

    return blocks


def convert_to_2d_palette(
    palette: list[tuple[int, int, int]],
) -> list[list[tuple[int, int, int]]]:
    return [palette[i : i + 16] for i in range(0, len(palette), 16)]


def extract_tex(input_path: Path) -> tuple[int, int, int, bytes]:
    data = input_path.read_bytes()
    format_code, width, height, _mip_count = parse_tex_header(data)

    print(
        "header",
        {
            "format_code": format_code,
            "width": width,
            "height": height,
            "_mip_count": _mip_count,
        },
    )

    if format_code not in [0x07, 0x12]:
        raise NotImplementedError(
            f"Unsupported TEX format 0x{format_code:02x}. "
            "This extractor currently supports palette-mapped TEX files only."
        )

    # 32bpp
    if format_code == 0x07:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height * 4
        payload = data[base_offset : base_offset + expected_size]

    # 8bpp palette-indexed
    elif format_code == 0x12:
        offset_table = [
            int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little")
            for i in range(7)
        ]
        base_offset = offset_table[0]

        expected_size = width * height
        payload = data[base_offset : base_offset + expected_size]

    if len(payload) != expected_size:
        raise ValueError(
            f"Payload size mismatch for {input_path.name}: "
            f"expected {expected_size} bytes, got {len(payload)}"
        )

    return format_code, width, height, payload


def is_all_transparent_clut(colours: list[tuple[int, int, int]]) -> bool:
    for swatch in colours:
        if sum(swatch) != 0:
            return False
    return True


def render_tex(
    payload: bytes,
    width: int,
    height: int,
    palette: list[tuple[int, int, int]],
    output_path: Path,
    format_code: int = 0x07,
    clut_base: int = 0,  # row index in palette file (0-based)
) -> None:
    clut_start = clut_base * 16
    if clut_start + 16 > len(palette):
        raise ValueError(
            f"Clut index {clut_base} out of range for palette size {len(palette)} (clut start {clut_start})"
        )

    if is_all_transparent_clut(palette[clut_start : clut_start + 16]):
        print(f"skip: Clut index {clut_base} only has black")
        return

    # Each pixel stores a 4-bit colour index (0-15).
    # For 0x07 (32bpp): index is in the alpha channel (byte 3 of each 4-byte pixel).
    # For 0x12 (8bpp palette-indexed): each byte is the index directly.
    # The colour index selects a colour from one 16-entry CLUT block within the palette:
    # final_index = clut_base*16 + colour_index.
    # Index 0 in any CLUT is transparent. clut_base must be supplied externally
    # (it is not encoded in the pixel data).
    pixels = []
    for pixel_index in range(width * height):
        if format_code == 0x07:
            colour_index = payload[pixel_index * 4 + 3]  # a_index == r_index >> 4
        else:  # 0x12
            colour_index = payload[pixel_index]
        final_index = clut_base * 16 + colour_index

        if colour_index == 0:
            pixels.append((255, 0, 255, 0))
        else:
            r, g, b = palette[final_index]
            pixels.append((r, g, b, 255))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    image.save(output_path)


def render_palette(_palette: list[tuple[int, int, int]], output_path: Path) -> None:
    # Determine end of meaningful data and trim palette if necessary
    last_nonzero_index = max(
        i for i, (r, g, b) in enumerate(_palette) if (r, g, b) != (0, 0, 0)
    )
    palette = _palette[: last_nonzero_index + 1]

    num_colors = len(palette)
    cols = 16
    rows = (num_colors + cols - 1) // cols
    cell_size = 16
    label_width = 40
    image_width = cols * cell_size + label_width
    image_height = rows * cell_size

    image = Image.new("RGB", (image_width, image_height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, (r, g, b) in enumerate(palette):
        x = (i % cols) * cell_size
        y = (i // cols) * cell_size
        for dx in range(cell_size):
            for dy in range(cell_size):
                image.putpixel((x + dx, y + dy), (r, g, b))

    for row in range(rows):
        y = row * cell_size
        label = str(row)
        draw.text((cols * cell_size + 2, y + 2), label, fill=(255, 255, 255))

    image.save(output_path)


def tex_to_csv(payload: bytes, input_path: Path, width: int, height: int) -> None:
    import csv

    output_path_grey = input_path.with_name(input_path.stem + "_grey.csv")
    output_path_alpha = input_path.with_name(input_path.stem + "_alpha.csv")

    with output_path_grey.open("w", newline="") as csvfile_grey:
        with output_path_alpha.open("w", newline="") as csvfile_alpha:
            writer_grey = csv.writer(csvfile_grey)
            # writer_grey.writerow(range(width))

            writer_alpha = csv.writer(csvfile_alpha)
            # writer_alpha.writerow(range(width))

            for y in range(height):
                row_grey = []
                row_alpha = []

                for x in range(width):
                    pixel_index = y * width + x
                    # b_index = payload[pixel_index * 4 + 0]
                    # g_index = payload[pixel_index * 4 + 1]
                    r_index = payload[pixel_index * 4 + 2]
                    a_index = payload[pixel_index * 4 + 3]

                    row_grey.append(r_index)
                    row_alpha.append(a_index)

                writer_grey.writerow(row_grey)
                writer_alpha.writerow(row_alpha)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a TEX file as a PNG using one or more COL palettes."
    )
    parser.add_argument("input", type=Path, help="Path to the input TEX file")
    parser.add_argument(
        "palette",
        type=Path,
        help="Path to a COL palette file.",
    )
    parser.add_argument(
        "--clut",
        type=int,
        default=None,
        help="Render tex against a specific CLUT row index (0-based) within the palette file. Otherwise renders against all CLUTs in the palette",
    )

    args = parser.parse_args()
    input_path: Path = args.input
    output_path: Path = input_path.with_suffix(".png")
    palette_path: Path = args.palette

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if not palette_path.exists():
        raise FileNotFoundError(f"Palette file does not exist: {palette_path}")

    palette = load_col_palette(palette_path)
    format_code, width, height, payload = extract_tex(input_path)

    # generate debug files
    # render_palette(palette, palette_path.with_name(palette_path.stem + "_palette.png"))
    # tex_to_csv(payload, input_path, width, height)
    # dump palette to txt
    # with open(
    #     palette_path.with_name(palette_path.stem + "_palette.txt"), "w"
    # ) as palette_txt:
    #     for index, data in enumerate(palette):
    #         palette_txt.write(f"{index}: {data[0], data[1], data[2]}\n")

    if args.clut is not None:
        render_tex(
            payload,
            width,
            height,
            palette,
            output_path,
            format_code=format_code,
            clut_base=args.clut,
        )
        print(
            f"Wrote {output_path} ({width}x{height}) with palette ({len(palette)} colors, format: {format_code})"
        )
    else:
        makedirs(input_path.parent / input_path.stem, exist_ok=True)

        # Render one image per CLUT block in the palette
        num_cluts = len(palette) // 16
        clut_str_len = len(f"{num_cluts}")

        # Create directory based on input_path.stem
        output_folder = output_path.parent / input_path.stem / palette_path.stem
        if not output_folder.exists():
            makedirs(output_folder, exist_ok=True)

        output_folder = (
            output_path.parent / input_path.stem / palette_path.stem / input_path.stem
        )

        for clut_base in range(num_cluts):
            clut_output_path = output_folder.with_name(
                f"{input_path.stem}_clut{clut_base:0{clut_str_len}d}.png"
            )
            render_tex(
                payload,
                width,
                height,
                palette,
                clut_output_path,
                format_code=format_code,
                clut_base=clut_base,
            )
            print(
                f"Wrote {clut_output_path} ({width}x{height}) with palette ({len(palette)} colors, format: {format_code})"
            )


if __name__ == "__main__":
    main()
