#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 heisun.xyz e0* 教程 HTML,解析成结构化 plan.json。

用法:
  python parse_tutorial.py <url> -o runs/e04/plan.json

解析规则见 references/tutorial-structure.md。页面为服务端渲染 HTML,直接 GET 即可。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import eprint  # noqa: E402

BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "pre", "li", "table"}

# 区块标题(【...】)到 plan 字段的映射
SECTION_FIELD = {
    "任务目的": "purpose",
    "任务环境": "environment",
    "任务资源": "resources",
    "任务说明": "description",
    "任务内容": "description",
    "任务步骤": "steps",
    "常见问题": "common_issues",
}

# 交互式命令特征(出现即视为需要喂应答)
INTERACTIVE_HINTS = [
    "mysql_secure_installation", "ssh-keygen", "ssh-copy-id",
    "mysql -u root -p", "mysql -uroot -p", "mysql -p",
]
# 进入交互式 REPL 的命令(单独成行)
INTERACTIVE_REPL = {"hive", "mysql", "hdfs dfs -appendToFile -", "spark-shell"}

# 代码块前的文字若含这些词,说明紧跟的代码块是「预期输出」而非要执行的命令
OUTPUT_MARKERS = ["期望结果", "预期结果", "结果如下", "输出如下", "运行结果", "返回结果", "查询结果"]

# manual(不可在 SSH 自动完成)特征
MANUAL_HINTS = [
    "virtualbox", "克隆", "网卡", "桥接", "host-only", "hostonly", "nat 模式",
    "图形界面", "浏览器", "网页", "界面中", "点击", "右键", "appliance",
    "http://", "https://", ":9870", ":8088", ":50070", ":16010", ":19888",
]

SID_PATTERNS = [
    r"你的学号后\s*3\s*位", r"替换为你学号后\s*3\s*位", r"学号后三位",
    r"学号后\s*3\s*位", r"<\s*学号", r"node[a-zA-Z]\s*\+\s*你?学号",
]

NODE_RE = re.compile(r"\b(node[a-cA-C])\b", re.I)


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def content_root(soup: BeautifulSoup):
    for sel in ("article", "main"):
        el = soup.find(sel)
        if el:
            return el
    el = soup.find("div", class_=re.compile(r"markdown|theme-doc|content", re.I))
    return el or soup.body or soup


def walk_blocks(node):
    """按文档顺序产出 block 级元素,不重复下钻已产出的块。"""
    for child in getattr(node, "children", []):
        name = getattr(child, "name", None)
        if name in BLOCK_TAGS:
            yield child
        elif name is not None:
            yield from walk_blocks(child)


def code_of(pre):
    code = pre.find("code")
    target = code if code else pre
    lang = None
    classes = (code.get("class") if code else pre.get("class")) or []
    for c in classes:
        m = re.match(r"language-([\w+]+)", c)
        if m:
            lang = m.group(1).lower()
    text = target.get_text()
    # 去掉行号/复制按钮可能引入的尾随空白
    return text.rstrip("\n"), lang


def text_of(el):
    return el.get_text(" ", strip=True)


def strip_prompts(code: str):
    """剥掉代码块里的 REPL/shell 提示符前缀,返回 (干净代码, repl)。

    repl ∈ {None,'hive','mysql','hbase','zk','spark'}:命令应送进对应交互会话。
    例:'hive> create table ...' -> ('create table ...','hive')
        '[zk: nodea220:2181(CONNECTED) 0] ls /' -> ('ls /','zk')
        'hbase(main):001:0> list' -> ('list','hbase')
    """
    repl = None
    out = []
    for ln in code.splitlines():
        m = re.match(r"^\s*(hive|mysql|spark-sql|scala)\s*>\s?", ln, re.I)
        if m:
            name = m.group(1).lower()
            repl = {"spark-sql": "spark", "scala": "spark"}.get(name, name)
            ln = ln[m.end():]
        elif re.match(r"^\s*MariaDB\s*\[[^\]]*\]\s*>\s?", ln):
            repl = "mysql"
            ln = re.sub(r"^\s*MariaDB\s*\[[^\]]*\]\s*>\s?", "", ln)
        elif re.match(r"^\s*\[zk:[^\]]*\]\s?", ln):           # [zk: host:2181(CONNECTED) N]
            repl = "zk"
            ln = re.sub(r"^\s*\[zk:[^\]]*\]\s?", "", ln)
        elif re.match(r"^\s*hbase\(main\):\d+:\d+>\s?", ln):  # hbase(main):001:0>
            repl = "hbase"
            ln = re.sub(r"^\s*hbase\(main\):\d+:\d+>\s?", "", ln)
        else:
            ln = re.sub(r"^\s*[\$#]\s+", "", ln)  # shell 提示符 $ / #
        out.append(ln)
    return "\n".join(out).strip("\n"), repl


