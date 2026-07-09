# pixels per tile
from pathlib import Path


TILE_SIZE = 16

# Map layering
COMPOSED_ORDER_BASIC = [2, 1, 0]  # back-to-front
COMPOSED_ORDER_REVERSED = [2, 0, 1]  # back-to-front

# Paths
EXE_PATH_LC1 = Path("PC/RXC1.exe")
EXE_PATH_LC2 = Path("PC/RXC2.exe")
