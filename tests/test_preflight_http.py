"""preflight_http.py 的测试 / tests for preflight_http.py

只测纯逻辑 —— 不联网，不需要 token。
Only the pure logic: no network, no token.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight_http as ph  # noqa: E402


class TestProtected(unittest.TestCase):
    def test_github_dir(self) -> None:
        self.assertTrue(ph.is_protected(".github/workflows/auto-merge.yml"))

    def test_rules_and_agents(self) -> None:
        self.assertTrue(ph.is_protected("RULES.md"))
        self.assertTrue(ph.is_protected("AGENTS.md"))

    def test_lookalikes_are_not_protected(self) -> None:
        # 前缀像但不是的，别误伤。/ Prefix lookalikes must not be flagged.
        self.assertFalse(ph.is_protected("RULES.md.example"))
        self.assertFalse(ph.is_protected("notes/AGENTS.md"))
        self.assertFalse(ph.is_protected("hello.py"))

    def test_check_protected_lists_hits(self) -> None:
        check = ph.check_protected(["hello.py", "RULES.md"])
        self.assertFalse(check.ok)
        self.assertIn("RULES.md", check.detail)

    def test_check_protected_clean(self) -> None:
        self.assertTrue(ph.check_protected(["hello.py", "docs/feed.js"]).ok)


class TestBranch(unittest.TestCase):
    def test_main_is_rejected(self) -> None:
        self.assertFalse(ph.check_branch_name("main").ok)
        self.assertFalse(ph.check_branch_name("master").ok)

    def test_topic_branch_is_fine(self) -> None:
        self.assertTrue(ph.check_branch_name("fix-something").ok)


class TestSameTree(unittest.TestCase):
    def test_different_trees_pass(self) -> None:
        self.assertTrue(ph.check_same_tree("aaa", "bbb").ok)

    def test_equal_trees_mean_already_merged(self) -> None:
        check = ph.check_same_tree("aaa", "aaa")
        self.assertFalse(check.ok)
        self.assertIn("已经合过", check.detail)

    def test_squash_merge_scenario(self) -> None:
        # squash 之后 commit sha 一定不同，内容却相同 —— 所以要比 tree。
        # After a squash the commit SHAs always differ while content does not,
        # which is exactly why the tree is the right thing to compare.
        commit_a, commit_b = "1111", "2222"
        self.assertNotEqual(commit_a, commit_b)
        self.assertFalse(ph.check_same_tree("same", "same").ok)

    def test_missing_tree_is_not_fatal(self) -> None:
        check = ph.check_same_tree("", "aaa")
        self.assertFalse(check.ok)
        self.assertFalse(check.fatal)


class TestSecrets(unittest.TestCase):
    def test_clean_patch(self) -> None:
        self.assertTrue(ph.check_secrets([{"filename": "a.py", "patch": "+print(1)"}]).ok)

    def test_classic_token_is_caught(self) -> None:
        fake = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        files = [{"filename": "leak.txt", "patch": '+token = "%s"' % fake}]
        check = ph.check_secrets(files)
        self.assertFalse(check.ok)
        # 别把秘密原样再打一遍。/ Never echo the secret back.
        self.assertNotIn(fake, check.detail)

    def test_private_key_is_caught(self) -> None:
        fake = "-----BEGIN " + "RSA PRIVATE KEY-----"
        self.assertFalse(ph.check_secrets([{"filename": "k", "patch": "+" + fake}]).ok)

    def test_missing_patch_is_ignored(self) -> None:
        # 大文件不返回 patch。/ Large files come back without a patch.
        self.assertTrue(ph.check_secrets([{"filename": "big.bin"}]).ok)


class TestConflictMarkers(unittest.TestCase):
    def test_clean_patch(self) -> None:
        self.assertTrue(ph.check_conflict_markers([{"filename": "a", "patch": "+hi"}]).ok)

    def test_markers_are_caught(self) -> None:
        files = [{"filename": "a", "patch": "+<<<<<<< HEAD\n+=======\n+>>>>>>> main\n"}]
        check = ph.check_conflict_markers(files)
        self.assertFalse(check.ok)
        self.assertIn("a", check.detail)

    def test_markdown_heading_underline_is_not_a_marker(self) -> None:
        # 七个等号在 Markdown 里是标题线，不是冲突。
        # Seven equals signs are a setext heading underline in Markdown.
        self.assertTrue(
            ph.check_conflict_markers([{"filename": "a.md", "patch": "+标题\n+=======\n"}]).ok
        )


class TestBehind(unittest.TestCase):
    def test_up_to_date_passes(self) -> None:
        self.assertTrue(ph.check_behind({"behind_by": 0}).ok)

    def test_behind_warns_but_does_not_block(self) -> None:
        check = ph.check_behind({"behind_by": 3})
        self.assertFalse(check.ok)
        self.assertFalse(check.fatal)


class TestMergeable(unittest.TestCase):
    def test_clean(self) -> None:
        self.assertTrue(ph.check_mergeable({"mergeable_state": "clean"}).ok)

    def test_dirty_blocks(self) -> None:
        check = ph.check_mergeable({"mergeable_state": "dirty"})
        self.assertFalse(check.ok)
        self.assertTrue(check.fatal)

    def test_unknown_only_warns(self) -> None:
        check = ph.check_mergeable({"mergeable_state": "unknown"})
        self.assertFalse(check.ok)
        self.assertFalse(check.fatal)

    def test_already_merged_is_not_a_problem(self) -> None:
        # 合过的 PR 的 mergeable_state 可能是 unknown，不该吓人。
        check = ph.check_mergeable({"merged": True, "mergeable_state": "unknown"})
        self.assertTrue(check.ok)

    def test_closed_without_merge(self) -> None:
        check = ph.check_mergeable({"state": "closed", "merged": False})
        self.assertTrue(check.ok)


class TestReport(unittest.TestCase):
    def test_blocked_by_fatal(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", False, fatal=True))
        self.assertTrue(r.blocked)
        self.assertEqual(r.warnings, [])

    def test_warning_does_not_block(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", False, fatal=False))
        self.assertFalse(r.blocked)
        self.assertEqual(len(r.warnings), 1)

    def test_format_clear(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", True, "fine"))
        text, code = ph.format_report(r)
        self.assertEqual(code, 0)
        self.assertIn("可以开", text)

    def test_format_blocked(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", False, "bad", fatal=True))
        text, code = ph.format_report(r)
        self.assertEqual(code, 1)
        self.assertIn("先别开 PR", text)

    def test_format_shows_fix(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", False, "bad", fix="这样修", fatal=True))
        text, _ = ph.format_report(r)
        self.assertIn("这样修", text)

    def test_warning_marker_is_not_the_block_marker(self) -> None:
        r = ph.Report()
        r.add(ph.Check("a", False, "meh", fatal=False))
        text, _ = ph.format_report(r)
        self.assertIn("!", text)
        self.assertNotIn("✘", text)


if __name__ == "__main__":
    unittest.main()