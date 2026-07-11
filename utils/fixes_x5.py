from utils.consts import TILE_SIZE, NIBBLE_MASK, NIBBLE_SHIFT, PAGES_PER_ROW, CHR256_PAGE_START, PAGE_SIZE_PX
from utils.ocl import OclEntry
from utils.types import TexData
from utils.omp import LayoutTable, build_chr256_ocl_indices

# ── X5 background-tileset chr256 (tex_bg) recovery (generic, no per-stage data) ──
#
# Some X5 stages store a background-LAYER tileset as a contiguous batch of OCL entries
# whose foreground-sheet (tex) data is leftover garbage while the real art lives in the
# chr256 sheet (tex_bg).  The game-agnostic build_chr256_ocl_indices leaves these on tex
# (sole page<8 entries outside its chr256-batch region) so they render as vertical-stripe
# "comb" garble — e.g. st061's sky, st070's jungle, st160's scanline plasma, st000's
# skyline.  This recovers them WITHOUT a per-stage table, using three independent signals
# that together exclude every settled stage (all move 0; the foreground layer is never
# touched):
#
#   1. SHEET-WALK RUN (structure): a maximal run of >= MIN_RUN_LEN consecutive OCL indices
#      whose tile coordinate (page*256 + clut_base) increments by exactly 1 — i.e. a
#      tileset batch dumped in sheet order.  Authored foreground/object tilesets reference
#      tiles in semantic order, so their coordinates jump around and never form long runs.
#   2. BACKGROUND-EXCLUSIVE (placement): NO tile of the run is placed in the foreground
#      layer (layer 0 = the top third of the 3-layer vertical-stacked layout).  This is
#      what excludes mixed foreground/background batches (e.g. st050's run 259-1091) and
#      guarantees the foreground render is byte-identical.
#   3. TEX IS A COMB (content): the run's not-yet-chr256 tiles have, in tex, a horizontal-
#      minus-vertical transition count >= COMB_THRESHOLD (median).  A comb (vertical
#      stripes, columns ~constant) is the signature of garbage tex; real art — foreground
#      detail OR a coherent background already correctly on tex — is isotropic (htr ~ vtr)
#      or horizontal-scanline (htr < vtr), so it scores below threshold.  This is what the
#      earlier plain "tex is noisy (high htr)" rule lacked: st050's detailed pillar tops
#      have high htr but htr ~ vtr, so they are NOT combs and stay on tex.
#
# Only tiles not already routed by the base heuristic are added (the base correctly handles
# most background batches, e.g. st160's starfield); tex_bg must be non-empty for them.
MIN_RUN_LEN = 16
COMB_THRESHOLD = 50


