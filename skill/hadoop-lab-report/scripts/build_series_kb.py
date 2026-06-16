#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 heisun.xyz e0* 全系列教程,提取「缺省知识」并落盘成知识库。

接任务前先把所有教程读一遍,把缺省密码 / IP / 主机名 / 端口 / 安装包 / 交互工具等全部抽取出来,
供本系列(P1–P7)复用。**这些缺省含教程账号/密码/IP,属配置类落盘物,只生成到用户项目目录(cwd),
绝不写进 skill 目录**(过 ensure_outside_skill 边界)。本脚本在当前工作目录一次性生成:
  - ./series_defaults.json   机器可读(collect_config.py --autofill / --interactive 读它)
  - ./series-defaults.md     人读 + 给 skill 当参考

用法:在项目目录运行 python <skill>/scripts/build_series_kb.py [--max 7]
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
import parse_tutorial as P  # 复用 fetch/解析  # noqa: E402
from _common import eprint, ensure_outside_skill  # noqa: E402

# 两套系列的 URL 模板;build 时按 --series / --tutorial 自动选。
E_BASE = "https://heisun.xyz/docs/hadoop-e/hadoop-e{:02d}/"
TRAINING_BASE = "https://heisun.xyz/docs/hadoop-training-v2/hadoop-training{:02d}/"
BASE = E_BASE   # 默认 e0* 系列(向后兼容:无参运行仍建 e 系列知识库)


def pick_base(series: str, tutorial_url: str = ""):
    """选系列 URL 模板:--series 显式优先;否则按 --tutorial 自动判断;默认 e0*。"""
    s = (series or "auto").lower()
    if s == "training" or (s == "auto" and "hadoop-training" in (tutorial_url or "")):
        return TRAINING_BASE, "hadoop-training-v2"
    return E_BASE, "hadoop-e0*"

RE_IDENT = re.compile(r"identified by\s+'([^']+)'", re.I)
RE_PWLINE = re.compile(r"(密码|password|passwd)\s*[:=是为]?\s*([A-Za-z0-9!@#._-]{3,})", re.I)
RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_PORT = re.compile(r":(\d{4,5})\b")
# 收紧:只认 nodea/nodeb/nodec(可带数字后缀)、hadoop+数字、master、slaveN,避免抓到散文/类名
RE_HOST = re.compile(r"\b(node[a-c]\d{0,3}|hadoop\d{1,3}|master|slave\d?)\b", re.I)
RE_PKG = re.compile(r"[\w.+-]+\.(?:tar\.gz|tgz|jar|zip|csv|rpm|sql|ova)\b", re.I)
INTERACTIVE = ["mysql_secure_installation", "ssh-keygen", "ssh-copy-id", "schematool",
               "mysql -u", "hive", "hdfs namenode -format", "start-dfs", "start-yarn"]


def all_code(plan):
    out = []
    for s in plan["subtasks"]:
        for f in ("purpose", "environment", "resources", "description"):
            if s.get(f):
                out.append(s[f])
        for st in s["steps"]:
            if st.get("code"):
                out.append(st["code"])
            if st.get("expect_output"):
                out.append(st["expect_output"])
            if st.get("text"):
                out.append(st["text"])
        for it in s.get("common_issues", []):
            out.append(it.get("symptom", "") + " " + it.get("fix", ""))
    return "\n".join(out)


