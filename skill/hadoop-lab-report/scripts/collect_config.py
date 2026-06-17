#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 / 读写 / 脱敏回显 / 自动落盘 / 交互生成 lab_config.json
(只存在于用户项目目录 cwd,绝不进 skill 目录;写盘前一律过 ensure_outside_skill 边界)。

用法:
  python collect_config.py --autofill [--tutorial URL] [--config lab_config.json]
      # 通读教程缺省值(项目目录 ./series_defaults.json),把 nodes/fixed_values 等**已知缺省直接落盘、
      # 不问用户**;已有值一律不覆盖(复用优先);身份段写占位,留给 --interactive 本人填。
  python collect_config.py --popup    [--config lab_config.json]
      # 在新控制台窗口弹出 --interactive(纯 Python 拉起,不走 powershell),等其结束后校验;
      # 仍有缺项则再弹。供主流程一键调用——用户侧直接弹窗,不必自己开终端。
  python collect_config.py --interactive [--config lab_config.json]
      # 交互式收集:身份段逐项本人输入;连接/固定值段凡有缺省的**静默采用**,只对无缺省项提示。
  python collect_config.py --validate [--config lab_config.json]  # 完整性校验(缺项/占位/格式)
  python collect_config.py --show     [--config lab_config.json]  # 脱敏回显(密码显示为 ****)
  python collect_config.py --derive   [--config lab_config.json]  # 派生 student_id_last3 并写回

要点:
- 教程缺省(账号/密码/IP/主机名/端口)由 build_series_kb.py 通读全系列产出的项目目录 ./series_defaults.json
  提供;--autofill 直接落盘、不打扰用户(做实验基本用默认)。
- 用户只需填教程给不了的:身份(姓名/学号/学院/班级/教师/地点/时间)+ 教程确实未提供缺省的连接项。
- 密码输入逐键回显 ****;结束打印脱敏总览;密码只存 lab_config.json 这一个文件。
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import (load_config, collect_secrets, make_masker, MASK, eprint,  # noqa: E402
                     is_placeholder, ensure_outside_skill)

SCHEMA_PATH = os.path.join(HERE, "..", "assets", "lab_config.schema.json")
# 教程缺省值知识库:由 build_series_kb.py 通读全系列产出,只落项目目录(cwd),不进 skill 目录。
KB_NAME = "series_defaults.json"
DEFAULT_TUTORIAL = "https://heisun.xyz/docs/hadoop-e/hadoop-e04/"

# 身份段占位(autofill 写入,待本人交互填写;is_placeholder 会识别为未填)
PLACEHOLDERS = {
    "name": "<你的姓名>", "student_id": "<完整学号>", "college": "<学院>",
    "major_class": "<专业班级>", "instructor": "<指导教师>",
    "location": "<实验地点>", "exam_time": "<实验时间>",
}

SENSITIVE_KEYS = {"hadoop_password", "root_password", "sudo_password",
                  "mariadb_root_password", "hive_user_password"}


def _mask_obj(obj, secrets):
    """递归把对象里的敏感值替换成 ****(用于安全打印)。"""
    masker = make_masker(secrets)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if (k in SENSITIVE_KEYS or k.endswith("_password")) and isinstance(v, str) and v.strip():
                out[k] = MASK
            else:
                out[k] = _mask_obj(v, secrets)
        return out
    if isinstance(obj, list):
        return [_mask_obj(x, secrets) for x in obj]
    if isinstance(obj, str):
        return masker(obj)
    return obj


