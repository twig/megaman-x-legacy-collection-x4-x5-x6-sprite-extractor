from typing import TypedDict
from enum import IntEnum

type ColourRGB = tuple[int, int, int]
type ColourRGBA = tuple[int, int, int, int]
type Palette = list[ColourRGBA]  # List of colours; alpha encodes STP: 255=opaque, 128=semi-transparent
type CLUT = list[Palette]  # Colour lookup table, 16 colours per row


class TexFormat(IntEnum):
    # https://github.com/RandomTBush/RTB-QuickBMS-Scripts/blob/master/Textures/CapcomMTFrameworkSwitch_TEX.bms
    FORMAT_32BPP = 0x07  # Value 7, BITPERPIX=32, BLOCKSIZE=128, ISCOMPRESSED=False
    FORMAT_8BPP = 0x12  # Value 18, TBC seems to be 8bpp (up from 4bpp in PSX) and maybe format BC3_UNORM_SRGB / BC3 / DXT5?


class TexData(TypedDict):
    format_code: TexFormat
    width: int
    height: int
    mip_count: int
    raw_image: bytes
