# Finding Stage Layout Offsets for Unresolved OMP Files

## Background — What we're looking for

Every stage in Mega Man X4/X5/X6 has a **layout table** — a simple grid of numbers stored inside
`RXC2.exe`. Each number tells the game which "screen" (a 16×16-tile chunk from the OMP file)
to place at that grid position.

Think of it like a spreadsheet:

- Columns = screen positions left to right (width **W**)
- Rows = screen positions top to bottom (height **H**)
- Each cell contains a **screen ID** — a number between 0 and `n_screens − 1`

A layout for a stage that is 5 screens wide × 29 rows tall is stored as `5 × 29 = 145 bytes`
for each of 3 layers (foreground, mid-BG, far-BG) — 435 bytes total, consecutively.

**The golden rule:** if the OMP has `n_screens = 100`, then every byte in layer 0 of the layout
must be between 0 and 99. The highest value present will equal exactly 99 for a fully-populated
stage.

---

## Easiest method

Run `explore_layout.py` against your preferred stage and start scrolling through the contents of the EXE.

The offsets are based on estimates of where the stage data may be, or the starting offset of the data section.

```python
python explore_layout.py stage_file.omp
```

Click on the left offset slider to move a row at a time.

Shift+Click the offset slider to scroll through a page at a time. Increase height to scroll through more content quicker.

**Note**: its possible for the data to look _mostly_ right but have gaps between screens. This means it is **not the right data**!

The correct data will have no gaps in between screens, making it easier to identify visually.
The wrong sections also have repeating screens which should not happen.

Once you found a recognisable part of the stage without gaps, adjust the offset/width/height until it looks right.

If everything worked out well, throw the offset values into `render_stage.STAGE_LAYOUT` and test with `render_stage.py`

## Older approaches

These kinda worked for X5 but didn't quite work for X6, but leaving notes here for prosperity.

Run the verifier to see what is already resolved:

```python
python debug\verify_x5_heights_omp.py
```

The summary at the bottom shows:

- **Block 1** (main layout region at `0x02D98548`) only matches 4 OMP files. All other block 1
  stages need OMP files with `n_screens` values we don't have — they will never match the 26 OMP
  files we have extracted.
- **21 OMP files have no layout match at all.** Their stages live in layout blocks not yet found.
  This includes the 12 regular-game stages: st020, st021, st040, st041, st050, st060, st070,
  st080, st170, st180, st220, staff_eng.

> **Note:** The 17 UNVERIFIED block 1 stages all need `n_screens` values (73, 100, 116 …) that
> none of our 26 OMP files have. Block 1 cannot be the home of the 12 unresolved regular stages.
> A separate, undiscovered layout block must exist for them.

---

## Step 1 — Know your OMP's `n_screens`

Before searching, find out how many screens the OMP has. Open a terminal in the workspace root
and run (replace the path for your stage):

```
python -c "
import struct
from pathlib import Path
d = Path('PC/X5/stage/st021/st021.omp').read_bytes()
n = struct.unpack_from('<I', d, 8)[0] // 256
print(f'n_screens = {n}  ->  layout bytes must be 0 to {n-1}')
"
```

Write that number down. For **st021** this gives `n_screens = 95`, so you are looking for layout
data where every byte is between 0 and 94 and the maximum value is exactly 94.

---

## Step 2 — Scan for candidate regions in Python

The layout bytes for a stage exist somewhere in the `.rdata` section of the exe
(`0x02D10200` – `0x02E79A00`). Run this to find them (replace `OMP_PATH` for your stage):

```python
python -c "
import struct
from pathlib import Path

OMP_PATH = Path('PC/X5/stage/st021/st021.omp')   # <- change this
EXE_PATH = Path('debug/RXC2.exe')

d = OMP_PATH.read_bytes()
n_screens = struct.unpack_from('<I', d, 8)[0] // 256
target_max = n_screens - 1
print(f'{OMP_PATH.stem}: n_screens={n_screens}, target L0_max={target_max}')
print()

exe = EXE_PATH.read_bytes()
RDATA_START = 0x2D10200
RDATA_END   = 0x2E79A00
MIN_LEN = 30   # ignore tiny fragments

regions = []
in_r = False; r_start = 0
for i in range(RDATA_START, RDATA_END):
    if exe[i] <= target_max:
        if not in_r: in_r = True; r_start = i
    else:
        if in_r:
            L = i - r_start
            data = exe[r_start:i]
            if L >= MIN_LEN and max(data) == target_max:
                facts = [(w,h) for w in range(1,51) for h in range(1,101) if 3*w*h==L]
                if facts:
                    regions.append((r_start, L, facts))
        in_r = False

print('Candidate regions (max==target_max, 3-layer factorizable):')
for off, L, facts in regions:
    print(f'  0x{off:08X}  len={L:5d}  3-layer dims: {facts[:4]}')
if not regions:
    print('  None found -- try relaxing: change max(data)==target_max to max(data)<=target_max')
"
```

