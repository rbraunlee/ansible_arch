# Optional profiles and default Voxtype

The helper profiles remain deliberately opt-in. Voxtype is the exception: the
default mapping enables it because the owner selected Voxtype and its typing /
audio prerequisites as desktop defaults. A host override replaces the complete
mapping, so retain every key rather than relying on a partial merge:

```yaml
optional_profiles:
  tmux_focus: false
  swappy: false
  media_recording: false
  archive_helpers: false
  mirror_tools: false
  voxtype:
    enabled: true
    provider: auto
```

The validation rejects missing or unknown keys, non-boolean flags, unknown
providers, and inconsistent `enabled` / `provider` pairs. The selections are:

| Profile | Selection and packages |
| --- | --- |
| `tmux_focus` | Opt-in: `tmux` |
| `swappy` | Opt-in: `swappy` |
| `media_recording` | Opt-in: `yt-dlp`, `ffmpeg`, `wf-recorder` |
| `archive_helpers` | Opt-in: `unrar`, `unzip`, `ncompress`, `7zip` |
| `mirror_tools` | Opt-in: `reflector`, `rate-mirrors`, `expac` |
| `voxtype`, `provider: auto` | Default: `wtype`, `pipewire-alsa`, then `voxtype-cuda` when `use_nvidia: true` or `voxtype-bin` when false |
| `voxtype`, `provider: cpu` | `wtype`, `pipewire-alsa`, `voxtype-bin` |
| `voxtype`, `provider: cuda` | `wtype`, `pipewire-alsa`, `voxtype-cuda`; requires `use_nvidia: true` |
| `voxtype`, `enabled: false`, `provider: none` | Explicitly installs no Voxtype packages |

`auto` is a direct, deterministic mapping from the existing strict
`use_nvidia` YAML boolean; it does not probe hardware. An explicit CUDA choice
with `use_nvidia: false` is rejected before package tasks run. `voxtype-bin` is
the Voxtype project's documented stable Arch/AUR distribution. The CPU profile
installs this CPU-capable package without requesting CUDA; it does not force a
runtime backend or undo existing GPU setup.

