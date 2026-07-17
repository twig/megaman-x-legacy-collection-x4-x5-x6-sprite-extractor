from utils.consts import (
    TILE_SIZE, NIBBLE_MASK, NIBBLE_SHIFT, PAGES_PER_ROW, CHR256_PAGE_START, PAGE_SIZE_PX,
    TILES_PER_SCREEN, CHR256_PAGE_MAX, OCL_INDEX_MASK, STP_TRANSLUCENT_BIT,
)
from utils.ocl import OclEntry
from utils.types import TexData
from utils.omp import LayoutTable, build_chr256_ocl_indices, OmpLayer

# X5 background-tileset chr256 (tex_bg) recovery
#
# Some X5 stages store a background-LAYER tileset as a contiguous batch of OCL entries
# whose foreground-sheet (tex) data is leftover garbage while the real art lives in the
# chr256 sheet (tex_bg).  The game-agnostic build_chr256_ocl_indices leaves these on tex
# so they render incorrectly.  Using three independent signals, the correct data can be
# recovered for st061 sky, st070 jungle, st160 plasma, st000 skyline.
#
#   1. SHEET-WALK RUN (structure): a maximal run of >= MIN_RUN_LEN consecutive OCL indices
#      whose tile coordinate (page*256 + tile_coords) increments by exactly 1 -- a tileset
#      batch dumped in sheet order.  Authored foreground/object tilesets reference tiles in
#      semantic order, so their coordinates jump around and never form long runs.
#   2. BACKGROUND-EXCLUSIVE (placement): NO tile of the run is placed in layer 0.
#      Excludes mixed foreground/background batches and guarantees a byte-identical
#      foreground render.
#   3. TEX IS A COMB (content): the run's not-yet-chr256 tiles have, in tex, a horizontal-
#      minus-vertical transition count >= COMB_THRESHOLD (median).  A comb (vertical stripes,
#      columns ~constant) is the signature of garbage tex; real art (foreground detail OR a
#      coherent background already on tex) is isotropic (htr ~ vtr) or horizontal-scanline
#      (htr < vtr), so it scores below threshold.
#
# Only tiles not already routed by the base heuristic are added; tex_bg must be non-empty.
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
    table, the two TEX sheets and the level layout -- no per-stage data."""
    base = set(build_chr256_ocl_indices(ocl, tex, tex_bg))

    def _grid(t: "TexData", e: OclEntry) -> "list[list[int]] | None":
        raw = t["raw_image"]; w = t["width"]; h = len(raw) // w
        gx = (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE_SIZE
        gy = (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE_SIZE
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
        return e.tex_page * 256 + e.tile_coords

    # Placement: which OCL indices appear in the foreground layer (top third of the
    # vertical-stacked 3-layer layout) and which appear anywhere.
    fg_rows = (level_height_screens // 3) * TILES_PER_SCREEN  # tile rows belonging to layer 0
    placed_fg: set[int] = set()
    placed_all: set[int] = set()
    for sy in range(level_height_screens):
        for sx in range(level_width_screens):
            sid = layout.get(sx, sy)
            if sid is None or sid >= n_screens:
                continue
            screen = omp_tiles[sid]
            for wy in range(TILES_PER_SCREEN):
                ly = sy * TILES_PER_SCREEN + wy
                for wx in range(TILES_PER_SCREEN):
                    raw = screen[wy * TILES_PER_SCREEN + wx]
                    if not raw:
                        continue
                    idx = raw & OCL_INDEX_MASK
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
    # `moved`.  Shorter clean runs are only adopted when they CONNECT to a confirmed
    # one, in the absorption pass below (OCL order interleaves other pages' batches,
    # chopping one logical sheet into sub-MIN_RUN_LEN fragments).
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
        if ocl[i].tex_page >= CHR256_PAGE_START:
            i += 1
            continue
        j = i
        while (j + 1 < n and ocl[j + 1].tex_page < CHR256_PAGE_START
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
            moved.update(notbase)   # confirmed background tileset -- seed

    # Absorption: re-join short clean fragments to the sheet they belong to.  A fragment
    # is adopted when one of its tiles is tilepos-adjacent (same page, +/-1) to a tile
    # already confirmed as background.  Iterated to a fixpoint so a chain of fragments
    # all reach the confirmed anchor.  The per-fragment foreground guard is preserved
    # (each fragment was already vetted in _classify), so a foreground placement in one
    # part of a sheet can never drag in the rest.
    def _tp_key(k: int) -> "tuple[int, int]":
        return (ocl[k].tex_page, _tilepos(ocl[k]))

    moved_tp = {_tp_key(k) for k in moved}
    changed = True
    while changed:
        changed = False
        for notbase in runs:
            if all(k in moved for k in notbase):
                continue
            if any((ocl[k].tex_page, _tilepos(ocl[k]) - 1) in moved_tp
                   or (ocl[k].tex_page, _tilepos(ocl[k]) + 1) in moved_tp
                   for k in notbase):
                for k in notbase:
                    if k not in moved:
                        moved.add(k); moved_tp.add(_tp_key(k)); changed = True

    return frozenset(base | moved), len(moved)


# X5 per-stage tile-sheet (tex vs tex_bg) overrides
#
# Companion to the generic build_x5_chr256_bg_override: per-stage sheet corrections for
# page>=8 tiles whose true art lives in the OPPOSITE sheet from where the base router puts
# them.
# - ``"bg"`` forces a tile to read tex_bg (chr256)
# - ``"tex"`` forces tex.
# - Index entries win over group entries (more specific).
#
# The routing rule from PSX TeheManX4 editor (Draw16xTile) is purely PAGE-based:
# page<8 reads the 4bpp sheet (tex), page>=8 reads the 8bpp sheet (chr256/tex_bg),
# with NO col component.  The PC HD port re-packed the two sheets so the
# real art for a given page>=8 tile ended up on tex in some stages and on tex_bg in others;
# no per-tile content signal separates the two, so the corrections are listed per stage.
# stem -> {(col, page): "bg" | "tex"}
X5_SHEET_OVERRIDE_BY_STAGE: dict[str, "dict[tuple[int, int], str]"] = {
    "staff_eng": {(64, 11): "bg", (80, 10): "bg", (80, 11): "bg", (96, 10): "bg"},
    # (Burn Dinorex Area 2): boss-room bg
    "st041": {(16, 9): "bg"},
}
# stem -> {ocl_idx: "bg" | "tex"}
X5_SHEET_OVERRIDE_INDICES: dict[str, "dict[int, str]"] = {
    # (Burn Dinorex Area 1): dragon-head flamethrowers
    "st040": {i: "bg" for i in (1585, 1586, 1587, 1588, 1589, 1590, 1591, 1592, 1593,
                                1596, 1597, 1598, 1599, 1600, 1601, 1603, 1604, 1605,
                                1666, 1667, 2157, 2158, 2159, 2160, 2161)},
    # (Tidal Whale): two disjoint mis-routed batches
    #  (a) col=32 page-11 background comb-garble on tex
    #  (b) col=7 page-1/2/3 rock-wall batch around the boss room
    "st030": {
        **{i: "bg" for i in range(3385, 3510)},
        **{i: "bg" for i in (2139, 2140, 2141, 2142, 2143, 2146, 2147, 2179, 2195, 2196, 2197,
                             2435, 2641, 2642, 2643, 2644, 2645, 2646, 2647, 2648, 2649, 2650,
                             3369)},
    },
    # (Spike Rosered): three unrelated sheet fixes.
    #  (a) OCL 2879 -> solid rock block
    #  (b) col=9 pages 1/3 -> foreground jungle-rock tiles
    #  (c) col=59 layer-1 rock-silhouette batch
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
        sheet = idx_ov.get(idx) or group_ov.get((e.col, e.tex_page))
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
    (e.g. st120's boss-room), so those tiles read an ALL-ZERO tex block and draw nothing.

    The recovery here is the unambiguous case only: a page 8-0xB tile whose tex block is
    EMPTY while tex_bg holds real pixels.  Rerouting it to tex_bg can never regress a tile
    that was already drawing (tex was blank), so no per-stage table is needed.

    If BOTH sheets hold coherent-but-different art, fixes stay in X5_SHEET_OVERRIDE_INDICES;
    eg. st040 dragon heads)  The default ``col + 64`` CLUT row already renders these correctly,
    so no palette fix is paired with it.

    Pure function of the OCL table and the two TEX sheets."""
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
        if e.is_empty:
            continue  # sky-fill sentinel -- never real art
        # 8-0xB are the 8bpp bitmap pages; tex_page 15 is the page-band-1 art slot
        # (gy=256) that _resolve_tile also draws (X5 st170 Rangda Bangda W bg on tex_bg).
        if not (CHR256_PAGE_START <= e.tex_page <= CHR256_PAGE_MAX or e.tex_page == 15) or idx in out:
            continue
        gx = (e.tex_page % PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordX * TILE
        gy = (e.tex_page // PAGES_PER_ROW) * PAGE_SIZE_PX + e.cordY * TILE
        if _block_has_data(tex_raw, tex_w, tex_h, gx, gy) is False \
                and _block_has_data(bg_raw, bg_w, bg_h, gx, gy):
            out.add(idx)
            n_moved += 1
    return frozenset(out), n_moved


# X5 per-stage CLUT-row fixes
#
# A few X5 background-tileset (tex_bg) batches reference a CLUT row whose static colours
# are the wrong palette phase: the tile's ``col + 64`` row holds a dark/saturated variant
# while the correct (in-game) colours live at a different row of the same stage COL.  This
# is NOT the generic X6 tex_page>=8 / clut_bank_selector mechanism (X5 COL files are plain static palettes,
# not VRAM snapshots) and there is no clean cross-stage rule -- a blanket per-route offset
# regresses other tiles -- so the affected (col, page) groups are listed per stage and the
# corrected row validated.  Applied ONLY to chr256/tex_bg-routed tiles
# so any same-(col,page) foreground tile is untouched.
#
# stem -> {(col, page): corrected_clut_row}, applied to tex_bg-routed tiles only.
X5_CLUT_ROW_FIXES: dict[str, dict[tuple[int, int], int]] = {
    # (Shining Firefly Area 2): fix the deep-blue "window column" bg to cyan
    "st061": {(11, 2): 80, (11, 3): 80},
}


def build_x5_clut_row_override(
    stage_stem: "str | None",
    ocl: list[OclEntry],
    chr256_set: "frozenset[int]",
) -> "dict[int, int] | None":
    """Return {ocl_idx: corrected_clut_row} for an X5 stage from X5_CLUT_ROW_FIXES, or None.

    Only chr256/tex_bg-routed tiles (idx in chr256_set) whose (col, page) is listed for the
    stage are relocated, so foreground tiles sharing the same (col, page) are never touched."""
    fixes = stage_stem and X5_CLUT_ROW_FIXES.get(stage_stem)
    if not fixes:
        return None
    out: dict[int, int] = {}
    for idx in chr256_set:
        if 0 <= idx < len(ocl):
            row = fixes.get((ocl[idx].col, ocl[idx].tex_page))
            if row is not None:
                out[idx] = row
    return out or None


# X5 st070 localized additive-water bake
#
# Spike Rosered's wet-floor "water" is a PSX semi-transparency (0x4000) effect whose
# in-game look is ADDITIVE blending over the reflected background, NOT the 50% alpha the STP
# bit yields.
#
# stem -> col value whose STP (0x4000) tiles at CLUT row col+64 are reflective water.
X5_ADDITIVE_WATER_STAGES: dict[str, int] = {
    "st070": 2,
}


def x5_additive_water(
    level_img,
    omp: OmpLayer,
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
    the layers behind them are modified, so the output is byte-identical everywhere else.

    Rather than composite the whole scene, we bake the effect per tile: for each water tile that
    HAS an opaque background in the layers BEHIND it (per the back-to-front fold), each opaque
    water pixel F is replaced with clip(B + F // coeff) at full opacity, where B is that tile's
    local background composited from the layers behind it.

    Baked opaque, the tile reads correctly BOTH in the flat per-layer
    render AND after a future 3-thirds fold.  Middle-layer water tiles with an empty back layer
    have no B and are left at their STP translucency.  st070-scoped; the still-frame
    CLUT_ANIM_STILL_FRAMES fix supplies the F."""
    water_col = X5_ADDITIVE_WATER_STAGES.get(stage_stem) if stage_stem else None
    if water_col is None or n_sy % 3 != 0:
        return 0

    tiles_per_layer = (n_sy // 3) * TILES_PER_SCREEN
    th = tiles_per_layer * TILE_SIZE  # third height in px

    work = level_img.convert("RGBA")
    ref = work.copy().load()   # pristine pixel access for background reads
    dst = work.load()          # written in place
    modified = 0

    for sy in range(n_sy):
        for sx in range(n_sx):
            sc = layout.get(sx, sy)
            if sc is None or sc >= omp.n_screens:
                continue
            for wy in range(TILES_PER_SCREEN):
                for wx in range(TILES_PER_SCREEN):
                    t = omp.tiles[sc][wy * TILES_PER_SCREEN + wx]
                    if t == 0 or not (t & STP_TRANSLUCENT_BIT):
                        continue
                    idx = t & OCL_INDEX_MASK
                    if idx >= len(ocl):
                        continue
                    e = ocl[idx]
                    if e.col != water_col or e.is_empty:
                        continue
                    lx, ly = sx * TILES_PER_SCREEN + wx, sy * TILES_PER_SCREEN + wy
                    layer = ly // tiles_per_layer
                    py_local = (ly % tiles_per_layer) * TILE_SIZE
                    px = lx * TILE_SIZE
                    tile_modified = False
                    for dy in range(TILE_SIZE):
                        row_y = ly * TILE_SIZE + dy
                        for dx in range(TILE_SIZE):
                            col_x = px + dx
                            lr, lg, lb, la = ref[col_x, row_y]
                            if la == 0:
                                continue
                            # local background B = composite the layers strictly behind
                            # this one, back-to-front (third 2 backmost, then 1 over it, ...).
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
