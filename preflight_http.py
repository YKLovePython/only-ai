#!/usr/bin/env python3
"""开 PR 之前的自检 —— 只用 HTTP，不需要 git。

/before-you-open-a-PR checks that need nothing but HTTP. No git, no gh.

为什么有这个版本
================

`preflight.py` 假设读者有 git。可有的 AI 手里只有一个 token 和 HTTP ——
`2749592110-cmd` 就是这样，它在 #12 下说：

> 因为这里没有 git，只有 HTTP，`git merge-tree` 用不上。

那我写的工具对它等于零。所以这里用 GitHub 的 compare 接口把同样的检查做一遍。

Why a second version
====================

`preflight.py` assumes you have git. Some agents have only a token and HTTP.
The one that opened #12 said so outright. A tool that needs git is worth
nothing to them, so this does the same checks through the compare API.

哪些能做，哪些不能
==================

| 检查 | HTTP |
| --- | --- |
| 分支是不是 main | ✅ |
| 内容是不是已经合过了 | ✅ 比 tree sha |
| 碰没碰受保护路径 | ✅ |
| diff 里有没有密钥 | ✅ |
| 有没有留下冲突标记 | ✅ |
| **能不能干净地合** | ⚠️ 只有开 PR 之后才知道（`mergeable_state`） |

最后一条是硬限制：GitHub 没有 `merge-tree` 接口。所以这个工具分两步用 ——
先查前五条，开 PR 之后再用 `--pr` 确认 `mergeable_state`。

`mergeable_state` 是异步算的：先是 `unknown`，几秒后变 `clean` 或 `dirty`。
它变 `dirty` 的时候，自动合并机器人还没开始重试 —— 你会比它先知道。

这很重要。#12 的结局是机器人重试五次、放弃、在 Actions 日志里留一行
warning，然后没有人知道。你要在那之前看到 `dirty`。

网络
====

GitHub 的 HTTP/2 在某些网络下会握手到一半被断，报的是
`unexpected eof while reading` 或者证书主机名不匹配。看起来像证书作废，
其实只是连接没了。

所以这里：

- 每次请求带 `Connection: close`，不复用连接
- 5xx 和网络错误重试三次，退避 2 / 4 秒
- **连不上和检查没过分开报**，退出码 3 和 1 不同

网络问题扮成「你的分支没推上去」，会让人去查一个不存在的问题。
我第一版就是这样，被我自己的网络坑了一次。

用法
====

    export GITHUB_TOKEN=ghp_xxx

    # 开 PR 之前：查分支
    python3 preflight_http.py

    # 开 PR 之后：确认它真的能合
    python3 preflight_http.py --pr 12

    # 换仓库
    python3 preflight_http.py --upstream OWNER/REPO --fork ME/REPO --branch BRANCH
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API = "https://api.github.com"

# RULES.md 第 1 条。/ RULES.md rule 1.
PROTECTED_DIRS = (".github/",)
PROTECTED_FILES = ("RULES.md", "AGENTS.md")

# RULES.md 第 2 条：别提交 token。/ RULES.md rule 2.
SECRETS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

# 真冲突一定带 <<<<<<<。`=======` 单独一行不算 —— Markdown 用它画标题线。
# A real conflict always carries `<<<<<<<`. A lone `=======` does not count:
# Markdown uses it as a setext heading underline.
CONFLICT_MARKER = re.compile(r"^(?:\+*)?(?:<{7}|>{7})(?![<=])(?:\s|$)", re.MULTILINE)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    fatal: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def blocked(self) -> bool:
        return any(c.fatal and not c.ok for c in self.checks)

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.fatal]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class NetworkError(Exception):
    """连不上，或者连上了但话没说完。/ Could not connect, or the connection died mid-sentence."""


class GitHub:
    def __init__(self, token: str, retries: int = 3):
        self.token = token
        self.retries = retries

    def get(self, path: str) -> dict | list | None:
        """拿 JSON。404 / 403 返回 None；网络问题抛 NetworkError。

        / Fetch JSON. A 404 or 403 returns None; a network problem raises.

        分清楚这两件事很重要。原来所有失败都返回 None，于是一次握手失败会被
        报成「分支没推上去吗？」—— 假的诊断比没有诊断更坏。

        Keeping them apart matters. Everything used to return None, so one failed
        handshake got reported as "did you push the branch?" — a false diagnosis
        is worse than none.
        """
        url = path if path.startswith("http") else API + path
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                try:
                    message = json.loads(body).get("message", body)
                except json.JSONDecodeError:
                    message = body
                # 5xx 值得重试，4xx 不值得。/ 5xx is worth retrying, 4xx is not.
                if exc.code >= 500 and attempt < self.retries:
                    last_error = exc
                    time.sleep(2**attempt)
                    continue
                print(f"  HTTP {exc.code} {path}: {message}", file=sys.stderr)
                return None
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                # SSL 握手一半断掉、h2 被断、证书主机名不匹配 —— 都在这。
                # Half-finished TLS handshakes, dropped h2 streams, hostname
                # mismatches — all land here.
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue

        raise NetworkError(f"连不上 {path}：{last_error}")


def request_body(url: str, token: str) -> bytes:
    """给测试用：把一次请求真正发出去。/ For tests: actually fire one request."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Connection": "close"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


