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

The single canonical path is
`/home/<username>/.config/ansible_arch/hyprland-optional.lua`; it does not use
`XDG_CONFIG_HOME` and is not configurable through host variables. The versioned
Lua loader uses that same `HOME` path. The Ansible helper traverses the home,
`.config`, and `ansible_arch` components through non-symlink directory
descriptors, checks ownership, and atomically replaces only the regular leaf.
It preserves an existing file without its fixed Ansible marker. A marked
generated file is reconciled on a repeat run; change profile variables instead
of editing it.

This prevents a checked ancestor symlink from redirecting the helper's write.
It is not a promise against a malicious same-user process replacing paths before
or after the helper exits; a target home used for deployment must not be shared
with an adversarial writer.

The pinned upstream source `33e2c02` currently has no integration point and
unconditionally starts `voxtype.service` plus unconditionally sets NVIDIA
environment variables. Before any system, desktop, AUR, firewall, or service
task, the playbook clones the selected rolling dotfiles revision into a
configured-user temporary checkout. It verifies the exact SHA-256 of the
versioned `ansible_arch_optional_overlay_v1.lua` loader and the required real
Hyprland gates, then deploys that same Git revision to `dotfiles.dest`. A later
remote update therefore cannot race the checked source within the run; the next
run selects a new rolling revision and validates it again.

If the contract is absent, changed, incomplete, or contains any `systemctl`
call, the preflight fails before workstation mutations and removes its temporary
checkout. It never patches or dirties the rolling clone. The dotfiles maintainer
must review and apply [the versioned patch](hyprland-optional-overlay-v1.patch)
in the dotfiles repository first. This repository does not publish that
second-repository change. The temporary preflight still runs in Ansible check
mode so check mode cannot report a source it did not validate.

The patch defaults both controls to false when the generated overlay is absent,
never starts `voxtype.service`, gates the Voxtype shortcut/submap, and gates the
NVIDIA environment variables. Once accepted upstream, the generated overlay
sets `voxtype_enabled` from `optional_profiles.voxtype.enabled` and
`nvidia_environment` from `use_nvidia`. The patch and loader are fixture-tested
with a stub Hyprland Lua API for absent, enabled, disabled, malformed, and
non-default-XDG cases; this is still not a real graphical session.

This is source-level and fixture-tested coverage, not runtime acceptance. An
authorized fresh-host/graphical-session gate must separately validate package
resolution, provider compatibility, microphone/backend/model setup, any chosen
user-service lifecycle, and actual dictation/desktop behavior.
