"""语音转文字。两个后端：本地 faster-whisper（离线）或 OpenAI 兼容云端接口。"""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np

from .audio import normalize, to_float32, to_wav_bytes


class STTError(RuntimeError):
    pass


class LocalWhisper:
    """faster-whisper 本地识别。模型在后台线程预加载，首次使用不用等。"""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.language = None if cfg.get("language") in (None, "", "auto") else cfg["language"]
        self._model = None
        self._error: Exception | None = None
        self._ready = threading.Event()
        threading.Thread(target=self._load, daemon=True, name="whisper-load").start()

    def _load(self):
        try:
            self._model = self._build_model(cpu_only=False)
        except Exception as e:  # noqa: BLE001
            self._error = e
        finally:
            self._ready.set()

    def _build_model(self, cpu_only: bool):
        from faster_whisper import WhisperModel

        local = self.cfg["local"]
        device = "cpu" if cpu_only else local.get("device", "cpu")
        compute_type = "int8" if device == "cpu" else local.get("compute_type", "float16")
        try:
            return WhisperModel(local["model"], device=device, compute_type=compute_type)
        except Exception:
            if device != "cpu":
                return WhisperModel(local["model"], device="cpu", compute_type="int8")
            raise

    def _fallback_to_cpu(self):
        self._model = self._build_model(cpu_only=True)

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._model is not None

    def wait_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout)

    def transcribe(self, audio_int16: np.ndarray, sample_rate: int) -> str:
        self._ready.wait()
        if self._error is not None:
            raise STTError(f"本地 whisper 模型加载失败: {self._error}")
        local = self.cfg["local"]
        # 中文提示可以显著提高标点与简体输出的稳定性
        initial_prompt = None
        if self.language == "zh":
            initial_prompt = "以下是普通话的句子，使用简体中文和标点符号。"
        kwargs = dict(
            language=self.language,
            beam_size=int(local.get("beam_size", 5)),
            vad_filter=bool(local.get("vad_filter", True)),
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            temperature=0.0,
            # 抗幻觉：静音/噪音段判为无语音，避免吐出“请点赞订阅”之类的训练残留字幕
            no_speech_threshold=float(local.get("no_speech_threshold", 0.6)),
            log_prob_threshold=float(local.get("log_prob_threshold", -1.0)),
            compression_ratio_threshold=2.4,
        )
        if local.get("normalize", True):
            audio_int16 = normalize(audio_int16)
        wav = to_float32(audio_int16)
        try:
            segments, _info = self._model.transcribe(wav, **kwargs)
            text = "".join(seg.text for seg in segments)
        except RuntimeError as e:
            # CUDA 运行库缺失（cublas/cudnn）时回退到 CPU 再试一次
            if any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda")):
                self._fallback_to_cpu()
                segments, _info = self._model.transcribe(wav, **kwargs)
                text = "".join(seg.text for seg in segments)
            else:
                raise
        return _drop_hallucinations(text.strip())


class ApiWhisper:
    """调用 OpenAI 兼容的 POST {base_url}/audio/transcriptions（OpenAI、Groq 等都兼容）。"""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.language = None if cfg.get("language") in (None, "", "auto") else cfg["language"]
        api = cfg["api"]
        self.base_url = api["base_url"].rstrip("/")
        self.model = api["model"]
        self.api_key = os.environ.get(api.get("api_key_env", "OPENAI_API_KEY"), "")

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def wait_ready(self, timeout: float | None = None) -> bool:
        return True

    def transcribe(self, audio_int16: np.ndarray, sample_rate: int) -> str:
        import httpx

        if not self.api_key:
            raise STTError(f"未设置 {self.cfg['api'].get('api_key_env')}，无法调用云端语音识别")
        data = {"model": self.model, "response_format": "json"}
        if self.language:
            data["language"] = self.language
        audio_int16 = normalize(audio_int16)
        files = {"file": ("audio.wav", to_wav_bytes(audio_int16, sample_rate), "audio/wav")}
        try:
            r = httpx.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
                timeout=60,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise STTError(f"云端语音识别失败: {e}") from e
        return (r.json().get("text") or "").strip()


# Whisper 在静音/纯噪音上常吐出的训练残留字幕短语；整段等于其一时直接丢弃
_HALLUCINATION_PHRASES = {
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    "请不吝点赞 订阅 转发 打赏",
    "字幕由amara.org社区提供",
    "明镜与点点栏目",
    "谢谢观看",
    "谢谢大家",
    "下期再见",
    "请订阅",
}


def _drop_hallucinations(text: str) -> str:
    compact = "".join(ch for ch in text if ch not in " ，。！!、,.")
    for p in _HALLUCINATION_PHRASES:
        pc = p.replace(" ", "")
        if compact == pc or (compact and len(compact) <= len(pc) + 3 and pc in compact):
            return ""
    return text


def build_stt(cfg: dict[str, Any]):
    provider = cfg.get("provider", "local")
    if provider == "api":
        return ApiWhisper(cfg)
    return LocalWhisper(cfg)
