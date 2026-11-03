"""Isolated behavioral coverage for ticket #10 optional profiles and overlay."""

import copy
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "optional_profiles"
FIXTURE_PLAYBOOK = FIXTURE_ROOT / "playbook.yml"
FIXTURE_COLLECTIONS = ROOT / "tests" / "fixtures" / "optional_profiles_stub_collections"
OVERLAY_HELPER = ROOT / "tasks" / "hyprland_optional_overlay.py"
OVERLAY_TASK = ROOT / "tasks" / "hyprland_optional_overlay.yml"
CONTRACT_PATCH = ROOT / "docs" / "hyprland-optional-overlay-v2.patch"
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
OVERLAY_MARKER = "ansible_arch_optional_overlay_v2"
LOADER_SHA256 = "4f8a1cf397ba28160395488d26470c16a87100cc8632ce12a4e78e80297b93c4"
LUA = shutil.which("lua") or shutil.which("lua5.4")

DEFAULT_PROFILES = {
    "tmux_focus": False,
    "swappy": False,
    "media_recording": False,
    "archive_helpers": False,
    "mirror_tools": False,
    "voxtype": {"enabled": True, "provider": "auto"},
}
PACKAGE_SETS = {
    "tmux_focus": ["tmux"],
    "swappy": ["swappy"],
    "media_recording": ["yt-dlp", "ffmpeg", "wf-recorder"],
    "archive_helpers": ["unrar", "unzip", "ncompress", "7zip"],
    "mirror_tools": ["reflector", "rate-mirrors", "expac"],
    "voxtype": ["wtype", "pipewire-alsa"],
}


