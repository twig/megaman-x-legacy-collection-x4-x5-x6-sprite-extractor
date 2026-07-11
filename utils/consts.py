# pixels per tile
from pathlib import Path


TILE_SIZE = 16

# OCL tile-address bit layout: page/cordX/cordY are packed as 4-bit nibbles in
# the pad / clut_base bytes.
# Low nibble via ``& NIBBLE_MASK``
# High nibble via ``(byte >> NIBBLE_SHIFT) & NIBBLE_MASK``.
NIBBLE_MASK = 0xF
NIBBLE_SHIFT = 4

# TEX sheet page grid. A TEX sheet holds PAGES_PER_ROW 256px pages across;
# a page's pixel origin is (page % PAGES_PER_ROW, page // PAGES_PER_ROW) * 256
PAGES_PER_ROW = 8
# 4bpp / 8bpp split: pages 0 -> CHR256_PAGE_START are 4bpp (tex);
# pages CHR256_PAGE_START onwards are 8bpp and route to the chr256 (tex_bg) sheet.
CHR256_PAGE_START = 8

# Map layering
COMPOSED_ORDER_BASIC = [2, 1, 0]  # back-to-front
COMPOSED_ORDER_REVERSED = [2, 0, 1]  # back-to-front

# Paths
EXE_PATH_LC1 = Path("PC/RXC1.exe")
EXE_PATH_LC2 = Path("PC/RXC2.exe")
