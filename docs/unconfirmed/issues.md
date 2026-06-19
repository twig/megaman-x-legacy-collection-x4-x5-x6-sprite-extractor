## Colour Scaling: Imprecise colour decoding

tehemanX4 uses `× 8` (left-shift 3) formula to expand 5-bit to 8-bit:

```csharp
byte R = (byte)(color % 32 * 8);  // same: 0-31 → 0-248
```

The accurate expansion `(v << 3) | (v >> 2)` maps 31 → 255. left-shift 3 produces 248 for pure white.

---

## Critical Difference: 8bpp CLUT Selection Per Pixel

This is the most significant divergence. In `Draw16xTile` (8bpp path):

```csharp
byte pixel = *(byte*)(bmpBackBuffer + sourceIndex + col);
int indexClut = clut + (pixel >> 4);   // upper nibble selects CLUT ROW
pixel &= 0xF;                           // lower nibble is color index within CLUT
```

The PSX 8bpp texture encodes **two pieces of data per byte**: the CLUT row offset in the upper nibble, and the palette index in the lower nibble. This allows different pixels in the same tile to reference different CLUT rows dynamically.

**Python `render_tex` does not do this:**

```python
colour_index = payload[pixel_index * 4 + 3]  # treats the whole byte as the colour index
final_index = clut_base * 16 + colour_index
```

It uses a single fixed `clut_base` for **all pixels**. If the PC TEX format carries the same CLUT-row-per-pixel encoding in the alpha channel (or even as the raw index value 0-255 rather than 0-15), any pixel whose upper nibble is non-zero would map to the wrong colour. The comment `a_index == r_index >> 4` suggests the stored value is already the final 4-bit index — but only if the PC format explicitly pre-limits it to 0-15. If any pixel has an alpha/index value > 15, the Python code will still use it as a direct index past the end of a single CLUT row, while the C# code would interpret the upper nibble as a CLUT row shift.

---

## Nibble Byte Ordering (4bpp)

C# calls `ConvertBmp` before storing pixels into `bmp[]`:

```csharp
// Swaps nibbles: PSX stores low nibble first, high nibble second
var n1 = (b[lc] & 0xF) << 4;
var n2 = (b[lc] >> 4) + n1;
b[lc] = (byte)n2;
```

Then in `Draw16xTile` 4bpp:

```csharp
if ((col & 1) == 1)
    pixel &= 0xF;    // odd col → low nibble (= original high nibble after swap)
else
    pixel >>= 4;     // even col → high nibble (= original low nibble after swap)
```

Net effect: PSX's low-nibble-first ordering is correctly reversed. The Python script avoids this entirely because the PC TEX format stores pixels as 4 bytes each (fully expanded RGBA), so no nibble packing exists.

---

## Transparency: Different Sentinel Behaviour

|              | Index 0                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------- |
| **Python**   | Explicit `(255, 0, 255, 0)` — magenta, fully transparent                                     |
| **C# (PSX)** | Writes whatever RGB is in `palette[clut + 64].Colors[0]` — typically black, no alpha channel |

The C# renderer has no alpha channel at all (writes to RGB `bmp[]`). On PSX, colour 0 in a CLUT is simply transparent by GPU convention (STP bit in the colour word), not by a sentinel value. If the PC COL files embed a non-black value at index 0, the Python will still treat it as transparent whereas the C# would render it.

---

## X6 page-10/11 tiles with `col` bit 6 set render with wrong CLUT

**Status:** PARTIALLY FIXED. The wrong *colour* is corrected for the bit-6 cols
(64/80/96) via `_stage_clut_row()` in utils/omp.py (see below). Still open: the
`col=48` "wrong tile" (wrong shape, not just palette) and the `col=0` page-11 case
(`pad` high-nibble 4, bit 6 clear) at st0g ~(1888,1296), which this remap does not
touch.

INVESTIGATION NOTE (2026-06): the "inverted shadow" colours on st03x/st04b/st05x.
Ground truth: screenshots/MegaManX6-BlazeHeatnix-SubStage.png shows st03x's
platforms as GREY/SILVER metallic with orange-rust accents over dark purple walls.
The baseline renders those platforms as SMOOTH dark NAVY (right shape/shading, wrong
hue) — that hue error is the "inverted shadow".

