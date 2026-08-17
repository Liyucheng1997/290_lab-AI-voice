"""配置加载：项目目录下的 config.json + .env。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.json"
ENV_PATH = PROJECT_DIR / ".env"

DEFAULT_CONFIG: dict[str, Any] = {
    # 热键
    "hotkey": {
        # hold: 按住说话，松开结束。单键如 f8 / ctrl_r / caps_lock，或组合键如 <ctrl>+<alt>（左右 Ctrl/Alt 都算）
        "hold_key": "<ctrl>+<alt>",
        # toggle: 按一次开始，再按一次结束（可与 hold 同时启用）。特殊键用尖括号，如 <ctrl>+<alt>+<space>、<ctrl>+<shift>+v；留空 "" 则禁用
        "toggle_combo": "<ctrl>+<shift>+<space>",
    },
    # 语音识别
    "stt": {
        # local = 本地 faster-whisper（离线，无需 key）；api = OpenAI 兼容的 /audio/transcriptions 接口
        "provider": "local",
        "language": "zh",  # zh / en / auto
        "local": {
            # tiny/base/small/medium/large-v3，越大越准越慢。想更准可用 medium/large-v3，
            # 但本机 int8 量化对 medium 会乱码：用大模型时必须把 compute_type 一并改成 "float32"（慢但稳）。
            "model": "small",
            "device": "cpu",  # cpu / cuda（cuda 需要 CUDA 12 + cuDNN 9 运行库，缺失时自动回退 cpu）
            "compute_type": "int8",  # small 用 int8（快）；medium/large 本机请改 float32
            "beam_size": 5,
            "vad_filter": True,
            "normalize": True,  # 自动放大偏小的录音音量，显著提升真人麦克风识别率
            "no_speech_threshold": 0.6,  # 越大越容易把轻声段判为静音，抑制幻觉
            "log_prob_threshold": -1.0,
        },
        "api": {
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model": "whisper-1",
        },
    },
    # AI 润色（Claude）—— 通过本机已登录的 Claude Code CLI（claude -p）调用，走 Claude Code 订阅额度，无需 API key
    "polish": {
        "enabled": True,
        "model": "claude-sonnet-5",  # 也可用 claude-opus-5 / claude-haiku-4-5
        "effort": "low",  # low / medium / high —— 语音润色用 low 最快
        "style": "clean",  # clean / formal / bullets / casual
        "custom_instruction": "",  # 附加给模型的个性化要求，如“我说的‘小陈’是人名，不要改”
        "timeout_seconds": 60,
        "claude_cli": "",  # 留空则自动在 PATH / ~/.local/bin 中查找 claude；也可填完整路径
    },
    # 输出
    "output": {
        "mode": "paste",  # paste = 剪贴板粘贴（推荐，中文可靠）；type = 模拟逐字键入
        "restore_clipboard": True,
        "append_space": False,
    },
    "audio": {
        "sample_rate": 16000,
        "device": None,  # None = 系统默认输入设备；也可填设备编号
        "min_seconds": 0.4,  # 短于这个时长的录音直接忽略
    },
    "ui": {
        "overlay": True,
        "tray": True,
    },
    "history": {
        "enabled": True,
        "path": "history.jsonl",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env(path: Path = ENV_PATH) -> None:
    """把 .env 里的 KEY=VALUE 写进 os.environ（不覆盖已有环境变量）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    load_env()
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
        return copy.deepcopy(DEFAULT_CONFIG)
    user = json.loads(path.read_text(encoding="utf-8"))
    return _deep_merge(DEFAULT_CONFIG, user)


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
