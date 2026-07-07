"""
Find a stage's LAYOUT OFFSET (+ row-width W) in the game EXE by matching an
acediez-style stage-layout map.  Validated on X5 st000/st030/st070 and X6 st00.

Two complementary methods run by default:

  HOUGH  (primary, searches the WHOLE exe)
    1. Recover the map's screen-id grid: match each 256px map cell to its best
       OMP screen by masked edge-correlation -> (row,col) -> screen_id, + confidence.
    2. For every width W and every byte offset, let each recovered cell vote for the
       offset that would place it there: offset = byte_position - (row*W + col).
       The true (offset, W) collects a vote from (nearly) every cell.
    Because it scans the whole file it finds layouts stored ANYWHERE -- this is how
    the intro stage st000 (kept far from the other stages, in a 0x02EC.. block) was
    located: 37/37 cells, layer-0 render-NCC 1.000.  FFT-only had missed it because
    that scan only tried per-stage pointer-table offsets.

  FFT  (cross-check, searches the per-game layout region)
    Tile layer-0 edge-thumbnails per candidate layout and FFT normalized-cross-
    correlate the map's edge-map over them.  Tolerant of a few wrong recovered ids;
    strong for foreground-dense stages.

Every candidate from either method is confirmed by rendering layer-0 at (offset,W,H)
and reporting the edge-NCC against the map (~1.0 == exact match); the final ranking
is by that render-NCC.

Usage:
  python match_layout_to_map.py st000 screenshots/X5_ST00_00_INTRO_combined.png --game X5
  python match_layout_to_map.py st070 map.png --game X5 --wmin 24 --wmax 44
  python match_layout_to_map.py st00  map.png --game X6 --method fft
"""
import argparse, struct, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_stage import preload_related_files, build_x6_chr256_override, EXE_PATH_LC2
from utils.omp import render_level, LayoutTable

TS = 64                                                   # thumbnail / descriptor resolution
REGION = {"X5": (0x02d97000, 0x02d9c800), "X6": (0x02dd3000, 0x02ddf000)}  # FILE offsets of layout data


def edge(gray):
    gy, gx = np.gradient(gray.astype(np.float32)); return np.hypot(gx, gy)


def omp_path_for(game, stage):
    return Path(f"PC/{game}/stage/{'map/'+stage if game=='X6' else stage+'/'+stage}.omp")


# ---------------------------------------------------------------- screen rendering

def screen_descriptors(omp, ocl, tex, tbg, fp, chr256, N):
    """Render every screen once -> edge thumbnails (for FFT compositing) plus the
    normalized edge vector / mask / coverage used for grid recovery."""
    thumbs = np.zeros((N, TS, TS), np.float32)
    SE = np.zeros((N, TS * TS), np.float32)
    SM = np.zeros((N, TS * TS), np.float32)
    cover = np.zeros(N, np.float32)
    for s in range(N):
        lay = LayoutTable.from_partial({(0, 0): s})
        im = render_level(omp, ocl, lay, 1, 1, tex=tex, tex_bg=tbg,
                          flags_to_palette=fp, chr256_override=chr256).convert("RGBA")
        mask = np.asarray(im.resize((TS, TS)))[..., 3] > 16
        e = edge(np.asarray(im.convert("L").resize((TS, TS)), float)) * mask
        thumbs[s] = e
        v = e.flatten()
        SE[s] = v / (np.linalg.norm(v) + 1e-6)
        SM[s] = mask.flatten()
        cover[s] = mask.mean()
    return thumbs, SE, SM, cover


def screen_thumbs(omp, ocl, tex, tbg, fp, chr256, N):   # back-compat helper
    return screen_descriptors(omp, ocl, tex, tbg, fp, chr256, N)[0]


# ---------------------------------------------------------------- grid recovery

def recover_grid(map_img, SE, SM, cover, N):
    """Match each 256px map cell to its best screen (masked edge cosine).
    Returns grid[rows,cols] of screen-ids (0 = sky) and conf[rows,cols]."""
    arr = np.asarray(map_img.convert("RGBA"))
    cols, rows = map_img.size[0] // 256, map_img.size[1] // 256
    grid = np.zeros((rows, cols), int); conf = np.zeros((rows, cols), float)
    for ry in range(rows):
        for rx in range(cols):
            cell = arr[ry*256:(ry+1)*256, rx*256:(rx+1)*256]
            if cell.shape[:2] != (256, 256):
                continue
            cim = Image.fromarray(cell)
            if (np.asarray(cim.convert("L"), float) > 16).mean() < 0.03:   # essentially sky
                continue
            m = np.asarray(cim.resize((TS, TS)))[..., 3] > 16
            ve = (edge(np.asarray(cim.convert("L").resize((TS, TS)), float)) * m).flatten()
            mv = ve[None, :] * SM
            mvn = mv / (np.linalg.norm(mv, axis=1, keepdims=True) + 1e-6)
            score = (mvn * SE).sum(1); score[cover < 0.05] = -1
            b = int(score.argmax()); grid[ry, rx] = b; conf[ry, rx] = float(score[b])
    return grid, conf


