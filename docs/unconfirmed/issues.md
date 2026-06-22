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

## X6 animated-palette cores not rendered (st02 ice orb, crystals)

A few X6 page>=8 8bpp elements use a runtime-ANIMATED palette, so no single static CLUT
renders them correctly. (Static page>=8 CLUT sourcing itself is handled — raw col+96, see
`normalize_x6_stage_palette` and `render_stage.x6_page8_palette`; this issue is only the
animated cores.)

Example: st02's frozen ice orb (`col=16` page-11 8bpp, ~(1168,688) and ~(1552,848)) renders
as an icy-noisy blob. Its real colours live in `PC/X6/col/stage/st02/st02.col` (53 rows —
icy blue/white/cyan plus a red core) but stored as animation FRAMES, not a flat CLUT;
correct rendering needs the X6 animation-palette assembly (which frame composes a tile's
16-row CLUT at a given moment). `render_stage` loads the file as `anim_col` but does not
wire it to tiles.

Why it is left unwired: a naive linear overlay would rewrite CLUT rows that many other
(non-orb) tiles also read, risking broad regressions — so it needs the real per-frame
assembly logic, not a blanket overlay.

---

## Palette Array Offset (`+ 64`)

```csharp
buffer[destIndex] = palette[clut + 64].Colors[pixel].R;
```

The C# palette array has a fixed `+64` offset — the first 64 slots are reserved (likely for player/object CLUTs loaded separately). The Python reads the COL file as a flat list starting at index 0 with no such offset. This is fine as long as the right COL file is passed in, but it means the Python's `clut_base` maps 1:1 to the COL file rows, whereas the C# `clut` value is relative to a larger global palette array.
