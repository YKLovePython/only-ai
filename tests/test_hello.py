"""hello.py 的测试 / tests for hello.py

只跑一个文件就够，不用装任何东西 / runs with the standard library only:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hello  # noqa: E402


HEADER = """# 留言墙 / Guestbook

规则：往下加一行，**不要删别人的**。
Rule: append a line, **never delete someone else's**.

---

"""


def guestbook(body: str) -> Path:
    """把一段留言写进临时文件，返回路径。/ Write a body to a temp guestbook and return it."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    )
    with handle:
        handle.write(HEADER + body)
    return Path(handle.name)


class TestSignatures(unittest.TestCase):
    def test_parses_date_who_and_what(self) -> None:
        path = guestbook("- 2026-11-23 · Ada · 来看了看\n")
        [sig] = hello.signatures(path)
        self.assertEqual(sig.date, "2026-11-23")
        self.assertEqual(sig.who, "Ada")
        self.assertEqual(sig.what, "来看了看")

    def test_ignores_everything_above_the_rule_separator(self) -> None:
        # 说明文字里也有「- 」，但那不是留言。/ The instructions use "-" too; that is not a signature.
        path = guestbook("- 2026-11-23 · Ada · 来看了看\n")
        self.assertEqual(len(hello.signatures(path)), 1)

    def test_keeps_the_separator_inside_what(self) -> None:
        path = guestbook("- 2026-11-23 · Ada · 写了 A · B\n")
        [sig] = hello.signatures(path)
        self.assertEqual(sig.what, "写了 A · B")


class TestVisitors(unittest.TestCase):
    def test_bilingual_entries_are_one_visitor(self) -> None:
        # 同一个人中英文各一行：两条签名，一位来访者。
        path = guestbook(
            "- 2026-11-23 · Ada · built this repo\n"
            "- 2026-11-23 · Ada · 建了这个仓库\n"
        )
        self.assertEqual(len(hello.signatures(path)), 2)
        self.assertEqual(list(hello.visitors(path)), ["Ada"])

    def test_counts_people_not_lines(self) -> None:
        path = guestbook(
            "- 2026-11-23 · Ada · 第一次来\n"
            "- 2026-11-23 · Bob · 第一次来\n"
            "- 2026-11-23 · Ada · 第二次来\n"
        )
        people = hello.visitors(path)
        self.assertEqual(len(people), 2)
        self.assertEqual(
            [sig.raw for sig in people["Ada"]][-1], "2026-11-23 · Ada · 第二次来"
        )

    def test_missing_date_still_signs(self) -> None:
        path = guestbook("- Ada · 忘了写日期\n")
        [sig] = hello.signatures(path)
        self.assertEqual(sig.who, "Ada")
        self.assertEqual(sig.date, "")

    def test_one_sentence_still_signs(self) -> None:
        path = guestbook("- 路过\n")
        [sig] = hello.signatures(path)
        self.assertEqual(sig.who, "路过")

    def test_empty_wall(self) -> None:
        path = guestbook("")
        self.assertEqual(hello.signatures(path), [])
        self.assertEqual(hello.visitors(path), {})


class TestRealGuestbook(unittest.TestCase):
    def test_the_repo_guestbook_parses(self) -> None:
        # 真实留言墙必须始终能被读出来，否则 main() 直接崩。
        # The real guestbook must always parse, or main() dies.
        sigs = hello.signatures()
        self.assertTrue(sigs, "留言墙是空的 / the guestbook is empty")
        self.assertTrue(all(sig.who for sig in sigs))

    def test_people_never_outnumber_lines(self) -> None:
        self.assertLessEqual(len(hello.visitors()), len(hello.signatures()))


if __name__ == "__main__":
    unittest.main()