"""
CLUT Finder GUI

Usage: python clut_finder.py image.png palette.col

Displays a screenshot and lets you select an area for CLUT index matching from palette file.
Clicking on screenshot image clears the selection.

Preferably PNG screenshots as the colours don't get distorted by JPG artifacting.
Tested with screenshots from Duckstation with scaling: billinear (sharp)
"""

import argparse
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
from PIL.Image import Image as PILImage

from utils.types import Palette, ColourRGB, ColourRGBA
from utils.palette import load_col_palettes, convert_palette_to_clut
from utils.tex import convert_tex_to_image
from extract_tex_to_png import (
    load_col_palettes,
    load_tex,
)


class CLUTFinderApp:
    def __init__(self, root: tk.Tk, screenshot: PILImage, palette: Palette):
        self.root = root
        self.palette = palette
        self.clut = convert_palette_to_clut(palette)
        self.image = screenshot.convert("RGB")
        self.photo = ImageTk.PhotoImage(self.image)
        self.w, self.h = self.image.size
        self.tex_file: Path | None = None
        self.matching_indexes: list[tuple[int, float]] = []

        # menu bar
        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open screenshot...", command=self.open_screenshot)
        file_menu.add_command(label="Open palette...", command=self.open_palette)
        file_menu.add_command(label="Open TEX file...", command=self.open_tex)
        menubar.add_cascade(label="File", menu=file_menu)
        root.config(menu=menubar)

        content_frame = tk.Frame(root)
        content_frame.pack(fill="both", expand=True)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.columnconfigure(2, weight=0)
        content_frame.rowconfigure(0, weight=1)

        screenshot_outer = tk.Frame(content_frame)
        screenshot_outer.grid(row=0, column=0, sticky="nsew")
        screenshot_outer.rowconfigure(0, weight=1)
        screenshot_outer.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(screenshot_outer, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas_image = self.canvas.create_image(
            0, 0, anchor="nw", image=self.photo
        )
        self.canvas.config(scrollregion=(0, 0, self.w, self.h))
        ss_vscroll = tk.Scrollbar(
            screenshot_outer, orient="vertical", command=self.canvas.yview
        )
        ss_vscroll.grid(row=0, column=1, sticky="ns")
        ss_hscroll = tk.Scrollbar(
            screenshot_outer, orient="horizontal", command=self.canvas.xview
        )
        ss_hscroll.grid(row=1, column=0, sticky="ew")
        self.canvas.config(yscrollcommand=ss_vscroll.set, xscrollcommand=ss_hscroll.set)

        tex_outer = tk.Frame(content_frame)
        tex_outer.grid(row=0, column=1, sticky="nsew")
        tex_outer.rowconfigure(0, weight=1)
        tex_outer.columnconfigure(0, weight=1)

        self.tex_canvas = tk.Canvas(tex_outer, width=1, height=1, bg="#1a1a1a")
        self.tex_canvas.grid(row=0, column=0, sticky="nsew")
        tex_vscroll = tk.Scrollbar(
            tex_outer, orient="vertical", command=self.tex_canvas.yview
        )
        tex_vscroll.grid(row=0, column=1, sticky="ns")
        tex_hscroll = tk.Scrollbar(
            tex_outer, orient="horizontal", command=self.tex_canvas.xview
        )
        tex_hscroll.grid(row=1, column=0, sticky="ew")
        self.tex_canvas.config(
            yscrollcommand=tex_vscroll.set, xscrollcommand=tex_hscroll.set
        )

        self.side_panel = tk.Frame(content_frame, width=200)
        self.side_panel.grid(row=0, column=2, sticky="ns")
        self.side_panel.pack_propagate(False)

        self.save_tex_button = tk.Button(
            self.side_panel,
            text="Save TEX as PNG",
            command=self.save_tex_preview,
        )
        self.save_tex_button.pack(fill="x", pady=(10, 2), padx=10)

        self.unique_colours_label = tk.Label(self.side_panel, text="", anchor="w")
        self.unique_colours_label.pack(fill="x", padx=10, pady=(4, 2))

        self.matches_label = tk.Label(
            self.side_panel, text="0 matching indexes", anchor="w"
        )
        self.matches_label.pack(fill="x", padx=10, pady=(0, 2))

        matches_frame = tk.Frame(self.side_panel)
        matches_frame.pack(fill="both", expand=True, pady=(0, 5), padx=10)

        self.matches_scrollbar = tk.Scrollbar(matches_frame, orient="vertical")
        self.matches = tk.Listbox(
            matches_frame,
            selectmode="single",
            yscrollcommand=self.matches_scrollbar.set,
            activestyle="none",
        )
        self.matches_scrollbar.config(command=self.matches.yview)
        self.matches.bind("<<ListboxSelect>>", self.on_match_selected)

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
        self.start_x = int(self.canvas.canvasx(event.x))
        self.start_y = int(self.canvas.canvasy(event.y))
        self.moved = False

    def on_mouse_drag(self, event):
        x = max(0, min(self.w - 1, int(self.canvas.canvasx(event.x))))
        y = max(0, min(self.h - 1, int(self.canvas.canvasy(event.y))))
        self.moved = True

        # For some reason we don't have the data we need
        if not self.start_x or not self.start_y:
            return

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
        end_x = max(0, min(self.w - 1, int(self.canvas.canvasx(event.x))))
        end_y = max(0, min(self.h - 1, int(self.canvas.canvasy(event.y))))

        # treat as click: clear selection if exists
        if not self.moved:
            if self.rect_id is not None:
                self.clear_selection()
            return

        # For some reason we don't have the data we need
        if not self.start_x or not self.start_y:
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
        pixels = self.image.load()

        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                # it's ok pixels is tuple, not float
                r, g, b = pixels[xx, yy]  # type: ignore
                self.colour_set.add((r, g, b))

        self.process_selected_colours()

    def open_screenshot(self):
        path = filedialog.askopenfilename(
            title="Open screenshot",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            image = Image.open(path)
        except Exception as e:
            messagebox.showerror("Open screenshot", f"Failed to open image: {e}")
            return

        self.load_screenshot(image)

    def load_screenshot(self, image: PILImage):
        self.image = image.convert("RGB")
        self.photo = ImageTk.PhotoImage(self.image)
        self.w, self.h = self.image.size
        self.canvas.itemconfig(self.canvas_image, image=self.photo)
        self.canvas.config(scrollregion=(0, 0, self.w, self.h))
        self.clear_selection()

    def open_palette(self):
        path = filedialog.askopenfilename(
            title="Open COL palette",
            filetypes=[("COL palette files", "*.col"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            palette = load_col_palettes(Path(path))
            self.palette = palette
            self.clut = convert_palette_to_clut(palette)
        except Exception as e:
            messagebox.showerror("Open COL palette", f"Failed to open palette: {e}")
            return

        self.clear_selection()

    def open_tex(self):
        path = filedialog.askopenfilename(
            title="Open TEX file",
            filetypes=[("TEX files", "*.tex"), ("All files", "*.*")],
        )
        if not path:
            return

        self.clear_selection()
        self.tex_file = Path(path)
        self.preview_tex()

    def save_tex_preview(self):
        if not self.tex_file or not hasattr(self, "preview_tex_image"):
            return

        default_name = self.tex_file.stem + "_preview.png"
        path = filedialog.asksaveasfilename(
            title="Save TEX as PNG",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            clut_index = self.matching_indexes[0][0] if self.matching_indexes else 0
            tex_data = load_tex(self.tex_file)
            image = convert_tex_to_image(tex_data, self.palette, clut_index)
            if image:
                image.save(path)
        except Exception as e:
            messagebox.showerror("Save TEX preview", f"Failed to save image: {e}")

    def preview_tex(self, clut_index: int | None = None):
        if not self.tex_file:
            return

        try:
            tex_data = load_tex(self.tex_file)
        except Exception as e:
            messagebox.showerror("Open TEX file", f"Failed to read TEX header: {e}")
            return

        # determine best matching clut index
        if clut_index is None:
            clut_index = (
                self.matching_indexes[0][0] if len(self.matching_indexes) else 0
            )
        preview_image = convert_tex_to_image(tex_data, self.palette, clut_index)

        if preview_image:
            preview_image.save("test.png")

            self.preview_tex_image = ImageTk.PhotoImage(preview_image)
            self.tex_canvas.delete("all")
            self.tex_canvas.create_image(
                0, 0, anchor="nw", image=self.preview_tex_image
            )
            self.tex_canvas.config(scrollregion=self.tex_canvas.bbox("all"))
            print("Generated preview for", self.tex_file)
        else:
            print("Unable to preview", self.tex_file)

    def clear_selection(self):
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.colour_set.clear()
        self.unique_colours_label.config(text="")
        self.matches_label.config(text="0 matching indexes")
        self.matching_indexes = []
        self.set_matches_list([])

    def process_selected_colours(self):
        # Fuzzy-matching of colour since screenshot isn't always accurate.
        def is_colour_match(search_colour: ColourRGB, palette_colour: ColourRGBA):
            difference = 3
            r1, g1, b1 = search_colour
            r2, g2, b2, _a = palette_colour

            match_r = (r1 - difference) < r2 < (r1 + difference)
            match_g = (g1 - difference) < g2 < (g1 + difference)
            match_b = (b1 - difference) < b2 < (b1 + difference)
            return match_r and match_g and match_b

        # Counts the number of similar colours in selection
        def count_fuzzy_clut_intersection(
            palette: Palette, selected_colours: set[ColourRGB]
        ) -> int:
            matches = 0

            for swatch_colour in palette:
                for selected_colour in selected_colours:
                    if is_colour_match(selected_colour, swatch_colour):
                        matches += 1

            return matches

        # [clut index, percentage of colour_set match]
        found: list[tuple[int, float]] = []

        # print("colour_set", self.colour_set)
        # print("palette", len(self.palette[32]))
        for index, row in enumerate(self.clut):
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
                match_percent = (match_count / 16) * 100

                # more than 95% match is good. usually get over 100%
                if match_percent >= 75:
                    found.append((index, match_percent))

        # SORT BY percent DESC
        filtered = sorted(
            [result for result in found],
            key=lambda x: x[1],
            reverse=True,
        )

        self.unique_colours_label.config(text=f"Unique colors: {len(self.colour_set)}")
        self.matches_label.config(text=f"{len(filtered)} matching indexes")

        self.matching_indexes = filtered
        self.set_matches_list(filtered)
        # Update preview if needed
        self.preview_tex()

    def set_matches_list(self, results: list[tuple[int, float]]):
        self.matches.delete(0, "end")
        for clut_index, percentage in results:
            self.matches.insert("end", f"#{clut_index} ({percentage:.1f}%)")
        if results:
            self.matches.selection_set(0)
            self.matches.activate(0)

    def on_match_selected(self, event):
        sel = self.matches.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.matching_indexes):
            return
        clut_index, _ = self.matching_indexes[idx]
        self.preview_tex(clut_index=clut_index)


def main():
    parser = argparse.ArgumentParser(
        description="Display PNG and pick unique RGBs from a selection"
    )
    parser.add_argument("png", help="Path to PNG image to open", type=Path)
    parser.add_argument(
        "--palette",
        help="Path to COL palette file (accepted, not required)",
        type=Path,
        default=Path(r"PC\X5\col\stage\col00_0x_eng.col"),
    )
    args = parser.parse_args()

    screenshot_file: Path = args.png
    palette_file: Path = args.palette

    try:
        img = Image.open(screenshot_file)
    except Exception as e:
        print(f"Failed to open image: {e}")
        sys.exit(1)

    try:
        palette = load_col_palettes(palette_file)
    except Exception as e:
        print(f"Failed to open palette: {e}")
        sys.exit(1)

    root = tk.Tk()
    root.title("CLUT Finder")
    root.minsize(640, 480)
    root.state("zoomed")

    app = CLUTFinderApp(root, img, palette)

    root.mainloop()


if __name__ == "__main__":
    main()
