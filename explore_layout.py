"""
Interactive stage layout binary explorer GUI.

Usage:
    python explore_layout.py <omp_file> [--layouts layouts_rxc2.bin]
    python explore_layout.py <omp_file> --exe PC/RXC2.exe --base-offset 0x02D98548

Left slider   — byte offset into the binary layout file (0 … file size)
Top slider    — level_width_screens (1 … 300)
Right slider  — level_height_screens (1 … 300)

The main area shows the rendered level produced by render_level().
Tick "Debug overlay" to draw the screen-grid and (sx,sy)/id labels.

Offset entry accepts both decimal (49676619) and hex (0x02EC2D4B) values.
"""

import argparse
import queue
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import ImageTk

from utils.consts import EXE_PATH_LC1, EXE_PATH_LC2
from utils.debug import debug_layout_csv, debug_overlay_level
from utils.omp import load_layout_from_exe, render_level
from render_stage import preload_related_files, STAGE_LAYOUT
from utils.types import GameVersion


# ── Main application ──────────────────────────────────────────────────────────

class LayoutExplorer(tk.Tk):
    def __init__(self, omp_path: Path, bin_path: Path, base_offset: int = 0, default_w: int = 25, default_h: int = 25) -> None:
        super().__init__()

        self.omp_path = omp_path
        self.bin_path = bin_path
        self.bin_size = len(self.bin_path.read_bytes())
        self.base_offset = max(0, min(base_offset, self.bin_size - 1))
        self.layout = None

        self.title(f"Layout Explorer — {omp_path.name}  |  {bin_path.name}")
        self.state("zoomed")  # maximise on Windows

        # Load stage assets (OMP, OCL, TEX, COL)
        try:
            result = preload_related_files(omp_path)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            sys.exit(1)
        self.omp, self.ocl, self.tex, self.tex_bg, self.flags_to_palette, game_version, _ = result

        # Render state
        self._photo: ImageTk.PhotoImage | None = None
        self._raw_img = None          # last rendered PIL Image
        self._fit_mode: bool = True   # True = fit-to-window, False = full size
        self._render_job: str | None = None
        self._render_cancel = threading.Event()
        self._result_queue: queue.Queue = queue.Queue()

        self._build_ui(default_w, default_h)
        self._schedule_render()
        self.after(50, self._poll_result)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, default_w: int, default_h: int) -> None:
        # 3 columns: [left panel] [canvas area] [right panel]
        # 3 rows:    [top slider] [canvas]       [status bar]
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Left panel: offset slider ─────────────────────────────────────────
        left = ttk.Frame(self, padding=(4, 4, 0, 4))
        left.grid(row=0, column=0, rowspan=2, sticky="ns")
        left.rowconfigure(3, weight=1)

        ttk.Label(left, text="Offset").grid(row=0, column=0, pady=(0, 2))
        self.offset_entry_var = tk.StringVar(value=str(self.base_offset))
        offset_spin = tk.Spinbox(
            left,
            from_=0,
            to=max(self.bin_size - 1, 0),
            increment=1,
            textvariable=self.offset_entry_var,
            width=12,
            justify="center",
            command=self._on_offset_entry,
        )
        offset_spin.grid(row=1, column=0, pady=(0, 2))
        offset_spin.bind("<Return>", self._on_offset_entry)
        offset_spin.bind("<FocusOut>", self._on_offset_entry)

        self.offset_hex_var = tk.StringVar(value=f"0x{self.base_offset:08X}")
        hex_entry = ttk.Entry(left, textvariable=self.offset_hex_var, width=12,
                              justify="center", state="readonly")
        hex_entry.grid(row=2, column=0, pady=(0, 4))

        self.offset_var = tk.IntVar(value=self.base_offset)
        self.offset_slider = ttk.Scale(
            left,
            from_=0,
            to=max(self.bin_size - 1, 0),
            orient=tk.VERTICAL,
            variable=self.offset_var,
            command=self._on_slider_change,
        )
        self.offset_slider.grid(row=3, column=0, sticky="ns")
        self.offset_slider.bind(
            "<ButtonPress-1>",
            lambda e: self._trough_jump(e, self.offset_slider, self.offset_var,
                                        lambda: int(self.width_var.get()),
                                        0, max(self.bin_size - 1, 0)),
        )
        self.offset_slider.bind(
            "<Shift-ButtonPress-1>",
            lambda e: self._trough_jump(e, self.offset_slider, self.offset_var,
                                        lambda: int(self.width_var.get() * self.height_var.get()),
                                        0, max(self.bin_size - 1, 0)),
        )

        ttk.Label(left, text=f"max: {self.bin_size - 1}", width=12).grid(row=4, column=0, pady=(4, 0))

        # ── Top panel: width slider + debug checkbox ──────────────────────────
        top = ttk.Frame(self, padding=(4, 4, 4, 0))
        top.grid(row=0, column=1, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Width (screens):").grid(row=0, column=0, padx=(0, 6))

        self.width_var = tk.IntVar(value=default_w)
        self.width_slider = ttk.Scale(
            top,
            from_=1,
            to=300,
            orient=tk.HORIZONTAL,
            variable=self.width_var,
            command=self._on_slider_change,
        )
        self.width_slider.grid(row=0, column=1, sticky="ew")
        self.width_slider.bind(
            "<ButtonPress-1>",
            lambda e: self._trough_jump(e, self.width_slider, self.width_var,
                                        lambda: 10, 1, 300),
        )

        self.width_entry_var = tk.StringVar(value=f"{default_w}")
        width_spin = tk.Spinbox(
            top,
            from_=1,
            to=300,
            increment=1,
            textvariable=self.width_entry_var,
            width=6,
            justify="center",
            command=self._on_width_entry,
        )
        width_spin.grid(row=0, column=2, padx=(6, 16))
        width_spin.bind("<Return>", self._on_width_entry)
        width_spin.bind("<FocusOut>", self._on_width_entry)

        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top,
            text="Debug overlay",
            variable=self.debug_var,
            command=self._schedule_render,
        ).grid(row=0, column=3)

        # ── Right panel: height slider ────────────────────────────────────────
        right = ttk.Frame(self, padding=(0, 4, 4, 4))
        right.grid(row=0, column=2, rowspan=2, sticky="ns")
        right.rowconfigure(2, weight=1)

        ttk.Label(right, text="Height").grid(row=0, column=0, pady=(0, 2))

        self.height_entry_var = tk.StringVar(value=f"{default_h}")
        height_spin = tk.Spinbox(
            right,
            from_=1,
            to=300,
            increment=1,
            textvariable=self.height_entry_var,
            width=6,
            justify="center",
            command=self._on_height_entry,
        )
        height_spin.grid(row=1, column=0, pady=(0, 4))
        height_spin.bind("<Return>", self._on_height_entry)
        height_spin.bind("<FocusOut>", self._on_height_entry)

        self.height_var = tk.IntVar(value=default_h)
        self.height_slider = ttk.Scale(
            right,
            from_=1,
            to=300,
            orient=tk.VERTICAL,
            variable=self.height_var,
            command=self._on_slider_change,
        )
        self.height_slider.grid(row=2, column=0, sticky="ns")
        self.height_slider.bind(
            "<ButtonPress-1>",
            lambda e: self._trough_jump(e, self.height_slider, self.height_var,
                                        lambda: 10, 1, 300),
        )

        # ── Scrollable canvas ─────────────────────────────────────────────────
        cf = ttk.Frame(self)
        cf.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(cf, bg="#1e1e1e", cursor="crosshair")
        hbar = ttk.Scrollbar(cf, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vbar = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        hbar.grid(row=1, column=0, sticky="ew")
        vbar.grid(row=0, column=1, sticky="ns")

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_click)

        # Right-mouse drag to pan
        self.canvas.bind("<ButtonPress-3>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B3-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(
            self,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 4))

    # ── Canvas display helpers ────────────────────────────────────────────────

    def _on_canvas_resize(self, event=None) -> None:
        if self._raw_img is not None and self._fit_mode:
            cw = event.width if event else self.canvas.winfo_width()
            ch = event.height if event else self.canvas.winfo_height()
            self._display_image(cw=cw, ch=ch)

    def _on_canvas_click(self, _=None) -> None:
        """Toggle between fit-to-window and full-size (scrollable) view."""
        if self._raw_img is None:
            return
        self._fit_mode = not self._fit_mode
        self._display_image()

    def _display_image(self, cw: int = 0, ch: int = 0) -> None:
        """Render _raw_img onto the canvas according to the current _fit_mode."""
        img = self._raw_img
        if img is None:
            return
        if self._fit_mode:
            if cw < 2 or ch < 2:
                self.update_idletasks()
                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
            if cw < 2 or ch < 2:
                return
            scale = min(cw / img.width, ch / img.height)
            disp = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            self._photo = ImageTk.PhotoImage(disp)
            self.canvas.delete("all")
            self.canvas.configure(scrollregion=(0, 0, cw, ch))
            self.canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._photo)
            self.canvas.configure(cursor="hand2")
        else:
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.configure(scrollregion=(0, 0, img.width, img.height))
            self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
            self.canvas.configure(cursor="crosshair")

    # ── Trough-click jump helper ──────────────────────────────────────────

    def _trough_jump(
        self,
        event: tk.Event,
        slider: ttk.Scale,
        var: tk.IntVar,
        get_inc,
        lo: int,
        hi: int,
    ) -> str | None:
        """Jump the slider by get_inc() toward the click position, instead of jumping to it."""
        orient = str(slider.cget("orient"))
        if orient == "vertical":
            size = slider.winfo_height()
            pos = event.y
        else:
            size = slider.winfo_width()
            pos = event.x
        if size <= 0:
            return None
        from_ = float(slider.cget("from"))
        to_ = float(slider.cget("to"))
        # Fraction clicked (0 = near-from_ end, 1 = near-to_ end)
        frac = pos / size
        click_val = from_ + frac * (to_ - from_)
        current = var.get()
        inc = get_inc()
        if click_val > current:
            new_val = min(hi, current + inc)
        elif click_val < current:
            new_val = max(lo, current - inc)
        else:
            return "break"
        var.set(new_val)
        self._on_slider_change()
        return "break"

    # ── Slider / entry callbacks ─────────────────────────────────────────────

    def _on_slider_change(self, _=None) -> None:
        w = int(self.width_var.get())
        h = int(self.height_var.get())
        off = int(self.offset_var.get())
        self.width_entry_var.set(str(w))
        self.height_entry_var.set(str(h))
        self.offset_entry_var.set(str(off))
        self.offset_hex_var.set(f"0x{off:08X}")
        self._schedule_render()

    def _on_offset_entry(self, _=None) -> None:
        try:
            val = int(self.offset_entry_var.get(), 0)  # accepts decimal and 0x… hex
            val = max(0, min(val, self.bin_size - 1))
        except ValueError:
            val = int(self.offset_var.get())
        self.offset_entry_var.set(str(val))
        self.offset_var.set(val)
        self.offset_hex_var.set(f"0x{val:08X}")
        self._schedule_render()

    def _on_width_entry(self, _=None) -> None:
        try:
            val = int(self.width_entry_var.get())
            val = max(1, min(val, 300))
        except ValueError:
            val = int(self.width_var.get())
        self.width_entry_var.set(str(val))
        self.width_var.set(val)
        self._schedule_render()

    def _on_height_entry(self, _=None) -> None:
        try:
            val = int(self.height_entry_var.get())
            val = max(1, min(val, 300))
        except ValueError:
            val = int(self.height_var.get())
        self.height_entry_var.set(str(val))
        self.height_var.set(val)
        self._schedule_render()

    # ── Render scheduling (debounce + background thread) ─────────────────────

    def _schedule_render(self, _=None) -> None:
        """Debounce: cancel any pending render callback and reschedule."""
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(200, self._start_render)

    def _start_render(self) -> None:
        self._render_job = None
        offset = int(self.offset_var.get())
        w = int(self.width_var.get())
        h = int(self.height_var.get())
        debug = self.debug_var.get()

        # Cancel any render already in flight
        self._render_cancel.set()

        # Drain stale results from the previous render
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

        self._render_cancel = threading.Event()
        self.status_var.set(f"Rendering  offset={offset} (0x{offset:X})  w={w}  h={h} …")

        cancel_token = self._render_cancel
        t = threading.Thread(
            target=self._render_worker,
            args=(offset, w, h, debug, cancel_token),
            daemon=True,
        )
        t.start()

    def _render_worker(
        self,
        offset: int,
        w: int,
        h: int,
        debug: bool,
        cancel: threading.Event,
    ) -> None:
        try:
            layout = load_layout_from_exe(self.bin_path, offset=offset, width=w, height=h)
            self.layout = layout  # store for debug overlay

            if layout is None:
                needed = w * h * 3
                self._result_queue.put((
                    "error",
                    f"Out of range: offset {offset} + {needed} bytes "
                    f"> file size {self.bin_size}",
                ))
                return

            # debug_layout_csv(self.omp, layout, Path(f"{self.omp_path.stem}.csv"))

            if cancel.is_set():
                return

            img = render_level(
                self.omp,
                self.ocl,
                layout,
                level_width_screens=w,
                level_height_screens=h,
                tex=self.tex,
                tex_bg=self.tex_bg,
                flags_to_palette=self.flags_to_palette,
            )

            if cancel.is_set():
                return

            if debug:
                debug_overlay_level(img, layout, w, h)

            self._result_queue.put(("ok", img, offset, w, h))

        except Exception as exc:
            self._result_queue.put(("error", str(exc)))

    def _poll_result(self) -> None:
        """Drain the result queue and update the canvas; reschedules itself."""
        try:
            item = self._result_queue.get_nowait()
            kind = item[0]
            if kind == "ok":
                _, img, offset, w, h = item
                self._raw_img = img
                self._display_image()
                self.status_var.set(
                    f"OK  offset={offset} (0x{offset:X})  w={w}  h={h}  "
                    f"({img.width}×{img.height} px)"
                )
            elif kind == "error":
                self.canvas.delete("all")
                self.canvas.create_text(
                    10, 10,
                    anchor="nw",
                    fill="#ff6666",
                    text=item[1],
                    font=("Consolas", 10),
                )
                self.status_var.set(f"Error: {item[1]}")
        except queue.Empty:
            pass
        self.after(50, self._poll_result)


