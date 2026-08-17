"""麦克风录音：开始/停止，返回 16kHz 单声道 float32 波形。"""

from __future__ import annotations

import io
import threading
import wave
from typing import Callable

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int = 16000, device=None,
                 on_level: Callable[[float], None] | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self.on_level = on_level  # 每个音频块回调一次音量 (0~1)，用于悬浮窗电平条
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):
        if status:
            pass  # overflow 等状态，忽略即可
        block = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(block)
        if self.on_level is not None:
            rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
            self.on_level(min(1.0, rms / 3000.0))

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=self.device,
            blocksize=1024,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """停止录音，返回 int16 波形（可能为空数组）。"""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks)

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / self.sample_rate


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


def to_float32(audio: np.ndarray) -> np.ndarray:
    return audio.astype(np.float32) / 32768.0


def normalize(audio_int16: np.ndarray, target_peak: float = 0.95,
              max_gain: float = 12.0, noise_floor: int = 60) -> np.ndarray:
    """把偏小的录音音量放大到接近满量程。内置麦克风常常音量很低，直接拖累识别率。

    target_peak: 归一化后的峰值(0~1)，留余量防削波；max_gain: 最大放大倍数(防把噪音放大成信号)；
    noise_floor: 峰值低于该 int16 值则认为无有效语音，不放大。
    """
    if audio_int16.size == 0:
        return audio_int16
    peak = int(np.max(np.abs(audio_int16)))
    if peak < noise_floor:
        return audio_int16
    gain = min(max_gain, (target_peak * 32767.0) / peak)
    if gain <= 1.05:
        return audio_int16  # 音量已够大
    out = np.clip(audio_int16.astype(np.float32) * gain, -32768, 32767)
    return out.astype(np.int16)
