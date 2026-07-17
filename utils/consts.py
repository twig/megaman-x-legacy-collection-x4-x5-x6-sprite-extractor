# pixels per tile
from pathlib import Path


TILE_SIZE = 16

# A screen is 16x16 tiles (so TILES_PER_SCREEN x TILE_SIZE pixels square).
TILES_PER_SCREEN = 16

# A CLUT / palette row holds CLUT_COLORS_PER_ROW colour entries.
CLUT_COLORS_PER_ROW = 16

# OCL tile-address bit layout: page/cordX/cordY are packed as 4-bit nibbles in
# the page_and_clutbank / tile_coords bytes.
# Low nibble via ``& NIBBLE_MASK``
# High nibble via ``(byte >> NIBBLE_SHIFT) & NIBBLE_MASK``.
NIBBLE_MASK = 0xF
NIBBLE_SHIFT = 4

# A VRAM/TEX page is PAGE_SIZE_PX x PAGE_SIZE_PX pixels.
PAGE_SIZE_PX = 256
# TEX sheet page grid. A TEX sheet holds PAGES_PER_ROW pages across;
# a page's pixel origin is (page % PAGES_PER_ROW, page // PAGES_PER_ROW) * PAGE_SIZE_PX
PAGES_PER_ROW = 8
# 4bpp / 8bpp split: pages 0 -> CHR256_PAGE_START are 4bpp (tex);
# pages CHR256_PAGE_START onwards are 8bpp and route to the chr256 (tex_bg) sheet.
CHR256_PAGE_START = 8
# Highest real 8bpp chr256 page nibble. Pages CHR256_PAGE_START..CHR256_PAGE_MAX
# (8..11) are the real 8bpp bitmap pages; a page nibble > CHR256_PAGE_MAX is the
# sky-fill sentinel territory (see PAD_SKYFILL_SENTINEL / pad=0x0F band-1 art).
CHR256_PAGE_MAX = 0xB

# OCL-index mask on a raw OMP u16 tile cell: the low 14 bits are the OCL index,
# the top 2 bits (0x8000 / 0x4000) are engine flag bits.
OCL_INDEX_MASK = 0x3FFF
# Bit 0x4000 of the raw OMP cell = PSX semi-transparency (STP)
STP_TRANSLUCENT_BIT = 0x4000

# Six-bit page field mask on the OCL ``page_and_clutbank`` byte: keeps the page nibble
# plus the page-band selector bit (0x10), while stripping the X6 pad_hi alt-bank bit (0x40).
PAGE_MASK_6bit = 0x3F
# page_and_clutbank byte sentinel meaning "no TEX data" - the crystal sky-fill slot, never real art.
PAD_SKYFILL_SENTINEL = 0xFF
# On pages >= CHR256_PAGE_START, this OCL col marks a chr256 (tex_bg) background tile
# (paired with col=0). See X6_BG_INDICATOR_COLS for the X6-specific pairing.
CHR256_COL_INDICATOR = 112

# Map layering
COMPOSED_ORDER_BASIC = [2, 1, 0]  # back-to-front
COMPOSED_ORDER_REVERSED = [2, 0, 1]  # back-to-front

# Paths
EXE_PATH_LC1 = Path("PC/RXC1.exe")
EXE_PATH_LC2 = Path("PC/RXC2.exe")
