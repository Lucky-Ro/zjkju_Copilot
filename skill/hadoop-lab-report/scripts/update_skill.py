#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行 skill 前自更新:用 Claude Code 自带的 git **每次新 clone** 最新版,免得用了过期版本。

需求(本脚本固化):
- 运行 skill **之前**,用 git **clone**(不是 pull)拉最新版。**默认 GitHub**,网络超时/失败**退让 Gitee**:
    GitHub: https://github.com/Lucky-Ro/zjkju_Copilot
    Gitee : https://gitee.com/lucky_ro/zjkju_Copilot
  两个镜像同源;clone/读取是**匿名**的(公开仓库),无需任何凭据,天然绕开 push 的凭据麻烦。
- **每次跑都新 clone**(`git clone --depth 1` 浅克隆到临时目录),同步进安装目录后**立即删除临时目录**:
  保证绝不过期、无缓存陈旧/损坏问题。同步时只覆盖内容确有变化的文件、从不删除安装目录里多余的文件。

行为:
  - 安装目录(`~/.claude/skills/hadoop-lab-report`)是**纯文件副本**(非 git)→ clone 最新 + 同步子树进去。
  - 若安装目录本身**在某个 git 仓库内**(开发/工作目录 clone)→ **跳过自更新**,交给你的 git 管理,
    绝不 clobber 你的本地改动。

用法(主流程在「阶段 -1 自更新」调用一次,失败也别阻断实验):
  python <skill>/scripts/update_skill.py
  python <skill>/scripts/update_skill.py --prefer gitee      # 强制先试 Gitee
  python <skill>/scripts/update_skill.py --timeout 40        # 每个远端 clone 的超时秒数(默认 30)
  python <skill>/scripts/update_skill.py --no-install-sync   # 只提示、不动安装目录

