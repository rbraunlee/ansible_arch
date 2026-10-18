"""Exercise the real .bashrc policy CLI using only synthetic private fixtures."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tasks/bashrc_policy.py"


class BashrcPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bashrc-policy-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.home = base / "home"
        self.home.mkdir(mode=0o700)
        self.skel = base / "skel.bashrc"
        self.skel.write_bytes(b"Arch default\n")
        package = base / "checkout" / "linux" / "bash"
        package.mkdir(parents=True)
        self.source = package / ".bashrc"
        self.source.write_bytes(b"managed shell\n")
        self.packages = [str(package)]
        self.target = self.home / ".bashrc"
        self.backups = self.home / ".bashrc-backups"

    def run_policy(self, *, packages=None, mode=None, cwd=None):
        process = subprocess.run(
            [sys.executable, str(POLICY), *([mode] if mode else []), "--home", str(self.home),
             "--skel", str(self.skel), "--packages-json",
             json.dumps(self.packages if packages is None else packages)],
            capture_output=True, text=True, cwd=cwd or self.home,
        )
        return process

    def outcome(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_missing_target_does_not_create_backup_or_note(self):
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertFalse(self.backups.exists())

    def test_untouched_default_is_removed_without_persistent_backup(self):
        self.target.write_bytes(b"Arch default\n")
        self.assertTrue(self.outcome(self.run_policy())["changed"])
        self.assertFalse(self.target.exists())
        self.assertFalse(self.backups.exists())

    def test_custom_file_is_preserved_and_note_does_not_claim_stow_succeeded(self):
        self.target.write_bytes(b"secret customized shell\n")
        self.target.chmod(0o640)
        outcome = self.outcome(self.run_policy())
        self.assertTrue(outcome["changed"])
        backup = Path(outcome["backup"])
        note = Path(outcome["note"])
        self.assertFalse(self.target.exists())
        self.assertEqual(backup.read_bytes(), b"secret customized shell\n")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o640)
        self.assertEqual(backup.stat().st_uid, os.geteuid())
        self.assertEqual(self.backups.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.backups.stat().st_uid, os.geteuid())
        self.assertEqual(note.stat().st_mode & 0o777, 0o600)
        text = note.read_text()
        self.assertIn(str(self.target), text)
        self.assertIn(str(backup), text)
        self.assertIn(str(self.source), text)
        self.assertIn("pending", text.lower())
        self.assertNotIn("secret customized shell", text)
        self.assertNotIn("secret customized shell", json.dumps(outcome))

    def test_correct_link_and_custom_backup_rerun_are_stable(self):
        self.target.write_bytes(b"my shell\n")
        first = self.outcome(self.run_policy())
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.target.symlink_to(self.source)
        before = sorted(self.backups.iterdir())
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertEqual(sorted(self.backups.iterdir()), before)
        self.assertEqual(Path(first["backup"]).read_bytes(), b"my shell\n")
        self.assertIn("pending", Path(first["note"]).read_text())

    def test_verified_stow_link_finalizes_custom_backup_note_once(self):
        self.target.write_bytes(b"custom shell\n")
        prepared = self.outcome(self.run_policy())
        note = Path(prepared["note"])
        self.assertIn("Status: replacement pending", note.read_text())
        self.target.symlink_to(self.source)  # Synthetic fixture: no Stow execution.
        self.assertTrue(self.outcome(self.run_policy(mode="--finalize"))["changed"])
        finalized = note.read_text()
        self.assertIn("Status: Stow .bashrc link verified; replacement completed", finalized)
        self.assertNotIn("Status: replacement pending", finalized)
        mtime = note.stat().st_mtime_ns
        self.assertFalse(self.outcome(self.run_policy(mode="--finalize"))["changed"])
        self.assertEqual(note.stat().st_mtime_ns, mtime)
        self.assertEqual(len(list(self.backups.iterdir())), 2)

    def test_retry_finalizes_pending_note_without_new_backup(self):
        self.target.write_bytes(b"custom shell\n")
        prepared = self.outcome(self.run_policy())
        self.assertNotEqual(self.run_policy(mode="--finalize").returncode, 0)
        self.assertIn("pending", Path(prepared["note"]).read_text())
        self.target.symlink_to(self.source)
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertTrue(self.outcome(self.run_policy(mode="--finalize"))["changed"])
        before = sorted(self.backups.iterdir())
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertFalse(self.outcome(self.run_policy(mode="--finalize"))["changed"])
        self.assertEqual(sorted(self.backups.iterdir()), before)

    def test_missing_or_wrong_stow_link_cannot_finalize_note(self):
        self.target.write_bytes(b"preserve me\n")
        prepared = self.outcome(self.run_policy())
        note = Path(prepared["note"])
        original = note.read_bytes()
        self.assertNotEqual(self.run_policy(mode="--finalize").returncode, 0)
        other = self.home.parent / "wrong-source"
        other.write_bytes(b"not Stow\n")
        self.target.symlink_to(other)
        self.assertNotEqual(self.run_policy(mode="--finalize").returncode, 0)
        self.assertEqual(note.read_bytes(), original)
        self.assertEqual(Path(prepared["backup"]).read_bytes(), b"preserve me\n")

    def test_new_custom_file_gets_unique_backup_without_rewriting_previous_one(self):
        self.target.write_bytes(b"first edition\n")
        first = self.outcome(self.run_policy())
        self.target.write_bytes(b"second edition\n")
        second = self.outcome(self.run_policy())
        self.assertNotEqual(first["backup"], second["backup"])
        self.assertEqual(Path(first["backup"]).read_bytes(), b"first edition\n")
        self.assertEqual(Path(second["backup"]).read_bytes(), b"second edition\n")
        self.assertEqual(len(list(self.backups.iterdir())), 4)

    def test_no_selected_source_never_removes_regular_target(self):
        self.target.write_bytes(b"existing\n")
        self.source.unlink()
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertEqual(self.target.read_bytes(), b"existing\n")
        self.assertFalse(self.backups.exists())

    def test_local_ignore_cannot_remove_an_untouched_default(self):
        self.target.write_bytes(b"Arch default\n")
        (self.source.parent / ".stow-local-ignore").write_text(r"^\.bashrc$" + "\n")
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.target.read_bytes(), b"Arch default\n")
        self.assertFalse(self.backups.exists())

    def test_global_and_stowrc_configuration_cannot_remove_customized_target(self):
        other = self.home.parent / "checkout" / "common" / "other"
        other.mkdir(parents=True)
        locations = (self.home / ".stow-global-ignore",
                     self.home / ".stowrc",
                     self.source.parent.parent / ".stow-global-ignore",
                     other / ".stowrc",
                     other / ".stow-global-ignore",
                     self.home.parent / ".stowrc")
        self.target.write_bytes(b"important configuration\n")
        for config in locations:
            with self.subTest(config=config):
                config.write_text("--ignore=.bashrc\n")
                outcome = self.run_policy(packages=self.packages + [str(other)], cwd=self.home.parent)
                self.assertNotEqual(outcome.returncode, 0, outcome.stdout)
                self.assertEqual(self.target.read_bytes(), b"important configuration\n")
                self.assertFalse(self.backups.exists())
                config.unlink()

    def test_unmanaged_bashrc_is_not_migrated_despite_stow_config(self):
        self.source.unlink()
        self.target.write_bytes(b"Arch default\n")
        (self.home / ".stowrc").write_text("--ignore=.bashrc\n")
        self.assertFalse(self.outcome(self.run_policy())["changed"])
        self.assertFalse(self.outcome(self.run_policy(mode="--finalize"))["changed"])
        self.assertEqual(self.target.read_bytes(), b"Arch default\n")

    def test_wrong_link_directory_and_ambiguous_sources_are_rejected(self):
        another = self.home.parent / "elsewhere"
        another.write_bytes(b"other\n")
        self.target.symlink_to(another)
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertTrue(self.target.is_symlink())
        self.target.unlink()
        self.target.mkdir()
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertTrue(self.target.is_dir())
        self.target.rmdir()
        self.target.write_bytes(b"keep me\n")
        other_package = self.home.parent / "checkout" / "common" / "other"
        other_package.mkdir(parents=True)
        (other_package / ".bashrc").write_bytes(b"another managed source\n")
        self.assertNotEqual(self.run_policy(packages=self.packages + [str(other_package)]).returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"keep me\n")
        self.assertFalse(self.backups.exists())

    def test_unsafe_backup_directory_and_missing_skel_do_not_discard_custom(self):
        self.target.write_bytes(b"save this\n")
        self.backups.symlink_to(self.home.parent)
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"save this\n")
        self.backups.unlink()
        self.skel.unlink()
        result = self.outcome(self.run_policy())
        self.assertEqual(Path(result["backup"]).read_bytes(), b"save this\n")

    def test_selected_symlink_source_is_not_adopted(self):
        self.target.write_bytes(b"existing\n")
        self.source.unlink()
        self.source.symlink_to(self.skel)
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"existing\n")

    def test_failed_backup_copy_or_note_retains_customized_original(self):
        spec = importlib.util.spec_from_file_location("bashrc_policy", POLICY)
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        self.target.write_bytes(b"preserve on disk failure\n")
        real_open = os.open

        def fail_backup(path, *args, **kwargs):
            if str(path).startswith(str(self.backups)):
                raise OSError("synthetic backup storage failure")
            return real_open(path, *args, **kwargs)

        with patch.object(policy.os, "open", side_effect=fail_backup):
            with self.assertRaises(OSError):
                policy.prepare(self.home, self.skel, self.packages)
        self.assertEqual(self.target.read_bytes(), b"preserve on disk failure\n")
        self.assertEqual(list(self.backups.iterdir()), [])

        def fail_note(path, *args, **kwargs):
            if str(path).endswith(".note"):
                raise OSError("synthetic note storage failure")
            return real_open(path, *args, **kwargs)

        with patch.object(policy.os, "open", side_effect=fail_note):
            with self.assertRaises(OSError):
                policy.prepare(self.home, self.skel, self.packages)
        self.assertEqual(self.target.read_bytes(), b"preserve on disk failure\n")
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_failed_final_note_write_leaves_backup_and_pending_note(self):
        self.target.write_bytes(b"saved original\n")
        prepared = self.outcome(self.run_policy())
        self.target.symlink_to(self.source)
        spec = importlib.util.spec_from_file_location("bashrc_policy", POLICY)
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        with patch.object(policy.os, "replace", side_effect=OSError("synthetic note write failure")):
            with self.assertRaises(OSError):
                policy.finalize(self.home, self.skel, self.packages)
        self.assertIn("Status: replacement pending", Path(prepared["note"]).read_text())
        self.assertEqual(Path(prepared["backup"]).read_bytes(), b"saved original\n")

    def test_task_calls_real_policy_for_all_selected_packages_before_stow(self):
        tasks = yaml.safe_load((ROOT / "tasks/dotfiles.yml").read_text())
        names = [task["name"] for task in tasks]
        policy = tasks[names.index("Prepare selected .bashrc for Stow")]
        self.assertLess(names.index(policy["name"]), names.index("Symlink dotfiles using Stow"))
        argv = policy["ansible.builtin.command"]["argv"]
        self.assertIn("ansible.builtin.first_found", " ".join(argv))
        self.assertIn("--packages-json", argv)
        self.assertIn("--skel", argv)
        self.assertIn("--home", argv)
        self.assertIn("found_dotfiles.results", " ".join(argv))
        self.assertEqual(policy["become_user"], "{{ username }}")
        self.assertTrue(policy["become"])
        self.assertNotIn("failed_when", policy)
        self.assertEqual(policy["ansible.builtin.command"]["chdir"], "/home/{{ username }}")
        stow = tasks[names.index("Symlink dotfiles using Stow")]
        self.assertEqual(stow["ansible.builtin.command"]["chdir"], "/home/{{ username }}")
        finalize = tasks[names.index("Finalize verified .bashrc replacement note")]
        self.assertGreater(names.index(finalize["name"]), names.index(stow["name"]))
        self.assertEqual(finalize["ansible.builtin.command"]["chdir"], "/home/{{ username }}")
        self.assertIn("--finalize", finalize["ansible.builtin.command"]["argv"])
        self.assertNotIn("failed_when", finalize)
        for task in (policy, stow, finalize):
            self.assertEqual(task["environment"]["HOME"], "/home/{{ username }}")
        report = tasks[names.index("Report customized .bashrc backup and recovery note")]
        self.assertIn(".backup", report["ansible.builtin.debug"]["msg"])
        self.assertIn(".note", report["ansible.builtin.debug"]["msg"])


if __name__ == "__main__":
    unittest.main()
