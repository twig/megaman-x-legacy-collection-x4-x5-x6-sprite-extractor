# PAT file format — Per-object sprite animation data
#
# The PAT file encodes all animation frames for a given enemy/object type.
# Each animation frame is built from one or more quads (sprite tiles), each
# referencing a tile within one of the object's TEX texture sheets.
#
# ============================================================
# PAT file structure + CLUT mapping analysis
# (obj00_00.pat — Bee Blader enemy, 24736 bytes total)
# ============================================================
#
# Section layout:
#
#   Offset      Size     Content
#   ─────────────────────────────────────────────────────────────────────────
#   0x0000      4 B      Magic: "PAT\x00"
#   0x0004      4 B      Version (LE u32 = 3)
#   0x0008      4 B      Animation count N (LE u32 = 10)
#   0x000C      N×4 B    Per-animation frame counts (LE u32 each)
#                          e.g. [84, 45, 29, 4, 4, 4, 3, 32, 33, 38]
#                          → total animation frames = 276
#   0x0034      115×4 B  Unique frame definitions: quad count per unique frame
#                          (LE u32 each). 115 entries × avg 8.35 quads = 960 quads.
#                          Cumulative sum gives the quad-array offset for each frame.
#                          NOTE: Only covers 960 of the 5486 total quads in the file;
#                          the remaining 4526 quads serve additional animation variants
#                          referenced via the frame sequence table (section below).
#   0x0200      227×4 B  Frame timing table: per-animation-frame display duration
#                          in game ticks (LE u32 each, values typically 1–96).
#   0x058C      343×4 B  Frame sequence table: (count: u16, start: u16) pairs.
#                          Each pair defines a contiguous window of animation frames.
#                          'count' = number of frames in the window.
#                          'start' = starting frame index within the animation frame
#                          reference space (cumulative, matches per-anim frame counts).
#                          Relationship between pairs and the 10 named animations:
#                            anim[0]: implicit (count=84, start=0)
#                            anim[1]: pair (45, 84)    = frame_counts[1], cumsum[0]
#                            anim[2]: pair (29, 129)   = frame_counts[2], cumsum[0:2]
#                            anim[3]: pair (4,  158)   = frame_counts[3], cumsum[0:3]
#                            ... and so on for all 10 animations.
#                          The table continues with 333 additional entries for
#                          sub-animations, hit-flash variants, etc.
#   0x0AE8      5486×4 B Quad data: packed 4-byte sprite tile records (see below).
#   0x60A0      —        End of file.
#
# ============================================================
# Quad data format (4 bytes per quad)
# ============================================================
#
#   byte 0 – flags:
#     bits[0:1]  tpage     texture page index → selects obj00_0a_N.tex (N = tpage)
#     bits[2:3]  clut      relative CLUT offset (0–3); resolve via OCL entry:
#                            absolute_clut = ocl_entry.clut_base + quad.clut
#     bit  4     (unused, must be 0)
#     bit  5     (unused, must be 0)
#     bit  6     flipH     horizontal mirror flag
#     bit  7     flipV     vertical mirror flag
#   byte 1 – tex:   tile index within the selected TEX texture sheet (0x00–0xFF)
#   byte 2 – x:     signed s8, X pixel offset from sprite anchor point
#   byte 3 – y:     signed s8, Y pixel offset from sprite anchor point
#
# ============================================================
# CLUT mapping flow
# ============================================================
#
#   The 2-bit 'clut' field in quad.flags is a *relative* offset.
#   The *absolute* CLUT index is resolved via the stage OCL table (see utils/ocl.py):
#
#     absolute_clut = ocl_entry.clut_base + quad.clut
#
#   Example — Bee Blader (obj00_0a), stage st000:
#     OCL entry 39: flags=0x38, col=8, clut_base=28
#       quad.clut=0 → CLUT 28   (primary body)
#       quad.clut=1 → CLUT 29
#       quad.clut=2 → CLUT 30
#       quad.clut=3 → CLUT 31
#     CLUTs 32–35 (col=8 total) are used for colour variants such as hit-flash,
#     referenced by a separate OCL entry that shares the same clut_base+4 offset.
#
# ============================================================

import struct
from dataclasses import dataclass, field
from pathlib import Path

PAT_MAGIC = b"PAT\x00"
PAT_HEADER_SIZE = 12  # magic(4) + version(4) + anim_count(4)


@dataclass
class Quad:
    """A single sprite tile record from the PAT quad data section."""
    tpage: int       # texture page index (0–3) → selects obj00_0a_N.tex
    clut: int        # relative CLUT offset (0–3); add to OCL clut_base for absolute index
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
        tpage = flags & 0x03
        clut = (flags >> 2) & 0x03
        flip_h = bool(flags & 0x40)
        flip_v = bool(flags & 0x80)
        tex = b[1]
        x = struct.unpack_from("b", bytes([b[2]]))[0]
        y = struct.unpack_from("b", bytes([b[3]]))[0]
        return cls(tpage=tpage, clut=clut, flip_h=flip_h, flip_v=flip_v, tex=tex, x=x, y=y)


@dataclass
class UniqueFrame:
    """
    A unique frame pattern from section A — a named set of quads that can be
    referenced by multiple animation steps.
    """
    index: int           # 0-based index into the unique frame table (section A)
    quad_offset: int     # absolute index of the first quad in the quad data array
    quads: list[Quad]    # all quads for this frame, in draw order


@dataclass
class SequencePair:
    """
    An entry from the frame sequence table — a contiguous window of animation frames.
    The 'start' value is a cumulative frame index matching the per-animation frame
    count totals. Animation 0 is implicit (start=0, count=frame_counts[0]).
    """
    count: int   # number of frames in this window
    start: int   # starting cumulative frame index


