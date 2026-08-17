# Mega Man X Legacy Collection Sprite Extractor for X4/X5/X6

Making it easier for sprite rippers to get accurate sprites straight from the source.

The code for this project heavily referenced information from [TehemanX4 Editor](https://github.com/Kuumba123/TeheManX4_Editor) to get past the layouts/OMP/OCL blocker, then worked on reverse engineering the data to work with X5 and X6.

Shoutout to acediez for [providing technical dumps](https://x.com/acediez/status/2061990111147937946) on Twitter which provided lots of guidance!

And [X GOD's vgmaps.com PSX stage dumps](https://www.vgmaps.com/Atlas/PSX/index.htm#MegaManX5) which saved countless hours in having to play the games and aided in finding layout offsets.

Check out [development highlights](https://twig.github.io/mmxlc-sprite-extractor/2026/08/16/mmxlc-sprites-extractor-dev-highlights.html) post to see the problems encountered along the way.

# Features

- MegaMan X4: all stages render correctly
- MegaMan X5: almost all stages render correctly
- MegaMan X6: all stages render correctly

# Requirements

- Python 3.14+
- Megaman X Legacy Collection [1](https://store.steampowered.com/app/743890/Mega_Man_X_Legacy_Collection/) and [2](https://store.steampowered.com/app/743900/Mega_Man_X_Legacy_Collection_2/) on PC/Steam (asset files not provided)

Tested on Windows 11, Python 3.14

# Quick start

```sh
python -m venv .venv
.venv\Scripts\activate.bat # Windows
# source .venv/bin/activate # Linux

# Install requirements
pip install -r requirements.txt

# Extract game assets
python extract_from_game.py

# Render a stage:
python render_stage.py PC\X4\stage\map\SCR02_01.omp

# Extract tiles
python clut_finder.py SCR02_01.png
```

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

- Buy and download Megaman X Legacy Collection 1 and/or 2 from Steam
- Find your game files from the MMXLC 1/2 library
  - Go to Steam Library
  - MMXLC 1/2 game
  - Cog > Manage > Browse local files
  - Copy Windows Explorer path
- Use `python extract_from_game.py` to extract assets from the games
- All the required files should now be in `.\PC` folder

# High level workflow

Always remember to get into Python virtualenv with `.venv\Scripts\activate.bat`

- Export stages (OMP files) to PNG
- Use CLUT finder to find palette colour indexes (CLUTs) or export level sprites as tiles as-is
- Test for regressions after making render changes

## Rendering whole stages as PNG

Use `python render_stage.py PC\X4\stage\map\SCR02_01.omp` to export a whole stage as PNG.

The output file will be `SCR02_01.png` with layer transparency preserved.

- Layers 0, 1 and 2 are rendered as-is based on layout data as separate sections in the same output PNG.
- Use `--composed` flag to flatten the 3 layers. Useful for extracting sprites which are split across multiple layers.
- The `--split-layers` flag will export each layer into separate files.
- `--debug` flag draws overlay to help visualise layout.

## Extracting palette information and tiles

`clut_finder.py` can be used for finding palette indexes from in-game screenshots or extracting rendered tiles.

Can also be used to dig a bit deeper to rendered sprite assets with different palettes or extract portions of the stage as tiles, use `python clut_finder.py st00_level.png`

- By default this loads up with palette file `PC\X5\col\stage\col00_0x_eng.col` (X5 intro stage palette for X)
- Use optional `--palette` to specify the path to another palette file.
- Use optional `--tex` to specify which TEX file you want to preview with the given palette.

Select areas from screenshot/TEX previews to save, then use the buttons to export them as PNGs. It automatically snaps to 16x16 tiles so you'll always get perfect alignment.

## Test for regressions

After making changes to the render code, it's a good idea to test rendering of all stages for regressions.

- Use `compare-baseline.bat` to generate all renders and diff images against the existing baseline.
- Identical renders are automatically deleted.
- Manually check diff image files to see what changed. Diff files will highlight what changed.
- Use `compare-baseline-accept.bat` if all diffs are good then commit new baseline.

# Low level workflow

These tools are more geared towards debugging specific game assets when rendering is not working as expected.

Some common file types used

| Extension | Description                                                                                   |
| --------- | --------------------------------------------------------------------------------------------- |
| ARC       | Capcom MT Framework archives files containing other files.                                    |
| EXE       | Megaman Legacy Collection executable binary file.                                             |
| COL       | Palette files.                                                                                |
| TEX       | Capcom MT Framework image/texture files.<br>Format 7 (0x07): 32bpp <br>Format 18 (0x12): 8bpp |
| OCL       | Object Colour Lookup table, links tile to correct palette.                                    |
| OMP       | Stage tile catalogs.                                                                          |
| CSV       | Spreadsheet files.                                                                            |

## Listing and extracting from ARC archives

Use `utils/arc.py` to extract from ARC files. The `--list` option will simply list all files instead of extracting.

**Extracting from PSX X5/X6 DAT archive**

The PSX version X5 and X6 has an extra layer of compression where all the ARC files have been lumped into a giant `ROCK_X5.dat` or `ROCK_X6.dat`. You'll need to use `psx_dat_extract.py` to pull the ARC files out from there.

The script created by [@Kuumba123](https://github.com/Kuumba123/MMX5---X6-DAT-Extract) was provided out of convenience as a way to help extract PSX assets for comparison against PC assets. No further effort around PSX will be provided as this project is focused on the PC Legacy Collection version.

## Rendering palette files (COL) to PNG

Use `render_palette.py file.col` to generate a PNG of the COL file to preview the contents.

Labels are provided to indicate which CLUT/palette index is shown.

## Extract tiles (TEX) images

The `debug_scripts/extract_tex_to_png.py` script was the initial prototype for converting MMXLC TEX images to PNG before `clut_finder.py` UX was created.

You need to give it `input.tex` and `palette.col` to get output PNG files.

```sh
python debug_scripts/extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col
```

- By default, the script will export a different PNG for each colour in the palette COL file for the given TEX file.
- Use `--clut #` to generate PNG for a specific palette (CLUT index)

```sh
python debug_scripts/extract_tex_to_png.py PC\X5\chr\stage\obj00_0a_000.tex PC\X5\col\stage\col00_0x_eng.col --clut 67
```

## Finding stage layout offsets

### What is a layout, screen, offset?

TEX and COL files are considered low level data. Going one level higher, the games use a combination of OMP and OCL (Object Colour Lookup) data to determine what palette is used to render a tile on the stage.

> Note: be aware that most X5/X6 stages use 2 tilesets (TEX files), the main TEX and the chr256 TEX. This explains why acediez's stage dumps are half garbled for each tileset. `build_chr256_ocl_indices()` contains a bunch of heuristics to determine which OCL indexes should be rendered using tex_bg/chr256.

What we consider the "stage map" is called a "layout", and is broken down into 16x16 tile grids called "screens" (each one being 256x256px since each tile is 16x16px). As the player moves around the level, different screens are loaded into memory. Assuming this was done to minimise memory usage on PSX.

The OMP file is used to map OCL entries to layout screens.

The problem is layouts are not stored in the ARC files, but the game executable files itself at particular offsets. This is why the game EXE files are needed to correctly render stages to PNG.

Offset is where the layout content begins within the EXE. The width/height information is used to determine how to interpret the layout array as a rectangular layout and also how many bytes to read from the EXE at a time. Various techniques were used to determine the offsets, ranging from lucky guesses to pattern matching against existing dumps.

To verify your offsets, use `explore_layout.py` to visualise the structure.

- Run via `python explore_layout PC\X6\stage\map\st00.omp` to debug X6 intro stage.
- By default, it can infer `--game` and `--exe` from OMP filenames from `game-files.csv`
- There are still some unmapped OMP files. To debug those, use `--game` and `--exe` to debug offsets.
- You can also specify `--layout` file to visualise PSX layout binaries.

Offsets are current as of:

- MMXLC1: 1.0.3.0 (released 17 March 2026)
- MMXLC2: 1.0.3.0 (released 17 March 2026)

In case the Megaman X Legacy Collection games get updated and offsets change, you can use the following scripts to find the new offsets.

### X4

X4 offsets are stored in a table in the PSX executable, so we use this data to extract the PSX layouts and find the equivalent content in the PC EXE.

- Extract the PSX X4 layouts using `python x4_extract_psx_layouts.py` out to `PSX\X4\layouts`
- Run `python x4_find_pc_offsets.py`
- You will get `x4_pc_mmxlc1_layout_offsets.py` containing all matching offsets ready for use.

### X5 and X6

The script scans the EXEs for patterns matching the provided map image files and ranks the potential offsets.

It brute-forces this search for a variety of width and heights as we don't have that information.

- Download the existing dumped maps
  - X5; [acediez's partial X5 stage dumps](https://archive.org/download/mmx_ps1_rips/Stage%20Layout/)
  - X6; [vgmaps.com](https://vgmaps.com/Atlas/PSX/index.htm#MegaManX6)
- Run `python match_layout_to_map.py [stage] [map_file.png] --game [VERSION]`

eg. `python match_layout_to_map.py st000 screenshots/X5_ST00_00_INTRO.png --game X5`

# Remaining issues

X4

- SCR00_00: (Intro) some missing tiles near glass (possibly rendered in-game)

X5

- st070: (Spike Rosered) ropes near vines partially missing (possibly rendered in-game)
- st180: (Zero Stage 3) missing slope tiles at the start (possibly rendered in-game)
- st220: (Training stage) non-standard format, needs more work

## Unconfirmed features

- background issues with `--composed` mode, unsure how to handle layer 3 when it doesn't align or repeat due to in-game parallax. Main goal of extracting image data from assets already achived
- post-render patching to match in-game fixes
- Animation sprites

# References

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
- [Kuumba123's MMX5---X6-DAT-Extract](https://github.com/Kuumba123/MMX5---X6-DAT-Extract) to compare PSX files
- [r/mahvelmods Texture Tutorial](https://www.reddit.com/r/mahvelmods/wiki/textures/)
- [xdanieldzd's Scarlet.IO.ImageFormats/CapcomTEX.cs](https://github.com/xdanieldzd/Scarlet/blob/master/Scarlet.IO.ImageFormats/CapcomTEX.cs)
- [FrozenFish24's TurnaboutTools TEXporter](https://github.com/FrozenFish24/TurnaboutTools/blob/master/TEXporter/TEXporter/Program.cs)
- zenhax.com threads
  - [New M.T. Framework Texture Format](https://zenhax.com/viewtopic.php@t=15549.html)
- [AsteriskAmpersand's MHR_Tex_Chopper](https://github.com/AsteriskAmpersand/MHR_Tex_Chopper)
- [RandomTBush's RTB-QuickBMS-Scripts CapcomMTFrameworkPC_TEX.bms](https://github.com/RandomTBush/RTB-QuickBMS-Scripts/blob/master/Textures%2FCapcomMTFrameworkPC_TEX.bms)
- [Silvris's MH-Tools-and-Scripts Noesis plugin tex_mtFramework_tex.py](https://github.com/Silvris/MH-Tools-and-Scripts/blob/master/Noesis%2Fplugins%2Fpython%2Ftex_mtFramework_tex.py)

# Licensing

Released under MIT License. For more details, see `LICENSE`
