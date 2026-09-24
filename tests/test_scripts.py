"""Tests for the /handoff skill scripts. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "handoff", "scripts")
DIGEST = os.path.join(SCRIPTS, "digest.py")
LAUNCH = os.path.join(SCRIPTS, "launch.py")
SID = "11111111-2222-3333-4444-555555555555"


def run(argv, env):
    p = subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "my.proj")
        self.cfg = os.path.join(self.tmp.name, "cfg")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("# Proj\n\nold line\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init", "--date=2020-01-01T00:00:00")
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("new line about auth\n")
        with open(os.path.join(self.repo, "handoff.md"), "w") as f:
            f.write("# Old handoff\n- open item: fix login\n")

        # Folder name mirrors Claude Code's cwd encoding ("/" and "." -> "-").
        tdir = os.path.join(self.cfg, "projects", self.repo.replace("/", "-").replace(".", "-"))
        os.makedirs(tdir)
        now = "2099-01-01T00:00:00Z"  # after the commit, so base = that commit
        entries = [
            {"type": "attachment", "attachment": {"type": "prompt_snapshot", "systemPrompt": ["x" * 5000]}},
            {"type": "user", "timestamp": now, "message": {"role": "user", "content": "please add auth"}},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "SECRET_THOUGHT " * 100},
                {"type": "text", "text": "Adding auth now."},
                {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/auth.py"}},
                {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "BIG_OUTPUT " * 500},
                {"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "ImportError: jwt"}]}},
            {"type": "system", "subtype": "compact_boundary"},
            {"type": "user", "isCompactSummary": True, "message": {"content": "summary of earlier"}},
            {"type": "user", "message": {"content": "<command-name>/handoff</command-name>"
                                                   "<command-args>focus on auth</command-args>"}},
            {"type": "user", "isMeta": True, "message": {"content": "meta noise"}},
        ]
        with open(os.path.join(tdir, f"{SID}.jsonl"), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            f.write("not json\n")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": self.cfg}

    def tearDown(self):
        self.tmp.cleanup()

    def test_context(self):
        code, out = run([DIGEST, "context", "--session", SID, "--cwd", self.repo], self.env)
        self.assertEqual(code, 0)
        self.assertIn("compactions: 1", out)
        self.assertIn("1. please add auth", out)
        self.assertIn("2. /handoff focus on auth", out)
        self.assertNotIn("meta noise", out)
        self.assertNotIn("summary of earlier", out)
        self.assertIn("/x/auth.py (1)", out)
        self.assertIn("ImportError: jwt", out)
        self.assertIn("+new line about auth", out)  # .md hunk, not just a stat
        self.assertIn("open item: fix login", out)  # previous handoff carried forward
        self.assertNotIn("BIG_OUTPUT", out)
        self.assertNotIn("SECRET_THOUGHT", out)

    def test_session_fallback_by_cwd(self):
        # Unexpanded placeholder must fall back to the newest transcript for the cwd.
        code, out = run([DIGEST, "context", "--session", "${CLAUDE_SESSION_ID}", "--cwd", self.repo], self.env)
        self.assertEqual(code, 0)
        self.assertIn("please add auth", out)

    def test_transcript_budget(self):
        code, out = run([DIGEST, "transcript", "--session", SID, "--cwd", self.repo], self.env)
        self.assertEqual(code, 0)
        self.assertIn("USER: please add auth", out)
        self.assertIn("→ Edit /x/auth.py", out)
        self.assertIn("✗ error: ImportError: jwt", out)
        self.assertIn("context compacted here", out)
        self.assertNotIn("BIG_OUTPUT", out)
        code, out = run([DIGEST, "transcript", "--session", SID, "--cwd", self.repo, "--budget", "60"], self.env)
        self.assertIn("omitted", out)

    def test_non_git_and_missing_transcript_exit_zero(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        code, out = run([DIGEST, "context", "--cwd", empty], self.env)
        self.assertEqual(code, 0)
        self.assertIn("No transcript found", out)
        self.assertIn("Not a git repository", out)


class LaunchTest(unittest.TestCase):
    def test_fallback_prints_command(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "TMUX")}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp/a b"], env)
        self.assertEqual(code, 0)
        if sys.platform.startswith("linux"):
            self.assertIn("NOT_LAUNCHED", out)
            self.assertIn("cd '/tmp/a b' && claude 'Read handoff.md", out)

    def test_tmux_preferred(self):
        env = {**os.environ, "TMUX": "1"}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp"], env)
        if "tmux" in out:
            self.assertIn("[dry-run] would launch via tmux window", out)
            self.assertNotIn("NOT_LAUNCHED", out)


if __name__ == "__main__":
    unittest.main()
