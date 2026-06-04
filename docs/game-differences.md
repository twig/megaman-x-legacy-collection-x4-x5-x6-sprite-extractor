# X4 / X5 / X6 PC File Format Differences

## Binary Format: Identical Across All Three Games

The parsers in `utils/*.py` require **no code changes** to handle X4 and X6 files.
All four file types share the same binary format:

| Format | Magic     | Header | Entry size                    |
| ------ | --------- | ------ | ----------------------------- |
| COL    | `COL\x00` | 12 B   | 2 B (BGR555)                  |
| OCL    | `OCL\x00` | 12 B   | 4 B (flags/col/clut_base/pad) |
| OMP    | `OMP\x00` | 12 B   | 2 B (LE u16 tile index)       |
| PAT    | `PAT\x00` | 12 B   | variable (see below)          |
| TEX    | `TEX\x00` | 0x30 B | 1 B (8bpp) or 4 B (32bpp)     |

The first 16 bytes of the stage TEX file are byte-for-byte identical across all three
games (dimensions 2048×2048, format code `0x12`, first mip offset `0x14`). Mip table
entries 2–7 are all zeros in X4 but hold valid offsets in X5/X6 — irrelevant since
only `offset_table[0]` is used.

All three PAT files share magic `PAT\x00` and version LE u32 = 3. The header layout
(magic / version / animation count / per-animation frame-count array) is identical;
only the values differ (see Quantitative Differences below).

---

## Quantitative Differences (Content, Not Format)

| Metric                                                            | X4                        | X5               | X6               |
| ----------------------------------------------------------------- | ------------------------- | ---------------- | ---------------- |
| Stage TEX size (bytes)                                            | 4,194,324 (2048×2048)     | same             | same             |
| COL entry count                                                   | 2,048 → **128 CLUT rows** | 8,192 → 512 rows | 8,192 → 512 rows |
| OCL entry count                                                   | 2,243                     | 3,777            | 3,098            |
| OMP map height / rows (stored as `n_rows×256` at header offset 8) | 86                        | 107              | 137              |
| OMP map width / cols (always 256 tiles = 4096 px)                 | 256                       | 256              | 256              |
| Chr TEX pages per object                                          | 14 (0–13)                 | 10 (0–9)         | 9 (0–8)          |
| PAT animation count                                               | 14 (0x0e)                 | 10 (0x0a)        | 17 (0x11)        |
| PAT file size (bytes)                                             | 38,832                    | 24,736           | 50,808           |

Stage TEX size and resolution are the same across all three games.

---

## Directory Layout

### X5 (reference — single per-stage subfolder)

```
stage/st000/                ← tex, ocl, omp share one folder
  st000.tex
  st000.ocl
  st000.omp
col/stage/
  col00_0x.col              ← standard stage palette
  col00_0x_eng.col          ← English localisation variant
  col00_0z.col              ← alt area palette
  st0_0.col                 ← animated cycling palette (crystals etc.)
chr/stage/
  obj00_0a_NNN.tex          (0–9)
  obj00_0a.ctex
pat/stage/
  obj00_00.pat              ← flat file, no subdirectory
                            ← magic PAT\x00, version 3, 10 animations
```

### X4 (separate subdirs per file type; **uppercase** filenames)

```
stage/dds/
  ST00_00.tex               ← uppercase; pattern ST{stage}_{half}.tex
stage/cel/
  SCR00_00.ocl              ← uppercase; SCR prefix, not the stage name
stage/map/
  SCR00_00.omp              ← uppercase; SCR prefix
stage/col/
  col00_0X_eng.col          ← COL lives inside stage/ (not in root col/)
                            ← no animated palette COL present in sample
col/stage/
  st0_0.col                 ← shared animated palette (same path as X5)
chr/stage/st00_00/
  OBJ00_0A_NNN.tex          (0–13) — 14 pages, uppercase, subdir per object
  st00_00.ctex
pat/stage/OBJ00_00/
  OBJ00_00.pat              ← subdir per PAT file
                            ← magic PAT\x00, version 3, 14 animations
rlist/
  st00_00_eng.rlst          ← X4-only file (magic `LST\x01`, 144 B); absent from X5/X6
```

> **SCR prefix**: the stage `st00_00` maps to `SCR00_00` for OCL/OMP. This mapping
> is not encoded in any file found in the sample — it must be tracked in caller code.

### X6 (separate subdirs like X4; **lowercase** filenames)

```
stage/dds/
  st00.tex
stage/cel/
  st00.ocl
stage/map/
  st00.omp
stage/col/
  col00_0x.col              ← standard palette
  col00_0z.col              ← alt area palette
  eng/
    col00_0x.col            ← English localisation variant (nested under eng/)
col/stage/st00/
  st00.col                  ← stage-specific animated palette (19 CLUT rows)
                            ← equivalent to X5's st0_0.col but per-stage
  st00_palette.png          ← debug visualisation committed alongside the binary
chr/stage/st00/
  st00_NNN.tex              (0–8) — 9 pages; object named after stage, not obj prefix
  st00.ctex
  st00_000/                 ← sub-subdir for first object's extra files
pat/stage/st00/
  st00.pat                  ← subdir per stage
                            ← magic PAT\x00, version 3, 17 animations
```

---

## Path Resolution Rules (for a loader/wrapper)

| File         | X4 path pattern                      | X5 path pattern                | X6 path pattern                          |
| ------------ | ------------------------------------ | ------------------------------ | ---------------------------------------- |
| Stage TEX    | `stage/dds/{STAGE}.tex`              | `stage/{stage}/{stage}.tex`    | `stage/dds/{stage}.tex`                  |
| Stage OCL    | `stage/cel/{SCR}.ocl`                | `stage/{stage}/{stage}.ocl`    | `stage/cel/{stage}.ocl`                  |
| Stage OMP    | `stage/map/{SCR}.omp`                | `stage/{stage}/{stage}.omp`    | `stage/map/{stage}.omp`                  |
| Main COL     | `stage/col/{col_name}.col`           | `col/stage/{col_name}.col`     | `stage/col/{col_name}.col`               |
| Animated COL | (not in sample)                      | `col/stage/st0_0.col`          | `col/stage/{stage}/{stage}.col`          |
| Eng COL      | `stage/col/{col_name}_eng.col`       | `col/stage/{col_name}_eng.col` | `stage/col/eng/{col_name}.col`           |
| PAT          | `pat/stage/{OBJ}/{OBJ}.pat` (subdir) | `pat/stage/{obj}.pat` (flat)   | `pat/stage/{stage}/{stage}.pat` (subdir) |

X4 and X6 share the `stage/{type}/` split; X5 bundles everything into `stage/{stage}/`.

---

## X4-Only: `rlist/` Files

X4 has `.rlst` files (magic `LST\x01`) in a top-level `rlist/` folder that are absent
from X5 and X6. File size is 144 bytes for the sample. Purpose is currently unknown.
