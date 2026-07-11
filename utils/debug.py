import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from utils.types import Palette, TexData, TexFormat
from utils.palette import convert_palette_to_clut
from utils.omp import LayoutTable, OmpLayer
from utils.consts import TILE_SIZE, TILES_PER_SCREEN, CLUT_COLORS_PER_ROW

_DEBUG_SCREEN_LINE  = (255, 220, 0, 210)   # yellow-ish grid lines
_DEBUG_SCREEN_TEXT  = (255, 220, 0, 255)   # yellow text
_DEBUG_LAYER_LINE  = (255, 0, 255, 255)   # layer lines
_DEBUG_TEXTBG = (0, 0, 0, 170)      # semi-transparent black text background


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

    cell_size = 16
    label_width = 40
    num_colors = len(palette)
    rows = (num_colors + CLUT_COLORS_PER_ROW - 1) // CLUT_COLORS_PER_ROW
    image_width = CLUT_COLORS_PER_ROW * cell_size + label_width
    image_height = rows * cell_size

    image = Image.new("RGB", (image_width, image_height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, (r, g, b, a) in enumerate(palette):
        x = (i % CLUT_COLORS_PER_ROW) * cell_size
        y = (i // CLUT_COLORS_PER_ROW) * cell_size
        for dx in range(cell_size):
            for dy in range(cell_size):
                image.putpixel((x + dx, y + dy), (r, g, b))

    for row in range(rows):
        y = row * cell_size
        label = str(row)
        draw.text((CLUT_COLORS_PER_ROW * cell_size + 2, y + 2), label, fill=(255, 255, 255))

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

# ── Debug overlay helpers ─────────────────────────────────────────────────────
def debug_layout_csv(layer: OmpLayer, layout: LayoutTable, output_path: Path):
    level_width_screens = layout.width
    level_height_screens = layout.height

    with output_path.open("w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        for sy in range(level_height_screens):
            # for each screen in the row, loop through the 16 rows vertically,
            # combining the data from each screen into a single row in the CSV
            for wy in range(TILES_PER_SCREEN):
                row: list[int] = []

                for sx in range(level_width_screens):
                    screen_id = layout.get(sx, sy)

                    if screen_id is None:
                        continue

                    screen_tiles = layer.tiles[screen_id]

                    # raw_ocl_idx = screen_tiles[wy * 16 + wx]
                    row.extend([screen_tiles[wy * TILES_PER_SCREEN + wx] for wx in range(TILES_PER_SCREEN)])

                writer.writerow(row)

    print(f"Debug layout CSV written to: {output_path}")


def debug_overlay_catalog(img, n_screens: int, tile_size: int = TILE_SIZE) -> None:
    """Draw per-screen boundary lines and screen-id labels on the catalog image."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default()
    for sid in range(n_screens):
        y = sid * tile_size
        draw.line([(0, y), (img.width - 1, y)], fill=_DEBUG_SCREEN_LINE, width=1)
        label = f"scr {sid}"
        tw = len(label) * 6 + 2
        draw.rectangle([0, y, tw, y + 9], fill=_DEBUG_TEXTBG)
        draw.text((1, y), label, fill=_DEBUG_SCREEN_TEXT, font=font)


def debug_overlay_level(
    img,
    layout: LayoutTable,
    level_width_screens: int,
    level_height_screens: int,
    tile_size: int = TILE_SIZE,
) -> None:
    """Draw screen boundary grid lines and (sx,sy)/id labels on the level image."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default()
    screen_px = TILE_SIZE * tile_size  # pixels per screen edge

    # Grid lines
    for sx in range(level_width_screens + 1):
        x = sx * screen_px
        draw.line([(x, 0), (x, img.height - 1)], fill=_DEBUG_SCREEN_LINE, width=1)
    for sy in range(level_height_screens + 1):
        y = sy * screen_px
        draw.line([(0, y), (img.width - 1, y)], fill=_DEBUG_SCREEN_LINE, width=1)

    # Per-screen labels
    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            screen_id = layout.get(sx, sy)
            px = sx * screen_px + 2
            py = sy * screen_px + 2
            sid_str = str(screen_id) if screen_id is not None else "?"
            lines = [f"Screen ({sx},{sy}), ID #{sid_str}"]
            tw = max(len(l) for l in lines) * 6 + 2
            draw.rectangle([px - 1, py - 1, px + tw, py + 19], fill=_DEBUG_TEXTBG)
            for i, line in enumerate(lines):
                draw.text((px, py + i * 10), line, fill=_DEBUG_SCREEN_TEXT, font=font)

    # Add in lines for layers 0, 1 and 2 for every ⅓ level_height_screens
    # only when height is clealy divisible by 3
    if level_height_screens % 3 == 0:
        for layer in range(3):
            y = (layer * level_height_screens // 3) * screen_px
            draw.line([(0, y), (img.width - 1, y)], fill=_DEBUG_LAYER_LINE, width=1)
