"""
End-to-end render test for st000 using the confirmed layout table from RXC2.exe.

Outputs:
  st000_level.png   — full level render using Layer 0 (foreground)
  st000_catalog.png — raw OMP screen catalog (debug, no layout)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.omp import load_omp, render_level, render_omp, load_layout_from_exe, LayerPreset
from utils.ocl import load_ocl
from utils.tex import load_tex
from utils.palette import load_col_palettes

BASE = Path("PC/X5/stage/st000")
COL_PATH = Path("PC/X5/col/stage/col00_0x.col")
EXE_PATH = Path("debug/RXC2.exe")

print("Loading OMP...")
omp = load_omp(BASE / "st000.omp")
print(f"  n_screens={omp.n_screens}")

print("Loading OCL...")
ocl = load_ocl(BASE / "st000.ocl")
print(f"  n_entries={len(ocl)}")

print("Loading TEX...")
tex = load_tex(BASE / "st000.tex")
print(f"  width={tex['width']} height={tex['height']} format={tex.get('format')}")

print("Loading COL palette...")
col = load_col_palettes(COL_PATH)
print(f"  palette loaded: {type(col).__name__}")

print("Loading layout from RXC2.exe (layer 0 = foreground)...")
layout = load_layout_from_exe(EXE_PATH, layer=0)
n_sy = len(layout.screens)
n_sx = len(layout.screens[0]) if layout.screens else 0
print(f"  dimensions: {n_sx} screens wide × {n_sy} screens tall")

# Verify anchors
checks = [
    ((0, 3), 11, "layout[3][0]=11"),
    ((0, 4), 26, "layout[4][0]=26"),
    ((4, 4), 30, "layout[4][4]=30"),
    ((8, 4), 34, "layout[4][8]=34"),
]
print("Verifying anchors...")
for (sx, sy), expected, label in checks:
    got = layout.get(sx, sy)
    status = "OK" if got == expected else f"FAIL (expected {expected}, got {got})"
    print(f"  {label}: {status}")

print()
print("Rendering full level (foreground layer)...")
flags_to_palette = {0x00: col, 0x38: col, 0x39: col, 0x3b: col}
img = render_level(
    omp,
    layout,
    level_width_screens=n_sx,
    level_height_screens=n_sy,
    raw_pixels=tex["raw_image"],
    tex_width=tex["width"],
    ocl_entries=ocl,
    flags_to_palette=flags_to_palette,
)
out_level = Path("st000_level.png")
img.save(out_level)
print(f"  Saved {out_level}  ({img.width}×{img.height} px)")

print()
print("Rendering OMP catalog (debug)...")
dbg = render_omp(
    omp,
    tex["raw_image"],
    tex["width"],
    ocl,
    flags_to_palette=flags_to_palette,
    preset=LayerPreset.MAIN,
)
out_catalog = Path("st000_catalog.png")
dbg.save(out_catalog)
print(f"  Saved {out_catalog}  ({dbg.width}×{dbg.height} px)")

print()
print("Done.")