# ── 裸命令块的 REPL 识别(教程常给不带提示符的裸命令)──
# 某代码块含这些 launch 词 → 为该子任务建立「活跃 REPL 上下文」;之后无提示符的裸命令块,
# 若每行首词都属于该 REPL 的动词白名单,则判为送进该 REPL(用上下文消歧 create/get/delete 等重名)。
REPL_LAUNCH = [
    (re.compile(r"\bzkCli\.sh\b"), "zk"),
    (re.compile(r"\bhbase\s+shell\b"), "hbase"),
    (re.compile(r"\bspark-shell\b|\bspark-sql\b"), "spark"),
]
REPL_VERBS = {
    "zk": {"create", "delete", "deleteall", "set", "get", "ls", "ls2", "stat",
           "getacl", "setacl", "sync", "addauth", "getephemerals",
           "getallchildrennumber", "config", "quit", "history", "removewatches",
           "listquota", "setquota", "delquota", "reconfig"},
    "hbase": {"create", "list", "describe", "disable", "enable", "drop", "put",
              "get", "scan", "delete", "deleteall", "count", "alter", "truncate",
              "status", "version", "whoami", "exists", "is_enabled", "is_disabled"},
}


def detect_launch_repl(code: str):
    """代码块里若含 REPL 启动命令(zkCli.sh / hbase shell / spark-shell),返回该 repl 名。"""
    for rx, name in REPL_LAUNCH:
        if rx.search(code):
            return name
    return None


_SHELL_META = re.compile(r"[|&;><`]|\$\(")   # 含 shell 元字符 → 不是 REPL 命令(zk/hbase 不用管道)


def looks_like_repl_block(code: str, repl: str) -> bool:
    """裸命令块是否「看起来全是该 REPL 的命令」:每非空行首词 ∈ 该 REPL 动词白名单,
    且不含 shell 元字符(管道/重定向/&& 等)。保守,降低把 shell `ls`/`get` 误判成 REPL 的概率。"""
    verbs = REPL_VERBS.get(repl)
    if not verbs:
        return False
    lines = [ln.strip() for ln in code.splitlines() if ln.strip()]
    if not lines:
        return False
    for ln in lines:
        if _SHELL_META.search(ln):
            return False
        if ln.split()[0].lower() not in verbs:
            return False
    return True


def detect_lang(code: str, lang_hint, repl=None):
    if repl == "hive":
        return "hiveql"
    if repl == "mysql":
        return "sql"
    if repl in ("zk", "hbase"):
        return repl          # zk / hbase 命令(送进对应交互会话)
    if repl == "spark":
        return "scala"
    if lang_hint in ("sql", "xml"):
        return lang_hint
    low = code.lower()
    for h in INTERACTIVE_HINTS:
        if h in low:
            return "interactive"
    for line in code.splitlines():
        if line.strip() in INTERACTIVE_REPL:
            return "interactive"
    return "shell"


def is_manual(text: str, code: str) -> bool:
    blob = (text + " " + code).lower()
    return any(h in blob for h in MANUAL_HINTS)


def needs_sid(text: str, code: str) -> bool:
    blob = text + " " + code
    return any(re.search(p, blob) for p in SID_PATTERNS)


def build_steps(blocks):
    """把【任务步骤】的 block 序列拆成有序步骤:文字 + 紧跟的代码块。

    - 代码块前文字含「期望结果」等 → 该代码块是预期输出,放 expect_output,code 留空
      (这类是「要求你自己写 HiveQL」的题目,命令由 Claude 生成)。
    - 否则剥掉提示符前缀作为要执行的命令,记录 repl(hive/mysql/spark)。
    """
    steps = []
    buf = []
    last_node = None
    idx = 0

    # 先扫一遍本子任务的代码块,看有无 REPL 启动命令(zkCli.sh / hbase shell / spark-shell),
    # 有则建立「活跃 REPL 上下文」——之后无提示符的裸命令块按动词白名单归入该 REPL(见 looks_like_repl_block)。
    repl_context = None
    for b in blocks:
        if b.name == "pre":
            c, _ = code_of(b)
            lr = detect_launch_repl(c)
            if lr:
                repl_context = lr
                break

    def flush(pre_code=None, lang_hint=None):
        nonlocal idx, buf, last_node
        text = " ".join(t for t in buf if t).strip()
        clean, repl = ("", None)
        expect = ""
        is_output = pre_code is not None and any(mk in text for mk in OUTPUT_MARKERS)
        if pre_code is not None:
            clean, repl = strip_prompts(pre_code)
            if is_output:
                expect, clean, repl = clean, "", None
            elif repl is None and clean:
                # 裸命令块的 REPL 归属:① 本块就含 launch(如 zkCli.sh)→ 该 repl;
                # ② 否则若子任务已有活跃 REPL 上下文且本块整块像该 REPL 的命令 → 归入。
                launch_repl = detect_launch_repl(clean)
                if launch_repl:
                    repl = launch_repl
                elif repl_context and looks_like_repl_block(clean, repl_context):
                    repl = repl_context
        if not text and not clean and not expect:
            buf = []
            return
        m = NODE_RE.search(text)
        node = m.group(1).lower() if m else last_node
        last_node = node
        lang = detect_lang(clean, lang_hint, repl) if clean else None
        # 步骤类型:auto=有可执行命令; author=需自己写命令(有期望输出无命令,如HiveQL题);
        #          manual=GUI/浏览器/人工; note=纯说明文字
        if is_manual(text, clean):
            kind = "manual"
        elif clean:
            kind = "auto"
        elif expect:
            kind = "author"
        else:
            kind = "note"
        idx += 1
        steps.append({
            "idx": idx,
            "text": text,
            "code": clean,
            "lang": lang,
            "repl": repl,
            "target_node": node,
            "interactive": lang == "interactive",
            "kind": kind,
            "needs_sid": needs_sid(text, clean) or needs_sid(text, expect),
            "expect_output": expect,
        })
        buf = []

    for b in blocks:
        if b.name == "pre":
            code, lang_hint = code_of(b)
            flush(code, lang_hint)
        else:
            buf.append(text_of(b))
    flush()  # 收尾:末尾纯文字步骤(常是 manual 指示)
    return steps


