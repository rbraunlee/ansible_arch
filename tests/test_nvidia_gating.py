"""Behavioral tests for the production NVIDIA task gating and rendering."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "nvidia_gating"
FIXTURE_PLAYBOOK = FIXTURE_ROOT / "playbook.yml"
FIXTURE_COLLECTIONS = ROOT / "tests" / "fixtures" / "nvidia_gating_stub_collections"
PACMAN_STUB = (
    FIXTURE_COLLECTIONS
    / "ansible_collections"
    / "community"
    / "general"
    / "plugins"
    / "modules"
    / "pacman.py"
)
HANDLER_MARKER = "TICKET5_INITRAMFS_HANDLER_RAN"
PACKAGE_RESULT_PATTERN = re.compile(r'"ticket5_package_stub": (\[[^]]*\])')
EXPECTED_NVIDIA_PACKAGES = [
    "nvidia-dkms",
    "nvidia-utils",
    "libva-nvidia-driver",
    "nvidia-settings",
]
TRUE_DROPIN = (
    "# Ansible managed: Early KMS for NVIDIA and BTRFS support\n"
    "MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)\n"
)
FALSE_DROPIN = (
    "# Ansible managed: Early KMS for NVIDIA and BTRFS support\n"
    "MODULES=(btrfs)\n"
)
ORIGINAL_LIMINE = "entry: Arch Linux\n  cmdline: root=UUID=fixture quiet\n"
INVALID_VALUES = (
    ("string-false", "false"),
    ("string-true", "true"),
    ("integer-zero", 0),
    ("integer-one", 1),
    ("null", None),
    ("list", []),
    ("mapping", {}),
)
USE_DEFAULT = object()


class NvidiaGatingTest(unittest.TestCase):
    maxDiff = None

    def prepare_case(self, parent, name):
        case = parent / name
        inventory_root = case / "inventory"
        runtime_root = case / "runtime"
        (inventory_root / "group_vars").mkdir(parents=True)
        runtime_root.mkdir(parents=True)
        shutil.copytree(ROOT / "group_vars" / "all", inventory_root / "group_vars" / "all")
        (inventory_root / "inventory.ini").write_text(
            "[local]\nlocalhost ansible_connection=local\n",
            encoding="utf-8",
        )
        limine_path = runtime_root / "boot" / "limine.conf"
        limine_path.parent.mkdir(parents=True)
        limine_path.write_text(ORIGINAL_LIMINE, encoding="utf-8")
        return {
            "case": case,
            "inventory_root": inventory_root,
            "runtime_root": runtime_root,
            "limine_path": limine_path,
            "dropin_dir": runtime_root / "etc" / "mkinitcpio.conf.d",
        }

    def ansible_environment(self, case):
        local_temp = case["case"] / ".ansible" / "local"
        remote_temp = case["case"] / ".ansible" / "remote"
        local_temp.mkdir(parents=True, exist_ok=True)
        remote_temp.mkdir(parents=True, exist_ok=True)

        config = case["case"] / "ansible.cfg"
        config.write_text("[defaults]\nretry_files_enabled = False\n", encoding="utf-8")
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("ANSIBLE_")}
        environment.update(
            {
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_COLLECTIONS_PATH": str(FIXTURE_COLLECTIONS),
                "ANSIBLE_LOCAL_TEMP": str(local_temp),
                "ANSIBLE_REMOTE_TEMP": str(remote_temp),
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_FORCE_COLOR": "0",
                "ANSIBLE_STDOUT_CALLBACK": "default",
                "ANSIBLE_RETRY_FILES_ENABLED": "0",
            }
        )
        return environment

    def assert_stub_resolution(self, case):
        result = subprocess.run(
            ["ansible-doc", "-t", "module", "-F"],
            cwd=case["inventory_root"],
            env=self.ansible_environment(case),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"ansible-doc failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        pacman_lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip().startswith("community.general.pacman ")
        ]
        self.assertEqual(len(pacman_lines), 1, result.stdout)
        self.assertIn(str(PACMAN_STUB.resolve()), pacman_lines[0])

    def run_case(self, case, use_nvidia=USE_DEFAULT, tags="nvidia"):
        extra_vars = {
            "ansible_become": False,
            "fixture_runtime_root": str(case["runtime_root"]),
            "ansible_python_interpreter": "/usr/bin/python",
            "limine_conf_path": str(case["limine_path"]),
            "mkinitcpio_dropin_dir": str(case["dropin_dir"]),
        }
        if use_nvidia is not USE_DEFAULT:
            extra_vars["use_nvidia"] = use_nvidia

        command = [
            "ansible-playbook",
            "-i",
            str(case["inventory_root"] / "inventory.ini"),
            str(FIXTURE_PLAYBOOK),
            "--tags",
            tags,
            "-v",
            "--extra-vars",
            json.dumps(extra_vars),
        ]
        return subprocess.run(
            command,
            cwd=case["inventory_root"],
            env=self.ansible_environment(case),
            capture_output=True,
            text=True,
            check=False,
        )

    def package_calls(self, output):
        return [json.loads(match) for match in PACKAGE_RESULT_PATTERN.findall(output)]

    def assert_successful_enabled_run(self, result, case, expect_handler):
        self.assertEqual(
            result.returncode,
            0,
            f"play failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertEqual(self.package_calls(result.stdout), [EXPECTED_NVIDIA_PACKAGES])
        self.assertIn("nvidia_drm.modeset=1", case["limine_path"].read_text(encoding="utf-8"))
        self.assertTrue(case["dropin_dir"].is_dir())
        self.assertEqual(
            (case["dropin_dir"] / "nvidia_btrfs.conf").read_text(encoding="utf-8"),
            TRUE_DROPIN,
        )
        self.assertEqual(HANDLER_MARKER in result.stdout, expect_handler)

    def test_default_and_explicit_true_enable_nvidia_for_tagged_runs(self):
        with tempfile.TemporaryDirectory(prefix="ansible-nvidia-enabled-") as directory:
            parent = Path(directory)
            for label, value in (("default", USE_DEFAULT), ("explicit-true", True)):
                with self.subTest(value=label):
                    case = self.prepare_case(parent, label)
                    self.assert_stub_resolution(case)
                    first = self.run_case(case, value)
                    self.assert_successful_enabled_run(first, case, expect_handler=True)

                    second = self.run_case(case, value)
                    self.assert_successful_enabled_run(second, case, expect_handler=False)

    def test_false_skips_packages_and_limine_but_keeps_btrfs_dropin(self):
        with tempfile.TemporaryDirectory(prefix="ansible-nvidia-disabled-") as directory:
            case = self.prepare_case(Path(directory), "disabled")
            self.assert_stub_resolution(case)
            first = self.run_case(case, False)
            self.assertEqual(
                first.returncode,
                0,
                f"play failed:\nstdout:\n{first.stdout}\nstderr:\n{first.stderr}",
            )
            self.assertEqual(self.package_calls(first.stdout), [])
            self.assertEqual(case["limine_path"].read_text(encoding="utf-8"), ORIGINAL_LIMINE)
            self.assertTrue(case["dropin_dir"].is_dir())
            self.assertEqual(
                (case["dropin_dir"] / "nvidia_btrfs.conf").read_text(encoding="utf-8"),
                FALSE_DROPIN,
            )
            self.assertIn(HANDLER_MARKER, first.stdout)

            second = self.run_case(case, False)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(self.package_calls(second.stdout), [])
            self.assertEqual(case["limine_path"].read_text(encoding="utf-8"), ORIGINAL_LIMINE)
            self.assertNotIn(HANDLER_MARKER, second.stdout)

    def test_ambient_ansible_settings_are_ignored(self):
        with tempfile.TemporaryDirectory(prefix="ansible-nvidia-ambient-") as directory:
            case = self.prepare_case(Path(directory), "ambient")
            hostile_config = case["case"] / "ambient.cfg"
            hostile_config.write_text("[tags]\nrun = all\nskip = always\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "ANSIBLE_CONFIG": str(hostile_config),
                "ANSIBLE_RUN_TAGS": "all",
                "ANSIBLE_SKIP_TAGS": "always",
                "ANSIBLE_BECOME": "true",
                "ANSIBLE_COLLECTIONS_PATH": "/nonexistent-fixture-collections",
            }):
                environment = self.ansible_environment(case)
                # Fail before execution if the isolation regresses, including
                # when the test suite is invoked as root.
                for key in ("ANSIBLE_RUN_TAGS", "ANSIBLE_SKIP_TAGS", "ANSIBLE_BECOME"):
                    self.assertNotIn(key, environment)
                self.assertEqual(environment["ANSIBLE_CONFIG"], str(case["case"] / "ansible.cfg"))
                self.assertEqual(environment["ANSIBLE_COLLECTIONS_PATH"], str(FIXTURE_COLLECTIONS))
                self.assert_stub_resolution(case)
                result = self.run_case(case, False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [])
            self.assertEqual(case["limine_path"].read_text(encoding="utf-8"), ORIGINAL_LIMINE)
            self.assertEqual((case["dropin_dir"] / "nvidia_btrfs.conf").read_text(encoding="utf-8"), FALSE_DROPIN)

    def test_unexpected_run_tags_fail_before_production_tasks(self):
        with tempfile.TemporaryDirectory(prefix="ansible-nvidia-tag-guard-") as directory:
            case = self.prepare_case(Path(directory), "unexpected-tags")
            self.assert_stub_resolution(case)
            result = self.run_case(case, False, tags="all")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NVIDIA fixture safety boundary violated", result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [])
            self.assertFalse(case["dropin_dir"].exists())
            self.assertEqual(case["limine_path"].read_text(encoding="utf-8"), ORIGINAL_LIMINE)

    def test_non_boolean_values_fail_before_any_tagged_mutation(self):
        with tempfile.TemporaryDirectory(prefix="ansible-nvidia-invalid-") as directory:
            parent = Path(directory)
            for label, value in INVALID_VALUES:
                with self.subTest(value=label):
                    case = self.prepare_case(parent, label)
                    self.assert_stub_resolution(case)
                    result = self.run_case(case, value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "use_nvidia must be a YAML boolean (true or false).",
                        result.stdout + result.stderr,
                    )
                    self.assertEqual(self.package_calls(result.stdout), [])
                    self.assertEqual(case["limine_path"].read_text(encoding="utf-8"), ORIGINAL_LIMINE)
                    self.assertFalse(case["dropin_dir"].exists())
                    self.assertNotIn(HANDLER_MARKER, result.stdout)


if __name__ == "__main__":
    unittest.main()
