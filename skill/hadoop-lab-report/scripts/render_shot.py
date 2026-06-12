#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把无头 SSH 终端的**真实输出**忠实重放成 **FinalShell 默认风格** 的终端截图 PNG(HTML + 无头 Edge)。

风格:纯黑底、白色等宽字、右侧一条淡淡的滚动条;**没有** macOS 窗框 /
红绿灯圆点 / 语法高亮——看起来就像在 FinalShell 里随手拖拽框选的截图,不疏离。

**提示符不再伪造:** `ssh_runner.py` 已开 PTY 回显并用真实 hostname 的 PS1,命令以「真实提示符 +
命令」形式落进 run.log(`[hadoop@<真实hostname> ~]$ cmd`)。本脚本**逐行重放该真实流**,只对可识别的
提示符前缀做着色(不改内容);`--prompt` **退为兜底**,仅用于无 PTY 回显的旧日志段。

本脚本自带三项「成品级」处理,**唯一权威渲染路径就是 `--from-log`**,Claude 不必再手写一次性渲染脚本:
- **命令清洗(clean_cmd)**:从截图显示里剥掉为自动化注入、学生本不会敲的管道噪声——开头的
  `sleep N;` / `source /etc/profile…;`,以及 `>/dev/null 2>&1` / `2>/dev/null` 重定向。**只动截图,
  run.log 仍存真实命令**(唯一真相)。
- **REPL 交互式美化**:把 `hbase shell <<'EOF' … EOF` 这类 heredoc 包裹 + 重复 banner 折叠成干净的
  `hbase(main):NNN:0> 命令` + 输出(hive/mysql 同理),跨段连号、banner 只出现一次。
- **缺输出守卫**:某段只有命令、没有输出行时,在 stderr 告警(揪出捕获缺失 / 命令-only 渲染)。

用法:
  # 从 run.log 批量渲染(按 '### <subtask>#<idx>' 分段,每段一张图)——**首选**
  python render_shot.py --from-log runs/e04/run.log --out runs/e04/shots/

  # 单段即时渲染(给无真实流的临时内容兜底;此时才需 --prompt 拼提示符)
  python render_shot.py --cmd "select * from empNNN;" --output-text "<真实输出>" \
      --out runs/e04/shots/step-4.2_10.png --prompt "[hadoop@nodeaNNN ~]$"

