# Code signing policy

Omniscient is free, open-source software (MIT). This page explains how the Windows installer is
built and signed, and who can approve a signed release.

## Status

**Not signed yet.** We are applying to the [SignPath Foundation](https://signpath.org/)
open-source programme for a free code signing certificate. Until it is granted, releases are
unsigned and Windows SmartScreen may warn when you run the installer (see
[docs/install.md](install.md#dépannage)). You can always verify a download against the
`SHA256SUMS` file attached to the same release; the install scripts already do this for you.

When signing is active, this page will say so, and the README will carry the attribution required
by the programme: *Free code signing provided by SignPath.io, certificate by SignPath Foundation.*

## What is signed

Only the Windows installer and widget executable that GitHub Actions builds from this public
repository (`.github/workflows/widget.yml`) for a release tag (`widget-v*`). Nothing is signed
from a developer's computer, and no binary is built from a fork or an unreviewed branch.

## Roles

| Role | Who | Can do |
|---|---|---|
| Committer | repository maintainers (GitHub: `VinceVibeCoding`) | merge pull requests into `dev` and `main` |
| Reviewer | the maintainer who is not the author when there is one; otherwise the CI checks (tests, typecheck, installer build on a clean Windows runner) | check a change before it is merged |
| Approver | `VinceVibeCoding` | approve a signing request for a release tag |

Everyone with these roles uses multi-factor authentication on GitHub and on SignPath.

## Process

1. Changes go through pull requests against `dev`; CI must pass.
2. A release is cut by merging `dev` into `main` and pushing an annotated tag `widget-vX.Y.Z`.
3. The Widget workflow builds the installer from that tag on a GitHub-hosted runner.
4. The approver reviews the signing request; only then is the artifact signed and attached to the
   draft release, which is published afterwards.
5. `SHA256SUMS` is generated from the signed files.

## Privacy

The app has no analytics and no telemetry. It talks to the network only to do what you ask: the AI
provider you configure, the web pages you open, GitHub for updates, and the accounts service
(Supabase) when you sign in. Your AI keys and conversations stay on your computer. See
[Privacy and security](../README.md#privacy-and-security).

## Reporting a problem

Suspected malicious or wrongly signed binaries: use GitHub's
[private vulnerability reporting](https://github.com/VinceVibeCoding/omniscient/security/advisories/new)
(see [SECURITY.md](../SECURITY.md)).