def validate(cfg: dict) -> list[str]:
    """轻量完整性校验:必填字段 + 占位提醒 + 格式。不含任何身份门禁(已废止)。"""
    errs = []
    ident = cfg.get("identity") or {}
    for k in ("name", "student_id", "college", "major_class", "instructor", "location", "exam_time"):
        v = str(ident.get(k, "")).strip()
        if not v:
            errs.append(f"identity.{k} 缺失")
        elif is_placeholder(v):
            errs.append(f"identity.{k} 仍是占位 {v},请本人填写")
    sid = str(ident.get("student_id", ""))
    if sid and not is_placeholder(sid) and not sid.isdigit():
        errs.append("identity.student_id 应为纯数字学号")
    nodes = cfg.get("nodes") or []
    if not nodes:
        errs.append("nodes 至少要有 1 个节点")
    for i, n in enumerate(nodes):
        for k in ("name", "host", "username", "hadoop_password"):
            if not str(n.get(k, "")).strip():
                errs.append(f"nodes[{i}].{k} 缺失")
    if not str(cfg.get("tutorial_url", "")).strip():
        errs.append("tutorial_url 缺失")
    # 占位提醒(尖括号包裹视为未填)
    for i, n in enumerate(nodes):
        for k in ("hadoop_password", "root_password", "sudo_password"):
            if n.get(k) and is_placeholder(n.get(k)):
                errs.append(f"nodes[{i}].{k} 仍是占位 {n.get(k)},请填真实值")
    for k, v in (cfg.get("fixed_values") or {}).items():
        if is_placeholder(v):
            errs.append(f"fixed_values.{k} 仍是占位 {v},请填真实值")
    return errs


# ───────────────────────── 交互输入(格式化、密码回显 ****) ─────────────────────────
def _input_secret(prompt: str) -> str:
    """读一个敏感值,逐键回显 ****(Windows msvcrt);非 Windows 退回 getpass(无回显);
    stdin 非终端(管道/自动化)时退回 input(),此时由调用方保证环境安全。"""
    if not sys.stdin.isatty():
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return input()
    if os.name == "nt":
        import msvcrt
        sys.stdout.write(prompt)
        sys.stdout.flush()
        buf: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\b":
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
            elif ch in ("\x00", "\xe0"):
                msvcrt.getwch()  # 方向键等扩展键,丢弃
            else:
                buf.append(ch)
                sys.stdout.write("*")
            sys.stdout.flush()
    import getpass
    return getpass.getpass(prompt)


def _real(v):
    """真实值(非空、非占位)→ 原值;否则 None。"""
    return v if (v not in (None, "") and not is_placeholder(v)) else None


def ask(label: str, current=None, default=None, secret: bool = False, required: bool = True,
        validator=None) -> str:
    """一项一行的格式化交互。
    - current:已有真实值(回车=保留当前);
    - default:教程缺省(回车=采用缺省);
    - 两者都没有时,required=True 必填、否则可选。validator(v)->str|None 返回错误信息。"""
    base = _real(current)
    dft = base if base is not None else (default if default not in (None, "") else None)
    while True:
        if dft is not None:
            shown = MASK if secret else str(dft)
            tag = "保留当前" if base is not None else "采用缺省"
            prompt = f"  {label} [回车={tag} {shown}]: "
        else:
            prompt = f"  {label}(必填,本人输入): " if required else f"  {label}(可选,回车跳过): "
        v = (_input_secret(prompt) if secret else input(prompt)).strip()
        if not v:
            if dft is not None:
                return str(dft)
            if not required:
                return ""
            print("    ↑ 该项必填,请输入。")
            continue
        if validator:
            err = validator(v)
            if err:
                print(f"    ↑ {err}")
                continue
        return v


def _maybe_fill_actor(config_path: str, tutorial_url: str):
    """training-v2 教程(P2–P4 围绕「我的演员」):身份齐了就顺手用 find_actor.py 按 姓名+学号 在
    花名册里把演员查出来写进 identity.actor。**best-effort**——查不到(脚本退出 3)不报死,
    留给大模型按花名册人工核对兜底,不阻断收集流程。e0* 教程直接跳过。"""
    if "hadoop-training" not in (tutorial_url or ""):
        return
    script = os.path.join(HERE, "find_actor.py")
    try:
        r = subprocess.run([sys.executable, script, "--config", os.path.abspath(config_path)],
                           cwd=os.getcwd())
        if r.returncode == 0:
            eprint("[actor] 已自动匹配演员并写入 identity.actor。")
        else:
            eprint("[actor] 脚本未能自动匹配演员(花名册缺失/没命中)——交给大模型按花名册人工核对兜底。")
    except Exception as e:
        eprint(f"[actor] 调用 find_actor 失败({type(e).__name__}: {e});交给大模型兜底。")


def _resolve_or_ask(label, existing, default, secret: bool = False, validator=None):
    """连接/固定值:existing 或 default 有真实值 → **静默采用(不提示)**;都没有 → 提示必填。"""
    for v in (existing, default):
        if v not in (None, "") and not is_placeholder(v):
            return v
    return ask(label, secret=secret, validator=validator)


