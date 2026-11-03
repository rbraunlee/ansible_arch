"""Behavioral regression tests for Ansible's automatic variable loading."""

import base64
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPLIT_GROUP_VARS = ROOT / "group_vars" / "all"
LOCALHOST_VARS = ROOT / "host_vars" / "localhost.yml"
FIXTURES = ROOT / "tests" / "fixtures" / "variable_loading"
LEGACY_GROUP_VARS = FIXTURES / "legacy_all.yml"
INSPECTION_PLAYBOOK = FIXTURES / "inspect.yml"
SNAPSHOT_PATTERN = re.compile(r"VARIABLE_SNAPSHOT=([A-Za-z0-9+/=]+)")
EXPECTED_SPLIT_FILES = {
    "aur.yml",
    "base.yml",
    "desktop.yml",
    "dotfiles.yml",
    "graphics.yml",
    "optional.yml",
    "services.yml",
    "system.yml",
}
# The legacy fixture is historical input and must not be changed for later
# defaults.  These are the reviewed ticket #9 default-package deltas, expressed
# relative to that fixture so this suite keeps testing compatibility rather than
# silently copying the current mappings into its expectations.
EXPECTED_PACKAGE_DELTAS = {
    "system_packages": {
        "remove": (),
        "insert_after": (
            ("snap-pac", "pacman-contrib"),
            ("ufw", "networkmanager"),
        ),
    },
    "desktop_packages": {
        "remove": ("ttf-font-awesome",),
        "insert_after": (
            ("hyprpaper", "hypridle"),
            ("hypridle", "hyprlock"),
            ("firefox", "dolphin"),
            ("npm", "neovim"),
            ("neovim", "tree-sitter-cli"),
            ("tree-sitter-cli", "ripgrep"),
            ("ttf-jetbrains-mono-nerd", "otf-font-awesome"),
            ("otf-font-awesome", "otf-comicshanns-nerd"),
        ),
    },
}
EXPECTED_ADDED_DEFAULTS = {
    "optional_profiles": {
        "tmux_focus": False,
        "swappy": False,
        "media_recording": False,
        "archive_helpers": False,
        "mirror_tools": False,
        "voxtype": {
            "enabled": False,
            "provider": "none",
        },
    },
    "optional_profile_package_sets": {
        "tmux_focus": ["tmux"],
        "swappy": ["swappy"],
        "media_recording": ["yt-dlp", "ffmpeg", "wf-recorder"],
        "archive_helpers": ["unrar", "unzip", "ncompress", "7zip"],
        "mirror_tools": ["reflector", "rate-mirrors", "expac"],
        "voxtype": ["wtype", "pipewire-alsa"],
    },
    "optional_voxtype_aur_packages": {
        "cuda": ["voxtype-cuda"],
    },
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise AssertionError(f"duplicate YAML key {key!r} in {loader.name}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def load_mapping(path):
    with path.open(encoding="utf-8") as stream:
        loaded = yaml.load(stream, Loader=UniqueKeyLoader)
    if not isinstance(loaded, dict):
        raise AssertionError(f"{path} must contain a YAML mapping")
    return loaded


class VariableLoadingTest(unittest.TestCase):
    maxDiff = None

    def aggregate_split_group_vars(self):
        actual_files = {path.name for path in SPLIT_GROUP_VARS.glob("*.yml")}
        self.assertEqual(actual_files, EXPECTED_SPLIT_FILES)

        combined = {}
        for path in sorted(SPLIT_GROUP_VARS.glob("*.yml")):
            for key, value in load_mapping(path).items():
                self.assertNotIn(key, combined, f"{key!r} is defined more than once")
                combined[key] = value
        return combined

    def prepare_project(self, parent, name, layout, host_overrides=None):
        project = parent / name
        (project / "group_vars").mkdir(parents=True)
        shutil.copy2(INSPECTION_PLAYBOOK, project / "inspect.yml")
        (project / "inventory.ini").write_text(
            "[local]\nlocalhost ansible_connection=local\n",
            encoding="utf-8",
        )

        if layout == "legacy":
            shutil.copy2(LEGACY_GROUP_VARS, project / "group_vars" / "all.yml")
        elif layout == "split":
            shutil.copytree(SPLIT_GROUP_VARS, project / "group_vars" / "all")
        else:
            raise AssertionError(f"unknown fixture layout: {layout}")

        if host_overrides is not None:
            (project / "host_vars").mkdir()
            (project / "host_vars" / "localhost.yml").write_text(
                yaml.safe_dump(host_overrides, sort_keys=False),
                encoding="utf-8",
            )
        return project

    def run_inspection(self, project, explicit_inventory):
        ansible_home = project / ".ansible" / "home"
        local_temp = project / ".ansible" / "local"
        remote_temp = project / ".ansible" / "remote"
        ansible_home.mkdir(parents=True)
        local_temp.mkdir(parents=True)
        remote_temp.mkdir(parents=True)

        config = project / "ansible.cfg"
        config.write_text(
            f"[defaults]\ninventory = {project / 'unused-default-inventory'}\n",
            encoding="utf-8",
        )
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("ANSIBLE_")}
        environment.update(
            {
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_HOME": str(ansible_home),
                "ANSIBLE_LOCAL_TEMP": str(local_temp),
                "ANSIBLE_REMOTE_TEMP": str(remote_temp),
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_FORCE_COLOR": "0",
                "ANSIBLE_STDOUT_CALLBACK": "default",
                "ANSIBLE_RETRY_FILES_ENABLED": "0",
            }
        )

        command = ["ansible-playbook"]
        if explicit_inventory:
            command.extend(["-i", str(project / "inventory.ini")])
        command.append(str(project / "inspect.yml"))
        result = subprocess.run(
            command,
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"command failed: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

        match = SNAPSHOT_PATTERN.search(result.stdout)
        self.assertIsNotNone(match, f"snapshot missing from output:\n{result.stdout}")
        return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))

    def expected_effective_legacy_values(self):
        expected = copy.deepcopy(load_mapping(LEGACY_GROUP_VARS))
        expected["username"] = "rbl"
        expected["dotfiles"]["dest"] = "/home/rbl/.dotfiles"
        expected["use_nvidia"] = "__MISSING__"
        expected["optional_profiles"] = "__MISSING__"
        expected["optional_profile_package_sets"] = "__MISSING__"
        expected["optional_voxtype_aur_packages"] = "__MISSING__"
        return expected

    def expected_split_values(self):
        """Build the reviewed split defaults from the immutable legacy fixture."""
        expected = copy.deepcopy(load_mapping(LEGACY_GROUP_VARS))
        for variable, delta in EXPECTED_PACKAGE_DELTAS.items():
            packages = expected[variable]
            for package in delta["remove"]:
                self.assertIn(package, packages)
                packages.remove(package)
            for anchor, package in delta["insert_after"]:
                self.assertIn(anchor, packages)
                self.assertNotIn(package, packages)
                packages.insert(packages.index(anchor) + 1, package)
        expected.update(copy.deepcopy(EXPECTED_ADDED_DEFAULTS))
        expected["use_nvidia"] = True
        return expected

    def assert_inventory_mode(self, snapshot, project, explicit_inventory):
        self.assertEqual(snapshot["inventory_hostname"], "localhost")
        sources = snapshot["inventory_sources"]
        if explicit_inventory:
            self.assertEqual(Path(snapshot["inventory_file"]).resolve(), (project / "inventory.ini").resolve())
            self.assertEqual([Path(source).resolve() for source in sources], [(project / "inventory.ini").resolve()])
        else:
            self.assertEqual(snapshot["inventory_file"], "__IMPLICIT__")
            self.assertNotIn((project / "inventory.ini").resolve(), [Path(source).resolve() for source in sources])

    def test_split_mapping_preserves_legacy_values_except_reviewed_package_deltas(self):
        self.assertEqual(self.aggregate_split_group_vars(), self.expected_split_values())
        self.assertFalse((ROOT / "group_vars" / "all.yml").exists())
        self.assertEqual(load_mapping(LOCALHOST_VARS), {})
        self.assertIn("# use_nvidia: false", LOCALHOST_VARS.read_text(encoding="utf-8"))

    def test_legacy_and_split_load_expected_defaults_with_explicit_and_implicit_localhost(self):
        with tempfile.TemporaryDirectory(prefix="ansible-variable-loading-") as directory:
            parent = Path(directory)
            for explicit_inventory in (True, False):
                mode = "explicit" if explicit_inventory else "implicit"
                legacy_project = self.prepare_project(parent, f"legacy-{mode}", "legacy")
                split_project = self.prepare_project(parent, f"split-{mode}", "split")

                legacy = self.run_inspection(legacy_project, explicit_inventory)
                split = self.run_inspection(split_project, explicit_inventory)
                self.assert_inventory_mode(legacy, legacy_project, explicit_inventory)
                self.assert_inventory_mode(split, split_project, explicit_inventory)

                expected_legacy = self.expected_effective_legacy_values()
                self.assertEqual(legacy["values"], expected_legacy)
                expected_split = self.expected_split_values()
                expected_split["username"] = "rbl"
                expected_split["dotfiles"]["dest"] = "/home/rbl/.dotfiles"
                self.assertEqual(split["values"], expected_split)

    def test_host_vars_override_group_scalar_list_and_boolean(self):
        overrides = {
            "username": "fixture-user",
            "desktop_packages": ["fixture-desktop-one", "fixture-desktop-two"],
            "use_nvidia": False,
            "optional_profiles": {
                "tmux_focus": True,
                "swappy": False,
                "media_recording": False,
                "archive_helpers": False,
                "mirror_tools": False,
                "voxtype": {
                    "enabled": False,
                    "provider": "none",
                },
            },
        }
        with tempfile.TemporaryDirectory(prefix="ansible-host-overrides-") as directory:
            parent = Path(directory)
            for explicit_inventory in (True, False):
                mode = "explicit" if explicit_inventory else "implicit"
                project = self.prepare_project(parent, mode, "split", overrides)
                snapshot = self.run_inspection(project, explicit_inventory)
                self.assert_inventory_mode(snapshot, project, explicit_inventory)

                values = snapshot["values"]
                self.assertEqual(values["username"], "fixture-user")
                self.assertEqual(values["desktop_packages"], overrides["desktop_packages"])
                self.assertIs(values["use_nvidia"], False)
                self.assertEqual(values["dotfiles"]["dest"], "/home/fixture-user/.dotfiles")
                self.assertEqual(values["system_packages"], self.expected_split_values()["system_packages"])
                self.assertEqual(values["optional_profiles"], overrides["optional_profiles"])


if __name__ == "__main__":
    unittest.main()
