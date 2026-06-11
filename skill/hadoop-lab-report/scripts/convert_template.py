#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把旧版二进制 .doc 转成 .docx(docx skill 只能编辑 .docx)。

优先用 Windows 自带 Word 的 COM 自动化(本机装了 Office);失败再退回 LibreOffice soffice。

用法:
  python convert_template.py [输入.doc] [输出.docx]
  # 缺省:输入 = ./干净的模板.doc(或 skill assets 里的同名),输出 = <skill>/assets/template.docx
"""
from __future__ import annotations
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
sys.path.insert(0, HERE)
from _common import eprint  # noqa: E402

DEFAULT_INPUTS = ["干净的模板.doc", os.path.join(ASSETS, "干净的模板.doc")]
DEFAULT_OUTPUT = os.path.join(ASSETS, "template.docx")


def via_word_com(src, dst):
    """用 Word COM 转换(wdFormatDocumentDefault=16 即 .docx)。"""
    ps = f"""
$ErrorActionPreference='Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {{
  $doc = $w.Documents.Open('{src}', $false, $true)
  $doc.SaveAs([ref]'{dst}', [ref]16)
  $doc.Close($false)
  Write-Output 'WORD_OK'
}} finally {{ $w.Quit() }}
"""
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    if "WORD_OK" in (p.stdout or "") and os.path.exists(dst):
        return True
    eprint("[Word COM 失败]", (p.stderr or p.stdout or "")[:300])
    return False


def via_soffice(src, dst):
    """退回 LibreOffice;优先用 docx skill 的 soffice 包装。"""
    outdir = os.path.dirname(os.path.abspath(dst))
    # 寻找 docx skill 的 soffice.py
    candidates = []
    base = os.environ.get("APPDATA", "")
    for root, _, files in os.walk(base) if base else []:
        if "soffice.py" in files and os.sep + "office" in root:
            candidates.append(os.path.join(root, "soffice.py"))
            break
    cmds = []
    if candidates:
        cmds.append([sys.executable, candidates[0], "--headless", "--convert-to", "docx",
                     "--outdir", outdir, src])
    cmds.append(["soffice", "--headless", "--convert-to", "docx", "--outdir", outdir, src])
    for c in cmds:
        try:
            p = subprocess.run(c, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
            produced = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".docx")
            if os.path.exists(produced):
                if os.path.abspath(produced) != os.path.abspath(dst):
                    os.replace(produced, dst)
                return True
        except Exception as e:
            eprint("[soffice 尝试失败]", type(e).__name__, str(e)[:150])
    return False


def main():
    args = sys.argv[1:]
    src = args[0] if len(args) >= 1 else next((p for p in DEFAULT_INPUTS if os.path.exists(p)), None)
    dst = args[1] if len(args) >= 2 else DEFAULT_OUTPUT
    if not src or not os.path.exists(src):
        eprint("找不到输入 .doc,请指定路径。尝试过:", DEFAULT_INPUTS)
        sys.exit(2)
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    if via_word_com(src, dst) or via_soffice(src, dst):
        eprint(f"[OK] 已转换: {src}\n  ->  {dst}")
        sys.exit(0)
    eprint("[X] 转换失败:Word COM 与 soffice 都不可用。")
    sys.exit(1)


if __name__ == "__main__":
    main()