def _digits(v):
    return None if str(v).isdigit() else "应为纯数字。"


def _load_existing(config_path: str) -> dict:
    if os.path.exists(config_path):
        try:
            return json.load(open(config_path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(config_path: str, cfg: dict):
    """落盘前过路径边界:绝不写进 skill 目录,只许落项目目录。"""
    path = ensure_outside_skill(config_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ───────────────────────── 教程缺省值知识库 ─────────────────────────
def load_series_defaults() -> dict:
    """教程缺省值知识库(项目目录 ./series_defaults.json);缺失时提示先重建,但不阻断。"""
    path = os.path.abspath(KB_NAME)
    if not os.path.exists(path):
        eprint(f"[!] 缺少 ./{KB_NAME}(教程缺省值知识库,应由 build_series_kb.py 通读全系列产出到项目目录)。")
        eprint("    建议先运行: python <skill>/scripts/build_series_kb.py  再收集,可少敲很多字。")
        return {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as e:
        eprint(f"[!] {KB_NAME} 读取失败({type(e).__name__}),忽略教程缺省。")
        return {}


def tutorial_defaults(kb: dict, tutorial_url: str = "") -> dict:
    """从知识库派生「教程缺省」:登录约定 + 三节点 IP 约定 + 服务缺省口令 + 通用登录口令。
    命中本次教程的那一篇优先,否则用全系列汇总。"""
    d = {"username": "hadoop", "ssh_port": "22",
         "hosts": ["10.0.0.71", "10.0.0.72", "10.0.0.73"],   # 系列教程三节点约定
         "login_password": "",
         "fixed_values": {}}
    series = kb.get("series", [])
    this = None
    for s in series:
        if tutorial_url and s.get("url", "").rstrip("/") == tutorial_url.rstrip("/"):
            this = s
            break
    scope = [this] if this else series
    # 服务口令:教程 `identified by '...'` 明确给出的(Hive/Sqoop 等元数据库口令)
    creds = {c for s in scope for c in (s.get("default_credentials_identified_by") or [])}
    for c in creds:
        lc = c.lower()
        if "hive" in lc:
            d["fixed_values"].setdefault("hive_user_password", c)
        if "sqoop" in lc:
            d["fixed_values"].setdefault("sqoop_password", c)
    # 通用登录/数据库口令:系列教程惯例 123456;教程提到则采用
    pwmentions = {p for s in scope for p in (s.get("password_mentions") or [])}
    if "123456" in pwmentions or not pwmentions:
        d["login_password"] = "123456"
    if d["login_password"]:
        d["fixed_values"].setdefault("mariadb_root_password", d["login_password"])
    return d


# ───────────────────────── §2 自动落盘(不问用户) ─────────────────────────
def autofill(config_path: str, tutorial_url: str = ""):
    """通读教程缺省值,把 nodes / fixed_values / 连接约定**直接落盘**到 ./lab_config.json,不问用户。
    已有值一律不覆盖(复用优先);身份段缺失则写占位,留给 --interactive 本人填。"""
    kb = load_series_defaults()
    existing = _load_existing(config_path)
    tutorial_url = tutorial_url or existing.get("tutorial_url") or DEFAULT_TUTORIAL
    tds = tutorial_defaults(kb, tutorial_url)

    # 身份段:已有真实值保留,否则写占位(交互阶段本人填)
    ident = dict(existing.get("identity") or {})
    ident.setdefault("course_name", "Hadoop集群部署与开发")
    for k, ph in PLACEHOLDERS.items():
        if not _real(ident.get(k)):
            ident[k] = ph
    if _real(ident.get("student_id")):
        ident["student_id_last3"] = str(ident["student_id"])[-3:]

    # 连接段:已有保留;否则按三节点约定 + 教程缺省补齐
    ex_nodes = existing.get("nodes") or []
    n = len(ex_nodes) or 3
    nodes = []
    for i in range(n):
        ex = ex_nodes[i] if i < len(ex_nodes) else {}
        node = {
            "name": ex.get("name") or ("node" + chr(ord("A") + i)),
            "host": ex.get("host") or (tds["hosts"][i] if i < len(tds["hosts"]) else ""),
            "ssh_port": int(ex.get("ssh_port") or tds["ssh_port"]),
            "username": ex.get("username") or tds["username"],
            "hadoop_password": ex.get("hadoop_password") or tds["login_password"],
        }
        sp = ex.get("sudo_password") or node["hadoop_password"]
        if sp:
            node["sudo_password"] = sp
        if ex.get("root_password"):
            node["root_password"] = ex["root_password"]
        nodes.append(node)

    # 固定值段:教程缺省补齐,已有不覆盖
    fixed = dict(existing.get("fixed_values") or {})
    for k, v in tds["fixed_values"].items():
        if not _real(fixed.get(k)):
            fixed[k] = v

    cfg = {
        "identity": ident,
        "nodes": nodes,
        "fixed_values": fixed,
        "packages": existing.get("packages") or [],
        "tutorial_url": tutorial_url,
    }
    _save(config_path, cfg)
    # training 教程且身份已是真实值(同项目复用)时,顺手把演员也查出来;身份还是占位则此步 no-op。
    _maybe_fill_actor(config_path, tutorial_url)
    eprint(f"[autofill] 教程缺省已落盘 {os.path.abspath(config_path)}(身份段为占位,待本人交互填写)。")
    eprint("脱敏总览:")
    eprint(json.dumps(_mask_obj(cfg, collect_secrets(cfg)), ensure_ascii=False, indent=2))


# ───────────────────────── §3 弹窗交互(用户填教程给不了的) ─────────────────────────
def interactive(config_path: str):
    """交互式收集:身份段逐项本人输入;连接/固定值凡有缺省**静默采用**,只对无缺省项提示。"""
    kb = load_series_defaults()
    existing = _load_existing(config_path)
    tutorial_url = existing.get("tutorial_url") or DEFAULT_TUTORIAL
    tds = tutorial_defaults(kb, tutorial_url)

    print("═══ lab_config.json 交互式收集 ═══")
    print("只需填教程给不了的:身份信息(+ 教程未提供缺省的连接项)。其余已按教程缺省自动填好。\n")

    print("【身份段】报告表头用;请本人逐项输入(已填过的回车保留)。")
    ex_ident = existing.get("identity") or {}
    ident = {"course_name": ex_ident.get("course_name") or "Hadoop集群部署与开发"}
    ident["name"] = ask("姓名", current=ex_ident.get("name"))
    ident["student_id"] = ask("完整学号", current=ex_ident.get("student_id"), validator=_digits)
    for k, label in (("college", "学院"), ("major_class", "专业班级"), ("instructor", "指导教师"),
                     ("location", "实验地点"), ("exam_time", "实验时间(如 20xx年x月x日)")):
        ident[k] = ask(label, current=ex_ident.get(k))
    ident["student_id_last3"] = ident["student_id"][-3:]
    print(f"  → 学号后3位自动派生:{ident['student_id_last3']}\n")

    print("【连接段】凡教程已给缺省的静默采用;仅对教程未提供缺省的项提示。")
    ex_nodes = existing.get("nodes") or []
    n = len(ex_nodes) or 3
    nodes = []
    for i in range(n):
        ex = ex_nodes[i] if i < len(ex_nodes) else {}
        node = {
            "name": _resolve_or_ask(f"节点{i + 1} 名", ex.get("name"), "node" + chr(ord("A") + i)),
            "host": _resolve_or_ask(f"节点{i + 1} IP/主机名", ex.get("host"),
                                    tds["hosts"][i] if i < len(tds["hosts"]) else None),
            "ssh_port": int(_resolve_or_ask(f"节点{i + 1} SSH端口", ex.get("ssh_port"),
                                            tds["ssh_port"], validator=_digits)),
            "username": _resolve_or_ask(f"节点{i + 1} 用户名", ex.get("username"), tds["username"]),
            "hadoop_password": _resolve_or_ask(f"节点{i + 1} hadoop 密码", ex.get("hadoop_password"),
                                               tds["login_password"], secret=True),
        }
        sp = ex.get("sudo_password") or node["hadoop_password"]
        if sp:
            node["sudo_password"] = sp
        if ex.get("root_password"):
            node["root_password"] = ex["root_password"]
        nodes.append(node)

    # 固定值段:教程缺省补齐;仍为空/占位的才提示
    fixed = dict(existing.get("fixed_values") or {})
    for k, v in tds["fixed_values"].items():
        if not _real(fixed.get(k)):
            fixed[k] = v
    for k in list(fixed.keys()):
        if is_placeholder(fixed.get(k)):
            fixed[k] = ask(k, secret=True)
    if not _real(fixed.get("mariadb_root_password")):
        fixed["mariadb_root_password"] = _resolve_or_ask(
            "MariaDB/MySQL root 密码", None, tds["login_password"], secret=True)

    cfg = {
        "identity": ident,
        "nodes": nodes,
        "fixed_values": fixed,
        "packages": existing.get("packages") or [],
        "tutorial_url": tutorial_url,
    }
    _save(config_path, cfg)
    # training-v2 教程:身份已收齐,这里按 姓名+学号 自动匹配演员写入 identity.actor(查不到不报死)。
    _maybe_fill_actor(config_path, tutorial_url)
    print(f"\n[OK] 已写入 {os.path.abspath(config_path)}(密码只存这一个文件,已在 .gitignore)。")
    print("脱敏总览:")
    print(json.dumps(_mask_obj(cfg, collect_secrets(cfg)), ensure_ascii=False, indent=2))
    errs = validate(cfg)
    if errs:
        print("\n[!] 校验未通过:")
        for e in errs:
            print("  - " + e)
        sys.exit(1)
    print("\n配置校验通过,可以开跑。")


def popup_interactive(config_path: str, max_rounds: int = 5) -> int:
    """在新控制台窗口运行 --interactive(纯 Python 拉起,不走 powershell -ExecutionPolicy Bypass),
    等窗口结束后校验;仍有缺项则再弹。主流程一键调用——用户侧直接弹窗,无需自己开终端。"""
    self_py = os.path.abspath(__file__)
    cfg_abs = os.path.abspath(config_path)
    cwd = os.getcwd()
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)  # Windows 新控制台;其它平台退回共享控制台
    for rnd in range(1, max_rounds + 1):
        eprint(f"[popup] 弹出交互配置窗口(第 {rnd}/{max_rounds} 次)…请在新窗口中填写身份信息。")
        try:
            proc = subprocess.Popen([sys.executable, self_py, "--interactive", "--config", cfg_abs],
                                    cwd=cwd, creationflags=creation)
            proc.wait()
        except Exception as e:
            eprint(f"[popup] 弹窗失败({type(e).__name__}: {e})。请手动运行: "
                   f"python {self_py} --interactive --config {cfg_abs}")
            return 1
        existing = _load_existing(config_path)
        errs = validate(existing) if existing else ["未生成 lab_config.json(窗口可能被提前关闭)"]
        if not errs:
            eprint(f"[popup] 配置完整,校验通过:{cfg_abs}")
            return 0
        eprint("[popup] 配置仍有缺项,准备重新弹窗:")
        for e in errs:
            eprint("  - " + e)
    eprint(f"[popup] 连续 {max_rounds} 次仍未补齐,停止自动弹窗。请检查后重试。")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="lab_config.json")
    ap.add_argument("--autofill", action="store_true", help="教程缺省直接落盘、不问用户")
    ap.add_argument("--tutorial", default="", help="本次教程网址(供 --autofill 选对应缺省)")
    ap.add_argument("--popup", action="store_true", help="弹出新控制台窗口跑 --interactive,完后校验")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--derive", action="store_true")
    args = ap.parse_args()

    if args.autofill:
        autofill(args.config, args.tutorial)
        return
    if args.popup:
        sys.exit(popup_interactive(args.config))
    if args.interactive:
        interactive(args.config)
        return

    cfg = load_config(args.config)
    secrets = collect_secrets(cfg)

    if args.show:
        print(json.dumps(_mask_obj(cfg, secrets), ensure_ascii=False, indent=2))
        return

    if args.derive:
        path = ensure_outside_skill(args.config)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"已写回,student_id_last3 = {cfg['identity'].get('student_id_last3')}")
        return

    # 默认即校验(含 --validate)
    errs = validate(cfg)
    if errs:
        print("配置校验未通过:")
        for e in errs:
            print("  - " + e)
        sys.exit(1)
    print(f"配置 OK。学号后3位={cfg['identity'].get('student_id_last3')}, "
          f"节点数={len(cfg.get('nodes', []))}, 教程={cfg.get('tutorial_url')}")


if __name__ == "__main__":
    main()
