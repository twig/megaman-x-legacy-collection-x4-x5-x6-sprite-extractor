# PAT file format — per-object sprite animation data (X4/X5/X6, PC MMLC)
#
# A PAT bundles the animation frames for an object/enemy.  Each frame is built from
# one or more quads (16x16 sprite tiles), each referencing a tile in one of the
# object's TEX sheets.
#
# ============================================================
# Format (authoritative: TeheManX4_Editor `Sprite.cs`)
# ============================================================
#
# Header:
#   0x00  4   magic "PAT\0"
#   0x04  4   version (LE u32, = 3)
#   0x08  4   anim_count N (LE u32) — number of animations
#   0x0C  N*4 per-animation frame counts (LE u32 each)
#
# Frame table (the "sprite" data, per Sprite.cs GetFrame):
#   A run of 4-byte entries, one per frame:
#       u16 quad_count       number of quads in the frame
#       u16 quad_offset_div4 start of the frame's quads, in 4-byte units, relative
#                            to the table base
#   The quads then follow.  Frame i's quads are at  base + quad_offset_div4*4,
#   and run for quad_count quads.  The first frame's quad_offset_div4 equals the
#   number of frames (quads begin immediately after the table), and offsets are
#   cumulative — so the table is self-describing and can be located by that
#   signature.  Frames may SHARE quads (offsets can point back), so the quad
#   region is smaller than the sum of quad counts.
#
# Quad (4 bytes, per Sprite.cs):
#   byte 0 flags: bits[0:1] tpage (TEX sheet index), bits[2:3] clut (relative CLUT
#                 offset), bit6 flipH, bit7 flipV  (bits 4-5 unused/zero)
#   byte 1 tex:   tile index within the TEX sheet
#   byte 2 x:     signed s8 X offset from the sprite anchor
#   byte 3 y:     signed s8 Y offset from the sprite anchor
#
# CLUT: quad.clut is a *relative* offset; absolute_clut = ocl_entry.clut_base + quad.clut.
#
# ── Not (yet) decoded ────────────────────────────────────────────────────────────
# How each of the anim_count animations maps onto the frame table — i.e. the per-
# animation *sequence* of frame indices and any per-frame timing — is held in
# additional X5 tables that are not reverse-engineered here.  load_pat() therefore
# exposes the raw `frame_counts` plus the decoded `frames` (the unique frames the
# animations are built from).  Single-animation files (anim_count == 1) have
# len(frames) == frame_counts[0], so their frame list IS the animation in order.
#
# Earlier revisions of this module hardcoded the section offsets of obj00_00.pat;
# that approach crashed on other PATs (e.g. the tiny warning.pat).  This parser is
# header/signature-driven and works across all PC X4/X5 stage PATs.

import struct
from dataclasses import dataclass, field
from pathlib import Path

PAT_MAGIC = b"PAT\x00"
PAT_HEADER_SIZE = 12  # magic(4) + version(4) + anim_count(4)


@dataclass
class Quad:
    """A single sprite tile record from a PAT frame."""
    tpage: int       # texture page index → selects TEX sheet N
    clut: int        # relative CLUT offset (add to OCL clut_base for the absolute row)
    flip_h: bool     # horizontal mirror
    flip_v: bool     # vertical mirror
    tex: int         # tile index within the TEX sheet (0–255)
    x: int           # signed X offset from sprite anchor (pixels)
    y: int           # signed Y offset from sprite anchor (pixels)

    @classmethod
    def from_bytes(cls, b: bytes) -> "Quad":
        if len(b) < 4:
            raise ValueError(f"Need 4 bytes for a Quad, got {len(b)}")
        flags = b[0]
        return cls(
            tpage=flags & 0x03,
            clut=(flags >> 2) & 0x03,
            flip_h=bool(flags & 0x40),
            flip_v=bool(flags & 0x80),
            tex=b[1],
            x=struct.unpack_from("b", b, 2)[0],
            y=struct.unpack_from("b", b, 3)[0],
        )


