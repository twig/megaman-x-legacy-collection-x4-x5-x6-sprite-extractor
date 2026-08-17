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
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
from PIL.Image import Image as PILImage

from utils.types import Palette, ColourRGB, ColourRGBA
from utils.palette import load_col_palettes, convert_palette_to_clut
from utils.tex import load_tex, convert_tex_to_image

class CLUTFinderApp:
    GRID_SIZE = 16

    def __init__(
        self, root: tk.Tk, screenshot: PILImage, palette: Palette, palette_file: Path, tex_file: Path | None
    ):
        self.root = root
        self.palette = palette
        self.palette_file = palette_file
        self.clut = convert_palette_to_clut(palette)
        self.clut_index = -1
        self.screenshot_original = screenshot
        self.screenshot_image = screenshot.convert("RGB")
        self.screenshot_tkimage = ImageTk.PhotoImage(self.screenshot_image)
        self.w, self.h = self.screenshot_image.size
        self.tex_file: Path | None = tex_file
        self.tex_w = 0
        self.tex_h = 0
        self.matching_indexes: list[tuple[int, float]] = []
        self.preview_tex_pil: PILImage | None = None
        self.ss_rect_coords: tuple[int, int, int, int] | None = None
        self.tex_start_x = None
        self.tex_start_y = None
        self.tex_rect_id = None
        self.tex_rect_coords: tuple[int, int, int, int] | None = None
        self.tex_moved = False
        self._matching_task_id = 0
        self._preview_task_id = 0

        # menu bar
        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open screenshot...", command=self.open_screenshot)
        file_menu.add_command(label="Open palette...", command=self.open_palette)
        file_menu.add_command(label="Open TEX file...", command=self.open_tex)
        menubar.add_cascade(label="File", menu=file_menu)
        root.config(menu=menubar)

        self.content_frame = tk.Frame(root)
        self.content_frame.pack(fill="both", expand=True)
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.columnconfigure(1, weight=0)
        self.content_frame.columnconfigure(2, weight=0)
        self.content_frame.rowconfigure(0, weight=1)

        screenshot_outer = tk.Frame(self.content_frame)
        screenshot_outer.grid(row=0, column=0, sticky="nsew")
        screenshot_outer.rowconfigure(0, weight=1)
        screenshot_outer.columnconfigure(0, weight=1)

        self.screenshot_canvas = tk.Canvas(screenshot_outer, width=1, height=1)
        self.screenshot_canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas_image = self.screenshot_canvas.create_image(
            0, 0, anchor="nw", image=self.screenshot_tkimage
        )
        self.screenshot_canvas.config(scrollregion=(0, 0, self.w, self.h))
        ss_vscroll = tk.Scrollbar(
            screenshot_outer, orient="vertical", command=self.screenshot_canvas.yview
        )
        ss_vscroll.grid(row=0, column=1, sticky="ns")
        ss_hscroll = tk.Scrollbar(
            screenshot_outer, orient="horizontal", command=self.screenshot_canvas.xview
        )
        ss_hscroll.grid(row=1, column=0, sticky="ew")
        self.screenshot_canvas.config(yscrollcommand=ss_vscroll.set, xscrollcommand=ss_hscroll.set)

        self.tex_outer = tk.Frame(self.content_frame)
        self.tex_outer.grid(row=0, column=1, sticky="nsew")
        self._set_tex_preview_visible(False)
        self.tex_outer.rowconfigure(0, weight=1)
        self.tex_outer.columnconfigure(0, weight=1)

        self.tex_canvas = tk.Canvas(self.tex_outer, width=1, height=1, bg="#1a1a1a")
        self.tex_canvas.grid(row=0, column=0, sticky="nsew")
        tex_vscroll = tk.Scrollbar(
            self.tex_outer, orient="vertical", command=self.tex_canvas.yview
        )
        tex_vscroll.grid(row=0, column=1, sticky="ns")
        tex_hscroll = tk.Scrollbar(
            self.tex_outer, orient="horizontal", command=self.tex_canvas.xview
        )
        tex_hscroll.grid(row=1, column=0, sticky="ew")
        self.tex_canvas.config(
            yscrollcommand=tex_vscroll.set, xscrollcommand=tex_hscroll.set
        )

        self.side_panel = tk.Frame(self.content_frame, width=200)
        self.side_panel.grid(row=0, column=2, sticky="ns")
        self.side_panel.pack_propagate(False)

        # save as PNG buttons
        self.export_png_label = tk.Label(
            self.side_panel, text="Export to PNG", anchor="w"
        )
        self.export_png_label.pack(fill="x", padx=10, pady=(0, 2))

        self.save_ss_selection_button = tk.Button(
            self.side_panel,
            text="Screenshot selection",
            command=self.save_screenshot_selection,
        )
        self.save_ss_selection_button.pack(fill="x", pady=(0, 2), padx=10)

        self.save_tex_selection_button = tk.Button(
            self.side_panel,
            text="TEX selection",
            command=self.save_tex_selection,
        )
        self.save_tex_selection_button.pack(fill="x", pady=(0, 2), padx=10)

        self.save_tex_button = tk.Button(
            self.side_panel,
            text="Full TEX preview",
            command=self.save_tex_preview,
        )
        self.save_tex_button.pack(fill="x", pady=(0, 2), padx=10)

        # colours
        self.is_clut_locked = tk.BooleanVar(value=False)
        self.lock_clut_check = tk.Checkbutton(
            self.side_panel,
            text="Lock current CLUT index",
            variable=self.is_clut_locked,
            command=self.on_lock_clut_toggled,
        )
        self.lock_clut_check.pack(fill="x", padx=10, pady=(10, 2))

        self.unique_colours_label = tk.Label(self.side_panel, text="", anchor="w")
        self.unique_colours_label.pack(fill="x", padx=10, pady=(4, 2))

        self.matches_label = tk.Label(
            self.side_panel, text="0 matching indexes", anchor="w"
        )
        self.matches_label.pack(fill="x", padx=10, pady=(0, 2))

        self.busy_label = tk.Label(self.side_panel, text="", anchor="w", fg="#888")
        self.busy_label.pack(fill="x", padx=10, pady=(0, 4))

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
        self.screenshot_canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.screenshot_canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.screenshot_canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.tex_canvas.bind("<ButtonPress-1>", self.on_tex_button_press)
        self.tex_canvas.bind("<B1-Motion>", self.on_tex_mouse_drag)
        self.tex_canvas.bind("<ButtonRelease-1>", self.on_tex_button_release)

    def _set_tex_preview_visible(self, visible: bool) -> None:
        if visible:
            self.tex_outer.grid()
            self.content_frame.columnconfigure(1, weight=1)
        else:
            self.tex_outer.grid_remove()
            self.content_frame.columnconfigure(1, weight=0)

    def snap_to_grid(self, value: int) -> int:
        return (value // self.GRID_SIZE) * self.GRID_SIZE

    def _normalize_grid_coords(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        max_w: int,
        max_h: int,
    ) -> tuple[int, int, int, int, int, int, int, int]:
        x0 = max(0, min(max_w - 1, x0))
        x1 = max(0, min(max_w - 1, x1))
        y0 = max(0, min(max_h - 1, y0))
        y1 = max(0, min(max_h - 1, y1))

        grid_x0 = x0 // self.GRID_SIZE
        grid_x1 = x1 // self.GRID_SIZE
        grid_y0 = y0 // self.GRID_SIZE
        grid_y1 = y1 // self.GRID_SIZE

        if grid_x1 < grid_x0:
            grid_x0, grid_x1 = grid_x1, grid_x0
        if grid_y1 < grid_y0:
            grid_y0, grid_y1 = grid_y1, grid_y0

        pixel_x0 = grid_x0 * self.GRID_SIZE
        pixel_y0 = grid_y0 * self.GRID_SIZE
        pixel_x1 = min(max_w - 1, ((grid_x1 + 1) * self.GRID_SIZE) - 1)
        pixel_y1 = min(max_h - 1, ((grid_y1 + 1) * self.GRID_SIZE) - 1)

        return (
            grid_x0,
            grid_y0,
            grid_x1,
            grid_y1,
            pixel_x0,
            pixel_y0,
            pixel_x1,
            pixel_y1,
        )

    def on_button_press(self, event):
        raw_x = int(self.screenshot_canvas.canvasx(event.x))
        raw_y = int(self.screenshot_canvas.canvasy(event.y))
        self.start_x = self.snap_to_grid(raw_x)
        self.start_y = self.snap_to_grid(raw_y)
        self.start_x = max(0, min(self.w - 1, self.start_x))
        self.start_y = max(0, min(self.h - 1, self.start_y))
        self.moved = False

    def on_mouse_drag(self, event):
        if self.start_x is None or self.start_y is None:
            return

        x = self.snap_to_grid(int(self.screenshot_canvas.canvasx(event.x)))
        y = self.snap_to_grid(int(self.screenshot_canvas.canvasy(event.y)))
        x = max(0, min(self.w - 1, x))
        y = max(0, min(self.h - 1, y))
        self.moved = True

        grid_x0, grid_y0, grid_x1, grid_y1, px0, py0, px1, py1 = self._normalize_grid_coords(
            self.start_x, self.start_y, x, y, self.w, self.h
        )

        if self.rect_id is None:
            self.rect_id = self.screenshot_canvas.create_rectangle(
                px0,
                py0,
                px1,
                py1,
                outline="red",
                width=2,
                tags=("selrect",),
            )
        else:
            self.screenshot_canvas.coords(self.rect_id, px0, py0, px1, py1)

    def on_button_release(self, event):
        if self.start_x is None or self.start_y is None:
            return

        end_x = self.snap_to_grid(int(self.screenshot_canvas.canvasx(event.x)))
        end_y = self.snap_to_grid(int(self.screenshot_canvas.canvasy(event.y)))
        end_x = max(0, min(self.w - 1, end_x))
        end_y = max(0, min(self.h - 1, end_y))

        # treat as click: clear screenshot selection if exists
        if not self.moved:
            if self.rect_id is not None:
                self.clear_screenshot_selection()
            return

        grid_x0, grid_y0, grid_x1, grid_y1, px0, py0, px1, py1 = self._normalize_grid_coords(
            self.start_x, self.start_y, end_x, end_y, self.w, self.h
        )

        if self.rect_id is not None:
            self.screenshot_canvas.coords(self.rect_id, px0, py0, px1, py1)

        self.ss_rect_coords = (px0, py0, px1, py1)

        print(
            f"Selected screenshot grid ({grid_x0},{grid_y0}) to ({grid_x1},{grid_y1}) "
            f"-> pixels ({px0},{py0}) to ({px1},{py1})",
            flush=True,
        )

        self.colour_set = set()
        pixels = self.screenshot_image.load()

        for yy in range(py0, py1 + 1):
            for xx in range(px0, px1 + 1):
                r, g, b = pixels[xx, yy]  # type: ignore
                self.colour_set.add((r, g, b))

        self.process_selected_colours()

    def on_tex_button_press(self, event):
        if self.tex_w == 0 or self.tex_h == 0:
            return

        raw_x = int(self.tex_canvas.canvasx(event.x))
        raw_y = int(self.tex_canvas.canvasy(event.y))
        self.tex_start_x = self.snap_to_grid(raw_x)
        self.tex_start_y = self.snap_to_grid(raw_y)
        self.tex_start_x = max(0, min(self.tex_w - 1, self.tex_start_x))
        self.tex_start_y = max(0, min(self.tex_h - 1, self.tex_start_y))
        self.tex_moved = False

    def on_tex_mouse_drag(self, event):
        if self.tex_start_x is None or self.tex_start_y is None:
            return

        x = self.snap_to_grid(int(self.tex_canvas.canvasx(event.x)))
        y = self.snap_to_grid(int(self.tex_canvas.canvasy(event.y)))
        x = max(0, min(self.tex_w - 1, x))
        y = max(0, min(self.tex_h - 1, y))
        self.tex_moved = True

        grid_x0, grid_y0, grid_x1, grid_y1, px0, py0, px1, py1 = self._normalize_grid_coords(
            self.tex_start_x, self.tex_start_y, x, y, self.tex_w, self.tex_h
        )

        self.tex_rect_coords = (px0, py0, px1, py1)
        if self.tex_rect_id is None:
            self.tex_rect_id = self.tex_canvas.create_rectangle(
                px0,
                py0,
                px1,
                py1,
                outline="cyan",
                width=2,
                tags=("texselrect",),
            )
        else:
            self.tex_canvas.coords(self.tex_rect_id, px0, py0, px1, py1)

    def on_tex_button_release(self, event):
        if self.tex_start_x is None or self.tex_start_y is None:
            return

        end_x = self.snap_to_grid(int(self.tex_canvas.canvasx(event.x)))
        end_y = self.snap_to_grid(int(self.tex_canvas.canvasy(event.y)))
        end_x = max(0, min(self.tex_w - 1, end_x))
        end_y = max(0, min(self.tex_h - 1, end_y))

        if not self.tex_moved:
            if self.tex_rect_id is not None:
                self.clear_tex_selection()
            return

        grid_x0, grid_y0, grid_x1, grid_y1, px0, py0, px1, py1 = self._normalize_grid_coords(
            self.tex_start_x, self.tex_start_y, end_x, end_y, self.tex_w, self.tex_h
        )

        self.tex_rect_coords = (px0, py0, px1, py1)
        if self.tex_rect_id is not None:
            self.tex_canvas.coords(self.tex_rect_id, px0, py0, px1, py1)

        print(
            f"Selected TEX grid ({grid_x0},{grid_y0}) to ({grid_x1},{grid_y1}) "
            f"-> pixels ({px0},{py0}) to ({px1},{py1})",
            flush=True,
        )

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
        self.screenshot_image = image.convert("RGB")
        self.screenshot_tkimage = ImageTk.PhotoImage(self.screenshot_image)
        self.w, self.h = self.screenshot_image.size
        self.screenshot_canvas.itemconfig(self.canvas_image, image=self.screenshot_tkimage)
        self.screenshot_canvas.config(scrollregion=(0, 0, self.w, self.h))
        self.clear_selection()

    def open_palette(self):
        filepath = filedialog.askopenfilename(
            title="Open COL palette",
            filetypes=[("COL palette files", "*.col"), ("All files", "*.*")],
        )
        if not filepath:
            return

        try:
            path = Path(filepath)
            palette = load_col_palettes(path)
            self.palette = palette
            self.clut = convert_palette_to_clut(palette)
            self.palette_file = path
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
        self._set_tex_preview_visible(True)
        self.preview_tex()

    def save_tex_preview(self):
        if not self.tex_file or not hasattr(self, "preview_tex_image"):
            messagebox.showinfo(
                "Save TEX selection", "Open a TEX file first."
            )
            return

        default_name = f"tex-{self.tex_file.stem}-col-{self.palette_file.stem}-clut-{self.clut_index}.png"
        path = filedialog.asksaveasfilename(
            title="Save TEX as PNG",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            tex_data = load_tex(self.tex_file)
            image = convert_tex_to_image(tex_data, self.palette, self.clut_index)
            if image:
                image.save(path)
        except Exception as e:
            messagebox.showerror("Save TEX preview", f"Failed to save image: {e}")

    def _save_crop(self, source: PILImage, coords: tuple[int, int, int, int]):
        px0, py0, px1, py1 = coords
        # selection coords are inclusive pixels; crop is exclusive on the far edge
        crop = source.crop((px0, py0, px1 + 1, py1 + 1))

        default_name = f"x{px0}_y{py0}-x{px1}_y{py1}.png"
        path = filedialog.asksaveasfilename(
            title="Save selection as PNG",
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            crop.save(path)
            print(f"Saved selection to {path}", flush=True)
        except Exception as e:
            messagebox.showerror("Save selection", f"Failed to save image: {e}")

    def save_screenshot_selection(self):
        if self.ss_rect_coords is None:
            messagebox.showinfo(
                "Save screenshot selection", "Select an area on the screenshot first."
            )
            return
        self._save_crop(self.screenshot_original, self.ss_rect_coords)

    def save_tex_selection(self):
        if self.tex_file is None:
            messagebox.showinfo(
                "Save TEX selection", "Open a TEX file first."
            )
            return

        if self.tex_rect_coords is None or self.preview_tex_pil is None:
            messagebox.showinfo(
                "Save TEX selection", "Select an area on the TEX preview first."
            )
            return
        self._save_crop(self.preview_tex_pil, self.tex_rect_coords)

    def on_lock_clut_toggled(self):
        if self.is_clut_locked.get():
            self.unique_colours_label.config(text=f"Unique colors: {len(self.colour_set)}")
            self.matches_label.config(text=f"CLUT locked at #{self.clut_index}")
            self.busy_label.config(text="")
            return

        if self.colour_set:
            self.process_selected_colours()

    def preview_tex(self, clut_index: int | None = None):
        if not self.tex_file:
            return

        tex_file = self.tex_file
        self._preview_task_id += 1
        task_id = self._preview_task_id

        # determine best matching clut index
        if clut_index is None:
            clut_index = self.matching_indexes[0][0] if len(self.matching_indexes) else 0

        # nothing to do
        if clut_index == self.clut_index:
            return

        self.clut_index = clut_index

        self.busy_label.config(text="Rendering TEX preview...")
        # self.tex_canvas.delete("all")
        self.tex_canvas.create_text(
            10,
            10,
            anchor="nw",
            text="Rendering preview...",
            fill="white",
        )
        self.tex_canvas.config(scrollregion=(0, 0, self.tex_w or 1, self.tex_h or 1))

        def worker():
            preview_image = None
            error = None
            try:
                tex_data = load_tex(tex_file)
                preview_image = convert_tex_to_image(tex_data, self.palette, clut_index)
            except Exception as exc:
                error = exc

            self.root.after(
                0,
                lambda: self._on_preview_ready(task_id, preview_image, clut_index, error),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_preview_ready(
        self,
        task_id: int,
        preview_image: PILImage | None,
        clut_index: int,
        error: Exception | None,
    ):
        if task_id != self._preview_task_id:
            return

        self.busy_label.config(text="")
        if error is not None:
            messagebox.showerror("Open TEX file", f"Failed to read TEX header: {error}")
            return

        if not preview_image:
            print("Unable to preview", self.tex_file, flush=True)
            return

        self.tex_w, self.tex_h = preview_image.size
        self.preview_tex_pil = preview_image
        self.preview_tex_image = ImageTk.PhotoImage(preview_image)
        self.tex_canvas.delete("all")
        self.tex_canvas.create_image(0, 0, anchor="nw", image=self.preview_tex_image)
        if self.tex_rect_coords is not None:
            px0, py0, px1, py1 = self.tex_rect_coords
            self.tex_rect_id = self.tex_canvas.create_rectangle(
                px0,
                py0,
                px1,
                py1,
                outline="cyan",
                width=2,
                tags=("texselrect",),
            )
        self.tex_canvas.config(scrollregion=self.tex_canvas.bbox("all"))
        print("Generated preview for", self.tex_file, flush=True)

    def clear_selection(self):
        self.clear_screenshot_selection()
        self.clear_tex_selection()
        self.colour_set.clear()
        self.unique_colours_label.config(text="")
        self.matches_label.config(text="0 matching indexes")
        self.busy_label.config(text="")
        self.matching_indexes = []
        self.set_matches_list([])
        self._matching_task_id += 1
        self._preview_task_id += 1

    def clear_screenshot_selection(self):
        if self.rect_id is not None:
            self.screenshot_canvas.delete(self.rect_id)
            self.rect_id = None
        self.ss_rect_coords = None
        self.start_x = None
        self.start_y = None
        self.moved = False

    def clear_tex_selection(self):
        if self.tex_rect_id is not None:
            self.tex_canvas.delete(self.tex_rect_id)
            self.tex_rect_id = None
        self.tex_rect_coords = None
        self.tex_start_x = None
        self.tex_start_y = None
        self.tex_moved = False

    def process_selected_colours(self):
        if self.is_clut_locked.get():
            self.unique_colours_label.config(text=f"Unique colors: {len(self.colour_set)}")
            self.matches_label.config(text=f"CLUT locked at #{self.clut_index}")
            self.busy_label.config(text="")
            return

        self._matching_task_id += 1
        task_id = self._matching_task_id
        selected_colours = set(self.colour_set)

        self.busy_label.config(text="Finding matching CLUTs...")
        self.matches_label.config(text="Searching...")
        self.set_matches_list([])
        self.matching_indexes = []

        def worker():
            # Fuzzy-matching of colour since screenshot isn't always accurate.
            def is_colour_match(search_colour: ColourRGB, palette_colour: ColourRGBA):
                difference = 10
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
            for index, row in enumerate(self.clut):
                match_count = count_fuzzy_clut_intersection(row, selected_colours)

                if match_count:
                    match_percent = (match_count / len(selected_colours)) * 100
                    if match_percent >= 50:
                        found.append((index, match_percent))

                # if index == 66 or index == 67:
                #     print(f"#{index}", "matches", match_count)
                #     print("row", len(row), row)
                #     print("sel", len(selected_colours), selected_colours)

            # SORT BY percent DESC
            filtered = sorted(found, key=lambda x: x[1], reverse=True)
            unique_count = len(selected_colours)

            self.root.after(
                0,
                lambda: self._on_matching_done(task_id, filtered, unique_count),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_matching_done(
        self,
        task_id: int,
        filtered: list[tuple[int, float]],
        unique_count: int,
    ):
        if task_id != self._matching_task_id:
            return

        self.unique_colours_label.config(text=f"Unique colors: {unique_count}")
        self.matches_label.config(text=f"{len(filtered)} matching indexes")
        self.busy_label.config(text="")

        self.matching_indexes = filtered
        self.set_matches_list(filtered)
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
        help="Path to COL palette file (optional)",
        type=Path,
        default=Path(r"PC\X5\col\stage\col00_0x_eng.col"),
    )
    parser.add_argument(
        "--tex",
        help="Path to TEX file (accepted, not required)",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    screenshot_file: Path = args.png
    palette_file: Path = args.palette
    tex_file: Path | None = args.tex

    try:
        img = Image.open(screenshot_file)
    except Exception as e:
        print(f"Failed to open image: {e}", flush=True)
        sys.exit(1)

    try:
        palette = load_col_palettes(palette_file)
    except Exception as e:
        print(f"Failed to open palette: {e}", flush=True)
        sys.exit(1)

    root = tk.Tk()
    root.title("CLUT Finder")
    root.minsize(640, 480)
    root.state("zoomed")

    app = CLUTFinderApp(root, img, palette, palette_file, tex_file)

    root.mainloop()


if __name__ == "__main__":
    main()
