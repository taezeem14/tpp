from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ButtonHandle:
    name: str
    label: str
    window_name: str
    widget: Any = None
    callbacks: list[Callable[[], None]] = field(default_factory=list)


@dataclass
class WindowHandle:
    name: str
    title: str
    widget: Any = None


class GuiRuntime:
    """Simple GUI abstraction layer inspired by Qt-style declarative flows."""

    def __init__(self) -> None:
        self.windows: dict[str, WindowHandle] = {}
        self.buttons: dict[str, ButtonHandle] = {}
        self.last_window_name: Optional[str] = None
        self.last_button_name: Optional[str] = None

        self._tk = None
        self._headless = False
        self._root_window = None
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            import tkinter as tk

            self._tk = tk
        except Exception:
            self._headless = True

    def _ensure_window_name(self, window_name: Optional[str]) -> str:
        if window_name:
            return window_name
        if self.last_window_name:
            return self.last_window_name
        return f"window_{len(self.windows) + 1}"

    def _ensure_button_name(self, button_name: Optional[str]) -> str:
        if button_name:
            return button_name
        if self.last_button_name:
            return f"button_{len(self.buttons) + 1}"
        return f"button_{len(self.buttons) + 1}"

    def create_window(self, title: str, window_name: Optional[str] = None) -> WindowHandle:
        name = self._ensure_window_name(window_name)

        handle = WindowHandle(name=name, title=title)
        if not self._headless and self._tk is not None:
            try:
                if self._root_window is None:
                    widget = self._tk.Tk()
                    self._root_window = widget
                else:
                    widget = self._tk.Toplevel(self._root_window)
                widget.title(title)
                handle.widget = widget
            except Exception:
                self._headless = True

        self.windows[name] = handle
        self.last_window_name = name
        return handle

    def get_window(self, window_name: Optional[str] = None) -> WindowHandle:
        name = self._ensure_window_name(window_name)
        if name not in self.windows:
            raise ValueError(f"Window '{name}' does not exist")
        return self.windows[name]

    def set_window_size(self, width: int, height: int, window_name: Optional[str] = None) -> None:
        window = self.get_window(window_name)
        if window.widget is not None:
            window.widget.geometry(f"{width}x{height}")

    def create_button(
        self,
        label: str,
        button_name: Optional[str] = None,
        window_name: Optional[str] = None,
    ) -> ButtonHandle:
        target_window = self.get_window(window_name)
        name = self._ensure_button_name(button_name)

        handle = ButtonHandle(name=name, label=label, window_name=target_window.name)

        if target_window.widget is not None and self._tk is not None:
            button_widget = self._tk.Button(target_window.widget, text=label)
            button_widget.pack()
            handle.widget = button_widget

        self.buttons[name] = handle
        self.last_button_name = name
        return handle

    def get_button(self, button_name: Optional[str] = None) -> ButtonHandle:
        if button_name is None:
            if self.last_button_name is None:
                raise ValueError("No button is available")
            button_name = self.last_button_name

        if button_name not in self.buttons:
            raise ValueError(f"Button '{button_name}' does not exist")
        return self.buttons[button_name]

    def on_button_click(self, callback: Callable[[], None], button_name: Optional[str] = None) -> None:
        button = self.get_button(button_name)
        button.callbacks.append(callback)

        if button.widget is not None:
            button.widget.configure(command=lambda: self._run_button_callbacks(button.name))

    def _run_button_callbacks(self, button_name: str) -> None:
        button = self.get_button(button_name)
        for callback in list(button.callbacks):
            callback()

    def show_window(self, window_name: Optional[str] = None) -> None:
        window = self.get_window(window_name)

        if self._headless or window.widget is None:
            print(f"[GUI] Headless mode active. Window '{window.title}' prepared but not displayed.")
            return

        if self._root_window is not None:
            self._root_window.mainloop()