@dataclass
class Frame:
    """One animation frame: an ordered list of quads (draw order)."""
    index: int
    quads: list[Quad] = field(default_factory=list)

    def bbox(self) -> tuple[int, int, int, int]:
        """(min_x, min_y, max_x+16, max_y+16) covering all 16x16 quads; (0,0,0,0) if empty."""
        if not self.quads:
            return (0, 0, 0, 0)
        xs = [q.x for q in self.quads]
        ys = [q.y for q in self.quads]
        return (min(xs), min(ys), max(xs) + 16, max(ys) + 16)


@dataclass
class PATData:
    """Parsed contents of a PAT animation file."""
    version: int
    anim_count: int
    frame_counts: list[int]   # per-animation frame counts (raw header values)
    frames: list[Frame]       # the unique frames the animations are built from
    frame_table_offset: int   # file offset of the located frame table

    @property
    def total_anim_frames(self) -> int:
        """Sum of per-animation frame counts (counts reused frames multiple times)."""
        return sum(self.frame_counts)


def _read_quads(data: bytes, base: int, off_div4: int, count: int) -> list[Quad]:
    start = base + off_div4 * 4
    return [Quad.from_bytes(data[start + i * 4: start + i * 4 + 4]) for i in range(count)]


def _table_at(data: bytes, base: int) -> tuple[int, list[int], list[int]] | None:
    """If a valid frame table starts at `base`, return (n_frames, counts, offs_div4).

    Validity follows Sprite.cs: entry 0's offset == n_frames (quads follow the
    table), offsets are cumulative, every quad is in-bounds, and quad flag bytes
    have the unused bits 4-5 clear.  Returns None otherwise.
    """
    n = len(data)
    if base + 4 > n:
        return None
    _c0, N = struct.unpack_from("<HH", data, base)
    if not (1 <= N <= 4096) or base + N * 4 > n:
        return None
    counts: list[int] = []
    offs: list[int] = []
    for i in range(N):
        c, o = struct.unpack_from("<HH", data, base + i * 4)
        if c < 1:
            return None
        if i == 0:
            if o != N:
                return None
        elif o != offs[-1] + counts[-1]:
            return None
        if base + o * 4 + c * 4 > n:
            return None
        counts.append(c)
        offs.append(o)
    # quad flag-byte sanity (bits 4-5 unused)
    for o, c in zip(offs, counts):
        q = base + o * 4
        for k in range(c):
            if data[q + k * 4] & 0x30:
                return None
    return N, counts, offs


def find_frame_table(data: bytes) -> tuple[int, list[int], list[int]]:
    """Locate the primary frame table — the valid table whose quad data extends
    furthest (the object's full frame set).  Returns (base, counts, offs_div4)."""
    best = None  # (quad_end, base, counts, offs)
    pos = PAT_HEADER_SIZE
    n = len(data)
    while pos < n - 4:
        res = _table_at(data, pos)
        if res is not None:
            N, counts, offs = res
            if N >= 2:  # ignore degenerate 1-entry tables (frequent false positives)
                quad_end = pos + (offs[-1] + counts[-1]) * 4
                if best is None or quad_end > best[0]:
                    best = (quad_end, pos, counts, offs)
        pos += 4
    if best is None:
        raise ValueError("No valid PAT frame table found")
    return best[1], best[2], best[3]


def load_pat(pat_path: Path) -> PATData:
    """Parse a PAT animation file into a PATData (header + decoded unique frames)."""
    if not pat_path.exists():
        raise FileNotFoundError(f"PAT file does not exist: {pat_path}")

    data = pat_path.read_bytes()
    if len(data) < PAT_HEADER_SIZE:
        raise ValueError(f"PAT file too small: {len(data)} bytes")
    if data[:4] != PAT_MAGIC:
        raise ValueError(f"Not a PAT file (bad magic): {data[:4]!r}")

    version, anim_count = struct.unpack_from("<II", data, 4)
    frame_counts = [
        struct.unpack_from("<I", data, PAT_HEADER_SIZE + i * 4)[0] for i in range(anim_count)
    ]

    base, counts, offs = find_frame_table(data)
    frames = [
        Frame(index=i, quads=_read_quads(data, base, offs[i], counts[i]))
        for i in range(len(counts))
    ]

    return PATData(
        version=version,
        anim_count=anim_count,
        frame_counts=frame_counts,
        frames=frames,
        frame_table_offset=base,
    )
