import argparse
from pathlib import Path

from utils.debug import debug_palette_png
from utils.palette import load_col_palettes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a palette COL to PNG."
    )
    parser.add_argument("col_file", type=Path, help="Path to the .col file")
    args = parser.parse_args()

    col_file: Path = args.col_file.resolve()

    if not col_file.exists():
        raise FileNotFoundError(f"ERROR: COL file not found: {col_file}")

    palette = load_col_palettes(col_file)
    out_file = Path('./out.png').with_stem(col_file.stem)
    debug_palette_png(palette, out_file)

    print(f"Saved {col_file.stem} to {out_file}")

if __name__ == "__main__":
    main()
