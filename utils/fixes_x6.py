from utils.consts import TILE_SIZE, NIBBLE_MASK, NIBBLE_SHIFT, PAGES_PER_ROW, CHR256_PAGE_START, PAGE_SIZE_PX, CHR256_PAGE_MAX
from utils.ocl import load_ocl, OclEntry, OclPaletteGroup
from utils.omp import LayoutTable, build_chr256_ocl_indices
from utils.types import GameVersion, TexData

X6_BG_INDICATOR_COLS = (0, 112)   # page>=8 OCL cols that mark chr256 background tiles
X6_PALETTE_FAN_MIN_COLS = 4       # >= this many distinct cols at one atlas coord ⇒ a recolored
                                  # tile fanned into palette variants (only stsel/st02/st05 have any)
X6_CHR256_COL_MIN = 112           # within such a fan, col >= this is the chr256 background variant;
                                  # lower cols are foreground recolors (read tex)

# ── X6 per-stage chr256 routing overrides, by explicit OCL INDEX ─────────────────
#
# Companion to the (col, page, pad_hi) group table X6_SHEET_OVERRIDE_BY_STAGE below, for
# tiles the content heuristic mis-routes that do NOT form a clean group — their
# (col, page, pad_hi) group also contains correctly-routed sibling tiles, so only specific
# OCL indices can be corrected.  ``"bg"`` forces the index INTO chr256 (read tex_bg),
# ``"tex"`` forces it OUT (read tex).  Each index was ground-truth-confirmed (no counter-
# examples among its placements); see the scrapbook per-index salvage analysis.
#
# st04a "tex": the hydraulic-press / Metal-Shark machinery TOP band (col=0, page=10, pad_hi=4)
#   — genuinely FOREGROUND, but the col=0 chr256 indicator sweeps it into tex_bg where it draws
#   chains/mesh.  868-883 skips 874/879 (col=64 left-edge, already tex).  NOT the whole
#   (0,10,4) class — the separate 1505-1612 structure IS background — hence per-index.
# "bg" runs: page>=8 (and a few page<8) background tiles left on tex by the heuristic, in
#   small mixed groups (st06a col240/pg11, st03 col21/pg4, st08 col3/pg5, st01, st02) that do
#   NOT form a clean (col, page, pad_hi) group.  st00's tan-blob run and st05's page>=8 cols
#   DID form clean groups and live in X6_SHEET_OVERRIDE_BY_STAGE below instead.
X6_SHEET_OVERRIDE_INDICES: dict[str, "dict[int, str]"] = {
    "st04a": {i: "tex" for i in (set(range(868, 884)) - {874, 879}) | {920, 921, 922}},
    "st01":  {2627: "bg"},
    "st02":  {i: "bg" for i in (2627, 2628)},
    "st03":  {i: "bg" for i in range(2444, 2452)},
    "st06a": {i: "bg" for i in (2190, 2191, 2194, 2195, 2196, 2198, 2199, 2200, 2201, 2202,
                                2203, 2204, 2205, 2206, 2207, 2208, 2209, 2210, 2211, 2212,
                                2213, 2214, 2215, 2217, 2218, 2219, 2220, 2221, 2222, 2223,
                                2224, 2225, 2226, 2227, 2230, 2231, 2232)},
    "st08":  {i: "bg" for i in range(2578, 2584)},
    # st0h: the temple-banner top tiles 523/524 (col=24, page=1, tile_type 0x39 animated)
    #   render bright cyan/magenta stripes from tex_bg; the real gold/dark-blue banner art
    #   lives in tex, matching their 0x38 sibling 483 (tex@88).  Route them back to tex.
    "st0h":  {523: "tex", 524: "tex"},
}


# ── X6 per-stage tile-sheet overrides ────────────────────────────────────────────
#
# Per-stage (col, page, pad_hi) -> sheet corrections for tiles the content heuristic in
# build_x6_chr256_override mis-routes.  tex-vs-tex_bg is NOT a function of any single OCL/OMP
# field — the same (col, page, pad_hi) reads tex_bg in one stage and tex in another — so these
# groups are listed per stage and each was validated against ground truth (in-game captures).
# ``"bg"`` forces the group INTO chr256 (read tex_bg); ``"tex"`` forces it OUT (read tex).
# A group is listed only when ALL of its visibly-affected placements were confirmed correct
# (zero counter-examples) — see the scrapbook salvage analysis.  This (col,page,pad_hi) table
# is consulted regardless of pad_hi, so it cleanly handles both the pad_hi=4 alt-bank machinery
# and ordinary pad_hi=0 background groups in one mechanism.
#
#   st0g  (48,10/11,4)->bg     dormant-mechaniloid armour; RMS 9.9 vs st0g-goal.png (tex 63.8).
#   st06a (16/32/48,11,4)->bg  same pad_hi=4 machinery class as st0g.
#   st00  (96,9,0)+(4,9,0)->bg   page>=8 bg groups the heuristic left on tex; (4,9,0) is the
#                                out-of-place tan-blob run at x~2560,y~2590.
#   st05  (128/144/160, 9/10/11, 0)->bg   the machine-room block in the SE corner — page>=8 bg
#                                cols carrying real data in BOTH sheets, on cols never anchored
#                                as background, so no heuristic pass caught them.
#   st0h  (80,11,0)->bg / st0i (64,10,0)->bg   more page>=8 bg groups left on tex.
#   st04a (40/47/50/51,1,0)->tex   page-1 foreground tiles the duplicate-pair rule over-routed
#                                  to chr256.
# (st04a's page-10 col=0 sub-batch is handled per-index in X6_SHEET_OVERRIDE_INDICES above:
# other (0,10,4) tiles in that stage ARE genuine background, so it is not a clean
# (col,page,pad_hi) group.)
X6_SHEET_OVERRIDE_BY_STAGE: dict[str, "dict[tuple[int, int, int], str]"] = {
    # stem -> {(col, page, pad_hi): "bg" | "tex"}
    "st0g":  {(48, 10, 4): "bg", (48, 11, 4): "bg"},
    "st00":  {(96, 9, 0): "bg", (4, 9, 0): "bg"},
    "st05":  {(128, 9, 0): "bg", (144, 9, 0): "bg", (160, 9, 0): "bg",
              (128, 10, 0): "bg", (160, 10, 0): "bg", (160, 11, 0): "bg",
              # Underwater-room water (col 41/42, pages 1-2): the base router split these
              # mixed groups, sending ~half to tex_bg where they draw black/white noise; the
              # coherent smooth-water art is on tex.  Force the whole groups to tex.
              (41, 1, 0): "tex", (41, 2, 0): "tex", (42, 1, 0): "tex", (42, 2, 0): "tex",
              # Egyptian sunset background (col 54-65, pages 2-3, at x240-320 / y8608-8960):
              # the pharaoh statue + sunset sky tiles routed to tex_bg render as blocky garble;
              # the real art is on tex (the page 5-7 siblings of these cols are already tex).
              (54, 2, 0): "tex", (56, 2, 0): "tex", (56, 3, 0): "tex", (59, 2, 0): "tex",
              (60, 2, 0): "tex", (60, 3, 0): "tex", (61, 2, 0): "tex", (63, 2, 0): "tex",
              (64, 2, 0): "tex", (65, 3, 0): "tex"},
    "st0h":  {(80, 11, 0): "bg"},
    "st06a": {(16, 11, 4): "bg", (32, 11, 4): "bg", (48, 11, 4): "bg"},
    "st0i":  {(64, 10, 0): "bg"},
    "st04a": {(40, 1, 0): "tex", (47, 1, 0): "tex", (50, 1, 0): "tex", (51, 1, 0): "tex"},
}

