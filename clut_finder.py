"""
CLUT Finder GUI

Usage: python clut_finder.py image.png palette.col

Displays a PNG and lets you drag a rectangular selection. On release,
collects unique RGB tuples from the selected area. Click (no-drag)
clears the selection.
"""

import argparse
import sys
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk


from extract_tex_to_png import load_col_palette


def parse_args():
    p = argparse.ArgumentParser(
        description="Display PNG and pick unique RGBs from a selection"
    )
    p.add_argument("png", help="Path to PNG image to open", type=Path)
    p.add_argument(
        "col", help="Path to COL palette file (accepted, not required)", type=Path
    )
    return p.parse_args()


# Split into rows of 16
def convert_to_2d_palette(
    palette: list[tuple[int, int, int]],
) -> list[list[tuple[int, int, int]]]:
    return [
        palette[clut_base : clut_base + 16] for clut_base in range(0, len(palette), 16)
    ]


class CLUToFinderApp:
    def __init__(self, root: tk.Tk, pil_image: Image.Image, palette):
        self.root = root
        self.palette = convert_to_2d_palette(palette)
        self.image = pil_image.convert("RGB")
        self.photo = ImageTk.PhotoImage(self.image)
        self.w, self.h = self.image.size

        content_frame = tk.Frame(root)
        content_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(content_frame, width=self.w, height=self.h)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas_image = self.canvas.create_image(
            0, 0, anchor="nw", image=self.photo
        )

        self.side_panel = tk.Frame(content_frame, width=200)
        self.side_panel.pack(side="right", fill="y")
        self.side_panel.pack_propagate(False)

        self.hint = tk.Label(
            self.side_panel,
            text="Drag to select; click to clear selection.",
            wraplength=180,
            justify="center",
        )
        self.hint.pack(fill="x", padx=10)

        self.status = tk.Label(
            self.side_panel, text="Unique colors: 0", anchor="center"
        )
        self.status.pack(fill="x", pady=(10, 5), padx=10)

        matches_frame = tk.Frame(self.side_panel)
        matches_frame.pack(fill="both", expand=True, pady=(10, 5), padx=10)

        self.matches_scrollbar = tk.Scrollbar(matches_frame, orient="vertical")
        self.matches = tk.Text(
            matches_frame,
            width=22,
            height=10,
            wrap="word",
            yscrollcommand=self.matches_scrollbar.set,
            bg=self.side_panel.cget("bg"),
            bd=0,
            relief="flat",
            state="disabled",
        )
        self.matches_scrollbar.config(command=self.matches.yview)

        self.matches.pack(side="left", fill="both", expand=True)
        self.matches_scrollbar.pack(side="right", fill="y")

        # selection state
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.moved = False
        self.colour_set = set()

        # bind events
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)

    def on_button_press(self, event):
        self.start_x = int(event.x)
        self.start_y = int(event.y)
        self.moved = False

    def on_mouse_drag(self, event):
        x = max(0, min(self.w - 1, int(event.x)))
        y = max(0, min(self.h - 1, int(event.y)))
        self.moved = True

        # update rectangle
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(
                self.start_x,
                self.start_y,
                x,
                y,
                outline="red",
                width=2,
                tags=("selrect",),
            )
        else:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, x, y)

    def on_button_release(self, event):
        end_x = max(0, min(self.w - 1, int(event.x)))
        end_y = max(0, min(self.h - 1, int(event.y)))

        if not self.moved:
            # treat as click: clear selection if exists
            if self.rect_id is not None:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
                self.colour_set.clear()
                self.update_status()
            return

        # normalize bbox
        x0 = min(self.start_x, end_x)
        x1 = max(self.start_x, end_x)
        y0 = min(self.start_y, end_y)
        y1 = max(self.start_y, end_y)

        # ensure coords inside image
        x0 = max(0, min(self.w - 1, x0))
        x1 = max(0, min(self.w - 1, x1))
        y0 = max(0, min(self.h - 1, y0))
        y1 = max(0, min(self.h - 1, y1))

        # sample pixels in bbox
        self.colour_set = set()
        pix = self.image.load()
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                r, g, b = pix[xx, yy]
                self.colour_set.add((r, g, b))

        self.update_status()

    def update_status(self):
        def is_colour_match(
            search_colour: list[int, int, int], palette_colour: list[int, int, int]
        ):
            difference = 3
            r1, g1, b1 = search_colour
            r2, g2, b2 = palette_colour

            match_r = (r1 - difference) < r2 < (r1 + difference)
            match_g = (g1 - difference) < g2 < (g1 + difference)
            match_b = (b1 - difference) < b2 < (b1 + difference)
            return match_r and match_g and match_b

        def count_fuzzy_clut_intersection(
            row: list[tuple[int, int, int]], selected_colours: set[tuple[int, int, int]]
        ) -> int:
            matches = 0

            for swatch_colour in row:
                for selected_colour in selected_colours:
                    if is_colour_match(selected_colour, swatch_colour):
                        matches += 1

            return matches

        # index, percentage of colour_set
        found: list[tuple[int, int]] = []

        # print("colour_set", self.colour_set)
        # print("palette", len(self.palette[32]))
        for index, row in enumerate(self.palette):
            match_count = count_fuzzy_clut_intersection(row, self.colour_set)
            # print("index", index, "match", match_count)

            # if index == 32:
            #     from pprint import pprint

            #     pprint(
            #         {
            #             "index": index,
            #             "row": row,
            #             "match_count": match_count,
            #             "colour_set": self.colour_set,
            #         },
            #         indent=2,
            #     )

            if match_count:
                found.append((index, (match_count / 16) * 100))

        filtered = sorted(
            # more than 75% match is decent
            [result for result in found if result[1] >= 75],
            key=lambda x: x[1],
            reverse=True,
        )

        self.status.config(text=f"""Unique colors: {len(self.colour_set)}

Matching indexes: {len(filtered)}""")

        self.set_matches_text(
            "\n".join(
                [f"#{clut_base} ({percentage}%)" for clut_base, percentage in filtered]
            )
        )

    def set_matches_text(self, text: str):
        self.matches.config(state="normal")
        self.matches.delete("1.0", "end")
        self.matches.insert("1.0", text)
        self.matches.config(state="disabled")


def main():
    args = parse_args()

    try:
        img = Image.open(args.png)
    except Exception as e:
        print(f"Failed to open image: {e}")
        sys.exit(1)

    try:
        palette = load_col_palette(args.col)
    except Exception as e:
        print(f"Failed to open palette: {e}")
        sys.exit(1)

    root = tk.Tk()
    root.title("CLUT Finder")

    app = CLUToFinderApp(root, img, palette)

    root.mainloop()


if __name__ == "__main__":
    main()