@dataclass
class PATData:
    """Parsed contents of a PAT animation file."""
    version: int
    anim_count: int
    frame_counts: list[int]          # per-animation frame counts, len = anim_count
    unique_frame_quad_counts: list[int]  # quad count for each of the 115 unique frames
    timing_values: list[int]         # per-step display durations in game ticks
    sequence_pairs: list[SequencePair]
    quads: list[Quad]                # flat quad array, all 5486 quads

    @property
    def total_frames(self) -> int:
        return sum(self.frame_counts)

    def get_unique_frames(self) -> list[UniqueFrame]:
        """
        Build UniqueFrame objects for each entry in section A (115 unique frames).
        Each UniqueFrame contains the quads for that frame pattern.
        """
        frames: list[UniqueFrame] = []
        offset = 0
        for i, qcount in enumerate(self.unique_frame_quad_counts):
            frame_quads = self.quads[offset : offset + qcount]
            frames.append(UniqueFrame(index=i, quad_offset=offset, quads=frame_quads))
            offset += qcount
        return frames

    def get_animation_sequence(self, anim_index: int) -> list[SequencePair]:
        """
        Return the sequence pairs that belong to the given animation index.

        Animation 0 is implicit in the file (its frames begin at frame step 0).
        Animations 1–N are listed consecutively at the start of the sequence table,
        followed by sub-animation and variant entries.
        """
        if not (0 <= anim_index < self.anim_count):
            raise IndexError(
                f"anim_index {anim_index} out of range (file has {self.anim_count} animations)"
            )
        if anim_index == 0:
            # Animation 0 is implicit: it occupies frame steps 0 to frame_counts[0]-1.
            return [SequencePair(count=self.frame_counts[0], start=0)]
        # Animations 1..N are explicitly listed in sequence_pairs[0..N-2].
        return [self.sequence_pairs[anim_index - 1]]


# ── Section boundary constants (obj00_00.pat, verified empirically) ──────────

_HEADER_SIZE = PAT_HEADER_SIZE                  # 0x0000 – 0x000B
_SECTION_A_START = 0x0034                       # after anim_count + frame_counts
_SECTION_TIMING_START = 0x0200
_SECTION_SEQUENCE_START = 0x058C
_SECTION_QUAD_START = 0x0AE8

_N_UNIQUE_FRAMES = 115
_N_TIMING_ENTRIES = 227
_N_SEQUENCE_PAIRS = 343


def load_pat(pat_path: Path) -> PATData:
    """
    Parse a PAT animation file and return a fully decoded PATData object.

    Section boundaries are derived from the header values where possible.
    The unique frame count (115), timing entry count (227), and sequence pair
    count (343) are computed from the known section offsets of the reference
    file; these are expected to vary between different PAT files.
    """
    if not pat_path.exists():
        raise FileNotFoundError(f"PAT file does not exist: {pat_path}")

    data = pat_path.read_bytes()

    if len(data) < PAT_HEADER_SIZE:
        raise ValueError(f"PAT file too small: {len(data)} bytes")

    if data[:4] != PAT_MAGIC:
        raise ValueError(f"Not a PAT file (bad magic): {data[:4]!r}")

    version = struct.unpack_from("<I", data, 4)[0]
    anim_count = struct.unpack_from("<I", data, 8)[0]

    # Per-animation frame counts immediately follow the header.
    frame_counts_offset = PAT_HEADER_SIZE
    frame_counts = [
        struct.unpack_from("<I", data, frame_counts_offset + i * 4)[0]
        for i in range(anim_count)
    ]

    # Section A: unique frame quad counts.
    # Starts after the per-anim frame counts; ends at 0x0200.
    section_a_start = frame_counts_offset + anim_count * 4
    section_a_end = _SECTION_TIMING_START
    n_unique_frames = (section_a_end - section_a_start) // 4
    unique_frame_quad_counts = [
        struct.unpack_from("<I", data, section_a_start + i * 4)[0]
        for i in range(n_unique_frames)
    ]

    # Frame timing table: LE u32 per animation step, small values (game tick durations).
    # Ends at _SECTION_SEQUENCE_START.
    n_timing = (_SECTION_SEQUENCE_START - _SECTION_TIMING_START) // 4
    timing_values = [
        struct.unpack_from("<I", data, _SECTION_TIMING_START + i * 4)[0]
        for i in range(n_timing)
    ]

    # Frame sequence table: (count:u16, start:u16) pairs.
    # Ends at _SECTION_QUAD_START.
    n_pairs = (_SECTION_QUAD_START - _SECTION_SEQUENCE_START) // 4
    sequence_pairs = []
    for i in range(n_pairs):
        off = _SECTION_SEQUENCE_START + i * 4
        count = struct.unpack_from("<H", data, off)[0]
        start = struct.unpack_from("<H", data, off + 2)[0]
        sequence_pairs.append(SequencePair(count=count, start=start))

    # Quad data: flat array of 4-byte quad records.
    n_quads = (len(data) - _SECTION_QUAD_START) // 4
    quads = [
        Quad.from_bytes(data[_SECTION_QUAD_START + i * 4 : _SECTION_QUAD_START + i * 4 + 4])
        for i in range(n_quads)
    ]

    return PATData(
        version=version,
        anim_count=anim_count,
        frame_counts=frame_counts,
        unique_frame_quad_counts=unique_frame_quad_counts,
        timing_values=timing_values,
        sequence_pairs=sequence_pairs,
        quads=quads,
    )
