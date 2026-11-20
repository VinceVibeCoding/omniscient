# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/VinceVibeCoding/omniscient/security/advisories/new)
on this repository. You should get a first answer within a week.

Include what you found, how to reproduce it, and the impact you expect. Remove any real
API key or token from the report.

## Supported versions

Only the latest commit on `main` is supported. There are no release branches yet.

## How Omniscient handles secrets and risk

- Everything listens on `127.0.0.1` only. The agents' hooks hold a credential that can only post
  events; only your paired widget can answer them. The widget's token lives in the Windows
  Credential Manager and the daemon keeps only a hash.
- AI provider keys are write-only (you can replace one, never read it back), are kept in a file only
  you can read, and are sent only to the provider's own address. They are never written into logs.
- Text from a web page is untrusted (prompt injection): a chat with a page attached runs with **no
  tools**, secrets in a page are masked before anything leaves, and field values and passwords are
  never read.
- Model spending is capped in code, not by prompts.
- No analytics, no telemetry.

Details and threat model: [docs/omniscient.md](docs/omniscient.md) (in French).

## Scope

In scope: this repository's code (`src/`, `widget/`, `scripts/`, the installers, CI). Out of scope:
Claude Code and other third-party tools it talks to; report those upstream.
