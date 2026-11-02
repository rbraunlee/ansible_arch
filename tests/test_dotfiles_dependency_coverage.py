"""Static coverage checks for the reviewed dotfiles dependency matrix."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "dotfiles-dependency-coverage.md"
DOTFILES_SOURCE_REVISION = "33e2c02de1451901ec512dbf6add16ee5d0fe419"
LOCAL_DOTFILES_REVISION = "0eee62fc889970b956f869008dbc5f6e11e7fa1f"
TOP_LEVEL_STOW_PACKAGES = {
    "common/agent-skills",
    "common/claude",
    "common/codex",
    "common/cursor",
    "common/ghostty",
    "common/nvim",
    "common/opencode",
    "common/scripts",
    "common/starship",
    "common/t3",
    "common/tmux",
    "common/wallpaper",
    "common/zsh",
    "linux/bash",
    "linux/hypr",
    "linux/swappy",
    "linux/voxtype",
    "linux/waybar",
    "linux/wofi",
    "linux/zsh",
}


class DotfilesDependencyCoverageTest(unittest.TestCase):
    def setUp(self):
        self.matrix = MATRIX.read_text(encoding="utf-8")

    def test_matrix_pins_the_audited_and_local_source_revisions(self):
        self.assertIn(DOTFILES_SOURCE_REVISION, self.matrix)
        self.assertIn(LOCAL_DOTFILES_REVISION, self.matrix)

    def test_matrix_covers_every_audited_top_level_stow_package(self):
        for package in TOP_LEVEL_STOW_PACKAGES:
            self.assertIn(f"`{package}`", self.matrix)

    def test_matrix_keeps_optional_and_hardware_requirements_out_of_ticket_nine_defaults(self):
        self.assertIn("Ticket #10", self.matrix)
        self.assertIn("`voxtype-cuda`, `wtype`, and `pipewire-alsa`", self.matrix)
        self.assertIn("`tmux`", self.matrix)


if __name__ == "__main__":
    unittest.main()
