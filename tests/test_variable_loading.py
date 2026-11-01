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
    "services.yml",
    "system.yml",
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
        local_temp = project / ".ansible" / "local"
        remote_temp = project / ".ansible" / "remote"
        local_temp.mkdir(parents=True)
        remote_temp.mkdir(parents=True)

        environment = os.environ.copy()
        environment.pop("ANSIBLE_CONFIG", None)
        environment.pop("ANSIBLE_INVENTORY", None)
        environment.update(
            {
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

    def test_split_mapping_preserves_every_legacy_value_once(self):
        legacy = load_mapping(LEGACY_GROUP_VARS)
        expected = copy.deepcopy(legacy)
        expected["use_nvidia"] = True

        self.assertEqual(self.aggregate_split_group_vars(), expected)
        self.assertFalse((ROOT / "group_vars" / "all.yml").exists())
        self.assertEqual(load_mapping(LOCALHOST_VARS), {})
        self.assertIn("# use_nvidia: false", LOCALHOST_VARS.read_text(encoding="utf-8"))

    def test_legacy_and_split_load_equivalently_with_explicit_and_implicit_localhost(self):
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
                expected_split = copy.deepcopy(expected_legacy)
                expected_split["use_nvidia"] = True
                self.assertEqual(split["values"], expected_split)

    def test_host_vars_override_group_scalar_list_and_boolean(self):
        overrides = {
            "username": "fixture-user",
            "desktop_packages": ["fixture-desktop-one", "fixture-desktop-two"],
            "use_nvidia": False,
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
                self.assertEqual(values["system_packages"], load_mapping(LEGACY_GROUP_VARS)["system_packages"])


if __name__ == "__main__":
    unittest.main()
