# VoicePen — AI 语音输入（Typeless 风格）

按住热键说话，松开后自动：**语音识别 → Claude 润色（去语气词 / 改口只留最终意思 / 纠错 / 补标点 / 整理条理）→ 粘贴到当前光标处**。
在任何软件里都能用（微信、浏览器、Word、IDE…），常驻系统托盘。

## 快速开始

1. 安装依赖（已自动创建 `.venv`）：
   ```bat
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. AI 润色使用**本机已登录的 Claude Code**（走 Claude Pro/Max 订阅额度，不需要 API key）：
   安装 [Claude Code](https://claude.com/claude-code) 后在终端运行一次 `claude` 完成登录即可。
   > 没装 Claude Code 也能用：只做语音识别、不润色。
3. 启动：双击 `run.bat`（后台运行，无窗口）；调试用 `run_debug.bat`（保留控制台输出）。
4. 在任意输入框里：**同时按住 Ctrl+Alt 说话，松开**。屏幕底部会显示状态：
   `● 正在聆听 → ◐ 识别中 → ✦ AI 润色中 → ✔ 已输入`。
   也可以按 `Ctrl+Shift+Space` 切换开始/结束（适合长段落）。

首次使用会自动下载本地语音模型（`small`，约 460MB），之后离线可用。

## 效果示例（预期）

| 说的话（识别原文） | 润色后 |
|---|---|
| 嗯，那个，我想说的是，就是明天下午三点，不对，四点，我们在会议室开个会，然后然后主要讨论一下这个季度的，呃，销售数据，还有下个季度的计划。 | 明天下午四点我们在会议室开个会，主要讨论这个季度的销售数据，以及下个季度的计划。 |

## 配置（`config.json`，首次运行自动生成）

| 项 | 说明 |
|---|---|
| `hotkey.hold_key` | 按住说话的键，默认 `<ctrl>+<alt>`（左右都可）。可改单键如 `f8`、`ctrl_r`、`caps_lock` |
| `hotkey.toggle_combo` | 切换模式组合键，默认 `<ctrl>+<shift>+<space>`，留空禁用 |
| `stt.provider` | `local` = 本地 faster-whisper（默认，离线）；`api` = OpenAI 兼容云端接口（OpenAI / Groq 等，需要 `OPENAI_API_KEY`），云端更快更准 |
| `stt.language` | `zh` / `en` / `auto` |
| `stt.local.model` | `tiny` / `base` / `small` / `medium` / `large-v3`，越大越准越慢；有 NVIDIA 显卡且装了 CUDA 12 + cuDNN 9 可把 `device` 改为 `cuda` |
| `polish.enabled` | 是否 AI 润色（托盘菜单也可切换） |
| `polish.model` | 默认 `claude-sonnet-5`；追求更高质量可改 `claude-opus-5`，更低延迟可改 `claude-haiku-4-5`（须是你 Claude Code 账号可用的模型） |
| `polish.claude_cli` | `claude` 命令的路径，留空自动查找（PATH、`~/.local/bin`） |
| `polish.style` | `clean` 标准整理 / `formal` 正式书面 / `bullets` 要点列表 / `casual` 轻松口语 |
| `polish.custom_instruction` | 附加要求，如“‘小陈’是人名不要改；术语保留英文” |
| `output.mode` | `paste` 剪贴板粘贴（默认，会自动恢复原剪贴板）；`type` 模拟逐字键入 |
| `history.path` | 每次输入的原文/润色结果记录在 `history.jsonl` |

托盘图标右键：开关润色、切换风格、打开配置 / 历史、退出。修改 `config.json` 后重启生效。

## 命令行调试

```bat
.venv\Scripts\python main.py --test-file 录音.wav            # 识别 + 润色
.venv\Scripts\python main.py --test-file 录音.wav --no-polish
.venv\Scripts\python main.py --test-polish "嗯 那个 我想说 就是 明天开会"
set VOICEPEN_DEBUG=1 && .venv\Scripts\python main.py         # 启动并在控制台打印状态
```

## 项目结构

```
main.py               入口
voicepen/config.py    配置 + .env
voicepen/audio.py     麦克风录音
voicepen/stt.py       语音识别（本地 faster-whisper / 云端 API）
voicepen/polish.py    Claude 润色（调用本机 Claude Code CLI）
voicepen/inject.py    粘贴到活动窗口
voicepen/hotkey.py    全局热键（按住 / 切换）
voicepen/ui.py        状态悬浮窗 + 托盘
voicepen/app.py       主流程
```

## 已知限制

- 目标程序若以管理员权限运行，普通权限的 VoicePen 无法向其粘贴（Windows UIPI 限制），请同样以管理员运行 VoicePen。
- 本地 `small` 模型对专有名词识别一般，可以换更大的模型，或改用云端 `api` 模式。
