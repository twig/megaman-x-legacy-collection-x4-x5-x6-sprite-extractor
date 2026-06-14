#!/usr/bin/env python3
"""
draw_grid.py - Draw a labeled grid over a PNG image.

Usage: python draw_grid.py input.png [--size 16]

Output: input-grid.png (original is not modified)
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_SIZE = 8
TEXT_PADDING = 6
COLOUR_YELLOW = (255, 255, 0)
COLOUR_YELLOW_75 = (255, 255, 0, 75)
COLOUR_GREEN = (0, 255, 0)
COLOUR_GREEN_150 = (0, 255, 0, 150)


def draw_grid(input_path: Path, grid_size: int = 16) -> None:
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    try:
        font = ImageFont.truetype("cour.ttf", FONT_SIZE)
    except OSError:
        font = ImageFont.load_default(size=FONT_SIZE)

    # Measure a sample label to determine padding needed
    dummy = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy)
    sample_bbox = dummy_draw.textbbox((0, 0), "999", font=font)
    label_w = int(sample_bbox[2] - sample_bbox[0])
    label_h = int(sample_bbox[3] - sample_bbox[1])

    pad_h = label_w + TEXT_PADDING
    pad_v = label_h + TEXT_PADDING

    new_w = pad_h + w + pad_h
    new_h = pad_v + h + pad_v

    canvas = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 255))
    canvas.paste(img, (pad_h, pad_v))

    # Draw grid lines on a transparent overlay, then composite
    overlay = Image.new("RGBA", (new_w, new_h), (30, 30, 30, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Vertical lines + column labels
    for col, x in enumerate(range(0, w, grid_size)):
        cx = x + pad_h
        overlay_draw.line(
            [(cx, pad_v), (cx, pad_v + h - 1)],
            fill=COLOUR_GREEN_150 if col % 10 == 0 else COLOUR_YELLOW_75,
            width=1,
        )
        label = str(col)
        bbox = overlay_draw.textbbox((0, 0), label, font=font)
        label_w = bbox[2] - bbox[0]
        # centre label to column above the line
        tx = cx + (grid_size // 2) - (label_w // 2)
        overlay_draw.text(
            (tx, 2),
            label,
            fill=(COLOUR_GREEN if col % 10 == 0 else COLOUR_YELLOW),
            font=font,
        )

    # Horizontal lines + row labels
    for row, y in enumerate(range(0, h, grid_size)):
        cy = y + pad_v
        overlay_draw.line(
            [(pad_h, cy), (pad_h + w - 1, cy)],
            fill=COLOUR_GREEN_150 if row % 10 == 0 else COLOUR_YELLOW_75,
            width=1,
        )
        label = str(row)
        bbox = overlay_draw.textbbox((0, 0), label, font=font)
        label_w = bbox[2] - bbox[0]
        label_h = bbox[3] - bbox[1]
        # right-align label to the left of the image
        tx = pad_h - label_w - 3
        ty = cy + (grid_size // 2) - (label_h // 2)
        overlay_draw.text(
            (tx, ty),
            label,
            fill=(COLOUR_GREEN if row % 10 == 0 else COLOUR_YELLOW),
            font=font,
        )

    canvas = Image.alpha_composite(canvas, overlay)

    output_path = input_path.with_stem(input_path.stem + "-grid")
    canvas.save(output_path)
    print(f"Saved: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw a labeled grid over a PNG image at regular intervals"
    )
    parser.add_argument("input", type=Path, help="Input PNG image")
    parser.add_argument(
        "--size",
        type=int,
        default=16,
        help="Grid cell size in pixels (default: 16)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"File not found: {args.input}")

    draw_grid(args.input, args.size)


if __name__ == "__main__":
    main()
