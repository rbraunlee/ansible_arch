# Dotfiles dependency coverage

This is a source-level package-coverage matrix for the dotfiles Stowed by this
playbook. It records the reviewed default path; it is not a claim that a
headless controller or VM exercised a graphical session.

## Scope and evidence

- Audited configured dotfiles upstream: [`33e2c02de1451901ec512dbf6add16ee5d0fe419`](https://github.com/BraunRudolf/.dotfiles/tree/33e2c02de1451901ec512dbf6add16ee5d0fe419).
- Read-only local dotfiles comparison: `0eee62fc889970b956f869008dbc5f6e11e7fa1f`.
  It is two commits ahead; the diff changes only `common/scripts` and
  `common/tmux` focus behavior and does not change this dependency set.
- The matrix records direct and transitive coverage separately: curl is
  supplied through Git/Pacman, GnuPG through Pacman, playerctl through Waybar,
  and compiler/make through `base-devel`.
- Official Arch metadata was read on 2026-11-02 without synchronizing a package
  database or installing anything. The ticket #9 identifiers resolve in Extra:
  [`networkmanager`](https://archlinux.org/packages/extra/x86_64/networkmanager/),
  [`hypridle`](https://archlinux.org/packages/extra/x86_64/hypridle/),
  [`hyprlock`](https://archlinux.org/packages/extra/x86_64/hyprlock/),
  [`dolphin`](https://archlinux.org/packages/extra/x86_64/dolphin/),
  [`neovim`](https://archlinux.org/packages/extra/x86_64/neovim/),
  [`tree-sitter-cli`](https://archlinux.org/packages/extra/x86_64/tree-sitter-cli/),
  [`ripgrep`](https://archlinux.org/packages/extra/x86_64/ripgrep/),
  [`pacman-contrib`](https://archlinux.org/packages/extra/x86_64/pacman-contrib/),
  [`otf-font-awesome`](https://archlinux.org/packages/extra/any/otf-font-awesome/),
  and [`otf-comicshanns-nerd`](https://archlinux.org/packages/extra/any/otf-comicshanns-nerd/).
  `ttf-font-awesome` is not retained: its old package URL redirects to the
  WOFF2 split package, whereas `otf-font-awesome` is the current installed-font
  split appropriate for the Waybar font provider.

The task order remains unchanged: system foundations install
`system_packages`, the desktop task installs `desktop_packages`, then the
dotfiles task clones the configured rolling checkout and Stows every immediate
directory under `common/` and `linux/`. A host override still replaces a whole
package list, so an override must include any desired defaults.

## Classification

- **Direct default** — an explicitly installed package provides a configured
  default path.
- **Transitive default** — a direct default package supplies the executable or
  library; it is intentionally not duplicated in a package list.
- **External bootstrap** — Arch base or the documented Ansible bootstrap, not
  a playbook package default.
- **Optional/manual** — configuration is present but the user must choose and
  install/configure the provider before use.
- **Platform/hardware excluded** — intentionally outside ticket #9; it needs
  a suitable host and the ticket #10 profile/integration decision.

## Top-level Stow package matrix

| Stow package | Source evidence at upstream `33e2c02` | Classification and coverage |
| --- | --- | --- |
| `common/agent-skills` | `common/agent-skills/.agents/skills/` | **Optional/manual**: choose the matching client and any account/service setup. |
| `common/claude` | `common/claude/.claude/settings.json`, `.claude/mcp/install.sh` | **Optional/manual** client and authentication; no client is selected by defaults. |
| `common/codex` | `common/codex/.codex/config.toml` | **Optional/manual** client and authentication; no client is selected by defaults. |
| `common/cursor` | `common/cursor/.cursor/skills/` | **Optional/manual** desktop client and authentication; no client is selected by defaults. |
| `common/ghostty` | `common/ghostty/.config/ghostty/config.ghostty` | **Direct default**: `ghostty` and `otf-comicshanns-nerd`, which supplies its configured ComicShanns Nerd Font face. |
| `common/nvim` | `common/nvim/.config/nvim/` and its plugin bootstrap | **Direct default**: `neovim`, `tree-sitter-cli`, and `ripgrep`; `npm` supplies the Node runtime used by the configuration. Plugin, parser, Mason/LSP, formatter, and selected-language downloads remain **manual** network setup. |
| `common/opencode` | `common/opencode/.config/opencode/opencode.jsonc` | **Optional/manual** client, provider/account, and any MCP setup. |
| `common/scripts` | `common/scripts/README.md` (`focus`, `notetaker`) | **Default-path direct**: `ghostty`; Bash is **external bootstrap**. `focus` additionally needs a user-selected project and `tmux`, which remains **optional/manual**. |
| `common/starship` | `common/starship/.config/starship.toml` | **Direct default**: `starship`; Nerd Font glyph rendering is covered by the direct font packages. Language/tool indicators are conditional and do not select runtimes. |
| `common/t3` | `common/t3/.config/t3/themes/gruvbox-material.json`, `README.md` | **Optional/manual** client and account/service setup. |
| `common/tmux` | `common/tmux/.config/tmux/tmux.conf`, `README.md` | **Optional/manual**: install `tmux` only when this workflow is selected; TPM/plugin bootstrap and project choice are separate. |
| `common/wallpaper` | `common/wallpaper/Pictures/Wallpapers/`; `linux/hypr/.config/hypr/hyprpaper.conf` | **Default-path direct**: the configured wallpaper asset is Stowed by this package and `hyprpaper` is directly installed. |
| `common/zsh` | `common/zsh/.zshrc`, `common/zsh/README.md` | **Direct default**: `zsh`, `starship`, `neovim`, and `ripgrep`. `curl` is **transitive default** through Git/Pacman; GnuPG through Pacman; compiler/make through `base-devel`. Media, archive, mirror, and package-inspection helpers are **optional/manual** at invocation. |
| `linux/bash` | `linux/bash/.bashrc` | **External bootstrap**: Bash comes from the Arch base. Its `nvim` and `rg` aliases use the direct defaults; legacy aliases remain **optional/manual** rather than defaults. |
| `linux/hypr` | `linux/hypr/.config/hypr/hyprland.lua`, `start-hypridle.sh`, `hypridle.conf` | **Direct default**: `hyprland`, `hyprpaper`, `waybar`, `mako`, `flameshot`, `wofi`, portals, clipboard tools, `hypridle`, `hyprlock`, and `dolphin`. `NetworkManager` is directly installed with system foundations for its enabled service; `pgrep` is from the base system. Idle/lock behavior needs an authorized graphical-session gate. |
| `linux/swappy` | `linux/swappy/.config/swappy/config` | **Optional/manual**: install `swappy` only if this screenshot editor is selected. |
| `linux/voxtype` | `linux/voxtype/.config/systemd/user/voxtype.service`, `config.toml`, README | **Pending feature integration**: provider choice (including `voxtype-cuda`, `wtype`, and `pipewire-alsa` for the CUDA path), backend/model acquisition, microphone selection, and user-service adoption await Ticket #10. The current upstream autostart still invokes Voxtype, so this remains an unresolved default-session gap until that integration is complete. |
| `linux/waybar` | `linux/waybar/.config/waybar/config.jsonc`, `scripts/update-sys.sh`, `style.css` | **Direct default**: `waybar`, `pacman-contrib` for `checkupdates`, `hyprlock`, `otf-font-awesome`, and `otf-comicshanns-nerd` for the configured ComicShanns face. `playerctl` is **transitive default** through Waybar. `paru` is supplied by the existing AUR task. |
| `linux/wofi` | `linux/wofi/.config/wofi/` | **Direct default**: `wofi`; its generic monospace choice needs no additional font package. |
| `linux/zsh` | `linux/zsh/.zshrc` | **Direct default**: `zsh` and `starship`; it shares the common Zsh providers. |

## Ticket #9 default changes

`system_packages` now directly includes `pacman-contrib` and `networkmanager`.
`desktop_packages` now directly includes `hypridle`, `hyprlock`, `dolphin`,
`neovim`, `tree-sitter-cli`, `ripgrep`, `otf-font-awesome`, and
`otf-comicshanns-nerd`; it replaces the obsolete `ttf-font-awesome` identifier.
No optional profile, Voxtype/NVIDIA environment treatment, dotfiles mutation, or
runtime validation is part of this change.

The default package additions above are covered at source level. Voxtype
autostart and NVIDIA-specific Hyprland environment settings remain pending
Ticket #10; classifying their providers as optional does not itself disable
the current upstream behavior. Other optional and manual prerequisites remain
as listed in the matrix.

## Runtime acceptance gate — separate authorization required

Static tests prove the default mappings, precedence, source-matrix coverage,
and syntax/lint only. This ticket did not open or execute the runtime gate. Once
the owner separately authorizes a fresh current-Arch guest, the gate must verify
that the current repositories resolve every default identifier, that the new
default binaries and `checkupdates` are present, and that the `NetworkManager`
service can start under the target's intended network setup. A logged-in Hyprland
session must separately verify Hypridle/Hyprlock, Dolphin, Waybar fonts/update
display, portals, and clipboard/audio behavior. Voxtype remains excluded pending
Ticket #10's profile decision. A controller test or headless VM does not satisfy
this gate, and neither may substitute for suitable hardware/model/provider QA.
