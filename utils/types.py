from typing import TypedDict
from enum import IntEnum

type ColourRGB = tuple[int, int, int]
type ColourRGBA = tuple[int, int, int, int]
type Palette = list[ColourRGB]  # List of colours
type CLUT = list[Palette]  # Colour lookup table, 16 colours per row


class TexFormat(IntEnum):
    FORMAT_8BPP = 0x07  # Value 7
    FORMAT_4BPP = 0x12  # Value 18, TBC if 4bpp


class TexData(TypedDict):
    format_code: TexFormat
    width: int
    height: int
    mip_count: int
    raw_image: bytes
