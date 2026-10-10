# -*- coding: utf-8 -*-

"""Small-screen layout helpers shared by the Tk dialogs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


def _work_area(window: tk.Misc) -> tuple[int, int, int, int]:
    """Return the Windows work area, falling back to Tk's display bounds."""

    fallback = (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = (
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            )

        rect = RECT()
        # SPI_GETWORKAREA excludes the taskbar and app bars.
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError):
        pass
    return fallback


def fit_to_screen(
    window: tk.Misc,
    preferred_width: int,
    preferred_height: int,
    *,
    minimum_width: int = 560,
    minimum_height: int = 380,
    margin: int = 32,
) -> tuple[int, int]:
    """Set an initial geometry that never extends beyond the usable display.

    Tk reports logical pixels, so this also works when Windows display scaling is
    enabled.  The minimum is capped to the available work area; callers should
    make their content scrollable instead of forcing a larger window.
    """

    window.update_idletasks()
    left, top, right, bottom = _work_area(window)
    available_width = max(320, right - left - margin * 2)
    available_height = max(240, bottom - top - margin * 2)
    width = min(preferred_width, available_width)
    height = min(preferred_height, available_height)
    min_width = min(minimum_width, width)
    min_height = min(minimum_height, height)
    window.minsize(min_width, min_height)
    x = left + max(margin, ((right - left) - width) // 2)
    y = top + max(margin, ((bottom - top) - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    return width, height


def make_vertical_scroll_area(parent: tk.Misc) -> tuple[tk.Canvas, ttk.Frame]:
    """Create a width-aware vertically scrollable content frame."""

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)
    canvas = tk.Canvas(parent, highlightthickness=0)
    scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
    content = ttk.Frame(canvas)
    content.columnconfigure(0, weight=1)
    window_id = canvas.create_window((0, 0), window=content, anchor=tk.NW)
    bound_widgets: set[str] = set()

    def on_mousewheel(event: tk.Event) -> None:
        if event.delta:
            canvas.yview_scroll(int(-event.delta / 120), "units")

    def bind_wheel_to_children(widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            key = str(child)
            if key not in bound_widgets:
                child.bind("<MouseWheel>", on_mousewheel, add="+")
                bound_widgets.add(key)
            bind_wheel_to_children(child)

    def refresh_scroll_region(_event: tk.Event) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        bind_wheel_to_children(content)

    content.bind(
        "<Configure>",
        refresh_scroll_region,
    )
    canvas.bind(
        "<Configure>",
        lambda event: canvas.itemconfigure(window_id, width=event.width),
    )
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
    scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

    canvas.bind("<MouseWheel>", on_mousewheel)
    content.bind("<MouseWheel>", on_mousewheel)
    return canvas, content


class WrapButtonBar(ttk.Frame):
    """A button bar that wraps controls instead of clipping them."""

    def __init__(self, parent: tk.Misc, **kwargs: object) -> None:
        super().__init__(parent, **kwargs)
        self._items: list[tuple[tk.Widget, bool]] = []
        self.bind("<Configure>", self._reflow, add="+")

    def add(self, widget: tk.Widget, *, right: bool = False) -> tk.Widget:
        self._items.append((widget, right))
        # Establish a requested size immediately.  Otherwise an empty frame
        # can stay one pixel wide and never receive a usable Configure event.
        widget.grid(
            row=0,
            column=len(self._items) - 1,
            padx=(0, 6),
            pady=(0, 4),
            sticky=tk.W,
        )
        self.after_idle(self._reflow)
        return widget

    def _reflow(self, _event: tk.Event | None = None) -> None:
        width = self.winfo_width()
        if width <= 1:
            return
        x = 0
        row = 0
        column = 0
        for widget, _right in self._items:
            widget.grid_forget()
            required = widget.winfo_reqwidth() + 6
            if x and x + required > width:
                x = 0
                row += 1
                column = 0
            widget.grid(row=row, column=column, padx=(0, 6), pady=(0, 4), sticky=tk.W)
            x += required
            column += 1
