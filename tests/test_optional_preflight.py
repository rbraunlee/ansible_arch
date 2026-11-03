"""Production-order, fail-closed preflight tests for ticket #10."""

import copy
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.yml"
PREFLIGHT_TASKS = ROOT / "tasks" / "optional_preflight.yml"
PATCH = ROOT / "docs" / "hyprland-optional-overlay-v1.patch"
FIXTURE = ROOT / "tests" / "fixtures" / "optional_preflight" / "playbook.yml"
COLLECTIONS = ROOT / "tests" / "fixtures" / "optional_preflight_stub_collections"
SENTINEL = "TICKET10_POST_PREFLIGHT_MUTATION_SENTINEL_REACHED"
CONTRACT_FAILURE = "does not implement immutable"
DEFAULT_PROFILES = {
    "tmux_focus": False,
    "swappy": False,
    "media_recording": False,
    "archive_helpers": False,
    "mirror_tools": False,
    "voxtype": {"enabled": False, "provider": "none"},
}


def baseline_hyprland():
    """A numbered upstream hunk fixture for applying the shipped patch exactly."""
    lines = ["\n"] * 190
    lines[14] = 'local terminal = "ghostty"\n'
    lines[15] = 'local fileManager = "dolphin"\n'
    lines[16] = 'local menu = "wofi --show drun"\n'
    lines[17] = 'local screenshot = "flameshot gui"\n'
    lines[24] = 'hl.on("hyprland.start", function()\n'
    lines[25] = '\thl.exec_cmd("focus")\n'
    lines[26] = '\thl.exec_cmd("waybar")\n'
    lines[27] = '\thl.exec_cmd("hyprpaper")\n'
    lines[28] = '\thl.exec_cmd("mako")\n'
    lines[29] = '\thl.exec_cmd("gsettings")\n'
    lines[30] = '\thl.exec_cmd("polkit")\n'
    lines[31] = '\thl.exec_cmd("hypridle")\n'
    lines[32] = '\t-- start is idempotent for an already active user unit; do not spawn a second daemon.\n'
    lines[33] = '\t-- Use a shell so the start is conditional on importing the Wayland session first.\n'
    lines[34] = (
        '\thl.exec_cmd("sh -c \'systemctl --user import-environment WAYLAND_DISPLAY DISPLAY '
        'XDG_CURRENT_DESKTOP XDG_SESSION_TYPE HYPRLAND_INSTANCE_SIGNATURE && '
        'systemctl --user start voxtype.service\'")\n'
    )
    lines[35] = 'end)\n'
    lines[41] = 'hl.env("XCURSOR_SIZE", "24")\n'
    lines[42] = 'hl.env("HYPRCURSOR_SIZE", "24")\n'
    lines[43] = 'hl.env("LIBVA_DRIVER_NAME", "nvidia")\n'
    lines[44] = 'hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")\n'
    lines[119] = 'local mainMod = "SUPER"\n'
    lines[161] = '-- Screenshot\n'
    lines[162] = 'hl.bind(mainMod .. " + CTRL + SHIFT + s", hl.dsp.exec_cmd(screenshot))\n'
    lines[164] = '-- Toggle local dictation; Voxtype types into whichever field has focus at output time.\n'
    lines[165] = 'hl.bind(mainMod .. " + CTRL + d", hl.dsp.exec_cmd("voxtype record toggle"))\n'
    lines[167] = '-- Isolate synthetic dictation from desktop shortcuts while output is typed.\n'
    lines[168] = "-- Do not bind Escape here: it can swallow wtype's first character.\n"
    lines[169] = 'hl.define_submap("voxtype_suppress", function()\n'
    lines[170] = (
        '\tfor _, key in ipairs({ "Super_L", "Super_R", "Control_L", "Control_R", '
        '"Alt_L", "Alt_R", "Shift_L", "Shift_R" }) do\n'
    )
    lines[171] = '\t\thl.bind(key, function() end)\n'
    lines[172] = '\tend\n'
    lines[173] = '\t-- Release held modifiers, then press F12 if output was interrupted.\n'
    lines[174] = '\thl.bind("F12", hl.dsp.submap("reset"))\n'
    lines[175] = 'end)\n'
    return "".join(lines)


class OptionalPreflightTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.username = pwd.getpwuid(os.geteuid()).pw_name

    def create_source_repository(self, root, state):
        repository = root / "source"
        source = repository / "linux" / "hypr" / ".config" / "hypr" / "hyprland.lua"
        source.parent.mkdir(parents=True)
        if state == "missing":
            source.write_text("-- source without optional contract\n", encoding="utf-8")
        else:
            source.write_text(baseline_hyprland(), encoding="utf-8")
            applied = subprocess.run(
                ["patch", "-p1", "-d", str(repository)],
                input=PATCH.read_text(encoding="utf-8"),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            if state == "drift":
                loader = source.with_name("ansible_arch_optional_overlay_v1.lua")
                loader.write_text("return { voxtype_enabled = false, nvidia_environment = false }\n", encoding="utf-8")
            elif state == "incomplete":
                source.write_text(
                    '-- local ansible_optional = dofile(os.getenv("HOME") .. "/.config/hypr/ansible_arch_optional_overlay_v1.lua")\n'
                    '-- if ansible_optional.nvidia_environment then hl.env("LIBVA_DRIVER_NAME", "nvidia") end\n'
                    '-- if ansible_optional.voxtype_enabled then hl.bind("fake", "voxtype record toggle") end\n',
                    encoding="utf-8",
                )

        for command in (
            ["git", "init", "-q", str(repository)],
            ["git", "-C", str(repository), "add", "."],
            [
                "git", "-C", str(repository), "-c", "user.email=fixture@example.invalid",
                "-c", "user.name=Fixture", "commit", "-qm", "fixture source",
            ],
        ):
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return repository

    def environment(self, root):
        config = root / "ansible.cfg"
        config.write_text(
            "[defaults]\n"
            "inventory = localhost,\n"
            "host_key_checking = False\n"
            "retry_files_enabled = False\n"
            "[privilege_escalation]\n"
            "become = False\n",
            encoding="utf-8",
        )
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")
        }
        environment.update(
            {
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_HOME": str(root / ".ansible" / "home"),
                "ANSIBLE_LOCAL_TEMP": str(root / ".ansible" / "local"),
                "ANSIBLE_REMOTE_TEMP": str(root / ".ansible" / "remote"),
                "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS),
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_FORCE_COLOR": "0",
                "ANSIBLE_STDOUT_CALLBACK": "default",
                "ANSIBLE_RETRY_FILES_ENABLED": "0",
            }
        )
        return environment

    def run_fixture(self, root, repository):
        variables = {
            "ansible_become": False,
            "fixture_runtime_root": str(root),
            "username": self.username,
            "use_nvidia": False,
            "dotfiles": {
                "repo": str(repository),
                "dest": str(root / "dotfiles"),
                "subdirs": ["common", "linux"],
            },
            "optional_profiles": copy.deepcopy(DEFAULT_PROFILES),
        }
        return subprocess.run(
            [
                "ansible-playbook", "-i", "localhost,", "-v", "--tags", "optional",
                "--extra-vars", json.dumps(variables), str(FIXTURE),
            ],
            cwd=root,
            env=self.environment(root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_main_orders_always_preflight_before_system_and_optional_tags_cannot_bypass(self):
        tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))[0]["tasks"]
        names = [task["name"] for task in tasks]
        self.assertLess(names.index("Validate optional profile selections"), names.index("Preflight the exact dotfiles revision"))
        self.assertLess(names.index("Preflight the exact dotfiles revision"), names.index("Import System configurations"))
        preflight = yaml.safe_load(PREFLIGHT_TASKS.read_text(encoding="utf-8"))
        self.assertEqual(preflight[0]["tags"], ["always"])
        self.assertEqual(preflight[1]["tags"], ["always"])

    def test_missing_or_drifted_contract_stops_before_fail_closed_mutation_sentinel(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-preflight-") as directory:
            parent = Path(directory)
            for state in ("missing", "drift", "incomplete"):
                with self.subTest(state=state):
                    root = parent / state
                    root.mkdir()
                    result = self.run_fixture(root, self.create_source_repository(root, state))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(CONTRACT_FAILURE, result.stdout + result.stderr)
                    self.assertNotIn(SENTINEL, result.stdout + result.stderr)
                    self.assertFalse((root / "dotfiles").exists())

    def test_exact_patched_contract_passes_preflight_then_reaches_sentinel(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-preflight-ok-") as directory:
            root = Path(directory)
            result = self.run_fixture(root, self.create_source_repository(root, "exact"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(SENTINEL, result.stdout + result.stderr)
            self.assertNotIn(CONTRACT_FAILURE, result.stdout + result.stderr)
            self.assertFalse((root / "dotfiles").exists())


if __name__ == "__main__":
    unittest.main()