**What to look for in the output:** a region whose dimensions match reasonable stage proportions.
For a 5-screens-wide vertical stage 25 rows tall you expect to see `(5, 25)` in the
`3-layer dims` list.

---

## Step 3 — Inspect the candidate in HxD

[HxD](https://mh-nexus.de/en/hxd/) is a free hex editor. Download and install it.

### Opening the file

1. Open HxD.
2. Go **File → Open** and navigate to `debug\RXC2.exe`.
3. Click **OK** when it warns about the large file size.

### Navigating to an offset

1. Press **Ctrl+G** (or **Search → Go to offset**).
2. Type the hex address from the Python output — for example `02D9A10E`.
3. Make sure **Hex** is selected (not Decimal).
4. Click **OK**.

The cursor jumps to that byte. The screen shows two panels:

- Left: the raw hex bytes (`1A 2E 00 3F …`)
- Right: a text interpretation (mostly gibberish for binary data — ignore it)

### What valid layout data looks like

The bytes will be **small numbers**. For a stage with `n_screens = 95` you should see values
mostly in the range `00` to `5E` (that's 94 in hex). You will **not** see large values like
`F4 E8 FF`.

**A good sign:** the first W bytes form the top row of the level. They often start with many
`00` bytes (empty sky at the top) and then increase further down.

**A bad sign:** large values like `E4 F7 00 00` repeating in groups of 4 — that is
coordinate/waypoint data, not a level map.

### Reading the grid visually in HxD

Go to **View → Bytes per row** and type the stage width W (e.g. `10` for a 10-screen-wide
stage). Now each row in HxD corresponds to one row of the level layout. Row 0 is the top of
the stage, row H − 1 is the bottom.

---

## Step 4 — Verify the candidate in Python

Once you have a candidate offset, verify it properly (fill in the four values at the top):

```python
python -c "
import struct
from pathlib import Path

OMP_PATH         = Path('PC/X5/stage/st021/st021.omp')  # <- your stage
EXE_PATH         = Path('debug/RXC2.exe')
CANDIDATE_OFFSET = 0x02D9A10E   # <- from your scan
W = 10   # width (screens per row)
H = 24   # height (screen rows)

d = OMP_PATH.read_bytes()
n_screens = struct.unpack_from('<I', d, 8)[0] // 256
target_max = n_screens - 1
print(f'OMP: {OMP_PATH.stem}  n_screens={n_screens}  target_max={target_max}')
print()

exe = EXE_PATH.read_bytes()
layer_size = W * H
layer0 = exe[CANDIDATE_OFFSET                   : CANDIDATE_OFFSET +   layer_size]
layer1 = exe[CANDIDATE_OFFSET +   layer_size    : CANDIDATE_OFFSET + 2*layer_size]
layer2 = exe[CANDIDATE_OFFSET + 2*layer_size    : CANDIDATE_OFFSET + 3*layer_size]

l0_max = max(layer0); l1_max = max(layer1); l2_max = max(layer2)
print(f'Layer 0 max = {l0_max}  (need {target_max} for CONFIRMED match)')
print(f'Layer 1 max = {l1_max}')
print(f'Layer 2 max = {l2_max}')
print()

print('Layer 0 grid (foreground -- top of stage first):')
for row in range(H):
    cells = layer0[row*W : (row+1)*W]
    print('  ' + '  '.join(f'{b:3d}' for b in cells))
"
```

**Interpreting the results:**

| `Layer 0 max` result      | Meaning                                                            |
| ------------------------- | ------------------------------------------------------------------ |
| Exactly `target_max`      | ✅ **Confirmed match** — this is almost certainly the right layout |
| Less than `target_max`    | 🟡 Plausible — stage may just not use all screens                  |
| Greater than `target_max` | ❌ Wrong region — look elsewhere                                   |

The grid should have `0` (empty) in obvious areas (e.g. the top rows for a tall vertical stage)
and increasing numbers toward the centre.

**Example of a good layer 0 grid** for a 5-column slice of a vertical stage:

```
  0    0    0    0    0
  0    0    0    0    0
  5   12   18    0    0
 23   24   25   26    0
 30   31   32   33   34
```

**Example of bad data** (coordinate/waypoint values, not a layout):

```
228  247    0    0  228  247    0    0
100   31    0    0  236  251    0    0
```

---

## Step 5 — Cross-check with `load_omp`

Once you believe you have the right offset and dimensions, check that every screen ID referenced
in the layout actually exists in the OMP:

```python
python -c "
import sys
sys.path.insert(0, '.')
from pathlib import Path
from utils.omp import load_omp, load_layout_from_exe

OMP_PATH = Path('PC/X5/stage/st021/st021.omp')   # <- your stage
EXE_PATH = Path('debug/RXC2.exe')
OFFSET   = 0x02D9A10E   # <- your candidate
W        = 10
H        = 24

omp = load_omp(OMP_PATH)
print(f'OMP n_screens = {omp.n_screens}  (valid screen IDs: 0 to {omp.n_screens-1})')

layout = load_layout_from_exe(EXE_PATH, offset=OFFSET, width=W, height=H, layer=0)

used_ids  = sorted(set(cell for row in layout.screens for cell in row))
max_used  = max(used_ids) if used_ids else 0
print(f'Layout uses screen IDs: {used_ids[:20]}{\"...\" if len(used_ids)>20 else \"\"}')
print(f'Max screen ID used: {max_used}')
print()

if max_used < omp.n_screens:
    print('OK: all referenced screen IDs exist in the OMP.')
else:
    print(f'BAD: layout references screen ID {max_used} but OMP only has {omp.n_screens} screens.')

non_empty = sum(1 for sid in used_ids if sid > 0 and any(omp.tiles[sid]))
print(f'Non-empty screens referenced: {non_empty} of {len(used_ids)-1} (excluding screen 0)')
"
```

If `max_used < omp.n_screens` and `non_empty` is a reasonable positive number, you have found
the match.

---

## Step 6 — Update `STAGE_LAYOUT` in `render_stage.py`

Open [render_stage.py](../render_stage.py) and find the `STAGE_LAYOUT` dict.

### Add (or update) the entry

Add the stage to the appropriate game sub-dict with an inline status tag. Use the
tag that matches your confidence — e.g. an exact max match → `CONFIRMED`, a partial
match → `UNCONFIRMED` (see the "STAGE_LAYOUT status codes" legend in
[render_stage.py](../render_stage.py)):

```python
"X5": {
    "st021": (0x02D9A10E, 10, 24),  # DONE
}
```

The inline tag is the source of truth for the stage's confidence; there is no
separate list to maintain.

### Test it

```
python render_stage.py PC\X5\stage\st021\st021.omp
```

If `st021_level.png` appears with recognisable level geometry (not a scrambled mess), the offset
is correct. The script prints the resolved `(offset=0x..  w=..  h=..)` on startup.

---

## Step 7 — When the stage isn't in block 1 at all

If the Python scan from Step 2 finds nothing, the stage's layout lives in a completely different
block — not the main block 1 region. This is the situation for:

- **st020, st040, st041, st050, st060, st070, st080, st170, st180, st220, staff_eng**

These OMP files have `n_screens` values (56, 79, 95, 106, 114, 118, 133, 141, 221, 222) that do
not appear anywhere in block 1 as valid `L0_max + 1` results. A separate undiscovered layout
block contains them.

Finding that block requires a broader search. The process is documented step-by-step in
[debug/find_size_table2.py](../debug/find_size_table2.py) (which documents how block 2, the boss
stage block, was found). The short version:

1. Pick an OMP. Note its `n_screens` as `N`.
2. Run the region scan (Step 2) with `min_len` lowered to 20 or fewer to catch smaller regions.
3. For each candidate region, check that its length factors as `W × H × 3` for realistic
   dimensions (W typically 5–25, H typically 18–30).
4. Look for a **size table** in the `.data` section (`0x02E79A00` onwards) that has a `(W, H)`
   entry whose cumulative sum of `3 × W × H` for preceding entries, added to the data block
   start address, lands exactly on your candidate offset.
5. If you find a consistent `(COPY_OFFSET, SIZE_TABLE_OFFSET)` pair, you have found the block.

This is exploratory work. The block 2 discovery notes in `find_size_table2.py` are the best
reference for how to approach it.
