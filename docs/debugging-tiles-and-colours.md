# Finding the right CLUT index (palette)

Play the game and take screenshots, or use [VGMaps](https://www.vgmaps.com/Atlas/PSX/index.htm) to grab the map dumps.

**Note**: online images may have slightly incorrect colours due to JPG artefacting.

Use `clut_finder.py <screenshot_file>.png` to get started.

Load the COL (palette) and TEX (tiles) files for the stage you want to debug.

Rule of thumb for TEX files is `stage_name.tex` is the first half of the stage, `stage_name_chr256.tex` for second half.

On the left, highlight the area you want to find the matching CLUT for. It's usually best to stick within the same type of tile.

The most likely CLUT will automatically be selected and the TEX will re-render with the matching palette.

# Debugging mismatched tiles

This is mostly obsolete now after figuring out OCL mappings and OMP catalogs, but was critical during the initial phase, before building up the tools and render path. Leaving it here in case someone needs to track down a rendering bug.

You can select tiles on both the left and right images to help find things easily. Lock the clut via checkbox so TEX refreshes don't slow you down.

The pixel/tile coordinates for selections are also printed out in terminal for convenience.

Use these values to figure out why tiles aren't showing up in the correct place in screens/layouts.