def extract(url, plan):
    blob = all_code(plan)
    creds = sorted(set(RE_IDENT.findall(blob)))
    pwhits = sorted({m[1] for m in RE_PWLINE.findall(blob) if not m[1].isdigit() or len(m[1]) >= 4})
    ips = sorted(set(RE_IP.findall(blob)))
    ports = sorted(set(RE_PORT.findall(blob)))
    hosts = sorted({h.lower() for h in RE_HOST.findall(blob)})
    pkgs = sorted(set(RE_PKG.findall(blob)))
    inter = sorted({k for k in INTERACTIVE if k in blob})
    return {
        "url": url,
        "title": plan["title"],
        "subtasks": [f"{s['subtask_id']} {s['title']}" for s in plan["subtasks"]],
        "default_credentials_identified_by": creds,
        "password_mentions": pwhits[:20],
        "ip_addresses": ips,
        "web_ports": ports,
        "hostnames": hosts,
        "packages": pkgs,
        "interactive_tools": inter,
        "common_issues": [it["symptom"] for s in plan["subtasks"] for it in s.get("common_issues", [])],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=7)
    ap.add_argument("--series", default="auto", choices=["auto", "e", "training"],
                    help="建哪套系列的知识库;auto=按 --tutorial 自动判断,默认 e0*")
    ap.add_argument("--tutorial", default="", help="本次教程网址(供 --series auto 判断系列)")
    ap.add_argument("--out-dir", default=".", help="知识库落盘目录,默认当前项目目录(不得在 skill 内)")
    args = ap.parse_args()
    base, series_label = pick_base(args.series, args.tutorial)
    # 路径边界:知识库含教程账号/密码/IP,只许落项目目录,绝不进 skill 目录
    out_json = ensure_outside_skill(os.path.join(args.out_dir, "series_defaults.json"))
    out_md = ensure_outside_skill(os.path.join(args.out_dir, "series-defaults.md"))
    eprint(f"建知识库:{series_label} 系列(模板 {base})")

    series = []
    for nn in range(1, args.max + 1):
        url = base.format(nn)
        try:
            plan = P.parse(url)
            if not plan.get("title"):
                eprint(f"e{nn:02d}: 无标题,跳过")
                continue
            info = extract(url, plan)
            series.append(info)
            eprint(f"e{nn:02d}: {info['title']}  凭据={info['default_credentials_identified_by']} "
                   f"包={len(info['packages'])} 端口={info['web_ports']}")
        except requests.HTTPError as e:
            eprint(f"e{nn:02d}: HTTP {e}(可能不存在,跳过)")
        except Exception as e:
            eprint(f"e{nn:02d}: 解析失败 {type(e).__name__}: {e}")

    json.dump({"series": series}, open(out_json, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 汇总人读 md
    md = [f"# heisun.xyz {series_label} 系列缺省知识库(自动抽取)",
          "",
          "> 由 `scripts/build_series_kb.py` 从各教程页自动抽取,落在**你的项目目录**(不进 skill 目录)。",
          "> **接任务时先读本文件**,把本次实验涉及的缺省密码 / IP / 主机名 / 端口 / 安装包对照到 `lab_config.json`",
          "> (`collect_config.py --autofill` 会自动落盘)。抽取是启发式的,执行时仍以教程原文为准。",
          ""]
    # 全系列共性
    all_creds = sorted({c for s in series for c in s["default_credentials_identified_by"]})
    all_ports = sorted({p for s in series for p in s["web_ports"]})
    md += ["## 全系列共性", "",
           f"- 数据库/服务缺省口令(`identified by` 等):{', '.join(all_creds) or '—'}",
           f"- 出现的端口:{', '.join(all_ports) or '—'}（其中 NameNode 9870、YARN 8088、SecondaryNN 50090 等 Web UI 需真实截图,标 manual;3306/2181 等是服务端口)",
           "- 主机名约定:nodea/nodeb/nodec(三节点),并带「你学号后3位」后缀(如 nodeaNNN,NNN=你学号后3位);表名同理(empNNN)。统一由 `apply_sid` 替换。",
           "- 三台节点 IP 常见为 10.0.0.71/72/73(具体以你的 lab_config.json 为准)。",
           ""]
    for s in series:
        md += [f"## {s['title']}", "",
               f"- 网址:{s['url']}",
               f"- 子任务:{'; '.join(s['subtasks'])}",
               f"- 数据库缺省口令:{', '.join(s['default_credentials_identified_by']) or '—'}",
               f"- IP:{', '.join(s['ip_addresses']) or '—'}",
               f"- 主机名:{', '.join(s['hostnames']) or '—'}",
               f"- Web 端口:{', '.join(s['web_ports']) or '—'}",
               f"- 安装包/数据:{', '.join(s['packages']) or '—'}",
               f"- 交互工具:{', '.join(s['interactive_tools']) or '—'}",
               f"- 常见问题:{len(s['common_issues'])} 条",
               ""]
    open(out_md, "w", encoding="utf-8").write("\n".join(md))
    eprint(f"\n[OK] 共 {len(series)} 篇 -> {out_json} + {out_md}")


if __name__ == "__main__":
    main()
