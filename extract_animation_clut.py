"""
Derive the per-stage CLUT-animation tables from RXC2.exe (Mega Man X5/X6, MMLC2 PC).

Background
----------
Animated-crystal tiles (OCL tile_type 0x39) get their colours from a per-stage
"animated COL" file (col/stage/<stage>/<stage>.col), driven by two pointer tables
embedded in RXC2.exe.  Format (confirmed against TeheManX4_Editor AnimeEditor):

    animated COL          flat array of 16-colour CLUTs (32 bytes each) = the "sets"
    ClutInfoPointers[i]   -> anime-pointer array, n entries; entry a -> [set,timer]
                            frame pairs.  `set` indexes the COL; `timer` = duration.
    ClutDestPointers[i]   -> [dest,length] byte pairs, one per anime.  `dest` is the
                            destination CLUT row in the stage palette; `length` the
                            number of consecutive CLUTs the anime drives.

The two tables are parallel and adjacent (ClutInfo = ClutDest + DEST_TO_INFO bytes),
and per stage the dest array sits immediately before the anime array
(dest_va == info_va - 2*n), so a stage's whole clut-anime block is self-describing.

Still-image rendering (what the renderer needs)
-----------------------------------------------
For each anime take frame 0's `set` (set0) and copy `length` CLUTs:
    stage_palette[dest + k] = animated_COL[set0 + k]   for k in range(length)
then render normally (tiles read CLUT row `col + 64`; animes write into that range).

How the table location was found (see experimental/find_clut_tables.py)
----------------------------------------------------------------------
The anime/dest/frame data live in one .data block beside the layout size tables.
The pointer tables were located by scanning for arrays of pointers into that block.
The constants below are those findings; re-derive with find_clut_tables.py if the
exe changes.

Usage
-----
    python extract_clut_animes.py                 # dump all stages it can match
    python extract_clut_animes.py --stage st0h    # one stage
    python extract_clut_animes.py --json out.json # machine-readable
"""
from __future__ import annotations
import argparse, json, struct
from pathlib import Path

EXE = Path("RXC2.exe")

# --- PE / section mapping (PE32, ImageBase 0x400000) ----------------------------
IMAGE_BASE = 0x400000

def load_sections(exe: bytes):
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    coff = pe + 4
    nsec = struct.unpack_from("<H", exe, coff + 2)[0]
    opt = coff + 20
    optsz = struct.unpack_from("<H", exe, coff + 16)[0]
    secs = []
    for i in range(nsec):
        s = opt + optsz + i * 40
        name = exe[s:s + 8].rstrip(b"\x00").decode("latin1")
        vsz, va, rsz, roff = struct.unpack_from("<IIII", exe, s + 8)
        secs.append((name, va, roff, rsz))
    return secs

class Exe:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        self.secs = load_sections(self.data)
    def va_to_off(self, va: int):
        rva = va - IMAGE_BASE
        for _n, sva, roff, rsz in self.secs:
            if sva <= rva < sva + rsz:
                return roff + (rva - sva)
        return None
    def u32(self, off: int): return struct.unpack_from("<I", self.data, off)[0]
    def u8(self, off: int): return self.data[off]

# --- clut-anime data region (found via find_clut_tables.py) ---------------------
# One .data block holds all stages' frame data, dest arrays and anime-pointer arrays,
# sitting beside the layout size tables.  An anime-pointer array entry points into
# this region; a ClutInfoPointers entry points to such an array (so its target's
# first 4 bytes are themselves a pointer into this region).
CLUT_REGION_VA = (0x0330bf00, 0x0330e000)
# ClutDestPointers and ClutInfoPointers are parallel tables; ClutInfo[i] sits this
# many bytes after ClutDest[i] (verified: info entry 0x30146b8 - dest entry 0x3014600).
DEST_TO_INFO = 0xb8

def is_clut_va(exe: Exe, v: int) -> bool:
    return CLUT_REGION_VA[0] <= v < CLUT_REGION_VA[1] and exe.va_to_off(v) is not None


