
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

### Variable Inheritance Chain

1. **`group_vars/all.yml`**: Global defaults (user-editable)
2. **`main.yml vars`**: Play-specific overrides
3. **`ansible_facts`**: Runtime system detection

## Task Module Details

### system.yml

**Responsibilities:**
- Enable pacman ParallelDownloads for faster installs
- Install dual kernel setup (Zen + LTS for rollback safety)
- NVIDIA DKMS drivers with early KMS support
- Firewall configuration via UFW
- NetworkManager with iwd backend
- Create `aur_builder` system user for secure AUR builds

**Key Handlers:**
- `Regenerate initramfs`: Triggered after NVIDIA module configuration
  - Modifies `/etc/mkinitcpio.conf.d/nvidia_btrfs.conf`
  - Runs `mkinitcpio -P` to rebuild initramfs

**NVIDIA Configuration:**
```
/etc/mkinitcpio.conf.d/nvidia_btrfs.conf
└── MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)
```

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
4. Symlink contents using GNU Stow with `-R -v` flags

**Stow Command:**
```bash
stow -R -v -d ~/.dotfiles/<subdir> -t /home/<username> <app>
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
# In group_vars/all.yml
system_packages:
  - <existing>...
  - new-package-name
```

**AUR packages:**
```yaml
# In group_vars/all.yml
aur_packages:
  - brave-bin
  - new-aur-package
```

### Adding Services

**Enable at boot:**
```yaml
# In group_vars/all.yml
enable_services:
  - NetworkManager
  - bluetooth
  - new-service-name
```

### Modifying Boot Parameters

**Add kernel params (NVIDIA example):**
```yaml
# In group_vars/all.yml
limine_conf_path: "/boot/limine/limine.conf"

# Edit tasks/system.yml - NVIDIA Early Modesetting task
# Add: nouveau.modeset=0 nvidia_drm.modeset=1 nvidia_drm.fbdev=1
```

## Maintenance Operations

### Update Playbook Dependency Collections

```bash
ansible-galaxy collection install --force -r requirements.yml
```

### Dry Run (Check Mode)

```bash
ansible-playbook main.yml --check
```

### Verbose Execution

```bash
# Debug level 1 (default)
ansible-playbook main.yml -v

# Debug level 2 (task details)
ansible-playbook main.yml -vvv
```

### Re-run Specific Task

```bash
# Start from specific task
ansible-playbook main.yml --start-at-task="Install AUR Packages"

# Start from specific play
ansible-playbook main.yml --step
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

**Cause:** Manual symlinks conflict with Stow

**Resolution:**
```bash
# Remove conflicting symlinks
rm -f ~/.config/conflicting-file
# Re-run playbook
ansible-playbook main.yml
```

## Testing

### Unit Test Tasks

```bash
# Test system setup only
ansible-playbook -i inventory.ini <<<'---
- import_playbook: main.yml
  tasks:
    - import_tasks: tasks/system.yml'
```

### Validate Configuration

```bash
# Syntax check
ansible-playbook main.yml --syntax-check

# YAML linting
ansible-lint main.yml tasks/*.yml
```

## Changelog

### Recent Changes

**Fixed:**
- Removed duplicate NVIDIA installation task
- Fixed idempotency in zap.yml
- Standardized `become` usage across tasks
- Added error handling for AUR operations

**Improved:**
- Moved all package lists to `group_vars/all.yml`
- Added block/rescue for AUR task isolation
- Better become_user handling for dotfiles

**Added:**
- Comprehensive variable management
- README.md for quick start
- Enhanced documentation in agent.md