Confirmed facts:
  • These are page>=8 8bpp background tiles.  The baseline draws them via `col+64`
    into the main VRAM-snapshot CLUT (e.g. col=48 → row 112), which is a smooth but
    navy gradient.  Measured colours: baseline (0,8,33)/(0,8,41) (R=0, high B) vs
    reference greys (32,32,32)/(56,56,56)/(72,72,64) (R=G=B).  A pure channel
    swap/rotate does NOT relate the two — it is a different palette, not a transform.
  • REJECTED fix #1 — route to stage base CLUT row 64: produced high-detail *noise*
    (a non-smooth palette misapplied to coherent index data), worse than baseline.
    Every other static main-col row tried is likewise noise; only the col+64 snapshot
    rows form a smooth gradient (so the index data IS coherent — the geometry is right).
  • The real colours ARE present in the per-stage file PC/X6/col/stage/st03x/st03x.col
    (16 rows): rows 1/2/3/8 are the grey-metal gradient ((115,115,132)/(189,189,198)/
    (132,132,148)…) and rows 9/10 the orange rust ((173,132,33)/(255,231,123)),
    matching the reference; rows 4-6 are the purple wall ((148,0,140)/(115,0,107)/
    (74,0,66)).  So the colours are recoverable in principle.
  • REJECTED fix #2 — index st03x.col directly by the 8bpp pixel value
    (color = st03x.col[v]): renders bright magenta garbage.  The 16 rows are
    ANIMATION FRAMES, not a flat 256-colour CLUT, so the texture index → CLUT-entry
    mapping needs the X6 animated/chr256 palette ASSEMBLY logic (which st03x.col row
    composes a given tile's CLUT at a given frame).  This is the same unresolved root
    cause as the st02 ice-orb below; the renderer loads the file as `anim_col` but
    does not wire it to tiles.

Status: ROOT CAUSE + correct colour SOURCE located; the frame-assembly mapping is
unresolved.  Do NOT reintroduce the row-64 remap, and do NOT index st03x.col flatly.
The diagnostics live in experimental/diag_recover_clut.py / diag_clut_pollution.py /
diag_render_candidates.py.

**Fix applied (colour only):** `_stage_clut_row()` remaps high-nibble-4 tiles whose
col has bit 6 set to CLUT row `(col & 0x3F) + 64` instead of `col + 64`. The +0x40 in
col exactly cancels the +64 stage base, so e.g. `col=96 → row 96` — the same grey-teal
CLUT the surrounding `col=32` wall tiles use, replacing the garish blue band. Gated on
the high-nibble-4 + bit-6 combination, so ordinary bit-6 cols that already render
correctly (e.g. `col=112`, pad high-nibble 0) are untouched. Confirmed to match only
st0g placed tiles (cols 64/80/96; no X4/X5, no other X6 stage).

**Where:** X6 stages with high-nibble-4 pad tiles — most visibly `st0g` (Secret Lab 1),
also `st02`, `st04a`, `st04b`, `st06a`. Example st0g pixel regions: a blue band at
~(576-1599, 540-690) and a "wrong tile" patch at ~(2112-2207, 928-1055).

**Symptom:** certain page-10/11 (8bpp) tiles render the correct *shape* but the wrong
*palette* (e.g. a garish blue band where a grey-teal wall belongs); a few look like the
wrong tile entirely because the bad CLUT makes them unrecognisable.

**Diagnosis (confirmed):**
- These are genuine 8bpp tiles (pixel high-nibbles up to 3-5) and the texture routing is
  correct — forcing a different CLUT base just produces garbage, which confirms the base
  `col + 64` is right and the texture data spans those rows.
- The fault is in `normalize_x6_stage_palette()` (utils/palette.py): it relocates stage
  CLUTs `col+96 → col+64` (a fixed +32-row shift). This is correct for tiles whose CLUT
  lands in the working range (e.g. `col=32` → row 96 ← src 128; `col=112` → row 176 ←
  src 208), **but for `col` values with bit 6 set (64/80/96) the relocation source lands
  in rows 192+** — the "enemy bank" region — which does not hold the stage's real static
  colours in the shared `col0g_0x.col` VRAM dump. `col=48` (→ row 112 ← src 144) is the
  same family.
- These tiles were previously hidden by the old over-broad `pad & 0xF0` skip; correcting
  that skip (now `(pad & 0xF) > 0xB or (pad & 0xF0) == 0x10`, matching the editor) made
  them visible and exposed this pre-existing palette gap. The majority of high-nibble-4
  tiles (`col` 0/16/32) DO render correctly and fill real gaps, so the skip fix stands.

**Still open — st02 ice orb (`col=16`, NOT bit-6):** the frozen orb/core at
~(1168-1295, 688-767) and ~(1552-1679, 848-927) is `col=16` page-11 8bpp, so the bit-6
remap above does not touch it (CLUT base stays row 80). It should be blue ice with a red
centre (see user reference) but renders as a garbled icy-noisy blob. Confirmed NOT fixable
from the static COL files:
  - The orb uses the **full 16-row 8bpp gradient** (pixel high-nibbles 0-15 → rows 80-95),
    so the entire 16-row block must be coherent.
  - Rows 80-95 are green-sentinel (0,231,33) polluted in *every* st02 COL variant
    (col02_0x/0z/xx/xz), and the +32 relocation source (rows 112-127) is polluted too.
    The bright-green sentinel marks runtime animation placeholders — the orb is almost
    certainly a **runtime-animated palette** element whose static snapshot has no real
    colours. The per-stage `st02.col` (53 rows) is the animation export and would need
    correct CLUT-position mapping to drive it.
  This is the same root cause family but has no static-data fix; left visible as a known
  issue. Other `col=16` page-11 tiles in stages without animated cores render fine.

  **st02.col investigation (per-stage animated palette):** `PC/X6/col/stage/st02/st02.col`
  is 53 CLUT rows and DOES hold the orb's real colours — icy blue/white/cyan gradients plus
  pure-red (rows 4-7) and red-core+cyan-ice (rows 48-52) gradients, almost free of the
  green-sentinel pollution that wrecks `col02_0x.col` rows 80-95.  So the colours are
  recoverable in principle.  BUT st02.col is structured as animation *frames*, not a flat
  1:1 CLUT image: overlaying it linearly onto the animation CLUT region (row 0 → CLUT 64)
  renders the orb as a recognisable icy ring (big improvement over the garble) but with a
  white/cyan core instead of the red pulse, plus residual noise; no single linear overlay
  offset reproduces the reference.  A correct render needs the X6 animation-palette assembly
  logic — i.e. which st02.col rows compose the orb's 16-row 8bpp CLUT at a given frame — which
  is unresolved.  A naive linear overlay is NOT a safe fix: it would rewrite CLUT rows 64-116,
  which many other (non-orb) stage tiles read, risking broad regressions.  The renderer
  already loads this file as `anim_col` (render_stage.preload_related_files) but does not yet
  wire it to any tile; wiring it correctly is the open follow-up.

**Why the bit-6 case was fixable but others are not:** the bit-6 remap works because the
`col-0x40` offset happens to point at a real, coherent stage CLUT already present in the
file. The `col=48` "wrong tile" (st0g) and `col=16` "ice orb" (st02) cases have no such
coherent source row available — picking correct source rows would need ground-truth
references or per-stage COL/animation-palette resolution, and the palette docstring records
that the row-192+ relocation exception was *removed* to fix st07, so naive relocation
changes risk regressing other stages.

---

## Palette Array Offset (`+ 64`)

```csharp
buffer[destIndex] = palette[clut + 64].Colors[pixel].R;
```

The C# palette array has a fixed `+64` offset — the first 64 slots are reserved (likely for player/object CLUTs loaded separately). The Python reads the COL file as a flat list starting at index 0 with no such offset. This is fine as long as the right COL file is passed in, but it means the Python's `clut_base` maps 1:1 to the COL file rows, whereas the C# `clut` value is relative to a larger global palette array.
