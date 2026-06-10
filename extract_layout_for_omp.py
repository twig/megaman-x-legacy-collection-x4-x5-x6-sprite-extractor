"""
Read `game-exe-stagelayout-offset-finder.csv` for manually mapped tile grid positions/catalog indexes.

Headings in CSV file are:
- omp: Path; filepath for OMP file we're trying to find the layout for
- game_tile_x: Int; 0-based number indicating X screen position (not coordinate) of tile in the game map (based off Arcdiez's PSX stage layout dumps)
- game_tile_y: Int; 0-based number indicating Y screen position (not coordinate) of tile in the game map (based off Arcdiez's PSX stage layout dumps)
- catalog_row_index: Int; 0-based number representing the OMP/OCL catalog row a tile is seen on (sometimes referred to as "screen_id")
- annotation: String; human readable description for the tile

How the data is mapped:
- Each tile is a fixed 16x16px square.
- The location a tile is placed on a stage is its X/Y game_tile position.
- `render_stage.py` generates an OMP/OCL catalog. Each row in the catalog represents the visual data for a particular screen.
- Use `draw_lines.py` to add lines on the catalog image to remove the need to count.
- Visually inspect Arcdiez's stage dumps to get the game_tile X/Y positions and map them to a catalog row in the CSV file.
- Sort results in the same game_tile_x by game_tile_y.
- Do not pick transparent tiles.

Steps to find stage layouts:
- The dimensions of the layout table is stored as SIZE_TABLE_OFF at offset 0x02F0B7BD
- Loop through each size entry and assume the layout table is stored sequentially starting at COPY1_OFFSET (0x02D98548) until we run into invalid data.
- The size of the layout table is (layout_width * layout_height * 3 layers) bytes
- The layout data stores each screen_id sequentially as a byte array for each layer of the map
- Think of each layer as MapLayer = byte[layout_width * layout_height]
- And the layout data as LayoutTable = MapLayer[3]
- We know that screen_id = layout[game_tile_y * layout_width + game_tile_x] for layer 0, so we can use the screen_id values to confirm if we've found the correct layout table
- Each CSV catalog_row_index we have helps identify anchor points in the EXE
- Once we confirm the layout matches our data points, it means we've found the layout for the OMP file noted in the CSV.
- Save layout binary data as layouts/{GameVersion}_stXXX_wWWW_hHHH.bin (raw layout bytes, all 3 layers)

Out of scope:
Block 2 (COPY2_OFFSET = 0x02D9B9A4) contain boss/Sigma stages and uses a different size table at 0x02E8DF71 with 4-byte entries (w, h, f1, f2), not 2-byte pairs.
The plan as written only handles Block 1 and will fail for st090_00, st100_00, st130, etc.
"""
