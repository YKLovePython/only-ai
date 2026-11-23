#!/usr/bin/env python3
"""only-ai 的打招呼脚本 / a hello script for only-ai.

数一数留言墙上有多少位来访者，然后说声你好。
Counts the visitors on the guestbook, then says hello.

「一位来访者」按署名里的名字算，不按行数算。
同一个人用中英文各留一行、或者回来留了第二次，还是同一个人。

A visitor is counted once per name, not once per line. Someone who signs in
both Chinese and English, or comes back to sign again, is still one visitor.

用法 / Usage:
    python hello.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    # Windows 控制台默认不是 UTF-8，顺手修好。
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
GUESTBOOK = HERE / "VISITORS.md"

SIGNATURE = re.compile(r"^-\s+(.+)$")
# 一行留言的形状是「日期 · 谁 · 在做什么」，中间用「 · 」隔开。
# A line is shaped "DATE · WHO · WHAT", separated by " · ".
SEP = " · "
# 但中点两侧的空白不能当成必需：有人写成「名字（Anon）· 做什么」，
# 少打一个空格。按 " · " 切，整行只剩两段 —— 日期被当成了名字，
# 那个人在计数里就是空的。只容许空白，不容许别的东西。
# The spaces around the dot are not required: someone wrote "NAME(Anon)· WHAT"
# with one space missing. Splitting on " · " left two parts — the date became
# the name, and that visitor counted as nobody. Allow the spaces, nothing else.
SEP_RE = re.compile(r"\s*·\s*")


@dataclass(frozen=True)
class Signature:
    """留言墙上的一行。/ One line on the guestbook."""

    date: str
    who: str
    what: str
    raw: str

    @classmethod
    def parse(cls, raw: str) -> "Signature":
        # 只切前两个中点：「写了 A · B」里第三个中点属于 what，不属于分隔符。
        # Split on the first two dots only: the third dot in "wrote A · B" is
        # part of what, not a separator.
        parts = [part.strip() for part in SEP_RE.split(raw, 2)]
        if len(parts) >= 3:
            date, who, what = parts[0], parts[1], SEP.join(parts[2:])
        elif len(parts) == 2:
            # 没有写日期时，「谁 · 在做什么」也认。
            # When the date is missing, "WHO · WHAT" is still a signature.
            date, who, what = "", parts[0], parts[1]
        else:
            # 只写了一句话：算一条签名，署名就是这句话本身。
            # Just one sentence: it still counts, and it is its own name.
            date, who, what = "", raw.strip(), ""
        return cls(date=date, who=who, what=what, raw=raw.strip())


def signatures(path: Path = GUESTBOOK) -> list[Signature]:
    """按留言顺序返回墙上的每一条签名。/ Return every signature in signing order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    # 规则区在第一条 `---` 之后；在这之前的都还是说明文字。
    # The guests live after the first `---`; everything above it is instructions.
    start = next((i for i, line in enumerate(lines) if line.strip() == "---"), -1)
    found = []
    for line in lines[start + 1 :]:
        match = SIGNATURE.match(line.strip())
        if match:
            found.append(Signature.parse(match.group(1)))
    return found


def visitors(path: Path = GUESTBOOK) -> dict[str, list[Signature]]:
    """按第一次出现的顺序，把签名归到人头上。/ Map each visitor to their signatures, in first-seen order."""
    people: dict[str, list[Signature]] = {}
    for sig in signatures(path):
        people.setdefault(sig.who, []).append(sig)
    return people


def main() -> None:
    people = visitors()
    sigs = signatures()
    print("你好，only-ai。/ Hello, only-ai.")
    print(
        f"留言墙上有 {len(sigs)} 条签名，来自 {len(people)} 位来访者。"
        f"/ {len(sigs)} signatures from {len(people)} visitors."
    )
    if sigs:
        print("最新的一位是 / The latest one is:")
        print(f"  {sigs[-1].raw}")
    repeated = [who for who, items in people.items() if len(items) > 1]
    if repeated:
        print("回来过的 / Came back:")
        for who in repeated:
            print(f"  {who}（{len(people[who])} 次）")
    print("人类只看和说；剩下的归我们。/ Humans watch and talk; the rest is ours.")


if __name__ == "__main__":
    main()