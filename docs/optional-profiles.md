# Optional profiles

Optional tools are deliberately opt-in. `optional.yml` supplies a complete
`optional_profiles` mapping whose default selects no optional package or
Voxtype provider. A host override replaces that whole mapping, so retain every
key rather than relying on a partial merge:

```yaml
optional_profiles:
  tmux_focus: true
  swappy: false
  media_recording: false
  archive_helpers: false
  mirror_tools: false
  voxtype:
    enabled: true
    provider: cuda
```

The profile validation rejects missing or unknown keys, non-boolean flags, an
unknown provider, and an inconsistent `enabled`/`provider` pair. The supported
selections are:

| Profile | Packages selected only when true |
| --- | --- |
| `tmux_focus` | `tmux` |
| `swappy` | `swappy` |
| `media_recording` | `yt-dlp`, `ffmpeg`, `wf-recorder` |
| `archive_helpers` | `unrar`, `unzip`, `ncompress`, `7zip` |
| `mirror_tools` | `reflector`, `rate-mirrors`, `expac` |
| `voxtype` with `provider: cuda` | Official: `wtype`, `pipewire-alsa`; AUR: `voxtype-cuda` |

No AI desktop client, model, account, or MCP provider is selected by these
profiles. Install and authenticate those clients manually if wanted.
`tmux_focus` only makes `tmux` available; TPM setup, choosing a project, and
invoking the Stowed `focus` helper remain manual.

## Voxtype rules and manual prerequisites

`voxtype.enabled: true` requires `provider: cuda`; `provider: cuda` requires
`use_nvidia: true`. `enabled: false` requires `provider: none`. The playbook
installs neither a model nor credentials and does not discover a microphone,
choose an audio backend, enable/start/restart a user service, reload Hyprland,
or run a dictation test. Those steps require an owner-approved, suitable
Wayland/PipeWire/NVIDIA host and remain manual.

The generated overlay only controls the next Hyprland configuration load after
the upstream contract below is adopted. Disabling the profile does not uninstall
`voxtype-cuda`, remove models or runtime state, stop/disable an already enabled
`voxtype.service`, or alter an existing graphical session. Similarly,
`use_nvidia: false` prevents the contract from adding the NVIDIA Hyprland
environment values on a subsequent session; it does not undo environment
values already inherited by a running session or migrate installed drivers.

## Guarded Hyprland contract

The task renders only
`~/.config/ansible_arch/hyprland-optional.lua`, a regular Ansible-owned file
outside the dotfiles checkout and every Stow package. It refuses to overwrite a
directory, symlink, or an existing regular file without the contract marker. A
marked generated file is reconciled on a repeat run; change host variables
instead of editing it.

The pinned upstream source `33e2c02` currently has no integration point and
unconditionally starts `voxtype.service` plus unconditionally sets NVIDIA
environment variables. Therefore the dotfiles task checks for the reviewed
contract and fails before any Stow operation if it is absent. It never patches
or dirties the rolling clone. The dotfiles maintainer must review and apply
[the versioned patch](hyprland-optional-overlay-v1.patch) in the dotfiles
repository first. This repository does not publish that second-repository
change.

The patch defaults both controls to false when the generated overlay is absent,
never starts `voxtype.service`, gates the Voxtype shortcut/submap, and gates the
NVIDIA environment variables. Once accepted upstream, the generated overlay
sets `voxtype_enabled` from `optional_profiles.voxtype.enabled` and
`nvidia_environment` from `use_nvidia`. Its marker and required gates are
checked before Stow so a changed or incomplete upstream implementation cannot
silently restore the old behavior.

This is source-level and fixture-tested coverage, not runtime acceptance. An
authorized fresh-host/graphical-session gate must separately validate package
resolution, provider compatibility, microphone/backend/model setup, any chosen
user-service lifecycle, and actual dictation/desktop behavior.