def decode_anime_array(exe: Exe, info_entry_off: int):
    """Decode one stage's animes given the ClutInfoPointers table-entry offset.

    The parallel ClutDestPointers entry (info_entry_off - DEST_TO_INFO) gives the
    [dest,length] array; the anime count n is the number of consecutive valid
    frame pointers in the anime array, confirmed by valid dest pairs.
    """
    info_va = exe.u32(info_entry_off)
    info_off = exe.va_to_off(info_va)
    dest_va = exe.u32(info_entry_off - DEST_TO_INFO)
    dest_off = exe.va_to_off(dest_va)
    if info_off is None or dest_off is None:
        return None
    # n = consecutive valid frame pointers whose matching dest pair is also valid
    n = 0
    while n < 64:
        p = exe.u32(info_off + n * 4)
        if not is_clut_va(exe, p):
            break
        dst, ln = exe.u8(dest_off + 2 * n), exe.u8(dest_off + 2 * n + 1)
        if not (8 <= dst <= 220 and 1 <= ln <= 64):
            break
        n += 1
    if n == 0:
        return None
    animes = []
    fptrs = [exe.u32(info_off + a * 4) for a in range(n)]
    for a in range(n):
        fo = exe.va_to_off(fptrs[a])
        set0 = exe.u8(fo)
        dest = exe.u8(dest_off + 2 * a)
        length = exe.u8(dest_off + 2 * a + 1)
        # full frames: read [set,timer] pairs until the next frame-pointer boundary
        nxt = sorted(p for p in fptrs if p > fptrs[a])
        end = exe.va_to_off(nxt[0]) if nxt else fo + 2
        frames = []
        if end and 0 < (end - fo) <= 256:
            for k in range((end - fo) // 2):
                frames.append((exe.u8(fo + 2 * k), exe.u8(fo + 2 * k + 1)))
        else:
            frames = [(set0, exe.u8(fo + 1))]
        animes.append({"dest": dest, "length": length, "set0": set0, "frames": frames})
    return animes


def find_info_pointer_table(exe: Exe):
    """Locate ClutInfoPointers by finding the .data run with the most entries that
    point to anime arrays (target's first 4 bytes is itself a clut-region pointer).
    Returns (table_file_off, length) covering the cluster."""
    hits = []  # file offsets of ClutInfoPointers-style entries
    for _n, sva, roff, rsz in exe.secs:
        if _n != ".data":
            continue
        for off in range(roff, roff + rsz - 4, 4):
            v = exe.u32(off)
            if not is_clut_va(exe, v):
                continue
            if is_clut_va(exe, exe.u32(exe.va_to_off(v))):
                hits.append(off)
    if not hits:
        return None, 0
    # take the tightest cluster (entries are 4-byte spaced with occasional gaps)
    hits.sort()
    best_lo = best_hi = hits[0]; lo = hits[0]; prev = hits[0]
    best = 1; cur = 1
    for h in hits[1:]:
        if h - prev <= 0x40:        # within the same table (gaps for null stages)
            cur += 1
        else:
            if cur > best:
                best, best_lo, best_hi = cur, lo, prev
            lo = h; cur = 1
        prev = h
    if cur > best:
        best, best_lo, best_hi = cur, lo, prev
    return best_lo, (best_hi - best_lo) // 4 + 1


def read_info_table(exe: Exe):
    """Return {clut_index: info_entry_file_off} for non-null ClutInfoPointers entries."""
    base, length = find_info_pointer_table(exe)
    out = {}
    if base is None:
        return out
    for i in range(length):
        off = base + i * 4
        v = exe.u32(off)
        if is_clut_va(exe, v) and is_clut_va(exe, exe.u32(exe.va_to_off(v))):
            out[i] = off
    return out


def col_sizes():
    """Animated-COL CLUT counts, {label: n_cluts}. RXC2 holds X5 and X6 only."""
    import sys
    sys.path.insert(0, ".")
    from utils.palette import load_col_palettes
    out = {}
    for game in ("X5", "X6"):
        for col in Path("PC").glob(f"{game}/col/stage/**/*.col"):
            try:
                out[str(col)] = len(load_col_palettes(col)) // 16
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", help="filter to a COL whose path contains this string")
    ap.add_argument("--json", type=Path, help="write machine-readable JSON here")
    args = ap.parse_args()

    exe = Exe(EXE)
    table = read_info_table(exe)
    sizes = col_sizes()

    result = []
    for idx, info_entry_off in sorted(table.items()):
        animes = decode_anime_array(exe, info_entry_off)
        if not animes:
            continue
        info_va = exe.u32(info_entry_off)
        need = max(a["set0"] + a["length"] for a in animes)   # min COL CLUTs required
        # animated COLs whose CLUT count is >= need and closest (the stage's own COL)
        matches = sorted((n - need, c) for c, n in sizes.items()
                         if n >= need and "_eng" not in c and "col0" not in Path(c).name)
        matches = [c for _d, c in matches[:6]]
        result.append({"clut_index": idx, "info_va": info_va,
                       "n_animes": len(animes), "col_cluts_needed": need,
                       "col_matches": matches, "animes": animes})

    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"wrote {args.json}  ({len(result)} stages)")
        return

    for r in result:
        if args.stage and not any(args.stage in m for m in r["col_matches"]):
            continue
        cols = ", ".join(Path(m).parts[-1] for m in r["col_matches"]) or "?"
        print(f"\nclut_index={r['clut_index']:2d}  info_va=0x{r['info_va']:08x}  "
              f"animes={r['n_animes']}  COL needs {r['col_cluts_needed']} cluts  -> {cols}")
        for a in r["animes"]:
            print(f"    dest={a['dest']:3d} len={a['length']:2d} set0={a['set0']:3d} "
                  f"frames={a['frames'][:8]}")


if __name__ == "__main__":
    main()
