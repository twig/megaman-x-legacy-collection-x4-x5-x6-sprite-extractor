import csv
from pathlib import Path
from PIL import Image, ImageDraw

from utils.types import Palette, TexData


def debug_palette_txt(palette: Palette, output_path: Path):
    with open(output_path, "w") as palette_txt:
        for index, data in enumerate(palette):
            palette_txt.write(f"{index}: {data[0], data[1], data[2]}\n")


def debug_palette_png(original_palette: Palette, output_path: Path) -> None:
    # Since this is mainly used for debugging, we don't need a big black patch at the end
    # Determine end of meaningful data and trim palette if necessary
    last_nonzero_index = max(
        i for i, (r, g, b) in enumerate(original_palette) if (r, g, b) != (0, 0, 0)
    )
    palette = original_palette[: last_nonzero_index + 1]

    cols = 16
    cell_size = 16
    label_width = 40
    num_colors = len(palette)
    rows = (num_colors + cols - 1) // cols
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


def debug_tex_csv(tex_data: TexData, input_path: Path) -> None:
    raw_image = tex_data["raw_image"]
    width = tex_data["width"]
    height = tex_data["height"]

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
                    r_index = raw_image[pixel_index * 4 + 2]
                    a_index = raw_image[pixel_index * 4 + 3]

                    row_grey.append(r_index)
                    row_alpha.append(a_index)

                writer_grey.writerow(row_grey)
                writer_alpha.writerow(row_alpha)