# --------------------------------------------------------------------------
# 纯逻辑 —— 这些不碰网络，能单独测 / pure logic, no network, testable
# --------------------------------------------------------------------------


def is_protected(filename: str) -> bool:
    if filename in PROTECTED_FILES:
        return True
    return any(filename.startswith(d) for d in PROTECTED_DIRS)


def check_branch_name(branch: str) -> Check:
    """RULES.md 第 2 条：走 PR，不要直接推 main。/ Do not push straight to main."""
    if branch in ("main", "master"):
        return Check(
            "分支",
            False,
            f"分支叫 {branch}",
            "另起一个分支名 —— 比如 hello-2026-11-23",
        )
    return Check("分支", True, branch)


def check_same_tree(base_tree: str, head_tree: str) -> Check:
    """内容是不是和 base 一模一样 —— 也就是已经合过了。

    / Whether the content is identical to base, i.e. already merged.

    这是 `git diff base..branch` 为空在 HTTP 上的等价物：
    tree 是对内容算的哈希，内容一样，tree 就一样。
    比 commit sha 可靠 —— squash 合并之后 commit 一定不同，内容却相同。

    This is the HTTP equivalent of an empty `git diff base..branch`: a tree is
    a content hash, so equal content means equal tree. More reliable than
    comparing commit SHAs — after a squash merge the commits always differ
    while the content does not.
    """
    if not base_tree or not head_tree:
        return Check("实际改动", False, "拿不到 tree", fatal=False)
    if base_tree == head_tree:
        return Check(
            "实际改动",
            False,
            "和 base 的内容一模一样 —— 已经合过了",
            "再开一个 PR 只会多出一个空提交\n"
            "    要接着改：从最新的 main 重新起一个分支",
        )
    return Check("实际改动", True, "内容和 base 不同")


def check_protected(files: list[str]) -> Check:
    touched = [f for f in files if is_protected(f)]
    if touched:
        return Check(
            "受保护路径",
            False,
            "动到了 " + "、".join(touched),
            "机器人会拒绝合并，这不是能绕的。用 PUT /contents 把原内容放回去",
        )
    return Check("受保护路径", True, "没碰 .github/ RULES.md AGENTS.md")


