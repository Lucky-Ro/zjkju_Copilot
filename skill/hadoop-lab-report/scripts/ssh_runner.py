#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSH 执行引擎(paramiko)。

设计要点:
- 每个节点开一个**持久交互 shell**(invoke_shell):环境(cd/source/sudo su)跨命令保留,
  天然支持交互提示符,像真终端。
- **忠实记录真实终端流**:PTY 保留输入回显,命令以「真实提示符 + 命令」形式出现在流里
  (`[hadoop@<真实hostname> ~]$ cmd`),输出逐行原样打印;同一份内容 tee 进 run.log,
  并作为截图来源(屏幕/日志/截图三处一致,render 不再伪造提示符)。
- **ANSI/控制序列清洗**:OSC 窗口标题(ESC]0;…BEL)、CSI 颜色/光标序列、\r 行内覆盖,
  在 tee 到屏幕/写 run.log 之前剥掉,只留人眼看到的可见文本。
- 所有 [敏感] 值在屏幕与日志里一律打码成 ****(仅发送给虚拟机的瞬间用真值;开回显后
  喂入的 secret 应答在 tee 层就地打码,呼应硬规矩 1)。
- 退出码用「分片哨兵」printf 'A''B''%s' 取得;哨兵命令自身的回显行从流中滤除。
- 交互应答按 playbook + 配置自动喂入(mysql_secure_installation / mysql -p / ssh-keygen / ssh-copy-id)。
- **hive/mysql 走真交互 REPL**:等 `hive>`/`mysql>`/`MariaDB [..]>` 提示符出现后按节奏逐句喂入,
  续行 `>` 自然出现;从流里识别 FAILED:/ERROR 判每句成败;per-statement 超时。
- state.json 断点续跑;失败默认停下,交给 Claude 自动修或进入「远程帮修模式」。

用法:
  python ssh_runner.py --preflight runs/e04/plan.json [--config lab_config.json]
  python ssh_runner.py --run       runs/e04/plan.json [--config lab_config.json] [--continue-on-error]
  python ssh_runner.py --probe nodeA [--config lab_config.json]
  (--repl-batch 退回旧的 hive -f / mysql < file 非交互方式,应急用)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import (load_config, collect_secrets, make_masker, run_dir,  # noqa: E402
                     apply_sid, eprint)

# ─── 超时设定 ───
# Hive/MR 是「长时间静默」大户:JVM 冷启动、SLF4J、连 metastore、建表、MR 作业提交期间
# 经常几十秒到几分钟无任何输出。倒计时定太短会把「正在慢慢干活」误判成「卡住」并放弃
# (run() 里空闲超时会直接 rc=None 放弃,不是单纯告警),所以这里给足余量。
IDLE_TIMEOUT = 360.0    # 单命令无新数据(且未见哨兵/未待应答)的最长静默,超过才判为卡住(原 8s 太短)
HARD_TIMEOUT = 3600.0   # 单命令硬上限(MR 作业可能跑很久),60 分钟兜底
REPL_IDLE = 600.0       # REPL banner/查询期允许的最长静默(hive 冷启动出 hive> 提示符可能要数分钟)

# ─── 哨兵延后(防 sudo type-ahead 抢答) ───
# 交互命令(sudo/ssh/mysql -p…)的「哨兵 printf」不能和命令一次性发出,否则 sudo 读密码时
# 会把缓冲区里排队的 printf 行当成密码 → Sorry, try again。改为命令先发、哨兵延后:
ANSWER_SETTLE = 0.4     # 应答交互提示后,通道安静这么久即认为输入阶段结束、可补发哨兵
SENTINEL_FALLBACK = 5.0 # 始终没出现提示(如 sudo 凭据已缓存)时,安静这么久兜底补发哨兵


# ───────────────────────── ANSI/控制序列清洗(A1) ─────────────────────────
RE_OSC = re.compile(r"\x1b\][0-9]{1,2};[^\x07\x1b]*(?:\x07|\x1b\\)")  # ESC]0;标题BEL/ST
RE_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")                       # 颜色/光标
RE_ESC1 = re.compile(r"\x1b[@-_=>]")                                    # 其余单字符 ESC 兜底


def clean_term(text: str) -> str:
    """剥掉 PTY 流里的不可见控制序列,只留人眼在终端里看到的文本。"""
    text = RE_OSC.sub("", text)
    text = RE_CSI.sub("", text)
    text = RE_ESC1.sub("", text)
    return text


def clean_line(line: str) -> str:
    """单行清洗:控制序列 + \r 行内覆盖(回车把光标移回行首重写,取最后一次)。"""
    line = clean_term(line)
    if "\r" in line:
        line = line.split("\r")[-1]
    return line


