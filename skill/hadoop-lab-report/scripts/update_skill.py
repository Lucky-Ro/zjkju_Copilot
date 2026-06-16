#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行 skill 前自更新:用 Claude Code 自带的 git 把本 skill 拉到最新版,免得用了过期版本。

需求(本脚本固化):
- **默认拉 GitHub**,网络超时/失败**退让拉 Gitee**(两个镜像同源):
    GitHub: https://github.com/Lucky-Ro/zjkju_Copilot
    Gitee : https://gitee.com/lucky_ro/zjkju_Copilot
- **安全第一**:`git pull --ff-only`,绝不产生 merge/rebase、绝不覆盖你未提交的本地改动;
  非 git 安装则用「缓存 clone + 同步子树」的方式更新,且只覆盖内容确有变化的文件、从不删除多余文件。

两种部署都能更新:
  (A) 脚本本身在某个 git 仓库内(开发/工作目录 clone)→ 直接 ff-only 拉取该仓库。
  (B) 本机 `~/.claude/skills/hadoop-lab-report` 这种**纯文件安装**(非 git)→ 在缓存目录维护一个
      仓库 clone(拉 GitHub→Gitee),再把其中 `skill/hadoop-lab-report/` 子树**同步进安装目录**。

用法(主流程在「阶段 -1 自更新」调用一次,失败也别阻断实验):
  python <skill>/scripts/update_skill.py
  python <skill>/scripts/update_skill.py --prefer gitee      # 强制先试 Gitee
  python <skill>/scripts/update_skill.py --timeout 40        # 每个远端尝试的超时秒数(默认 30)
  python <skill>/scripts/update_skill.py --no-install-sync   # 非 git 安装时只提示、不做子树同步

