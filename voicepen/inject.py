"""把文字送进当前活动窗口的光标处。"""

from __future__ import annotations

import time

import pyperclip
from pynput.keyboard import Controller, Key


class TextInjector:
    def __init__(self, mode: str = "paste", restore_clipboard: bool = True, append_space: bool = False):
        self.mode = mode
        self.restore_clipboard = restore_clipboard
        self.append_space = append_space
        self._kb = Controller()

    def inject(self, text: str) -> None:
        if not text:
            return
        if self.append_space and not text.endswith((" ", "\n")):
            text += " "
        if self.mode == "type":
            self._kb.type(text)
            return
        self._paste(text)

    def _paste(self, text: str) -> None:
        old = None
        if self.restore_clipboard:
            try:
                old = pyperclip.paste()
            except Exception:  # noqa: BLE001
                old = None
        pyperclip.copy(text)
        # 确保用户按热键时残留的修饰键不会干扰 Ctrl+V
        for k in (Key.ctrl_r, Key.alt_l, Key.alt_r, Key.shift, Key.cmd):
            try:
                self._kb.release(k)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.12)
        self._kb.press(Key.ctrl)
        time.sleep(0.02)
        self._kb.press("v")
        time.sleep(0.02)
        self._kb.release("v")
        time.sleep(0.02)
        self._kb.release(Key.ctrl)
        if self.restore_clipboard and old is not None:
            # 给目标程序一点时间读取剪贴板，再恢复原内容
            time.sleep(0.5)
            try:
                pyperclip.copy(old)
            except Exception:  # noqa: BLE001
                pass
