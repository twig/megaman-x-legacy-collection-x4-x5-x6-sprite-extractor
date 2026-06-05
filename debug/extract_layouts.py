"""
Extract all stage layout tables from RXC2.exe (Mega Man X Legacy Collection 2 PC).

NOTE: All offsets and constants below are specific to Mega Man X5 in RXC2.exe.
X4 and X6 use different offsets within the same executable.

Confirmed parameters (X5 only):
  Size table:   file offset 0x02F0B7BD — byte pairs (w, h) per stage
  Layout data:  consecutive block starting at 0x02D98548 (.rdata section)
  Format:       each stage = 3 consecutive layers, each layer = w*h bytes

OMP verification:
  This block contains 21 data-bearing stages and 8 zero-dimension placeholders.
  4 stages confirmed by matching max(layer0) == OMP n_screens-1:
    idx  0 (15x24) -> st010
    idx  8 (5x29)  -> st030, st160
    idx 10 (5x29)  -> st061
    idx 13 (5x26)  -> st120
  17 stages are UNVERIFIED: their required n_screens values are not found in
  PC/X5/stage. They likely belong to a second layout block elsewhere in the exe
  (21 OMP files also have no match in this block).

Output:
  layouts/stXXX_wWWW_hHHH.bin   raw layout bytes (w*h*3), all 3 layers
  layouts/stXXX_wWWW_hHHH.csv   human-readable layer-0 grid (screen_ids)
  layouts/index.txt             summary of all stages found
"""

import struct
from pathlib import Path

EXE_PATH = Path("debug/RXC2.exe")
OUT_DIR  = Path("layouts")

# ── X5-specific constants ─────────────────────────────────────────────────────
# These offsets apply only to the X5 portion of RXC2.exe.
# X4 and X6 have their own separate layout blocks and size tables elsewhere.
COPY1_OFFSET     = 0x02D98548   # start of X5 packed layout data block (.rdata)
SIZE_TABLE_OFF   = 0x02F0B7BD   # X5 size table: byte pairs (w, h) per stage
MAX_STAGES       = 40           # upper bound; stop early if data looks invalid
MAX_SCREEN_ID    = 250          # rough plausibility upper bound for layer 0

# Stage indices confirmed against OMP files (max(layer0) == n_screens-1).
# All other data-bearing indices are UNVERIFIED against this OMP set.
CONFIRMED_OMP: dict[int, list[str]] = {
    0:  ["st010"],
    8:  ["st030", "st160"],
    10: ["st061"],
    13: ["st120"],
}

exe = Path(EXE_PATH).read_bytes()
print(f"Loaded {len(exe):,} bytes from {EXE_PATH}")

# ── Read size table ────────────────────────────────────────────────────────────
sizes: list[tuple[int, int]] = []
for i in range(MAX_STAGES):
    off = SIZE_TABLE_OFF + i * 2
    if off + 2 > len(exe):
        break
    w, h = exe[off], exe[off + 1]
    # Stop if we run into implausibly large values (signal we're past the table)
    if w > 100 or h > 100:
        print(f"  Size table ends at index {i} (w={w}, h={h} out of range)")
        break
    sizes.append((w, h))

print(f"\nSize table at 0x{SIZE_TABLE_OFF:08X}: {len(sizes)} entries")
for i, (w, h) in enumerate(sizes):
    print(f"  [{i:2d}]  w={w:3d}  h={h:3d}  layer_size={w*h:4d}")

# ── Compute cumulative offsets ─────────────────────────────────────────────────
stage_offsets: list[tuple[int, int, int, int]] = []  # (idx, offset, w, h)
pos = COPY1_OFFSET

for i, (w, h) in enumerate(sizes):
    layer_size = w * h
    total      = layer_size * 3
    if total == 0:
        # Zero-dimension stage: no layout data in the packed block
        stage_offsets.append((i, -1, w, h))
        continue
    stage_offsets.append((i, pos, w, h))
    pos += total

print(f"\nStage offsets (cumulative from 0x{COPY1_OFFSET:08X}):")
for idx, off, w, h in stage_offsets:
    if off == -1:
        print(f"  [st{idx:03d}]  (no layout — w={w} or h={h} is 0)")
    else:
        chunk16 = exe[off:off+16].hex()
        max_id  = max(exe[off:off+w*h]) if w*h > 0 else 0
        print(f"  [st{idx:03d}]  0x{off:08X}  w={w}  h={h}  "
              f"layer0_max={max_id:3d}  first16={chunk16}")

# ── Extract to files ───────────────────────────────────────────────────────────
OUT_DIR.mkdir(parents=True, exist_ok=True)
index_lines = ["stage_idx, file_offset_hex, width, height, layer_size, note"]
extracted = 0

for idx, off, w, h in stage_offsets:
    layer_size = w * h
    total      = layer_size * 3

    if off == -1 or total == 0:
        index_lines.append(f"st{idx:03d}, -, {w}, {h}, 0, no_layout")
        continue

    # Sanity check: layer 0 should have all values <= MAX_SCREEN_ID
    layer0 = exe[off : off + layer_size]
    layer0_max = max(layer0) if layer0 else 0
    if idx in CONFIRMED_OMP:
        note = "confirmed_" + "_".join(CONFIRMED_OMP[idx])
    elif layer0_max > MAX_SCREEN_ID:
        note = f"WARN_max={layer0_max}"
    else:
        note = "unverified"

    stem = f"st{idx:03d}_w{w:03d}_h{h:03d}"

    # Binary: all 3 layers
    bin_path = OUT_DIR / f"{stem}.bin"
    raw = exe[off : off + total]
    bin_path.write_bytes(raw)

    # CSV: layer 0 grid
    csv_path = OUT_DIR / f"{stem}_layer0.csv"
    with csv_path.open("w") as f:
        f.write(f"# stage={idx}  offset=0x{off:08X}  w={w}  h={h}\n")
        for sy in range(h):
            row = [layer0[sy * w + sx] for sx in range(w)]
            f.write(",".join(str(v) for v in row) + "\n")

    index_lines.append(f"st{idx:03d}, 0x{off:08X}, {w}, {h}, {layer_size}, {note}")
    extracted += 1

index_path = OUT_DIR / "index.txt"
index_path.write_text("\n".join(index_lines) + "\n")

print(f"\nExtracted {extracted} stages to {OUT_DIR}/")
print(f"Index written to {index_path}")
print("\nDone.")
