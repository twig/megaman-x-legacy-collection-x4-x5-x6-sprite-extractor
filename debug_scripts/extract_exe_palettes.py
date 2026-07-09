"""
Extract a whole palette section from RXC2.exe into COL files.

The colours for the X5 "WARNING" (health-advisory) screen are not in any asset file;
they live in RXC2.exe as a small block of 16-colour BGR555 CLUTs.  That block is a
self-contained SECTION of NINE palettes (only two of which are the WARNING pair — the
rest are other screen/effect palettes that share the block: grayscale, gold, fire, blue,
etc.).  The palettes are recognisable: most colours carry the PSX STP (bit-15) flag, and
the section is bounded on both sides by all-zero padding rows.  This script extracts ALL
nine, not just the WARNING ones.

To survive an EXE update (which would move the data to a different offset), nothing here
is hard-coded to an absolute address.  Instead:

  1. ANCHOR BY CONTENT — search the whole EXE for the 32-byte warm-red WARNING CLUT
     (BASE_SIG); it is highly distinctive and serves only to locate the section.
  2. EXPAND TO SECTION — from each anchor, walk outward in 32-byte (one-CLUT) steps
     while the row still looks like a palette (clut_run), stopping at the padding rows.
  3. PICK THE LARGEST SECTION — the signature appears more than once (a duplicate block);
     keep the run with the most CLUTs (the canonical 9-CLUT section).

Outputs (into --out-dir):
  * section.col       — all N palettes in one COL (feed to extract_warning.py --palette)
  * palette_NN.col    — each palette on its own
  * preview.png       — a labelled grid of every palette row
CLUTs are copied verbatim (raw BGR555 bytes, STP bits preserved); the COL header is the
standard b"COL\\0" + reserved + colour count, so they load with load_col_palettes.

Usage:
    python extract_warning_palette.py                       # -> scrapbook/warning/exe_palettes/
    python extract_warning_palette.py --exe PC/RXC2.exe --out-dir out/
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.consts import EXE_PATH_LC2
from utils.palette import load_col_palettes
from utils.debug import debug_palette_png

# 32-byte BGR555 signature: the WARNING warm-red base CLUT (clut 0, the Alia
# illustration palette).  Derived once from RXC2.exe; used only as a content anchor, so
# if the EXE is repacked the block is re-found at its new offset.  If the palette bytes
# themselves ever change, the search fails loudly rather than reading a wrong address.
BASE_SIG = bytes([
    0x00, 0x00, 0x42, 0x88, 0x88, 0x90, 0xcc, 0x98, 0x10, 0xa1, 0x52, 0xa1, 0x54, 0xa9,
    0x54, 0xa9, 0x94, 0xb1, 0x96, 0xb1, 0xd6, 0xb9, 0xd6, 0xb9, 0x16, 0xc2, 0x98, 0xd2,
    0x1a, 0xe3, 0x9e, 0xf3,
])

CLUT_BYTES = 32            # 16 colours * 2 bytes (BGR555)
IMAGE_BASE = 0x400000      # PE32 ImageBase, for reporting VAs only

COL_MAGIC = b"COL\x00"


def is_palette_row(data: bytes, off: int) -> bool:
    """A 32-byte row that looks like one of these CLUTs: not all-zero, and most colours
    carry the STP (bit-15) flag — the consistent signature of this palette block.  (We do
    NOT require index 0 == 0, so a section may include the odd non-transparent-0 CLUT.)"""
    if off < 0 or off + CLUT_BYTES > len(data):
        return False
    words = struct.unpack_from("<16H", data, off)
    if not any(words):
        return False  # all-zero padding row
    stp = sum(1 for w in words if w & 0x8000)
    return stp >= 10


def clut_run(data: bytes, anchor: int) -> tuple[int, int]:
    """Expand from an anchor CLUT outward over consecutive palette rows; return
    (start_off, n_cluts).  Stops at the first non-palette row (padding / other data) in
    each direction."""
    start = anchor
    while is_palette_row(data, start - CLUT_BYTES):
        start -= CLUT_BYTES
    end = anchor
    while is_palette_row(data, end + CLUT_BYTES):
        end += CLUT_BYTES
    return start, (end - start) // CLUT_BYTES + 1


def find_sections(data: bytes) -> list[tuple[int, int]]:
    """All distinct palette sections anchored by BASE_SIG, as (start_off, n_cluts),
    sorted largest-first."""
    sections: dict[int, int] = {}
    pos = data.find(BASE_SIG)
    while pos != -1:
        start, n = clut_run(data, pos)
        sections[start] = n            # dedupe overlapping anchors by section start
        pos = data.find(BASE_SIG, pos + 1)
    return sorted(sections.items(), key=lambda kv: -kv[1])


def file_off_to_va(exe: bytes, off: int) -> int | None:
    """Best-effort PE32 file-offset -> virtual address (for reporting only)."""
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    coff = pe + 4
    nsec = struct.unpack_from("<H", exe, coff + 2)[0]
    optsz = struct.unpack_from("<H", exe, coff + 16)[0]
    opt = coff + 20
    for i in range(nsec):
        s = opt + optsz + i * 40
        _vsz, va, rsz, roff = struct.unpack_from("<IIII", exe, s + 8)
        if roff <= off < roff + rsz:
            return IMAGE_BASE + va + (off - roff)
    return None


def write_col(path: Path, clut_bytes: bytes) -> int:
    """Write a COL file: header (magic + reserved + colour count) then the raw BGR555
    colour data.  Returns the colour count."""
    n_colours = len(clut_bytes) // 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(COL_MAGIC)
        f.write(struct.pack("<I", 0))          # reserved
        f.write(struct.pack("<I", n_colours))  # colour count
        f.write(clut_bytes)
    return n_colours


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", type=Path, default=EXE_PATH_LC2)
    ap.add_argument("--out-dir", type=Path, default=Path("scrapbook/warning/exe_palettes"))
    args = ap.parse_args()

    exe = args.exe.read_bytes()
    sections = find_sections(exe)
    if not sections:
        raise SystemExit(
            f"WARNING base palette signature not found in {args.exe} — the EXE may have "
            "changed the palette bytes; re-derive BASE_SIG."
        )

    start, n = sections[0]  # largest section
    va = file_off_to_va(exe, start)
    va_str = f"0x{va:08x}" if va is not None else "?"
    print(f"found {len(sections)} section(s) anchored by BASE_SIG; "
          f"using largest: {n} CLUTs @ file 0x{start:08x} (VA {va_str})")
    for s, m in sections[1:]:
        print(f"  (other section: {m} CLUTs @ file 0x{s:08x})")

    clut_bytes = exe[start: start + n * CLUT_BYTES]
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) all palettes in one COL (feed to extract_warning.py --palette)
    write_col(out_dir / "section.col", clut_bytes)
    # # 2) each palette on its own
    # for r in range(n):
    #     write_col(out_dir / f"palette_{r:02d}.col", clut_bytes[r * CLUT_BYTES:(r + 1) * CLUT_BYTES])
    # 3) labelled preview grid of every row
    pal = load_col_palettes(out_dir / "section.col")
    debug_palette_png(pal, out_dir / "preview.png", skip_trailing_blacks=False)

    # The WARNING pair (red illustration + white text) is the BASE_SIG row and its successor.
    base_idx = (exe.find(BASE_SIG, start) - start) // CLUT_BYTES
    print(f"wrote {n} palettes to {out_dir}/ : section.col + palette_00..{n - 1:02d}.col + preview.png")
    print("  per-row first/last colour:")
    for r in range(n):
        row = pal[r * 16:r * 16 + 16]
        tag = "  <-- WARNING illustration" if r == base_idx else \
              "  <-- WARNING text" if r == base_idx + 1 else ""
        print(f"    row {r}: {row[0][:3]} .. {row[-1][:3]}{tag}")


if __name__ == "__main__":
    main()
