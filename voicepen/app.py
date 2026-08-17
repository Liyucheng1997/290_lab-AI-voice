"""VoicePen 主流程：热键 → 录音 → 转写 → 润色 → 粘贴。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config as cfgmod
from .audio import Recorder
from .hotkey import HotkeyManager
from .inject import TextInjector
from .polish import PolishError, build_polisher
from .stt import STTError, build_stt
from .ui import Overlay, build_tray


class VoicePenApp:
    def __init__(self):
        self.cfg = cfgmod.load_config()
        self.status_text = "空闲"
        self._busy = False
        self._lock = threading.Lock()

        self.overlay = Overlay(enabled=self.cfg["ui"].get("overlay", True))
        self.recorder = Recorder(
            sample_rate=int(self.cfg["audio"]["sample_rate"]),
            device=self.cfg["audio"].get("device"),
            on_level=self.overlay.set_level,
        )
        self.stt = build_stt(self.cfg["stt"])
        self.polisher = build_polisher(self.cfg["polish"])
        out = self.cfg["output"]
        self.injector = TextInjector(out.get("mode", "paste"), out.get("restore_clipboard", True),
                                     out.get("append_space", False))
        hk = self.cfg["hotkey"]
        self.hotkeys = HotkeyManager(
            hk.get("hold_key"), hk.get("toggle_combo"),
            on_hold_start=self.start_recording, on_hold_end=self.stop_recording,
            on_toggle=self.toggle_recording,
        )
        self.tray = build_tray(self) if self.cfg["ui"].get("tray", True) else None
        self.history_path = cfgmod.PROJECT_DIR / self.cfg["history"].get("path", "history.jsonl")

    # ---------- 托盘用到的属性 ----------
    @property
    def polish_enabled(self) -> bool:
        return bool(self.cfg["polish"].get("enabled", True))

    @property
    def style(self) -> str:
        return self.cfg["polish"].get("style", "clean")

    @property
    def hold_key_name(self) -> str:
        return (self.cfg["hotkey"].get("hold_key") or "-").replace("<", "").replace(">", "").replace("+", " + ").replace("_r", "(右)").replace("_l", "(左)")

    def set_polish_enabled(self, enabled: bool) -> None:
        self.cfg["polish"]["enabled"] = enabled
        cfgmod.save_config(self.cfg)
        self.overlay.show("info", f"AI 润色已{'开启' if enabled else '关闭'}", auto_hide=1.5)

    def set_style(self, style: str) -> None:
        self.cfg["polish"]["style"] = style
        self.polisher.style = style
        cfgmod.save_config(self.cfg)
        self.overlay.show("info", f"润色风格：{style}", auto_hide=1.5)

    def open_config(self) -> None:
        os.startfile(cfgmod.CONFIG_PATH)  # type: ignore[attr-defined]

    def open_history(self) -> None:
        if not self.history_path.exists():
            self.history_path.write_text("", encoding="utf-8")
        os.startfile(self.history_path)  # type: ignore[attr-defined]

    def quit(self) -> None:
        try:
            self.hotkeys.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:  # noqa: BLE001
                pass
        self.overlay.quit()

    # ---------- 录音控制 ----------
    def start_recording(self) -> None:
        with self._lock:
            if self._busy or self.recorder.recording:
                return
            try:
                self.recorder.start()
            except Exception as e:  # noqa: BLE001
                self.overlay.show("error", f"无法打开麦克风：{e}", auto_hide=3)
                return
        self.status_text = "录音中"
        self.overlay.show("recording", "正在聆听… 松开结束")

    def stop_recording(self) -> None:
        with self._lock:
            if not self.recorder.recording:
                return
            audio = self.recorder.stop()
            if self.recorder.duration(audio) < float(self.cfg["audio"].get("min_seconds", 0.4)):
                self.status_text = "空闲"
                self.overlay.hide()
                return
            self._busy = True
        threading.Thread(target=self._pipeline, args=(audio,), daemon=True, name="pipeline").start()

    def toggle_recording(self) -> None:
        if self.recorder.recording:
            self.stop_recording()
        else:
            self.start_recording()

    # ---------- 核心流水线 ----------
    def _pipeline(self, audio) -> None:
        t0 = time.perf_counter()
        raw = polished = ""
        stt_ms = polish_ms = 0
        try:
            if not self.stt.ready:
                self.overlay.show("transcribing", "首次使用，正在加载语音模型…（下载可能需要一会）")
                self.stt.wait_ready()
            self.status_text = "转写中"
            self.overlay.show("transcribing", "正在识别语音…")
            t1 = time.perf_counter()
            raw = self.stt.transcribe(audio, self.recorder.sample_rate)
            stt_ms = int((time.perf_counter() - t1) * 1000)
            if not raw.strip():
                self.overlay.show("info", "没有听清，请再试一次", auto_hide=1.5)
                return

            final = raw
            if self.polish_enabled and self.polisher.available:
                self.status_text = "润色中"
                self.overlay.show("polishing", f"AI 润色中… \n{_preview(raw)}")
                t2 = time.perf_counter()
                try:
                    polished = self.polisher.polish(raw)
                    polish_ms = int((time.perf_counter() - t2) * 1000)
                    if polished:
                        final = polished
                except PolishError as e:
                    self.overlay.show("error", f"润色失败，已粘贴原文：{e}", auto_hide=3)
                    time.sleep(0.8)
            elif self.polish_enabled and not self.polisher.available:
                self.overlay.show("info", "未找到 Claude Code CLI，仅粘贴识别原文", auto_hide=2)
                time.sleep(0.6)

            self.status_text = "输入中"
            self.hotkeys.paused = True
            try:
                self.injector.inject(final)
            finally:
                self.hotkeys.paused = False
            self.overlay.show("done", _preview(final), auto_hide=2.0)
            self._append_history(raw, polished, self.recorder.duration(audio), stt_ms, polish_ms)
        except STTError as e:
            self.overlay.show("error", str(e), auto_hide=4)
        except Exception as e:  # noqa: BLE001
            self.overlay.show("error", f"出错了：{type(e).__name__}: {e}", auto_hide=4)
        finally:
            self._busy = False
            self.status_text = "空闲"
            _ = t0

    def _append_history(self, raw: str, polished: str, duration: float, stt_ms: int, polish_ms: int) -> None:
        if not self.cfg["history"].get("enabled", True):
            return
        rec = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(duration, 2),
            "raw": raw,
            "polished": polished,
            "stt_ms": stt_ms,
            "polish_ms": polish_ms,
        }
        try:
            with self.history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- 启动 ----------
    def run(self) -> None:
        self.hotkeys.start()
        if self.tray is not None:
            self.tray.run_detached()

        hold = self.cfg["hotkey"].get("hold_key")
        toggle = self.cfg["hotkey"].get("toggle_combo")
        tips = []
        if hold:
            tips.append(f"按住 {hold} 说话")
        if toggle:
            tips.append(f"{toggle} 开始/结束")
        self.overlay.show("info", "VoicePen 已启动 · " + "，".join(tips), auto_hide=3.5)

        def _warn_later():
            time.sleep(4)
            if self.polish_enabled and not self.polisher.available:
                self.overlay.show("info", "未检测到 Claude Code CLI（claude 命令）：请安装 Claude Code 并在终端运行 claude 登录，重启后即可 AI 润色", auto_hide=5)
            if hasattr(self.stt, "wait_ready"):
                self.stt.wait_ready()
                if not self.stt.ready and self.cfg["stt"].get("provider", "local") == "local":
                    self.overlay.show("error", f"语音模型加载失败：{getattr(self.stt, '_error', '')}", auto_hide=8)

        threading.Thread(target=_warn_later, daemon=True).start()
        self.overlay.run()


def _preview(text: str, n: int = 60) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def run_cli_test(args: list[str]) -> int:
    """命令行调试：--test-file x.wav [--no-polish] / --test-polish "文本"。"""
    cfg = cfgmod.load_config()
    if "--test-polish" in args:
        text = args[args.index("--test-polish") + 1]
        out = build_polisher(cfg["polish"]).polish(text)
        print("RAW     :", text)
        print("POLISHED:", out)
        return 0
    if "--test-file" in args:
        import wave

        import numpy as np

        path = Path(args[args.index("--test-file") + 1])
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            nch = wf.getnchannels()
            width = wf.getsampwidth()
        if width != 2:
            print("只支持 16-bit PCM wav", file=sys.stderr)
            return 2
        audio = np.frombuffer(frames, dtype=np.int16)
        if nch > 1:
            audio = audio.reshape(-1, nch)[:, 0]
        if sr != 16000:
            # 简单线性重采样到 16k
            x_old = np.linspace(0, 1, len(audio), endpoint=False)
            x_new = np.linspace(0, 1, int(len(audio) * 16000 / sr), endpoint=False)
            audio = np.interp(x_new, x_old, audio.astype(np.float32)).astype(np.int16)
            sr = 16000
        stt = build_stt(cfg["stt"])
        print("加载语音模型…")
        stt.wait_ready()
        t = time.perf_counter()
        raw = stt.transcribe(audio, sr)
        print(f"RAW ({int((time.perf_counter()-t)*1000)} ms):", raw)
        if "--no-polish" not in args:
            p = build_polisher(cfg["polish"])
            if p.available:
                t = time.perf_counter()
                print(f"POLISHED ({int((time.perf_counter()-t)*1000)} ms):", p.polish(raw))
            else:
                print("(未找到 Claude Code CLI，跳过润色)")
        return 0
    print(__doc__)
    return 1
