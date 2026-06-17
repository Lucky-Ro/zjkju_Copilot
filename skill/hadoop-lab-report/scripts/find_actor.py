#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按使用者「姓名 + 学号」在花名册里**确定性地**查到分配给本人的演员,写回 lab_config.json。

为什么要这个脚本:training-v2(P2–P4)的每个任务都围绕「我的演员」展开——演员来自课程发的
`学生演员分配表-*.xlsx`(列:学号 / 姓名 / 对应演员)。这一步必须**准**,所以优先用脚本按学号精确
匹配;脚本搞不定(花名册缺失/未装 openpyxl/0 命中或多命中)时**非零退出**,把活儿退让给大模型去
人工核对(SKILL.md 已写明兜底口径),绝不瞎编。

匹配策略(保证「准」):
  1. **学号精确匹配为主键**(strip 后字符串比较);命中后用姓名**交叉校验**,不一致仅告警、仍以学号为准。
  2. 学号查不到 → 退而用**姓名精确匹配**(唯一命中才算)。
  3. 0 命中 / 多命中 → 退出码 3,打印清晰原因,交给大模型兜底。

用法:
  python find_actor.py                         # 读 ./lab_config.json 的 identity,写回 identity.actor
  python find_actor.py --name 周恩祈 --student-id 2024101240340 --print
  python find_actor.py --roster "D:/.../学生演员分配表.xlsx" --no-write --print
  python find_actor.py --print                 # 仅打印,不写盘(--no-write 亦可)

退出码:0=已匹配(并按需写回);2=写盘越界被拒;3=没找到/缺花名册/缺依赖(→ 大模型兜底)。
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import eprint, ensure_outside_skill, is_placeholder  # noqa: E402

# 花名册默认探测位置(资料库 ~/hadoop集群部署实战 或工作目录下的同名资料库)。
# 文件名以「学生演员分配」开头即可(教程称 学生演员分配.xlsx,实物常是 学生演员分配表-XX班.xlsx)。
ROSTER_GLOBS = [
    "./hadoop集群部署实战/**/学生演员分配*.xlsx",
    "./hadoop集群部署实战/学生演员分配*.xlsx",
    "./学生演员分配*.xlsx",
    os.path.expanduser("~/hadoop集群部署实战/**/学生演员分配*.xlsx"),
    os.path.expanduser("~/hadoop集群部署实战/学生演员分配*.xlsx"),
]