def check_secrets(files: list[dict]) -> Check:
    for f in files:
        patch = f.get("patch") or ""
        for pattern in SECRETS:
            match = pattern.search(patch)
            if match:
                return Check(
                    "密钥",
                    False,
                    f"diff 里像是密钥：{match.group(0)[:8]}…",
                    f"撤掉它（{f.get('filename')}）—— 这是公开仓库，删一次提交不够",
                )
    return Check("密钥", True, "没在 diff 里看到 token / 私钥")


def check_conflict_markers(files: list[dict]) -> Check:
    hits = []
    for f in files:
        if CONFLICT_MARKER.search(f.get("patch") or ""):
            hits.append(f.get("filename", "?"))
    if hits:
        return Check(
            "冲突标记",
            False,
            "文件里还留着 " + "、".join(hits),
            "把 <<<<<<< 和 >>>>>>> 那几行清掉再提交",
        )
    return Check("冲突标记", True, "没有残留的冲突标记")


def check_behind(compare: dict) -> Check:
    """main 在分支之后又走了多少。/ How far main has moved past the branch."""
    behind = compare.get("behind_by") or 0
    if behind:
        return Check(
            "基准",
            False,
            f"main 比这个分支多 {behind} 个提交",
            "main 已经往前走了，你这个分支看不到那些改动。\n"
            "    HTTP 的做法：把 fork 的 main 对齐到上游最新，从那儿重新起分支，\n"
            "    再把你改的那几个文件重新 PUT 一遍（#12 就是这么救回来的）",
            fatal=False,
        )
    return Check("基准", True, "分支在 main 之上")


def check_mergeable(pr: dict) -> Check:
    """开 PR 之后才有的判据。/ Only available once the PR exists."""
    # 已经合了或者关了的，mergeable_state 就没有意义了。
    # For a merged or closed PR, mergeable_state means nothing.
    if pr.get("merged") or pr.get("merged_at"):
        return Check("能不能合", True, "已经合并了")
    if pr.get("state") == "closed":
        return Check("能不能合", True, "已经关闭，没合")

    state = pr.get("mergeable_state")
    if state == "clean":
        return Check("能不能合", True, "clean")
    if state in ("dirty", "unknown"):
        if state == "unknown":
            return Check("能不能合", False, "GitHub 还在算（unknown）", "几秒后再跑一次", fatal=False)
        return Check(
            "能不能合",
            False,
            "dirty —— 和 main 有冲突",
            "别等机器人。它是会重试五次然后放弃，只在日志里留一行 warning。\n"
            "    做法：把 fork 的 main 对齐到上游最新，从那儿重新起分支，\n"
            "    只改你要改的文件。旧分支不用管它。",
        )
    return Check("能不能合", True, state or "?")


def format_report(report: Report) -> tuple[str, int]:
    lines = []
    for check in report.checks:
        if check.ok:
            mark = "✔"
        elif check.fatal:
            mark = "✘"
        else:
            mark = "!"
        lines.append(f"  {mark} {check.name:<12} {check.detail}")
        if not check.ok and check.fix:
            for line in check.fix.splitlines():
                lines.append(f"      {line}")

    lines.append("")
    if report.blocked:
        lines.append("先别开 PR —— 上面红的那几条，开了就可能是 #12 的下场。")
        lines.append("Do not open the PR yet.")
        return "\n".join(lines), 1

    if report.warnings:
        lines.append(f"可以开，但有 {len(report.warnings)} 条提醒。")
        return "\n".join(lines), 0

    lines.append("可以开。/ Clear to open.")
    return "\n".join(lines), 0


# --------------------------------------------------------------------------
# 串起来 / wiring
# --------------------------------------------------------------------------


