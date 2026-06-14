from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

PALETTE_BLOCK_SIZE = 243
PALETTE_BLOCK_COLORS = 81


def load_palette(palette_path: Path) -> list[list[tuple[int, int, int]]] | None:
    if not palette_path.exists():
        return None

    data = palette_path.read_bytes()
    if len(data) < 8 or data[:4] != b"COL\x00":
        return None

    blocks: list[list[tuple[int, int, int]]] = []
    offset = 8
    while offset + PALETTE_BLOCK_SIZE <= len(data):
        block = data[offset : offset + PALETTE_BLOCK_SIZE]
        colors = [tuple(block[i : i + 3]) for i in range(0, PALETTE_BLOCK_SIZE, 3)]
        blocks.append(colors)
        offset += PALETTE_BLOCK_SIZE

    return blocks


def resolve_palette_path(palette_path: Path) -> Path | None:
    return palette_path if palette_path.exists() else None


def convert_dds_to_png(input_path: Path, palette_path: Path, output_path: Path) -> None:
    with Image.open(input_path) as image:
        image = image.convert("RGBA")

        r, g, b, a = image.split()

        # as-is
        image.save(output_path)

        # channel mode
        with output_path.with_name(f"{output_path.name}_channel.png") as filename:
            output = Image.merge("RGBA", (r, a, b, g))
            output.save(filename)

        # replace by palette index
        from pprint import pprint

        palette = load_palette(palette_path)

        #         0123
        # get the RGBA channel data
        red_values = image.get_flattened_data(0)
        green_values = image.get_flattened_data(1)
        blue_values = image.get_flattened_data(2)
        alpha_values = image.get_flattened_data(3)

        print(
            "minmax",
            "r",
            [min(list(red_values)), max(list(red_values))],
            "g",
            [min(list(green_values)), max(list(green_values))],
            "b",
            [min(list(blue_values)), max(list(blue_values))],
            "a",
            [min(list(alpha_values)), max(list(alpha_values))],
        )

        # multi-palette
        # pprint(palette, indent=2)
        for palette_index in range(0, len(palette)):
            pal = palette[palette_index]

            # this palette doesn't have enough to paint this image
            if len(pal) < max(alpha_values):
                continue

            with output_path.with_name(
                f"{output_path.name}_col_{palette_index}.png"
            ) as filename:
                output = Image.new("RGB", image.size)
                pixels = output.load()
                current_index = 0

                for x in range(0, image.width):
                    for y in range(0, image.height):
                        alpha_index = alpha_values[current_index]
                        current_index += 1

                        # print(
                        #     "image",
                        #     x,
                        #     y,
                        #     alpha_index,
                        # )
                        pixels[x, y] = pal[alpha_index]

                output.save(filename)

        # flat-palette
        with output_path.with_name(f"{output_path.name}_col.png") as filename:
            output = Image.new("RGB", image.size)
            pixels = output.load()
            current_index = 0

            flat_palette = []
            for b in palette:
                flat_palette += b

            for x in range(0, image.width):
                for y in range(0, image.height):
                    col_r = red_values[current_index]
                    col_g = green_values[current_index]
                    col_b = blue_values[current_index]
                    alpha_index = alpha_values[current_index]
                    current_index += 1

                    print("image", (x, y), ">", (col_r, col_g, col_b, alpha_index))
                    pixels[x, y] = flat_palette[alpha_index]

            output.save(filename)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a DDS texture to PNG and normalize the mixed channels."
    )
    parser.add_argument("input", type=Path, help="Path to the input DDS file")
    parser.add_argument(
        "palette",
        type=Path,
        nargs="?",
        help="Path to a COL palette file. Defaults to <input>.col.",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Optional output PNG path. Defaults to <input>.png",
    )

    args = parser.parse_args()

    input_path: Path = args.input
    palette_path: Path = args.palette or input_path.with_suffix(".col")
    output_path: Path = args.output or input_path.with_suffix(".png")

    if not resolve_palette_path(palette_path):
        print("Invalid palette", palette_path)
        return

    convert_dds_to_png(
        input_path,
        palette_path,
        output_path,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
