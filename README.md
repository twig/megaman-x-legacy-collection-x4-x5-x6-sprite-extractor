# MegaMan X Legacy Collection 1 and 2 Sprite Extractor

Trying to find ways to make it easier for sprite rippers to get accurate sprites straight from the source.

# Features

- MegaMan X4: all stages render correctly
- MegaMan X5: most stages render correctly
- MegaMan X6: all stages render correctly

Incomplete

- render_stage in --composite mode (stack layers 0 and 1)
- figure out what to do with background (layer 3) not aligning because of parallaxing
- post-render patching to match in-game fixes

Maybe

- Animation sprites

# Remaining issues

X4

- scr00: (Intro) some missing tiles near glass, glass is not bright enough

X5

- st070: (Spike Rosered) ropes near vines partially missing (possibly rendered in-game)
- st180: (Zero Stage 3) missing slope tiles at the start (possibly rendered in-game)
- st220: (Training stage) non-standard format, needs more work

# References for code

- ❤️ [Kuumba123's TehemanX4 Editor](https://github.com/Kuumba123/TeheManX4_Editor)
- ❤️ [acediez's partial X5 stage dumps](https://x.com/acediez/status/2061990111147937946) or [archive.org](https://archive.org/download/mmx_ps1_rips/Stage%20Layout/)
- ❤️ X GOD's vgmaps stage dumps for [X5](https://www.vgmaps.com/Atlas/PSX/index.htm#MegaManX5) and [X6](https://www.vgmaps.com/Atlas/PSX/index.htm#MegaManX6)
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

# Requirements

- Python 3.13+
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

### First time setup

- Buy and download Megaman X Legacy Collection 1 and 2 from Steam
- Find your game files from the MMXLC or MMXLC2 library
  - Go to Steam Library
  - MMXLC or MMXLC2 game
  - Cog > Manage > Browse local files
  - Copy Windows Explorer path
- Use `python extract_from_game.py` to extract assets from the games
- All the required files should now be in `.\PC` folder

### File types

| Extension | Description                                         |
| --------- | --------------------------------------------------- |
| COL       | Palette files                                       |
| TEX       | Image files. Formats <br>0x07: 32bpp <br>0x12: 8bpp |

There are others, but not there yet.

# Workflow

First get into Python virtualenv with `.venv\Scripts\activate.bat`

## Extract 32bpp TEX images

The `debug_scripts/extract_tex_to_png.py` script is used for converting MMXLC TEX images to PNG.

### Generate for all colours in palette

Generate texture using all palette colours (CLUTs) in given palette file.

```sh
python debug_scripts/extract_tex_to_png.py TEX_file COL_file
```

Example: `python debug_scripts/extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col`

### Specific colours

Generate texture using given palette file and specific CLUT index.

```sh
python debug_scripts/extract_tex_to_png.py TEX_file COL_file --clut CLUT_BASE
```

Example: `python debug_scripts/extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col --clut 67`

## Determining CLUT base index

There are a lot of palette combinations to try and this can be very time consuming.

Use `clut_finder.py` to quickly find the correct CLUT index to use for the given texture you want.

```sh
python clut_finder.py SCREENSHOT_file [COL_file]
```

- Play the game on an emulator and take a screenshot of the scene you're trying to extract from
- Load the screenshot into the script along with the COL palette file you suspect contains the colours
- Using a mouse, highlight the area you want colours for
- It should help you narrow down the possible CLUTs for the selection
- Try the results with `extract_tex_to_png.py --clut BASE_INDEX` option

## Test for regressions

- Use `compare-baseline.bat` to generate all renders and diff images against the existing baseline.
- Manually check diff image files to see what changed. Diff files will highlight what changed and crop accordingly.- Use `compare-baseline-accept.bat` if all diffs are good then commit new baseline.
