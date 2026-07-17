from utils.consts import TILE_SIZE, PAGES_PER_ROW, CHR256_PAGE_START, PAGE_SIZE_PX, CHR256_PAGE_MAX
from utils.ocl import load_ocl, OclEntry, OclPaletteGroup
from utils.omp import LayoutTable, build_chr256_ocl_indices
from utils.types import GameVersion, TexData

X6_BG_INDICATOR_COLS = (0, 112)   # page>=8 OCL cols that mark chr256 background tiles
X6_PALETTE_FAN_MIN_COLS = 4       # >= this many distinct cols at one atlas coord = a recolored
                                  # tile fanned into palette variants
X6_CHR256_COL_MIN = 112           # within such a fan, col >= this is the chr256 background variant;
                                  # lower cols are foreground recolors (read tex)

# X6 per-stage chr256 routing overrides, by explicit OCL INDEX.
#
# Companion to the (col, page, pad_hi) group table X6_SHEET_OVERRIDE_BY_STAGE below, for
# tiles the content heuristic mis-routes that do NOT form a clean group.  "bg" forces the
# index INTO chr256 (read tex_bg), "tex" forces it OUT (read tex).
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
    "st0h":  {523: "tex", 524: "tex"},
}


# X6 per-stage tile-sheet overrides.
#
# Per-stage (col, page, pad_hi) -> sheet corrections for tiles build_x6_chr256_override
# mis-routes.  tex-vs-tex_bg is NOT a function of any single OCL/OMP field (the same
# (col, page, pad_hi) reads tex_bg in one stage and tex in another), so groups are per-stage.
# "bg" forces the group INTO chr256 (read tex_bg); "tex" forces it OUT (read tex).
# Consulted regardless of pad_hi, so it handles both the pad_hi=4 alt-bank machinery and pad_hi=0
# background groups in one mechanism.
X6_SHEET_OVERRIDE_BY_STAGE: dict[str, "dict[tuple[int, int, int], str]"] = {
    # stem -> {(col, page, pad_hi): "bg" | "tex"}
    "st0g":  {(48, 10, 4): "bg", (48, 11, 4): "bg"},
    "st00":  {(96, 9, 0): "bg", (4, 9, 0): "bg"},
    "st05":  {(128, 9, 0): "bg", (144, 9, 0): "bg", (160, 9, 0): "bg",
              (128, 10, 0): "bg", (160, 10, 0): "bg", (160, 11, 0): "bg",
              (41, 1, 0): "tex", (41, 2, 0): "tex", (42, 1, 0): "tex", (42, 2, 0): "tex",
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
    counterpart in the OCL table -- the base routing handles foreground/background
    duplicate pairs (page<8 and page>=8, via its Pass 3a-3c) but leaves these
    unpaired sole background tiles on tex because nothing pairs them.

    A page>=8 tile is added when its (page, col) matches a col already confirmed as
    background by the base routing, and tex / tex_background hold different non-empty
    pixel data at its coordinate.

    Sole-entry gate: a (page, cordX, cordY) coordinate that appears MORE THAN ONCE is a
    foreground/background duplicate pair, not an unpaired sole background tile.  Its
    first occurrence is the foreground tile (tex) and any background variant is the
    later occurrence, already routed by build_chr256_ocl_indices (Pass 3c).  Background
    indicator cols (0/112) are exempt: a same-indicator-col duplicate (e.g. st04a page>=8
    col=0 pairs) is genuinely background and must still be added.

    Per-stage sheet overrides: the (col, page, pad_hi) groups in
    X6_SHEET_OVERRIDE_BY_STAGE[stage_stem] and the explicit OCL indices in
    X6_SHEET_OVERRIDE_INDICES[stage_stem] are each forced to their named sheet --
    "bg" ADDS the tile to chr256, "tex" REMOVES it.  Index entries take precedence over groups.
    """
    base_chr256 = build_chr256_ocl_indices(ocl, tex, tex_background)
    extra = set(base_chr256)

    bg_raw = tex_background["raw_image"]
    bg_w = tex_background["width"]

    # Count occurrences per page>=8 (page, cordX, cordY) coordinate for the sole-entry gate.
    pg8_coord_count: dict[tuple[int, int, int], int] = {}
    for entry in ocl:
        if entry.tex_page >= CHR256_PAGE_START:
            key = (entry.tex_page, entry.cordX, entry.cordY)
            pg8_coord_count[key] = pg8_coord_count.get(key, 0) + 1

    # Cols already confirmed as background by the base routing.
    confirmed_bg_page_col: set[tuple[int, int]] = set()
    for idx in extra:
        entry = ocl[idx]
        if entry.tex_page >= CHR256_PAGE_START:
            confirmed_bg_page_col.add((entry.tex_page, entry.col))

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
            if entry.tex_page < CHR256_PAGE_START:
                continue
            if (entry.tex_page, entry.col) not in confirmed_bg_page_col:
                continue
            # Sole-entry gate (see docstring): skip non-indicator duplicates.
            if (pg8_coord_count.get((entry.tex_page, entry.cordX, entry.cordY), 0) > 1
                    and entry.col not in X6_BG_INDICATOR_COLS):
                continue
            gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
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

    # Page>=8 empty-foreground background recovery.  Anchor-free signal: the FOREGROUND
    # sheet (tex) is EMPTY at the tile's coordinate while the chr256 sheet (tex_background)
    # holds real pixels -- a placed tile whose foreground is blank can only have come from
    # the background sheet, so route it to tex_background.  Pixel-additive (only fills
    # previously-blank cells).  Recovers page>=8 bg tiles missing as holes (e.g. st0h walls).
    if pg8_empty_bg:
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            if entry.tex_page < CHR256_PAGE_START:
                continue
            gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
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

    # Gap-fill pass: interior holes in a contiguous background strip.
    #
    # A chr256 background tileset is laid out as horizontal strips: consecutive OCL indices
    # mapping to consecutive (page, tile_coords).  The base fill heuristic occasionally drops
    # a single fully-painted tile out of such a strip.  An entry routed to tex whose immediate
    # neighbours (idx-1, idx+1) are BOTH background, same page, tile_coords forming a
    # consecutive triple (cb-1, cb, cb+1), is an interior strip member and belongs on tex_bg.
    # Guards: consecutive-tile_coords (a fg tile interrupting OCL order breaks the run) and
    # MIN_STRIP_RUN -- the lockstep chr256 strip through idx must span at least this many
    # tiles (real bg strips run dozens; short fg-region bg fragments are excluded).
    # tex_bg must hold pixel data at the coordinate for the swap to be meaningful.
    MIN_STRIP_RUN = 20
    pre_gap = frozenset(extra)  # snapshot: measure runs/neighbours order-independently

    def _strip_run(idx: int, page: int, cb: int) -> int:
        """Length of the lockstep chr256 strip (consecutive index + tile_coords) through idx."""
        n = 1
        k = idx - 1
        while k >= 0 and k in pre_gap and ocl[k].tex_page == page and ocl[k].tile_coords == cb - (idx - k):
            n += 1; k -= 1
        k = idx + 1
        while k < len(ocl) and k in pre_gap and ocl[k].tex_page == page and ocl[k].tile_coords == cb + (k - idx):
            n += 1; k += 1
        return n

    for idx in range(1, len(ocl) - 1) if gap_fill else ():
        if idx in pre_gap:
            continue
        entry = ocl[idx]
        if entry.tex_page >= CHR256_PAGE_START:
            continue
        if (idx - 1) not in pre_gap or (idx + 1) not in pre_gap:
            continue
        prev_e, next_e = ocl[idx - 1], ocl[idx + 1]
        if prev_e.tex_page != entry.tex_page or next_e.tex_page != entry.tex_page:
            continue
        if prev_e.tile_coords != entry.tile_coords - 1 or next_e.tile_coords != entry.tile_coords + 1:
            continue
        if _strip_run(idx, entry.tex_page, entry.tile_coords) < MIN_STRIP_RUN:
            continue
        gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
        gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
            continue
        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
            continue
        extra.add(idx)

    # Background-strip interior gap bridge (multi-tile).
    #
    # Unlike the single-hole gap-fill above, a chr256 background strip can lose a SHORT RUN
    # of interior tiles to tex: a contiguous lockstep tile_coords sequence on one page routed
    # to tex_bg except for a 2-4 tile stretch in its middle.  Bridge a maximal run of
    # tex-routed tiles when it is a genuine interior gap of a long lockstep tex_bg strip:
    #   - the run lies on one page, tile_coords in lockstep with the OCL index (idx+1 ->
    #     tile_coords+1), same lockstep continuing unbroken across the brackets on both sides;
    #   - tiles immediately before and after the run are BOTH already tex_bg (interior, not a
    #     strip end -- strip ends are handled by strip_tail_extend);
    #   - the gap is at most _GAP_MAX tiles wide;
    #   - the combined bracketing tex_bg run spans at least _GAP_MIN_BRACKET tiles; and
    #   - tex_bg holds real pixels at every gap tile.
    _GAP_MAX = 4
    _GAP_MIN_BRACKET = 12
    pre_bridge = frozenset(extra)

    def _bg_run_len(start: int, step: int, page: int, cb0: int) -> int:
        """Length of the lockstep tex_bg run from `start` going by `step` (+/-1)."""
        n = 0
        k = start
        want = cb0
        while (0 <= k < len(ocl) and k in pre_bridge and ocl[k].tex_page == page
               and ocl[k].tile_coords == want):
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
            if (entry.tex_page >= CHR256_PAGE_START or (idx - 1) not in pre_bridge
                    or prev.tex_page != entry.tex_page
                    or prev.tile_coords != entry.tile_coords - 1):
                idx += 1; continue
            # Collect the maximal run of tex (not-bg) lockstep tiles starting at idx.
            run = [idx]
            j = idx + 1
            while (j < len(ocl) and j not in pre_bridge and ocl[j].tex_page == entry.tex_page
                   and ocl[j].tile_coords == ocl[j - 1].tile_coords + 1
                   and len(run) <= _GAP_MAX):
                run.append(j); j += 1
            # Right bracket: tile after the run must be a tex_bg lockstep successor.
            nxt = ocl[j] if j < len(ocl) else None
            ok = (len(run) <= _GAP_MAX and nxt is not None and j in pre_bridge
                  and nxt.tex_page == entry.tex_page
                  and nxt.tile_coords == ocl[j - 1].tile_coords + 1)
            if ok and nxt:
                left_len = _bg_run_len(idx - 1, -1, entry.tex_page, entry.tile_coords - 1)
                right_len = _bg_run_len(j, +1, entry.tex_page, nxt.tile_coords)
                if left_len + right_len >= _GAP_MIN_BRACKET:
                    for g in run:
                        e = ocl[g]
                        gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
                        gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
                        if gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h:
                            continue
                        if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                                   for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                            continue
                        extra.add(g)
            idx = j + 1 if ok else idx + 1

    # Palette-fan col split.
    #
    # A texture coordinate shared by MANY distinct `col` (palette) values is a tile recolored
    # into several palette variants: foreground variants plus ONE chr256 background variant.
    # The base large-gap different-col rules route ALL far/different-col occurrences to chr256,
    # so the intermediate FOREGROUND recolors get wrongly read from the background sheet.
    #
    # Within such a fan the chr256 background variant is the one whose col is in the high band
    # (col >= X6_CHR256_COL_MIN); lower-col variants are foreground recolors and read tex.
    # Per-col (not per-coordinate) matters: moving the whole group drags the genuine col>=112
    # background onto tex.  Fires only where a coordinate is fanned across
    # >= X6_PALETTE_FAN_MIN_COLS distinct cols (only stsel_eng/st02/st05).  Requiring BOTH a
    # high-band and a low-band member confines it to genuine mixed fg/bg fans.
    #
    # An all-low-band fan (NO col>=X6_CHR256_COL_MIN member) has no background variant to
    # anchor the split; route it entirely to tex when tex_background is NOT a solid tile
    # (bg_fill < 3/4 area) and tex holds pixel data (chr256 slot is only fragments, real art
    # lives in tex).  The solid-bg gate keeps real all-low-band chr256 backgrounds on tex_bg.
    SOLID_FILL = (TILE_SIZE * TILE_SIZE * 3) // 4
    if palette_fan_guard:
        members_by_coord: dict[tuple[int, int, int], list[int]] = {}
        for i, entry in enumerate(ocl):
            members_by_coord.setdefault((entry.tex_page, entry.cordX, entry.cordY), []).append(i)
        # Cols confirmed as foreground "text/recolor" palettes by the all-low-band fan rule
        # below; used to recover narrower (2-3 col) members of the same recolored glyph set
        # that fall under X6_PALETTE_FAN_MIN_COLS.
        fg_text_cols: set[int] = set()
        for (page, cordX, cordY), idxs in members_by_coord.items():
            cols = {ocl[i].col for i in idxs}
            if len(cols) < X6_PALETTE_FAN_MIN_COLS:
                continue
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
                # Mixed fan: lower-col variants are foreground recolors -- remove them from
                # chr256.  High-band placement is LEFT TO THE BASE ROUTING (it already routes
                # genuine chr256 backgrounds to tex_bg and keeps stsel panels on tex).
                for i in idxs:
                    if ocl[i].col < X6_CHR256_COL_MIN:
                        extra.discard(i)    # low-band variant -> foreground (tex)
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

        # Recovery pass: a recolored glyph set may also appear with FEWER palette variants
        # (below X6_PALETTE_FAN_MIN_COLS).  Promote any remaining chr256 tile whose col belongs
        # to a confirmed text/recolor palette set, on an all-low coordinate whose background is
        # non-solid and whose foreground holds art.
        if fg_text_cols:
            for (page, cordX, cordY), idxs in members_by_coord.items():
                if any(ocl[i].col >= X6_CHR256_COL_MIN for i in idxs):
                    continue
                if not any(i in extra and ocl[i].col in fg_text_cols for i in idxs):
                    continue
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

    # Foreground/background pair recovery.
    # A small-span page<8 group all routed to chr256 by the base "no-large-gap whole-group"
    # rule is sometimes really a fg/bg DUPLICATE pair: the FIRST occurrence is the foreground
    # tile (art in tex), later occurrence(s) the chr256 background variant.
    # build_chr256_ocl_indices._nolg_first_is_fg_pair catches only the sparse-fragment form
    # and skips 0x38 first occurrences, so fully-painted foreground tiles slip through.
    # Recover the first occurrence to tex when its coordinate holds non-empty tex pixels that
    # DIFFER from tex_bg (a genuine distinct foreground tile).  Fixes st0h zip-lines.
    if fg_pair_fix:
        # The chr256 background variant sits within this many OCL indices of the fg first
        # occurrence for a genuine tight fg/bg pair; farther-apart groups are real recolor
        # batches whose first occurrence is correctly the chr256 background.
        CHR256_PAIR_MAX_GAP = 280
        groups: dict[tuple[int, int, int], list[int]] = {}
        for i, entry in enumerate(ocl):
            if entry.tex_page < CHR256_PAGE_START:
                groups.setdefault((entry.tex_page, entry.cordX, entry.cordY), []).append(i)
        for (page, cordX, cordY), idxs in groups.items():
            if len(idxs) < 2:
                continue
            s = sorted(idxs)
            if (s[1] - s[0]) >= CHR256_PAIR_MAX_GAP:
                continue # background variant too far -> not a tight pair
            if not all(i in extra for i in s):
                continue # only the "whole group -> chr256" case
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
                extra.discard(s[0]) # first occurrence -> foreground (tex)

    # Foreground duplicate-strip recovery (seam-continuity vote)
    #
    # A foreground tilemap stored as a long contiguous strip whose every tile ALSO has a
    # recolored duplicate FARTHER away (past fg_pair_fix's 280 bound) slips through: each
    # (page, cordX, cordY) is a no-large-gap group the base routing sends wholly to tex_bg.
    # The gap bound can't be widened without regressing st03/st04a, and within-tile coherence
    # doesn't separate them.  Decisive signal: SEAM CONTINUITY along the strip -- the CORRECT
    # sheet renders texture-adjacent tiles (tile_coords, tile_coords+1) with a continuous
    # shared edge, the wrong sheet with a discontinuity.
    #
    # For each maximal lockstep run (consecutive OCL index + tile_coords, same page) of FIRST
    # occurrences of multi-col duplicate groups STILL wholly routed to tex_bg here, route the
    # whole run to tex when it spans >= _FGSTRIP_MIN_RUN tiles and the tex seams are clearly
    # more continuous than tex_bg (mean seam |diff| ratio tex_bg/tex >= _FGSTRIP_SEAM_RATIO).
    _FGSTRIP_MIN_RUN = 8
    _FGSTRIP_SEAM_RATIO = 1.4

    def _seam(raw: bytes, w: int, h: int, gx0: int, gy0: int, gx1: int, gy1: int) -> float:
        """Mean |diff| down the vertical seam between tile0 right edge and tile1 left edge."""
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
        groups_fs: dict[tuple[int, int, int], list[int]] = {}
        for i, e in enumerate(ocl):
            groups_fs.setdefault((e.tex_page, e.cordX, e.cordY), []).append(i)

        def _is_fg_strip_cand(i: int) -> bool:
            e = ocl[i]
            if e.tex_page >= CHR256_PAGE_START or i not in extra:
                return False
            idxs = groups_fs[(e.tex_page, e.cordX, e.cordY)]
            if len(idxs) < 2 or min(idxs) != i:
                return False # only a group's first occurrence
            return len({ocl[j].col for j in idxs}) >= 2 # mixed-col duplicate (fg/bg pair)

        def _xy(e: OclEntry) -> tuple[int, int]:
            return (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE, (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE

        i = 0
        nocl = len(ocl)
        while i < nocl:
            if not _is_fg_strip_cand(i):
                i += 1; continue
            run = [i]
            j = i + 1
            while (j < nocl and _is_fg_strip_cand(j)
                   and ocl[j].tex_page == ocl[j - 1].tex_page
                   and ocl[j].tile_coords == ocl[j - 1].tile_coords + 1):
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
                        extra.discard(g)           # whole strip -> foreground (tex)
            i = j

    # -- Garbage-foreground whole-page flip ------------------------------------
    #
    # Some X6 stages store a background tileset across an ENTIRE page<8 as sole
    # entries (each (page, cordX, cordY) coordinate appears exactly once, so there
    # are no multi-entry groups for the base routing's group rules to act on),
    # while that page's FOREGROUND sheet (tex) is corrupt -- high-frequency striped
    # garbage -- and the chr256 sheet (tex_bg) holds the real, coherent tile art.
    # Because the entries are sole and tex is non-empty (it is garbage, not blank),
    # none of the chr256 routing reaches them and the whole page renders as the
    # striped/garbled mess on st04a (pages 2 & 3) and st03 (page 5).
    #
    # The distinguishing signal is NOT fill or tex!=tex_bg difference -- those also
    # match pages where tex is the CORRECT sheet and tex_bg is the garbage one
    # (st05 pages 4-7, st08 page 7) or where tex_bg is simply EMPTY (st0g pages
    # 2-3); routing those to tex_bg would regress them.  The only reliable
    # discriminator is COHERENCE: striped garbage has a high mean absolute
    # horizontal-neighbour difference of raw 8bpp indices (~=3.6-6.4 across the
    # corrupt pages), while coherent tile art has smooth runs (~=0.5-1.2).
    #
    # Flip a page tex->tex_bg only when ALL hold:
    #   - page<8 and >=95% of its entries are sole (no group rules apply);
    #   - >= _GPF_MIN_SOLE of those sole entries are still on tex;
    #   - tex_bg is non-empty over the page (it has real art to draw);
    #   - coh_tex >= _GPF_GARBAGE_MIN (tex is striped garbage); and
    #   - coh_bg <= coh_tex x _GPF_CLEAN_RATIO (tex_bg is clearly more coherent).
    _GPF_GARBAGE_MIN = 2.5
    _GPF_CLEAN_RATIO = 0.5
    _GPF_FRAC_SOLE = 0.95
    _GPF_MIN_SOLE = 40
    _GPF_BGFILL_MIN = 0.05

    def _page_coherence(raw: bytes, w: int, h: int, coords: set[tuple[int, int]], page: int) -> float:
        """Mean |horizontal-neighbour diff| of nonzero raw px over a page's tiles."""
        tot = cnt = 0
        for cordX, cordY in coords:
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

    def _page_bg_fill(coords: set[tuple[int, int]], page: int) -> float:
        """Fraction of nonzero tex_bg pixels over a page's tiles."""
        nz = total = 0
        for cordX, cordY in coords:
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
        pg_coord_count: dict[tuple[int, int, int], int] = {}
        for idx, entry in enumerate(ocl):
            page = entry.tex_page
            if page >= CHR256_PAGE_START:
                continue
            pg_entries.setdefault(page, []).append(idx)
            k = (page, entry.cordX, entry.cordY)
            pg_coord_count[k] = pg_coord_count.get(k, 0) + 1

        for page, idxs in pg_entries.items():
            sole = [i for i in idxs
                    if pg_coord_count[(page, ocl[i].cordX, ocl[i].cordY)] == 1]
            if len(sole) / len(idxs) < _GPF_FRAC_SOLE:
                continue
            sole_on_tex = [i for i in sole if i not in extra]
            if len(sole_on_tex) < _GPF_MIN_SOLE:
                continue
            distinct_coords = {(ocl[i].cordX, ocl[i].cordY) for i in idxs}
            if _page_bg_fill(distinct_coords, page) < _GPF_BGFILL_MIN:
                continue
            coh_tex = _page_coherence(tx_raw, tx_w, tx_h, distinct_coords, page)
            coh_bg = _page_coherence(bg_raw, bg_w, bg_h, distinct_coords, page)
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

    # -- Background-strip tail extension ---------------------------------------
    #
    # A chr256 background tileset is sometimes stored as a foreground/background
    # DUPLICATE-PAIR batch: each (page, cordX, cordY) coordinate appears twice -- the
    # first occurrence (low OCL index) is the foreground tile (tex) and the second
    # (high index, different col) is the chr256 background variant (tex_bg), routed
    # by the base large-gap different-col rule (omp.py Pass 2 / Pass 3c).  The
    # second-occurrence halves form ONE contiguous OCL run whose indices and
    # tile_coords advance in lockstep on a single page.
    #
    # When the TAIL of such a strip loses its foreground partners, those coordinates
    # exist only as SOLE entries (n=1) -- they continue the very same contiguous run
    # but, having no duplicate, the pair rule never fires and they default to tex.
    # Page 7's tex sheet there is the corrupt striped foreground (coh ~= 4.5-6.2)
    # while tex_bg holds the coherent art (coh ~= 0.6-2.0), so they render as the
    # garbled tiles reported at level (176-179, 358-360).  The per-page garbage flip
    # can't help (page 7 is 92% paired, not a garbage page) and the single-hole
    # gap-fill can't bridge a contiguous run (each tile's idx+1 neighbour is also
    # still on tex).
    #
    # Extend the strip: a tex-routed entry whose immediate index predecessor (idx-1)
    # is a confirmed tex_bg tile on the SAME page with tile_coords exactly one less is
    # the next member of that background strip.  Route it to tex_bg when --
    #   - the backward lockstep tex_bg run through idx-1 spans >= _STE_MIN_RUN tiles
    #     (a genuine strip, not a stray pair);
    #   - tex_bg holds real pixels at the coordinate (background art to draw); and
    #   - the tex tile is EITHER empty (would render a transparent hole) OR striped
    #     garbage (coh >= _STE_GARBAGE_MIN and tex_bg clearly more coherent).  A
    #     coherent foreground tile fails this content gate and halts the extension,
    #     so the run can never bleed past the end of the real background strip.
    # Iterating index-ascending carries the flip down the whole tail (each freshly
    # flipped tile becomes the predecessor anchor for the next).
    #
    # Regression safety: structurally this only ever appends to the END of an
    # already-confirmed background strip (lockstep index+tile_coords on one page), and
    # the content gate restricts it to empty or striped-garbage tex tiles -- exactly
    # the tiles that rendered nothing or garbage before.  Each level cell maps to one
    # OCL index, so a flip can neither move nor occlude any other tile.
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
        """Length of the lockstep tex_bg strip ending at idx-1 (consecutive index + tile_coords)."""
        n = 0
        k = idx - 1
        want_cb = cb - 1
        while (k >= 0 and k in extra and ocl[k].tex_page == page
               and ocl[k].tile_coords == want_cb):
            n += 1; k -= 1; want_cb -= 1
        return n

    if strip_tail_extend:
        for idx in range(1, len(ocl)):
            if idx in extra:
                continue
            entry = ocl[idx]
            if entry.tex_page >= CHR256_PAGE_START:
                continue
            if (idx - 1) not in extra:
                continue
            prev = ocl[idx - 1]
            if prev.tex_page != entry.tex_page or prev.tile_coords != entry.tile_coords - 1:
                continue
            gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
            if (gx + TILE_SIZE > bg_w or gy + TILE_SIZE > bg_h or
                    gx + TILE_SIZE > tx_w or gy + TILE_SIZE > tx_h):
                continue
            if not any(bg_raw[(gy + dy) * bg_w + gx + dx]
                       for dy in range(TILE_SIZE) for dx in range(TILE_SIZE)):
                continue
            if _bg_strip_run_back(idx, entry.tex_page, entry.tile_coords) < _STE_MIN_RUN:
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

    # -- Background-batch empty-hole suppression -------------------------------
    #
    # After all routing (including the garbage-page flip above), a few tiles can
    # remain on tex as INTERIOR stragglers inside a chr256 background batch: both
    # their OCL-index neighbours route to tex_bg on the same page, but the tile's
    # OWN tex_bg slot is empty, so the base/flip routing left it on tex.  When that
    # tile's tex slot holds the corrupt striped-garbage foreground, it renders as a
    # garbage box surrounded by clean background.
    # There is no real art for the tile in EITHER sheet, so the correct render is
    # transparent -- route it to the empty tex_bg slot
    # (all-zero pixels -> fully transparent paste) instead of drawing the garbage.
    #
    # Gates (verified to touch EXACTLY these 2 placed tiles across all X6 stages --
    # zero impact elsewhere):
    #   - tile currently on tex (not already chr256), page<8;
    #   - both OCL neighbours (idx-1, idx+1) route to tex_bg, on the SAME page
    #     (interior to a contiguous background batch -- not a lone foreground tile);
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
            if entry.tex_page >= CHR256_PAGE_START:
                continue
            if (idx - 1) not in extra or (idx + 1) not in extra:
                continue
            if ocl[idx - 1].tex_page != entry.tex_page or ocl[idx + 1].tex_page != entry.tex_page:
                continue
            gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
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

    # -- Page>=8 background-strip garbage-hole suppression ---------------------
    #
    # bg_empty_hole_fill suppresses garbage holes interior to a page<8 background
    # batch, keyed on OCL-index neighbours.  The page>=8 chr256 strips are ordered
    # by tile coordinate (raster order) WITHIN a (page, col), not by OCL index,
    # so an interior empty-tex_bg hole there is invisible to index-neighbour logic.
    # No art exists in either sheet for these slots, so the correct
    # render is transparent -- route them to the empty tex_bg.
    #
    # Gated to fire on exactly these tiles:
    #   - page in 8..0xB, tile currently on tex, tex_bg fully empty at its coordinate;
    #   - tex holds striped garbage (coh_tex >= _PG8H_GARBAGE_MIN); and
    #   - the tile's (page, col) strip has a tex_bg-routed member at BOTH a smaller and
    #     a larger tile coordinate (the hole is interior to a real background strip, not a
    #     lone foreground tile).
    _PG8H_GARBAGE_MIN = 5.0
    if pg8_garbage_hole_suppress:
        # Members are stored as (cordY, cordX) so tuple ordering matches the raster
        # scan (row-major) -- i.e. "a smaller / larger tile coordinate along the strip",
        # exactly the order the packed tile_coords byte gave.
        bg_coords_by_pagecol: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for i, e in enumerate(ocl):
            if e.tex_page >= CHR256_PAGE_START and i in extra:
                bg_coords_by_pagecol.setdefault((e.tex_page, e.col), []).append((e.cordY, e.cordX))
        for idx, entry in enumerate(ocl):
            if idx in extra:
                continue
            if entry.tex_page < CHR256_PAGE_START or entry.tex_page > CHR256_PAGE_MAX:
                continue
            members = bg_coords_by_pagecol.get((entry.tex_page, entry.col))
            if not members:
                continue
            here = (entry.cordY, entry.cordX)
            if not (any(c < here for c in members) and any(c > here for c in members)):
                continue
            gx = (entry.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordX * TILE_SIZE
            gy = (entry.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + entry.cordY * TILE_SIZE
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
                    (entry.col, entry.tex_page, entry.clut_bank_selector))
                if sheet == "bg":
                    extra.add(idx)
                elif sheet == "tex":
                    extra.discard(idx)
    return frozenset(extra)


# -- X6 per-stage CLUT-row fixes -------------------------------------------------
#
# This table is now EMPTY -- every X6 per-index CLUT-row fix has been eliminated:
#   - st04a (138) / st04b (16): proven redundant with the pad_hi=4 bank rule and removed
#     (the only real correction was st04a's (0,10) row in X6_PADHI_ROW_BY_STAGE).
#   - st00 (2): the flat backdrop is now sourced from st00.col via CLUT_ANIM_STILL_FRAMES.
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
    of the sub-stages) is NOT handled here.  It is a GENERAL renderer rule -- those tiles
    read the raw, un-normalized stage CLUT at col+96 -- applied via the x6_page8_palette
    argument to render_level/render_omp.  See utils/omp._X6_PAGE8_CLUT_OFFSET.
    """
    fixes = X6_CLUT_ROW_FIXES.get(stage_stem)
    if not fixes:
        return None
    override = {idx: row for idx, row in fixes.items() if 0 <= idx < len(ocl)}
    return override or None


# -- X6 CLUT-bank rule (pad_hi) ---------------------------------------------------
#
# The OCL ``page_and_clutbank`` byte's HIGH nibble is an X6 CLUT-bank selector that
# the universal ``col + 64`` lookup ignores as based on TeheManX4's Draw16xTile()
# discards it via ``page = (val >> 24) & 0xF``.  ``pad_hi == 0`` is correct at col+64
# for all cols; ``pad_hi == 4`` occurs ONLY on the machinery tiles and needs
# an alternate CLUT bank in the BOTTOM half of VRAM.
#
# Everything not listed uses ``alt_row = X6_PADHI_DEFAULT_BANK + col`` (320 + col).
# This is the +96 stage-CLUT offset (X6_STAGE_CLUT_OFFSET) mirrored into VRAM's bottom
# half: in normalized-palette space the page>=8 CLUTs sit at row 320+col.
#
# Per-stage EXCEPTIONS (X6_PADHI_ROW_BY_STAGE) override the default where a stage uploaded
# its alt CLUTs to a different bottom-half row. A wrong row shows as a slight hue shift
# (right col band, wrong row) or a gross mismatch (wrong col entirely).
X6_PADHI_ALT_BANK = 4
X6_PADHI_DEFAULT_BANK = 320  # alt_row = 320 + col  (+96 stage-CLUT offset, bottom VRAM half)
X6_PADHI_ROW_BY_STAGE: dict[str, dict[tuple[int, int], int]] = {
    # stage -> {(col, page): alt_clut_row}
    "st04a": {(16, 9): 192, (16, 10): 192, (16, 11): 192, (0, 10): 288, (0, 11): 288},
    "st04b": {(16, 10): 368},
}


def build_x6_padhi_clut_override(ocl: list[OclEntry], stage_stem: str) -> "dict[int, int]":
    """
    Return {ocl_idx: alt_clut_row} for every page>=8 tile whose ``page_and_clutbank``
    high nibble is the alternate-bank selector (X6_PADHI_ALT_BANK).
    Only meaningful for X6.
    """
    by_col_page = X6_PADHI_ROW_BY_STAGE.get(stage_stem, {})
    out: dict[int, int] = {}
    for idx, entry in enumerate(ocl):
        if entry.clut_bank_selector != X6_PADHI_ALT_BANK:
            continue
        out[idx] = by_col_page.get((entry.col, entry.tex_page), X6_PADHI_DEFAULT_BANK + entry.col)
    return out