def build_x5_chr256_bg_override(
    ocl: list[OclEntry],
    tex: TexData,
    tex_bg: TexData,
    layout: LayoutTable,
    n_screens: int,
    omp_tiles: list[list[int]],
    level_width_screens: int,
    level_height_screens: int,
) -> "tuple[frozenset[int], int]":
    """Return (chr256_indices, n_moved): the base chr256 set unioned with the recovered
    background-tileset tiles.  n_moved is how many tiles this pass added (0 = unchanged).

    See the module comment above for the three-signal rule.  Pure function of the OCL
    table, the two TEX sheets and the level layout — no per-stage data."""
    base = set(build_chr256_ocl_indices(ocl, tex, tex_bg))

    def _grid(t: "TexData", e: OclEntry) -> "list[list[int]] | None":
        raw = t["raw_image"]; w = t["width"]; h = len(raw) // w
        gx = (e.page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
        gy = (e.page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
        if gx + TILE_SIZE > w or gy + TILE_SIZE > h:
            return None
        return [list(raw[(gy + r) * w + gx : (gy + r) * w + gx + TILE_SIZE]) for r in range(TILE_SIZE)]

    def _htr(g: list[list[int]]) -> int:
        return sum(1 for row in g for i in range(TILE_SIZE - 1) if row[i] != row[i + 1])

    def _vtr(g: list[list[int]]) -> int:
        return sum(1 for c in range(TILE_SIZE) for r in range(TILE_SIZE - 1) if g[r][c] != g[r + 1][c])

    def _nonempty(g: list[list[int]]) -> bool:
        return any(p for row in g for p in row)

    def _tilepos(e: OclEntry) -> int:
        return e.page * 256 + e.clut_base

    # Placement: which OCL indices appear in the foreground layer (top third of the
    # vertical-stacked 3-layer layout) and which appear anywhere.
    fg_rows = (level_height_screens // 3) * 16  # tile rows belonging to layer 0
    placed_fg: set[int] = set()
    placed_all: set[int] = set()
    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            sid = layout.get(sx, sy)
            if sid is None or sid >= n_screens:
                continue
            screen = omp_tiles[sid]
            for wy in range(16):
                ly = sy * 16 + wy
                for wx in range(16):
                    raw = screen[wy * 16 + wx]
                    if not raw:
                        continue
                    idx = raw & 0x3FFF
                    placed_all.add(idx)
                    if ly < fg_rows:
                        placed_fg.add(idx)

    # Maximal sheet-walk runs (page<8, consecutive OCL index whose tilepos increments
    # by exactly 1) are the background-tileset batches.  Classify every run by the
    # three signals INDEPENDENT of its length:
    #   clean = background-exclusive (no member placed in the foreground layer)
    #           AND tex is a comb (median htr-vtr >= COMB_THRESHOLD)
    #           AND tex_bg holds real pixels for >= half its movable tiles.
    # A long (>= MIN_RUN_LEN) clean run is a confirmed background tileset and seeds
    # `moved`.  Shorter clean runs are NOT trusted on their own (a brief comb run inside
    # a foreground region would be a false positive) — they are only adopted when they
    # CONNECT to a confirmed one, in the absorption pass below.
    #
    # Why short fragments arise: the OCL order interleaves one tileset's batch with
    # entries from OTHER, already-routed background batches (on different pages), which
    # chops a single logical sheet into short index-fragments even though that sheet's
    # per-page tilepos sequence stays perfectly contiguous.  e.g. st061's page-4 sky/
    # water sheet (tilepos 1047..1202) is split every ~4 tiles by interleaved page-2/3
    # background entries, leaving its head (OCL 2580-2601) and a lone tile (2734) as
    # sub-MIN_RUN_LEN fragments that this length gate would otherwise drop — they render
    # as comb garble on tex while their real art sits in tex_bg.
    def _classify(run: "list[int]") -> "tuple[list[int], bool] | None":
        """Return (movable_indices, clean) for a run, or None if it cannot move.

        None when any member is foreground (background-exclusive guard) or the run has
        no not-yet-base, placed tile.  `clean` is the comb + tex_bg-non-empty verdict."""
        if any(k in placed_fg for k in run):
            return None
        notbase = [k for k in run if k not in base and k in placed_all]
        if not notbase:
            return None
        combs: list[int] = []
        bg_ok = 0
        for k in notbase:
            gt = _grid(tex, ocl[k]); gb = _grid(tex_bg, ocl[k])
            if gt is None or gb is None:
                continue
            combs.append(_htr(gt) - _vtr(gt))
            if _nonempty(gb):
                bg_ok += 1
        if not combs:
            return None
        combs.sort()
        median = combs[len(combs) // 2]
        return notbase, (median >= COMB_THRESHOLD and bg_ok >= 0.5 * len(notbase))

    runs: "list[list[int]]" = []   # movable indices of every clean, non-foreground run
    moved: set[int] = set()
    n = len(ocl)
    i = 0
    while i < n:
        if ocl[i].page >= CHR256_PAGE_START:
            i += 1
            continue
        j = i
        while (j + 1 < n and ocl[j + 1].page < CHR256_PAGE_START
               and _tilepos(ocl[j + 1]) == _tilepos(ocl[j]) + 1):
            j += 1
        run = list(range(i, j + 1))
        i = j + 1
        info = _classify(run)
        if info is None:
            continue
        notbase, clean = info
        if not clean:
            continue
        runs.append(notbase)
        if len(run) >= MIN_RUN_LEN:
            moved.update(notbase)   # confirmed background tileset — seed

    # Absorption: re-join short clean fragments to the sheet they belong to.  A fragment
    # is adopted when one of its tiles is tilepos-adjacent (same page, +/-1) to a tile
    # already confirmed as background, bridging the OCL-order splits described above.
    # Iterated to a fixpoint so a chain of fragments (each adjacent only to the next)
    # all reach the confirmed anchor.  The per-fragment foreground guard is preserved
    # (each fragment was already vetted in _classify), so a foreground placement in one
    # part of a sheet can never drag in the rest — unlike merging into one run.
    def _tp_key(k: int) -> "tuple[int, int]":
        return (ocl[k].page, _tilepos(ocl[k]))

    moved_tp = {_tp_key(k) for k in moved}
    changed = True
    while changed:
        changed = False
        for notbase in runs:
            if all(k in moved for k in notbase):
                continue
            if any((ocl[k].page, _tilepos(ocl[k]) - 1) in moved_tp
                   or (ocl[k].page, _tilepos(ocl[k]) + 1) in moved_tp
                   for k in notbase):
                for k in notbase:
                    if k not in moved:
                        moved.add(k); moved_tp.add(_tp_key(k)); changed = True

    return frozenset(base | moved), len(moved)


# ── X5 per-stage tile-sheet (tex vs tex_bg) overrides ────────────────────────────
#
# Companion to the generic build_x5_chr256_bg_override: per-stage sheet corrections for
# page>=8 tiles whose true art lives in the OPPOSITE sheet from where the base router puts
# them.  Direct analogue of the X6 pair X6_SHEET_OVERRIDE_BY_STAGE (a (col, page) GROUP
# table) and X6_SHEET_OVERRIDE_INDICES (an explicit OCL-INDEX table for fixes that don't
# form a clean group).  ``"bg"`` forces a tile to read tex_bg (chr256); ``"tex"`` forces
# tex.  Index entries win over group entries (more specific).
#
# Background — the routing rule from the game itself (TeheManX4 editor Draw16xTile) is
# purely PAGE-based: page<8 reads the 4bpp sheet (tex), page>=8 reads the 8bpp sheet
# (chr256/tex_bg), with NO col component.  The renderer can't apply that rule blanket on
# the PC HD port, though: the port re-packed the two sheets so the real art for a given
# page>=8 tile ended up on tex in some stages and on tex_bg in others.  No per-tile content
# signal separates the two — the wrong sheet holds coherent fragments of OTHER real tiles,
# so coherence and level-seam-continuity metrics both mis-classify it — so the corrections
# are listed per stage against ground truth.
#
#   st040 (Burn Dinorex Area 1): the wall-mounted dragon-head flamethrowers
#     are an 8bpp chr256 tileset, but col=16 is not a chr256 palette indicator (0/112) so
#     the base router left the whole class on tex.  CRUCIALLY this stage has TWO col=16
#     page-10/11 batches that REUSE the same texture coordinates but resolve to OPPOSITE
#     sheets: OCL 738-848 is a complete dragon copy that is coherent on tex (verified, must
#     stay), while OCL 1585-2161 is a second set of placements whose art is only coherent on
#     tex_bg (the originally-reported "garbled dragon heads", garbage on tex).  Because the
#     two batches share (col, page) AND texture coords, a group key cannot tell them apart —
#     the discriminator is the OCL-index batch.  Hence the 1585-2161 indices are listed
#     explicitly (the 25 placed col=16 page-10/11 tiles in that range) and routed to tex_bg;
#     everything else in the class is left on its default tex.  Validated vs the in-game
#     sprite (metal head, yellow eye, gear/flame mouth) for both batches.
#   staff_eng (end credits / staff roll): the scrolling background band repeats every two
#     screens (level x 0-319, 512-831, 1024-1343 at y 1312-1439).  Its page-10/11 art was
#     re-packed onto tex_bg for cols 64/80/96 while cols 16/32/48 keep their art on tex —
#     both sheets hold DIFFERENT coherent data at these coords (so the generic tex-empty
#     recovery correctly skips them; only col separates the two halves).  Every placed
#     col-64/80/96 page-10/11 tile lives in those bands, so the (col, page) group key moves
#     exactly them and nothing else.
X5_SHEET_OVERRIDE_BY_STAGE: dict[str, "dict[tuple[int, int], str]"] = {
    # stem -> {(col, page): "bg" | "tex"}
    "staff_eng": {(64, 11): "bg", (80, 10): "bg", (80, 11): "bg", (96, 10): "bg"},
    # st041 (Burn Dinorex Area 2): fixes boss room background tileset whose page-10 portion
    # base router + tex-empty recovery correctly route to tex_bg, but whose page-9 portion
    # is garbled in tex. Real 8bpp page-9 tiles is on tex_bg due to
    # build_x5_chr256_bg_override only walking pages<8 and the tex-empty recovery only
    # fires when tex is blank.
    "st041": {(16, 9): "bg"},
}
X5_SHEET_OVERRIDE_INDICES: dict[str, "dict[int, str]"] = {
    # stem -> {ocl_idx: "bg" | "tex"}
    # st040 dragon-head batch B (OCL 1585-2161, col=16 pages 10/11) → tex_bg.  Batch A
    # (738-848, same coords) is deliberately absent so it stays on its correct tex sheet.
    "st040": {i: "bg" for i in (1585, 1586, 1587, 1588, 1589, 1590, 1591, 1592, 1593,
                                1596, 1597, 1598, 1599, 1600, 1601, 1603, 1604, 1605,
                                1666, 1667, 2157, 2158, 2159, 2160, 2161)},
    # st030 (Tidal Whale / Duff McWhalen): two disjoint mis-routed batches.
    #  (a) OCL 3385-3509 (col=32 page-11 background, level x880-1231 y3072-3215) whose art the PC
    #      port re-packed onto tex_bg, rendering as comb-garble on tex.  A DIFFERENT col=32 page-11
    #      batch (OCL 1085-1339) is correct on tex, so a (col, page) group key can't separate them.
    #  (b) The col=7 page-1/2/3 rock-wall batch around the console room (level x4896-5856, the
    #      foreground layer).  The PC port packed a DIFFERENT-but-coherent rock variant onto tex at
    #      these coords, so the base router (page<8 -> tex) leaves them there: they render as lighter
    #      rectangular patches that don't blend, and OCL 2644 draws a spurious opaque block where its
    #      tex_bg slot is (correctly) near-empty.  This CANNOT be a content rule — e.g. OCL 2139 is
    #      byte-identical on tex to OCL 484, which must STAY on tex; only the OCL index (placement
    #      batch) distinguishes them (cf. st040).  Palette is already correct (col+64); this is purely
    #      a sheet selection.  Indices are the GT-verified set (vs X5_ST03_00 screenshot): routing
    #      them tex_bg improves 18309 px with zero regressions.  The generic bg-recovery skips them
    #      because it is gated to background-layer-EXCLUSIVE runs and these are foreground-placed.
    "st030": {
        **{i: "bg" for i in range(3385, 3510)},
        **{i: "bg" for i in (2139, 2140, 2141, 2142, 2143, 2146, 2147, 2179, 2195, 2196, 2197,
                             2435, 2641, 2642, 2643, 2644, 2645, 2646, 2647, 2648, 2649, 2650,
                             3369)},
    },
    # st070 (Spike Rosered): two unrelated sheet fixes in this stage.
    #
    #  (a) OCL 2879 → tex_bg.  col=0 page-1 (coord 8,10) draws a spurious solid rock block in the
    #      open passage left of the floating outcrop (level x5568-5583 y832-847); in-game there is
    #      no block there.  The slot holds a fully-opaque rock on tex (256/256 px) but a near-empty
    #      right-edge sliver on tex_bg (42/256) — a page<8 "both sheets differ" case the generic
    #      chr256 bg-recovery can't separate.  col=0/page=1 is far too common for a group key, so the
    #      single index is listed explicitly; tex_bg removes the block.
    #
    #  (b) OCL 1713-1820 (col=9, pages 1/3) → tex.  A batch of foreground jungle-rock tiles the
    #      generic build_x5_chr256_bg_override OVER-routes onto tex_bg, where the same coords hold an
    #      unrelated sparse fragment that renders as a garish black-and-red block (level x1664-1711
    #      y1984-2047 and y2240-2287).  Their dominant col=0 siblings (e.g. 601, 1067) correctly read
    #      tex.  The defect signature is exact — col=9, in the bg-recovery set, tex fully opaque
    #      (256/256) yet tex_bg sparse (<256) — which isolates precisely these 15 indices (every other
    #      col=9 tex_bg tile is bg_nz=256, identical on both sheets, or tex_nz<256, a genuine
    #      background).  They are placed ONLY in the two flagged regions, so forcing them to tex is
    #      safe; palette is left at col+64 (col=9 and col=0 are near-identical on the tex rock tiles).
    #
    #  (c) col=59 layer1 rock-silhouette batch → tex.  The base build_chr256_ocl_indices routes
    #      these to tex_bg, where they hold only sparse fragments (15-64/256), so the layer 1
    #      rock silhouette renders full of gaps and the solid sunset-sky backdrop (layer 2) shows
    #      through.  Their real art is a solid rock face on tex256.  These 14 indices
    #      are the layer-1 formation placements only, listed explicitly (a (col, page) group key would
    #      also match the partial col=59/page-2 tiles at OCL 920-963 that are already correctly on tex).
    "st070": {2879: "bg",
              **{i: "tex" for i in (1713, 1714, 1715, 1723, 1724, 1725, 1734, 1735, 1736,
                                    1745, 1746, 1747, 1818, 1819, 1820)},
              **{i: "tex" for i in (1489, 1490, 1491, 1493, 1606, 1607, 1608, 1609, 1615,
                                    1618, 1619, 1620, 1621, 1627)}},
}


def build_x5_sheet_override(
    stage_stem: "str | None",
    ocl: list[OclEntry],
    chr256_set: "frozenset[int]",
) -> "frozenset[int]":
    """Apply the X5 per-stage sheet overrides to an already-computed chr256 routing set.

    The (col, page) GROUP table (X5_SHEET_OVERRIDE_BY_STAGE) and the explicit OCL-INDEX
    table (X5_SHEET_OVERRIDE_INDICES) are each consulted; index entries win on conflict.
    ``"bg"`` adds a tile to the chr256 set (read tex_bg); ``"tex"`` removes it.  Returns
    chr256_set unchanged when the stage has no overrides.  Pure function of the OCL table."""
    group_ov = stage_stem and X5_SHEET_OVERRIDE_BY_STAGE.get(stage_stem)
    idx_ov = (stage_stem and X5_SHEET_OVERRIDE_INDICES.get(stage_stem)) or {}
    if not group_ov and not idx_ov:
        return chr256_set
    group_ov = group_ov or {}
    out = set(chr256_set)
    for idx, e in enumerate(ocl):
        sheet = idx_ov.get(idx) or group_ov.get((e.col, e.page))
        if sheet == "bg":
            out.add(idx)
        elif sheet == "tex":
            out.discard(idx)
    return frozenset(out)


def build_x5_pg8_empty_bg_override(
    ocl: list[OclEntry],
    tex: "TexData",
    tex_bg: "TexData",
    chr256_set: "frozenset[int]",
) -> "tuple[frozenset[int], int]":
    """Recover page>=8 tiles the base router leaves on tex where tex holds NOTHING.

    Return (chr256_indices, n_moved).  The X5 analogue of the X6 ``pg8_empty_bg`` pass
    and the unambiguous half of the X4/X5/X6 page-based routing rule.

    Pages 0-7 are split between tex / tex_bg by build_x5_chr256_bg_override; pages 8-0xB
    are 8bpp art that ``_resolve_tile`` routes to tex_bg ONLY when col is 0/112 (the chr256
    indicators) or the tile is in chr256_set.  Every other page>=8 tile defaults to tex.
    On the PC HD port some stages re-packed that art onto tex_bg under a non-indicator col
    (e.g. st120's machine-room tileset, cols 32/48/64/80 pages 10/11), so those tiles read
    an ALL-ZERO tex block and draw nothing — undrawn-audit category G.

    The recovery here is the unambiguous case only: a page 8-0xB tile whose tex block is
    EMPTY while tex_bg holds real pixels.  Rerouting it to tex_bg can never regress a tile
    that was already drawing (tex was blank), and it never touches a stage where tex holds
    the real art — so no per-stage table is needed.  (The hard case, where BOTH sheets hold
    coherent-but-different art, stays in X5_SHEET_OVERRIDE_INDICES; cf. st040's dragon heads.)
    The default ``col + 64`` CLUT row already renders these correctly, so no palette fix is
    paired with it.  Pure function of the OCL table and the two TEX sheets.

    Verified by experiment_x5_pg8_bg.py: across every level-mapped X5 stage this moves tiles
    ONLY in st120 (464 tiles, matching the audit's six G groups exactly); every other stage
    is a no-op, so the settled byte-identical baselines are unaffected."""
    TILE = TILE_SIZE
    tex_raw = tex["raw_image"]; tex_w = tex["width"]
    tex_h = len(tex_raw) // tex_w if tex_w else 0
    bg_raw = tex_bg["raw_image"]; bg_w = tex_bg["width"]
    bg_h = len(bg_raw) // bg_w if bg_w else 0

    def _block_has_data(raw: bytes, w: int, h: int, gx: int, gy: int) -> "bool | None":
        """True/False if the 16x16 block holds any non-zero pixel, or None if off-sheet."""
        if gx < 0 or gy < 0 or gx + TILE > w or gy + TILE > h:
            return None
        return any(raw[(gy + r) * w + gx + c] for r in range(TILE) for c in range(TILE))

    out = set(chr256_set)
    n_moved = 0
    for idx, e in enumerate(ocl):
        if e.pad == 0xFF:
            continue  # sky-fill sentinel (page nibble 15 too) — never real art
        # 8-0xB are the 8bpp bitmap pages; page 15 (pad=0x0F) is the page-band-1 art
        # slot (gy=256) that _resolve_tile also draws — the X5 st170 Rangda Bangda W
        # background whose tex block is blank while tex_bg holds it (same tex-empty
        # recovery, so still regression-free; sky stays dropped as its tex_bg is empty too).
        if not (CHR256_PAGE_START <= e.page <= 0xB or e.page == 15) or idx in out:
            continue
        gx = (e.page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE
        gy = (e.page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE
        if _block_has_data(tex_raw, tex_w, tex_h, gx, gy) is False \
                and _block_has_data(bg_raw, bg_w, bg_h, gx, gy):
            out.add(idx)
            n_moved += 1
    return frozenset(out), n_moved


# ── X5 per-stage CLUT-row fixes ──────────────────────────────────────────────────
#
# A few X5 background-tileset (tex_bg) batches reference a CLUT row whose static colours
# are the wrong palette phase: the tile's ``col + 64`` row holds a dark/saturated variant
# while the correct (in-game) colours live at a different row of the same stage COL.  This
# is NOT the generic X6 page>=8 / pad_hi mechanism (X5 COL files are plain static palettes,
# not VRAM snapshots) and there is no clean cross-stage rule — a blanket per-route offset
# regresses other tiles — so the affected (col, page) groups are listed per stage and the
# corrected row validated against ground truth.  Applied ONLY to chr256/tex_bg-routed tiles
# so any same-(col,page) foreground tile is untouched.
#
#   st061 (Shining Firefly Area 2): the spiral "aqua column" background-water batch
#     (col=11, pages 2-3, OCL 1972-2080 — a single contiguous sheet-walk run, the ONLY
#     col=11 tiles in the stage) renders saturated deep-blue at col+64 (row 75).  The
#     in-game glow is the light pastel-cyan gradient at row 80 (col 16); confirmed against
#     x5-izzy-glow-ingame.png and the stitched map MegaManX5-IzzyGlow-Area2.png.
X5_CLUT_ROW_FIXES: dict[str, dict[tuple[int, int], int]] = {
    # stem -> {(col, page): corrected_clut_row}, applied to tex_bg-routed tiles only.
    "st061": {(11, 2): 80, (11, 3): 80},
}


def build_x5_clut_row_override(
    stage_stem: "str | None",
    ocl: list[OclEntry],
    chr256_set: "frozenset[int]",
) -> "dict[int, int] | None":
    """Return {ocl_idx: corrected_clut_row} for an X5 stage from X5_CLUT_ROW_FIXES, or None.

    Only chr256/tex_bg-routed tiles (idx in chr256_set) whose (col, page) is listed for the
    stage are relocated, so foreground tiles sharing the same (col, page) are never touched.
    Pure function of the OCL table and the routing set — no pixel data."""
    fixes = stage_stem and X5_CLUT_ROW_FIXES.get(stage_stem)
    if not fixes:
        return None
    out: dict[int, int] = {}
    for idx in chr256_set:
        if 0 <= idx < len(ocl):
            row = fixes.get((ocl[idx].col, ocl[idx].page))
            if row is not None:
                out[idx] = row
    return out or None


# ── X5 st070 localized additive-water bake ─────────────────────────────────────
# st070's reflective wet-floor "water" is a PSX semi-transparency (0x4000) effect whose
# in-game look is ADDITIVE blending over the reflected background, NOT the 50% alpha the STP
# bit yields (memory: x5-st070-water-is-clut-cycling-stp).  The renderer stacks X5's three
# parallax layers vertically into one tall image (thirds = front / middle / back; see
# x5-layer-compositing-recipe), so at render time a front-layer water tile has no background
# beneath it — additive over nothing goes near-black.  Rather than composite the whole scene,
# we bake the effect per tile: for each rendering water tile (col=2 -> CLUT row 66) that HAS
# an opaque background in the layers BEHIND it (per the back-to-front fold), each opaque water
# pixel F is replaced with clip(B + F // coeff) at full opacity, where B is that tile's local
# background composited from the layers behind it.  Baked opaque, the tile reads correctly BOTH
# in the flat per-layer render AND after a future 3-thirds fold (front draws last over the
# identical B).  st070's 128 middle-layer water tiles have an empty back layer behind them, so
# they have no B and are left at their STP translucency (additive over nothing is meaningless).
# Confirmed coeff = 2 (B+F/2 = best RMS; full additive B+F was mean-exact).  st070-scoped —
# only its water is characterised; the still-frame CLUT_ANIM_STILL_FRAMES fix supplies the F.
X5_ADDITIVE_WATER_STAGES: dict[str, int] = {
    # stem -> col value whose STP (0x4000) tiles at CLUT row col+64 are reflective water.
    "st070": 2,
}


def x5_additive_water(
    level_img,
    omp,
    ocl: list[OclEntry],
    layout: LayoutTable,
    n_sx: int,
    n_sy: int,
    stage_stem: "str | None",
    coeff: int = 2,
) -> int:
    """Bake the additive reflective sheen onto an X5 stage's STP water tiles, in place.

    Returns the number of tiles composited (0, image untouched, for stages without an entry
    in X5_ADDITIVE_WATER_STAGES).  Only opaque water pixels that have an opaque background in
    the layers behind them are modified, so the output is byte-identical everywhere else."""
    water_col = X5_ADDITIVE_WATER_STAGES.get(stage_stem) if stage_stem else None
    if water_col is None or n_sy % 3 != 0:
        return 0

    tiles_per_layer = (n_sy // 3) * 16
    th = tiles_per_layer * 16  # third height in px

    work = level_img.convert("RGBA")
    ref = work.copy().load()   # pristine pixel access for background reads
    dst = work.load()          # written in place
    modified = 0

    for sy in range(n_sy):
        for sx in range(n_sx):
            sc = layout.get(sx, sy)
            if sc is None or sc >= omp.n_screens:
                continue
            for wy in range(16):
                for wx in range(16):
                    t = omp.tiles[sc][wy * 16 + wx]
                    if t == 0 or not (t & 0x4000):
                        continue
                    idx = t & 0x3FFF
                    if idx >= len(ocl):
                        continue
                    e = ocl[idx]
                    if e.col != water_col or e.pad == 0xFF:
                        continue
                    lx, ly = sx * 16 + wx, sy * 16 + wy
                    layer = ly // tiles_per_layer
                    py_local = (ly % tiles_per_layer) * 16
                    px = lx * 16
                    tile_modified = False
                    for dy in range(16):
                        row_y = ly * 16 + dy
                        for dx in range(16):
                            col_x = px + dx
                            lr, lg, lb, la = ref[col_x, row_y]
                            if la == 0:
                                continue
                            # local background B = composite the layers strictly behind
                            # this one, back-to-front (third 2 backmost, then 1 over it, …).
                            br = bg = bb = ba = 0.0
                            for third in range(2, layer, -1):
                                sr, sg, sb, sal = ref[col_x, third * th + py_local + dy]
                                sa = sal / 255.0
                                inv = 1 - sa
                                br = sr * sa + br * inv
                                bg = sg * sa + bg * inv
                                bb = sb * sa + bb * inv
                                ba = sa + ba * inv
                            if ba <= 0:
                                continue
                            dst[col_x, row_y] = (
                                min(255, int(br + lr // coeff)),
                                min(255, int(bg + lg // coeff)),
                                min(255, int(bb + lb // coeff)),
                                255,
                            )
                            tile_modified = True
                    if tile_modified:
                        modified += 1

    if modified:
        level_img.paste(work, (0, 0))
    return modified
