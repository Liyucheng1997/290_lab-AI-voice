"""状态悬浮窗（tkinter）与系统托盘（pystray）。tkinter 必须运行在主线程。"""

from __future__ import annotations

import os
import queue
import tkinter as tk
from typing import Callable

from PIL import Image, ImageDraw

STATE_STYLE = {
    # state: (前景色, 图标)
    "idle": ("#9aa0a6", "●"),
    "recording": ("#ff5252", "●"),
    "transcribing": ("#ffb300", "◐"),
    "polishing": ("#7c4dff", "✦"),
    "done": ("#00c853", "✔"),
    "error": ("#ff1744", "✖"),
    "info": ("#40c4ff", "ⓘ"),
}


class Overlay:
    """底部居中的小型无边框置顶窗口，显示当前状态和录音电平。线程安全：其它线程用 post()。"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg="#202124")

        self._frame = tk.Frame(self.root, bg="#202124", padx=16, pady=10)
        self._frame.pack()
        self._icon = tk.Label(self._frame, text="●", font=("Segoe UI Emoji", 14), bg="#202124", fg="#9aa0a6")
        self._icon.pack(side="left", padx=(0, 8))
        self._label = tk.Label(self._frame, text="", font=("Microsoft YaHei UI", 11), bg="#202124", fg="#e8eaed",
                               justify="left", wraplength=520)
        self._label.pack(side="left")
        self._level = tk.Canvas(self._frame, width=60, height=10, bg="#202124", highlightthickness=0)
        self._level.pack(side="left", padx=(10, 0))
        self._level_bar = self._level.create_rectangle(0, 0, 0, 10, fill="#ff5252", width=0)

        self._hide_job = None
        self.root.after(40, self._drain)

    # ---- 线程安全 API ----
    def post(self, fn: Callable, *args) -> None:
        self._q.put((fn, args))

    def show(self, state: str, text: str, auto_hide: float | None = None) -> None:
        if os.environ.get("VOICEPEN_DEBUG"):
            print(f"[{state}] {text}", flush=True)
        self.post(self._show, state, text, auto_hide)

    def hide(self) -> None:
        self.post(self._hide)

    def set_level(self, level: float) -> None:
        self.post(self._set_level, level)

    def quit(self) -> None:
        self.post(self.root.quit)

    # ---- 主线程内部实现 ----
    def _drain(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                try:
                    fn(*args)
                except Exception:  # noqa: BLE001
                    pass
        except queue.Empty:
            pass
        self.root.after(40, self._drain)

    def _place(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 90}")

    def _show(self, state: str, text: str, auto_hide: float | None):
        if not self.enabled:
            return
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        fg, icon = STATE_STYLE.get(state, STATE_STYLE["idle"])
        self._icon.configure(text=icon, fg=fg)
        self._label.configure(text=text)
        if state == "recording":
            self._level.pack(side="left", padx=(10, 0))
        else:
            self._level.pack_forget()
        self._place()
        self.root.deiconify()
        self.root.lift()
        if auto_hide:
            self._hide_job = self.root.after(int(auto_hide * 1000), self._hide)

    def _hide(self):
        self._hide_job = None
        self.root.withdraw()
        self._level.coords(self._level_bar, 0, 0, 0, 10)

    def _set_level(self, level: float):
        self._level.coords(self._level_bar, 0, 0, int(60 * max(0.0, min(1.0, level))), 10)

    def run(self) -> None:
        self.root.mainloop()


def make_tray_image(color: str = "#7c4dff") -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    # 简单的麦克风形状
    d.rounded_rectangle((26, 14, 38, 36), radius=6, fill="white")
    d.arc((20, 22, 44, 44), start=0, end=180, fill="white", width=3)
    d.line((32, 44, 32, 50), fill="white", width=3)
    d.line((25, 50, 39, 50), fill="white", width=3)
    return img


def build_tray(app) -> "pystray.Icon | None":
    """构建托盘图标；app 需提供 polish_enabled/style 属性及若干回调。"""
    try:
        import pystray
    except Exception:  # noqa: BLE001
        return None

    def toggle_polish(icon, item):
        app.set_polish_enabled(not app.polish_enabled)

    def make_style_setter(style):
        def _set(icon, item):
            app.set_style(style)
        return _set

    style_menu = pystray.Menu(
        *[
            pystray.MenuItem(label, make_style_setter(key), checked=lambda item, k=key: app.style == k, radio=True)
            for key, label in (("clean", "标准整理"), ("formal", "正式书面"), ("bullets", "要点列表"), ("casual", "轻松口语"))
        ]
    )
    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"VoicePen · {app.status_text}", None, enabled=False),
        pystray.MenuItem(lambda item: f"按住 {app.hold_key_name} 说话", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("AI 润色", toggle_polish, checked=lambda item: app.polish_enabled),
        pystray.MenuItem("润色风格", style_menu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开配置文件", lambda icon, item: app.open_config()),
        pystray.MenuItem("打开历史记录", lambda icon, item: app.open_history()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda icon, item: app.quit()),
    )
    icon = pystray.Icon("VoicePen", make_tray_image(), "VoicePen 语音输入", menu)
    return icon
