"""VoicePen 入口。

用法：
  python main.py                        启动（托盘 + 悬浮窗 + 全局热键）
  python main.py --test-file a.wav      用一个 wav 文件测试 识别→润色 流程
  python main.py --test-file a.wav --no-polish
  python main.py --test-polish "嗯 那个 我想说的是 就是 明天开会"   只测试润色
"""

import sys


def main() -> int:
    args = sys.argv[1:]
    if any(a.startswith("--test") for a in args):
        from voicepen.app import run_cli_test

        return run_cli_test(args)

    # 单实例保护：占用一个本地端口，第二个实例启动时直接退出，避免热键被触发两次
    import socket

    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", 47831))
        guard.listen(1)
    except OSError:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, "VoicePen 已经在运行（看系统托盘）。", "VoicePen", 0x40)
        except Exception:  # noqa: BLE001
            print("VoicePen 已经在运行。")
        return 0

    from voicepen.app import VoicePenApp

    VoicePenApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