def hough_search(exe, grid, conf, wmin, wmax, N, region=None, conf_min=0.5):
    """Each non-sky, high-confidence cell (r,c,v) votes offset = pos(v) - (r*W+c)
    for every W.  Returns sorted [(votes, n_cells, offset, W)] (best first)."""
    exe_arr = np.frombuffer(exe, np.uint8); L = len(exe_arr)
    lo, hi = (0, L) if region is None else region
    cells = [(r, c, int(grid[r, c]))
             for r in range(grid.shape[0]) for c in range(grid.shape[1])
             if 0 < grid[r, c] < N and conf[r, c] >= conf_min]
    if not cells:
        return [], 0
    pos = {v: np.flatnonzero(exe_arr == v) for v in {v for _, _, v in cells}}
    votes = np.zeros(L, np.int32)
    out = []
    for W in range(wmin, wmax + 1):
        votes.fill(0)
        for (r, c, v) in cells:
            p = pos[v] - (r * W + c)
            p = p[(p >= lo) & (p < hi)]
            votes[p] += 1
        o = int(votes.argmax())
        out.append((int(votes[o]), len(cells), o, W))
    out.sort(reverse=True)
    return out, len(cells)


# ---------------------------------------------------------------- FFT method

def composite(thumbs, lb, W, H, N):
    C = np.zeros((H * TS, W * TS), np.float32)
    for sy in range(H):
        for sx in range(W):
            sid = lb[sy * W + sx]
            if sid < N:
                C[sy*TS:(sy+1)*TS, sx*TS:(sx+1)*TS] = thumbs[sid]
    return C


def fft_ncc(R, M):
    Rh, Rw = R.shape; Mh, Mw = M.shape
    if Mh > Rh or Mw > Rw: return -9.0, (0, 0)
    T = M - M.mean(); tn = float(np.sqrt((T*T).sum()))
    if tn < 1e-6: return -9.0, (0, 0)
    corr = np.fft.irfft2(np.fft.rfft2(R) * np.conj(np.fft.rfft2(T, s=R.shape)), s=R.shape)
    oy, ox = Rh - Mh + 1, Rw - Mw + 1
    num = corr[:oy, :ox]
    ii = np.zeros((Rh+1, Rw+1)); ii[1:, 1:] = np.cumsum(np.cumsum(R, 0), 1)
    ii2 = np.zeros((Rh+1, Rw+1)); ii2[1:, 1:] = np.cumsum(np.cumsum(R*R, 0), 1)
    def ws(I): return (I[Mh:Mh+oy, Mw:Mw+ox] - I[0:oy, Mw:Mw+ox]
                       - I[Mh:Mh+oy, 0:ox] + I[0:oy, 0:ox])
    s1, s2 = ws(ii), ws(ii2); n = Mh*Mw
    den = np.sqrt(np.maximum(s2 - s1*s1/n, 1e-6)) * tn
    ncc = num / np.maximum(den, 1e-9)
    p = np.unravel_index(ncc.argmax(), ncc.shape)
    return float(ncc[p]), (int(p[1]), int(p[0]))


def candidate_offsets(exe, game):
    """Layout offsets pointed at by the per-stage pointer table (VA range scan)."""
    lo, hi = REGION[game][0] + 0x400e00, REGION[game][1] + 0x400e00
    return sorted(set(struct.unpack_from("<I", exe, o)[0] - 0x400e00
                      for o in range(0x2e79a00, 0x3332000 - 4, 4)
                      if lo <= struct.unpack_from("<I", exe, o)[0] < hi))


def fft_search(exe, thumbs, map_fft, cands, wmin, wmax, Hf, N, top=8):
    res = []
    for off in cands:
        for W in range(wmin, wmax + 1):
            need = W * Hf
            if off + need > len(exe): continue
            lb = exe[off:off + need]
            if max(lb) >= N: continue          # invalid screen-id => wrong offset/width
            sc, _ = fft_ncc(composite(thumbs, lb, W, Hf, N), map_fft)
            res.append((sc, off, W))
    res.sort(reverse=True)
    return res[:top]


# ---------------------------------------------------------------- validation

def render_ncc(omp, ocl, tex, tbg, fp, chr256, exe, off, W, H, N, map_small, SZ):
    """Render layer 0 at (off,W,H), return edge-NCC vs the map (1.0 == exact)."""
    if off < 0 or off + W*H*3 > len(exe): return -9.0
    if max(exe[off:off + W*H]) >= N: return -9.0      # invalid layer-0 id
    lay = LayoutTable.from_bytes(exe[off:off + W*H*3], W, H, 0)
    im = render_level(omp, ocl, lay, W, H, tex=tex, tex_bg=tbg,
                      flags_to_palette=fp, chr256_override=chr256).convert("L")
    RE = edge(np.asarray(im.resize(SZ), float))
    a, b = RE - RE.mean(), map_small - map_small.mean()
    d = float(np.sqrt((a*a).sum() * (b*b).sum()))
    return float((a*b).sum() / d) if d > 1e-9 else -9.0


