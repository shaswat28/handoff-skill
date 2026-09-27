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
HOOKS = os.path.join(SCRIPTS, "hooks.py")
HOOKS_INSTALL = os.path.join(SCRIPTS, "hooks_install.py")
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
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY", "TMUX", "CLAUDE_CODE_ENTRYPOINT")}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp/a b"], env)
        self.assertEqual(code, 0)
        if sys.platform.startswith("linux"):
            self.assertIn("NOT_LAUNCHED", out)
            self.assertIn("cd '/tmp/a b' && claude 'Read handoff.md", out)

    def test_tmux_preferred(self):
        env = {**os.environ, "TMUX": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp"], env)
        if "tmux" in out:
            self.assertIn("[dry-run] would launch via tmux window", out)
            self.assertNotIn("NOT_LAUNCHED", out)


class PasteModeTest(unittest.TestCase):
    def test_desktop_entrypoint_uses_paste_mode(self):
        env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "TMUX": "1"}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp"], env)
        self.assertEqual(code, 0)
        self.assertIn("PASTE_MODE", out)
        self.assertIn("Read handoff.md", out)
        self.assertNotIn("tmux", out)

    def test_terminal_mode_overrides_desktop(self):
        env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}
        code, out = run([LAUNCH, "--dry-run", "--mode", "terminal", "--cwd", "/tmp"], env)
        self.assertNotIn("PASTE_MODE", out)

    def test_cli_entrypoint_not_paste(self):
        env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "cli"}
        code, out = run([LAUNCH, "--dry-run", "--cwd", "/tmp"], env)
        self.assertNotIn("PASTE_MODE", out)


class LineEndingsTest(unittest.TestCase):
    def test_skill_files_are_lf_and_forced_lf(self):
        # CRLF (Git for Windows' default) breaks scripts/py and /handoff silently.
        with open(os.path.join(ROOT, ".gitattributes")) as f:
            self.assertIn("eol=lf", f.read())
        for dirpath, _, files in os.walk(os.path.join(ROOT, "skills")):
            for name in files:
                if name.endswith(".pyc"):
                    continue
                with open(os.path.join(dirpath, name), "rb") as f:
                    self.assertNotIn(b"\r\n", f.read(), name)


class MacCandidatesTest(unittest.TestCase):
    def test_macos_uses_osascript_with_escaped_prompt(self):
        sys.path.insert(0, SCRIPTS)
        import launch
        from unittest import mock
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        with mock.patch.object(launch.platform, "system", return_value="Darwin"), \
                mock.patch.dict(os.environ, {**env, "TERM_PROGRAM": "iTerm.app"}, clear=True):
            got = list(launch.candidates("/Users/me/my proj", 'say "hi" \\ bye'))
        self.assertEqual([label for label, _ in got], ["iTerm2", "Terminal.app"])
        script = got[1][1][2]
        self.assertTrue(script.startswith('tell application "Terminal" to do script "cd'))
        self.assertIn("'/Users/me/my proj'", script)
        self.assertIn('\\"hi\\"', script)  # quotes escaped for AppleScript
        self.assertIn("osascript", launch.RETURNS_QUICKLY)

    def test_failed_launcher_falls_back(self):
        # A launcher that exits non-zero must not be reported as LAUNCHED.
        sys.path.insert(0, SCRIPTS)
        import launch
        from unittest import mock
        with mock.patch.object(launch, "candidates", return_value=[("fake", ["tmux", "no-such-cmd"])]), \
                mock.patch.object(launch, "copy_to_clipboard", return_value=None), \
                mock.patch.object(sys, "argv", ["launch.py", "--mode", "terminal", "--cwd", "/tmp"]), \
                mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
            launch.main()
        self.assertIn("fake failed", out.getvalue())
        self.assertIn("NOT_LAUNCHED", out.getvalue())


class HooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": self.tmp.name}
        self.log = os.path.join(self.tmp.name, "chat.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, event, session="s1", tokens=None, extra=(), stdin=None):
        if tokens is not None:
            with open(self.log, "a") as f:
                f.write("x" * 100 + "\n")  # junk line, like a partial tail read
                f.write(json.dumps({"type": "assistant", "message": {"usage": {
                    "input_tokens": 1, "cache_read_input_tokens": tokens - 11,
                    "cache_creation_input_tokens": 5, "output_tokens": 5}}}) + "\n")
        payload = stdin if stdin is not None else json.dumps(
            {"session_id": session, "transcript_path": self.log, "trigger": "auto"})
        p = subprocess.run([sys.executable, HOOKS, event, *extra], input=payload,
                           capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout, p.stderr

    def test_two_warnings_each_once(self):
        args = ("--window", "1000", "--warn", "45,70")
        self.assertEqual(self.hook("prompt", tokens=300, extra=args)[1], "")
        code, out, _ = self.hook("prompt", tokens=500, extra=args)
        self.assertEqual(code, 0)
        self.assertIn("Cheapest point", json.loads(out)["systemMessage"])
        self.assertEqual(self.hook("prompt", tokens=600, extra=args)[1], "")
        msg = json.loads(self.hook("prompt", tokens=800, extra=args)[1])["systemMessage"]
        self.assertIn("slower and less precise", msg)
        self.assertIn("80% of context", msg)
        self.assertEqual(self.hook("prompt", tokens=900, extra=args)[1], "")

    def test_jump_past_both_shows_only_later_one(self):
        args = ("--window", "1000", "--warn", "45,70")
        out = self.hook("prompt", session="s2", tokens=900, extra=args)[1]
        self.assertIn("slower", out)
        self.assertEqual(self.hook("prompt", session="s2", tokens=950, extra=args)[1], "")
        # A different chat gets its own warnings.
        self.assertIn("slower", self.hook("prompt", session="s3", tokens=950, extra=args)[1])

    def test_precompact_postpones_once(self):
        code, _, err = self.hook("precompact")
        self.assertEqual(code, 2)
        self.assertIn("postponed once", err)
        self.assertEqual(self.hook("precompact")[0], 0)
        manual = json.dumps({"session_id": "m", "trigger": "manual"})
        self.assertEqual(self.hook("precompact", stdin=manual)[0], 0)

    def test_never_breaks_session(self):
        self.assertEqual(self.hook("prompt", stdin="not json")[0], 0)
        self.assertEqual(self.hook("prompt", extra=("--window", "abc"))[0], 0)
        missing = json.dumps({"session_id": "x", "transcript_path": "/nope.jsonl"})
        self.assertEqual(self.hook("prompt", stdin=missing), (0, "", ""))


class HooksInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = os.path.join(self.tmp.name, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"model": "opus", "hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "echo mine"}]}]}}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args):
        p = subprocess.run([sys.executable, HOOKS_INSTALL, *args, "--settings", self.settings],
                           capture_output=True, text=True)
        with open(self.settings) as f:
            return p.returncode, json.load(f)

    def test_install_is_idempotent_and_keeps_other_settings(self):
        self.run_install("install", "--window", "1000000")
        code, s = self.run_install("install", "--window", "1000000", "--warn", "40,65")
        self.assertEqual(code, 0)
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["hooks"]["Stop"][0]["hooks"][0]["command"], "echo mine")
        self.assertEqual(len(s["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(len(s["hooks"]["PreCompact"]), 1)
        self.assertEqual(s["hooks"]["PreCompact"][0]["matcher"], "auto")
        self.assertIn("--window 1000000 --warn 40,65", s["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])
        self.assertTrue(os.path.exists(self.settings + ".handoff-bak"))

    def test_no_compact_hold_and_uninstall(self):
        _, s = self.run_install("install", "--no-compact-hold")
        self.assertNotIn("PreCompact", s["hooks"])
        _, s = self.run_install("uninstall")
        self.assertEqual(s["hooks"], {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]})

    def test_rejects_bad_input_without_touching_file(self):
        with open(self.settings, "w") as f:
            f.write("{broken")
        p = subprocess.run([sys.executable, HOOKS_INSTALL, "install", "--settings", self.settings],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        with open(self.settings) as f:
            self.assertEqual(f.read(), "{broken")
        p = subprocess.run([sys.executable, HOOKS_INSTALL, "install", "--warn", "abc",
                            "--settings", self.settings], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
