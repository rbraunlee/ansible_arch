# Arch Workstation Deployment

Ansible playbook for automating a complete Arch Linux workstation setup with Hyprland, NVIDIA drivers, and dotfiles management.

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

Edit `group_vars/all.yml` to customize:

```yaml
username: "rbl"                    # Your username
dotfiles.repo: "your-dotfiles-url"  # Your dotfiles repository
```

### 3. Run the Playbook

Execute the playbook:

```bash
ansible-playbook main.yml
```

## Features

- **System Setup**: Linux kernels (Zen & LTS), NVIDIA DKMS drivers, firewall (UFW)
- **Desktop Environment**: Hyprland, Waybar, Ghostty/Kitty terminal
- **AUR Integration**: Paru AUR helper with secure `aur_builder` user
- **Dotfiles**: Automatic git clone and stow symlink management
- **Zsh Setup**: Starship prompt, Zap plugin manager

## Customization

All configurable variables are in `group_vars/all.yml`:

- `system_packages`: Core system tools
- `desktop_packages`: GUI applications
- `nvidia_packages`: graphics drivers
- `aur_packages`: AUR packages to install
- `dotfiles`: Repository configuration

## Troubleshooting

### AUR Installation Fails
Ensure `aur_builder` has network access and sudo permissions:

```bash
sudo editor /etc/sudoers.d/11-install-aur_builder
```

### NVIDIA Drivers
If your GPU is not NVIDIA, comment out the NVIDIA section in `group_vars/all.yml`.

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
│   └── all.yml        # Global variables
└── tasks/
    ├── system.yml     # System packages & services
    ├── desktop.yml    # Desktop environment
    ├── aur.yml        # AUR packages
    ├── dotfiles.yml   # Dotfiles management
    └── zap.yml        # Zsh plugin manager
```

## Security Notes

- `aur_builder` system user for secure AUR builds
- UFW firewall enabled by default
- No secrets or credentials stored in playbook

## See Also

For detailed technical documentation, see [agent.md](agent.md).
