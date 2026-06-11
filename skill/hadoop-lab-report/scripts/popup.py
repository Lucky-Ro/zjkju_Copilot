#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一弹窗助手(远程帮修模式抓注意力用)—— 纯 Python,不碰 PowerShell。

为什么纯 Python:
- 之前经 PowerShell 弹窗要 `-ExecutionPolicy Bypass`,会被安全分类器拦,且易留空白控制台。
- 这里直接用 ctypes 调 Win32 `MessageBoxW`:原生 Unicode(中文不乱码)、置顶、前台,
  detached + CREATE_NO_WINDOW 启动子进程显示,不阻塞调用方、不留空白窗。

用法:
  python popup.py "卡在 4.1 第3步,需要你配一下网卡,弄好回我『继续』"
  python popup.py --title "实验已完成" "报告已生成,见 报告.docx"
密码等敏感信息绝不要放进消息。
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile

# Win32 MessageBox flags
MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_SYSTEMMODAL = 0x1000
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
FLAGS = MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST


def _show_from_file(meta_path: str):
    """子进程:读 UTF-8 元数据 → 弹 MessageBoxW → 删临时文件。"""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    finally:
        try:
            os.unlink(meta_path)
        except OSError:
            pass
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, meta.get("message", ""), meta.get("title", ""), FLAGS)


def fire(message: str, title: str = "Hadoop 实验报告 Copilot - 需要你帮个忙") -> None:
    """父进程:写临时元数据,detached 起一个无窗口子进程去弹框,自己立刻返回。"""
    fd, meta_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"message": message, "title": title}, f, ensure_ascii=False)
    CREATE_NO_WINDOW = 0x08000000
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--show", meta_path],
                     creationflags=flags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="*")
    ap.add_argument("--title", default="Hadoop 实验报告 Copilot - 需要你帮个忙")
    ap.add_argument("--show", help="(内部)从该 JSON 文件读取并弹窗")
    args = ap.parse_args()
    if args.show:
        _show_from_file(args.show)
        return
    msg = " ".join(args.message).strip() or "需要你处理一下,详见对话。"
    fire(msg, args.title)
    print("[popup] 已弹出提醒")


if __name__ == "__main__":
    main()
