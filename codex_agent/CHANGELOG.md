# Changelog

## 0.1.7

- Only create the required first backup for configuration-changing apply runs.
- Keep entity-control apply runs from calling Supervisor backups.
- Render answers as markdown and collapse tool activity into human-readable summaries.
- Trim the Supervisor full-backup request payload and report backup API errors clearly.

## 0.1.6

- Force sidebar assets to refresh so the human-readable run renderer loads.
- Run Codex without its internal bubblewrap sandbox inside the add-on container.
- Load the Supervisor token through Home Assistant's s6 environment wrapper and file fallback.

## 0.1.5

- Clean Codex device-login output and expose a clickable login URL.
- Render run progress as human-readable activity instead of raw JSON.
- Improve Home Assistant API and dashboard context available to Codex.

## 0.1.4

- Repair managed Codex config for existing users and remove unsupported CLI keys.

## 0.1.3

- Use Codex CLI flags supported by `codex exec`.

## 0.1.2

- Fix container startup path so the web app module is importable at runtime.

## 0.1.1

- Use standard buffered ingress responses for the sidebar UI.

## 0.1.0

- Initial production-oriented add-on scaffold.
- Added admin-only ingress UI.
- Added per-user Codex login state.
- Added ask, propose, apply, and full-auto modes.
- Added first-change Supervisor backup.
- Added risk classification, secret approval gate, run audit, and retention.
