from __future__ import annotations

import argparse
from pathlib import Path
from os import makedirs


from utils.types import Palette, TexData
from utils.debug import (
    debug_palette_png,
    debug_tex_csv,
    debug_palette_txt,
    debug_clut_txt,
)
from utils.palette import load_col_palettes
from utils.tex import load_tex, convert_tex_to_image


def render_tex(
    tex_data: TexData,
    palette: Palette,
    output_path: Path,
    clut_index: int,  # 0-based row index in CLUT table
) -> None:
    image = convert_tex_to_image(tex_data, palette, clut_index)

    if image:
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
    # debug_palette_txt(palette, palette_path.with_name(palette_path.stem + "_debug.txt"))
    # debug_clut_txt(
    #     palette, palette_path.with_name(palette_path.stem + "_clut_debug.txt")
    # )
    debug_tex_csv(tex_data, input_path)

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