def parse(url: str) -> dict:
    soup = BeautifulSoup(fetch(url), "html.parser")
    root = content_root(soup)
    blocks = list(walk_blocks(root))

    title = ""
    subtasks = []
    cur = None          # 当前子任务
    cur_field = None    # 当前区块字段名
    cur_issue = None    # 当前常见问题条目
    section_buf = []    # 累积当前区块的 block 元素(用于 steps)

    def close_field():
        nonlocal section_buf
        if cur and cur_field == "steps":
            cur["steps"] = build_steps(section_buf)
        section_buf = []

    for b in blocks:
        name = b.name
        txt = text_of(b)
        if name == "h1" and not title:
            title = txt
            continue
        if name == "h2":
            inner = re.match(r"^【(.+?)】", txt)
            if re.match(r"^任务\s*\d+(\.\d+)*", txt):
                close_field()
                cur_field = None
                cur_issue = None
                m = re.match(r"^任务\s*([\d.]+)\s*[-—:：]*\s*(.*)$", txt)
                sid_ = m.group(1) if m else txt
                ttl = (m.group(2) if m else "").strip()
                cur = {"subtask_id": sid_, "title": ttl, "purpose": "",
                       "environment": "", "resources": "", "description": "",
                       "steps": [], "common_issues": []}
                subtasks.append(cur)
            elif inner and cur is not None:
                close_field()
                key = inner.group(1).strip()
                cur_field = SECTION_FIELD.get(key)
                cur_issue = None
            else:
                close_field()
                cur_field = None
            continue
        if cur is None:
            continue
        if cur_field == "common_issues":
            if name == "h3":
                cur_issue = {"symptom": re.sub(r"^\d+[\.、]\s*", "", txt), "fix": ""}
                cur["common_issues"].append(cur_issue)
            elif cur_issue is not None:
                if name == "pre":
                    code, _ = code_of(b)
                    cur_issue["fix"] += ("\n" + code)
                else:
                    cur_issue["fix"] = (cur_issue["fix"] + " " + txt).strip()
            continue
        if cur_field == "steps":
            section_buf.append(b)
            continue
        if cur_field in ("purpose", "environment", "resources", "description"):
            if name == "pre":
                code, _ = code_of(b)
                cur[cur_field] = (cur[cur_field] + "\n" + code).strip()
            else:
                cur[cur_field] = (cur[cur_field] + " " + txt).strip()
    close_field()

    return {"url": url, "title": title, "subtasks": subtasks}


def summarize(plan: dict):
    nsub = len(plan["subtasks"])
    nstep = sum(len(s["steps"]) for s in plan["subtasks"])
    allst = [st for s in plan["subtasks"] for st in s["steps"]]
    from collections import Counter
    kinds = Counter(st["kind"] for st in allst)
    nsid = sum(1 for st in allst if st["needs_sid"])
    nissue = sum(len(s["common_issues"]) for s in plan["subtasks"])
    eprint(f"标题: {plan['title']}")
    eprint(f"子任务: {nsub}  步骤: {nstep}  含学号占位: {nsid}  常见问题: {nissue}")
    eprint(f"步骤类型: auto={kinds['auto']} author(需自己写)={kinds['author']} "
           f"manual(GUI/人工)={kinds['manual']} note={kinds['note']}")
    for s in plan["subtasks"]:
        eprint(f"  - 任务{s['subtask_id']} {s['title']}  (步骤 {len(s['steps'])}, 问题 {len(s['common_issues'])})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    plan = parse(args.url)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    summarize(plan)
    eprint(f"已写入 {args.out}")


if __name__ == "__main__":
    main()
