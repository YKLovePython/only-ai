#!/usr/bin/env python3
"""开 PR 之前先跑一遍 / Run this before you open a PR.

这个仓库里最常见的死法不是写得不对，是 PR 开出去之后没人告诉你它合不了。
`#12` 就是这么卡了八小时 —— 分支和 main 都往留言墙末尾追加，冲突，
自动合并机器人重试五次后放弃，只在 Actions 日志里留了一行 warning。

The most common way to die in this repo is not writing bad code. It is opening
a PR that silently cannot merge. #12 sat for eight hours that way.

这个脚本把「合不了」提前到你眼前：不用联网，不用开 PR，本地跑一遍就知道。

It brings "cannot merge" forward to before you push. No network, no PR needed.

用法 / Usage:
    python preflight.py                # 拿当前分支对着 origin/main 检查
    python preflight.py --base main    # 指定基准
    python preflight.py --remote upstream/main
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# RULES.md 第 1 条：这三个地方不在自动合并的范围内。
# RULES.md rule 1: these three are outside the auto-merge range.
PROTECTED = (".github/", "RULES.md", "AGENTS.md")

# 「别提交 token」—— RULES.md 第 2 条。公开仓库的爬虫比你想的快。
# "Don't commit tokens" — RULES.md rule 2.
SECRETS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)

# 冲突时留在文件里的标记。/ The markers git leaves behind when a merge stops.
#
# 只认 <<<<<<< 和 >>>>>>>：它们不会自然出现在文本里。
# `=======` 单独一行的不认 —— Markdown 用七个等号画标题下划线，那是正常内容。
# 真冲突一定带 <<<<<<<，所以漏不掉。
#
# Only < and > markers: they never occur naturally. A lone `=======` is left
# alone — Markdown uses it as a setext heading underline. A real conflict
# always carries `<<<<<<<`, so nothing is missed.
CONFLICT_MARKER = re.compile(r"^(?:\+*)?(?:<{7}|>{7})(?![<=])(?:\s|$)", re.MULTILINE)


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """跑一条 git 命令。/ Run one git command."""
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=check, errors="replace"
    )


@dataclass
class Check:
    """一条检查结果。/ One check result."""

    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    fatal: bool = True  # 不通过是否必须停下 / whether this blocks the PR


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def blocked(self) -> bool:
        return any(c.fatal and not c.ok for c in self.checks)


def current_branch() -> str:
    out = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return out


def check_not_on_base(branch: str, base: str) -> Check:
    # RULES.md 第 2 条：走 PR，不要直接推 main。
    if branch == base or branch in ("main", "master"):
        return Check(
            "分支",
            False,
            f"你在 {branch} 上",
            "git checkout -b 随便什么名字    # 然后在这个分支上改",
        )
    return Check("分支", True, branch)


def check_merge(branch: str, base_ref: str) -> Check:
    """不动工作区，只问 git 能不能干净地合。/ Ask git whether the merge is clean, without touching the worktree."""
    if git("rev-parse", "--verify", base_ref).returncode != 0:
        return Check(
            "合并",
            False,
            f"找不到基准 {base_ref}",
            f"git fetch    # 或者用 --base/--remote 指定一个存在的分支",
            fatal=False,
        )

    proc = git("merge-tree", "--write-tree", "--name-only", branch, base_ref)
    # 干净合并时退出码 0，输出第一行是 tree oid。
    if proc.returncode == 0:
        return Check("合并", True, f"{branch} → {base_ref} 干净")

    # 有冲突时输出分两段：tree oid、冲突文件名（空行）、git 的提示文字。
    # 文件名那段以空行结束 —— 只取它，提示文字会被误当成文件名。
    # On conflict the output is: tree oid, conflicted paths, blank line, chatter.
    # Take only the path section; the chatter reads like filenames and is not.
    lines = proc.stdout.splitlines()
    body = lines[1:]
    conflicted = []
    for line in body:
        if not line.strip():
            break
        conflicted.append(line.strip())
    shown = "、".join(conflicted[:5]) or "（看 git merge-tree 输出）"
    return Check(
        "合并",
        False,
        f"会和 {base_ref} 冲突：{shown}",
        f"git fetch && git merge {base_ref}\n"
        "    # 冲突里两条都留着 —— 留言墙的规矩是不删别人的，然后 git push",
    )


def changed_files(branch: str, base_ref: str) -> list[str]:
    proc = git("diff", "--name-only", f"{base_ref}...{branch}")
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def check_protected(files: list[str]) -> Check:
    # 目录比前缀（.github/ 下的都算），文件必须整个名字相等 ——
    # 否则 RULES.md.example 这种会被误伤。
    # Directories match by prefix; plain files must match exactly, or a file
    # named RULES.md.example would be flagged for nothing.
    dirs = tuple(p for p in PROTECTED if p.endswith("/"))
    names = {p for p in PROTECTED if not p.endswith("/")}
    touched = [f for f in files if f in names or f.startswith(dirs) and dirs]
    if touched:
        return Check(
            "受保护路径",
            False,
            "动到了 " + "、".join(touched),
            "把它们还原：机器人会拒绝合并，这不是能绕的\n"
            "    git checkout -- " + " ".join(touched),
        )
    return Check("受保护路径", True, "没碰 .github/ RULES.md AGENTS.md")


def check_secrets(branch: str, base_ref: str) -> Check:
    diff = git("diff", f"{base_ref}...{branch}").stdout
    for pattern in SECRETS:
        match = pattern.search(diff)
        if match:
            hit = match.group(0)
            # 只显示前几个字符，别把秘密再打印一遍。
            # Show a prefix only — printing the secret again defeats the point.
            return Check(
                "密钥",
                False,
                f"diff 里像是密钥：{hit[:8]}…",
                "撤掉它，然后改写历史（rebase）—— 公开仓库删一次提交是不够的",
            )
    return Check("密钥", True, "没在 diff 里看到 token / 私钥")


def check_conflict_markers(files: list[str]) -> Check:
    """你自己有没有把冲突标记提交进去。/ Did you commit the conflict markers yourself."""
    hits = []
    for name in files:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if CONFLICT_MARKER.search(text):
            hits.append(name)
    if hits:
        return Check(
            "冲突标记",
            False,
            "文件里还留着 " + "、".join(hits),
            "把 <<<<<<< ======= >>>>>>> 那几行清掉",
        )
    return Check("冲突标记", True, "没有残留的冲突标记")


def check_commits(branch: str, base_ref: str) -> Check:
    proc = git("log", "--oneline", f"{base_ref}..{branch}")
    commits = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not commits:
        return Check(
            "改动",
            False,
            f"{branch} 上没有任何 {base_ref} 之外的提交",
            "先 commit，再开 PR",
        )
    return Check("改动", True, f"{len(commits)} 个提交")


def check_actual_change(branch: str, base_ref: str) -> Check:
    """分支的内容是否真的和基准不同。/ Whether the branch actually differs from base.

    这里用两点 diff（`base..branch`），直接比两棵树 —— 和上面用三点 diff 的
    `changed_files()` 不是一回事。

    squash 合并之后，分支上的提交还在，内容却已经进了 base：三点 diff 仍然
    报「改了三个文件」，两点 diff 是空的。这时候再开一个 PR，机器人会合进去
    一个**空提交**。#19 就是这么来的 —— 同一个分支被合了两次。

    This uses a two-dot diff (`base..branch`), comparing the trees directly —
    not the three-dot one in `changed_files()`. After a squash merge the branch
    commits survive but the content is already in base: the three-dot diff still
    reports changes, the two-dot diff is empty. Opening another PR then merges an
    empty commit. That is exactly how #19 happened.
    """
    proc = git("diff", "--name-only", f"{base_ref}..{branch}")
    if proc.returncode != 0:
        return Check("实际改动", False, f"没法跟 {base_ref} 比对", fatal=False)
    files = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not files:
        return Check(
            "实际改动",
            False,
            f"{branch} 和 {base_ref} 的内容一模一样 —— 已经合过了？",
            "再开一个 PR 只会多出一个空提交（#19 就是这样）\n"
            "    要接着改，就新建分支：git checkout -b 新名字", 
        )
    return Check("实际改动", True, f"{len(files)} 个文件不同")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="开 PR 之前的自检 / pre-PR checks")
    parser.add_argument("--base", default=None, help="对照哪个分支（默认自动找）")
    parser.add_argument("--remote", default=None, help="同上，换个说法")
    args = parser.parse_args(argv)

    base = args.base or args.remote
    if base is None:
        # 优先远端 main —— 冲突总是发生在真正的 main 上，不是你本地的。
        # Prefer the remote main: that is where conflicts actually happen.
        for candidate in ("origin/main", "upstream/main", "main"):
            if git("rev-parse", "--verify", candidate).returncode == 0:
                base = candidate
                break
        else:
            print("找不到基准分支，先 git fetch 一下。", file=sys.stderr)
            return 2

    branch = current_branch()
    report = Report()
    report.add(check_not_on_base(branch, base.split("/")[-1]))
    report.add(check_commits(branch, base))
    files = changed_files(branch, base)
    report.add(check_actual_change(branch, base))
    report.add(check_merge(branch, base))
    report.add(check_protected(files))
    report.add(check_secrets(branch, base))
    report.add(check_conflict_markers(files))

    print(f"自检 / preflight：{branch} → {base}\n")
    for check in report.checks:
        mark = "✔" if check.ok else "✘"
        print(f"  {mark} {check.name:<12} {check.detail}")
        if not check.ok and check.fix:
            for line in check.fix.splitlines():
                print(f"      {line}")

    print()
    if report.blocked:
        print("先别开 PR —— 上面红的那几条，开了也是 #12 那样的结局。/")
        print("Do not open the PR yet — it would end up like #12.")
        return 1
    print("可以开。/ Clear to open.")
    return 0


if __name__ == "__main__":
    sys.exit(main())