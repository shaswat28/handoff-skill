import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ShellInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "installer"
        self.root.mkdir()
        shutil.copy2(ROOT / "install.sh", self.root / "install.sh")
        shutil.copytree(ROOT / "skills", self.root / "skills")
        self.config = Path(self.temp.name) / "config"

    def run_installer(self, *args):
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        return subprocess.run(
            ["bash", str(self.root / "install.sh"), *args], cwd=self.root,
            env=env, text=True, capture_output=True,
        )

    def settings_bytes(self):
        path = self.config / "settings.json"
        return path.read_bytes() if path.exists() else None

    def test_default_installs_skill_without_settings_file(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.config / "skills/handoff/SKILL.md").is_file())
        self.assertIsNone(self.settings_bytes())
        self.assertIn("--hooks --window 1000000", result.stdout)

    def test_default_preserves_existing_settings_byte_for_byte(self):
        self.config.mkdir()
        settings = self.config / "settings.json"
        original = b'{ "foreign": [1, 2], "hooks": {"Other": []} }\n'
        settings.write_bytes(original)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.read_bytes(), original)

    def assert_our_hooks(self):
        settings = json.loads((self.config / "settings.json").read_text())
        commands = [h["command"] for groups in settings["hooks"].values()
                    for group in groups for h in group.get("hooks", [])]
        self.assertTrue(any("hooks.py prompt" in command for command in commands), commands)

    def test_hooks_flag_installs_hooks(self):
        result = self.run_installer("--hooks")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_our_hooks()

    def test_window_alone_implies_hooks(self):
        result = self.run_installer("--window", "1000000")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_our_hooks()

    def test_hooks_and_no_hooks_conflict_without_changes(self):
        self.config.mkdir()
        settings = self.config / "settings.json"
        original = b'{"foreign":true}\n'
        settings.write_bytes(original)
        result = self.run_installer("--hooks", "--no-hooks")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(settings.read_bytes(), original)
        self.assertFalse((self.config / "skills/handoff").exists())

    def test_no_hooks_removes_our_hooks(self):
        self.assertEqual(self.run_installer("--hooks").returncode, 0)
        result = self.run_installer("--no-hooks")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((self.config / "settings.json").read_text())
        commands = [h["command"] for groups in settings.get("hooks", {}).values()
                    for group in groups for h in group.get("hooks", [])]
        self.assertFalse(any("hooks.py" in command for command in commands), commands)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh is not on PATH")
class PowerShellInstallerTests(unittest.TestCase):
    def test_powershell_installer_available(self):
        self.skipTest("PowerShell integration coverage is not configured in this environment")


if __name__ == "__main__":
    unittest.main()