def build_x6_chr256_override(
    ocl: list[OclEntry],
    tex: TexData,
    tex_background: TexData,
    stage_stem: "str | None" = None,
    gap_fill: bool = True,
    palette_fan_guard: bool = True,
    fg_pair_fix: bool = True,
    pg8_empty_bg: bool = True,
    garbage_page_flip: bool = True,
    strip_tail_extend: bool = True,
    interior_gap_bridge: bool = True,
    fg_strip_recover: bool = True,
    bg_empty_hole_fill: bool = True,
    pg8_garbage_hole_suppress: bool = True,
) -> frozenset[int]:
    """
    Return the chr256 (tex_background) OCL-index set for an X6 stage.

    Starts from the game-agnostic build_chr256_ocl_indices() routing and adds a
    trailing batch of background tiles on pages >= 8 that have no foreground
    counterpart in the OCL table — the base routing handles foreground/background
    duplicate pairs (page<8 and page>=8, via its Pass 3a-3c) but leaves these
    unpaired sole background tiles on tex because nothing pairs them.

    A page>=8 tile is added when its (page, col) matches a col already confirmed as
    background by the base routing, and tex / tex_background hold different non-empty
    pixel data at its coordinate (so the routing actually matters).

    Sole-entry gate: a (page, clut_base) coordinate that appears MORE THAN ONCE is a
    foreground/background duplicate pair, not an unpaired sole background tile.  Its
    first occurrence is the foreground tile (tex) and any background variant is the
    later occurrence, already routed by build_chr256_ocl_indices (Pass 3c).  Adding
    the first occurrence here would read the foreground texture for a background slot
    — e.g. st02's page=11 col=29 ice-incline tiles rendered as jagged foreground
    fragments instead of the smooth chr256 hill.  Background indicator cols (0/112)
    are exempt: a same-indicator-col duplicate (e.g. st04a page>=8 col=0 pairs) is
    genuinely background and must still be added.

    Per-stage sheet overrides close out (no-op when stage_stem is None/absent): the
    (col, page, pad_hi) groups in X6_SHEET_OVERRIDE_BY_STAGE[stage_stem] and the explicit OCL
    indices in X6_SHEET_OVERRIDE_INDICES[stage_stem] are each forced to their named sheet —
    ``"bg"`` ADDS the tile to chr256 (art the content passes leave on tex but really lives in
    tex_bg), ``"tex"`` REMOVES it.  Index entries take precedence over group entries.
    """
    base_chr256 = build_chr256_ocl_indices(ocl, tex, tex_background)
    extra = set(base_chr256)

    bg_raw = tex_background["raw_image"]
    bg_w = tex_background["width"]

    # Count occurrences per page>=8 (page, clut_base) coordinate for the sole-entry gate.
    pg8_coord_count: dict[tuple, int] = {}
    for entry in ocl:
        if entry.page >= CHR256_PAGE_START:
            key = (entry.page, entry.clut_base)
            pg8_coord_count[key] = pg8_coord_count.get(key, 0) + 1

    # Cols already confirmed as background by the base routing.
    confirmed_bg_page_col: set[tuple] = set()
    for idx in extra:
        entry = ocl[idx]
        if entry.page >= CHR256_PAGE_START:
            confirmed_bg_page_col.add((entry.page, entry.col))

    tx_raw = tex["raw_image"]
    tx_w = tex["width"]
    tx_h = len(tx_raw) // tx_w
    bg_h = len(bg_raw) // bg_w

    # Unpaired sole-background tiles (only runs when the base routing confirmed at
    # least one page>=8 background col; otherwise there is nothing to anchor to).
    if confirmed_bg_page_col:
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            if entry.page < CHR256_PAGE_START:
                continue
            if (entry.page, entry.col) not in confirmed_bg_page_col:
                continue
            # Sole-entry gate (see docstring): skip non-indicator duplicates.
            if (pg8_coord_count.get((entry.page, entry.clut_base), 0) > 1
                    and entry.col not in X6_BG_INDICATOR_COLS):
                continue
            gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h or
                    gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h):
                continue
            # Both textures must have non-empty, differing pixel data.
            if not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if all(tx_raw[(gy + dy) * tx_w + gx + dx] ==
                   bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Page>=8 empty-foreground background recovery ──────────────────────────
    #
    # The base routing classifies page>=8 background tiles using the col=0/112
    # chr256 palette indicators (omp.py Pass 3a/3b/3c) or large-span different-col
    # duplicate pairs.  A stage whose page>=8 background tileset uses NEITHER — sole
    # entries at distinct coordinates carrying ordinary palette cols (st0h's pages
    # 10-11 use cols 6/32/48/80/96) — is invisible to all of those passes, and the
    # "unpaired sole-background" pass above also skips it because that pass requires
    # an already-confirmed background (page, col) anchor AND a non-empty foreground
    # tile.  Result: st0h drew none of its ~160 page>=8 background tiles (the museum
    # walls/floors), leaving large holes.
    #
    # The unambiguous, anchor-free signal for these is: the FOREGROUND sheet (tex) is
    # EMPTY at the tile's coordinate while the chr256 sheet (tex_background) holds
    # real pixels.  A placed tile (non-zero OMP cell) whose foreground texture is
    # blank can only have come from the background sheet — there is nothing else to
    # draw.  Route every such page>=8 entry to tex_background.
    #
    # Regression safety: this is provably pixel-additive.  It only adds entries whose
    # tex tile is entirely empty, so before the change those tiles rendered NOTHING
    # (a fully-transparent paste).  Each level cell maps to exactly one OCL index, so
    # filling a previously-blank cell can neither alter nor occlude any pixel already
    # drawn by another tile.  It never removes an index from the set and never touches
    # page<8 routing, so X4/X5 (which don't call this) and every page<8 tile are
    # byte-identical.  Across the settled X6 stages the only tiles it adds are
    # OMP-referenced background tiles previously missing as holes (st00 +7, st04b +42,
    # st05 +33, st06a +18, st0h +160) — recoveries, not regressions.
    if pg8_empty_bg:
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            if entry.page < CHR256_PAGE_START:
                continue
            gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h or
                    gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h):
                continue
            # Foreground must be empty (tile would otherwise render nothing) and the
            # chr256 sheet must hold real pixels to draw instead.
            if any(tx_raw[(gy + dy) * tx_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Gap-fill pass: interior holes in a contiguous background strip ─────────
    #
    # A chr256 background tileset is laid out as horizontal strips: a run of
    # consecutive OCL indices that map to consecutive (page, clut_base) tile
    # coordinates.  The base routing's per-tile fill heuristic occasionally drops
    # a single fully-painted tile out of such a strip (it mistakes the dense pixel
    # data for a foreground object — e.g. st01's green-moss ridge transition tile
    # at OCL 2702, the lone gap in the 2695-2719 page-3 strip).
    #
    # An entry currently routed to tex whose immediate index neighbours (idx-1 and
    # idx+1) are BOTH background, on the SAME page, with clut_base forming a
    # consecutive triple (cb-1, cb, cb+1), is itself an interior strip member and
    # belongs on tex_bg.  Two guards keep genuine foreground tiles out:
    #   - The consecutive-clut_base requirement: a foreground tile interrupting the
    #     OCL order (e.g. st01 OCL 2627, whose neighbour jumps to another page)
    #     breaks the run and is never considered.
    #   - MIN_STRIP_RUN: the lockstep chr256 strip through idx must span at least
    #     this many tiles.  A genuine background tilemap strip (sky ridge, moss
    #     line, ice ridge, machinery wall) runs for dozens of tiles; a 2-4 tile
    #     run of background fragments inside a foreground-heavy region is NOT a
    #     strip.  Confirmed across X6: genuine strip gaps span >= 31 tiles
    #     (st01 2702→115, 2677→31; st02 2373→35; st04b 1116→112, 1132→40) while
    #     the foreground pole/chain region in st0h yields only 4-11 (470→4,
    #     505→11), which a threshold of 20 cleanly excludes.
    # tex_bg must hold pixel data at the coordinate for the swap to be meaningful.
    MIN_STRIP_RUN = 20
    pre_gap = frozenset(extra)  # snapshot: measure runs/neighbours order-independently

    def _strip_run(idx: int, page: int, cb: int) -> int:
        """Length of the lockstep chr256 strip (consecutive index + clut_base) through idx."""
        n = 1
        k = idx - 1
        while k >= 0 and k in pre_gap and ocl[k].page == page and ocl[k].clut_base == cb - (idx - k):
            n += 1; k -= 1
        k = idx + 1
        while k < len(ocl) and k in pre_gap and ocl[k].page == page and ocl[k].clut_base == cb + (k - idx):
            n += 1; k += 1
        return n

    for idx in range(1, len(ocl) - 1) if gap_fill else ():
        if idx in pre_gap:
            continue
        entry = ocl[idx]
        if entry.page >= CHR256_PAGE_START:
            continue
        if (idx - 1) not in pre_gap or (idx + 1) not in pre_gap:
            continue
        prev_e, next_e = ocl[idx - 1], ocl[idx + 1]
        if prev_e.page != entry.page or next_e.page != entry.page:
            continue
        if prev_e.clut_base != entry.clut_base - 1 or next_e.clut_base != entry.clut_base + 1:
            continue
        if _strip_run(idx, entry.page, entry.clut_base) < MIN_STRIP_RUN:
            continue
        gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
        gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
            continue
        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
            continue
        extra.add(idx)

    # ── Background-strip interior gap bridge (multi-tile) ─────────────────────
    #
    # The single-hole gap-fill above only bridges a ONE-tile hole (both immediate
    # OCL neighbours are tex_bg).  A chr256 background strip can instead lose a SHORT
    # RUN of interior tiles to tex: a contiguous lockstep clut_base sequence on one
    # page is routed to tex_bg except for a 2-4 tile stretch in its middle, which the
    # base routing pinned to tex.  This happens when those interior tiles are reused
    # foreground/background duplicates whose later (background) occurrence carries the
    # same col as the foreground first occurrence (col=0) plus a 0x38 hit-flash type:
    # the same-col 0x38 blocking rule forces the whole coordinate to tex, even though
    # in THIS placement the tile is an interior member of a tex_bg strip.  Confirmed
    # in st01 (OCL 2605-2606, clut_base 0xD6-0xD7): a 2-tile gap inside the lockstep
    # background run 2600-2615 (clut_base 0xD1-0xE0), drawn as a diagonal "smear"
    # interrupting the mossy-rock cluster wherever those two slots are placed.
    #
    # Bridge a maximal run of tex-routed tiles when it is a genuine interior gap of a
    # long lockstep tex_bg strip:
    #   - the run lies on one page with clut_base advancing in lockstep with the OCL
    #     index (idx+1 ↔ clut_base+1), and the SAME lockstep continues unbroken across
    #     the brackets on both sides;
    #   - the tile immediately before the run and immediately after it are BOTH already
    #     tex_bg (the run is interior, not a strip end — strip ends are handled by
    #     strip_tail_extend);
    #   - the gap is at most _GAP_MAX tiles wide (a short dropout, not a foreground
    #     object spanning the strip);
    #   - the combined bracketing tex_bg run (left + right lockstep members) spans at
    #     least _GAP_MIN_BRACKET tiles (a real background strip, not a stray pair); and
    #   - tex_bg holds real pixels at every gap tile (background art to draw).
    # The lockstep-continuity + both-sides-bracketed + bracket-length gates make this
    # provably confined to interior dropouts of a continuous background strip; verified
    # across every X6 stage to add only st01's 2 tiles and touch nothing else.
    _GAP_MAX = 4
    _GAP_MIN_BRACKET = 12
    pre_bridge = frozenset(extra)

    def _bg_run_len(start: int, step: int, page: int, cb0: int) -> int:
        """Length of the lockstep tex_bg run from `start` going by `step` (±1)."""
        n = 0
        k = start
        want = cb0
        while (0 <= k < len(ocl) and k in pre_bridge and ocl[k].page == page
               and ocl[k].clut_base == want):
            n += 1; k += step; want += step
        return n

    if interior_gap_bridge:
        idx = 1
        while idx < len(ocl):
            if idx in pre_bridge:
                idx += 1; continue
            entry = ocl[idx]
            # Left bracket: previous index must be a tex_bg lockstep predecessor.
            prev = ocl[idx - 1]
            if (entry.page >= CHR256_PAGE_START or (idx - 1) not in pre_bridge
                    or prev.page != entry.page
                    or prev.clut_base != entry.clut_base - 1):
                idx += 1; continue
            # Collect the maximal run of tex (not-bg) lockstep tiles starting at idx.
            run = [idx]
            j = idx + 1
            while (j < len(ocl) and j not in pre_bridge and ocl[j].page == entry.page
                   and ocl[j].clut_base == ocl[j - 1].clut_base + 1
                   and len(run) <= _GAP_MAX):
                run.append(j); j += 1
            # Right bracket: tile after the run must be a tex_bg lockstep successor.
            nxt = ocl[j] if j < len(ocl) else None
            ok = (len(run) <= _GAP_MAX and nxt is not None and j in pre_bridge
                  and nxt.page == entry.page
                  and nxt.clut_base == ocl[j - 1].clut_base + 1)
            if ok:
                left_len = _bg_run_len(idx - 1, -1, entry.page, entry.clut_base - 1)
                right_len = _bg_run_len(j, +1, entry.page, nxt.clut_base)
                if left_len + right_len >= _GAP_MIN_BRACKET:
                    for g in run:
                        e = ocl[g]
                        gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
                        gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
                        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                            continue
                        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                            continue
                        extra.add(g)
            idx = j + 1 if ok else idx + 1

    # ── Palette-fan col split ─────────────────────────────────────────────────
    #
    # A texture coordinate shared by MANY distinct `col` (palette) values is a tile
    # that has been recolored into several palette variants: the foreground
    # variants (the stage-select boss panels, the st05/st02 recolored objects) plus
    # ONE chr256 background variant at the same coordinate.  The base routing's
    # large-gap different-col rules route ALL the far/different-col occurrences to
    # chr256, so the intermediate FOREGROUND recolors get wrongly read from the
    # (often fragmentary) background sheet.
    #
    # Within such a fan, the chr256 background variant is the one whose col sits in
    # the high band (col >= X6_CHR256_COL_MIN — the 0x70/0xA0/0xB0 chr256 palette
    # rows seen as col 112/121/126/160/176 in stsel/st02/st05); the lower-col
    # variants are foreground recolors and read tex.  Per-col (not per-coordinate)
    # is essential: an earlier per-coordinate version moved the whole group and so
    # also dragged the genuine col>=112 background onto tex (the st02/st05
    # regressions).
    #
    # The split only fires where a coordinate is fanned across
    # >= X6_PALETTE_FAN_MIN_COLS distinct cols.  Empirically that occurs ONLY on
    # stsel_eng / st02 / st05 — every settled gameplay stage has zero chr256
    # entries at such coords — so they are provably untouched.  Requiring BOTH a
    # high-band and a low-band member confines it to genuine mixed fg/bg fans and
    # avoids inverting same-band groups (e.g. st00's col=112 foreground over a
    # col=24 background, which never reaches >= 4 cols anyway).
    #
    # An all-low-band fan (NO col>=X6_CHR256_COL_MIN member, e.g. stsel's page-0
    # stage-name text, cols 35-40) has no background variant to anchor the split.
    # It is routed entirely to tex when tex_background is NOT a solid tile there
    # (bg_fill < 3/4 area) and tex holds some pixel data — i.e. the chr256 slot is
    # only fragments while the real glyph art lives in tex.  The solid-bg gate is
    # what keeps real all-low-band chr256 backgrounds on tex_bg: st05's page-0/1/2
    # recolor fans are fully painted (bg_fill == 256), so they are left alone.
    # Verified: among all X6 stages, only stsel_eng has all-low-band fans whose
    # background is non-solid, so no settled gameplay stage is affected.
    SOLID_FILL = (TILE_SIZE * TILE_SIZE * 3) // 4
    if palette_fan_guard:
        members_by_coord: dict[tuple, list[int]] = {}
        for i, entry in enumerate(ocl):
            members_by_coord.setdefault((entry.page, entry.clut_base), []).append(i)
        # Cols confirmed as foreground "text/recolor" palettes by the all-low-band
        # fan rule below; used to recover narrower (2-3 col) members of the same
        # recolored glyph set that fall under X6_PALETTE_FAN_MIN_COLS.  Empty for
        # every settled stage (none has such fans), so this never affects gameplay.
        fg_text_cols: set[int] = set()
        for (page, clut_base), idxs in members_by_coord.items():
            cols = {ocl[i].col for i in idxs}
            if len(cols) < X6_PALETTE_FAN_MIN_COLS:
                continue
            cordX = clut_base & NIBBLE_MASK
            cordY = (clut_base >> NIBBLE_SHIFT) & NIBBLE_MASK
            gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * TILE_SIZE
            gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # Routing only matters where the two sheets actually differ here.
            if all(tx_raw[(gy + dy) * tx_w + gx + dx] == bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            has_hi = any(c >= X6_CHR256_COL_MIN for c in cols)
            has_lo = any(c < X6_CHR256_COL_MIN for c in cols)
            if has_hi and has_lo:
                # Mixed fan: the lower-col variants are foreground recolors — remove
                # them from chr256.  The high-band variant's placement is LEFT TO THE
                # BASE ROUTING: it already routes genuine chr256 backgrounds (st05
                # col126, st02 col160/176) to tex_bg, and correctly keeps stsel's
                # col112 panel palette on tex.  Forcing high-band entries into chr256
                # here wrongly dragged those stsel panels onto the sparse background.
                for i in idxs:
                    if ocl[i].col < X6_CHR256_COL_MIN:
                        extra.discard(i)    # low-band variant → foreground (tex)
            elif not has_hi:
                # All-low-band fan: foreground when the chr256 slot is only
                # fragments (not a solid tile) and tex actually holds art.
                fg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if tx_raw[(gy + dy) * tx_w + gx + dx])
                bg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if bg_raw[(gy + dy) * bg_w + gx + dx])
                if bg_fill < SOLID_FILL and fg_fill > 0:
                    for i in idxs:
                        extra.discard(i)
                    fg_text_cols |= cols   # remember these recolor palettes

        # Recovery pass: a recolored glyph set may also appear with FEWER palette
        # variants (e.g. stsel's stage-name text at cb 0x12-0x15 uses only cols
        # 39/40, below X6_PALETTE_FAN_MIN_COLS).  Promote any remaining chr256 tile
        # whose col belongs to a confirmed text/recolor palette set, on an all-low
        # coordinate whose background is non-solid and whose foreground holds art.
        # Gated by fg_text_cols, which is empty on every gameplay stage.
        if fg_text_cols:
            for (page, clut_base), idxs in members_by_coord.items():
                if any(ocl[i].col >= X6_CHR256_COL_MIN for i in idxs):
                    continue
                if not any(i in extra and ocl[i].col in fg_text_cols for i in idxs):
                    continue
                cordX = clut_base & NIBBLE_MASK
                cordY = (clut_base >> NIBBLE_SHIFT) & NIBBLE_MASK
                gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * TILE_SIZE
                gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * TILE_SIZE
                if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                        gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                    continue
                bg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if bg_raw[(gy + dy) * bg_w + gx + dx])
                fg_fill = sum(1 for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)
                              if tx_raw[(gy + dy) * tx_w + gx + dx])
                if bg_fill < SOLID_FILL and fg_fill > 0:
                    for i in idxs:
                        if ocl[i].col in fg_text_cols:
                            extra.discard(i)

    # ── Foreground/background pair recovery ───────────────────────────────────
    # A small-span (< CHR256_PAIR_GAP) page<8 group whose members were ALL routed to
    # chr256 by the base "no-large-gap whole-group" rule is sometimes really a
    # foreground/background DUPLICATE pair: the FIRST occurrence is the foreground
    # tile (its art lives in tex) and the later occurrence(s) are the chr256
    # background variant.  build_chr256_ocl_indices._nolg_first_is_fg_pair catches
    # only the sparse-fragment form (fg*3 <= bg over a solid bg) and skips 0x38
    # first occurrences, so fully-painted foreground tiles (e.g. st0h's pole/chain
    # columns, tex_fill ~256) slip through and read the background sheet.
    #
    # Recover the first occurrence to tex when its coordinate holds non-empty tex
    # pixels that DIFFER from tex_bg (a genuine distinct foreground tile).
    if fg_pair_fix:
        # The chr256 background variant sits within this many OCL indices of the
        # foreground first occurrence for a genuine TIGHT fg/bg pair — st0h's
        # pole/chain pairs span at most 261.  Stages whose near-threshold no-large-gap
        # groups are real recolor batches (first occurrence correctly chr256
        # background) keep their second member farther away: st04a 307, st04b 347+,
        # st03 430.  This empirically-derived bound isolates the st0h pole case and
        # leaves every other X6 stage byte-identical; a looser bound regressed st03
        # (its dark-metal first occurrences turned to garbage when forced onto tex).
        CHR256_PAIR_MAX_GAP = 280
        groups: dict[tuple, list[int]] = {}
        for i, entry in enumerate(ocl):
            if entry.page < CHR256_PAGE_START:
                groups.setdefault((entry.page, entry.clut_base), []).append(i)
        for (page, clut_base), idxs in groups.items():
            if len(idxs) < 2:
                continue
            s = sorted(idxs)
            if (s[1] - s[0]) >= CHR256_PAIR_MAX_GAP:
                continue                       # background variant too far → not a tight pair
            if not all(i in extra for i in s):
                continue                       # only the "whole group → chr256" case
            cordX = clut_base & NIBBLE_MASK
            cordY = (clut_base >> NIBBLE_SHIFT) & NIBBLE_MASK
            gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * TILE_SIZE
            gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            fg_nonempty = any(tx_raw[(gy + dy) * tx_w + gx + dx]
                              for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            differs = any(tx_raw[(gy + dy) * tx_w + gx + dx] != bg_raw[(gy + dy) * bg_w + gx + dx]
                          for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            if fg_nonempty and differs:
                extra.discard(s[0])            # first occurrence → foreground (tex)

    # ── Foreground duplicate-strip recovery (seam-continuity vote) ────────────
    #
    # fg_pair_fix above recovers TIGHT foreground/background pairs (second member
    # within CHR256_PAIR_MAX_GAP=280 of the first).  A foreground tilemap stored as a
    # long contiguous strip whose every tile ALSO has a recolored duplicate FARTHER
    # away slips through: each (page, clut_base) is a no-large-gap group (span < 500,
    # so the base routing sends the whole group to tex_bg) but the second occurrence
    # sits 300-450 indices out — past the 280 bound that fg_pair_fix uses to avoid
    # regressing st03 (gap 430) and st04a (307).  Confirmed in st04b: OCL 1020-1156
    # (page 1, col=9, clut_base 0x48-0xD0) is the Recycle-Lab floor/machinery strip,
    # each tile reused in other areas as a col 5/16/21/22 recolor; all 137 first
    # occurrences were pinned to tex_bg and the floor rendered as scrambled garbage.
    #
    # The gap bound can't be widened without regressing st03/st04a (their first
    # occurrences ARE the background and belong on tex_bg), and within-tile coherence
    # does not separate them.  The decisive signal is SEAM CONTINUITY along the strip:
    # the CORRECT sheet renders texture-adjacent tiles (clut_base, clut_base+1) with a
    # continuous shared edge, the wrong sheet with a discontinuity.  Aggregated over a
    # whole lockstep run this cleanly separates the cases — mean seam |Δ| ratio
    # (tex_bg / tex): st04b 1.8 (tex continuous → foreground) vs st03 0.3, st04a 0.8,
    # st08x 1.0 (tex_bg continuous → stay background).
    #
    # For each maximal lockstep run (consecutive OCL index + clut_base, same page) of
    # FIRST occurrences of multi-col duplicate groups that are STILL wholly routed to
    # tex_bg at this point (so stsel/st0i/st0h, already moved to tex by the palette-fan
    # and fg_pair_fix passes above, are not candidates), route the whole run to tex
    # when the run spans >= _FGSTRIP_MIN_RUN tiles and the tex seams are clearly more
    # continuous than tex_bg (ratio >= _FGSTRIP_SEAM_RATIO).  Verified across every X6
    # stage to fire on st04b's strip alone and leave all other stages byte-identical.
    _FGSTRIP_MIN_RUN = 8
    _FGSTRIP_SEAM_RATIO = 1.4

    def _seam(raw: bytes, w: int, h: int, gx0: int, gy0: int, gx1: int, gy1: int) -> float:
        """Mean |Δ| down the vertical seam between tile0's right edge and tile1's left edge."""
        if (max(gy0, gy1) + TILE_SIZE > h or gx0 + TILE_SIZE > w or gx1 + TILE_SIZE > w):
            return -1.0
        tot = cnt = 0
        for dy in range(TILE_SIZE):
            a = raw[(gy0 + dy) * w + gx0 + TILE_SIZE - 1]
            b = raw[(gy1 + dy) * w + gx1]
            if a or b:
                tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    if fg_strip_recover:
        groups_fs: dict[tuple, list[int]] = {}
        for i, e in enumerate(ocl):
            groups_fs.setdefault((e.page, e.clut_base), []).append(i)

        def _is_fg_strip_cand(i: int) -> bool:
            e = ocl[i]
            if e.page >= CHR256_PAGE_START or i not in extra:
                return False
            idxs = groups_fs[(page, e.clut_base)]
            if len(idxs) < 2 or min(idxs) != i:
                return False                       # only a group's first occurrence
            return len({ocl[j].col for j in idxs}) >= 2   # mixed-col duplicate (fg/bg pair shape)

        def _xy(e: OclEntry) -> tuple[int, int]:
            return (e.page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE, (e.page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE

        i = 0
        nocl = len(ocl)
        while i < nocl:
            if not _is_fg_strip_cand(i):
                i += 1; continue
            run = [i]
            j = i + 1
            while (j < nocl and _is_fg_strip_cand(j)
                   and ocl[j].page == ocl[j - 1].page
                   and ocl[j].clut_base == ocl[j - 1].clut_base + 1):
                run.append(j); j += 1
            if len(run) >= _FGSTRIP_MIN_RUN:
                sum_t = sum_b = 0.0
                ns = 0
                for k in range(len(run) - 1):
                    gx0, gy0 = _xy(ocl[run[k]])
                    gx1, gy1 = _xy(ocl[run[k + 1]])
                    s_t = _seam(tx_raw, tx_w, tx_h, gx0, gy0, gx1, gy1)
                    s_b = _seam(bg_raw, bg_w, bg_h, gx0, gy0, gx1, gy1)
                    if s_t >= 0 and s_b >= 0:
                        sum_t += s_t; sum_b += s_b; ns += 1
                if ns and sum_t > 0 and (sum_b / sum_t) >= _FGSTRIP_SEAM_RATIO:
                    for g in run:
                        extra.discard(g)           # whole strip → foreground (tex)
            i = j

    # ── Garbage-foreground whole-page flip ────────────────────────────────────
    #
    # Some X6 stages store a background tileset across an ENTIRE page<8 as sole
    # entries (each (page, clut_base) coordinate appears exactly once, so there
    # are no multi-entry groups for the base routing's group rules to act on),
    # while that page's FOREGROUND sheet (tex) is corrupt — high-frequency striped
    # garbage — and the chr256 sheet (tex_bg) holds the real, coherent tile art.
    # Because the entries are sole and tex is non-empty (it is garbage, not blank),
    # none of the chr256 routing reaches them and the whole page renders as the
    # striped/garbled mess reported on st04a (pages 2 & 3) and st03 (page 5).
    #
    # The distinguishing signal is NOT fill or tex≠tex_bg difference — those also
    # match pages where tex is the CORRECT sheet and tex_bg is the garbage one
    # (st05 pages 4-7, st08 page 7) or where tex_bg is simply EMPTY (st0g pages
    # 2-3); routing those to tex_bg would regress them.  The only reliable
    # discriminator is COHERENCE: striped garbage has a high mean absolute
    # horizontal-neighbour difference of raw 8bpp indices (≈3.6-6.4 across the
    # corrupt pages), while coherent tile art has smooth runs (≈0.5-1.2).
    #
    # Flip a page tex→tex_bg only when ALL hold (verified across every X6 stage to
    # fire on exactly st03 p5, st04a p2, st04a p3 and nothing else):
    #   - page<8 and ≥95% of its entries are sole (no group rules apply);
    #   - ≥ _GPF_MIN_SOLE of those sole entries are still on tex;
    #   - tex_bg is non-empty over the page (it has real art to draw);
    #   - coh_tex ≥ _GPF_GARBAGE_MIN (tex is striped garbage); and
    #   - coh_bg ≤ coh_tex × _GPF_CLEAN_RATIO (tex_bg is clearly more coherent).
    # The ratio gate also excludes identical-sheet pages (coh_tex == coh_bg, e.g.
    # st06a/st06x, where routing is irrelevant anyway).
    _GPF_GARBAGE_MIN = 2.5
    _GPF_CLEAN_RATIO = 0.5
    _GPF_FRAC_SOLE = 0.95
    _GPF_MIN_SOLE = 40
    _GPF_BGFILL_MIN = 0.05

    def _page_coherence(raw: bytes, w: int, h: int, clut_bases, page: int) -> float:
        """Mean |horizontal-neighbour diff| of nonzero raw px over a page's tiles."""
        tot = cnt = 0
        for cb in clut_bases:
            cordX = cb & NIBBLE_MASK; cordY = (cb >> NIBBLE_SHIFT) & NIBBLE_MASK
            gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * TILE_SIZE
            gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * TILE_SIZE
            if gx + TILE_SIZE > w or gy + TILE_SIZE > h:
                continue
            for dy in range(TILE_SIZE):
                base = (gy + dy) * w + gx
                for dx in range(TILE_SIZE - 1):
                    a = raw[base + dx]; b = raw[base + dx + 1]
                    if a or b:
                        tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    def _page_bg_fill(clut_bases, page: int) -> float:
        """Fraction of nonzero tex_bg pixels over a page's tiles."""
        nz = total = 0
        for cb in clut_bases:
            cordX = cb & NIBBLE_MASK; cordY = (cb >> NIBBLE_SHIFT) & NIBBLE_MASK
            gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + cordX * TILE_SIZE
            gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + cordY * TILE_SIZE
            if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                continue
            for dy in range(TILE_SIZE):
                base = (gy + dy) * bg_w + gx
                for dx in range(TILE_SIZE):
                    if bg_raw[base + dx]:
                        nz += 1
                    total += 1
        return nz / total if total else 0.0

    if garbage_page_flip:
        # Per page<8: collect entry indices and coordinate occurrence counts.
        pg_entries: dict[int, list[int]] = {}
        pg_coord_count: dict[tuple, int] = {}
        for idx, entry in enumerate(ocl):
            page = entry.page
            if page >= CHR256_PAGE_START:
                continue
            pg_entries.setdefault(page, []).append(idx)
            k = (page, entry.clut_base)
            pg_coord_count[k] = pg_coord_count.get(k, 0) + 1

        for page, idxs in pg_entries.items():
            sole = [i for i in idxs
                    if pg_coord_count[(page, ocl[i].clut_base)] == 1]
            if len(sole) / len(idxs) < _GPF_FRAC_SOLE:
                continue
            sole_on_tex = [i for i in sole if i not in extra]
            if len(sole_on_tex) < _GPF_MIN_SOLE:
                continue
            distinct_cb = {ocl[i].clut_base for i in idxs}
            if _page_bg_fill(distinct_cb, page) < _GPF_BGFILL_MIN:
                continue
            coh_tex = _page_coherence(tx_raw, tx_w, tx_h, distinct_cb, page)
            coh_bg = _page_coherence(bg_raw, bg_w, bg_h, distinct_cb, page)
            if coh_tex < _GPF_GARBAGE_MIN or coh_bg > coh_tex * _GPF_CLEAN_RATIO:
                continue
            # tex is striped garbage, tex_bg holds the coherent art: route every
            # entry on this page whose tex_bg coordinate is non-empty to tex_bg.
            for i in idxs:
                gx = (page % PAGES_PER_ROW) * PAGE_SIZE_PX + ocl[i].cordX * TILE_SIZE
                gy = (page // PAGES_PER_ROW) * PAGE_SIZE_PX + ocl[i].cordY * TILE_SIZE
                if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                    continue
                if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                    extra.add(i)

    # ── Background-strip tail extension ───────────────────────────────────────
    #
    # A chr256 background tileset is sometimes stored as a foreground/background
    # DUPLICATE-PAIR batch: each (page, clut_base) coordinate appears twice — the
    # first occurrence (low OCL index) is the foreground tile (tex) and the second
    # (high index, different col) is the chr256 background variant (tex_bg), routed
    # by the base large-gap different-col rule (omp.py Pass 2 / Pass 3c).  The
    # second-occurrence halves form ONE contiguous OCL run whose indices and
    # clut_base advance in lockstep on a single page (e.g. st01 page-7 OCL
    # 3763-3827 ↔ clut_base 0x00-0x40, the Amazon river/ground background row).
    #
    # When the TAIL of such a strip loses its foreground partners, those coordinates
    # exist only as SOLE entries (n=1) — they continue the very same contiguous run
    # (st01 OCL 3828-3838 ↔ clut_base 0x41-0x4B, same page 7) but, having no
    # duplicate, the pair rule never fires and they default to tex.  Page 7's tex
    # sheet there is the corrupt striped foreground (coh ≈ 4.5-6.2) while tex_bg
    # holds the coherent art (coh ≈ 0.6-2.0), so they render as the garbled tiles
    # reported at level (176-179, 358-360).  The per-page garbage flip can't help
    # (page 7 is 92% paired, not a garbage page) and the single-hole gap-fill can't
    # bridge a contiguous run (each tile's idx+1 neighbour is also still on tex).
    #
    # Extend the strip: a tex-routed entry whose immediate index predecessor (idx-1)
    # is a confirmed tex_bg tile on the SAME page with clut_base exactly one less is
    # the next member of that background strip.  Route it to tex_bg when —
    #   - the backward lockstep tex_bg run through idx-1 spans ≥ _STE_MIN_RUN tiles
    #     (a genuine strip, not a stray pair);
    #   - tex_bg holds real pixels at the coordinate (background art to draw); and
    #   - the tex tile is EITHER empty (would render a transparent hole) OR striped
    #     garbage (coh ≥ _STE_GARBAGE_MIN and tex_bg clearly more coherent).  A
    #     coherent foreground tile fails this content gate and halts the extension,
    #     so the run can never bleed past the end of the real background strip.
    # Iterating index-ascending carries the flip down the whole tail (each freshly
    # flipped tile becomes the predecessor anchor for the next).
    #
    # Regression safety: structurally this only ever appends to the END of an
    # already-confirmed background strip (lockstep index+clut_base on one page), and
    # the content gate restricts it to empty or striped-garbage tex tiles — exactly
    # the tiles that rendered nothing or garbage before.  Each level cell maps to one
    # OCL index, so a flip can neither move nor occlude any other tile.  Verified
    # across every X6 stage to add only such strip-tail tiles (st01 +11) and touch
    # nothing on the settled stages.
    _STE_GARBAGE_MIN = 2.5
    _STE_CLEAN_RATIO = 0.5
    _STE_MIN_RUN = 8

    def _tile_coh(raw: bytes, w: int, gx: int, gy: int) -> float:
        """Mean |horizontal-neighbour diff| of nonzero raw px over one tile."""
        tot = cnt = 0
        for dy in range(TILE_SIZE):
            base = (gy + dy) * w + gx
            for dx in range(TILE_SIZE - 1):
                a = raw[base + dx]; b = raw[base + dx + 1]
                if a or b:
                    tot += abs(a - b); cnt += 1
        return tot / cnt if cnt else 0.0

    def _bg_strip_run_back(idx: int, page: int, cb: int) -> int:
        """Length of the lockstep tex_bg strip ending at idx-1 (consecutive index + clut_base)."""
        n = 0
        k = idx - 1
        want_cb = cb - 1
        while (k >= 0 and k in extra and ocl[k].page == page
               and ocl[k].clut_base == want_cb):
            n += 1; k -= 1; want_cb -= 1
        return n

    if strip_tail_extend:
        for idx in range(1, len(ocl)):
            if idx in extra:
                continue
            entry = ocl[idx]
            if entry.page >= CHR256_PAGE_START:
                continue
            if (idx - 1) not in extra:
                continue
            prev = ocl[idx - 1]
            if prev.page != entry.page or prev.clut_base != entry.clut_base - 1:
                continue
            gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if _bg_strip_run_back(idx, entry.page, entry.clut_base) < _STE_MIN_RUN:
                continue
            # Content gate: empty tex (transparent hole) or striped garbage tex.
            fg_empty = not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                               for dy in range(TILE_SIZE) for dx in range(TILE_SIZE))
            if not fg_empty:
                coh_tex = _tile_coh(tx_raw, tx_w, gx, gy)
                coh_bg = _tile_coh(bg_raw, bg_w, gx, gy)
                if coh_tex < _STE_GARBAGE_MIN or coh_bg > coh_tex * _STE_CLEAN_RATIO:
                    continue
            extra.add(idx)

    # ── Background-batch empty-hole suppression ───────────────────────────────
    #
    # After all routing (including the garbage-page flip above), a few tiles can
    # remain on tex as INTERIOR stragglers inside a chr256 background batch: both
    # their OCL-index neighbours route to tex_bg on the same page, but the tile's
    # OWN tex_bg slot is empty, so the base/flip routing left it on tex.  When that
    # tile's tex slot holds the corrupt striped-garbage foreground, it renders as a
    # garbage box surrounded by clean background (st03's two remaining holes:
    # ocl 2676 page 4, ocl 2747 page 5).  There is no real art for the tile in
    # EITHER sheet, so the correct render is transparent — route it to the empty
    # tex_bg slot (all-zero pixels → fully transparent paste) instead of drawing
    # the garbage.
    #
    # Gates (verified to touch EXACTLY these 2 placed tiles across all X6 stages —
    # zero impact elsewhere):
    #   - tile currently on tex (not already chr256), page<8;
    #   - both OCL neighbours (idx-1, idx+1) route to tex_bg, on the SAME page
    #     (interior to a contiguous background batch — not a lone foreground tile);
    #   - tex_bg is fully empty at the tile's coordinate (no background art); and
    #   - tex is non-empty (there is garbage to suppress; an already-empty tex tile
    #     renders nothing regardless, so adding it would be a redundant no-op).
    # The neighbour gate is what keeps genuine sparse foreground tiles (sparkles,
    # edges, glyph pixels with high coherence but no surrounding bg batch) on tex.
    if bg_empty_hole_fill:
        for idx in range(1, len(ocl) - 1):
            if idx in extra:
                continue
            entry = ocl[idx]
            if entry.page >= CHR256_PAGE_START:
                continue
            if (idx - 1) not in extra or (idx + 1) not in extra:
                continue
            if ocl[idx - 1].page != entry.page or ocl[idx + 1].page != entry.page:
                continue
            gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # tex_bg fully empty (no real art) and tex non-empty (garbage to hide).
            if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if not any(tx_raw[(gy + dy) * tx_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            extra.add(idx)

    # ── Page>=8 background-strip garbage-hole suppression ─────────────────────
    #
    # bg_empty_hole_fill suppresses garbage holes interior to a page<8 background
    # batch, keyed on OCL-index neighbours.  The page>=8 chr256 strips are ordered
    # by clut_base WITHIN a (page, col), not by OCL index, so an interior empty-tex_bg
    # hole there is invisible to index-neighbour logic.  st08's machinery gap (page
    # 11, col 10, clut_base 0xF1-0xF4) is such a block: 4 placed tiles whose tex_bg
    # slot is empty sit inside the clut_base span of the 136-tile (page 11, col 10)
    # background strip, with tex_bg-routed members at both lower and higher clut_base.
    # Their tex holds striped garbage (coh 8-70), drawn as colourful streaks in the
    # dark machinery.  No art exists in either sheet for these slots, so the correct
    # render is transparent — route them to the empty tex_bg.
    #
    # Gated to fire on exactly these tiles (verified zero elsewhere across X6):
    #   - page in 8..0xB, tile currently on tex, tex_bg fully empty at its coordinate;
    #   - tex holds striped garbage (coh_tex >= _PG8H_GARBAGE_MIN); and
    #   - the tile's (page, col) strip has a tex_bg-routed member at BOTH a smaller and
    #     a larger clut_base (the hole is interior to a real background strip, not a
    #     lone foreground tile).
    # Like bg_empty_hole_fill this is pixel-additive: it only routes already-garbage
    # placed tiles to an empty (transparent) slot, never altering any other tile.
    _PG8H_GARBAGE_MIN = 5.0
    if pg8_garbage_hole_suppress:
        bg_cb_by_pagecol: dict[tuple, list[int]] = {}
        for i, e in enumerate(ocl):
            if e.page >= CHR256_PAGE_START and i in extra:
                bg_cb_by_pagecol.setdefault((e.page, e.col), []).append(e.clut_base)
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            if entry.page < CHR256_PAGE_START or entry.page > CHR256_PAGE_MAX:
                continue
            members = bg_cb_by_pagecol.get((page, entry.col))
            if not members:
                continue
            if not (any(c < entry.clut_base for c in members) and any(c > entry.clut_base for c in members)):
                continue
            gx = (entry.page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            # tex_bg fully empty (no background art).
            if any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            # tex is striped garbage (otherwise it may be a legitimate sparse tile).
            if _tile_coh(tx_raw, tx_w, gx, gy) < _PG8H_GARBAGE_MIN:
                continue
            extra.add(idx)

    if stage_stem:
        # Per-stage sheet overrides: (col, page, pad_hi) GROUP table, plus a per-OCL-index
        # table for fixes that don't form a clean group.  Index entries win (more specific).
        # "bg" forces a tile INTO chr256 (read tex_bg); "tex" forces it OUT (read tex).
        group_ov = X6_SHEET_OVERRIDE_BY_STAGE.get(stage_stem, {})
        idx_ov = X6_SHEET_OVERRIDE_INDICES.get(stage_stem, {})
        if group_ov or idx_ov:
            for idx, entry in enumerate(ocl):
                sheet = idx_ov.get(idx) or group_ov.get(
                    (entry.col, entry.page, entry.clut_bank_selector))
                if sheet == "bg":
                    extra.add(idx)
                elif sheet == "tex":
                    extra.discard(idx)
    return frozenset(extra)


# ── X6 per-stage CLUT-row fixes ─────────────────────────────────────────────────
#
# This table is now EMPTY — every X6 per-index CLUT-row fix has been eliminated:
#   • st04a (138) / st04b (16): proven redundant with the pad_hi=4 bank rule and removed
#     (the only real correction was st04a's (0,10) row in X6_PADHI_ROW_BY_STAGE).
#   • st00 (2): the flat backdrop is now sourced from st00.col via CLUT_ANIM_STILL_FRAMES.
# Kept as an (empty) table + build_x6_clut_row_override hook so a future genuinely
# per-index fix has a home.  Keyed by OMP stem -> {ocl_idx : corrected CLUT row}.
X6_CLUT_ROW_FIXES: dict[str, dict[int, int]] = {
}


def build_x6_clut_row_override(
    stage_stem: str,
    ocl: list[OclEntry],
    chr256_set: "frozenset[int]",
) -> "dict[int, int] | None":
    """
    Return {ocl_idx: corrected_clut_row} for an X6 stage from X6_CLUT_ROW_FIXES, or
    None when the stage has no fixes.  Fixes are keyed by explicit OCL index (see
    X6_CLUT_ROW_FIXES) so only the validated tiles are relocated.  Indices beyond the
    stage's OCL table are dropped.  The chr256_set argument is accepted for signature
    stability but is not used (the CLUT row is texture-routing-independent).

    NOTE: the X6 "inverted shadows" class (page>=8 pad_hi=0 8bpp tiles, e.g. the boss-bg
    of the sub-stages) is NOT handled here.  It is a GENERAL renderer rule — those tiles
    read the raw, un-normalized stage CLUT at col+96 — applied via the x6_page8_palette
    argument to render_level/render_omp.  See utils/omp._X6_PAGE8_CLUT_OFFSET.
    """
    fixes = X6_CLUT_ROW_FIXES.get(stage_stem)
    if not fixes:
        return None
    override = {idx: row for idx, row in fixes.items() if 0 <= idx < len(ocl)}
    return override or None


# ── X6 CLUT-bank rule (pad_hi) ───────────────────────────────────────────────────
#
# ROOT CAUSE of the page>=8 "wrong colour" machinery tiles: the OCL ``pad`` byte's
# HIGH nibble ``(pad >> 4) & 0xF`` is an X6 CLUT-bank selector that the universal
# ``col + 64`` lookup ignores — both this renderer and the game's own TeheManX4
# Draw16xTile discard it via ``page = (val >> 24) & 0xF``.  ``pad_hi == 0`` is correct
# at col+64 for all cols; ``pad_hi == 4`` occurs ONLY on the machinery tiles and needs
# an alternate CLUT bank in the BOTTOM half of VRAM.
#
# DATA-DERIVED DEFAULT: ``alt_row = X6_PADHI_DEFAULT_BANK + col`` (= 320 + col).  This is
# the +96 stage-CLUT offset (X6_STAGE_CLUT_OFFSET) mirrored into VRAM's bottom half: in
# normalized-palette space the page>=8 CLUTs sit at row 320+col.  Verified exact for st02
# (col0→320, col16→336), st06a col0→320, st04b col0→320, and st0g col0/16/80/96
# (→320/336/400/416).  See experimental/diag_bank_table_search.py for the reconciliation
# (full RXC2.exe survey found no separate per-stage bank table; the clut-anime tables hold
# only crystal dests 64-127).
#
# Per-stage EXCEPTIONS (X6_PADHI_ROW_BY_STAGE) override the default where a stage uploaded
# its alt CLUTs to a different bottom-half row.  These are genuine deviations (re-confirmed
# vs the rule, not mis-pins): st04a (whole stage, lower bank), st04b col=16.
# A wrong row shows as a slight hue shift (right col band, wrong row) or a gross mismatch
# (wrong col entirely).  Validated by RMS (st04a) and ground-truth match (st04b).
X6_PADHI_ALT_BANK = 4
X6_PADHI_DEFAULT_BANK = 320  # alt_row = 320 + col  (+96 stage-CLUT offset, bottom VRAM half)
X6_PADHI_ROW_BY_STAGE: dict[str, dict[tuple[int, int], int]] = {
    # stage -> {(col, page): alt_clut_row} for groups that DEVIATE from the 320+col default.
    # Everything not listed uses 320 + col.
    # st04a: whole-stage lower bank (col0→288, col16→192).  RMS-validated (err ~3-7);
    # (0,10)→192 is contact-sheet-only.
    "st04a": {(16, 9): 192, (16, 10): 192, (16, 11): 192, (0, 10): 288, (0, 11): 288},
    # st04b col=16: silver spikes at 368 (default 336 renders garbage — coherence-confirmed).
    "st04b": {(16, 10): 368},
}


def build_x6_padhi_clut_override(ocl: list[OclEntry], stage_stem: str) -> "dict[int, int]":
    """
    Return {ocl_idx: alt_clut_row} for every page>=8 tile whose ``pad`` high nibble is
    the alternate-bank selector (X6_PADHI_ALT_BANK).  The default row is the data-derived
    ``X6_PADHI_DEFAULT_BANK + col`` (320 + col); a per-(col, page) entry in
    X6_PADHI_ROW_BY_STAGE overrides it for stages whose alt CLUTs live elsewhere.
    Game-version-agnostic input; only meaningful for X6.
    """
    by_col_page = X6_PADHI_ROW_BY_STAGE.get(stage_stem, {})
    out: dict[int, int] = {}
    for idx, entry in enumerate(ocl):
        if entry.clut_bank_selector != X6_PADHI_ALT_BANK:
            continue
        # Per-stage deviation wins; otherwise the universal 320 + col rule.
        out[idx] = by_col_page.get((entry.col, entry.page), X6_PADHI_DEFAULT_BANK + entry.col)
    return out