The CUDA profile uses the separately maintained
[`voxtype-cuda` AUR package](https://aur.archlinux.org/packages/voxtype-cuda),
which builds Whisper with CUDA support from source. It is not one of the three
packages listed in the upstream installation guide. On 2026-11-03, the active
AUR RPC record reported version `1.1.0-1`, maintainer `graysky`, and no out-of-date
flag. Its [versioned metadata](https://aur.archlinux.org/cgit/aur.git/tree/.SRCINFO?h=voxtype-cuda&id=67a503ea71805eafac3ed9375b66bf9d8c9167c1)
declares `cuda` and `nvidia-utils` as required dependencies, plus build tools.
The AUR transaction therefore brings in the CUDA toolkit transitively; it is
not a missing optional runtime dependency. Building this provider can take
substantial time and disk space. Its default CUDA architecture list does not
cover every NVIDIA GPU, so `use_nvidia: true` alone does not establish hardware
compatibility. Validate the selected GPU/toolkit/driver combination on the
intended target before runtime acceptance.

For comparison, `voxtype-bin` was version `1.1.1-1`, maintained by `peteonrails`,
at AUR commit `b86700ebcaa847352cffab29e6f8332bac72f71d`. Its bundled ONNX CUDA
variants and optional runtime requirements are different from the source-built
Whisper CUDA provider selected here. Models and engines must match the chosen
provider. Package metadata was read without executing recipes or install hooks;
no package installation or database sync was performed. The isolated package
stubs verify selection and ordering, not successful builds or GPU execution.

No AI desktop client, model, account, or MCP provider is selected by these
profiles. `tmux_focus` only makes `tmux` available; TPM setup, choosing a
project, and invoking the Stowed `focus` helper remain manual.

## Voxtype rules and manual prerequisites

An enabled Voxtype mapping selects `auto`, `cpu`, or `cuda`; a disabled mapping
must use `none`. The playbook does not download `large-v3-turbo` or any other
model, provide credentials, discover a microphone, choose a backend, or run a
dictation test. Model acquisition, microphone/PipeWire QA, backend setup, and
provider compatibility require an owner-approved suitable host and remain
manual.

The generated overlay changes the next Hyprland configuration load only. When
Voxtype is enabled, that next normal Hyprland session imports the allowlisted
Wayland session variables and performs the existing idempotent
`systemctl --user start voxtype.service`; Ansible itself neither starts nor
restarts the service and does not alter an already running graphical session.
When disabled, the next configuration load contains no Voxtype service-start
call, shortcut, or suppression submap. Disabling also does not uninstall a
provider, remove models/runtime state, or stop/disable an already active user
service.

`use_nvidia: false` makes the generated overlay omit the two NVIDIA Hyprland
environment values on a subsequent session. It does not undo environment values
already inherited by a running session or migrate installed drivers.

## Guarded Hyprland contract

The single canonical overlay path is
`/home/<username>/.config/ansible_arch/hyprland-optional.lua`; it does not use
`XDG_CONFIG_HOME` and is not configurable through host variables. The versioned
Lua loader uses that same `HOME` path. The Ansible helper traverses the home,
`.config`, and `ansible_arch` components through non-symlink directory
descriptors, checks ownership, and atomically replaces only the regular leaf.
It preserves an existing unmarked file. It recognizes the prior fixed v1 marker
only to migrate an already managed overlay to v2; change profile variables
instead of editing a generated file.

This prevents a checked ancestor symlink from redirecting the helper's write.
It is not a promise against a malicious same-user process replacing paths before
or after the helper exits; a target home used for deployment must not be shared
with an adversarial writer.

The pinned upstream source `33e2c02` currently has no integration point and
unconditionally starts `voxtype.service` plus unconditionally sets NVIDIA
environment variables. Before any system, desktop, AUR, firewall, or service
task, the playbook clones the selected rolling dotfiles revision into a
configured-user temporary checkout. It verifies the exact SHA-256 of the
immutable `ansible_arch_optional_overlay_v2.lua` loader, the real NVIDIA and
Voxtype binding gates, and the one bounded startup command inside the Voxtype
gate. It then deploys that same Git revision to `dotfiles.dest`. A later remote
update therefore cannot race the checked source within the run; the next run
selects and validates a new rolling revision.

If the contract is absent, changed, incomplete, uses a raw daemon or a service
restart, or moves the startup command outside its guard, the preflight fails
before workstation mutations and removes its temporary checkout. It never
patches or dirties the rolling clone. The dotfiles maintainer must review and
apply [the versioned patch](hyprland-optional-overlay-v2.patch) in the dotfiles
repository first. This repository does not publish that second-repository
change. The temporary preflight still runs in Ansible check mode so check mode
cannot report a source it did not validate.

The v2 patch deliberately gives an absent generated overlay `true` defaults for
both Voxtype and NVIDIA behavior. Thus a standalone dotfiles checkout that has
not adopted Ansible's generated overlay preserves its current upstream startup,
shortcut, and NVIDIA workflow. A generated false overlay is distinct: it
explicitly disables the startup, shortcut/submap, and NVIDIA values. Malformed
overlays fail configuration loading. The exact patch and loader execute in a
fixture with a stub Hyprland Lua API for absent, true, false, malformed, and
non-default-XDG cases; this is still not a real graphical session.

This is source-level and fixture-tested coverage, not runtime acceptance. An
authorized fresh-host / graphical-session gate must separately validate package
resolution, CPU/CUDA provider compatibility, model and microphone/backend
setup, the user-service lifecycle, and actual dictation/desktop behavior.

## Tagged updates

After a full deployment has established the system/AUR prerequisites and Stow
links, `--tags optional` validates and checks out the selected dotfiles
revision, updates the overlay, and installs Voxtype plus any selected helper
packages. `--tags dotfiles` selects the checkout and overlay tasks only; it is
not a complete Stow deployment. Both retain the always-tagged preflight.
Neither tagged path establishes the base system, `aur_builder`, Paru, or Stow
links on a fresh host; use the full playbook for initial provisioning. Full host
application remains separately authorized; these commands are not routine
controller checks.
