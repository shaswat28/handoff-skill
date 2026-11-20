"""Regression tests for handoff context and launch."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_scripts import DIGEST, LAUNCH, SCRIPTS, SID, git

sys.path.insert(0, SCRIPTS)
import digest


def message(role, content, **fields):
    return {"type": role, "message": {"content": content}, **fields}


class DigestExtraTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cwd = Path(temp.name)
        self.cfg = self.cwd / "cfg"
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.cfg),
                    "PYTHONIOENCODING": "utf-8"}

    def run_script(self, script, *args, cwd=None):
        result = subprocess.run(
            [sys.executable, script, *args, "--cwd", str(cwd or self.cwd)],
            capture_output=True, env=self.env,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8", "replace")

    def write_transcript(self, *entries):
        path = self.cfg / "projects" / "fixture" / f"{SID}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")

    def init_repo(self):
        git(self.cwd, "init", "-q", "-b", "main")
        doc = self.cwd / "README.md"
        doc.write_bytes(b"original\n")
        git(self.cwd, "add", "README.md")
        git(self.cwd, "commit", "-qm", "initial")
        return doc

    def test_only_human_origins_are_prompts(self):
        self.assertIsNone(digest.human_prompt(message(
            "user", "injected", origin={"kind": "task-notification"})))
        self.assertEqual(digest.human_prompt(message(
            "user", "actual", origin={"kind": "human"})), "actual")
        self.assertEqual(digest.human_prompt(message("user", "legacy")), "legacy")

    def test_noise_prefixes_in_strings_and_mixed_blocks(self):
        for prefix in ("<task-notification>", "<bash-input>", "<bash-stdout>",
                       "<bash-stderr>", "<ci-monitor-event>"):
            with self.subTest(prefix=prefix):
                noise = prefix + "injected"
                self.assertIsNone(digest.human_prompt(message("user", noise)))
                self.assertEqual(digest.human_prompt(message("user", [
                    {"type": "text", "text": noise},
                    {"type": "text", "text": "actual"},
                ])), "actual")

    def test_non_git_docs_carry_forward_legacy_handoff(self):
        (self.cwd / "handoff.md").write_text("open item\n" + "line\n" * 79 + "hidden\n",
                                           encoding="utf-8")
        with redirect_stdout(io.StringIO()) as out:
            digest.print_docs(self.cwd, None)
        previous = out.getvalue().partition("### Previous handoff")[2]
        self.assertIn("open item", previous)
        self.assertIn("(1 more lines)", previous)
        self.assertNotIn("hidden", previous)

    def test_markdown_hunk_from_repo_root_when_cwd_is_subdirectory(self):
        doc = self.init_repo()
        doc.write_bytes(b"root edit\n")
        subdir = self.cwd / "nested"
        subdir.mkdir()
        out = self.run_script(DIGEST, "context", cwd=subdir)
        self.assertIn("#### README.md", out)
        self.assertIn("+root edit", out)

    def test_nested_cwd_lists_repo_root_key_docs_and_untracked_relative_paths(self):
        self.init_repo()
        subdir = self.cwd / "nested"
        subdir.mkdir()
        (self.cwd / "root.md").write_text("root doc\n")
        (subdir / "local.txt").write_text("x")
        out = self.run_script(DIGEST, "context", cwd=subdir)
        self.assertIn("- ../README.md:", out)
        self.assertIn("local.txt", out)
        self.assertNotIn("../local.txt", out)

    def test_markdown_changes_excludes_handoff_directory(self):
        self.init_repo()
        (self.cwd / ".handoff").mkdir()
        (self.cwd / ".handoff" / "old.md").write_text("private state")
        with redirect_stdout(io.StringIO()) as out:
            digest.print_markdown_changes(str(self.cwd), "HEAD")
        self.assertNotIn("old.md", out.getvalue())

    def test_git_decodes_utf8_and_replaces_invalid_bytes(self):
        doc = self.init_repo()
        doc.write_bytes("café".encode("utf-8") + b"\xff\n")
        out = digest.git(["diff", "--text", "HEAD", "--", "README.md"], self.cwd)
        self.assertIn("+café\ufffd", out)

    def test_digest_prints_arrows_and_errors_on_cp1252_pipe(self):
        self.env["PYTHONIOENCODING"] = "cp1252:strict"
        self.write_transcript(
            message("assistant", [{"type": "tool_use", "id": "1", "name": "Read",
                                   "input": {"file_path": "sample"}}]),
            message("user", [{"type": "tool_result", "tool_use_id": "1",
                              "is_error": True, "content": "missing"}]),
        )
        out = self.run_script(DIGEST, "transcript", "--session", SID)
        self.assertIn("→ Read sample", out)
        self.assertIn("✗ error: missing", out)
        out = self.run_script(DIGEST, "context", "--session", SID)
        self.assertIn("→ missing", out)

    def test_launch_prints_utf8_on_cp1252_pipe(self):
        self.env["PYTHONIOENCODING"] = "cp1252:strict"
        out = self.run_script(LAUNCH, "--dry-run", "--mode", "paste", "--prompt", "Read → ✗")
        self.assertIn("Read → ✗", out)

    def test_invalid_arguments_exit_zero(self):
        for script, args in ((DIGEST, ["context"]), (LAUNCH, [])):
            with self.subTest(script=script):
                self.run_script(script, *args, "--invalid-option")

    def context_at_fixed_time(self, *args):
        with mock.patch.object(digest, "datetime", wraps=datetime) as clock, \
                mock.patch.dict(os.environ, self.env), redirect_stdout(io.StringIO()) as out:
            clock.now.return_value = datetime(2026, 11, 20, 14, 5)
            with mock.patch.object(sys, "argv", [DIGEST, "context", "--cwd", str(self.cwd), *args]):
                with self.assertRaises(SystemExit) as result:
                    digest.main()
                self.assertEqual(result.exception.code, 0)
        return out.getvalue()

    def test_context_creates_handoff_directory_and_prints_session_target(self):
        out = self.context_at_fixed_time("--session", SID)
        self.assertIn("Handoff target: .handoff/20261120-1405-11111111.md", out)
        self.assertEqual((self.cwd / ".handoff" / ".gitignore").read_bytes(), b"*\n")
        self.assertFalse((self.cwd / ".handoff" / "20261120-1405-11111111.md").exists())
        out = self.context_at_fixed_time("--session", "22222222-3333")
        self.assertIn("Handoff target: .handoff/20261120-1405-22222222.md", out)

    def test_missing_and_unexpanded_session_use_fallback_name(self):
        for args in ((), ("--session", "${CLAUDE_SESSION_ID}")):
            with self.subTest(args=args):
                self.assertIn("Handoff target: .handoff/20261120-1405-session.md",
                              self.context_at_fixed_time(*args))

    def test_blocked_handoff_directory_does_not_abort_digest(self):
        (self.cwd / ".handoff").write_bytes(b"existing file")
        (self.cwd / "handoff.md").write_bytes(b"carry this forward\n")
        out = self.context_at_fixed_time("--session", SID)
        self.assertIn("Not a git repository", out)
        self.assertIn("carry this forward", out)
        self.assertIn("Handoff target:", out)

    def test_missing_project_directory_is_not_created(self):
        missing = self.cwd / "missing"
        self.run_script(DIGEST, "context", cwd=missing)
        self.assertFalse(missing.exists())

    def test_previous_handoff_uses_newest_by_mtime_except_target(self):
        directory = self.cwd / ".handoff"
        directory.mkdir()
        for name, body, mtime in (
            ("20261120-1405-11111111.md", "exclude current", 300),
            ("20261118-1405-22222222.md", "carry this item", 200),
            ("20261119-1405-33333333.md", "skip older", 100),
        ):
            path = directory / name
            path.write_text(body, encoding="utf-8")
            os.utime(path, (mtime, mtime))
        (self.cwd / "handoff.md").write_bytes(b"skip legacy\n")
        out = self.context_at_fixed_time("--session", SID)
        self.assertIn("exclude current", out)
        for excluded in ("carry this item", "skip older", "skip legacy"):
            self.assertNotIn(excluded, out)

    def test_launch_file_flows_to_paste_and_terminal_prompts(self):
        path = ".handoff/20261120-1405-11111111.md"
        for mode in ("paste", "terminal"):
            with self.subTest(mode=mode):
                out = self.run_script(LAUNCH, "--dry-run", "--mode", mode, "--file", path)
                self.assertIn(f"Read {path} in this folder", out)

    def test_last_activity_is_capped_and_follows_last_compaction(self):
        boundary = {"type": "system", "subtype": "compact_boundary"}
        summary = message("user", "compacted summary", isCompactSummary=True)
        old = message("assistant", [
            {"type": "text", "text": "before last compaction"},
            {"type": "tool_use", "id": "old", "name": "OldTool"},
        ])
        recent = message("assistant", [
            *({"type": "text", "text": line} for line in
              ("older text block", "recent one", "recent two", "x" * 400)),
            *({"type": "tool_use", "id": str(i), "name": f"Tool-{i:02}"}
              for i in range(12)),
            {"type": "thinking", "thinking": "hidden thought"},
        ])
        for markers in ((boundary, summary), (summary,), ()):
            with self.subTest(markers=markers):
                self.write_transcript(*markers, old, *markers, recent)
                out = self.run_script(DIGEST, "context", "--session", SID)
                _, heading, tail = out.partition("### Last activity\n")
                if not markers:
                    self.assertEqual(heading, "")
                    continue
                self.assertTrue(heading)
                activity = tail.split("\n### ", 1)[0]
                for text in ("recent one", "recent two", "Tool-02", "Tool-11"):
                    self.assertIn(text, activity)
                self.assertEqual(activity.count("Tool-"), 10)
                self.assertIn("x" * 299 + "…", activity)
                for excluded in ("before last compaction", "OldTool", "older text block",
                                 "Tool-00", "Tool-01", "hidden thought", "x" * 300):
                    self.assertNotIn(excluded, activity)

    def test_git_lists_only_untracked_paths_up_to_limit(self):
        doc = self.init_repo()
        doc.write_bytes(b"tracked edit\n")
        folder = self.cwd / "new files"
        folder.mkdir()
        for i in range(33):
            (folder / f"file-{i:02}.txt").touch()
        out = self.run_script(DIGEST, "context")
        git_section = out.split("### Git\n", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(git_section.count("new files/file-"), 30)
        self.assertIn("new files/file-29.txt", git_section)
        self.assertIn("+3 more", git_section)
        self.assertNotIn("README.md", git_section)
        self.assertEqual(out.count("new files/file-00.txt"), 1)

    def test_git_lists_fifteen_unpushed_subjects_only_with_upstream(self):
        self.init_repo()
        git(self.cwd, "branch", "base")
        git(self.cwd, "branch", "--set-upstream-to=base", "main")
        for i in range(17):
            git(self.cwd, "commit", "--allow-empty", "-qm", f"subject {i:02}")
        out = self.run_script(DIGEST, "context")
        git_section = out.split("### Git\n", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(git_section.count("subject "), 15)
        self.assertIn("subject 16", git_section)
        self.assertIn("subject 02", git_section)
        self.assertNotIn("subject 01", git_section)
        git(self.cwd, "branch", "--unset-upstream", "main")
        out = self.run_script(DIGEST, "context")
        git_section = out.split("### Git\n", 1)[1].split("\n### ", 1)[0]
        self.assertNotIn("Unpushed commit", git_section)
        self.assertNotIn("subject ", git_section)

    def test_same_minute_handoff_uses_first_free_name(self):
        directory = self.cwd / ".handoff"
        directory.mkdir()
        (directory / "20261120-1405-session.md").touch()
        out = self.context_at_fixed_time()
        self.assertIn("Handoff target: .handoff/20261120-1405-session-2.md", out)