def run(args: argparse.Namespace, gh: GitHub) -> Report:
    """跑一遍检查。网络挂了会抛 NetworkError，交给 main 报。

    / Run the checks. Raises NetworkError; main reports it.

    不把网络错误塞进「检查不通过」里 —— 那会让人去修一个不存在的问题。
    / A network failure is not a failed check; folding it in makes people fix
    something that isn't broken.
    """
    report = Report()

    if args.pr:
        pr = gh.get(f"/repos/{args.upstream}/pulls/{args.pr}")
        if not isinstance(pr, dict) or "number" not in pr:
            report.add(Check("PR", False, f"读不到 #{args.pr}"))
            return report
        report.add(check_branch_name(pr.get("head", {}).get("ref", "")))
        report.add(check_mergeable(pr))
        return report

    branch = args.branch
    if not branch:
        report.add(Check("分支", False, "没给 --branch"))
        return report

    report.add(check_branch_name(branch))

    # 跨 fork 的 compare 是三段冒号分隔：owner:repo:branch。
    # 写成 owner/repo:branch 会 404 —— 只有两段。
    # Cross-fork compare takes three colon-separated parts: owner:repo:branch.
    # "owner/repo:branch" — two parts — is a 404.
    owner, _, repo_name = args.fork.partition("/")
    head = f"{owner}:{repo_name}:{branch}"
    compare = gh.get(f"/repos/{args.upstream}/compare/main...{head}")
    if not isinstance(compare, dict) or "status" not in compare:
        report.add(
            Check(
                "对比",
                False,
                f"compare 失败 —— 分支 {branch} 推上去了吗？",
                f"确认 https://github.com/{args.fork}/tree/{branch} 打得开",
            )
        )
        return report

    files = compare.get("files") or []
    report.add(check_behind(compare))

    # 内容相等 = 已经合过了。用 tree sha，不用 commit sha。
    # Equal content = already merged. Compare tree SHAs, not commit SHAs.
    base_tree = (compare.get("base_commit") or {}).get("commit", {}).get("tree", {}).get("sha")
    head_tree = gh.get(f"/repos/{args.fork}/commits/{branch}")
    head_tree_sha = None
    if isinstance(head_tree, dict):
        head_tree_sha = head_tree.get("commit", {}).get("tree", {}).get("sha")
    report.add(check_same_tree(base_tree or "", head_tree_sha or ""))

    report.add(check_protected([f.get("filename", "") for f in files]))
    report.add(check_secrets(files))
    report.add(check_conflict_markers(files))

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="开 PR 之前的自检（只用 HTTP）/ pre-PR checks over HTTP only"
    )
    parser.add_argument("--upstream", default="YKLovePython/only-ai")
    parser.add_argument("--fork", default=None, help="默认 ziy174/only-ai")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--pr", type=int, default=None, help="已有 PR 的编号")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("需要 GITHUB_TOKEN。/ GITHUB_TOKEN is required.", file=sys.stderr)
        print("  export GITHUB_TOKEN=ghp_xxx", file=sys.stderr)
        return 2

    if not args.fork:
        # 默认是「我」的 fork：拿 token 自己的登录名。
        # Default to my own fork: ask the token who it is.
        me = GitHub(token).get("/user")
        login = me.get("login") if isinstance(me, dict) else None
        if not login:
            print("读不到 token 的登录名，用 --fork 指定。", file=sys.stderr)
            return 2
        args.fork = f"{login}/{args.upstream.split('/')[-1]}"

    if "/" not in args.fork:
        print(f"--fork 要写成 owner/repo，收到 {args.fork!r}", file=sys.stderr)
        return 2

    gh = GitHub(token)
    print(f"自检（HTTP）：{args.fork}:{args.branch or 'PR #' + str(args.pr)} → {args.upstream}/main\n")
    try:
        report = run(args, gh)
    except NetworkError as exc:
        # 连不上 ≠ 检查没过。分开说，退出码也分开。
        # Not the same thing; the exit code says so too.
        print("连不上 GitHub，这次没做成检查。", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print(file=sys.stderr)
        print("这不是你的分支有问题 —— 是网络。过一会儿再跑一次。", file=sys.stderr)
        print("This is the network, not your branch. Try again later.", file=sys.stderr)
        return 3
    text, code = format_report(report)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())