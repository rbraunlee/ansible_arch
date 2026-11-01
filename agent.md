
# Arch Workstation Deployment - Technical Documentation

Detailed technical documentation for the Ansible-based Arch Linux workstation deployment system.

## Architecture

### Execution Flow

```
main.yml
├── tasks/system.yml     (1/5) - System foundation
├── tasks/desktop.yml    (2/5) - GUI & desktop
├── tasks/aur.yml        (3/5) - AUR packages
├── tasks/dotfiles.yml   (4/5) - Dotfiles management
└── tasks/zap.yml        (5/5) - Zsh plugins
```

### Variable Layout and Precedence

Ansible automatically loads the mappings in `group_vars/all/`; the playbook
does not use `include_vars` or `import_vars`. The concern files are:

- `base.yml`: `username` and `limine_conf_path`
- `system.yml`: `system_packages`
- `desktop.yml`: `desktop_packages` and `audio_packages`
- `graphics.yml`: `nvidia_packages` and `use_nvidia`
- `services.yml`: `enable_services`
- `aur.yml`: `aur_packages`
- `dotfiles.yml`: the complete `dotfiles` mapping

The split preserves the previous values, list order, and Jinja expressions.
`use_nvidia: true` is the only added default. `host_vars/localhost.yml` is an
empty mapping with commented examples, ready for machine-specific overrides.

For the relevant inventory layers, group defaults are lower precedence than
host variables; play variables and command-line extra vars have higher
precedence. Scalars override scalars, but lists replace lists rather than merge.
Nested mappings should be written as mappings, not dotted YAML keys. In
particular, a host override for `dotfiles` must repeat its complete `repo`,
`dest`, and `subdirs` structure.

## Task Module Details

### system.yml

**Responsibilities:**
- Enable pacman ParallelDownloads for faster installs
- Install dual kernel setup (Zen + LTS for rollback safety)
- Optional NVIDIA DKMS drivers with early KMS support
- Firewall configuration via UFW
- NetworkManager with iwd backend
- Create `aur_builder` system user for secure AUR builds

**Key Handlers:**
- `Regenerate initramfs`: Triggered when the managed module drop-in changes
  - The copy task manages `/etc/mkinitcpio.conf.d/nvidia_btrfs.conf`
  - Runs `mkinitcpio -P` to rebuild initramfs

**NVIDIA Configuration:**

- The first system task validates that `use_nvidia` is an actual YAML boolean.
  Its `always` tag ensures `--tags nvidia` cannot skip validation.
- The default/true path installs the unchanged `nvidia_packages` list, adds
  `nvidia_drm.modeset=1` to `limine_conf_path`, and renders:

  ```text
  MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)
  ```

- The false path skips NVIDIA package and Limine tasks, while still creating
  the mkinitcpio directory and rendering the shared Btrfs content:

  ```text
  MODULES=(btrfs)
  ```

- The `nvidia` tag covers the package, Limine, directory, and drop-in tasks.
- False does not uninstall packages or remove a Limine flag left by a previous
  true run. Hardware detection and cleanup migrations are intentionally absent.
- `mkinitcpio_dropin_dir` defaults to `/etc/mkinitcpio.conf.d`. The override
  exists for safe test redirection and does not change the system default.
- Limine remains a prerequisite for the overall workstation deployment.

### desktop.yml

**Responsibilities:**
- Install Hyprland Wayland compositor
- Install Wayland utilities (waybar, wofi, mako, etc.)
- PipeWire audio stack
- Set Zsh as default shell for user
- Prepare `.config` directory for dotfiles

**Wayland Portal Setup:**
```
xdg-desktop-portal-hyprland  # Hyprland-native portal
xdg-desktop-portal-gtk       # Fallback portal
```

### aur.yml

**Architecture:**
- Uses `kewlfft.aur` collection for AUR operations
- Runs builds as `aur_builder` user (isolation from main user)
- Wrapped in block/rescue for error handling

**Security Model:**
```
aur_builder  →  /etc/sudoers.d/11-install-aur_builder
                →  NOPASSWD: /usr/bin/pacman
```

### dotfiles.yml

