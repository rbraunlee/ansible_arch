# Arch Workstation Deployment

Ansible playbook for automating a complete Arch Linux workstation setup with
Hyprland, optional NVIDIA drivers, and dotfiles management.

## Prerequisites

- Fresh Arch Linux installation (minimal install)
- Limine bootloader installed
- Ansible installed
- Python 3 installed
- NetworkManager for networking
- Git installed
- User account created (default: `rbl`)

## Quick Start

### 1. Install Dependencies

First, install Ansible and clone the AUR collection:

```bash
sudo pacman -S ansible git python
ansible-galaxy collection install -r requirements.yml
```

### 2. Configure Variables

Ansible automatically loads every YAML mapping in `group_vars/all/`. The files
are split by concern without changing the existing package, service, user, or
dotfiles values. `use_nvidia` is the only added default and is `true`.

Put machine-specific values in `host_vars/localhost.yml`. It is an empty mapping
with commented examples in the repository. Use normal nested YAML mappings;
do not use dotted keys such as `dotfiles.repo`:

```yaml
---
username: "workstation-user"

# Lists replace the group default; include the complete desired list.
desktop_packages:
  - hyprland
  - firefox

use_nvidia: false

# Override the complete nested mapping rather than one dotted key.
dotfiles:
  repo: "https://example.invalid/owner/dotfiles.git"
  dest: "/home/{{ username }}/.dotfiles"
  subdirs:
    - common
    - linux
```

Scalar host values override group scalars. Host lists replace group lists; they
are not merged. A host-level `dotfiles` value must therefore contain the
complete mapping shown above.

`use_nvidia` must be an actual YAML boolean. For a command-line override, use a
JSON extra-vars object so Ansible receives a boolean rather than a string:

```bash
ansible-playbook -i inventory.ini main.yml --extra-vars '{"use_nvidia": false}'
```

Do not use `--extra-vars use_nvidia=false`; key/value extra vars produce the
string `"false"`, which the playbook deliberately rejects.

### 3. Apply to the Prepared Target

`inventory.ini` targets the machine on which Ansible is running. The following
command performs workstation changes and is only for the intended, prepared
Arch target; it is not a controller QA command:

```bash
ansible-playbook -i inventory.ini main.yml
```

## Features

- **System Setup**: Linux kernels (Zen & LTS), optional NVIDIA DKMS drivers,
  firewall (UFW)
- **Desktop Environment**: Hyprland, Waybar, Ghostty/Kitty terminal
- **AUR Integration**: Paru AUR helper with secure `aur_builder` user
- **Dotfiles**: Automatic git clone and stow symlink management
- **Zsh Setup**: Starship prompt, Zap plugin manager

## Customization

Global defaults are organized under `group_vars/all/`:

- `base.yml`: username and Limine path
- `system.yml`: core system packages
- `desktop.yml`: GUI and audio packages
- `graphics.yml`: NVIDIA packages and `use_nvidia`
- `services.yml`: enabled services
- `aur.yml`: AUR packages
- `dotfiles.yml`: complete repository, destination, and subdirectory mapping

### NVIDIA Selection

The default `use_nvidia: true` preserves the existing behavior: install the
configured NVIDIA packages, add `nvidia_drm.modeset=1` to the configured Limine
file, and manage this mkinitcpio content:

```text
MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)
```

With `use_nvidia: false`, NVIDIA package and Limine tasks are skipped, while the
shared managed drop-in remains with Btrfs only:

```text
MODULES=(btrfs)
```

The drop-in continues to notify the initramfs handler only when its content
changes.

Disabling the flag does not uninstall existing NVIDIA packages or remove a
previously written Limine flag. It controls future task execution; cleanup of an
already configured NVIDIA machine is a separate manual migration.

The `nvidia` tag includes strict flag validation, the mkinitcpio directory
prerequisite, and the shared Btrfs drop-in. A normal `--tags nvidia` run cannot
bypass boolean validation. Limine remains a general prerequisite for this
workstation playbook even when NVIDIA is disabled.

## Troubleshooting

### AUR Installation Fails

Ensure `aur_builder` has network access and sudo permissions:

```bash
sudo editor /etc/sudoers.d/11-install-aur_builder
```

### NVIDIA Drivers

Set `use_nvidia: false` in `host_vars/localhost.yml` before applying to a target
without NVIDIA hardware. This does not remove artifacts from an earlier enabled
run; inspect and migrate an existing machine separately.

### Dotfiles Issues

Check that your dotfiles repository exists and is accessible:

```bash
git ls-remote https://github.com/BraunRudolf/.dotfiles.git
```

## Directory Structure

```
├── main.yml           # Main playbook
├── inventory.ini      # Localhost inventory
├── requirements.yml   # Ansible collections
├── group_vars/
│   └── all/           # Automatically loaded global defaults by concern
│       ├── aur.yml
│       ├── base.yml
│       ├── desktop.yml
│       ├── dotfiles.yml
│       ├── graphics.yml
│       ├── services.yml
│       └── system.yml
├── host_vars/
│   └── localhost.yml  # Empty mapping with override examples
└── tasks/
    ├── system.yml     # System packages & services
    ├── desktop.yml    # Desktop environment
    ├── aur.yml        # AUR packages
    ├── dotfiles.yml   # Dotfiles management
    └── zap.yml        # Zsh plugin manager
```

## Validation

The following commands validate source and isolated behavior without applying
the workstation playbook:

```bash
ansible-playbook -i inventory.ini main.yml --syntax-check
ansible-lint \
  main.yml tasks/*.yml group_vars/all/*.yml host_vars/localhost.yml \
  tests/fixtures/variable_loading/*.yml \
  tests/fixtures/nvidia_gating/playbook.yml
python -m unittest discover -s tests -v
```

Run the NVIDIA coverage through the Python test runner. Do not execute
`tests/fixtures/nvidia_gating/playbook.yml` directly: the test harness supplies
the no-op Pacman module, temporary filesystem paths, disabled privilege
escalation, and a debug-only initramfs handler needed to make the run safe.

Those tests import the real production system tasks and exercise their
templating and tag selection, but they do not install packages, run
`mkinitcpio`, or validate real hardware. Full application and repeat application
on an authorized disposable guest, followed by physical NVIDIA acceptance when
applicable, are separate verification stages and are not claimed by the
isolated test suite.

The system task retains Arch's rolling-release expectation of a full system
upgrade before package installation; this change does not introduce or endorse
partial upgrades.

## Security Notes

- `aur_builder` system user for secure AUR builds
- UFW firewall enabled by default
- No secrets or credentials stored in playbook

## See Also

For detailed technical documentation, see [agent.md](agent.md).
