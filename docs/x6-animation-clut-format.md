# RXC2.exe clut-animation tables (X5/X6) — reverse engineering notes

Goal: colour the animated-crystal tiles (OCL `tile_type == 0x39`) correctly by
loading the per-stage animated COL's **frame-0** CLUTs into the static palette at
the slots the game animates. This is the data needed to do that.

## Format (confirmed from TeheManX4_Editor `AnimeEditor.xaml.cs`)

The PSX engine (mirrored by the PC port) drives clut animation from two per-stage
pointer tables + the animated COL:

- **Animated COL** (`col/stage/{stage}/{stage}.col`) = the "clut buffer": a flat
  array of 16-colour CLUTs (32 bytes each). `n_sets = filesize_colours / 16`.
  e.g. `st0h.col` = 29 sets.
- **ClutInfoPointers[stage]** → an _anime-pointer array_ of `n` entries (one per
  anime). Entry `a` → a list of `[set, timer]` byte-pairs (the animation frames).
  `set` indexes the COL; `timer` is the frame duration.
- **ClutDestPointers[stage]** → a `[dest, length]` byte array (one pair per anime):
  `dest` = destination CLUT row in the stage palette, `length` = number of CLUTs.

**Still render (frame 0):** for each anime, take its first frame's `set` (= `set0`)
and copy `length` CLUTs: `palette[dest + i] = COL[set0 + i]` for `i in 0..length`.
The crystal tiles then render via the normal `col+64` lookup, because the animes
write into the `col+64` range (dests observed at 64–92 = the crystal abs_clut slots).

## Located in RXC2.exe (PE32, ImageBase 0x400000)

File↔VA: `.rdata` VA = file + 0x400e00; `.data` VA = file + 0x401600.

- **Clut-anime data block**: file ~`0x02f0a000`–`0x02f0e000` (.data), right beside
  the layout size tables (`SIZE_TABLE_OFF = 0x02F0B7BD`). Contains the `[set,timer]`
  frame data, the `[dest,length]` dest arrays, and the per-anime pointer arrays.
- **ClutInfoPointers** (per-stage → anime-pointer array): file ~`0x03014658`+
  (VA ~`0x3415c58`). Sparse (null for stages with no clut anime). Confirmed entries
  point to anime arrays e.g. VA `0x330c0d8` (22 animes), `0x330c5e8` (24), etc.
- **Dest array** for a stage sits immediately _before_ its anime-pointer array:
  `dest_va = info_va - 2*n`. Verified: dest `0x330c0ac` + 22·2 = info `0x330c0d8`.

14 anime-pointer arrays were recovered (see `experimental/extract_clut_anime.py`).
Example (info @ file 0x2f0aad8, 22 animes, all length 1):
`dests = [71,78,78,64,76,77,73,72,74,75,65,66,68,79,80,70,67,69,64,78,70,127]`,
`set0 = [4,10,16,21,23,28,32,36,42,47,51,59,67,71,73,75,77,82,87,93,102,104]`.

## General extractor

`extract_animation_clut.py` (repo root) derives every clut-anime definition from
RXC2.exe for X5+X6 — no hard-coded per-stage addresses. It:

- parses the PE, auto-locates the **ClutInfoPointers** table (the densest .data run
  of pointers-to-anime-arrays) and reads the parallel **ClutDestPointers** entry at
  `info_entry − 0xb8`;
- decodes each stage's animes: `(dest, length, set0, full frames)`, with the anime
  count validated against the dest array;
- suggests the owning animated COL by CLUT-count.

```
python extract_animation_clut.py                 # readable dump (19 stages)
python extract_animation_clut.py --json out.json # machine-readable
python extract_animation_clut.py --stage st0h    # filter by COL-name candidate
```

Per anime, the still-image CLUT is `COL[set0 .. set0+length]` → `palette[dest ..]`.

**Caveat (open):** the exact `clut_index → stage-name` map isn't pinned. COL-size
candidates collide (st0g/st0h both 29; X5/X6 overlap), and dest slots are a
contiguous block that only partially lines up with a stage's scattered crystal
`col+64` values — so association is currently a hint, confirmed by rendering. The
decoded definitions themselves are solid (clean ping-pong/cycle frame data).

## Remaining work to wire it up

1. **Clean the per-anime decode**: trailing animes sometimes read past the real
   dest array (lengths come out as 0xF8/0xFA = garbage); the true anime count per
   stage is shorter than the pointer-array slot count. Bound the dest array properly
   (likely a terminator or the `MaxClutAnimes`-equivalent count).
2. **Map arrays → X6 stages**: determine the ClutInfoPointers table base / stage
   index (the X6 asset order is at file 0x2dd1bf8: st00,st01,st01x,…,st0g,st0h,st0i,
   stsel). RXC2 is X5+X6 combined, so confirm which index block is X6.
3. **Integrate**: in `preload_related_files`, after building `stage_palette`, apply
   frame-0 of each anime (`palette[dest+i] = anim_col[set0+i]`) for the X6 stage,
   then keep the normal `col+64` render path. Gate to the stage's own table entry so
   only its animated slots change.
4. **Validate**: render all X6 stages vs baseline; only animated-crystal slots
   should change, and st0h's crystals should match the game.

Tooling: `experimental/find_clut_tables.py` (locate tables),
`experimental/extract_clut_anime.py` (decode per-stage anime defs),
`experimental/decode_clut_animes.py`, `experimental/diag_anim_correlate.py`.