**Process:**
1. Clone dotfiles repository
2. Create `.config` directory with proper permissions
3. Find subdirectories in `common/` and `linux/`
4. Before Stow, inspect the configured user's root `.bashrc` only if exactly one
   selected package provides it. If Stow ignore/options configuration might
   suppress the link (a local ignore in that package, or global ignore/`.stowrc`
   configuration in the home/working directory or selected package trees), fail
   before removing the target. GNU Stow scopes another package's
   `.stow-local-ignore` to that package, so unrelated local rules are accepted.
   Both policy and Stow run from the configured user's home with `HOME` set to
   that path for the same `.stowrc` lookup context; the Stow `-d` and `-t` paths
   remain absolute. An unchanged Arch `/etc/skel/.bashrc` is removed without
   backup; a customized regular file is copied to a unique backup in
   `/home/<username>/.bashrc-backups/`
   (private mode `0700`) before removal. Wrong links, directories, ambiguous
   sources and unsafe backup destinations fail without replacing the target.
5. Stow creates links; reruns without a checkout update use `--stow`, while a
   checkout change uses `--restow` to prune stale links. The matching `.note`
   records the original path, backup and planned Stow source. It stays pending
   if Stow fails; only after Stow succeeds and the intended link is verified is
   its status atomically changed to "Stow .bashrc link verified; replacement
   completed." A successful retry can finalize a pending note without another
   backup. This status verifies the link, not the entire workstation deployment.
   Check the current target before restoring from the backup.

**Stow Command:**
```bash
stow -v -d ~/.dotfiles/<subdir> -t /home/<username> --stow <app>
```

### zap.yml

**Function:**
- Checks for existing Zap installation
- Downloads and runs install script if missing
- Idempotent via stat check

## Customization Guide

### Adding Packages

**System/Official packages:**
```yaml
# In group_vars/all/system.yml
system_packages:
  - <existing>...
  - new-package-name
```

**AUR packages:**
```yaml
# In group_vars/all/aur.yml
aur_packages:
  - brave-bin
  - new-aur-package
```

### Adding Services

**Enable at boot:**
```yaml
# In group_vars/all/services.yml
enable_services:
  - NetworkManager
  - bluetooth
  - new-service-name
```

### Host Overrides

Keep group defaults reusable and place machine-specific values in
`host_vars/localhost.yml`. The checked-in file remains an empty mapping until
overrides are needed:

```yaml
---
username: "workstation-user"

# This list replaces desktop_packages; it does not extend it.
desktop_packages:
  - hyprland
  - firefox

use_nvidia: false

# Override the complete nested mapping. Dotted keys are not supported here.
dotfiles:
  repo: "https://example.invalid/owner/dotfiles.git"
  dest: "/home/{{ username }}/.dotfiles"
  subdirs:
    - common
    - linux
```

Both accepted `use_nvidia` values are YAML booleans. Strings, integers, null,
lists, and mappings fail before system mutations. JSON preserves the type for a
one-run command-line override on an intended target:

```bash
ansible-playbook -i inventory.ini main.yml --extra-vars '{"use_nvidia": false}'
```

Do not use `--extra-vars use_nvidia=false`; that form supplies a string and is
rejected. When NVIDIA is enabled, `limine_conf_path` continues to identify the
Limine configuration that receives `nvidia_drm.modeset=1`.

## Maintenance Operations

### Update Playbook Dependency Collections

```bash
ansible-galaxy collection install --force -r requirements.yml
```

### Prepared-Target Execution and Rolling Updates

The inventory targets the local machine. Commands in this subsection perform
workstation operations and belong only on the intended, prepared Arch target;
they are not controller validation commands.

The system task performs a full `pacman -Syu` before package installation, in
line with Arch's rolling-release model. Partial upgrades remain unsupported.
The modular-variable and NVIDIA changes do not alter that update policy or any
package-list default.

For verbose target execution:

```bash
# Verbosity level 1
ansible-playbook -i inventory.ini main.yml -v

# Verbosity level 3
ansible-playbook -i inventory.ini main.yml -vvv
```

### Re-run Specific Task

