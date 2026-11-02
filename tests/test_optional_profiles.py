"""Isolated behavioral tests for ticket #10 optional profile tasks."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "optional_profiles"
FIXTURE_PLAYBOOK = FIXTURE_ROOT / "playbook.yml"
FIXTURE_COLLECTIONS = ROOT / "tests" / "fixtures" / "optional_profiles_stub_collections"
PACMAN_STUB = (
    FIXTURE_COLLECTIONS
    / "ansible_collections"
    / "community"
    / "general"
    / "plugins"
    / "modules"
    / "pacman.py"
)
AUR_STUB = (
    FIXTURE_COLLECTIONS
    / "ansible_collections"
    / "kewlfft"
    / "aur"
    / "plugins"
    / "modules"
    / "aur.py"
)
PACKAGE_RESULT_PATTERN = re.compile(r'"ticket10_package_stub": (\[[^]]*\])')
AUR_RESULT_PATTERN = re.compile(r'"ticket10_aur_stub": (\[[^]]*\])')
OVERLAY_MARKER = "ansible_arch_optional_overlay_v1"
CONTRACT_SOURCE = """-- ansible_arch_optional_overlay_v1
local ansible_optional = {}
local ansible_optional_path = "ansible_arch/hyprland-optional.lua"
local loaded, overlay = pcall(dofile, ansible_optional_path)
if ansible_optional.voxtype_enabled then
end
if ansible_optional.nvidia_environment then
end
"""
UNSUPPORTED_SOURCE = """-- legacy source without ticket #10 integration
hl.exec_cmd(\"systemctl --user start voxtype.service\")
hl.env(\"LIBVA_DRIVER_NAME\", \"nvidia\")
"""
DEFAULT_PROFILES = {
    "tmux_focus": False,
    "swappy": False,
    "media_recording": False,
    "archive_helpers": False,
    "mirror_tools": False,
    "voxtype": {"enabled": False, "provider": "none"},
}
PACKAGE_SETS = {
    "tmux_focus": ["tmux"],
    "swappy": ["swappy"],
    "media_recording": ["yt-dlp", "ffmpeg", "wf-recorder"],
    "archive_helpers": ["unrar", "unzip", "ncompress", "7zip"],
    "mirror_tools": ["reflector", "rate-mirrors", "expac"],
    "voxtype": ["wtype", "pipewire-alsa"],
}


class OptionalProfilesTest(unittest.TestCase):
    maxDiff = None

    def prepare_case(self, parent, name, *, source=CONTRACT_SOURCE, overlay=None):
        case = parent / name
        source_path = case / "dotfiles" / "linux" / "hypr" / ".config" / "hypr" / "hyprland.lua"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(source, encoding="utf-8")
        overlay_path = case / "home" / "rbl" / ".config" / "ansible_arch" / "hyprland-optional.lua"
        if overlay is not None:
            overlay_path.parent.mkdir(parents=True)
            overlay_path.write_text(overlay, encoding="utf-8")
        return {
            "root": case,
            "source": source_path,
            "overlay": overlay_path,
        }

    def ansible_environment(self, case):
        config = case["root"] / "ansible.cfg"
        local_temp = case["root"] / ".ansible" / "local"
        remote_temp = case["root"] / ".ansible" / "remote"
        ansible_home = case["root"] / ".ansible" / "home"
        for directory in (local_temp, remote_temp, ansible_home):
            directory.mkdir(parents=True, exist_ok=True)
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
                "ANSIBLE_HOME": str(ansible_home),
                "ANSIBLE_LOCAL_TEMP": str(local_temp),
                "ANSIBLE_REMOTE_TEMP": str(remote_temp),
                "ANSIBLE_COLLECTIONS_PATH": str(FIXTURE_COLLECTIONS),
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_FORCE_COLOR": "0",
                "ANSIBLE_STDOUT_CALLBACK": "default",
                "ANSIBLE_RETRY_FILES_ENABLED": "0",
            }
        )
        return environment

    def variables(self, case, *, profiles=None, use_nvidia=True):
        return {
            "ansible_become": False,
            "fixture_runtime_root": str(case["root"]),
            "username": "rbl",
            "aur_builder": "fixture_aur_builder",
            "use_nvidia": use_nvidia,
            "dotfiles": {
                "repo": "https://example.invalid/dotfiles.git",
                "dest": str(case["root"] / "dotfiles"),
                "subdirs": ["common", "linux"],
            },
            "optional_profiles": copy.deepcopy(profiles or DEFAULT_PROFILES),
            "optional_profile_package_sets": copy.deepcopy(PACKAGE_SETS),
            "optional_voxtype_aur_packages": {"cuda": ["voxtype-cuda"]},
            "optional_hyprland_overlay": {
                "path": str(case["overlay"]),
                "contract_marker": OVERLAY_MARKER,
            },
        }

    def assert_stub_resolution(self, case):
        result = subprocess.run(
            ["ansible-doc", "-t", "module", "-F"],
            cwd=case["root"],
            env=self.ansible_environment(case),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for module, path in (
            ("community.general.pacman", PACMAN_STUB),
            ("kewlfft.aur.aur", AUR_STUB),
        ):
            lines = [
                line for line in result.stdout.splitlines()
                if line.strip().startswith(module + " ")
            ]
            self.assertEqual(len(lines), 1, result.stdout)
            self.assertIn(str(path.resolve()), lines[0])

    def run_case(self, case, *, profiles=None, use_nvidia=True, tags="optional"):
        self.assert_stub_resolution(case)
        command = [
            "ansible-playbook",
            "-i",
            "localhost,",
            "-v",
            "--tags",
            tags,
            "--extra-vars",
            json.dumps(self.variables(case, profiles=profiles, use_nvidia=use_nvidia)),
            str(FIXTURE_PLAYBOOK),
        ]
        return subprocess.run(
            command,
            cwd=case["root"],
            env=self.ansible_environment(case),
            capture_output=True,
            text=True,
            check=False,
        )

    def package_calls(self, output):
        return [json.loads(match) for match in PACKAGE_RESULT_PATTERN.findall(output)]

    def aur_calls(self, output):
        return [json.loads(match) for match in AUR_RESULT_PATTERN.findall(output)]

    def assert_safe_failure(self, result, case, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message.lower(), (result.stdout + result.stderr).lower())
        self.assertEqual(self.package_calls(result.stdout), [])
        self.assertEqual(self.aur_calls(result.stdout), [])
        self.assertFalse(case["overlay"].exists())

    def test_default_profile_is_opt_in_and_repeatable(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-default-") as directory:
            case = self.prepare_case(Path(directory), "default")
            first = self.run_case(case)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(self.package_calls(first.stdout), [])
            self.assertEqual(self.aur_calls(first.stdout), [])
            self.assertEqual(
                case["overlay"].read_text(encoding="utf-8"),
                "-- ansible_arch_optional_overlay_v1\n"
                "-- Generated by ansible_arch from optional_profiles. Do not edit this file;\n"
                "-- use a complete host_vars optional_profiles mapping instead.\n"
                "return {\n"
                "  voxtype_enabled = false,\n"
                "  nvidia_environment = true,\n"
                "}\n",
            )
            self.assertEqual(case["source"].read_text(encoding="utf-8"), CONTRACT_SOURCE)

            second = self.run_case(case)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(self.package_calls(second.stdout), [])
            self.assertEqual(self.aur_calls(second.stdout), [])
            self.assertIn("changed=0", second.stdout)

    def test_selected_profiles_install_only_their_grouped_providers(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        for profile in ("tmux_focus", "swappy", "media_recording", "archive_helpers", "mirror_tools"):
            profiles[profile] = True
        profiles["voxtype"] = {"enabled": True, "provider": "cuda"}
        expected_packages = [
            "tmux",
            "swappy",
            "yt-dlp",
            "ffmpeg",
            "wf-recorder",
            "unrar",
            "unzip",
            "ncompress",
            "7zip",
            "reflector",
            "rate-mirrors",
            "expac",
            "wtype",
            "pipewire-alsa",
        ]
        with tempfile.TemporaryDirectory(prefix="ansible-optional-enabled-") as directory:
            case = self.prepare_case(Path(directory), "enabled")
            result = self.run_case(case, profiles=profiles)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                self.package_calls(result.stdout),
                [expected_packages],
                result.stdout + result.stderr,
            )
            self.assertEqual(self.aur_calls(result.stdout), [["voxtype-cuda"]], result.stdout + result.stderr)
            self.assertIn("voxtype_enabled = true", case["overlay"].read_text(encoding="utf-8"))
            self.assertIn("nvidia_environment = true", case["overlay"].read_text(encoding="utf-8"))

    def test_disabled_profile_with_non_nvidia_renders_no_nvidia_environment(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-non-nvidia-") as directory:
            case = self.prepare_case(Path(directory), "non-nvidia")
            result = self.run_case(case, use_nvidia=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [])
            self.assertEqual(self.aur_calls(result.stdout), [])
            overlay = case["overlay"].read_text(encoding="utf-8")
            self.assertIn("voxtype_enabled = false", overlay)
            self.assertIn("nvidia_environment = false", overlay)

    def test_invalid_profiles_fail_before_packages_or_overlay_mutation(self):
        invalid_cases = {
            "string-flag": {**DEFAULT_PROFILES, "tmux_focus": "true"},
            "unknown-key": {**DEFAULT_PROFILES, "unknown": False},
            "enabled-none": {**DEFAULT_PROFILES, "voxtype": {"enabled": True, "provider": "none"}},
            "disabled-cuda": {**DEFAULT_PROFILES, "voxtype": {"enabled": False, "provider": "cuda"}},
        }
        with tempfile.TemporaryDirectory(prefix="ansible-optional-invalid-") as directory:
            parent = Path(directory)
            for label, profiles in invalid_cases.items():
                with self.subTest(label=label):
                    case = self.prepare_case(parent, label)
                    result = self.run_case(case, profiles=profiles)
                    self.assert_safe_failure(result, case, "Optional")
                    self.assertEqual(case["source"].read_text(encoding="utf-8"), CONTRACT_SOURCE)

    def test_cuda_profile_rejects_non_nvidia_before_packages_or_overlay_mutation(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        profiles["voxtype"] = {"enabled": True, "provider": "cuda"}
        with tempfile.TemporaryDirectory(prefix="ansible-optional-cuda-non-nvidia-") as directory:
            case = self.prepare_case(Path(directory), "cuda-non-nvidia")
            result = self.run_case(case, profiles=profiles, use_nvidia=False)
            self.assert_safe_failure(result, case, "Voxtype provider cuda requires use_nvidia: true.")
            self.assertEqual(case["source"].read_text(encoding="utf-8"), CONTRACT_SOURCE)

    def test_missing_source_contract_fails_before_selected_profile_packages(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        profiles["voxtype"] = {"enabled": True, "provider": "cuda"}
        with tempfile.TemporaryDirectory(prefix="ansible-optional-contract-") as directory:
            case = self.prepare_case(Path(directory), "missing-contract", source=UNSUPPORTED_SOURCE)
            result = self.run_case(case, profiles=profiles)
            self.assert_safe_failure(result, case, "does not implement the reviewed")
            self.assertEqual(case["source"].read_text(encoding="utf-8"), UNSUPPORTED_SOURCE)

    def test_unowned_overlay_is_preserved(self):
        unowned_overlay = "return { voxtype_enabled = true, nvidia_environment = true }\n"
        with tempfile.TemporaryDirectory(prefix="ansible-optional-preserve-") as directory:
            case = self.prepare_case(Path(directory), "unowned", overlay=unowned_overlay)
            result = self.run_case(case)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to replace an unowned optional overlay", result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [])
            self.assertEqual(self.aur_calls(result.stdout), [])
            self.assertEqual(case["overlay"].read_text(encoding="utf-8"), unowned_overlay)

    def test_managed_overlay_drift_is_reconciled_and_then_idempotent(self):
        managed_drift = (
            "-- ansible_arch_optional_overlay_v1\n"
            "return { voxtype_enabled = true, nvidia_environment = true }\n"
        )
        with tempfile.TemporaryDirectory(prefix="ansible-optional-drift-") as directory:
            case = self.prepare_case(Path(directory), "drift", overlay=managed_drift)
            result = self.run_case(case, use_nvidia=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            reconciled = case["overlay"].read_text(encoding="utf-8")
            self.assertIn("voxtype_enabled = false", reconciled)
            self.assertIn("nvidia_environment = false", reconciled)

            repeat = self.run_case(case, use_nvidia=False)
            self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
            self.assertIn("changed=0", repeat.stdout)

    def test_unexpected_tags_fail_before_production_tasks(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-tags-") as directory:
            case = self.prepare_case(Path(directory), "unexpected-tags")
            result = self.run_case(case, tags="all")
            self.assert_safe_failure(result, case, "Optional profile fixture safety boundary violated")
            self.assertEqual(case["source"].read_text(encoding="utf-8"), CONTRACT_SOURCE)


if __name__ == "__main__":
    unittest.main()
