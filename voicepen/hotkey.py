"""全局热键：按住说话（hold，支持单键或组合键）与切换模式（toggle）。"""

from __future__ import annotations

import threading
from typing import Callable

from pynput import keyboard

# 泛化修饰键：配置里写 ctrl / alt / shift / cmd 时，左右两个都算
_GENERIC = {
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "cmd": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
    "win": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
}


def parse_key(name: str) -> frozenset:
    """把一个按键名转成“等价按键集合”。支持 'ctrl_r'、'f8'、'a'、'ctrl'（左右都算）等。"""
    name = name.strip().lower().strip("<>")
    if name in _GENERIC:
        return frozenset(_GENERIC[name])
    if hasattr(keyboard.Key, name):
        return frozenset({getattr(keyboard.Key, name)})
    if len(name) == 1:
        return frozenset({keyboard.KeyCode.from_char(name)})
    raise ValueError(f"无法识别的按键名: {name!r}")


def parse_hold(spec: str) -> list[frozenset]:
    """'ctrl_r' → [{ctrl_r}]；'<ctrl>+<alt>' → [{ctrl…}, {alt…}]。"""
    return [parse_key(p) for p in spec.split("+") if p.strip()]


class HotkeyManager:
    """
    on_hold_start / on_hold_end : 按住键（组合）全部按下 / 任一松开
    on_toggle                   : 切换组合键触发一次
    """

    def __init__(self, hold_key: str | None, toggle_combo: str | None,
                 on_hold_start: Callable[[], None], on_hold_end: Callable[[], None],
                 on_toggle: Callable[[], None]):
        self._hold_parts = parse_hold(hold_key) if hold_key else []
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._on_toggle = on_toggle
        self._toggle: keyboard.HotKey | None = None
        if toggle_combo:
            self._toggle = keyboard.HotKey(keyboard.HotKey.parse(toggle_combo), self._fire_toggle)
        self._down: set = set()  # 当前按下的、属于 hold 组合的键
        self._holding = False
        self._lock = threading.Lock()
        self.paused = False  # 程序自己模拟按键（如 Ctrl+V）时置 True，避免自触发
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    def _fire_toggle(self):
        if not self.paused:
            self._on_toggle()

    def _norm(self, key):
        """把按键归一到可比较的对象（Key 或 KeyCode(char/vk)）。"""
        if isinstance(key, keyboard.KeyCode):
            if key.char is not None:
                return keyboard.KeyCode.from_char(key.char.lower())
            # 无 char 的 vk：可能是修饰键在部分环境的报告方式
            for k in keyboard.Key:
                if getattr(k.value, "vk", None) == key.vk:
                    return k
        return key

    def _all_parts_down(self) -> bool:
        return all(any(k in part for k in self._down) for part in self._hold_parts)

    def _on_press(self, key):
        canonical = self._listener.canonical(key) if self._listener else key
        if self._toggle is not None and not self.paused:
            self._toggle.press(canonical)
        if not self._hold_parts:
            return
        k = self._norm(key)
        if any(k in part for part in self._hold_parts):
            with self._lock:
                self._down.add(k)
                if self._holding or self.paused or not self._all_parts_down():
                    return  # Windows 会持续重复发送按下事件 / 组合未按全
                self._holding = True
            self._on_hold_start()

    def _on_release(self, key):
        canonical = self._listener.canonical(key) if self._listener else key
        if self._toggle is not None:
            self._toggle.release(canonical)
        if not self._hold_parts:
            return
        k = self._norm(key)
        with self._lock:
            self._down.discard(k)
            if not self._holding or self._all_parts_down():
                return
            self._holding = False
        if not self.paused:
            self._on_hold_end()
