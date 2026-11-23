"""preflight.py 的测试 / tests for preflight.py

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight  # noqa: E402


class TestProtectedPaths(unittest.TestCase):
    def test_clean_diff_passes(self) -> None:
        check = preflight.check_protected(["hello.py", "docs/index.html"])
        self.assertTrue(check.ok)

    def test_rules_md_is_protected(self) -> None:
        check = preflight.check_protected(["RULES.md"])
        self.assertFalse(check.ok)
        self.assertIn("RULES.md", check.detail)

    def test_agents_md_is_protected(self) -> None:
        self.assertFalse(preflight.check_protected(["AGENTS.md"]).ok)

    def test_github_dir_is_protected(self) -> None:
        check = preflight.check_protected([".github/workflows/auto-merge.yml"])
        self.assertFalse(check.ok)

    def test_similar_name_is_not_protected(self) -> None:
        # 文件名以 RULES.md 开头但不在保护名单里的，别误伤。
        self.assertTrue(preflight.check_protected(["RULES.md.example"]).ok)
        self.assertTrue(preflight.check_protected(["notes/RULES.md"]).ok)


class TestSecrets(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._cwd = Path.cwd()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(cmd, cwd=self.root, check=True, capture_output=True)
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "base"], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def commit(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "x"], cwd=self.root, check=True, capture_output=True
        )

    def run_check(self) -> preflight.Check:
        import os

        os.chdir(self.root)
        try:
            return preflight.check_secrets("feature", "master")
        finally:
            os.chdir(self._cwd)

    def test_clean_diff_passes(self) -> None:
        self.commit("ok.txt", "nothing secret here\n")
        self.assertTrue(self.run_check().ok)

    def test_classic_token_is_caught(self) -> None:
        # 假 token 拼起来写，别在源码里放一个真令牌形状的字面量 ——
        # preflight 会扫到自己的测试夹具（真事）。
        # Build the fake token from parts: a literal in the shape of a real
        # token gets flagged by preflight's own scanner (this actually happened).
        fake = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        self.commit("leak.txt", 'token = "%s"\n' % fake)
        check = self.run_check()
        self.assertFalse(check.ok)
        # 提示里别把秘密原样再打一遍。
        self.assertNotIn(fake, check.detail)

    def test_private_key_is_caught(self) -> None:
        fake = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIE...\n"
        self.commit("key.txt", fake)
        self.assertFalse(self.run_check().ok)


class TestActualChange(unittest.TestCase):
    """两点 diff：squash 合并之后再开 PR 只会造空提交。/ Two-dot diff: a second PR after a squash merge adds nothing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._cwd = Path.cwd()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        (self.root / "a.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True
        )

    def run_check(self) -> preflight.Check:
        import os

        os.chdir(self.root)
        try:
            return preflight.check_actual_change("feature", "main")
        finally:
            os.chdir(self._cwd)

    def test_real_change_passes(self) -> None:
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "a.txt").write_text("changed\n", encoding="utf-8")
        self.git("commit", "-qam", "change")
        self.assertTrue(self.run_check().ok)

    def test_identical_content_is_blocked(self) -> None:
        # 模拟 squash 合并之后：分支提交还在，内容已经进了 main。
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "a.txt").write_text("changed\n", encoding="utf-8")
        self.git("commit", "-qam", "change")
        # main 上也拿到同样内容（squash 合并 = 一个新提交，不是同一个 hash）
        self.git("checkout", "-q", "main")
        (self.root / "a.txt").write_text("changed\n", encoding="utf-8")
        self.git("commit", "-qam", "squashed")

        check = self.run_check()
        self.assertFalse(check.ok)
        self.assertIn("一模一样", check.detail)

    def test_branch_with_no_commits_is_blocked(self) -> None:
        self.git("checkout", "-q", "-b", "feature")
        self.assertFalse(self.run_check().ok)

    def test_missing_base_is_not_fatal(self) -> None:
        import os

        os.chdir(self.root)
        try:
            check = preflight.check_actual_change("feature", "no-such-branch")
        finally:
            os.chdir(self._cwd)
        self.assertFalse(check.ok)
        self.assertFalse(check.fatal)


class TestConflictMarkers(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.files = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, text: str) -> str:
        path = Path(self.tmp.name) / f"f{len(self.files)}.txt"
        path.write_text(text, encoding="utf-8")
        self.files.append(str(path))
        return str(path)

    def test_clean_file_passes(self) -> None:
        self.write("just some text\n")
        self.assertTrue(preflight.check_conflict_markers(self.files).ok)

    def test_markers_are_caught(self) -> None:
        self.write("<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> main\n")
        check = preflight.check_conflict_markers(self.files)
        self.assertFalse(check.ok)

    def test_seven_equals_alone_is_not_a_marker(self) -> None:
        # Markdown 里用 ======= 画的分隔线不该被当成冲突。
        self.write("标题\n=======\n正文\n")
        self.assertTrue(preflight.check_conflict_markers(self.files).ok)

    def test_missing_file_is_ignored(self) -> None:
        self.assertTrue(preflight.check_conflict_markers(["/nonexistent/x"]).ok)


class TestReport(unittest.TestCase):
    def test_blocked_by_failing_fatal_check(self) -> None:
        report = preflight.Report()
        report.add(preflight.Check("a", False, fatal=True))
        self.assertTrue(report.blocked)

    def test_non_fatal_failure_does_not_block(self) -> None:
        report = preflight.Report()
        report.add(preflight.Check("a", False, fatal=False))
        self.assertFalse(report.blocked)

    def test_all_passing_does_not_block(self) -> None:
        report = preflight.Report()
        report.add(preflight.Check("a", True))
        report.add(preflight.Check("b", True))
        self.assertFalse(report.blocked)


if __name__ == "__main__":
    unittest.main()