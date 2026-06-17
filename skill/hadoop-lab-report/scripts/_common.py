#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hadoop-lab-report 各脚本共享工具:配置加载、密码打码、路径边界、学号派生。

设计原则:
- 密码只来自 lab_config.json;任何写盘/打屏前都过 mask()。
- 含真实信息的配置/缺省值文件(lab_config.json、series_defaults.json 等)只能落在
  用户项目目录(cwd):写盘前一律过 ensure_outside_skill(),拒绝写进 skill 安装目录。
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys

# skill 安装目录根 = 本文件(scripts/_common.py)所在目录的上一级。
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK,会把中文/UTF-8 输出弄成乱码;统一强制 UTF-8(stdin 一并,
# 供管道/自动化喂中文输入时编码一致)。
for _s in (sys.stdout, sys.stderr, sys.stdin):
    try:
        _s.reconfigure(encoding="utf-8")  # py3.7+
    except Exception:
        pass

MASK = "****"


def eprint(*a, **k):
    """打到 stderr,避免污染需要捕获的 stdout。"""
    print(*a, file=sys.stderr, **k)
    sys.stderr.flush()


def is_placeholder(v) -> bool:
    s = str(v or "").strip()
    return (not s) or (s.startswith("<") and s.endswith(">"))


def ensure_outside_skill(path: str) -> str:
    """路径边界(硬规矩):把 path 解析为绝对路径,若位于 skill 安装目录(SKILL_ROOT)之内
    → 报错并非零退出,拒绝落盘。含真实信息的配置/缺省值文件只能生成/存在于用户项目目录(cwd),
    绝不能出现在 skill 目录内。所有「写」配置/缺省值的脚本入口在写文件前必须过这道边界。"""
    ap = os.path.abspath(path)
    root = os.path.abspath(SKILL_ROOT)
    try:
        inside = os.path.commonpath([ap, root]) == root
    except ValueError:  # 不同盘符 → 一定不在 skill 内
        inside = False
    if inside:
        eprint(f"[边界] 拒绝把配置/缺省值写入 skill 目录:{ap}")
        eprint(f"        含真实信息的文件只能落在项目目录(cwd),不得落在 {root} 之内。")
        raise SystemExit(2)
    return ap


def popup_safe(msg: str):
    """best-effort 弹一个 Windows 提醒(popup.py 已封装 detached/UTF-8);失败不影响主流程。"""
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "popup.py")
        subprocess.Popen([sys.executable, script, msg])
    except Exception:
        pass


