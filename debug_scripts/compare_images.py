#!/usr/bin/env python3
"""Compare a sample image against a baseline, tile by tile.

The image is broken into 16x16 pixel tiles. Any tile that differs from the
baseline is highlighted by drawing a solid yellow square in its place.

By default the highlights are saved directly onto the sample image (overwriting
it). Pass --diff to instead write to <sample_filename>_diff.<ext>.
"""

import argparse
import os
import sys

from PIL import Image

TILE = 16
YELLOW = (255, 255, 0)


def compare(sample_path, baseline_path, tile=TILE, save_diff=False, crop=True):
    sample = Image.open(sample_path).convert("RGBA")
    baseline = Image.open(baseline_path).convert("RGBA")

    if sample.size != baseline.size:
        print(
            f"warning: size mismatch sample={sample.size} baseline={baseline.size}; "
            "comparing the overlapping region only"
        )

    width = min(sample.width, baseline.width)
    height = min(sample.height, baseline.height)

    sample_px = sample.load()
    baseline_px = baseline.load()

    diff_tiles = 0
    total_tiles = 0
    bbox = None  # (min_x, min_y, max_x, max_y) over all differing tiles

    for ty in range(0, height, tile):
        for tx in range(0, width, tile):
            total_tiles += 1
            differs = False
            for y in range(ty, min(ty + tile, height)):
                for x in range(tx, min(tx + tile, width)):
                    if sample_px[x, y] != baseline_px[x, y]:
                        differs = True
                        break
                if differs:
                    break

            if differs:
                diff_tiles += 1
                x0, y0 = tx, ty
                x1 = min(tx + tile, sample.width) - 1
                y1 = min(ty + tile, sample.height) - 1
                for x in range(x0, x1 + 1):
                    sample_px[x, y0] = (*YELLOW, 255)
                    sample_px[x, y1] = (*YELLOW, 255)
                for y in range(y0, y1 + 1):
                    sample_px[x0, y] = (*YELLOW, 255)
                    sample_px[x1, y] = (*YELLOW, 255)

                if bbox is None:
                    bbox = [x0, y0, x1, y1]
                else:
                    bbox[0] = min(bbox[0], x0)
                    bbox[1] = min(bbox[1], y0)
                    bbox[2] = max(bbox[2], x1)
                    bbox[3] = max(bbox[3], y1)

    if save_diff:
        root, ext = os.path.splitext(sample_path)
        out_path = f"{root}-diff{ext}"
    else:
        out_path = sample_path

    if crop and bbox is not None:
        # right/bottom are inclusive pixel coords, crop expects exclusive
        sample = sample.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1))

    sample.save(out_path)
    print(f"{diff_tiles}/{total_tiles} tiles differ -> {out_path}")
    return diff_tiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", help="path to the sample image")
    parser.add_argument("baseline", help="path to the baseline image")
    parser.add_argument(
        "--diff",
        action="store_true",
        help="save to <sample_filename>_diff instead of overwriting the sample",
    )
    parser.add_argument(
        "--tile", type=int, default=TILE, help="tile size in pixels (default 16)"
    )
    parser.add_argument(
        "--no-crop",
        dest="crop",
        action="store_false",
        help="keep full image instead of cropping to the bounds of the differences",
    )
    args = parser.parse_args()

    compare(
        args.sample,
        args.baseline,
        tile=args.tile,
        save_diff=args.diff,
        crop=args.crop,
    )


if __name__ == "__main__":
    sys.exit(main())
