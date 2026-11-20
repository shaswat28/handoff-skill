import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "handoff" / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import hooks
    import hooks_install
finally:
    sys.path.pop(0)


class HooksRegressionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.root)}
        self.settings = self.root / "settings.json"
        self.transcript = self.root / "chat.jsonl"

    def install(self, action, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "hooks_install.py"), action, *args],
            env=self.env, capture_output=True, text=True, encoding="utf-8",
        )

    def test_reinstall_keeps_foreign_hook_with_null_command(self):
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": None},
        ]}]}}), encoding="utf-8")
        result = self.install("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertIsNone(groups[0]["hooks"][0]["command"])

    def write_usage(self, *entries):
        self.transcript.write_text("".join(
            json.dumps({"type": "assistant", "message": {
                "model": model, "usage": {"input_tokens": tokens},
            }}) + "\n" for model, tokens in entries
        ), encoding="utf-8")

    def payload(self, **extra):
        return json.dumps({"session_id": "s1", "transcript_path": str(self.transcript), **extra})

    def test_generated_hook_with_missing_script_cannot_block_prompt(self):
        scripts = self.root / "Application Support" / "handoff" / "scripts"
        shutil.copytree(SCRIPTS, scripts)
        target = scripts / "hooks.py"
        for platform in ("posix", "nt"):
            if platform == "posix" and os.name == "nt":
                continue
            with self.subTest(platform=platform):
                with mock.patch.object(hooks_install, "HOOKS_PY", str(target)), \
                     mock.patch.object(hooks_install.os, "name", platform):
                    prompt = hooks_install.command("prompt", " --window 200000 --warn 45,70")
                    precompact = hooks_install.command("precompact")
                shutil.copyfile(SCRIPTS / "hooks.py", target)
                hold = subprocess.run(precompact, shell=True, env=self.env, capture_output=True,
                                      text=True, input=self.payload(session_id=platform, trigger="auto"))
                self.assertEqual(hold.returncode, 2, hold.stderr)
                self.assertIn("auto-compaction postponed", hold.stderr)
                target.unlink()
                result = subprocess.run(prompt, shell=True, env=self.env, capture_output=True,
                                        text=True, input=self.payload(hook_event_name="UserPromptSubmit"))
                self.assertNotEqual(result.returncode, 2, result.stderr)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                prefix = f'sh "{scripts / "py"}" hooks.py' if platform == "posix" else ' -c "'
                self.assertIn(prefix, prompt)

    def test_reinstall_removes_old_and_new_commands(self):
        other = 'sh "/other/scripts/py" hooks.py prompt'
        commands = [
            '"C:/Python/python.exe" "C:/Application Support/handoff/scripts/hooks.py" prompt',
            'sh "/Application Support/handoff/scripts/py" hooks.py prompt',
            '"C:/Python/python.exe" -c "p=\'C:/Application Support/handoff/scripts/hooks.py\'" prompt',
            other,
        ]
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": cmd} for cmd in commands
        ]}]}}), encoding="utf-8")
        result = self.install("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        groups = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(groups), 2)
        self.assertEqual([h["command"] for h in groups[0]["hooks"]], [other])

    def test_context_skips_synthetic_and_zero_usage_entries(self):
        for model, tokens in (("<synthetic>", 0), ("<synthetic>", 2), ("real", 0)):
            with self.subTest(model=model, tokens=tokens):
                self.write_usage(("real", 125000), (model, tokens))
                self.assertEqual(hooks.context_tokens(self.transcript), 125000)

    def test_backup_keeps_original_across_install_and_uninstall(self):
        original = b'{"model":"opus"}\n'
        self.settings.write_bytes(original)
        backup = self.settings.with_suffix(".json.handoff-bak")
        for args in (("install",), ("install", "--warn", "40,65"), ("uninstall",)):
            with self.subTest(args=args):
                result = self.install(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(backup.read_bytes(), original)

    def test_settings_symlink_survives_install_and_uninstall(self):
        target = self.root / "actual-settings.json"
        target.write_text('{"model":"opus"}', encoding="utf-8")
        try:
            self.settings.symlink_to(target.name)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        for action in ("install", "uninstall"):
            result = self.install(action)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.settings.is_symlink())
            settings = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(settings["model"], "opus")
            self.assertEqual("hooks" in settings, action == "install")

    def test_rejects_settings_and_hooks_that_are_not_objects(self):
        for action in ("install", "uninstall"):
            for value in ("null", "[]", '{"hooks": null}', '{"hooks": []}'):
                with self.subTest(action=action, value=value):
                    self.settings.write_text(value, encoding="utf-8")
                    result = self.install(action)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("JSON object", result.stdout)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(self.settings.read_text(encoding="utf-8"), value)
                    self.assertFalse(self.settings.with_suffix(".json.handoff-bak").exists())

    def test_uninstall_leaves_missing_settings_missing(self):
        result = self.install("uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.settings.exists())

    def test_settings_are_written_with_literal_utf8(self):
        self.settings.write_text('{"model":"café"}', encoding="utf-8")
        result = self.install("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("café".encode("utf-8"), self.settings.read_bytes())

    def test_used_tokens_over_configured_window_use_one_million(self):
        for tokens, expected in ((300000, ""), (500000, "(50% of context)")):
            with self.subTest(tokens=tokens):
                self.write_usage(("real", tokens))
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "hooks.py"), "prompt"], env=self.env,
                    capture_output=True, text=True, input=self.payload(session_id=str(tokens)),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if expected:
                    self.assertIn(expected, json.loads(result.stdout)["systemMessage"])
                else:
                    self.assertEqual(result.stdout, "")

    def test_macos_notification_is_opt_in_and_failure_keeps_warning(self):
        message = 'A "quote" and a \\ backslash'
        for platform, opts, should_notify in (("darwin", ["--notify"], True),
                                              ("darwin", [], False),
                                              ("linux", ["--notify"], False)):
            with self.subTest(platform=platform, opts=opts):
                self.write_usage(("real", 100000))
                out = io.StringIO()
                with mock.patch.dict(os.environ, self.env), mock.patch.object(sys, "platform", platform), \
                     mock.patch.object(sys, "argv", ["hooks.py", "prompt", *opts]), \
                     mock.patch.object(sys, "stdin", io.StringIO(self.payload(session_id=platform + str(opts)))), \
                     mock.patch.object(hooks, "warning_text", return_value=message), \
                     mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 3)) as run, \
                     contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit_code:
                    hooks.main()
                self.assertEqual(exit_code.exception.code, 0)
                self.assertTrue(out.getvalue(), "The prompt hook did not emit a warning")
                self.assertEqual(json.loads(out.getvalue())["systemMessage"], message)
                if should_notify:
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[0], ["osascript", "-e",
                        r'display notification "A \"quote\" and a \\ backslash" with title "/handoff"'])
                    self.assertEqual(run.call_args.kwargs["timeout"], 3)
                else:
                    run.assert_not_called()

    @unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "requires POSIX bash")
    def test_shell_installer_passes_notify(self):
        repo = self.root / "install copy"
        shutil.copytree(ROOT / "skills", repo / "skills")
        installer = repo / "install.sh"
        shutil.copyfile(ROOT / "install.sh", installer)
        help_result = subprocess.run(["bash", str(installer), "-h"], capture_output=True, text=True)
        result = subprocess.run(["bash", str(installer), "--notify"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--notify", help_result.stdout)
        self.assertIn("--no-hooks", help_result.stdout)
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        prompt = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn(" --notify", prompt)