class OptionalProfilePackagesTest(unittest.TestCase):
    maxDiff = None

    def prepare_case(self, parent, name):
        case = parent / name
        case.mkdir()
        return {"root": case}

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

    def variables(self, case, *, profiles=None, use_nvidia=True, aur_packages=None):
        return {
            "ansible_become": False,
            "fixture_runtime_root": str(case["root"]),
            "username": "rbl",
            "aur_builder": "fixture_aur_builder",
            "use_nvidia": use_nvidia,
            "optional_profiles": copy.deepcopy(profiles or DEFAULT_PROFILES),
            "optional_profile_package_sets": copy.deepcopy(PACKAGE_SETS),
            "optional_voxtype_aur_packages": aur_packages or {
                "cpu": ["voxtype-bin"],
                "cuda": ["voxtype-cuda"],
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

    def run_case(self, case, *, profiles=None, use_nvidia=True, aur_packages=None, tags="optional"):
        self.assert_stub_resolution(case)
        command = [
            "ansible-playbook",
            "-i",
            "localhost,",
            "-v",
            "--tags",
            tags,
            "--extra-vars",
            json.dumps(
                self.variables(
                    case, profiles=profiles, use_nvidia=use_nvidia, aur_packages=aur_packages
                )
            ),
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

    @staticmethod
    def package_calls(output):
        return [json.loads(match) for match in PACKAGE_RESULT_PATTERN.findall(output)]

    @staticmethod
    def aur_calls(output):
        return [json.loads(match) for match in AUR_RESULT_PATTERN.findall(output)]

    def assert_safe_failure(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message.lower(), (result.stdout + result.stderr).lower())
        self.assertEqual(self.package_calls(result.stdout), [])
        self.assertEqual(self.aur_calls(result.stdout), [])

    def test_default_profile_installs_nvidia_voxtype_and_is_repeatable(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-default-") as directory:
            case = self.prepare_case(Path(directory), "default")
            first = self.run_case(case)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(self.package_calls(first.stdout), [["wtype", "pipewire-alsa"]])
            self.assertEqual(self.aur_calls(first.stdout), [["voxtype-cuda"]])
            self.assertIn("changed=0", first.stdout)

            second = self.run_case(case)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(self.package_calls(second.stdout), [["wtype", "pipewire-alsa"]])
            self.assertEqual(self.aur_calls(second.stdout), [["voxtype-cuda"]])
            self.assertIn("changed=0", second.stdout)

    def test_selected_profiles_install_only_their_grouped_providers(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        for profile in ("tmux_focus", "swappy", "media_recording", "archive_helpers", "mirror_tools"):
            profiles[profile] = True
        profiles["voxtype"] = {"enabled": True, "provider": "cuda"}
        expected_packages = [
            "tmux", "swappy", "yt-dlp", "ffmpeg", "wf-recorder", "unrar", "unzip",
            "ncompress", "7zip", "reflector", "rate-mirrors", "expac", "wtype",
            "pipewire-alsa",
        ]
        with tempfile.TemporaryDirectory(prefix="ansible-optional-enabled-") as directory:
            case = self.prepare_case(Path(directory), "enabled")
            result = self.run_case(case, profiles=profiles)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [expected_packages])
            self.assertEqual(self.aur_calls(result.stdout), [["voxtype-cuda"]])

    def test_default_non_nvidia_profile_uses_the_cpu_provider(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-cpu-default-") as directory:
            case = self.prepare_case(Path(directory), "cpu-default")
            result = self.run_case(case, use_nvidia=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [["wtype", "pipewire-alsa"]])
            self.assertEqual(self.aur_calls(result.stdout), [["voxtype-bin"]])

    def test_explicit_cpu_provider_stays_cpu_on_nvidia(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        profiles["voxtype"] = {"enabled": True, "provider": "cpu"}
        with tempfile.TemporaryDirectory(prefix="ansible-optional-cpu-explicit-") as directory:
            case = self.prepare_case(Path(directory), "cpu-explicit")
            result = self.run_case(case, profiles=profiles, use_nvidia=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [["wtype", "pipewire-alsa"]])
            self.assertEqual(self.aur_calls(result.stdout), [["voxtype-bin"]])

    def test_explicit_voxtype_disable_skips_its_packages(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        profiles["voxtype"] = {"enabled": False, "provider": "none"}
        with tempfile.TemporaryDirectory(prefix="ansible-optional-disabled-") as directory:
            case = self.prepare_case(Path(directory), "disabled")
            result = self.run_case(case, profiles=profiles)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.package_calls(result.stdout), [])
            self.assertEqual(self.aur_calls(result.stdout), [])

    def test_invalid_profiles_fail_before_package_mutation(self):
        invalid_cases = {
            "string-flag": {**DEFAULT_PROFILES, "tmux_focus": "true"},
            "unknown-key": {**DEFAULT_PROFILES, "unknown": False},
            "enabled-none": {**DEFAULT_PROFILES, "voxtype": {"enabled": True, "provider": "none"}},
            "disabled-cuda": {**DEFAULT_PROFILES, "voxtype": {"enabled": False, "provider": "cuda"}},
            "disabled-auto": {**DEFAULT_PROFILES, "voxtype": {"enabled": False, "provider": "auto"}},
            "unknown-provider": {**DEFAULT_PROFILES, "voxtype": {"enabled": True, "provider": "rocm"}},
        }
        with tempfile.TemporaryDirectory(prefix="ansible-optional-invalid-") as directory:
            parent = Path(directory)
            for label, profiles in invalid_cases.items():
                with self.subTest(label=label):
                    case = self.prepare_case(parent, label)
                    self.assert_safe_failure(self.run_case(case, profiles=profiles), "Optional")

    def test_invalid_provider_package_mapping_fails_before_package_mutation(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-invalid-provider-map-") as directory:
            case = self.prepare_case(Path(directory), "invalid-provider-map")
            self.assert_safe_failure(
                self.run_case(case, aur_packages={"cuda": ["voxtype-cuda"]}),
                "Voxtype provider packages",
            )

    def test_cuda_profile_rejects_non_nvidia_before_package_mutation(self):
        profiles = copy.deepcopy(DEFAULT_PROFILES)
        profiles["voxtype"] = {"enabled": True, "provider": "cuda"}
        with tempfile.TemporaryDirectory(prefix="ansible-optional-cuda-non-nvidia-") as directory:
            case = self.prepare_case(Path(directory), "cuda-non-nvidia")
            self.assert_safe_failure(
                self.run_case(case, profiles=profiles, use_nvidia=False),
                "Voxtype provider cuda requires use_nvidia: true.",
            )

    def test_unexpected_tags_fail_before_production_tasks(self):
        with tempfile.TemporaryDirectory(prefix="ansible-optional-tags-") as directory:
            case = self.prepare_case(Path(directory), "unexpected-tags")
            self.assert_safe_failure(self.run_case(case, tags="all"), "fixture safety boundary")


class CanonicalOverlayHelperTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.username = pwd.getpwuid(os.geteuid()).pw_name

    def run_helper(
        self, home, *, voxtype=False, nvidia=False, check=False, xdg_home=None, test_mode=True
    ):
        environment = os.environ.copy()
        if test_mode:
            environment["ANSIBLE_ARCH_OPTIONAL_OVERLAY_TEST"] = "1"
        if xdg_home is not None:
            environment["XDG_CONFIG_HOME"] = str(xdg_home)
        command = [
            sys.executable,
            str(OVERLAY_HELPER),
            "--home", str(home),
            "--username", self.username,
            "--voxtype-enabled", str(voxtype).lower(),
            "--nvidia-environment", str(nvidia).lower(),
        ]
        if check:
            command.append("--check")
        return subprocess.run(command, env=environment, capture_output=True, text=True, check=False)

    def test_canonical_home_overlay_ignores_nondefault_xdg_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="ansible-overlay-canonical-") as directory:
            root = Path(directory)
            home = root / "home" / self.username
            home.mkdir(parents=True)
            nondefault_xdg = root / "other-xdg"
            first = self.run_helper(home, voxtype=True, nvidia=False, xdg_home=nondefault_xdg)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue(json.loads(first.stdout)["changed"])
            canonical = home / ".config" / "ansible_arch" / "hyprland-optional.lua"
            self.assertTrue(canonical.is_file())
            self.assertFalse(nondefault_xdg.exists())
            self.assertIn("voxtype_enabled = true", canonical.read_text(encoding="utf-8"))
            self.assertIn("nvidia_environment = false", canonical.read_text(encoding="utf-8"))

            repeat = self.run_helper(home, voxtype=True, nvidia=False, xdg_home=nondefault_xdg)
            self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
            self.assertFalse(json.loads(repeat.stdout)["changed"])

    def test_parent_config_and_overlay_directory_symlinks_cannot_escape(self):
        with tempfile.TemporaryDirectory(prefix="ansible-overlay-symlink-") as directory:
            root = Path(directory)
            for label in ("home", "config", "overlay-directory"):
                with self.subTest(ancestor=label):
                    case = root / label
                    escaped = case / "escaped-unowned"
                    escaped.mkdir(parents=True)
                    home_parent = case / "home"
                    home = home_parent / self.username
                    if label == "home":
                        home_parent.mkdir()
                        home.symlink_to(escaped, target_is_directory=True)
                    elif label == "config":
                        home.mkdir(parents=True)
                        (home / ".config").symlink_to(escaped, target_is_directory=True)
                    else:
                        overlay_parent = home / ".config"
                        overlay_parent.mkdir(parents=True)
                        (overlay_parent / "ansible_arch").symlink_to(escaped, target_is_directory=True)

                    result = self.run_helper(home)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-symlink directory", result.stderr)
                    self.assertFalse((escaped / "hyprland-optional.lua").exists())

    def test_unowned_file_is_preserved_and_check_mode_writes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="ansible-overlay-preserve-") as directory:
            root = Path(directory)
            home = root / "home" / self.username
            overlay = home / ".config" / "ansible_arch" / "hyprland-optional.lua"
            overlay.parent.mkdir(parents=True)
            original = "return { voxtype_enabled = true, nvidia_environment = true }\n"
            overlay.write_text(original, encoding="utf-8")
            result = self.run_helper(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unowned optional overlay", result.stderr)
            self.assertEqual(overlay.read_text(encoding="utf-8"), original)

            new_home = root / "fresh-home" / self.username
            new_home.mkdir(parents=True)
            check = self.run_helper(new_home, check=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertTrue(json.loads(check.stdout)["changed"])
            self.assertFalse((new_home / ".config").exists())

    def test_prior_managed_marker_migrates_to_v2_but_embedded_marker_does_not(self):
        with tempfile.TemporaryDirectory(prefix="ansible-overlay-migration-") as directory:
            root = Path(directory)
            home = root / "home" / self.username
            overlay = home / ".config" / "ansible_arch" / "hyprland-optional.lua"
            overlay.parent.mkdir(parents=True)
            overlay.write_text(
                "-- ansible_arch_optional_overlay_v1\n"
                "return { voxtype_enabled = false, nvidia_environment = false }\n",
                encoding="utf-8",
            )
            migrated = self.run_helper(home, voxtype=True, nvidia=True)
            self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
            payload = overlay.read_text(encoding="utf-8")
            self.assertTrue(payload.startswith("-- " + OVERLAY_MARKER + "\n"))
            self.assertIn("voxtype_enabled = true", payload)

            overlay.write_text(
                "-- owner content\n-- ansible_arch_optional_overlay_v1\n"
                "return { voxtype_enabled = false, nvidia_environment = false }\n",
                encoding="utf-8",
            )
            preserved = self.run_helper(home)
            self.assertNotEqual(preserved.returncode, 0)
            self.assertIn("unowned optional overlay", preserved.stderr)
            self.assertTrue(overlay.read_text(encoding="utf-8").startswith("-- owner content\n"))

    def test_noncanonical_home_is_rejected_outside_the_isolated_test_mode(self):
        with tempfile.TemporaryDirectory(prefix="ansible-overlay-canonical-reject-") as directory:
            home = Path(directory) / "home" / self.username
            home.mkdir(parents=True)
            result = self.run_helper(home, test_mode=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical configured-user home", result.stderr)
            self.assertFalse((home / ".config").exists())

    def test_production_task_has_no_user_writable_path_or_marker_override(self):
        task = OVERLAY_TASK.read_text(encoding="utf-8")
        self.assertIn('"/home/{{ username }}"', task)
        self.assertNotIn("optional_hyprland_overlay", task)
        self.assertNotIn("ANSIBLE_ARCH_OPTIONAL_OVERLAY_TEST", task)
        self.assertIn("hyprland_optional_overlay.py", task)


@unittest.skipUnless(LUA, "Lua interpreter is unavailable")
class HyprlandContractPatchTest(unittest.TestCase):
    def baseline(self):
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

    def patched_tree(self, root):
        source = root / "linux" / "hypr" / ".config" / "hypr" / "hyprland.lua"
        source.parent.mkdir(parents=True)
        source.write_text(self.baseline(), encoding="utf-8")
        result = subprocess.run(
            ["patch", "-p1", "-d", str(root)],
            input=CONTRACT_PATCH.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        loader = source.with_name("ansible_arch_optional_overlay_v2.lua")
        self.assertEqual(hashlib.sha256(loader.read_bytes()).hexdigest(), LOADER_SHA256)
        return source, loader

    @staticmethod
    def lua_harness():
        return """\
hl = {}
function hl.on(_, callback) callback() end
function hl.exec_cmd(command) print("EXEC:" .. command) end
function hl.env(name, value) print("ENV:" .. name .. "=" .. value) end
function hl.bind(key, _) print("BIND:" .. key) end
function hl.define_submap(name, callback) print("SUBMAP:" .. name); callback() end
hl.dsp = {
  exec_cmd = function(command) return command end,
  submap = function(name) return name end,
}
dofile(arg[1])
"""

    def run_patched_config(self, *, overlay=None, xdg_config_home=None):
        with tempfile.TemporaryDirectory(prefix="ansible-hyprland-contract-") as directory:
            root = Path(directory)
            source, loader = self.patched_tree(root)
            home = root / "home" / "fixture-user"
            loader_target = home / ".config" / "hypr" / loader.name
            loader_target.parent.mkdir(parents=True)
            shutil.copy2(loader, loader_target)
            if overlay is not None:
                overlay_target = home / ".config" / "ansible_arch" / "hyprland-optional.lua"
                overlay_target.parent.mkdir(parents=True)
                overlay_target.write_text(overlay, encoding="utf-8")
            harness = root / "harness.lua"
            harness.write_text(self.lua_harness(), encoding="utf-8")
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment["XDG_CONFIG_HOME"] = str(xdg_config_home or (root / "nondefault-xdg"))
            return subprocess.run(
                [LUA, str(harness), str(source)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def assert_guarded_start(self, output):
        startup = "EXEC:sh -c 'systemctl --user import-environment"
        self.assertEqual(output.count("systemctl --user start voxtype.service"), 1)
        self.assertIn(startup, output)
        self.assertLess(
            output.index("systemctl --user import-environment"),
            output.index("systemctl --user start voxtype.service"),
        )
        self.assertNotIn("voxtype -q daemon", output)
        self.assertNotIn("systemctl --user restart", output)

    def test_exact_patch_absent_overlay_preserves_standalone_defaults(self):
        result = self.run_patched_config()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ENV:LIBVA_DRIVER_NAME=nvidia", result.stdout)
        self.assertIn("ENV:__GLX_VENDOR_LIBRARY_NAME=nvidia", result.stdout)
        self.assertIn("BIND:SUPER + CTRL + d", result.stdout)
        self.assertIn("SUBMAP:voxtype_suppress", result.stdout)
        self.assert_guarded_start(result.stdout)

    def test_exact_patch_true_and_false_overlays_gate_runtime_behavior(self):
        enabled = self.run_patched_config(
            overlay="return { voxtype_enabled = true, nvidia_environment = true }\n"
        )
        self.assertEqual(enabled.returncode, 0, enabled.stdout + enabled.stderr)
        self.assertIn("ENV:LIBVA_DRIVER_NAME=nvidia", enabled.stdout)
        self.assertIn("ENV:__GLX_VENDOR_LIBRARY_NAME=nvidia", enabled.stdout)
        self.assertIn("BIND:SUPER + CTRL + d", enabled.stdout)
        self.assertIn("SUBMAP:voxtype_suppress", enabled.stdout)
        self.assert_guarded_start(enabled.stdout)

        disabled = self.run_patched_config(
            overlay="return { voxtype_enabled = false, nvidia_environment = false }\n"
        )
        self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
        self.assertNotIn("ENV:LIBVA_DRIVER_NAME=nvidia", disabled.stdout)
        self.assertNotIn("BIND:SUPER + CTRL + d", disabled.stdout)
        self.assertNotIn("SUBMAP:voxtype_suppress", disabled.stdout)
        self.assertNotIn("systemctl", disabled.stdout)

    def test_exact_patch_rejects_malformed_overlay_under_nondefault_xdg(self):
        result = self.run_patched_config(
            overlay="return { voxtype_enabled = 'true', nvidia_environment = false }\n",
            xdg_config_home=Path("/tmp/nondefault-xdg-for-test"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid ansible_arch optional overlay values", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
