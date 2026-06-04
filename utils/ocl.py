# OCL file format — Object Colour Lookup table
#
# The OCL file is a per-stage flat array of 4-byte entries. Each entry encodes
# both the CLUT (palette row) assignment and the TEX tile coordinates for one
# tile slot in the stage. It is indexed directly by the u16 values stored in the
# OMP file (after stripping any flip flags).
#
# ============================================================
# OCL binary format (confirmed against st000.ocl, 15,120 bytes)
# ============================================================
#
#   Offset   Size    Content
#   ────────────────────────────────────────────────────────
#   0x0000   4 B     Magic: "OCL\x00"
#   0x0004   4 B     Version (LE u32 = 1)
#   0x0008   4 B     Entry count (LE u32; 3777 for st000)
#   0x000C   N×4 B   Entries (one per tile slot):
#
#   Per-entry byte layout (confirmed):
#     byte 0 – flags:   rendering group / variant selector
#                         0x00 = standard stage tile
#                         0x38 = alternate/hit-flash palette variant
#                         0x39 = animated palette group
#     byte 1 – col:     palette column; abs_clut = col + 64  (confirmed)
#     byte 2 – (named 'clut_base', legacy misnomer):
#                       TEX tile position encoding —
#                         cordX = byte2 & 0x0F   (low  nibble, tile column within page)
#                         cordY = (byte2 >> 4) & 0x0F  (high nibble, tile row within page)
#     byte 3 – (named 'pad', legacy misnomer):
#                       TEX page encoding —
#                         page  = byte3 & 0x0F
#                       Values observed: 0–5, 10, 11, 15, 16 (0x10), 255 (0xFF)
#                       page=16 (0x10→masked to 0) = player/sprite tiles
#                       page=255 = sentinel/unused entry
#
# ============================================================
# TEX tile coordinate formula (confirmed)
# ============================================================
#
#   Given an OclEntry e:
#     cordX = e.clut_base & 0x0F
#     cordY = (e.clut_base >> 4) & 0x0F
#     page  = e.pad & 0x0F
#
#     gx = (page % 8) * 256 + cordX * 16   # pixel X of tile top-left in TEX
#     gy = (page // 8) * 256 + cordY * 16   # pixel Y of tile top-left in TEX
#
#   tex_x (tile column in TEX) = page * 16 + cordX
#   tex_y (tile row    in TEX) = cordY
#
# ============================================================
# CLUT formula (confirmed)
# ============================================================
#
#   abs_clut = e.col + 64
#
#   Confirmed against omp-to-expected-tiles.csv cross-check:
#     OCL[1092]: col=3  → abs_clut=67  ✓
#     OCL[715]:  col=26 → abs_clut=90  ✓
#     OCL[1371]: col=4  → abs_clut=68  ✓
#
# ============================================================
# Field name note
# ============================================================
#
#   The OclEntry field names 'clut_base' and 'pad' are legacy misnomers
#   inherited from early reverse engineering. They are kept unchanged to avoid
#   breaking existing callers. See byte layout above for their actual meaning.
#
# ============================================================
# CHR companion files (context only — not OCL format)
# ============================================================
#
#   PC/X5/chr/stage/ per-enemy directory contains:
#     obj00_0a.ctex   — CTEX manifest ("CTEX\x00"); links numbered .tex files
#     obj00_0a_N.cof  — COF colour-offset file ("COF\x00"); TEX path + checksum
#                       CLUT assignments are NOT in .cof; they live in OCL.
#
# ============================================================

import struct
from dataclasses import dataclass
from pathlib import Path

OCL_MAGIC = b"OCL\x00"
OCL_HEADER_SIZE = 12  # magic(4) + version(4) + entry_count(4)
OCL_ENTRY_SIZE = 4


@dataclass
class OclEntry:
    flags: int      # byte 0: rendering group / variant selector
                    #   0x00 = standard stage tile
                    #   0x38 = alternate/hit-flash palette variant
                    #   0x39 = animated palette group
    col: int        # byte 1: palette column; abs_clut = col + 64  (confirmed)
    clut_base: int  # byte 2: TEX tile coords (legacy field name — NOT a CLUT index)
                    #   cordX = clut_base & 0x0F
                    #   cordY = (clut_base >> 4) & 0x0F
    pad: int        # byte 3: TEX page (legacy field name — NOT padding)
                    #   page = pad & 0x0F

    def abs_clut_stage(self) -> int:
        """
        Return the absolute CLUT row index for this stage tile entry.
        Formula confirmed against omp-to-expected-tiles.csv: abs_clut = col + 64.
        """
        return self.col + 64

    def absolute_clut(self, relative_clut: int = 0) -> int:
        """
        Deprecated — the original model (clut_base + relative_clut) was based on
        an unconfirmed PAT/object CLUT theory that contradicts binary evidence.
        Use abs_clut_stage() for stage tile CLUT resolution.
        """
        return self.abs_clut_stage()


def load_ocl(ocl_path: Path) -> list[OclEntry]:
    if not ocl_path.exists():
        raise FileNotFoundError(f"OCL file does not exist: {ocl_path}")

    data = ocl_path.read_bytes()

    if len(data) < OCL_HEADER_SIZE:
        raise ValueError(f"OCL file too small: {len(data)} bytes")

    if data[:4] != OCL_MAGIC:
        raise ValueError(f"Not an OCL file: {data[:4]!r}")

    _version = struct.unpack_from("<I", data, 4)[0]
    entry_count = struct.unpack_from("<I", data, 8)[0]

    expected_size = OCL_HEADER_SIZE + entry_count * OCL_ENTRY_SIZE
    if len(data) < expected_size:
        raise ValueError(
            f"OCL entry count {entry_count} exceeds file size "
            f"(expected {expected_size} bytes, got {len(data)})"
        )

    entries: list[OclEntry] = []
    for i in range(entry_count):
        offset = OCL_HEADER_SIZE + i * OCL_ENTRY_SIZE
        flags, col, clut_base, pad = data[offset : offset + OCL_ENTRY_SIZE]
        entries.append(OclEntry(flags=flags, col=col, clut_base=clut_base, pad=pad))

    return entries


def get_absolute_clut(entries: list[OclEntry], ocl_index: int) -> int:
    """
    Return the absolute CLUT row index for the stage tile at ocl_index.
    Formula: entries[ocl_index].col + 64  (confirmed against omp-to-expected-tiles.csv).
    """
    if not (0 <= ocl_index < len(entries)):
        raise IndexError(f"ocl_index {ocl_index} out of range (table has {len(entries)} entries)")
    return entries[ocl_index].abs_clut_stage()
