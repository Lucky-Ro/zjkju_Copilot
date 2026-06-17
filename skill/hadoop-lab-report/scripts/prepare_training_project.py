#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把内置的 training-v2 参考工程模板(assets/training-code/expN)**物化 + 参数化**到 runs/tNN/project/。

为什么要这个脚本:P2–P4 的参考代码已抽象内置到 skill,但每人要按自己的「学号后三位 + 演员」定制——
包名 `hadoop9999`(9999=学号后三位占位)要改成 `hadoop<sid3>`、Java 里写死的 `"我的演员"` 要换成本人
分配到的演员。这一步确定性强,交给脚本最稳;脚本报错再按 references/training-v2-reference.md 手工兜底。

做的事:
  1. 选 Part(P2/P3/P4 或 t02/t03/t04 或 training02/03/04)→ 对应内置模板 exp1/exp2/exp3。
  2. 复制模板到 runs/tNN/project/(已存在则先清空,保证可重复)。
  3. 全工程文本替换 `hadoop9999` → `hadoop<sid3>`(.java/.xml),并重命名包目录 hadoop9999 → hadoop<sid3>。
  4. .java 里 `"我的演员"` / `ACTOR="我的演员"` → 真实演员(apply_actor)。
  5. 把资料库的 Film.json 拷进 src/main/resources/(P3/P4 纯 Java 从 classpath 读它)。

用法:
  python prepare_training_project.py P3                     # sid3/actor 自动取 lab_config.json
  python prepare_training_project.py training03 --sid3 340 --actor 林雪
  python prepare_training_project.py P2 --film-json D:/data/Film.json --out-dir .

退出码:0=成功;2=写盘越界;3=参数/模板/Film.json 缺失(打印原因)。
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import eprint, ensure_outside_skill, apply_actor, is_placeholder  # noqa: E402

ASSETS_TRAINING = os.path.join(os.path.dirname(HERE), "assets", "training-code")

# Part 别名 → (模板目录, run 目录 id)
PART_MAP = {
    "p2": ("exp1", "t02"), "t02": ("exp1", "t02"), "training02": ("exp1", "t02"), "2": ("exp1", "t02"),
    "p3": ("exp2", "t03"), "t03": ("exp2", "t03"), "training03": ("exp2", "t03"), "3": ("exp2", "t03"),
    "p4": ("exp3", "t04"), "t04": ("exp3", "t04"), "training04": ("exp3", "t04"), "4": ("exp3", "t04"),
}

FILM_GLOBS = [
    "./hadoop集群部署实战/Film.json",
    "./hadoop集群部署实战/**/Film.json",
    os.path.expanduser("~/hadoop集群部署实战/Film.json"),
    os.path.expanduser("~/hadoop集群部署实战/**/Film.json"),
]

TEXT_EXTS = {".java", ".xml"}


def _read_lab() -> dict:
    """读 lab_config.json 的 identity(取 sid3/actor 缺省);缺失/坏文件返回空。"""
    path = "lab_config.json"
    if not os.path.exists(path):
        return {}
    try:
        import json
        cfg = json.load(open(path, encoding="utf-8"))
        ident = cfg.get("identity") or {}
        sid = str(ident.get("student_id") or "").strip()
        if sid and not ident.get("student_id_last3"):
            ident["student_id_last3"] = sid[-3:]
        return ident
    except Exception:
        return {}


def find_film_json(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for pat in FILM_GLOBS:
        hits = sorted(glob.glob(pat, recursive=True), key=len)   # 短路径(顶层)优先
        if hits:
            return hits[0]
    return None


def _substitute_tree(root: str, sid3: str, actor: str):
    """全树文本替换:hadoop9999→hadoop<sid3>(.java/.xml);.java 再 apply_actor(我的演员→actor)。"""
    pkg_old, pkg_new = "hadoop9999", f"hadoop{sid3}"
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in TEXT_EXTS:
                continue
            p = os.path.join(dirpath, fn)
            with open(p, encoding="utf-8") as f:
                text = f.read()
            new = text.replace(pkg_old, pkg_new)
            if ext == ".java" and actor:
                new = apply_actor(new, actor)
            if new != text:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)


