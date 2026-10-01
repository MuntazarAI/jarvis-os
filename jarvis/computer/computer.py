"""Computer control for GNOME/Wayland: screenshot, windows, clipboard, input.

Read-only operations run live. Input automation goes through ydotool
(daemon verified running) and is policy-gated HIGH risk. Anything the
compositor forbids (global screenshot without portal consent, virtual
keyboard protocol) is reported honestly instead of faked.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import RiskLevel
from ..tools.tools import Tool, ToolResult, ToolSpec


def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# -- screenshot -------------------------------------------------------------------
class ScreenController:
    def __init__(self, display: str = ":0") -> None:
        self.display = display

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def capture(self, dest: str) -> dict[str, Any]:
        """Capture via x11grab. On GNOME/Wayland this sees the XWayland
        layer; full-compositor capture requires portal consent (interactive)
        and is reported as such, not faked."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        if not self.available():
            return {"ok": False, "error": "ffmpeg not installed"}
        try:
            proc = _run(["ffmpeg", "-y", "-v", "error", "-f", "x11grab",
                         "-i", self.display, "-frames:v", "1", dest], timeout=20.0)
            if proc.returncode == 0 and Path(dest).exists():
                size = Path(dest).stat().st_size
                if size < 1000:
                    return {"ok": False, "error": "capture is blank",
                            "note": "compositor gave no pixels; portal consent needed"}
                return {"ok": True, "path": dest, "bytes": size,
                        "scope": "x11grab (XWayland layer)",
                        "note": "full-desktop capture needs portal consent"}
            return {"ok": False, "error": proc.stderr[-300:] or "ffmpeg failed"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# -- windows -------------------------------------------------------------------------
class WindowController:
    def available(self) -> bool:
        return shutil.which("wmctrl") is not None

    def list_windows(self) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "wmctrl not installed"}
        try:
            proc = _run(["wmctrl", "-l"])
            if proc.returncode != 0:
                return {"ok": False, "error": proc.stderr[-300:]}
            windows = []
            for line in proc.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    windows.append({"id": parts[0], "desktop": parts[1],
                                    "host": parts[2], "title": parts[3]})
            return {"ok": True, "windows": windows,
                    "scope": "X11 clients only on Wayland"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def focus(self, window_id: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "wmctrl not installed"}
        try:
            proc = _run(["wmctrl", "-i", "-a", window_id])
            return {"ok": proc.returncode == 0,
                    "error": proc.stderr[-300:] if proc.returncode else ""}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# -- clipboard (GTK native on Wayland, xclip fallback) ----------------------------------
class ClipboardController:
    def read(self) -> dict[str, Any]:
        text = self._gtk_read()
        if text is not None:
            return {"ok": True, "text": text, "backend": "gtk"}
        if shutil.which("xclip"):
            try:
                proc = _run(["xclip", "-o", "-selection", "clipboard"])
                if proc.returncode == 0:
                    return {"ok": True, "text": proc.stdout, "backend": "xclip"}
            except (OSError, subprocess.SubprocessError):
                pass
        return {"ok": False, "error": "clipboard unreadable (no gtk/xclip path)"}

    def write(self, text: str) -> dict[str, Any]:
        if self._gtk_write(text):
            return {"ok": True, "backend": "gtk", "chars": len(text)}
        if shutil.which("xclip"):
            try:
                proc = subprocess.run(["xclip", "-i", "-selection", "clipboard"],
                                      input=text, capture_output=True, text=True,
                                      timeout=10)
                if proc.returncode == 0:
                    return {"ok": True, "backend": "xclip", "chars": len(text)}
            except (OSError, subprocess.SubprocessError):
                pass
        return {"ok": False, "error": "clipboard unwritable"}

    @staticmethod
    def _gtk_read() -> str | None:
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk, Gdk
            return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        except Exception:
            return None

    @staticmethod
    def _gtk_write(text: str) -> bool:
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk, Gdk
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(text, -1)
            cb.store()
            return True
        except Exception:
            return False


# -- input via ydotool --------------------------------------------------------------------
@dataclass
class InputController:
    key_delay_ms: int = 20

    def available(self) -> bool:
        return shutil.which("ydotool") is not None

    def _call(self, *args: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "ydotool not installed"}
        try:
            proc = _run(["ydotool", *args], timeout=15.0)
            if proc.returncode == 0:
                return {"ok": True}
            return {"ok": False, "error": (proc.stderr or proc.stdout)[-300:] or
                    "ydotool failed (is ydotoold running?)"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def move(self, x: int, y: int, relative: bool = False) -> dict[str, Any]:
        args = ["mousemove", "-x", str(x), "-y", str(y)]
        if relative:
            args.append("--relative")
        return self._call(*args)

    def click(self, button: str = "left") -> dict[str, Any]:
        codes = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}
        if button not in codes:
            return {"ok": False, "error": f"unknown button: {button}"}
        return self._call("click", codes[button])

    def type_text(self, text: str) -> dict[str, Any]:
        if len(text) > 2000:
            return {"ok": False, "error": "refusing to type >2000 chars at once"}
        return self._call("type", "--key-delay", str(self.key_delay_ms), "--", text)

    def key(self, *keys: str) -> dict[str, Any]:
        if not keys:
            return {"ok": False, "error": "no keys given"}
        return self._call("key", *keys)

    def scroll(self, direction: str = "up", amount: int = 3) -> dict[str, Any]:
        code = {"up": "0x100", "down": "0x101"}.get(direction)
        if code is None:
            return {"ok": False, "error": f"unknown direction: {direction}"}
        for _ in range(max(1, amount)):
            result = self._call("click", code)
            if not result.get("ok"):
                return result
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        daemon = False
        try:
            proc = _run(["pgrep", "-x", "ydotoold"])
            daemon = proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
        return {"ydotool": self.available(), "daemon": daemon}


@dataclass
class ComputerController:
    screen: ScreenController = field(default_factory=ScreenController)
    windows: WindowController = field(default_factory=WindowController)
    clipboard: ClipboardController = field(default_factory=ClipboardController)
    input: InputController = field(default_factory=InputController)

    def status(self) -> dict[str, Any]:
        return {"screenshot": self.screen.available(),
                "windows": self.windows.available(),
                "clipboard_gtk": ClipboardController._gtk_read is not None,
                "input": self.input.status(),
                "session": "wayland/gnome",
                "limits": ["full-desktop screenshot needs portal consent",
                           "input automation is HIGH risk: approval-gated"]}


# -- tool registration ---------------------------------------------------------------
def computer_tools(controller: ComputerController | None = None) -> list[Tool]:
    """Policy-gated Tool wrappers. Read ops are SAFE/LOW, input is HIGH."""
    ctrl = controller or ComputerController()

    def _wrap(name: str, fn: Any) -> ToolResult:
        try:
            out = fn()
            if isinstance(out, dict) and "ok" in out:
                return ToolResult(tool=name, ok=bool(out.pop("ok")),
                                  output=out, error=out.get("error", ""))
            return ToolResult(tool=name, ok=True, output=out)
        except TypeError as exc:
            return ToolResult(tool=name, ok=False, error=f"bad arguments: {exc}")
        except Exception as exc:
            return ToolResult(tool=name, ok=False,
                              error=f"{type(exc).__name__}: {exc}")

    return [
        Tool(ToolSpec("screen_capture", "Capture the screen to a PNG file",
                       RiskLevel.SAFE, 20.0, ["desktop.screenshot"]),
             lambda dest="/tmp/jarvis-screen.png": _wrap(
                 "screen_capture", lambda: ctrl.screen.capture(dest))),
        Tool(ToolSpec("window_list", "List visible application windows",
                       RiskLevel.SAFE, 10.0, ["desktop.windows"]),
             lambda: _wrap("window_list", ctrl.windows.list_windows)),
        Tool(ToolSpec("window_focus", "Focus a window by id",
                       RiskLevel.MEDIUM, 10.0, ["desktop.windows"]),
             lambda window_id="": _wrap(
                 "window_focus", lambda: ctrl.windows.focus(window_id))),
        Tool(ToolSpec("clipboard_read", "Read the system clipboard",
                       RiskLevel.LOW, 5.0, ["clipboard.read"]),
             lambda: _wrap("clipboard_read", ctrl.clipboard.read)),
        Tool(ToolSpec("clipboard_write", "Write text to the system clipboard",
                       RiskLevel.MEDIUM, 5.0, ["clipboard.write"]),
             lambda text="": _wrap(
                 "clipboard_write", lambda: ctrl.clipboard.write(text))),
        Tool(ToolSpec("mouse_move", "Move the pointer to x,y",
                       RiskLevel.HIGH, 10.0, ["desktop.input"]),
             lambda x=0, y=0: _wrap(
                 "mouse_move", lambda: ctrl.input.move(int(x), int(y)))),
        Tool(ToolSpec("mouse_click", "Click left|right|middle",
                       RiskLevel.HIGH, 10.0, ["desktop.input"]),
             lambda button="left": _wrap(
                 "mouse_click", lambda: ctrl.input.click(button))),
        Tool(ToolSpec("type_text", "Type text via virtual input (max 2000 chars)",
                       RiskLevel.HIGH, 15.0, ["desktop.input"]),
             lambda text="": _wrap(
                 "type_text", lambda: ctrl.input.type_text(text))),
        Tool(ToolSpec("press_keys", "Press a key combination, e.g. ctrl c",
                       RiskLevel.HIGH, 10.0, ["desktop.input"]),
             lambda keys="": _wrap(
                 "press_keys", lambda: ctrl.input.key(*keys.split()))),
    ]
