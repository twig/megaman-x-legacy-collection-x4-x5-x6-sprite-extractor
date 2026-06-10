"""
When given an OMP file, read `game-exe-stagelayout-offset-finder.csv` for manually
mapped tile coordinates/catalog indexes.

Headings in CSV file are:
- omp: Path; filepath for OMP file we're trying to find the layout for
- game_tile_x: Int; 0-based number indicating X-index of tile in the game map (based off Arcdiez's PSX stage layout dumps)
- game_tile_y: Int; same as game_tile_y but Y-axis
- catalog_row_index: Int; 0-based number representing the OMP/OCL catalog row a tile is seen on
- annotation: String; human readable description for the tile

How the data is mapped:
- Each tile is a fixed 16x16px square.
- The location a tile is placed on a stage is its X/Y game_tile coordinates.
- `render_stage.py` generates an OMP/OCL catalog. Each row in the catalog represents the visual data for a particular screen.
- Use `draw_lines.py` to add lines on the catalog image to remove the need to count.
- Visually inspect Arcdiez's stage dumps to get the game_tile X/Y positions and map them to a catalog row in the CSV file.
- Sort results in the same game_tile_x by game_tile_y.

Steps to find the layouts:
- The data size of each screen is 256
- We can calculate the number of screens from the (OMP filesize - header) / 256
- With the number of screens we can calculate the exact layout size expected for each OMP
- The size of the layout table is (2 byte header for width/height) + (total_screens * 256) * 3 layers
- We can determine screen_id = (game_tile_y * layout_width + game_tile_x)
- The layout data stores each screen_id sequentially as a byte array for each layer of the map
- Think of each layer as MapLayer = byte[layout_width * layout_height]
- And the layout data as LayoutTable = MapLayer[3]
- We use the CSV data to generate a screen_id for each mapping
- Each screen_id we have helps identify anchor points in the EXE
- If the distance between each anchor point checks out, we can identify exactly where we are in the file and calculate the start/end for extraction
"""