退出码:0=已更新/已是最新/无需动作;3=两个远端都没拉成(网络问题,建议人工检查,但不阻断)。
"""
from __future__ import annotations
import argparse
import filecmp
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)                 # 安装目录根(.../hadoop-lab-report)
REPO_SUBPATH = os.path.join("skill", "hadoop-lab-report")   # 仓库内 skill 子树相对路径

GITHUB = "https://github.com/Lucky-Ro/zjkju_Copilot.git"
GITEE = "https://gitee.com/lucky_ro/zjkju_Copilot.git"
# 缓存 clone 落在 ~/.claude 下(非 git 安装时用),**不放进 skills/**(免被 skill 加载器误扫成
# 重复 skill),也不进任何项目目录、不进 skill 目录。
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "zjkju_update_cache")
SKIP_NAMES = {".git", "__pycache__", ".gitignore"}   # 同步子树时跳过的目录/文件名


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)
    sys.stderr.flush()


def _git_env(timeout: int) -> dict:
    """让 git 自身在网络停滞时尽快放弃(低速即超时),并禁用任何凭据交互(免卡在密码提示)。"""
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


def current_branch(repo: str, timeout: int) -> str:
    rc, out, _ = git(["rev-parse", "--abbrev-ref", "HEAD"], repo, timeout)
    b = out.strip()
    return b if (rc == 0 and b and b != "HEAD") else "main"


def remotes_in_order(prefer: str):
    return [("Gitee", GITEE), ("GitHub", GITHUB)] if prefer == "gitee" \
        else [("GitHub", GITHUB), ("Gitee", GITEE)]


# ───────────────────────── (A) 脚本在 git 仓库内:直接 ff-only 拉取 ─────────────────────────
def pull_repo(repo: str, prefer: str, timeout: int) -> bool:
    branch = current_branch(repo, timeout)
    # 有未提交改动也不强拉:ff-only 本身不会覆盖被跟踪文件的本地改动,失败就如实报告并跳过。
    rc, dirty, _ = git(["status", "--porcelain"], repo, timeout)
    if rc == 0 and dirty.strip():
        eprint("[update] 检测到本地有未提交改动 —— 仍尝试 ff-only 拉取(不会覆盖你的改动;"
               "若因此无法快进则跳过,保留你的工作)。")
    for label, url in remotes_in_order(prefer):
        eprint(f"[update] 从 {label} 拉取最新版(ff-only, branch={branch})…")
        rc, out, err = git(["pull", "--ff-only", url, branch], repo, timeout)
        if rc == 0:
            msg = (out + err).strip().splitlines()
            tail = msg[-1] if msg else ""
            if "Already up to date" in (out + err) or "已经是最新" in (out + err):
                eprint(f"[update] {label}:已是最新版。")
            else:
                eprint(f"[update] {label}:已更新到最新版。{tail}")
            return True
        reason = "网络超时" if rc == 124 else (err.strip().splitlines()[-1] if err.strip() else f"rc={rc}")
        eprint(f"[update] {label} 未成功({reason})。" + ("git 缺失,无法自更新。" if rc == 127 else "换下一个镜像…"))
        if rc == 127:
            return False
    return False


# ───────────────────────── (B) 非 git 安装:缓存 clone + 同步子树 ─────────────────────────
def cache_clone_or_pull(prefer: str, timeout: int) -> bool:
    """在 CACHE_DIR 维护一个仓库 clone:已存在则 ff-only 拉取,否则 clone。GitHub→Gitee 退让。"""
    parent = os.path.dirname(CACHE_DIR)
    os.makedirs(parent, exist_ok=True)
    if os.path.exists(os.path.join(CACHE_DIR, ".git")):
        branch = current_branch(CACHE_DIR, timeout)
        for label, url in remotes_in_order(prefer):
            eprint(f"[update] 更新本地缓存仓库(从 {label}, ff-only)…")
            rc, _, err = git(["pull", "--ff-only", url, branch], CACHE_DIR, timeout)
            if rc == 0:
                return True
            if rc == 127:
                eprint("[update] git 缺失,无法自更新。")
                return False
            eprint(f"[update] {label} 缓存拉取失败({'超时' if rc == 124 else 'rc=%d' % rc}),换镜像…")
        return False
    # 还没有缓存 → clone(浅克隆省流量)
    for label, url in remotes_in_order(prefer):
        eprint(f"[update] 首次从 {label} 克隆仓库到缓存…")
        if os.path.isdir(CACHE_DIR):
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        rc, _, err = git(["clone", "--depth", "1", url, CACHE_DIR], parent, timeout)
        if rc == 0:
            return True
        if rc == 127:
            eprint("[update] git 缺失,无法自更新。")
            return False
        eprint(f"[update] {label} 克隆失败({'超时' if rc == 124 else 'rc=%d' % rc}),换镜像…")
    return False


def sync_tree(src: str, dst: str) -> int:
    """把 src 子树同步进 dst:只覆盖内容确有变化的文件,从不删除 dst 里多余的文件(安全)。
    跳过 .git/__pycache__/.gitignore。返回更新的文件数。"""
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
            shutil.copy2(s, t)
            changed += 1
            eprint(f"[update]   ↻ {os.path.join(rel, fn) if rel != '.' else fn}")
    return changed


def update_non_git(prefer: str, timeout: int) -> bool:
    if not cache_clone_or_pull(prefer, timeout):
        return False
    src = os.path.join(CACHE_DIR, REPO_SUBPATH)
    if not os.path.isdir(src):
        eprint(f"[update] 缓存仓库里找不到 {REPO_SUBPATH},跳过同步(仓库结构可能已变)。")
        return False
    n = sync_tree(src, SKILL_ROOT)
    if n:
        eprint(f"[update] 已把 {n} 个更新文件同步到安装目录:{SKILL_ROOT}")
    else:
        eprint("[update] 安装目录已是最新版,无需改动。")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefer", choices=["github", "gitee"], default="github",
                    help="先试哪个镜像(默认 github;超时/失败退让另一个)")
    ap.add_argument("--timeout", type=int, default=30, help="每个远端尝试的超时秒数(默认 30)")
    ap.add_argument("--no-install-sync", action="store_true",
                    help="非 git 安装时只提示、不做缓存 clone + 子树同步")
    args = ap.parse_args()

    repo = find_repo_root(HERE)
    if repo:
        eprint(f"[update] 本 skill 在 git 仓库内:{repo}")
        ok = pull_repo(repo, args.prefer, args.timeout)
    else:
        eprint(f"[update] 本 skill 为纯文件安装(非 git):{SKILL_ROOT}")
        if args.no_install_sync:
            eprint("[update] 已指定 --no-install-sync:跳过自更新。"
                   "(如需自动更新,请用 git clone 安装本仓库,或去掉该参数。)")
            sys.exit(0)
        ok = update_non_git(args.prefer, args.timeout)

    if ok:
        sys.exit(0)
    eprint("[update] 两个镜像都没拉成 —— 多半是网络问题。"
           "本次先用当前已安装版本继续(不阻断实验);稍后可手动重试自更新。")
    sys.exit(3)


if __name__ == "__main__":
    main()