```bash
# Start from specific task
ansible-playbook -i inventory.ini main.yml --start-at-task="Install AUR Packages"

# Start from specific play
ansible-playbook -i inventory.ini main.yml --step
```

## Error Handling

### AUR Failures

**Symptom:** AUR block fails, playback stops

**Cause:** Network issues, AUR build failure, missing dependencies

**Resolution:**
```bash
# Check build logs
journalctl -u aur_builder
# Or manually test
sudo -u aur_builder paru -Syu brave-bin
```

### NVIDIA Driver Failures

**Symptom:** Boot issues, black screen

**Cause:** Initramfs not regenerated, missing modules

**Resolution:**
```bash
# Manually regenerate
sudo mkinitcpio -P

# Verify modules loaded
lsmod | grep nvidia
```

### Dotfiles Conflicts

**Symptom:** Stow fails with "already exists" error

**Cause:** A target conflicts with Stow. Only the configured user's root
`.bashrc` has the narrow default/custom-file policy described above.

**Resolution:** Inspect the exact conflicting target and intended source; do
not delete unrelated paths or adopt them wholesale. For a customized `.bashrc`,
the playbook prints its backup and recovery-note locations. To restore, inspect
the note and current target, remove the Stow link if present, then copy the
backup back to its original path with metadata preserved (for example `cp -p`).
Do not move or overwrite the original backup while verifying the restoration.

## Testing and Verification Boundaries

### Safe Controller Validation

These commands parse and lint the playbook and run isolated tests without
applying `main.yml`:

```bash
ansible-playbook -i inventory.ini main.yml --syntax-check
ansible-lint \
  main.yml tasks/*.yml group_vars/all/*.yml host_vars/localhost.yml \
  tests/fixtures/variable_loading/*.yml \
  tests/fixtures/nvidia_gating/playbook.yml
python -m unittest discover -s tests -v
```

The variable-loading tests create temporary old/new layouts and invoke real
Ansible loading for explicit inventory and implicit localhost. They verify
value equivalence, unique definitions, and scalar/list/boolean host precedence.

The NVIDIA tests import the production `tasks/system.yml` under
`--tags nvidia`, including its real validation, conditions, templating, and tag
selection. The Python harness removes inherited Ansible settings and supplies
its own configuration; when selected, an `always` fixture pre-task rejects
unexpected run/skip tags, privilege escalation, or mismatched redirected paths.
Direct `--skip-tags always` execution bypasses this guard; the supported Python
runner never supplies skip tags. The harness resolves Pacman to
a no-op fixture module, redirecting Limine and mkinitcpio paths into a temporary
directory, disabling privilege escalation, and replacing the initramfs handler
with a debug marker. A fail-closed UFW fixture permits task-file parsing but
must never be selected by the tagged run.

Always invoke this coverage through the Python test runner. Running
`tests/fixtures/nvidia_gating/playbook.yml` directly omits the harness safety
controls and is unsupported.

### Verification Not Covered by Isolated Tests

The safe suite does not install packages, run `mkinitcpio`, change a real
Limine configuration, exercise services/firewall, detect hardware, or apply the
complete workstation. Full application and a repeat on an authorized disposable
guest are separate acceptance checks. Distinguish intentional upstream package
or dotfiles updates from unexpected configuration changes; a rolling update
does not guarantee a zero-change repeat. Physical NVIDIA
boot, modesetting, and graphics acceptance is another separate stage when
applicable. Neither stage is implied by a passing isolated suite, and this
documentation does not claim that either has run.

## Changelog

### Recent Changes

**Fixed:**
- Removed duplicate NVIDIA installation task
- Fixed idempotency in zap.yml
- Standardized `become` usage across tasks
- Added error handling for AUR operations

**Improved:**
- Moved all package lists to `group_vars/all.yml` (historical layout, now superseded)
- Split global defaults across automatically loaded `group_vars/all/` mappings
- Added strict boolean NVIDIA gating with a Btrfs-only disabled path
- Added block/rescue for AUR task isolation
- Better become_user handling for dotfiles

**Added:**
- Comprehensive variable management
- README.md for quick start
- Enhanced documentation in agent.md
