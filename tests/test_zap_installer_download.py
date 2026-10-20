"""Host-safe contract check for the Zap installer download configuration.

Only parse task YAML; never run a playbook, download, or installer on the host.
"""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ZapInstallerDownloadTest(unittest.TestCase):
    def test_precreated_installer_is_replaced_with_downloaded_bytes(self):
        tasks = yaml.safe_load((ROOT / "tasks/zap.yml").read_text())
        install = next(task for task in tasks if task["name"] == "Install Zap plugin manager when absent")
        create = next(task for task in install["block"] if task["name"] == "Create temporary Zap installer file")
        download = next(task for task in install["block"] if task["name"] == "Download Zap installer")

        self.assertEqual(create["ansible.builtin.tempfile"]["state"], "file")
        self.assertEqual(download["ansible.builtin.get_url"]["dest"], "{{ zap_installer_tmp.path }}")
        # get_url's default conditional request can return 304 for the newly
        # created empty tempfile when its mtime is newer than the server file.
        self.assertIs(download["ansible.builtin.get_url"].get("force"), True)


if __name__ == "__main__":
    unittest.main()