def load_config(path: str = "lab_config.json") -> dict:
    """加载 lab_config.json(只读项目目录的 ./lab_config.json),并自动派生学号后3位。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到配置文件: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 自动派生学号后3位
    ident = cfg.get("identity", {})
    sid = str(ident.get("student_id", "")).strip()
    if sid:
        ident["student_id_last3"] = sid[-3:]
    return cfg


def collect_secrets(cfg: dict) -> list[str]:
    """收集所有 [敏感] 值(各节点密码 + fixed_values 的全部值),用于打码。

    返回按长度降序,先替换长的,避免短串先命中造成残留。
    """
    secrets: set[str] = set()
    for node in cfg.get("nodes", []):
        for k in ("hadoop_password", "root_password", "sudo_password"):
            v = node.get(k)
            if v:
                secrets.add(str(v))
    for v in (cfg.get("fixed_values") or {}).values():
        if v:
            secrets.add(str(v))
    # 去掉空串/占位空白
    secrets = {s for s in secrets if s and s.strip()}
    return sorted(secrets, key=len, reverse=True)


def make_masker(secrets: list[str]):
    """返回一个 mask(text)->text 函数,把任何敏感串替换成 ****。"""
    def mask(text):
        if text is None:
            return text
        if not isinstance(text, str):
            text = str(text)
        for s in secrets:
            if s and s in text:
                text = text.replace(s, MASK)
        return text
    return mask


def run_id_from_url(url: str) -> str:
    """教程网址 → 运行目录 id。
    - .../hadoop-e/hadoop-e04/                  → e04
    - .../hadoop-training-v2/hadoop-training04/ → t04
      (training 系列单独命名空间 tNN,不与 e0* 系列撞 runs/ 目录)
    """
    u = url or ""
    m = re.search(r"hadoop-training(\d{2})", u)
    if m:
        return "t" + m.group(1)
    m = re.search(r"hadoop-(e\d{2})", u)
    if m:
        return m.group(1)
    m = re.search(r"(e\d{2})", u)
    return m.group(1) if m else "eXX"


def run_dir(cfg: dict, base: str = ".") -> str:
    eNN = run_id_from_url(cfg.get("tutorial_url", ""))
    d = os.path.join(base, "runs", eNN)
    os.makedirs(os.path.join(d, "shots"), exist_ok=True)
    os.makedirs(os.path.join(d, "manual"), exist_ok=True)
    return d


# 学号后3位占位的各种写法
_SID_PH = r"(?:你的?学号后\s*3\s*位|替换为你学号后\s*3\s*位|学号后三位|学号后\s*3\s*位|<\s*学号后\s*3\s*位\s*>)"


def apply_sid(text: str, sid3: str) -> str:
    """学号占位替换:把教程/生成内容里的占位统一换成学号后3位。

    - `<前缀>+占位` → `<前缀><sid3>`(去掉加号),如 hadoop+你学号后3位→hadoopNNN、nodea+学号后3位→nodeaNNN。
    - 裸占位 → sid3,如 emp你的学号后3位→empNNN、dept你学号后3位→deptNNN(NNN=学号后3位)。
    只替换明确的占位形式,不误伤已具体的示例值。规则见 references/report-template.md。
    """
    if not text or not sid3:
        return text
    # 先处理「前缀+占位」,把加号一并吃掉(用 \g<1> 防止 \1+数字 被当八进制转义)
    text = re.sub(r"([A-Za-z][\w-]*)\s*\+\s*" + _SID_PH, r"\g<1>" + sid3, text)
    # 再处理裸占位
    text = re.sub(_SID_PH, sid3, text)
    text = re.sub(r"<\s*学号\s*>", sid3, text)
    return text


# 演员占位的各种写法(training-v2 系列:每个任务都围绕「我的演员」)。长的排前面,
# 避免 `我的演员` 先把 `修改为我的演员的姓名` 吃掉。
_ACTOR_PH = (
    "修改为我的演员的姓名",   # 教程/README Java 样例里的占位
    "我的演员姓名",           # README 样例 String actor="我的演员姓名"
    "<我的演员>",             # 本 skill 内置参考模板里的占位
    "你的演员",
    "我的演员",
)


def apply_actor(text: str, actor: str) -> str:
    """演员占位替换:把生成/参考内容里的演员占位统一换成本人分配到的演员(actor)。

    覆盖两类:
    1. **Java 常量** `ACTOR="..."`(参考工程里写死的 王祖贤/王菲,或抽象模板里的 `<我的演员>`)
       → 把双引号里的值整体设为真实演员,无论原值是真名还是占位。
    2. **文案/样例占位**:修改为我的演员的姓名 / 我的演员姓名 / <我的演员> / 你的演员 / 我的演员。

    只在**传入的这段内容**上替换——由调用方对「确实要个性化的代码 / SQL / 报告段」显式调用,
    不全局乱改教程标题。actor 为空则原样返回(没查到演员时不乱替)。
    """
    if not text or not actor:
        return text
    # 1) Java 常量 ACTOR="..." 的值(\g<1>/\g<2> 防止与后续数字粘连)
    text = re.sub(r'(ACTOR\s*=\s*")[^"]*(")', r"\g<1>" + actor + r"\g<2>", text)
    # 2) 文案/样例占位(长的先替)
    for ph in _ACTOR_PH:
        text = text.replace(ph, actor)
    return text
