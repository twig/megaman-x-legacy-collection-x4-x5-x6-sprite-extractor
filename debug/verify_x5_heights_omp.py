"""
Verify X5 extract_layouts.py stage indices against X5 OMP files.

For each stage with layout data, check whether max(layer0) == OMP n_screens - 1.
OMP format: magic OMP\0 (4 bytes), flags DWORD@4, n_screens*256 DWORD@8.

Each OMP screen occupies 512 bytes of data (confirmed: fsize = n_screens*512 + 12).
Screen IDs in layer-0 are 0-indexed (0 … n_screens-1).

"CONFIRMED"  = L0_max == n_screens-1 for a known OMP.
"UNVERIFIED" = no OMP with that n_screens found in PC/X5/stage; the stage may
               belong to a layout block not yet identified, or use a screen set
               whose OMP was not extracted.
"""

import struct
from pathlib import Path

EXE_PATH       = Path("debug/RXC2.exe")
OMP_DIR        = Path("PC/X5/stage")
COPY1_OFFSET   = 0x02D98548
SIZE_TABLE_OFF = 0x02F0B7BD
MAX_STAGES     = 40

exe = Path(EXE_PATH).read_bytes()

# ── Read OMP files → name: n_screens ─────────────────────────────────────────
omp_nscreens: dict[str, int] = {}
for omp_path in sorted(OMP_DIR.rglob("*.omp")):
    data = omp_path.read_bytes()
    if len(data) < 12 or data[:3] != b"OMP":
        print(f"SKIP {omp_path.name}: bad magic {data[:4].hex()}")
        continue
    raw = struct.unpack_from("<I", data, 8)[0]
    n_screens = raw // 256
    omp_nscreens[omp_path.stem] = n_screens

# ── Read size table ───────────────────────────────────────────────────────────
sizes: list[tuple[int, int]] = []
for i in range(MAX_STAGES):
    off = SIZE_TABLE_OFF + i * 2
    if off + 2 > len(exe):
        break
    w, h = exe[off], exe[off + 1]
    if w > 100 or h > 100:
        break
    sizes.append((w, h))

# ── Build reverse lookup: expected_l0_max → list of OMP names ─────────────────
l0max_to_omps: dict[int, list[str]] = {}
for name, n in omp_nscreens.items():
    key = n - 1
    l0max_to_omps.setdefault(key, []).append(name)

# ── Compare layout block against OMP ──────────────────────────────────────────
pos = COPY1_OFFSET
confirmed: list[tuple[int, str]]  = []   # (layout_idx, omp_name)
unverified: list[int]             = []   # layout_idx with no OMP match
matched_omp_names: set[str]       = set()

print(f"{'idx':>4}  {'offset':>10}  {'w':>3}  {'h':>3}  {'L0_max':>6}  {'status':<12}  omp_match / note")
print("-" * 85)

for i, (w, h) in enumerate(sizes):
    layer_size = w * h
    total      = layer_size * 3

    if total == 0:
        print(f"  {i:2d}   {'--':>10}  {w:3d}  {h:3d}  {'--':>6}  no_layout")
        continue

    layer0 = exe[pos : pos + layer_size]
    l0_max = max(layer0) if layer0 else 0

    matches = l0max_to_omps.get(l0_max, [])
    if matches:
        status    = "CONFIRMED"
        match_str = ", ".join(sorted(matches))
        confirmed.append((i, match_str))
        matched_omp_names.update(matches)
    else:
        status    = "UNVERIFIED"
        match_str = f"need n_screens={l0_max+1}, none found"
        unverified.append(i)

    print(f"  {i:2d}   0x{pos:08X}  {w:3d}  {h:3d}  {l0_max:6d}  {status:<12}  {match_str}")
    pos += total

# ── OMP files with no layout match ───────────────────────────────────────────
unmatched_omps = [(n, ns) for n, ns in sorted(omp_nscreens.items()) if n not in matched_omp_names]

# ── Summary ───────────────────────────────────────────────────────────────────
total_layout = sum(1 for w, h in sizes if w * h > 0)
print()
print("=" * 85)
print("SUMMARY")
print("=" * 85)
print(f"  Layout block : 0x{COPY1_OFFSET:08X}  size table at 0x{SIZE_TABLE_OFF:08X}")
print(f"  Stages in block : {total_layout} with data, {len(sizes)-total_layout} empty (zero dimension)")
print()
print(f"  CONFIRMED ({len(confirmed)} stages -- L0_max == n_screens-1):")
for idx, omp in confirmed:
    w, h = sizes[idx]
    print(f"    layout idx {idx:2d}  ({w}x{h})  ->  {omp}")
print()
print(f"  UNVERIFIED ({len(unverified)} stages -- no matching OMP found in PC/X5/stage):")
for idx in unverified:
    w, h = sizes[idx]
    ls   = w * h
    # recompute l0_max
    offset = COPY1_OFFSET + sum(3*ww*hh for ww, hh in sizes[:idx] if ww*hh > 0)
    l0m = max(exe[offset:offset+ls]) if ls else 0
    print(f"    layout idx {idx:2d}  ({w}x{h})  L0_max={l0m}  (need n_screens={l0m+1})")
print()
print(f"  OMP files with NO layout match ({len(unmatched_omps)} of {len(omp_nscreens)}):")
for name, ns in unmatched_omps:
    print(f"    {name:<20s}  n_screens={ns:4d}  (expected L0_max={ns-1})")
print()
if not unverified and not unmatched_omps:
    print("  ALL stages and OMP files matched OK.")
else:
    print("  NOTE: unverified layout stages and unmatched OMP files likely belong to")
    print("  a separate layout block not yet identified in the exe.")