# ───────────────────────── 日志 / 回显(tee + 打码) ─────────────────────────
class Tee:
    def __init__(self, log_path, secrets):
        self.f = open(log_path, "a", encoding="utf-8")
        self.secrets = list(secrets)
        self.mask = make_masker(self.secrets)

    def add_secret(self, val):
        """运行期补登敏感值(A4):开回显后喂入的 secret 若被 PTY 回显,tee 层就地打码。"""
        v = str(val or "")
        if v.strip() and v not in self.secrets:
            self.secrets.append(v)
            self.secrets.sort(key=len, reverse=True)
            self.mask = make_masker(self.secrets)

    def _emit(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()
        self.f.write(text)
        self.f.flush()

    def cmd(self, c):
        self._emit(">> " + self.mask(c) + "\n")

    def out(self, line):
        self._emit(self.mask(line) + "\n")

    def info(self, s):
        self._emit(self.mask(s) + "\n")

    def section(self, title):
        self._emit("\n### " + self.mask(title) + "\n")

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


# ───────────────────────── 交互应答 playbook ─────────────────────────
# 每条:(正则, 值或@configref, 是否敏感)。@x 解析自 fixed_values[x];@node.x 解析自当前节点。
def build_playbook(cmd: str):
    low = cmd.lower()
    pb = []
    if "mysql_secure_installation" in low:
        pb = [
            (r"current password for root", "", False),          # 全新安装直接回车
            (r"unix_socket authentication", "n", False),
            (r"[Ss]et root password|[Cc]hange the root password", "Y", False),
            (r"New password", "@mariadb_root_password", True),
            (r"Re-enter new password", "@mariadb_root_password", True),
            (r"anonymous users", "Y", False),
            (r"[Dd]isallow root login remotely", "Y", False),
            (r"test database", "Y", False),
            (r"[Rr]eload privilege tables", "Y", False),
        ]
    elif re.search(r"mysql\s+-u\s*root\s+-p\b|mysql\s+-uroot\s+-p\b|mysql\s+-p\b", low):
        pb = [(r"Enter password", "@mariadb_root_password", True)]
    elif "ssh-keygen" in low:
        pb = [
            (r"Enter file in which", "", False),
            (r"Enter passphrase", "", False),
            (r"Enter same passphrase", "", False),
            (r"Overwrite", "y", False),
        ]
    elif "ssh-copy-id" in low or low.startswith("ssh "):
        pb = [
            (r"Are you sure you want to continue connecting", "yes", False),
            (r"password:", "@node.hadoop_password", True),
        ]
    return pb


def resolve_answer(val, cfg, node):
    if isinstance(val, str) and val.startswith("@"):
        ref = val[1:]
        if ref.startswith("node."):
            return str(node.get(ref[5:], ""))
        return str((cfg.get("fixed_values") or {}).get(ref, ""))
    return val


# ───────────────────────── 持久 shell 会话 ─────────────────────────
class Shell:
    def __init__(self, client, log: Tee, cfg, node):
        self.log = log
        self.cfg = cfg
        self.node = node
        self.chan = client.invoke_shell(term="xterm", width=200, height=1000)
        self.chan.settimeout(0.2)
        self._init_session()

    def _init_session(self):
        # A2:保留输入回显(命令像真人敲的一样出现在提示符后);PS1 用 \h 取**真实 hostname**,
        # 与 render 不再各写一套——截图里的提示符全部来自这条真实流。
        self._tail = ""   # 上一轮残留的裸提示符(无换行),与下一条命令的回显拼成完整行
        self.repl_state = None   # 当前所处的交互 REPL 名(hive/mysql/hbase/zk/spark);None=普通 shell
        self.hostname = ""       # 真实主机名(供 zkCli -server 等动态启动命令用,faithful 提示符)
        self._send_raw("export PS1='[\\u@\\h \\W]\\$ '; export LANG=en_US.UTF-8 2>/dev/null\n")
        time.sleep(0.6)
        txt = clean_term(self._drain(0.6))   # 吞掉 banner + 设置命令的回显
        self._tail = txt.rsplit("\n", 1)[-1]  # 但保留行尾的新提示符,供第一条命令拼行
        m = re.search(r"@([^\s\]]+)", self._tail)   # 从 [user@host ~]$ 提示符里取真实主机名
        if m:
            self.hostname = m.group(1)

    def _send_raw(self, s):
        self.chan.send(s)

    def _drain(self, idle=0.35):
        """读到安静为止,返回期间收到的全部文本(不打日志)。"""
        buf = []
        last = time.time()
        while time.time() - last < idle:
            try:
                data = self.chan.recv(4096)
                if data:
                    buf.append(data.decode("utf-8", "replace"))
                    last = time.time()
                    continue
            except Exception:
                pass
            time.sleep(0.05)
        return "".join(buf)

    def run(self, cmd: str, extra_answers=None, timeout=HARD_TIMEOUT):
        """执行一条命令,实时回显+捕获,返回 (exit_code, captured_text)。

        命令与「哨兵 printf」分两次发送:非交互命令紧挨着发(等价旧行为、零回归);
        交互命令(sudo/ssh/mysql -p…)的哨兵**延后**到交互输入阶段结束再发——否则 sudo
        读密码时会把缓冲区里排队的 printf 行当成密码(type-ahead 抢答)→ Sorry, try again。"""
        token = "M" + uuid.uuid4().hex[:6].upper()
        sent = "CLZJ"
        marker_re = re.compile(re.escape(sent + token) + r"(\d+)")
        # 分片哨兵:命令回显里出现的是带引号的形式,不会命中 marker_re
        sentinel = f"printf '{sent}''{token}''%s\\n' \"$?\"\n"

        # 组装应答表:命令自带的(extra_answers) + playbook
        answers = []
        for a in (extra_answers or []):
            answers.append({"re": re.compile(a["pattern"]),
                            "val": resolve_answer(a.get("value", ""), self.cfg, self.node),
                            "secret": bool(a.get("secret")), "used": False})
        for pat, val, secret in build_playbook(cmd):
            answers.append({"re": re.compile(pat),
                            "val": resolve_answer(val, self.cfg, self.node),
                            "secret": secret, "used": False})
        # sudo 密码兜底(始终生效)
        answers.append({"re": re.compile(r"\[sudo\] password for "),
                        "val": str(self.node.get("sudo_password")
                                   or self.node.get("hadoop_password", "")),
                        "secret": True, "used": False})

        # 不再额外打 `>> cmd`(B2):命令以「真实提示符 + 回显」形式出现在流里,
        # 行首提示符来自上一轮残留的 self._tail,与 PTY 回显拼成完整行。
        # 先只发命令本身;哨兵按是否交互决定即时发还是延后发(见 run() docstring)。
        self._send_raw(cmd + "\n")
        interactive = (bool(extra_answers) or bool(build_playbook(cmd))
                       or bool(re.search(r"\bsudo\b", cmd)))
        if interactive:
            sentinel_sent = False
        else:
            self._send_raw(sentinel)       # 非交互:命令+哨兵紧挨着,等价旧行为
            sentinel_sent = True
        answered_at = None                 # 最近一次成功应答交互提示的时刻

        captured = []
        pending = self._tail
        self._tail = ""
        rc = None
        start = last = time.time()
        while True:
            try:
                data = self.chan.recv(4096).decode("utf-8", "replace")
            except Exception:
                data = ""
            if data:
                last = time.time()
                pending += data
                # 整行的部分清洗后逐行回显
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    line = clean_line(line.rstrip("\r"))
                    m = marker_re.search(line)
                    if m:
                        rc = int(m.group(1))
                        break
                    if token in line and "printf" in line:
                        continue   # 哨兵命令自身的回显行,不属于用户视角的终端内容
                    captured.append(line)
                    self.log.out(line)
                if rc is not None:
                    break
                # 残行(无换行的提示符,如 "Enter password: ")里检测待应答项
                cp = clean_line(pending)
                if self._maybe_answer(cp, answers):
                    answered_at = time.time()
                if not sentinel_sent and self._sentinel_ready(answered_at, last):
                    self._send_raw(sentinel)
                    sentinel_sent = True
                if sentinel_sent and marker_re.search(cp):
                    rc = int(marker_re.search(cp).group(1))
                    pending = ""
                    break
            else:
                # 无数据:可能在等输入(残行提示)或卡住
                if pending and self._maybe_answer(clean_line(pending), answers):
                    answered_at = time.time()
                if not sentinel_sent and self._sentinel_ready(answered_at, last):
                    self._send_raw(sentinel)
                    sentinel_sent = True
                if time.time() - last > IDLE_TIMEOUT:
                    self.log.info(f"[!] 命令超过 {IDLE_TIMEOUT:.0f}s 无输出,可能在等待人工/卡住。")
                    rc = None
                    break
                if time.time() - start > timeout:
                    self.log.info(f"[!] 命令超过硬上限 {timeout:.0f}s,放弃等待。")
                    rc = None
                    break
                time.sleep(0.1)
        # 收尾:哨兵之后的残余(通常是新提示符)留作下一条命令的行首,保证提示符不丢
        rest = clean_term(pending + self._drain(0.35))
        lines = rest.split("\n")
        self._tail = lines[-1]
        for ln in lines[:-1]:
            ln = clean_line(ln.rstrip("\r"))
            if ln.strip() and not (token in ln and "printf" in ln) and not marker_re.search(ln):
                captured.append(ln)
                self.log.out(ln)
        return rc, "\n".join(captured)

    def _sentinel_ready(self, answered_at, last_data_t):
        """交互命令何时补发哨兵 printf:
        - 已应答过交互提示(如 sudo 密码):通道安静 ANSWER_SETTLE 即认为命令已吃掉输入、
          进入正常执行,此刻补发哨兵不会被当成密码读走。
        - 始终没出现提示(sudo 凭据已缓存、或命令本就不读 stdin):安静 SENTINEL_FALLBACK 兜底补发。"""
        quiet = time.time() - last_data_t
        if answered_at is not None:
            return quiet >= ANSWER_SETTLE
        return quiet >= SENTINEL_FALLBACK

    def _maybe_answer(self, pending, answers):
        for a in answers:
            if a["used"]:
                continue
            if a["re"].search(pending):
                if a["secret"]:
                    # A4:开回显后,喂入的 secret 可能被 PTY 明文回显进流;先补登打码再发送
                    self.log.add_secret(a["val"])
                self._send_raw(a["val"] + "\n")
                shown = "****" if a["secret"] else a["val"]
                self.log.cmd(f"(应答) {shown}")
                a["used"] = True
                return True
        return False

    # ───────── 交互 REPL(真实出现 hive>/mysql>/hbase(main)>/[zk:…]/scala> 提示符)─────────
    # 所有 REPL 统一「逐句喂入、等提示符再喂下一句」:命令↔回显逐条交错,绝不批量灌。
    # 字段:launch 启动命令(zk 动态,见 _repl_launch_cmd,故为 None);prompt 就绪提示符(停在行尾);
    #       error 失败识别;exit 退出命令;line_based 是否按「每非空行一句」切(zk/hbase/spark 是,
    #       hive/mysql 按 `;` 切);settle launch 后吸收异步连接日志的秒数(zk 连接是异步的)。
    SHELL_PROMPT_RE = re.compile(r"\][$#] $")
    REPL_SPECS = {
        "hive": {
            "launch": "hive",
            "prompt": re.compile(r"(?:^|\n)hive> $"),
            "error": re.compile(r"FAILED:|^Error\b|Exception", re.M),
            "exit": "exit;", "line_based": False, "settle": 0.0,
        },
        "mysql": {
            "launch": "mysql -uroot -p",
            "prompt": re.compile(r"(?:^|\n)(?:mysql|MariaDB \[[^\]]*\])> $"),
            "error": re.compile(r"^ERROR \d+", re.M),
            "exit": "quit", "line_based": False, "settle": 0.0,
        },
        "hbase": {
            "launch": "hbase shell",
            "prompt": re.compile(r"hbase\(main\):\d+:\d+>\s*$"),
            "error": re.compile(r"^ERROR\b|^ERROR:", re.M),
            "exit": "quit", "line_based": True, "settle": 0.0,
        },
        "zk": {                                   # zkCli.sh:启动命令动态生成(见 _repl_launch_cmd)
            "launch": None,
            "prompt": re.compile(r"\[zk:[^\]]*\]\s*$"),   # [zk: nodea220:2181(CONNECTED) N]
            "error": re.compile(r"KeeperErrorCode|Authentication is not valid"),
            "exit": "quit", "line_based": True, "settle": 2.0,   # 连接异步,settle 吸收 SyncConnected 等
        },
        "spark": {                                # spark-shell(scala);best-effort
            "launch": "spark-shell",
            "prompt": re.compile(r"(?:^|\n)scala>\s*$"),
            "error": re.compile(r"^<console>:|error:|Exception", re.M),
            "exit": ":quit", "line_based": True, "settle": 0.0,
        },
    }

    def _repl_launch_cmd(self, repl):
        """REPL 启动命令。zk 动态拼真实主机名 + 端口(faithful:提示符显示 nodea220:2181,与教程一致);
        其余取 spec['launch']。zk 端口默认 2181,可由 fixed_values.zk_port 覆盖。"""
        if repl == "zk":
            port = str((self.cfg.get("fixed_values") or {}).get("zk_port", "2181"))
            host = self.hostname or self.node.get("host", "localhost")
            return f"zkCli.sh -server {host}:{port}"
        return self.REPL_SPECS[repl]["launch"]

    @staticmethod
    def split_statements(sql: str):
        """按「行尾分号」切成独立语句,保留语句内部换行(续行 > 会自然出现)。hive/mysql 用。"""
        stmts, buf = [], []
        for ln in sql.splitlines():
            buf.append(ln)
            if ln.strip().endswith(";"):
                stmts.append("\n".join(buf).strip())
                buf = []
        tail = "\n".join(buf).strip()
        if tail:
            stmts.append(tail + ";")
        return [s for s in stmts if s]

    @staticmethod
    def split_lines(text: str):
        """按「每非空行一句」切。zk/hbase/spark 等基于行的 REPL 用(命令不以 `;` 结尾)。
        顺带剥掉本就是启动命令的行(如 zkCli.sh/hbase shell):那是 launch,由 enter_repl 负责。"""
        out = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if re.match(r"^(zkCli\.sh|hbase\s+shell|spark-shell|spark-sql)\b", s):
                continue
            out.append(s)
        return out

    def _wait_for(self, prompt_re, captured, timeout=HARD_TIMEOUT, answers=None, idle=REPL_IDLE):
        """读流直到清洗后的残行命中 prompt_re(提示符停在行尾=ready)。
        期间逐行回显/记录;命中后提示符留在 self._tail,与下一次喂入的回显拼行。
        返回 (ok, 期间文本)。"""
        pending = self._tail
        self._tail = ""
        seg = []
        start = last = time.time()
        while True:
            try:
                data = self.chan.recv(4096).decode("utf-8", "replace")
            except Exception:
                data = ""
            if data:
                last = time.time()
                pending += data
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    line = clean_line(line.rstrip("\r"))
                    captured.append(line)
                    seg.append(line)
                    self.log.out(line)
                cp = clean_line(pending)
                if answers:
                    self._maybe_answer(cp, answers)
                if prompt_re.search(cp):
                    self._tail = cp
                    return True, "\n".join(seg)
            else:
                cp = clean_line(pending)
                if answers and pending:
                    self._maybe_answer(cp, answers)
                if prompt_re.search(cp):
                    self._tail = cp
                    return True, "\n".join(seg)
                if time.time() - last > idle:
                    self.log.info(f"[!] REPL 超过 {idle:.0f}s 无输出,可能卡住。")
                    return False, "\n".join(seg)
                if time.time() - start > timeout:
                    self.log.info(f"[!] REPL 超过硬上限 {timeout:.0f}s,放弃等待。")
                    return False, "\n".join(seg)
                time.sleep(0.1)

    def _mysql_answers(self):
        return [{"re": re.compile(r"Enter password"),
                 "val": str((self.cfg.get("fixed_values") or {}).get("mariadb_root_password", "")),
                 "secret": True, "used": False}]

    def _settle(self, seconds, captured):
        """launch 后吸收异步连接日志(如 zk 的 SyncConnected / 后续 INFO)进**当前段**,
        直到安静 `seconds`。这样首条命令的回显不会和异步日志挤在一起。不报超时告警。"""
        pending = self._tail
        self._tail = ""
        last = time.time()
        while time.time() - last < seconds:
            chunk = self._drain(0.3)
            if chunk:
                pending += chunk
                last = time.time()
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    line = clean_line(line.rstrip("\r"))
                    if line.strip():
                        captured.append(line)
                        self.log.out(line)
        self._tail = clean_line(pending)

    def enter_repl(self, repl, timeout=HARD_TIMEOUT):
        """进入交互 REPL(若已在其中则直接返回 True)。发 launch、等就绪提示符,launch+banner
        落进**当前段**。zk 等连接异步的 REPL 再 settle 一会吸收异步日志。未就绪返回 False。"""
        if self.repl_state == repl:
            return True
        if self.repl_state:
            self.exit_repl()
        spec = self.REPL_SPECS[repl]
        answers = self._mysql_answers() if repl == "mysql" else None
        captured = []
        self._send_raw(self._repl_launch_cmd(repl) + "\n")
        ok, _ = self._wait_for(spec["prompt"], captured, timeout=timeout, answers=answers)
        if not ok:
            self.log.info(f"[!] {repl} REPL 未就绪。")
            self._send_raw("\x03\n")          # Ctrl-C 尝试脱身
            self._drain(0.6)
            return False
        if spec.get("settle"):
            self._settle(spec["settle"], captured)
        self.repl_state = repl
        return True

    def feed_repl(self, repl, statements, timeout=HARD_TIMEOUT):
        """向**已进入**的 REPL 逐句喂入本代码块的语句(一句一回车,等下一个提示符再喂下一句),
        命令↔回显逐条交错。返回**本块**的 (rc, out)。未就绪则退回 _run_repl_batch。"""
        if not self.enter_repl(repl, timeout=timeout):
            return self._run_repl_batch(repl, statements, timeout)
        spec = self.REPL_SPECS[repl]
        answers = self._mysql_answers() if repl == "mysql" else None
        splitter = self.split_lines if spec.get("line_based") else self.split_statements
        captured = []
        failed = 0
        for stmt in splitter(statements):
            self._send_raw(stmt + "\n")
            ok, seg = self._wait_for(spec["prompt"], captured, timeout=timeout, answers=answers)
            if not ok:
                failed += 1
                break
            if spec["error"].search(seg):
                failed += 1
        return (0 if failed == 0 else 1), "\n".join(captured)

    def exit_repl(self):
        """退出当前 REPL 回到普通 shell。**静默**吞掉退出噪声(如 zk 的 WATCHER Closed /
        session closed),不记日志、不进截图;只把行尾的 shell 提示符留作下一条命令拼行。"""
        if not self.repl_state:
            return
        spec = self.REPL_SPECS[self.repl_state]
        self._send_raw(spec["exit"] + "\n")
        pending = self._tail
        self._tail = ""
        start = time.time()
        while time.time() - start < 10:
            chunk = self._drain(0.4)
            pending = clean_term(pending + chunk)
            if self.SHELL_PROMPT_RE.search(pending.split("\n")[-1]):
                break
            if not chunk:
                break
        self._tail = clean_line(pending.split("\n")[-1])
        self.repl_state = None

    def run_repl(self, repl, statements, timeout=HARD_TIMEOUT, batch=False):
        """单发封装 = enter+feed+exit(供 --repl-batch 应急或单块调用)。会话保持由 cmd_run
        直接编排 enter/feed/exit 完成(同子任务同 REPL 复用一个会话、块间不退出)。"""
        if batch or repl not in self.REPL_SPECS:
            return self._run_repl_batch(repl, statements, timeout)
        rc, out = self.feed_repl(repl, statements, timeout=timeout)
        self.exit_repl()
        return rc, out

    def _run_repl_batch(self, repl, statements, timeout=HARD_TIMEOUT):
        """(旧路径,应急 --repl-batch / 交互未就绪兜底)非交互方式喂入。
        交互不可用时退而求其次,不追求交错。"""
        if repl in ("zk", "hbase", "spark"):
            # 行式 REPL:把命令逐行通过 heredoc 灌进客户端(应急,不交错)
            body = "\n".join(self.split_lines(statements))
            launch = self._repl_launch_cmd(repl)
            return self.run(f"{launch} <<'CLZJEOF'\n{body}\nCLZJEOF", timeout=timeout)
        body = statements if statements.strip().endswith(";") else statements + ";"
        tmp = f"/tmp/clzj_{uuid.uuid4().hex[:6]}." + ("hql" if repl == "hive" else "sql")
        heredoc = f"cat > {tmp} <<'CLZJEOF'\n{body}\nCLZJEOF"
        self.run(heredoc, timeout=60)
        if repl == "hive":
            return self.run(f"hive -f {tmp}", timeout=timeout)
        if repl == "mysql":
            pwd = str((self.cfg.get("fixed_values") or {}).get("mariadb_root_password", ""))
            return self.run(f"mysql -uroot -p{pwd} < {tmp}", timeout=timeout)
        return self.run(f"cat {tmp}", timeout=30)


# ───────────────────────── 连接管理 ─────────────────────────
# ─── 连接重试设定(指数避让) ───
CONNECT_ATTEMPTS = 4        # 总尝试次数:1 次首发 + 3 次重试
CONNECT_BACKOFF_BASE = 2.0  # 指数避让基数,重试前等待 2s → 4s → 8s
# 可重试:握手超时、端口暂不可达、协议 banner 读取失败等瞬时故障。
# AuthenticationException / NoValidConnectionsError 都是 SSHException 子类:认证失败
# 在下面单独 except 摘除(立即上抛),NoValidConnectionsError 走 SSHException 这条重试。
RETRYABLE = (socket.timeout, TimeoutError,
             paramiko.ssh_exception.NoValidConnectionsError,
             paramiko.ssh_exception.SSHException, OSError)


def connect(node, log=None, attempts=CONNECT_ATTEMPTS, base=CONNECT_BACKOFF_BASE):
    """带指数避让重试的 SSH 连接。握手超时/瞬时不可达会重试 attempts 次
    (间隔 base**1, base**2 … 秒);认证失败立即上抛,不浪费时间重试。"""
    def _note(msg):
        (log.info if log else eprint)(msg)
    last = None
    for i in range(1, attempts + 1):
        try:
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cli.connect(hostname=node["host"], port=int(node.get("ssh_port", 22)),
                        username=node.get("username", "hadoop"),
                        password=node.get("hadoop_password"),
                        look_for_keys=False, allow_agent=False, timeout=15)
            if i > 1:
                _note(f"[retry] {node['name']} 第 {i}/{attempts} 次尝试连接成功。")
            return cli
        except paramiko.AuthenticationException:
            raise                      # 密码/认证错,重试无意义,立即上抛
        except RETRYABLE as e:
            last = e
            if i < attempts:
                delay = base ** i      # 2, 4, 8 …
                _note(f"[retry] {node['name']} 连接失败({type(e).__name__}),"
                      f"{delay:.0f}s 后第 {i + 1}/{attempts} 次重试…")
                time.sleep(delay)
            else:
                _note(f"[X] {node['name']} 连续 {attempts} 次连接失败:"
                      f"{type(e).__name__}: {e}")
    raise last                          # 重试用尽,把最后一次异常抛给调用方(语义不变)


def node_by_name(cfg, name):
    for n in cfg.get("nodes", []):
        if n["name"].lower() == str(name).lower():
            return n
    return None


# ───────────────────────── state.json ─────────────────────────
def load_state(rd):
    p = os.path.join(rd, "state.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"cursor": None, "steps": {}, "issues": [], "blocked": None}


def save_state(rd, st):
    json.dump(st, open(os.path.join(rd, "state.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def launch_live_window(rd):
    """默认自动弹一个实时日志窗口(独立控制台),让用户像看真终端一样跟着看。

    用**纯 Python**(live_tail.py)在新控制台拉起,不用 PowerShell —— 这样不触发
    `-ExecutionPolicy Bypass` 的安全分类器拦截(那正是上次「终端没弹出」的原因)。
    先 touch run.log,窗口一开就有内容、不空等。失败不影响主流程。
    """
    try:
        script = os.path.join(HERE, "live_tail.py")
        runlog = os.path.abspath(os.path.join(rd, "run.log"))
        open(runlog, "a", encoding="utf-8").close()   # 确保文件已存在
        CREATE_NEW_CONSOLE = 0x00000010
        flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
        subprocess.Popen([sys.executable, script, runlog],
                         creationflags=flags, cwd=os.path.dirname(runlog))
        eprint(f"[live] 已打开实时日志窗口,跟随 {runlog}")
    except Exception as e:
        eprint(f"[live] 打开实时窗口失败(不影响运行): {type(e).__name__}: {e}")


def live_init(rd, title):
    with open(os.path.join(rd, "live.md"), "w", encoding="utf-8") as f:
        f.write(f"# 运行进度:{title}\n\n"
                f"> 高层进度;完整实时输出看同目录 run.log(启动时已自动弹 live_tail.py 实时窗口)。\n\n")


def live(rd, text):
    with open(os.path.join(rd, "live.md"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


# ───────────────────────── 子命令 ─────────────────────────
def cmd_probe(cfg, log, name):
    node = node_by_name(cfg, name)
    if not node:
        log.info(f"[X] 配置里没有节点 {name}")
        return 2
    try:
        cli = connect(node, log)
        sh = Shell(cli, log, cfg, node)
        rc, out = sh.run("whoami && hostname -I 2>/dev/null || hostname")
        cli.close()
        log.info(f"[OK] {name} 可登录 (rc={rc})")
        return 0
    except Exception as e:
        log.info(f"[X] {name} 连接失败: {type(e).__name__}: {e}")
        return 1


def cmd_preflight(cfg, log, plan, rd):
    """预检:登录 / sudo / 节点连通 / 安装包就位。结果写 preflight.json,
    并把「缺什么」汇总到 missing[],供 Claude 决定是否弹窗让用户先备齐(一步到位)。"""
    log.section("预检 preflight")
    result = {"nodes": {}, "connectivity": {}, "packages": {}, "missing": [], "ready": True}
    shells = {}
    for node in cfg.get("nodes", []):
        nm = node["name"]
        try:
            cli = connect(node, log)
            sh = Shell(cli, log, cfg, node)
            shells[nm] = (cli, sh)
            sh.run("whoami; id")
            rc, out = sh.run("sudo -n true && echo SUDO_OK || echo SUDO_NEEDS_PWD")
            sudo = "ok" if "SUDO_OK" in out else "needs_pwd"
            result["nodes"][nm] = {"login": True, "sudo": sudo}
            log.info(f"[OK] {nm} 登录成功 (sudo={sudo})")
        except Exception as e:
            result["nodes"][nm] = {"login": False, "error": f"{type(e).__name__}: {e}"}
            result["missing"].append(f"无法 SSH 登录 {nm}({node.get('host')}):{type(e).__name__}")
            result["ready"] = False
            log.info(f"[X] {nm} 登录失败: {type(e).__name__}: {e}")
    # 节点连通性
    for n in cfg.get("nodes", []):
        if n["name"] in shells:
            _, sh = shells[n["name"]]
            for m in cfg.get("nodes", []):
                if m is not n:
                    rc, out = sh.run(f"ping -c1 -W1 {m['host']} >/dev/null 2>&1 && "
                                     f"echo REACH_OK || echo REACH_FAIL")
                    key = f"{n['name']}->{m['name']}"
                    okp = "REACH_OK" in out
                    result["connectivity"][key] = okp
                    if not okp:
                        result["missing"].append(f"{n['name']} ping 不通 {m['name']}({m['host']})")
    # 安装包就位(local 看 dest 是否已上传;remote 看 src 是否存在)
    names = [n["name"] for n in cfg.get("nodes", [])]
    for pkg in cfg.get("packages", []):
        cand = [pkg.get("node")] if pkg.get("node") else names
        for nm in cand:
            if nm in shells:
                _, sh = shells[nm]
                path = (pkg.get("dest_path", "") + pkg.get("name", "")) \
                    if pkg.get("src_type") == "local" else pkg.get("src_path", "")
                rc, out = sh.run(f"test -e '{path}' && echo PKG_OK || echo PKG_MISSING")
                present = "PKG_OK" in out
                result["packages"][f"{pkg.get('name')}@{nm}"] = {"path": path, "present": present,
                                                                 "src_type": pkg.get("src_type")}
                # local 包未就位不算缺(可现场上传);remote 包缺失才算缺
                if not present and pkg.get("src_type") == "remote":
                    result["missing"].append(f"{nm} 上找不到包 {pkg.get('name')}({path})")
                    result["ready"] = False
    for cli, _ in shells.values():
        cli.close()
    with open(os.path.join(rd, "preflight.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if result["ready"]:
        log.info("[OK] 预检通过,环境就绪,可开始执行。preflight.json 已写。")
    else:
        log.info("[!] 预检有缺口(见下),请准备齐后再跑;或对不通的节点进入远程帮修模式:")
        for m in result["missing"]:
            log.info(f"    - {m}")
    return 0 if result["ready"] else 1


RUNNABLE = {"auto"}  # 自动跑的只有 auto;author 待 Claude 生成命令,manual 是前置条件,note 仅上下文


def cmd_run(cfg, log, plan, rd, continue_on_error=False, repl_batch=False):
    sid3 = cfg["identity"].get("student_id_last3", "")
    st = load_state(rd)
    live_init(rd, plan.get("title", ""))
    shells = {}

    def shell_for(node_name):
        node = node_by_name(cfg, node_name) or cfg["nodes"][0]
        key = node["name"]
        if key not in shells:
            shells[key] = Shell(connect(node, log), log, cfg, node)
        return shells[key]

    def resolved_key(step):
        node = node_by_name(cfg, step.get("target_node")) or cfg["nodes"][0]
        return node["name"]

    def next_exec_step(steps, i):
        """同子任务内,i 之后第一个真正会执行的步(auto + 有 code)。"""
        for s in steps[i + 1:]:
            if s.get("kind") == "auto" and s.get("code"):
                return s
        return None

    def exit_all_repls():
        for s in shells.values():
            try:
                s.exit_repl()
            except Exception:
                pass

    rc_final = 0
    try:
        for sub in plan["subtasks"]:
            steps = sub["steps"]
            for i, step in enumerate(steps):
                sid_key = f"{sub['subtask_id']}#{step['idx']}"
                if st["steps"].get(sid_key) == "done":
                    log.info(f"[skip] {sid_key} 已完成,跳过(仍可在排版阶段引用其证据)")
                    continue
                kind = step["kind"]
                log.section(f"{sid_key}  [{kind}] {step['text'][:60]}")
                live(rd, f"- ▶ {sid_key} [{kind}] {step['text'][:50]}")
                if kind == "manual":
                    log.info("[manual] GUI/人工步骤,列入前置条件,需用户操作后回『继续』。")
                    st["steps"][sid_key] = "manual"
                    live(rd, f"    · {sid_key} 需人工/GUI(前置条件)")
                    continue
                if kind == "note":
                    st["steps"][sid_key] = "note"
                    continue
                if kind == "author":
                    log.info("[author] 需 Claude 生成命令(如 HiveQL),再对照 expect_output 校验;"
                             "本引擎不自动执行。")
                    st["steps"][sid_key] = "author-pending"
                    continue
                if step["lang"] == "xml":
                    log.info("[xml] 配置文件内容:请由 Claude 用 heredoc 写入目标文件,不在此自动执行。")
                    st["steps"][sid_key] = "xml-pending"
                    continue

                code = apply_sid(step["code"], sid3)  # 学号占位替换
                sh = shell_for(step.get("target_node") or cfg["nodes"][0]["name"])
                if step.get("repl") and not repl_batch:
                    # 真交互:进入会话(首块捕获 launch+banner 进本段)→ 逐句喂入本块语句。
                    # 同子任务下一可执行步若仍是同 REPL+同节点,则**不退出**(会话跨块复用,
                    # 临时节点 -e 得以保留);否则收尾退出。每块仍是独立 ### 段 → 各自一张图。
                    sh.enter_repl(step["repl"])
                    rc, out = sh.feed_repl(step["repl"], code)
                    nxt = next_exec_step(steps, i)
                    keep = (nxt is not None and nxt.get("repl") == step["repl"]
                            and resolved_key(nxt) == resolved_key(step))
                    if not keep:
                        sh.exit_repl()
                elif step.get("repl"):                 # --repl-batch 应急:非交互喂入
                    sh.exit_repl()
                    rc, out = sh.run_repl(step["repl"], code, batch=True)
                else:
                    sh.exit_repl()                     # 跑普通 shell 命令前,先离开任何 REPL
                    rc, out = sh.run(code)

                if rc == 0:
                    st["steps"][sid_key] = "done"
                    live(rd, f"    ✓ {sid_key} 完成")
                else:
                    st["steps"][sid_key] = "failed"
                    st["cursor"] = {"subtask": sub["subtask_id"], "step": step["idx"]}
                    save_state(rd, st)
                    live(rd, f"    ✗ {sid_key} 失败 rc={rc}")
                    log.info(f"[FAIL] {sid_key} 退出码={rc}。"
                             f"{'继续(--continue-on-error)' if continue_on_error else '停下,交给 Claude 处理。'}")
                    if not continue_on_error:
                        rc_final = 1
                        return rc_final
                save_state(rd, st)
            exit_all_repls()   # 子任务结束:退出残留会话(回到 shell,临时节点随会话释放)
    finally:
        exit_all_repls()
        for sh in shells.values():
            try:
                sh.chan.get_transport().close()
            except Exception:
                pass
        save_state(rd, st)
    log.info("[OK] 执行流程结束(auto 步骤)。author/xml/manual 步骤需 Claude/用户补完。")
    return rc_final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="lab_config.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preflight", metavar="PLAN")
    g.add_argument("--run", metavar="PLAN")
    g.add_argument("--probe", metavar="NODE")
    ap.add_argument("--continue-on-error", action="store_true")
    ap.add_argument("--no-window", action="store_true",
                    help="不自动弹实时日志窗口(默认会弹)")
    ap.add_argument("--repl-batch", action="store_true",
                    help="hive/mysql 退回旧的 hive -f / mysql < file 非交互方式(应急)")
    args = ap.parse_args()

    cfg = load_config(args.config)   # 读项目目录的 ./lab_config.json,派生学号后3位
    secrets = collect_secrets(cfg)
    rd = run_dir(cfg)
    log = Tee(os.path.join(rd, "run.log"), secrets)
    # 默认自动弹实时窗口(probe 太短不弹)
    if (args.run or args.preflight) and not args.no_window:
        launch_live_window(rd)
    try:
        if args.probe:
            sys.exit(cmd_probe(cfg, log, args.probe))
        plan_path = args.preflight or args.run
        plan = json.load(open(plan_path, encoding="utf-8"))
        if args.preflight:
            sys.exit(cmd_preflight(cfg, log, plan, rd))
        else:
            sys.exit(cmd_run(cfg, log, plan, rd, args.continue_on_error, args.repl_batch))
    finally:
        log.close()


if __name__ == "__main__":
    main()