退出码:0=已更新/无需动作(或开发目录跳过);3=两个镜像都没 clone 成(网络问题,用当前版本继续,不阻断)。
"""
from __future__ import annotations
import argparse
import filecmp
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)                 # 安装目录根(.../hadoop-lab-report)
REPO_SUBPATH = os.path.join("skill", "hadoop-lab-report")   # 仓库内 skill 子树相对路径

GITHUB = "https://github.com/Lucky-Ro/zjkju_Copilot.git"
GITEE = "https://gitee.com/lucky_ro/zjkju_Copilot.git"
SKIP_NAMES = {".git", "__pycache__", ".gitignore"}   # 同步子树时跳过的目录/文件名


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)
    sys.stderr.flush()


def _git_env(timeout: int) -> dict:
    """让 git 自身在网络停滞时尽快放弃(低速即超时),并禁用任何凭据交互(免卡在密码提示)。
    clone 公开仓库本是匿名的;关交互只是兜底,避免极端情况下弹凭据窗卡死。"""
    env = dict(os.environ)
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"        # < 1KB/s
    env["GIT_HTTP_LOW_SPEED_TIME"] = str(max(5, timeout))
    env["GIT_TERMINAL_PROMPT"] = "0"                # 不弹用户名/密码提示
    env["GCM_INTERACTIVE"] = "Never"                # 关 Git Credential Manager 交互
    return env


def git(args, cwd, timeout: int):
    """跑一条 git。返回 (rc, stdout, stderr);超时返回 (124, '', 'timeout');git 缺失返回 (127, '', ...)。"""
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=_git_env(timeout),
                           timeout=timeout + 8)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "git 未安装或不在 PATH"


def find_repo_root(start: str):
    """从 start 向上找含 .git 的目录(.git 可为目录或 worktree 的文件);找不到返回 None。"""
    d = start
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def remotes_in_order(prefer: str):
    return [("Gitee", GITEE), ("GitHub", GITHUB)] if prefer == "gitee" \
        else [("GitHub", GITHUB), ("Gitee", GITEE)]


TMP_PREFIX = "zjkju_skillupd_"


def _force_writable(func, p, _exc):
    """rmtree 错误处理器:git 的 .git/objects/pack/* 在 Windows 上是**只读**的,直接删会被拒;
    清掉只读位再重试该删除操作。其它错误吞掉(交给外层重试 / 下次清扫)。"""
    try:
        os.chmod(p, stat.S_IWRITE)
        func(p)
    except Exception:
        pass


def _rmtree(path: str):
    """尽力删除目录,重试几次。两个 Windows 坑都治:
    ① git 的 pack/objects 是**只读**文件 → onexc 处理器清只读位再删;
    ② clone 超时被 kill 的 git 子进程短暂占用句柄 → 隔一会儿重试。删不掉的留给下次启动清扫。"""
    for _ in range(6):
        if not os.path.exists(path):
            return
        try:
            shutil.rmtree(path, onexc=_force_writable)        # py3.12+
        except TypeError:
            shutil.rmtree(path, onerror=_force_writable)      # 旧版回退
        if not os.path.exists(path):
            return
        time.sleep(0.4)


def _sweep_stale_temps():
    """清掉 %TEMP% 里历史遗留的 zjkju_skillupd_* 临时 clone 目录(上次 clone 超时被杀等留下的),
    避免累积。best-effort:那时的 git 子进程多已退出,句柄已释放,能干净删除。"""
    for d in glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")):
        _rmtree(d)


# ───────────────────────── clone 最新版(GitHub→Gitee 退让) ─────────────────────────
def clone_latest(prefer: str, timeout: int):
    """每次**新** clone 最新版到一个临时目录。先清扫历史遗留临时目录;再按 [GitHub, Gitee]
    (--prefer gitee 反转)依次 `git clone --depth 1 <url>`(浅克隆,只取最新一版,省流量);
    **首个成功即返回 repo 路径**;超时(rc=124)/失败(rc≠0)→ 清掉该临时目录、试下一个镜像;
    rc=127(git 缺失)→ 放弃返回 None。返回 repo 路径(调用方用完负责 _rmtree 其父临时目录);两镜像都没成 → None。"""
    _sweep_stale_temps()        # 先自愈:清掉上次超时被杀留下的残骸,避免累积
    for label, url in remotes_in_order(prefer):
        tmp = tempfile.mkdtemp(prefix=TMP_PREFIX)
        repo = os.path.join(tmp, "repo")
        eprint(f"[update] 从 {label} 克隆最新版(git clone --depth 1)…")
        rc, _, err = git(["clone", "--depth", "1", url, repo], tmp, timeout)
        if rc == 0:
            return repo
        _rmtree(tmp)
        if rc == 127:
            eprint("[update] git 缺失,无法自更新。")
            return None
        reason = "网络超时" if rc == 124 else (err.strip().splitlines()[-1][:120] if err.strip() else f"rc={rc}")
        eprint(f"[update] {label} 克隆未成功({reason}),换下一个镜像…")
    return None


def _atomic_copy(src: str, dst: str):
    """把 src 复制到 dst,**原子落地**:先写同目录临时文件,再 `os.replace` 覆盖。
    中断/崩溃只会留下「旧文件完整」或「新文件完整」,绝不出现写到一半的半截文件;
    剩余文件由下次运行的 sync_tree 自动补齐。copy2 保留 mtime(供 Python 判定是否重编译 .pyc)。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst), prefix=".tmp_upd_")
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)         # 同盘原子替换(Windows/POSIX 都支持覆盖目标)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def sync_tree(src: str, dst: str) -> int:
    """把 src 子树同步进 dst:只覆盖内容确有变化的文件,从不删除 dst 里多余的文件(安全)。
    每个文件**原子替换**(_atomic_copy),中断不会留半截文件。跳过 .git/__pycache__/.gitignore。
    返回更新的文件数。"""
    changed = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
        rel = os.path.relpath(root, src)
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        for fn in files:
            if fn in SKIP_NAMES:
                continue
            s = os.path.join(root, fn)
            t = os.path.join(target_dir, fn)
            if os.path.exists(t) and filecmp.cmp(s, t, shallow=False):
                continue                     # 内容一致,免写
            os.makedirs(target_dir, exist_ok=True)
            _atomic_copy(s, t)
            changed += 1
            eprint(f"[update]   ↻ {os.path.join(rel, fn) if rel != '.' else fn}")
    return changed


def update_install(prefer: str, timeout: int) -> bool:
    """clone 最新版 → 把其中 skill/hadoop-lab-report 子树同步进安装目录 → 删临时 clone。"""
    repo = clone_latest(prefer, timeout)
    if not repo:
        return False
    tmp_parent = os.path.dirname(repo)
    try:
        src = os.path.join(repo, REPO_SUBPATH)
        if not os.path.isdir(src):
            eprint(f"[update] 克隆里找不到 {REPO_SUBPATH},跳过同步(仓库结构可能已变)。")
            return False
        n = sync_tree(src, SKILL_ROOT)
        if n:
            eprint(f"[update] 已把 {n} 个更新文件同步到安装目录:{SKILL_ROOT}")
        else:
            eprint("[update] 安装目录已是最新版,无需改动。")
        return True
    finally:
        _rmtree(tmp_parent)   # 跑完即删临时 clone(重试,防 Windows 句柄占用),不留持久缓存


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefer", choices=["github", "gitee"], default="github",
                    help="先试哪个镜像(默认 github;超时/失败退让另一个)")
    ap.add_argument("--timeout", type=int, default=30, help="每个远端 clone 的超时秒数(默认 30)")
    ap.add_argument("--no-install-sync", action="store_true",
                    help="只提示、不 clone/不动安装目录")
    args = ap.parse_args()

    repo = find_repo_root(SKILL_ROOT)
    if repo:
        eprint(f"[update] 安装目录在 git 仓库内({repo}),自更新交给你的 git 管理,本脚本跳过(不动你的本地改动)。")
        sys.exit(0)
    if args.no_install_sync:
        eprint("[update] 已指定 --no-install-sync:跳过自更新。")
        sys.exit(0)

    eprint(f"[update] 安装目录为纯文件安装:{SKILL_ROOT} → 每次新 clone 最新版并同步。")
    if update_install(args.prefer, args.timeout):
        sys.exit(0)
    eprint("[update] 两个镜像都没 clone 成 —— 多半是网络问题。"
           "本次先用当前已安装版本继续(不阻断实验);稍后可手动重试自更新。")
    sys.exit(3)


if __name__ == "__main__":
    main()
