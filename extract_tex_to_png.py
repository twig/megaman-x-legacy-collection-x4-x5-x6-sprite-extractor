from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

PAL_HEADER_SIZE = 0
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


def load_palette_blocks(palette_path: Path) -> list[tuple[int, int, int]]:
    if not palette_path.exists():
        raise FileNotFoundError(f"Palette file does not exist: {palette_path}")

    palette_data = palette_path.read_bytes()

    if len(palette_data) < PAL_HEADER_SIZE + 1:
        raise ValueError(f"Palette file too small: {len(palette_data)} bytes")

    if palette_data[:4] != b"COL\x00":
        raise ValueError(f"Not a COL file: {palette_data[:4]!r}")

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
    while offset + PAL_BLOCK_SIZE <= len(palette_data):
        block = palette_data[offset : offset + PAL_BLOCK_SIZE]
        value = int.from_bytes(block, byteorder="little")

        # Currently "close enough", potential slight miscalculations on the colours
        # Extract 5-bit channels
        r = value & 0x1F
        g = (value >> 5) & 0x1F
        b = (value >> 10) & 0x1F

        # Scale 0-31 -> 0-248
        r8 = r << 3
        g8 = g << 3
        b8 = b << 3

        blocks.append((r8, g8, b8))
        offset += PAL_BLOCK_SIZE

    if not blocks:
        raise ValueError("No palette blocks found in COL file")

    return blocks


def extract_tex(input_path: Path) -> tuple[int, int, int, bytes]:
    data = input_path.read_bytes()
    format_code, width, height, _mip_count = parse_tex_header(data)

    if format_code != 0x07:
        raise NotImplementedError(
            f"Unsupported TEX format 0x{format_code:02x}. "
            "This extractor currently supports palette-mapped TEX files only."
        )

    offset_table = [
        int.from_bytes(data[0x10 + i * 4 : 0x14 + i * 4], "little") for i in range(7)
    ]
    base_offset = offset_table[0]

    expected_size = width * height * 4
    payload = data[base_offset : base_offset + expected_size]
    if len(payload) != expected_size:
        raise ValueError(
            f"Payload size mismatch for {input_path.name}: "
            f"expected {expected_size} bytes, got {len(payload)}"
        )

    return format_code, width, height, payload


def render_tex(
    payload: bytes,
    width: int,
    height: int,
    palette: list[tuple[int, int, int]],
    output_path: Path,
) -> None:
    pixels = []
    index_channel = 3  # rgba
    for pixel_index in range(width * height):
        raw_index = payload[pixel_index * 4 + index_channel]

        b_index = payload[pixel_index * 4 + 0]
        g_index = payload[pixel_index * 4 + 1]
        r_index = payload[pixel_index * 4 + 2]
        a_index = payload[pixel_index * 4 + 3]

        # the following calculations are incorrect
        # colour_index = round(r_index / 17)
        # palette_row = round(a_index / 17)
        colour_index = r_index >> 4  # or round(r_index/17)
        palette_row = a_index >> 4  # or round(a_index/17)
        final_index = palette_row * 16 + colour_index

        print(
            pixel_index, "rgba", (r_index, g_index, b_index, a_index), "->", final_index
        )

        if raw_index >= len(palette):
            raise ValueError(
                f"Palette index {raw_index} out of range for palette size {len(palette)}"
            )
        elif final_index == 0:
            pixels.append((255, 0, 255, 0))
        else:
            # pixels.append(palette[raw_index])
            # pixels.append(palette[a_index])
            r, g, b = palette[final_index]
            pixels.append((r, g, b, 255))

    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    image.save(output_path)


def render_palette(palette: list[tuple[int, int, int]], output_path: Path) -> None:
    num_colors = len(palette)
    cols = 32
    rows = (num_colors + cols - 1) // cols
    cell_size = 16
    image_width = cols * cell_size
    image_height = rows * cell_size

    image = Image.new("RGB", (image_width, image_height), color=(0, 0, 0))
    for i, (r, g, b) in enumerate(palette):
        x = (i % cols) * cell_size
        y = (i // cols) * cell_size
        for dx in range(cell_size):
            for dy in range(cell_size):
                image.putpixel((x + dx, y + dy), (r, g, b))

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

    args = parser.parse_args()
    input_path: Path = args.input
    output_path: Path = input_path.with_suffix(".png")
    palette_path: Path = args.palette

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if not palette_path.exists():
        raise FileNotFoundError(f"Palette file does not exist: {palette_path}")

    palette = load_palette_blocks(palette_path)
    _format_code, width, height, payload = extract_tex(input_path)

    render_tex(payload, width, height, palette, output_path)
    # render_palette(palette, palette_path.with_name(palette_path.stem + "_palette.png"))
    # tex_to_csv(payload, input_path, width, height)

    print(
        f"Wrote {output_path} ({width}x{height}) with palette ({len(palette)} colors, format: {_format_code})"
    )

    # dump palette to txt
    # with open(
    #     palette_path.with_name(palette_path.stem + "_palette.txt"), "w"
    # ) as palette_txt:
    #     for index, data in enumerate(palette):
    #         palette_txt.write(f"{index}: {data[0], data[1], data[2]}\n")


if __name__ == "__main__":
    main()
