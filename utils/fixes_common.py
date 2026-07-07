# ── Still-image CLUT-animation substitution ──────────────────────────────────────
#
# OMP stem -> (anim_col_filename | None, [(dest_clut_row, anim_src_row, length), ...]).
# Copy `length` consecutive CLUTs from an animated COL starting at anim_src_row into the
# static stage palette starting at dest_clut_row, BEFORE rendering.  anim_col_filename
# selects the source COL (resolved next to the game-files col_animate path); None uses the
# stage's default col_animate.  This substitutes one frame of a CLUT animation so a still
# PNG shows the intended colours instead of the stale placeholder baked into the static COL.
# The animated COL is loaded with stp_as_alpha, so STP-flagged effect rows render translucent.
#
#   SCR01_00 (X4, Web Spider Area 1): TWO distinct animated waterfalls, both driven by
#     st1_0.col.
#     (a) FOREGROUND (layer 0) deep-blue fall: body col=13 -> CLUT row 77, edge col=14 -> 78.
#         Static col01_0X_eng.col holds a green/pink placeholder there.  st1_0 rows 0-1 are
#         the frame-0 deep-blue downward scroll (all STP); copy rows 0-1 -> CLUT rows 77-78.
#     (b) BACKGROUND (layer 2) light blue-grey fall: col=45 -> CLUT row 109.  Static row 109
#         holds a gold/orange placeholder at the animated water indices.  st1_0 carries a
#         SECOND, lighter cycle at rows 13/16/19/22 (a period-3 interleave; rows 14/17/20/23
#         are the dimmer partner stream).  Frame-0 of the light cycle is row 13 — copy it ->
#         CLUT row 109.  Verified empirically: applying st1_0 row 13 to the actual col=45 tile
#         pixel indices matches x4-spider-waterfall-bg.png far better (d~30) than the gold
#         static (d~54), the dimmer stream (d~39), or the deep-blue fg cycle (d~69).  All 46
#         col=45/page-7 OCL entries (225 placements) live in the layer-2 band — waterfall-only.
CLUT_ANIM_STILL_FRAMES: "dict[str, tuple]" = {
    "SCR01_00": (None, [(77, 0, 2), (109, 13, 1)]),
    # SCR01_01 (Web Spider Area 2): the OTHER section — col_animate is the teal st1_1.col.
    # Only col=13 -> row 77 is waterfall (col 14/15 unused); static col01_1X_eng.col row 77 is
    # a blue ramp with pink high-indices.  Copy st1_1 row 0 -> CLUT row 77 (length 1).
    "SCR01_01": (None, [(77, 0, 1)]),
    # st00 (X6 Intro Stage): the flat dark backdrop behind the machinery (OCL 2446/3038,
    # col=43 -> row 107, the ONLY col=43 tiles in the stage, a solid palette-index-3 fill)
    # is a static stand-in for a CLUT-animated slot.  In-game its colour is driven from
    # st00.col (the stage animated COL); set 12 is the dark-red phase.  Copy st00.col set 12
    # -> row 107 so the fill's colour comes from the game's own animation data instead of a
    # hard-coded CLUT row.  Sources from the default col_animate (st00.col); equals the old
    # row-129 override at the used index (index 3 = (8,0,0)).  See docs/x6-clut-anime-format.md.
    # opaque=True: force alpha 255 on the copied rows (unlike the X4 waterfalls, this backdrop
    # is opaque in-game; set 12 carries the STP bit, which stp_as_alpha would make translucent).
    "st00": (None, [(107, 12, 1)], True),
    # st070 (Spike Rosered): the reflective-floor "water" tiles are STP (0x4000) and use
    # col=2 -> CLUT row 66, a row the engine fills at runtime from the stage's animated COL
    # (st7_0.col).  The static col07_0x_eng.col holds a stale/corrupt frame there — idx0-11
    # are the correct muted blues but idx12-15 are garbage ((0,0,231) blue, (181,0,0) RED,
    # two greys), which paints red speckles on the water.  st7_0.col set 195 is the coherent
    # water frame (VRAM-confirmed; matches idx0-11 exactly and gives idx12-15 proper blues),
    # so copy set 195 -> row 66.  col=2/row 66 is WATER-EXCLUSIVE in st070 (204 STP placements,
    # 0 non-STP), so this is collateral-free.  Row 64 (col=0) also carries a few STP floor tiles
    # but is the stage's shared default col (4330 non-water placements) — NOT globally
    # substitutable — so it is deliberately left alone.  STP alpha (128, halved to 64 by the
    # 0x4000 bit) keeps the water translucent as before; only the colour is corrected.
    # NB the in-game reflective sheen additionally needs additive blending over the composited
    # background layer, which the current per-layer (non-composited) render cannot supply; see
    # memory x5-st070-water-is-clut-cycling-stp / x5-layer-compositing-recipe.
    "st070": (None, [(66, 195, 1)]),
}
