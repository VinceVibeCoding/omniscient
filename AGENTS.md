# Omniscient

Omniscient is a small Windows desktop widget (Tauri) plus its local Python engine, the daemon behind
the `omniscient` CLI. It lets users interact with agents from any provider (Claude Code, Copilot,
API keys, local models) outside the IDE, see and approve their requests, monitor LLM usage against
their subscriptions, and chat about the web page they are looking at. Everything stays on the user's
machine. This repo is public (`VinceVibeCoding/omniscient`).

## What the repo contains

| Path | What |
|---|---|
| `src/omniscient/group/` | the daemon (HTTP on `127.0.0.1`, sessions, approvals, chat, usage, hooks) |
| `src/omniscient/cli*.py` | the CLI: `omniscient group ...`, `update`, `ext ...`, `project`, `theme`, `schedule`, `--version`, `--update` |
| `src/omniscient/resources/`, `theme/`, `registry/` | packaged data, themes, project registry |
| `widget/` | the Tauri app (TypeScript front end in `widget/src`, Rust in `widget/src-tauri`) |
| `install.ps1`, `install.sh` | one-command installers (Windows; Linux, macOS, WSL) |
| `plugins/`, `.claude-plugin/` | the Claude Code plugin |
| `docs/` | user docs (French), `docs/agents/` for agent skills config |
| `tests/` | Python tests (offline) |

## Commands

```
uv sync --group dev && uv run pytest         # Python tests (offline)
uv run ruff check src tests                  # lint
cd widget && npx tsc --noEmit && npm test    # widget type check and tests
```

## Rules for every agent

1. **Read before you build.** Read the code and the doc you touch (`docs/omniscient.md` for the
   widget and daemon) before changing it.
2. **Code standards:** frozen dataclasses, files under 400 lines, functions under 50 lines,
   validation at every boundary, no swallowed errors, TDD with 80%+ coverage, offline tests
   (inject fakes; no network, real model or GitHub calls).
3. **No personal data** in code, tests, docs or fixtures: no user names, absolute home paths,
   e-mails, GitHub ids, tokens. Use generic names and fake ids.
4. **No hardcoded paths.** Resolve data locations at command time (`omniscient.home`) so tests can
   point `OMNISCIENT_HOME` at a temp folder.
5. **Never answer a human's side of a HITL ticket.** Grilling and prototype verdicts come only from
   the owner.
6. **Security first.** The widget never blocks an agent, never clicks or types in a web page; a chat
   with a page attached runs with no tools; secrets are never logged. Keep runtime floors low (people
   install on their own PCs): ask before raising a minimum version.
7. User-facing text is French today and goes through `src/omniscient/i18n.py`; code, comments,
   commits and `README.md`/`AGENTS.md` are English; `docs/*.md` are French.

## Branches and releases

- Work on a branch, open a pull request against **`dev`**. Never push to `dev` or `main` directly.
- `dev` -> `main` is a pull request merged with `--merge` (no squash, no rebase).
- Releases: an annotated tag `widget-vX.Y.Z` on `main` builds the widget installer in CI.
- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
- Never `git stash` in a shared worktree, never force-push.

## Known gotchas

- The engine and the widget are installed separately; `omniscient update` updates both.
- On WSL the daemon runs in Linux but the widget is a Windows app: they meet over a local port
  (default 7341). `omniscient group doctor` diagnoses it.
- Time zones and paths differ across Windows, WSL and Linux: keep tests independent of both.
- Tests that exercise `install.sh` and `install.ps1` assert on message texts; update them with the
  scripts.

## Issue tracker

GitHub Issues; see `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md` and
`docs/agents/domain.md`.