def find_roster(explicit: str | None) -> str | None:
    """定位花名册 xlsx:显式 --roster 优先;否则按 ROSTER_GLOBS 探测,取第一个命中。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for pat in ROSTER_GLOBS:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0]
    return None


def _norm(v) -> str:
    """统一成可比较的字符串:None→'';数字(openpyxl 可能把学号读成 int/float)→去小数;去首尾空白。"""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def load_roster(path: str, sheet: str | None = None) -> list[dict]:
    """读花名册 → [{'sid','name','actor'}, ...]。按表头文本(学号/姓名/演员)定位列,跳过标题行。
    openpyxl 缺失 → 抛 ImportError(调用方据此退让大模型)。"""
    try:
        import openpyxl
    except ImportError as e:
        raise ImportError("未安装 openpyxl,无法读花名册 xlsx(pip install openpyxl)") from e

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]

    rows = [[_norm(c) for c in r] for r in ws.iter_values()] if hasattr(ws, "iter_values") \
        else [[_norm(c) for c in r] for r in ws.iter_rows(values_only=True)]

    # 找到含「学号 / 姓名 / 演员」三种表头的那一行
    hdr_idx = sid_col = name_col = actor_col = None
    for i, row in enumerate(rows):
        sc = nc = ac = None
        for j, cell in enumerate(row):
            if "学号" in cell:
                sc = j
            elif "姓名" in cell:
                nc = j
            elif "演员" in cell:   # 「对应演员」/「演员」
                ac = j
        if sc is not None and nc is not None and ac is not None:
            hdr_idx, sid_col, name_col, actor_col = i, sc, nc, ac
            break
    if hdr_idx is None:
        raise ValueError(f"花名册 {path} 里找不到同时含「学号/姓名/演员」表头的行,无法解析")

    out = []
    for row in rows[hdr_idx + 1:]:
        sid = row[sid_col] if sid_col < len(row) else ""
        name = row[name_col] if name_col < len(row) else ""
        actor = row[actor_col] if actor_col < len(row) else ""
        if sid or name:
            out.append({"sid": sid, "name": name, "actor": actor})
    return out


def match_actor(roster: list[dict], name: str, sid: str) -> tuple[str, str]:
    """在花名册里定位演员。返回 (actor, how)。匹配不到 → 抛 LookupError(交给大模型兜底)。"""
    name, sid = _norm(name), _norm(sid)
    # 1) 学号精确匹配(主键)
    if sid:
        hits = [r for r in roster if r["sid"] and r["sid"] == sid]
        if len(hits) == 1:
            r = hits[0]
            if name and r["name"] and r["name"] != name:
                eprint(f"[!] 学号 {sid} 命中,但花名册姓名「{r['name']}」与传入「{name}」不一致——以学号为准。")
            if not r["actor"]:
                raise LookupError(f"学号 {sid} 在花名册命中,但「对应演员」列为空。")
            return r["actor"], f"按学号 {sid} 精确匹配"
        if len(hits) > 1:
            raise LookupError(f"学号 {sid} 在花名册命中 {len(hits)} 行(应唯一),请人工核对。")
    # 2) 退而用姓名精确匹配(唯一命中才算)
    if name:
        hits = [r for r in roster if r["name"] and r["name"] == name]
        if len(hits) == 1 and hits[0]["actor"]:
            return hits[0]["actor"], f"按姓名「{name}」精确匹配(学号未命中)"
        if len(hits) > 1:
            raise LookupError(f"姓名「{name}」在花名册有 {len(hits)} 个同名,无法唯一确定,请用学号或人工核对。")
    raise LookupError(f"花名册里找不到 姓名「{name}」/ 学号「{sid}」对应的演员。")


def _read_identity(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    try:
        return (json.load(open(config_path, encoding="utf-8")).get("identity") or {})
    except Exception:
        return {}


def _write_actor(config_path: str, actor: str) -> None:
    """把 actor 写回 lab_config.json 的 identity.actor(保留其余内容);写前过路径边界。"""
    path = ensure_outside_skill(config_path)
    cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    cfg.setdefault("identity", {})["actor"] = actor
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description="按姓名+学号查分配到的演员,写回 lab_config.identity.actor")
    ap.add_argument("--config", default="lab_config.json", help="lab_config.json 路径(读身份/写 actor)")
    ap.add_argument("--roster", default="", help="花名册 xlsx 路径(默认探测资料库 学生演员分配*.xlsx)")
    ap.add_argument("--name", default="", help="使用者姓名(默认取 lab_config.identity.name)")
    ap.add_argument("--student-id", default="", help="使用者完整学号(默认取 lab_config.identity.student_id)")
    ap.add_argument("--sheet", default="", help="花名册工作表名(默认第一个)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="把匹配到的演员打印到 stdout")
    ap.add_argument("--no-write", action="store_true", help="只匹配/打印,不写回 lab_config.json")
    args = ap.parse_args()

    ident = _read_identity(args.config)
    name = args.name or _norm(ident.get("name"))
    sid = args.student_id or _norm(ident.get("student_id"))
    if is_placeholder(name):
        name = ""
    if is_placeholder(sid):
        sid = ""
    if not name and not sid:
        eprint("[find_actor] 既没传 --name/--student-id,lab_config 身份也是空/占位 —— 无法匹配。"
               "请先收集身份(collect_config.py --popup)或显式传参。")
        return 3

    roster_path = find_roster(args.roster or None)
    if not roster_path:
        eprint("[find_actor] 没找到花名册(学生演员分配*.xlsx)。探测过:"
               + " , ".join(ROSTER_GLOBS))
        eprint("           → 退让大模型:请人工打开花名册,按姓名+学号定位演员,再写入 lab_config.identity.actor。")
        return 3

    try:
        roster = load_roster(roster_path, args.sheet or None)
        actor, how = match_actor(roster, name, sid)
    except (ImportError, ValueError, LookupError) as e:
        eprint(f"[find_actor] 脚本未能确定演员:{e}")
        eprint(f"           花名册:{roster_path}")
        eprint("           → 退让大模型:请人工核对花名册定位演员,再写入 lab_config.identity.actor,绝不瞎编。")
        return 3

    eprint(f"[find_actor] {how} → 演员:{actor}  (花名册:{roster_path})")
    if not args.no_write:
        try:
            _write_actor(args.config, actor)
            eprint(f"[find_actor] 已写回 {os.path.abspath(args.config)} 的 identity.actor = {actor}")
        except SystemExit:
            raise
        except Exception as e:
            eprint(f"[find_actor] 写回 lab_config 失败({type(e).__name__}: {e}),但演员已查到:{actor}")
    if args.do_print:
        print(actor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
