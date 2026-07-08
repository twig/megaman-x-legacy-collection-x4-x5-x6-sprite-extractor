import csv
from pathlib import Path
from PIL import Image, ImageDraw

from utils.types import Palette, TexData, TexFormat
from utils.palette import convert_palette_to_clut
from utils.omp import LayoutTable, OmpLayer


def debug_palette_txt(palette: Palette, output_path: Path):
    with open(output_path, "w") as palette_txt:
        for index, swatch in enumerate(palette):
            palette_txt.write(f"{index}: {swatch[0], swatch[1], swatch[2]}\n")


def debug_clut_txt(palette: Palette, output_path: Path):
    clut = convert_palette_to_clut(palette)
    with open(output_path, "w") as clut_txt:
        for clut_index, palette in enumerate(clut):
            clut_txt.write(f"clut index #{clut_index}:\n")

            for index, swatch in enumerate(palette):
                clut_txt.write(f"{index}: {swatch[0], swatch[1], swatch[2]}\n")


def debug_palette_png(original_palette: Palette, output_path: Path, skip_trailing_blacks=True) -> None:
    # Since this is mainly used for debugging, we don't need a big black patch at the end
    # Determine end of meaningful data and trim palette if necessary
    if skip_trailing_blacks:
        last_nonzero_index = max(
            i for i, (r, g, b, a) in enumerate(original_palette) if (r, g, b) != (0, 0, 0)
        )
        palette = original_palette[: last_nonzero_index + 1]
    else:
        palette = original_palette

    cols = 16
    cell_size = 16
    label_width = 40
    num_colors = len(palette)
    rows = (num_colors + cols - 1) // cols
    image_width = cols * cell_size + label_width
    image_height = rows * cell_size

    image = Image.new("RGB", (image_width, image_height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, (r, g, b, a) in enumerate(palette):
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


def debug_tex_csv(tex_data: TexData, input_path: Path) -> None:
    raw_image = tex_data["raw_image"]
    width = tex_data["width"]
    height = tex_data["height"]

    output_path_8bpp = input_path.with_name(input_path.stem + "_8bpp.csv")
    output_path_grey = input_path.with_name(input_path.stem + "_grey.csv")
    output_path_alpha = input_path.with_name(input_path.stem + "_alpha.csv")

    if tex_data["format_code"] == TexFormat.FORMAT_8BPP:
        with output_path_8bpp.open("w", newline="") as csvfile:
            writer = csv.writer(csvfile)

            for y in range(height):
                row = []

                for x in range(width):
                    pixel_index = y * width + x
                    pixel = raw_image[pixel_index]
                    row.append(pixel)

                writer.writerow(row)

    elif tex_data["format_code"] == TexFormat.FORMAT_32BPP:
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
                        r_index = raw_image[pixel_index * 4 + 2]
                        a_index = raw_image[pixel_index * 4 + 3]

                        row_grey.append(r_index)
                        row_alpha.append(a_index)

                    writer_grey.writerow(row_grey)
                    writer_alpha.writerow(row_alpha)

def debug_layout_csv(layer: OmpLayer, layout: LayoutTable, output_path: Path):
    level_width_screens = layout.width
    level_height_screens = layout.height

    with output_path.open("w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        for sy in range(level_height_screens):
            # for each screen in the row, loop through the 16 rows vertically,
            # combining the data from each screen into a single row in the CSV
            for wy in range(16):
                row: list[int] = []

                for sx in range(level_width_screens):
                    screen_id = layout.get(sx, sy)

                    if screen_id is None:
                        continue

                    screen_tiles = layer.tiles[screen_id]

                    # raw_ocl_idx = screen_tiles[wy * 16 + wx]
                    row.extend([screen_tiles[wy * 16 + wx] for wx in range(16)])

                writer.writerow(row)

    print(f"Debug layout CSV written to: {output_path}")
