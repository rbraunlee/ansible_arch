"""Check the dotfiles task's argv against GNU Stow's real CLI parser only.

No Stow command or Ansible task is executed. STOW_PARSER_SOURCE may point to
the read-only guest Stow 2.4.1 script; otherwise the installed script is used.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import unittest

from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("STOW_PARSER_SOURCE", "/usr/bin/stow"))


class DotfilesStowArgvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        match = re.search(r"(?ms)^sub parse_options \{.*?(?=^sub sanitize_path_options \{)", source)
        if match is None:
            raise AssertionError(f"GNU Stow parse_options not found in {SOURCE}")
        cls.parser = (
            "use strict; use warnings; use Getopt::Long qw(GetOptionsFromArray); "
            "use JSON::PP qw(encode_json);\n"
            + match.group()
            + "my ($opts, $unstow, $stow) = parse_options(@ARGV); "
            "print encode_json({options => $opts, unstow => $unstow, stow => $stow});\n"
        )
        tasks = yaml.safe_load((ROOT / "tasks/dotfiles.yml").read_text())
        cls.task = next(task for task in tasks if task["name"] == "Symlink dotfiles using Stow")

    def rendered_argv(self, updated):
        checkout = "/home/lintqa/checkout space"
        package = "app space"
        vars_ = {
            "dotfiles_checkout": {"changed": updated},
            "dotfiles": {"dest": checkout},
            "username": "lintqa",
            "item": [
                {"item": "common"},
                {"path": f"{checkout}/common/{package}"},
            ],
        }
        environment = Environment()
        environment.filters.update(FilterModule().filters())
        return [environment.from_string(arg).render(vars_) for arg in self.task["ansible.builtin.command"]["argv"]]

    def parse(self, argv):
        result = subprocess.run(
            ["perl", "-e", self.parser, "--", *argv[1:]],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_space_containing_package_is_selected_for_restow_or_stow(self):
        for updated in (True, False):
            with self.subTest(updated=updated):
                argv = self.rendered_argv(updated)
                self.assertEqual(argv[0], "stow")
                parsed = self.parse(argv)
                self.assertEqual(parsed["options"]["dir"], "/home/lintqa/checkout space/common")
                self.assertEqual(parsed["options"]["target"], "/home/lintqa")
                self.assertEqual(parsed["stow"], ["app space"])
                self.assertEqual(parsed["unstow"], ["app space"] if updated else [])

    def test_guest_failure_is_caused_by_end_of_options_marker(self):
        # Actual failed guest argv (excluding program); Stow's <> callback
        # receives no package after the Getopt::Long -- terminator.
        guest_argv = [
            "stow", "--restow", "-v", "-d",
            "/home/lintqa_1792247367/checkout space/common", "-t",
            "/home/lintqa_1792247367", "--", "app space",
        ]
        parsed = self.parse(guest_argv)
        self.assertEqual(parsed["stow"], [])
        self.assertEqual(parsed["unstow"], [])

    def test_command_failures_remain_visible_and_link_changes_are_reported(self):
        self.assertNotIn("failed_when", self.task)
        self.assertEqual(
            self.task["changed_when"],
            "stow_out.stderr is search('(?m)^(?:LINK|UNLINK):')",
        )


if __name__ == "__main__":
    unittest.main()