# ── Entry point ───────────────────────────────────────────────────────────────

COPY1_OFFSET_X4 = 0x00B60D08  # X4 first layout block start in RXC1.exe (ST00_00)
COPY1_OFFSET_X5 = 0x02D98548  # X5 block 1 layout start in RXC2.exe
COPY1_OFFSET_X6 = 0x02DD4000  # X6 block 1 layout start in RXC2.exe

_EXE_BASE_OFFSETS: dict[GameVersion, int] = {
    GameVersion.X4: COPY1_OFFSET_X4,
    GameVersion.X5: COPY1_OFFSET_X5,
    GameVersion.X6: COPY1_OFFSET_X6,
}


_GAME_EXE_MAP: dict[GameVersion, Path] = {
    GameVersion.X4: EXE_PATH_LC1,
    GameVersion.X5: EXE_PATH_LC2,
    GameVersion.X6: EXE_PATH_LC2,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive stage layout binary explorer.")
    parser.add_argument("omp_file", type=Path, help="Path to the .omp file")
    parser.add_argument(
        "--game", type=int, choices=[4, 5, 6],
        help="Game version: 4 = X4, 5 = X5, 6 = X6",
    )
    parser.add_argument(
        "--exe", type=Path, default=None,
        help="Game EXE path (default: RXC1.exe for X4, RXC2.exe for X5/X6)",
    )
    parser.add_argument(
        "--layout", type=Path, default=None,
        help="Override: use a binary layout file instead of the EXE (starts at offset 0)",
    )
    args = parser.parse_args()

    omp_file: Path = args.omp_file.resolve()
    layout_w = 25
    layout_h = 25

    if args.layout is not None:
        bin_path = args.layout
        base_offset = 0
    else:
        if args.game is not None:
            game = GameVersion(args.game)
        elif 'X4' in str(args.omp_file):
            game = GameVersion.X4
        elif 'X5' in str(args.omp_file):
            game = GameVersion.X5
        elif 'X6' in str(args.omp_file):
            game = GameVersion.X6
        else:
            messagebox.showerror("Load Error", "Cannot determine game version from OMP filename. Please specify --game explicitly.")
            sys.exit(1)

        print('Detected GameVersion:', game)
        bin_path = args.exe if args.exe is not None else _GAME_EXE_MAP[game]
        base_offset = _EXE_BASE_OFFSETS[game]

        layout_entry = STAGE_LAYOUT.get(f"X{game}", {}).get(omp_file.stem)

        if layout_entry:
            base_offset, layout_w, layout_h = layout_entry

    app = LayoutExplorer(omp_file, bin_path.resolve(), base_offset=base_offset, default_w=layout_w, default_h=layout_h)
    app.mainloop()


if __name__ == "__main__":
    main()