def _rename_pkg_dirs(root: str, sid3: str):
    """把任意名为 hadoop9999 的目录重命名为 hadoop<sid3>(自底向上,避免路径失效)。"""
    new_name = f"hadoop{sid3}"
    for dirpath, dirs, _files in os.walk(root, topdown=False):
        for d in dirs:
            if d == "hadoop9999":
                os.rename(os.path.join(dirpath, d), os.path.join(dirpath, new_name))


def main() -> int:
    ap = argparse.ArgumentParser(description="物化+参数化 training-v2 参考工程到 runs/tNN/project/")
    ap.add_argument("part", help="P2/P3/P4 或 t02/t03/t04 或 training02/03/04")
    ap.add_argument("--sid3", default="", help="学号后三位(默认取 lab_config.student_id_last3)")
    ap.add_argument("--actor", default="", help="本人演员(默认取 lab_config.identity.actor)")
    ap.add_argument("--film-json", default="", help="Film.json 路径(默认探测资料库)")
    ap.add_argument("--out-dir", default=".", help="项目根(默认当前目录;工程落在 <out-dir>/runs/tNN/project)")
    ap.add_argument("--no-film", action="store_true", help="不拷 Film.json(只参数化源码)")
    args = ap.parse_args()

    key = args.part.strip().lower()
    if key not in PART_MAP:
        eprint(f"[prepare] 不认识的 Part:{args.part}(用 P2/P3/P4 或 t02/t03/t04 或 training02/03/04)")
        return 3
    exp_dir, run_id = PART_MAP[key]

    ident = _read_lab()
    sid3 = args.sid3 or str(ident.get("student_id_last3") or "")
    actor = args.actor or str(ident.get("actor") or "")
    if is_placeholder(sid3):
        sid3 = ""
    if is_placeholder(actor):
        actor = ""
    if not sid3 or not sid3.isdigit() or len(sid3) != 3:
        eprint(f"[prepare] 学号后三位无效:'{sid3}'。请传 --sid3 NNN 或先填好 lab_config 的学号。")
        return 3
    if not actor:
        eprint("[prepare] 没有演员(--actor 为空且 lab_config.identity.actor 未填)。"
               "请先 python scripts/find_actor.py 或传 --actor;否则源码里 \"我的演员\" 不会被替换。")
        # 允许继续(只改包名),但提醒——演员留空时不替换,免得生成错代码
    src = os.path.join(ASSETS_TRAINING, exp_dir)
    if not os.path.isdir(src):
        eprint(f"[prepare] 找不到内置模板 {src}(skill 安装是否完整?)")
        return 3

    dest = ensure_outside_skill(os.path.join(args.out_dir, "runs", run_id, "project"))
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    _substitute_tree(dest, sid3, actor)
    _rename_pkg_dirs(dest, sid3)

    # Film.json → src/main/resources/
    if not args.no_film:
        film = find_film_json(args.film_json or None)
        if not film:
            eprint("[prepare] 没找到 Film.json(探测:" + " , ".join(FILM_GLOBS) + ")。"
                   "可加 --film-json PATH 或 --no-film。工程已参数化,但 P3/P4 跑前需自备 Film.json。")
        else:
            res_dir = os.path.join(dest, "src", "main", "resources")
            os.makedirs(res_dir, exist_ok=True)
            shutil.copy2(film, os.path.join(res_dir, "Film.json"))
            eprint(f"[prepare] 已拷 Film.json → {os.path.join(res_dir, 'Film.json')}(来源:{film})")

    eprint(f"[prepare] 工程就绪:{dest}")
    eprint(f"          包名 hadoop9999 → hadoop{sid3};演员占位 \"我的演员\" → "
           f"{actor or '(未替换,演员留空)'};Part={args.part}")
    eprint(f"          下一步:cd {dest} && mvn -q -DskipTests package")
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
