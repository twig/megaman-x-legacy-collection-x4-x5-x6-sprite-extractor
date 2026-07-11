# pixels per tile
from pathlib import Path


TILE_SIZE = 16

# OCL tile-address bit layout: page/cordX/cordY are packed as 4-bit nibbles in
# the pad / clut_base bytes.
# Low nibble via ``& NIBBLE_MASK``
# High nibble via ``(byte >> NIBBLE_SHIFT) & NIBBLE_MASK``.
NIBBLE_MASK = 0xF
NIBBLE_SHIFT = 4

# Map layering
COMPOSED_ORDER_BASIC = [2, 1, 0]  # back-to-front
COMPOSED_ORDER_REVERSED = [2, 0, 1]  # back-to-front

# Paths
EXE_PATH_LC1 = Path("PC/RXC1.exe")
EXE_PATH_LC2 = Path("PC/RXC2.exe")
