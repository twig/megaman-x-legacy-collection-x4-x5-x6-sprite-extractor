"""
Extract all X6 stage layout tables from RXC2.exe (Mega Man X Legacy Collection 2 PC).

NOTE: All offsets and constants below are specific to Mega Man X6 in RXC2.exe.
X4 and X5 use different offsets within the same executable.

Confirmed parameters (X6):
  Layout data: consecutive block starting at file offset 0x02DD4000 (.rdata section)
  Total size:  14160 bytes (confirmed by entropy analysis — vtable/RTTI data begins at
               block offset 14160)
  Stage count: 13 stages
  Stage width: 16 (all stages share the same w=16)
  Heights:     [28, 23, 33, 43, 18, 33, 43, 26, 7, 3, 1, 9, 28]
  Format:      each stage = 3 consecutive layers (layer0, layer1, layer2),
               each layer = w*h bytes

All 13 heights verified by OMP L0_max cross-validation:
  - Each stage's Layer 0 max ID exactly equals n_screens-1 from its OMP file
  - OMP mapping: [st00, st02, st04a, st06a, st0ca, stsel_eng, st0g,
                  st05x, st02x, st08x, st04x, st03x, st06x]
  - Sum constraint: 14160 = 3 * 16 * 295, sum(heights) = 295

Output:
  layouts_x6/stXXX_w016_hHHH.bin        raw layout bytes (w*h*3), all 3 layers
  layouts_x6/stXXX_w016_hHHH_layer0.csv  human-readable layer-0 grid (screen IDs)
  layouts_x6/index.txt                   summary of all stages
"""

from pathlib import Path

EXE_PATH = Path("debug/RXC2.exe")
OUT_DIR  = Path("layouts_x6")

# ── X6-specific constants ─────────────────────────────────────────────────────
BLOCK_OFFSET = 0x02DD4000      # file offset of X6 layout block start (.rdata)
W            = 16              # all X6 stages have width = 16
X6_HEIGHTS   = [28, 23, 33, 43, 18, 33, 43, 26, 7, 3, 1, 9, 28]
X6_OMP_FILES = [
    'st00', 'st02', 'st04a', 'st06a', 'st0ca',
    'stsel_eng', 'st0g', 'st05x', 'st02x', 'st08x', 'st04x', 'st03x', 'st06x',
]

exe = Path(EXE_PATH).read_bytes()
print(f"Loaded {len(exe):,} bytes from {EXE_PATH}")

# ── Compute stage offsets ──────────────────────────────────────────────────────
total_bytes = sum(3 * W * h for h in X6_HEIGHTS)
print(f"\nX6 block:   file offset 0x{BLOCK_OFFSET:08X}")
print(f"Stages:     {len(X6_HEIGHTS)}")
print(f"Width:      {W} (all stages)")
print(f"Heights:    {X6_HEIGHTS}")
print(f"Sum h:      {sum(X6_HEIGHTS)}")
print(f"Total data: {total_bytes} bytes")

print(f"\nStage offsets (from block start at 0x{BLOCK_OFFSET:08X}):")
print(f"  {'idx':>3}  {'file_offset':>12}  {'block_off':>9}  {'w':>3}  {'h':>3}  "
      f"{'layer_size':>10}  {'L0_max':>6}  {'first16'}")
print(f"  {'-'*3}  {'-'*12}  {'-'*9}  {'-'*3}  {'-'*3}  "
      f"{'-'*10}  {'-'*6}  {'-'*32}")

block_pos = 0
stage_table = []   # (idx, file_offset, block_offset, h, omp_name)

for i, (h, omp_name) in enumerate(zip(X6_HEIGHTS, X6_OMP_FILES)):
    layer_size = W * h
    file_off   = BLOCK_OFFSET + block_pos
    layer0     = exe[file_off : file_off + layer_size]
    l0_max     = max(layer0) if layer0 else 0
    first16    = exe[file_off : file_off + 16].hex()
    print(f"  [{i:3d}]  0x{file_off:08X}  {block_pos:9d}  {W:3d}  {h:3d}  "
          f"{layer_size:10d}  {l0_max:6d}  {omp_name:12s}  {first16}")
    stage_table.append((i, file_off, block_pos, h, omp_name))
    block_pos += 3 * layer_size

print(f"\n  Final block_pos: {block_pos} (expected {total_bytes}: "
      f"{'OK' if block_pos == total_bytes else 'MISMATCH'})")

# ── Extract to files ───────────────────────────────────────────────────────────
OUT_DIR.mkdir(parents=True, exist_ok=True)
index_lines = ["stage_idx, file_offset_hex, block_offset, width, height, layer_size, l0_max, omp_file"]

extracted = 0
for idx, file_off, block_off, h, omp_name in stage_table:
    layer_size = W * h
    total      = layer_size * 3

    layer0 = exe[file_off : file_off + layer_size]
    l0_max = max(layer0) if layer0 else 0

    stem = f"st{idx:03d}_w{W:03d}_h{h:03d}"

    # Binary: all 3 layers
    bin_path = OUT_DIR / f"{stem}.bin"
    raw = exe[file_off : file_off + total]
    bin_path.write_bytes(raw)

    # CSV: layer 0 grid
    csv_path = OUT_DIR / f"{stem}_layer0.csv"
    with csv_path.open("w") as f:
        f.write(f"# stage={idx}  offset=0x{file_off:08X}  block_off={block_off}  "
                f"w={W}  h={h}\n")
        for sy in range(h):
            row = [layer0[sy * W + sx] for sx in range(W)]
            f.write(",".join(str(v) for v in row) + "\n")

    index_lines.append(
        f"st{idx:03d}, 0x{file_off:08X}, {block_off}, {W}, {h}, {layer_size}, {l0_max}, {omp_name}"
    )
    extracted += 1

index_path = OUT_DIR / "index.txt"
index_path.write_text("\n".join(index_lines) + "\n")

print(f"\nExtracted {extracted} stages to {OUT_DIR}/")
print(f"Index written to {index_path}")
print("\nDone.")