def first_invalid_row(exe, off, W, N, maxrows=128):
    """Row at which layer 0 hits an impossible screen-id (bounds the max H)."""
    for r in range(maxrows):
        seg = exe[off + r*W: off + (r+1)*W]
        if len(seg) < W or max(seg) >= N:
            return r
    return maxrows


def region_tag(game, off):
    lo, hi = REGION[game]
    return "[in-region]" if lo <= off < hi else "[OUT-of-region]"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage"); ap.add_argument("map")
    ap.add_argument("--game", choices=("X5", "X6"), default="X6")
    ap.add_argument("--method", choices=("hough", "fft", "both"), default="both")
    ap.add_argument("--wmin", type=int, default=18)
    ap.add_argument("--wmax", type=int, default=40)
    ap.add_argument("--h", type=int, default=0, help="render rows for validation (0 = map rows)")
    ap.add_argument("--region-only", action="store_true", help="restrict Hough to the game's layout region")
    ap.add_argument("--conf", type=float, default=0.5, help="min cell confidence to vote (Hough)")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    omp, ocl, tex, tbg, fp, gv = preload_related_files(omp_path_for(args.game, args.stage))
    chr256 = build_x6_chr256_override(ocl, tex, tbg) if args.game == "X6" else None
    N = omp.n_screens
    exe = EXE_PATH_LC2.read_bytes()

    mp = Image.open(args.map)
    cols, rows = mp.size[0] // 256, mp.size[1] // 256
    H = args.h or rows
    SZ = (cols * 24, rows * 24)                                  # validation render-NCC resolution
    map_small = edge(np.asarray(mp.convert("L").resize(SZ), float))
    map_fft = edge(np.asarray(mp.convert("L").resize((cols * TS, rows * TS)), float))

    print(f"{args.stage}: map {mp.size} ({cols}x{rows} screens), n_screens={N}, "
          f"W[{args.wmin}-{args.wmax}], validate H={H}\n")
    print("rendering screen descriptors...")
    thumbs, SE, SM, cover = screen_descriptors(omp, ocl, tex, tbg, fp, chr256, N)

    cands = {}   # (off, W) -> tag describing how it was proposed

    if args.method in ("hough", "both"):
        grid, conf = recover_grid(mp, SE, SM, cover, N)
        nz = int((grid > 0).sum())
        mc = float(conf[conf > 0].mean()) if nz else 0.0
        print(f"\nrecovered grid: {nz} non-sky cells, mean confidence {mc:.3f}"
              + ("   (low confidence -> Hough ids may be unreliable; lean on FFT/render-NCC)"
                 if mc < 0.7 else ""))
        region = REGION[args.game] if args.region_only else None
        hres, ncell = hough_search(exe, grid, conf, args.wmin, args.wmax, N,
                                   region=region, conf_min=args.conf)
        scope = "region" if args.region_only else "whole-EXE"
        print(f"HOUGH ({scope}), {ncell} voting cells -- top by vote count:")
        for votes, nc, off, W in hres[:args.top]:
            print(f"  votes={votes:3d}/{nc}  0x{off:08X}  W={W:2d}  {region_tag(args.game, off)}")
            cands.setdefault((off, W), "hough")

    if args.method in ("fft", "both"):
        Hf = max(rows + 4, H)
        fres = fft_search(exe, thumbs, map_fft, candidate_offsets(exe, args.game),
                          args.wmin, args.wmax, Hf, N, top=args.top)
        print(f"\nFFT (pointer-table offsets, region) -- top by composite NCC:")
        for sc, off, W in fres:
            print(f"  ncc={sc:.3f}  0x{off:08X}  W={W:2d}  {region_tag(args.game, off)}")
            cands.setdefault((off, W), "fft")

    # Confirm every proposed candidate by an actual layer-0 render vs the map.
    print(f"\nFINAL ranking by layer-0 render-NCC vs map (H={H}):")
    scored = []
    for (off, W), src in cands.items():
        ncc = render_ncc(omp, ocl, tex, tbg, fp, chr256, exe, off, W, H, N, map_small, SZ)
        scored.append((ncc, off, W, src))
    scored.sort(reverse=True)
    for ncc, off, W, src in scored:
        maxh = first_invalid_row(exe, off, W, N)
        print(f"  NCC={ncc:.3f}  0x{off:08X}  W={W:2d}  H<= {maxh:2d}  via {src:5s} {region_tag(args.game, off)}")
    if scored and scored[0][0] > 0.3:
        ncc, off, W, src = scored[0]
        print(f"\n==> best: 0x{off:08X}, W={W}  (NCC {ncc:.3f}; set H from the map / full stage extent)")


if __name__ == "__main__":
    main()
