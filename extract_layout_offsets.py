"""
Derive X5 / X6 stage LAYOUT offsets from RXC2.exe (Mega Man X5/X6, MMLC2 PC).

The game stores a per-stage **layout pointer table** in .data: each entry is a VA
pointing at that stage's layout data in .rdata.  Located the same way as the clut
tables (find_clut_tables.py): search .data for pointers into the layout region and
take the cluster (anchored by a confirmed offset — X6 st00/st02/st05, X5 st010).

    X6 table @ file 0x0307e898 ; X5 table @ file 0x02e865a8
    entries are 4-byte VAs (virtual addresses);
    layout file_offset = VA - 0x400e00  (.rdata delta).

The pointer table gives EXACT layout offsets.  Two ways to label each offset:
  * n_screens (OMP): a stage's layout layer-0 references screens 0..n-1, so the max
    byte over the layout start == n-1.  RELIABLE for X6.  For X5 the layout data is
    packed tighter (windows over/undershoot), so this is only a rough hint.
  * correlation: match each table offset to the nearest CURRENT STAGE_LAYOUT offset;
    a small delta means the table confirms/corrects that stage.  Best signal for X5.

Width/height still need confirming per stage; this only fixes the offset.

Usage:
    python extract_layout_offsets.py --game X6      # dump + n_screens labels
    python extract_layout_offsets.py --game X5      # dump + correlation to current
"""
from __future__ import annotations
import argparse, struct, sys
from pathlib import Path

EXE = Path("PC/RXC2.exe")
RDATA_FILE_TO_VA = 0x400e00            # .rdata: VA = file + this

GAMES = {
    "X5": {"region": (0x02d97000, 0x02d9c800), "omp": "PC/X5/stage/*/*.omp"},
    "X6": {"region": (0x02dd3000, 0x02ddf000), "omp": "PC/X6/stage/map/*.omp"},
}

# Current STAGE_LAYOUT offsets (for the correlation labeller).
CURRENT = {
    "X5": {"st000": 0x02EC2D4B, "st010": 0x02D98528, "st020": 0x02D9A407,
           "st021": 0x02D9A404, "st030": 0x02D9A407, "st040": 0x02D9A3DE,
           "st041": 0x02D9A3DE, "st050": 0x02D99508, "st060": 0x02D992B3,
           "st061": 0x02D9A690, "st070": 0x02D98548, "st080": 0x02D99A7D,
           "st120": 0x02D9979F, "st160": 0x02D98524, "st170": 0x02D99CBA,
           "st180": 0x02D99CBA, "st220": 0x02D99F7D},
    "X6": {},  # X6 is labelled by n_screens instead (reliable)
}


def find_layout_table(exe: bytes, region):
    """Return sorted unique layout file-offsets of the densest pointer cluster."""
    lo, hi = region[0] + RDATA_FILE_TO_VA, region[1] + RDATA_FILE_TO_VA
    hits = []
    for off in range(0x2e79a00, 0x3332000 - 4, 4):     # scan .data
        v = struct.unpack_from("<I", exe, off)[0]
        if lo <= v < hi:
            hits.append(off)
    if not hits:
        return []
    best = cur = [hits[0]]
    for h in hits[1:]:
        if h - cur[-1] <= 0x28:
            cur.append(h)
        else:
            best, cur = (cur if len(cur) > len(best) else best), [h]
    best = cur if len(cur) > len(best) else best
    offs = sorted({struct.unpack_from("<I", exe, o)[0] - RDATA_FILE_TO_VA for o in best})
    return offs


def n_screens(glob: str):
    sys.path.insert(0, ".")
    from utils.omp import load_omp
    out = {}
    for p in sorted(Path().glob(glob)):
        try:
            out[p.stem] = load_omp(p).n_screens
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", choices=("X5", "X6"), default="X6")
    args = ap.parse_args()
    cfg = GAMES[args.game]
    exe = EXE.read_bytes()
    offs = find_layout_table(exe, cfg["region"])
    ns = n_screens(cfg["omp"])
    cur = CURRENT[args.game]

    print(f"{args.game}: {len(offs)} layout offsets in pointer table (file-offset order)\n")
    print(f"{'layout_off':>12}  label")
    for i, f in enumerate(offs):
        # n_screens hint: largest non-saturated max over a few windows == n-1.
        # (Reliable for X6's full-size layouts; only a rough hint for X5.)
        reads = [max(exe[f:f + w]) for w in (256, 384, 512, 768)]
        mx = max((m for m in reads if m < 255), default=max(reads))
        ns_cands = [s for s, n in ns.items() if n - 1 == mx]
        # correlation: nearest current offset
        corr = ""
        if cur:
            st = min(cur, key=lambda s: abs(cur[s] - f))
            d = f - cur[st]
            if abs(d) <= 0x40:
                corr = f"~{st} (was 0x{cur[st]:08X}, {d:+d})"
        label = corr or (", ".join(ns_cands) and f"n_screens~{', '.join(ns_cands)}") or "?"
        print(f"  0x{f:08x}  {label}")


if __name__ == "__main__":
    main()
