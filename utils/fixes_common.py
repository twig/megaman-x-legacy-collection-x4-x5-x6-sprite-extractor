# CLUT-animation to still-image substitution
# Substitutes one frame of a CLUT animation so a still PNG shows the intended colours
# instead of the stale placeholder baked into the static COL.
#
# OMP stem -> (anim_col_filename | None, [(dest_clut_row, anim_src_row, length), ...]).
# Copy `length` consecutive CLUTs from an animated COL starting at anim_src_row into the
# static stage palette starting at dest_clut_row, BEFORE rendering.  anim_col_filename
# selects the source COL (resolved next to the game-files col_animate path); None uses the
# stage's default col_animate.
#
# The animated COL is loaded with stp_as_alpha, so STP-flagged effect rows render translucent.
CLUT_ANIM_STILL_FRAMES: "dict[str, tuple]" = {
    # SCR01_00 (X4 Web Spider Area 1): 2 animated waterfalls.
    "SCR01_00": (None, [(77, 0, 2), (109, 13, 1)]),
    # SCR01_01 (X4 Web Spider Area 2): water.
    "SCR01_01": (None, [(77, 0, 1)]),
    # st00 (X6 Intro Stage): dark-red glow
    # opaque=True forces alpha 255 (backdrop is opaque; carries
    # the STP bit which stp_as_alpha would otherwise make translucent)
    "st00": (None, [(107, 12, 1)], True),
    # st070 (X5 Spike Rosered): reflective-floor water tiles are STP
    "st070": (None, [(66, 195, 1)]),
}
