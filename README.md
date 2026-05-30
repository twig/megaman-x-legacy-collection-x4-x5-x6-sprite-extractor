# MegaMan X Legacy Collection 1 and 2 Sprite Extractor

Trying to find ways to make it easier for sprite rippers to get accurate sprites straight from the source.

`WIP:` currently only working with _some_ X5 assets

# Requirements

- Python 3.12+
- Megaman X Legacy Collection 1 and 2 on PC/Steam (for ARC files)
- Game Extractor (to extract ARC files)

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
- Navigate to game of choice (X4/X5/X6) and get the ARC files to extract from
- Use Game Extrator to extract game assets from each of the ARC files

TODO: more information/details on filenames and folders later

### File types

| Extension | Description                                           |
| --------- | ----------------------------------------------------- |
| COL       | Palette files                                         |
| TEX       | Image files. Formats <br>0x07: 32bpp <br>0x12: 8bpp ? |

There are others, but not there yet.

# Workflow

First get into Python virtualenv with `.venv\Scripts\activate.bat`

## Extract 32bpp TEX images

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
