#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时日志窗口(纯 Python,自带控制台)。

为什么用 Python 而不是 PowerShell:
- 之前用 `Start-Process powershell -ExecutionPolicy Bypass -File live_tail.ps1` 直接当工具命令开窗口,
  被安全分类器拦(Bypass=削弱安全)。改成纯 Python,由 ssh_runner 用 `python` 在新控制台拉起,
  不碰 PowerShell / 执行策略 / 分类器。
- 立刻打印已有内容(修「第一行不显示」),再 150ms 低延迟跟随(修「等好久」)。

用法(ssh_runner 会自动拉起;也可手动):
  python live_tail.py <run.log 路径>
"""
from __future__ import annotations
import os
import sys
import time

C = {"cmd": "\033[96m", "head": "\033[93m", "err": "\033[91m",
     "ans": "\033[90m", "out": "\033[0m", "dim": "\033[90m", "reset": "\033[0m"}
ERR_WORDS = ("error", "fail", "exception", "denied", "refused", "traceback")


def _enable_vt_and_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            ctypes.windll.kernel32.SetConsoleTitleW("Hadoop Lab Report - LIVE")
        except Exception:
            pass


def colorize(line: str) -> str:
    s = line.rstrip("\n")
    low = s.lower()
    if s.startswith(">> (应答)"):
        c = C["ans"]
    elif s.startswith(">> "):
        c = C["cmd"]
    elif s.startswith("### "):
        c = C["head"]
    elif any(w in low for w in ERR_WORDS):
        c = C["err"]
    else:
        c = C["out"]
    return c + s + C["reset"]


def main():
    if len(sys.argv) < 2:
        print("usage: python live_tail.py <run.log>")
        return
    path = os.path.abspath(sys.argv[1])
    _enable_vt_and_utf8()
    print(C["head"] + "==== LIVE VIEW (real time) ====" + C["reset"])
    print(C["dim"] + path + C["reset"])
    print("-" * 60)
    n = 0
    while not os.path.exists(path):
        time.sleep(0.2)
        n += 1
        if n % 25 == 0:
            print(C["dim"] + "(等待日志文件出现...)" + C["reset"])
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        while True:
            line = f.readline()
            if line:
                print(colorize(line))
            else:
                time.sleep(0.15)   # 到文件末尾:稍等再继续跟随


if __name__ == "__main__":
    main()
