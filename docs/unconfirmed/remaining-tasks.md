# Missing pieces for full stage rendering

> **Historical bring-up checklist.** The pipeline below is implemented; the main open
> piece is item 4 (X6 animated-palette cores) — see `docs/unconfirmed/issues.md`.

## What you have ✅

- `utils/tex.py` — renders TEX to PIL Image given palette + CLUT index
- `utils/palette.py` — loads COL files

---

## 1. OMP parser

`st000.omp` is the tilemap. The tile data is clearly LE u16 tile indices (e.g. `0x0702`, `0x06FA`) that directly index into `st000.ocl`. Zero entries are transparent/empty. The structure visible in the file is **sparse rows** — each row has content at a fixed column offset, then long runs of zeros. What's unknown:

- **Which TEX/tileset a tile uses** — Unsure how or where this information is stored

## 2. Tile extraction from `st000.tex`

`st000.tex` is 4 MB, 8bpp format (`0x12`). Given tile size is almost certainly **16×16 pixels** (256 bytes per tile), the sheet holds ~16,384 tiles. What's unknown:

- **Tiles-per-row in the sheet** — needed to compute the 2D pixel offset from a flat tile_id: `pixel_x = (tile_id % tiles_per_row) * 16`, `pixel_y = (tile_id // tiles_per_row) * 16`
- The existing `convert_tex_to_image` in `tex.py` renders the whole TEX as one image — you'd need a `extract_tile(tex_data, tile_id)` function

## 3. `st000_chr256.tex` and `st000_ch3.tex`

Two companion tilesets whose purpose is unconfirmed:

- `st000_chr256.tex` — likely the **256-color parallax background layer** (chr256 = character/tile set for the 256-wide scrolling BG)
- `st000_ch3.tex` — likely a **third scroll layer** (ch3 = channel/layer 3, a mid-ground or decorative layer)

These may be referenced by specific OMP layer entries, or they may be standalone background panels rendered at a fixed scroll offset.

## 4. OCL `flags` byte → COL file selection

For sprites (OCL entry 39), `flags=0x38` and `col=8` meant 8 CLUTs starting at `clut_base` in `col00_0x.col`. For stage tiles, you're seeing `flags=0x39` and `flags=0x3b` on early OCL entries with `clut_base=0` — this is where the **animated crystal palette** (`st0_0.col`) kicks in. The flags byte almost certainly selects between:

| flags  | COL file                                         |
| ------ | ------------------------------------------------ |
| `0x00` | `col00_0x.col` (standard stage tileset)          |
| `0x39` | `st0_0.col` (animated crystal — cycling palette) |
| `0x3b` | unknown (possibly `col00_0z.col` for alt area)   |
| `0x38` | `col00_0x.col` variant / hit flash               |

This mapping needs to be confirmed by cross-referencing which OCL entries carry `flags=0x39` against which tiles visually use the animated crystal palette.

---

## Rendering pipeline summary

Once the above is resolved, the full pipeline for a static stage layer PNG would be:

```
st000.omp  →  [OMP parser]  →  layer[N]: 2D array of tile_ids (W×H)
                                    ↓
tile_id  →  st000.ocl  →  (clut_base, flags)
                                    ↓
         flags → select COL file  →  palette
                                    ↓
tile_id  →  st000.tex  →  16×16 pixel block  →  apply palette[clut_base]
                                    ↓
                           composite tiles onto W*16 × H*16 canvas
```

Layers rendered separately, then optionally composited in back→front order:
`st000_chr256.tex` (far BG) → OMP layer 0 (BG tiles) → OMP layer 1 (main/platform tiles) → OMP layer 2 (FG tiles) → sprites from PAT.
