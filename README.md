# Home Assistant Codex Agent

Home Assistant Codex Agent is a production-oriented Home Assistant OS add-on
that puts Codex in the sidebar for administrators. Each Home Assistant admin
uses their own Codex login and subscription. The add-on can answer questions,
propose changes, or apply approved changes against Home Assistant configuration
and APIs.

## v1 Scope

- Sidebar-only UI through Home Assistant ingress
- Admin-only panel visibility
- Per-user Codex authentication and state under `/data`
- Ask, propose, and apply modes
- Low-risk automation with high-risk approval gates
- Optional full-auto mode with an explicit warning
- Full Supervisor backup before the first apply-mode change
- 30-day audit retention by default, configurable in add-on options
- HA OS target with `amd64` and `aarch64` images

## Installation

1. Publish this repository to GitHub.
2. Update `repository.yaml`, `codex_agent/config.yaml`, and the GitHub Actions
   image settings if your GitHub owner or repository name differs.
3. In Home Assistant, go to **Settings > Add-ons > Add-on Store**.
4. Add this repository URL as a custom add-on repository.
5. Install **Codex Agent** and start it.

## Security Model

This add-on is intentionally powerful. It requests Supervisor admin API access
because v1 is designed to make configuration changes, create backups, call Home
Assistant APIs, and operate add-ons when an administrator asks it to. The add-on
does not expose a host port; access is through Home Assistant ingress.

Codex credentials are stored per Home Assistant user in the add-on data volume.
Treat the add-on backup and `/data/users/*/codex_home/auth.json` as sensitive
material.

## Documentation

See [`codex_agent/DOCS.md`](codex_agent/DOCS.md) for configuration, operation,
risk classification, and publishing notes.
