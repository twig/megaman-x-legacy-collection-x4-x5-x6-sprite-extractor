# MegaMan X Legacy Collection 1 and 2 Sprite Extractor

Trying to find ways to make it easier for sprite rippers to get accurate sprites straight from the source.

`WIP:` currently only working with _some_ X5 assets

Remaining

- 4bpp TEX
- Animation sprites maybe?

# References for code

- [TileMolester](https://github.com/toruzz/TileMolester)
- [ARC format](https://www.watto.org/specs.html?specs=Archive_ARC_ARC_2)
- romhacking.net threads
  - [Megaman X PS1 Background Sprites Ripped](https://www.romhacking.net/forum/index.php?topic=36801.0)
  - [Mega Man X4 (PSX) Decompression Routine](https://www.romhacking.net/forum/index.php?topic=21330.0)
  - [Mega Man X Legacy Collection Sprites Extraction](https://www.romhacking.net/forum/index.php?topic=26730.0)
  - [Need help with MegaManX4 Sprites](https://www.romhacking.net/forum/index.php?topic=26749)
- [mmx5 improvement project addendum Workbook_2022.07.19.xlsx](https://archive.org/download/mmx5_improvement_project_addendum)
- [Mega Man X6 Tweaks Workbook](https://www.romhacking.net/documents/780/)
- [MT Framework .Tex files?](https://gbatemp.net/threads/mt-framework-tex-files.456868/)
- [r/mahvelmods Texture Tutorial](https://www.reddit.com/r/mahvelmods/wiki/textures/)
- [xdanieldzd's Scarlet.IO.ImageFormats/CapcomTEX.cs](https://github.com/xdanieldzd/Scarlet/blob/master/Scarlet.IO.ImageFormats/CapcomTEX.cs)
- [FrozenFish24's TurnaboutTools TEXporter](https://github.com/FrozenFish24/TurnaboutTools/blob/master/TEXporter/TEXporter/Program.cs)
- zenhax.com threads
  - [New M.T. Framework Texture Format](https://zenhax.com/viewtopic.php@t=15549.html)
- [AsteriskAmpersand's MHR_Tex_Chopper](https://github.com/AsteriskAmpersand/MHR_Tex_Chopper)
- [RandomTBush's RTB-QuickBMS-Scripts CapcomMTFrameworkPC_TEX.bms](https://github.com/RandomTBush/RTB-QuickBMS-Scripts/blob/master/Textures%2FCapcomMTFrameworkPC_TEX.bms)
- [Silvris's MH-Tools-and-Scripts Noesis plugin tex_mtFramework_tex.py](https://github.com/Silvris/MH-Tools-and-Scripts/blob/master/Noesis%2Fplugins%2Fpython%2Ftex_mtFramework_tex.py)
- [Kuumba123's MMX5---X6-DAT-Extract](https://github.com/Kuumba123/MMX5---X6-DAT-Extract) to compare PSX files
- ❤️ [Kuumba123's TehemanX4 Editor](https://github.com/Kuumba123/TeheManX4_Editor)

# Requirements

- Python 3.12+
- Megaman X Legacy Collection [1](https://store.steampowered.com/app/743890/Mega_Man_X_Legacy_Collection/) and [2](https://store.steampowered.com/app/743900/Mega_Man_X_Legacy_Collection_2/) on PC/Steam (for ARC files)
- [Watto Game Extractor](https://www.watto.org/game_extractor.html) (to extract ARC files)

# Setup

## Python

We need to set up a Python virtualenv and install requirements.

```sh
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Game files

- Buy and download Megaman X Legacy Collection 1 and 2 from Steam
- Go to the game files from the MMXLC or MMXLC2 library
  - Library > MMXLC Game > Cog > Manage > Browse local files
- Navigate to game of choice (X4/X5/X6) and get the ARC files to extract from
  - Mega Man X Legacy Collection\nativeDX10\X4\romPC
  - Mega Man X Legacy Collection 2\nativeDX10\X5\romPC
  - Mega Man X Legacy Collection 2\nativeDX10\X6\romPC
- Use Game Extrator to extract game assets from each of the ARC files

TODO: more information/details on filenames and folders later

### File types

| Extension | Description                                          |
| --------- | ---------------------------------------------------- |
| COL       | Palette files                                        |
| TEX       | Image files. Formats <br>0x07: 8bpp <br>0x12: 4bpp ? |

There are others, but not there yet.

# Workflow

First get into Python virtualenv with `.venv\Scripts\activate.bat`

## Extract 8bpp TEX images

The `extract_tex_to_png.py` script is used for converting MMXLC TEX images to PNG.

### Generate for all colours in palette

Generate texture using all palette colours (CLUTs) in given palette file.

```sh
python extract_tex_to_png.py TEX_file COL_file
```

Example: `python extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col`

### Specific colours

Generate texture using given palette file and specific CLUT index.

```sh
python extract_tex_to_png.py TEX_file COL_file --clut CLUT_BASE
```

Example: `python extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col`

## Determining CLUT base index

There are a lot of palette combinations to try and this can be very time consuming.

Use `clut_finder.py` to quickly find the correct CLUT index to use for the given texture you want.

```sh
python clut_finder.py SCREENSHOT_file COL_file
```

- Play the game on an emulator and take a screenshot of the scene you're trying to extract from
- Load the screenshot into the script along with the COL palette file you suspect contains the colours
- Using a mouse, highlight the area you want colours for
- It should help you narrow down the possible CLUTs for the selection
- Try the results with `extract_tex_to_png.py --clut BASE_INDEX` option