Win10 自带 Edge,零额外安装。也可 --browser 指定 chrome.exe。
"""
from __future__ import annotations
import argparse
import html
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import eprint  # noqa: E402

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
DEFAULT_PROMPT = "[hadoop@node ~]$"

# ── 版式常量(整数像素,锁死 CSS 与截图高度,避免 HiDPI 半像素裁切)──
# 之前 CSS 用 line-height:1.42 → 15px×1.42 = 21.3px(非整数),叠加 --force-device-scale-factor=2,
# 每行 42.6 设备像素落在半像素位置,栅格化时每行底部那条像素被抗锯齿吃掉(「每行底下缺一条像素」)。
# 改为整数偶数行高(22px → ×2=44 设备像素,整数),且 CSS 与 shoot() 共用同一常量、不再各写一份漂移。
LINE_H = 22          # 行高(px,整数偶数)
FONT_PX = 15         # 字号(px;15×2=30 整数,不影响)
PAD_V, PAD_L, PAD_R = 14, 16, 22   # 终端内边距(上下 / 左 / 右)
SCALE = 2            # 设备像素缩放(整数行高下 2 已无裁切;需更锐可调 3)

# ── 截图裁切坏区间(Edge 无头的真正成因,曾让 5.1#1/2/3 截图「只有命令、没有输出」)──
# 实测:`--window-size=1040,H`,当 H 落在 **≈[100,136]px**(2 行内容恰好算到这区间)时,Edge 无头会把
# 整页塌成只剩第一行(确定性,与时机无关)。旧公式 `34+(行数+1)*22` 对 2~3 行内容正好命中。
# 修法:窗口高度永远给「内容估算 + BAND_MARGIN」,**恒高于坏区间上沿**,再用 Pillow 裁掉底部多余黑边
# 得到紧凑图(Pillow 不可用则保留少量黑边兜底,不影响阅读)。
BAND_MARGIN = 140    # 富余高度:min 窗口 = 28+22+140=190 > 136,且容忍换行行数低估 ~6 行
CHARS_PER_ROW = 116  # 估算每行可容字符(960px 内容宽 / Consolas 15px≈8.25px),用于把长行的换行算进高度

# FinalShell 默认风:纯黑底、白等宽字、真实提示符、右侧淡滚动条、无窗框/无高亮。
CSS = (
    "* { margin:0; padding:0; box-sizing:border-box; }\n"
    "html,body { background:#0c0c0c; }\n"
    ".term { position:relative; width:1000px; background:#0c0c0c; color:#dcdcdc;\n"
    "        font-family:Consolas,'Cascadia Mono','DejaVu Sans Mono',monospace;\n"
    f"        font-size:{FONT_PX}px; line-height:{LINE_H}px; "
    f"padding:{PAD_V}px {PAD_R}px {PAD_V}px {PAD_L}px;\n"
    "        white-space:pre-wrap; word-break:break-all; }\n"
    ".l { display:block; }\n"
    ".prompt { color:#eaeaea; }\n"      # 提示符 [user@host ~]$ 略亮的白
    ".cmd { color:#ffffff; }\n"          # 命令本身,纯白
    ".ans { color:#7a7a7a; }\n"          # 自动喂入的应答,暗灰
    ".out { color:#cfcfcf; }\n"          # 普通输出,浅灰(FinalShell 默认不花哨上色)
    ".sb { position:absolute; top:0; right:3px; width:9px; height:100%;\n"
    "      background:#161616; border-radius:5px; }\n"
    ".sb i { position:absolute; right:0; top:8%; width:9px; height:42%;\n"
    "        background:#3a3a3a; border-radius:5px; }\n"
)


# ───────────────────────── 命令清洗(只动截图显示,run.log 不动) ─────────────────────────
RE_REDIR = re.compile(r"\s*\d?>\s*/dev/null(?:\s+2>&1)?|\s*2>\s*/dev/null")  # >/dev/null 2>&1 / 2>/dev/null
RE_SLEEP = re.compile(r"^\s*sleep\s+\d+(?:\.\d+)?\s*;\s*")                    # 开头的 sleep N;
RE_SRCPROF = re.compile(r"^\s*source\s+/etc/profile[^;&|]*[;&]+\s*")         # 开头的 source /etc/profile…; / &&
RE_HEREDOC_TAIL = re.compile(r"\s*<<\s*'?\w+'?.*$")                          # 末尾的 <<'EOF'…(REPL 启动行用)


def clean_cmd(s):
    """剥掉为自动化注入、学生本不会敲的管道噪声:先去重定向(免得 2>&1 里的 & 干扰 source 段匹配),
    再循环去开头的 sleep / source 直到稳定,收尾清掉残留分号/空白。"""
    s = RE_REDIR.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = RE_SLEEP.sub("", s)
        s = RE_SRCPROF.sub("", s)
    return s.strip().lstrip(";").strip()


# ───────────────────────── 行渲染小工具 ─────────────────────────
# 真实流里可识别的提示符前缀:shell [user@host ~]$/# 、hive>、mysql>、MariaDB [db]>。
RE_PROMPT = re.compile(r'^(\[[^\]\n]*\][$#]|(?:hive|mysql|MariaDB \[[^\]]*\])>)(\s.*)?$')


def _row_prompt(prom, cmd):
    """一行「提示符 + 命令」:提示符着 .prompt,命令着 .cmd,中间留一个空格。"""
    return (f'<span class="l"><span class="prompt">{html.escape(prom)}</span> '
            f'<span class="cmd">{html.escape(cmd.strip())}</span></span>')


def _row_out(text):
    return f'<span class="l out">{html.escape(text)}</span>'


def _prompt_split(line):
    """命中提示符前缀 → 返回 (提示符, 命令部分);否则 None。"""
    m = RE_PROMPT.match(line)
    if not m:
        return None
    return m.group(1), (m.group(2) or "")


def _prompt_only_row(prom):
    return f'<span class="l"><span class="prompt">{html.escape(prom)}</span></span>'


def wrap_page(rows):
    body = "".join(rows)
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body><div class="term">{body}<div class="sb"><i></i></div></div></body></html>')


def render_html(lines, prompt=DEFAULT_PROMPT):
    """lines: list of (kind, text);kind ∈ {cmd, ans, out}。返回 (page, plains):
    plains = 每行的纯文本(供 shoot 估算换行后的真实高度)。
    - out:**真实终端流**,逐行重放(提示符已在流里,识别到就着色、命令过 clean_cmd 去噪);新日志主路径。
    - cmd:**兜底**——仅无 PTY 回显的旧日志段才有 `>> cmd`,此时才用 --prompt 拼提示符。
    - ans:自动喂入的应答(密码已脱敏成 ****),暗灰显示。"""
    rows, plains = [], []
    for kind, text in lines:
        if kind == "cmd":      # 兜底:旧日志的裸命令行,补一个 --prompt
            c = clean_cmd(text)
            rows.append(f'<span class="l"><span class="prompt">{html.escape(prompt)}</span> '
                        f'<span class="cmd">{html.escape(c)}</span></span>')
            plains.append(f"{prompt} {c}")
        elif kind == "ans":
            rows.append(f'<span class="l ans">{html.escape(text)}</span>')
            plains.append(text)
        else:
            sp = _prompt_split(text)
            if sp and sp[1].strip():
                c = clean_cmd(sp[1])
                rows.append(_row_prompt(sp[0], c))
                plains.append(f"{sp[0]} {c}")
            elif sp:
                rows.append(_prompt_only_row(sp[0]))
                plains.append(sp[0])
            else:
                rows.append(_row_out(text))
                plains.append(text)
    return wrap_page(rows), plains


# ───────────────────────── REPL 交互式美化(hbase/hive/mysql heredoc) ─────────────────────────
# 把 `… hbase shell … <<'EOF' / > stmt / > EOF / <重复 banner> / stmt + 输出 / exit` 这种 heredoc 段,
# 折叠成干净的交互会话:`hbase(main):NNN:0> stmt` + 输出。跨段连号、banner 只出现一次。
REPL_SPECS = {
    "hbase": {"launch_re": re.compile(r"\bhbase\s+shell\b"),
              "prompt": "hbase(main):{n:03d}:0>",
              "banner_end_re": re.compile(r"^Version\s")},
    "hive":  {"launch_re": re.compile(r"(?:^|[;&|]\s*)hive\b"),
              "prompt": "hive>", "banner_end_re": None},
    "mysql": {"launch_re": re.compile(r"(?:^|[;&|]\s*)mysql\b"),
              "prompt": "mysql>", "banner_end_re": None},
}
_SKIP_OUT = ("[skip]", "[OK]", "[FAIL]", "[!]", "[manual]", "[author]", "[xml]")


def detect_repl(lines):
    """section 首行是「提示符 + 含 REPL 启动词的 heredoc 命令」→ 返回 repl 名;否则 None。
    `cat >> file <<EOF` 这类文件写入 heredoc 启动行里没有 hbase shell/hive/mysql 启动词,不会误判。"""
    if not lines:
        return None
    sp = _prompt_split(lines[0][1])
    if not sp:
        return None
    cmd = sp[1]
    if "<<" not in cmd:
        return None
    for name, spec in REPL_SPECS.items():
        if spec["launch_re"].search(cmd):
            return name
    return None


def _extract_heredoc(raw):
    """raw[0] = `[prompt]$ … <<'TAG'`。返回 (launcher, statements, out_lines):
    statements = heredoc body 里的真实命令(去掉 exit 与 TAG);out_lines = TAG 关闭行之后的全部行。"""
    launcher = raw[0]
    m = re.search(r"<<\s*'?([A-Za-z0-9_]+)'?", launcher)
    tag = m.group(1) if m else None
    statements, out_lines, closed = [], [], False
    for ln in raw[1:]:
        if not closed:
            s = ln.strip()
            inner = s[1:].strip() if s.startswith(">") else s
            if tag and inner == tag:
                closed = True
            elif inner and inner != "exit":
                statements.append(inner)
            continue
        out_lines.append(ln)
    return launcher, statements, out_lines


def render_repl_section(lines, repl, state):
    """把一个 REPL heredoc 段折叠成交互式行;state 跨段保存连号计数与「banner 是否已展示」。
    返回 (rows, plains):rows=HTML 行,plains=对应纯文本(供 shoot 估高)。"""
    spec = REPL_SPECS[repl]
    raw = [t for (_, t) in lines]
    launcher, statements, out_lines = _extract_heredoc(raw)
    stmtset = set(s.strip() for s in statements if s.strip())
    n = state["counter"].get(repl, 0)
    first = repl not in state["banner_shown"]

    # banner 切割:hbase 的 banner 截到 `Version …` 行;每段都重复出现,只在首段保留一次。
    be = spec.get("banner_end_re")
    banner, body = [], out_lines
    if be:
        for i, ln in enumerate(out_lines):
            if be.search(ln.strip()):
                banner, body = out_lines[:i + 1], out_lines[i + 1:]
                break
    while body and not body[0].strip():   # 去掉 banner/Version 之后的前导空行,避免双空行
        body.pop(0)

    items = []   # (html, plain)
    if first:
        sp = _prompt_split(launcher)
        prom = sp[0] if sp else DEFAULT_PROMPT
        disp = RE_HEREDOC_TAIL.sub("", clean_cmd(sp[1] if sp else launcher))  # 去掉 <<'EOF' 尾巴
        disp = disp or "hbase shell"
        items.append((_row_prompt(prom, disp), f"{prom} {disp}"))
        for b in banner:
            items.append((_row_out(b), b))
        if banner:
            items.append((_row_out(""), ""))   # banner 后空一行,更像真实交互
        state["banner_shown"].add(repl)

    for ln in body:
        s = ln.strip()
        if s == "exit" or (s == "" and not items):
            continue
        if "执行流程结束" in s or s.startswith(_SKIP_OUT):
            continue
        if s and s in stmtset:
            n += 1
            pr = spec["prompt"].format(n=n)
            items.append((_row_prompt(pr, s), f"{pr} {s}"))
        else:
            items.append((_row_out(ln), ln))
    while items and items[-1][0] == _row_out(""):   # 去尾部空行
        items.pop()
    state["counter"][repl] = n
    rows = [h for h, _ in items]
    plains = [p for _, p in items]
    return rows, plains


def _warn_if_no_output(title, lines):
    """守卫:某段只有命令行、没有任何输出行 → stderr 告警(疑似捕获缺失 / 命令-only 渲染)。"""
    outs = [t for (k, t) in lines if k != "ans"]
    body = [t for t in outs[1:] if t.strip()]   # 第一条通常是命令行,其后应有输出
    if outs and not body:
        eprint(f"  [warn] {title} 仅命令、无输出行(疑似命令-only 渲染或捕获缺失)")


# ───────────────────────── 截图 ─────────────────────────
def find_browser(override=None):
    if override:
        return override
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    raise FileNotFoundError("找不到 Edge/Chrome,请用 --browser 指定 msedge.exe 路径")


def _visual_rows(plains):
    """把每行按 CHARS_PER_ROW 估算换行后占的视觉行数,求和——长输出(describe/scan)会换行,
    据此把窗口给够,避免内容被窗口截断。"""
    return sum(max(1, math.ceil(len(t) / CHARS_PER_ROW)) for t in plains) or 1


def _trim_bottom(png_path):
    """裁掉底部多余的纯背景区域,得到紧贴内容的紧凑图。
    Pillow 不可用则原样保留(底部留一点黑边,不影响阅读)——故 Pillow 只是「锦上添花」、非硬依赖。"""
    try:
        from PIL import Image
    except Exception:
        return
    try:
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        px = im.load()
        last = -1
        for y in range(h - 1, -1, -1):
            if any(px[x, y][0] > 60 for x in range(0, w, 5)):   # 命中文字亮像素(忽略暗色滚动条)
                last = y
                break
        if last >= 0:
            bottom = min(h, last + PAD_V * SCALE + 2)            # 末行下留一点底边距
            if 0 < bottom < h:
                im.crop((0, 0, w, bottom)).save(png_path)
    except Exception:
        pass


def shoot(html_text, png_path, browser, visual_rows):
    width = 1040
    # 窗口高度 = 内容估算 + BAND_MARGIN,**永远高于裁切坏区间上沿(~136px)**,避免整页塌成一行;
    # 渲染后用 _trim_bottom 裁掉底部多余黑边得到紧凑图。
    height = min(PAD_V * 2 + max(visual_rows, 1) * LINE_H + BAND_MARGIN, 6000)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_text)
        html_path = f.name
    png_abs = os.path.abspath(png_path)   # Edge 的 --screenshot 相对其 CWD,必须绝对路径
    os.makedirs(os.path.dirname(png_abs), exist_ok=True)
    uri = "file:///" + html_path.replace("\\", "/")
    udd = tempfile.mkdtemp(prefix="clzj_edge_")
    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check", "--no-sandbox",
           f"--user-data-dir={udd}", f"--force-device-scale-factor={SCALE}",
           f"--window-size={width},{height}", f"--screenshot={png_abs}", uri]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    try:
        os.unlink(html_path)
    except OSError:
        pass
    if not os.path.exists(png_abs):
        raise RuntimeError(f"截图失败 (rc={p.returncode}): {(p.stderr or '')[:400]}")
    _trim_bottom(png_abs)
    return png_abs


def parse_log(log_path):
    """把 run.log 切成 [(title, [(kind,text),...]), ...],按 '### ' 分段。
    新日志里命令以「真实提示符 + 命令」形式落在普通行(out),逐行重放即可;只有
    `>> (应答) ****`(脱敏应答)与极少数旧日志的 `>> cmd`(兜底)仍带 `>> ` 前缀。"""
    sections = []
    cur_title, cur_lines = None, []
    for raw in open(log_path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("### "):
            if cur_title is not None and cur_lines:
                sections.append((cur_title, cur_lines))
            cur_title, cur_lines = line[4:].strip(), []
        elif line.startswith(">> (应答) "):
            cur_lines.append(("ans", line[3:]))
        elif line.startswith(">> "):
            cur_lines.append(("cmd", line[3:]))
        else:
            if line.strip() == "" and not cur_lines:
                continue
            cur_lines.append(("out", line))
    if cur_title is not None and cur_lines:
        sections.append((cur_title, cur_lines))
    return sections


def safe_name(title):
    m = re.match(r"([\d.]+)#(\d+)", title)
    if m:
        return f"step-{m.group(1)}_{m.group(2)}.png"
    return "shot-" + re.sub(r"[^\w]+", "_", title)[:40] + ".png"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-log")
    ap.add_argument("--title")
    ap.add_argument("--cmd")
    ap.add_argument("--output-text")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT,
                    help="兜底提示符(仅用于无 PTY 回显的旧日志 / --cmd 即时渲染),"
                         "如 \"[hadoop@nodeaNNN ~]$\";新日志的提示符来自真实流,无需设置")
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser")
    args = ap.parse_args()
    browser = find_browser(args.browser)

    if args.from_log:
        sections = parse_log(args.from_log)
        state = {"counter": {}, "banner_shown": set()}   # REPL 跨段连号 + banner 只展示一次
        n = 0
        for title, lines in sections:
            png = os.path.join(args.out, safe_name(title))
            repl = detect_repl(lines)
            if repl:
                rows, plains = render_repl_section(lines, repl, state)
                shoot(wrap_page(rows), png, browser, _visual_rows(plains))
            else:
                page, plains = render_html(lines, args.prompt)
                shoot(page, png, browser, _visual_rows(plains))
                _warn_if_no_output(title, lines)
            eprint(f"  渲染 {png}")
            n += 1
        eprint(f"共渲染 {n} 张到 {args.out}(FinalShell 风,提示符来自真实终端流,已清洗噪声 + REPL 美化)")
    else:
        lines = []
        if args.cmd:
            lines.append(("cmd", args.cmd))
        if args.output_text:
            for ln in args.output_text.splitlines():
                lines.append(("out", ln))
        page, plains = render_html(lines, args.prompt)
        shoot(page, args.out, browser, _visual_rows(plains))
        eprint(f"渲染 {args.out}")


if __name__ == "__main__":
    main()
