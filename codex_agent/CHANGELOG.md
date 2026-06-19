# Changelog

## 0.1.16

- Add compatibility anchors for stale sidebar assets during add-on updates.
- Guard chat and session rendering against mixed cached HTML and JavaScript.
- Prevent missing optional controls from surfacing as a failed message send.

## 0.1.15

- Replace the Recent runs surface with a Sessions list.
- Keep session conversations in the chat so follow-up messages retain context.
- Clear the composer immediately after Send and show startup feedback in the chat.
- Generate topic-focused session titles instead of copying the first prompt.

## 0.1.14

- Stop clearing origin-wide browser caches from the ingress page.
- Add an ingress-safe base path so static assets and API calls resolve under Home Assistant.
- Render model choices in the initial HTML and keep a frontend fallback list.

## 0.1.13

- Add a header model selector with the current recommended Codex models.
- Persist the selected model and mode locally across questions, sessions, and reloads.
- Pass the selected model to `codex exec --model` for each run.
- Move generated diffs out of the chat stream into a toolbar button and PR-style diff modal.

## 0.1.12

- Force fresh sidebar HTML, CSS, and JavaScript on each add-on version update.
- Add no-store cache headers for browser, proxy, ingress, and Cloudflare cache layers.
- Clear browser HTTP/cache-storage entries once when a new add-on version is loaded.
- Show the running add-on version in the header for quick stale-browser checks.
- Make New session an immediate draft state that creates the real session on first run.
- Add elapsed wait feedback while runs are starting or waiting for the next update.

## 0.1.11

- Fix New session clicks by removing invalid nested label markup around session controls.
- Constrain Recent runs with single-column cards so long prompts cannot widen the page.
- Normalize item started/completed events into concise human-readable activity.
- Keep tool activity collapsed by default and add Open all / Close all controls.
- Show immediate feedback while a run or new session is starting.

## 0.1.10

- Fix the session selector layout so session names are visible and selectable.
- Keep Recent runs constrained when prompts are long.
- Keep selected sessions and Recent runs in sync after refreshes and new runs.

## 0.1.9

- Add user-scoped conversation sessions so follow-up runs stay in the same context.
- Keep only concise recent run previews in the Recent runs list to prevent long prompt layout breaks.
- Improve session-aware history selection and expose active session switching in sidebar UI.

## 0.1.8

- Transform run events server-side into safe, human-readable summaries.
- Add markdown-focused answer rendering and tool summaries that hide raw JSON payloads.
- Preserve tool detail visibility while suppressing structured JSON in the default sidebar feed.

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
