<div align="center">

<img src="widget/src-tauri/icons/128x128@2x.png" alt="Omniscient: a golden eye on a deep-blue tile" width="112" />

# Omniscient

**An idea factory for builders, and a desktop widget that sees the page you see.**

[![CI](https://github.com/VinceVibeCoding/omniscient/actions/workflows/ci.yml/badge.svg)](https://github.com/VinceVibeCoding/omniscient/actions/workflows/ci.yml)
[![Widget build](https://github.com/VinceVibeCoding/omniscient/actions/workflows/widget.yml/badge.svg)](https://github.com/VinceVibeCoding/omniscient/actions/workflows/widget.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB.svg)](https://www.python.org/)

[Quick start](#quick-start) · [Omnigroup widget](#omnigroup-the-widget) · [Ideas](#ideas-the-factory) · [Bring your own AI](#bring-your-own-ai) · [Privacy](#privacy-and-security) · [Roadmap](#roadmap) · [Contributing](#contributing)

</div>

---

Omniscient has two halves that work alone or together:

| | What it is | You use it to |
|---|---|---|
| **Omnigroup** (the widget) | A small always-on-top Windows app. | Watch every AI agent you run, approve their requests, and **chat with the AI of your choice about the web page you are looking at**. |
| **The idea factory** | A terminal studio plus five background loops. | Turn tech news into ideas, have a council of agents debate and score them, and build throwaway prototypes. |

Free and MIT-licensed. Bring your own AI: Claude Code, an API key, or a local model. Your keys and
conversations stay on your computer.

> **Language.** The interface is currently in **French**. Agent-written notes follow the language in
> your profile (`fr` or `en`). Making the UI translatable is a welcome contribution
> (see `src/omniscient/i18n.py`).

## Quick start

### One command (Windows 10/11)

Open **PowerShell** (Start menu › type *PowerShell*), paste, press Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1 | iex"
```

That is the whole install. It needs Windows 10/11 and an internet connection, nothing else (no
admin rights, no git, no Python: the script fetches what is missing; Claude Code is optional, it is
only needed for coding chats). It installs uv, the engine (SHA-256 verified, no git), starts the
engine at every logon, writes the Claude Code hooks (settings backed up first) and installs the
Omnigroup widget. Re-run the same command to update.

Then open **Omnigroup** from the Start menu, go to *Réglages › Demander un code*, type the 6-digit
code shown on your desktop, pick your AI and choose a look. Pin it to your taskbar (right-click ›
*Pin to taskbar*).

**Uninstall:** Windows *Settings › Apps › Omnigroup › Uninstall*, then
`omniscient group autostart remove`, `omniscient group hooks uninstall --write` and
`uv tool uninstall omniscient`. What the script does, what it writes where, full uninstall and
troubleshooting (SmartScreen, antivirus, no winget, proxy): [docs/install.md](docs/install.md)
(in French).

### Manual installation (Installation manuelle)

The widget is a Windows app. It talks to a small background **engine** (a Python program) over a
local-only port. The engine can run **natively on Windows (PowerShell)** or **inside WSL2 / Linux**:
pick one of the two paths below. Either way you install nothing beforehand except uv.

| | A. PowerShell (native Windows) | B. WSL2 / Linux |
|---|---|---|
| Good for | people who prefer to run each step themselves | people who already live in WSL (Claude Code runs there) |
| Engine runs in | Windows | WSL2 |
| Start at login | `omniscient group autostart install --write` | systemd user service |

#### A. PowerShell (native Windows)

Open **PowerShell** (Start menu › type *PowerShell*).

```powershell
# 1. Install uv (it fetches the right Python for you, no separate Python install)
winget install --id astral-sh.uv -e
#    No winget? powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
#    Then CLOSE AND REOPEN PowerShell so `uv` is found.

# 2. Install the engine
uv tool install git+https://github.com/VinceVibeCoding/omniscient   # needs git; the one-liner above does not

# 3. Set up: preview first (writes nothing), then apply
omniscient group setup
omniscient group setup --write     # hooks (settings backed up first) + widget download

# 4. Start the engine (leave this window open) ...
omniscient group serve
#    ... or start it at every logon instead (per-user task, no admin rights, no window):
omniscient group autostart install --write
```

`--write` downloads the Omnigroup installer into your *Downloads* folder and verifies its SHA-256.
**Run that installer** (it adds *Omnigroup* to the Start menu; WebView2 is installed if missing).

#### B. WSL2 / Linux

In a WSL2 terminal (Windows 10/11) or any Linux terminal. The widget itself always runs on Windows.

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh     # then reopen the terminal

# 2. Install the engine
uv tool install git+https://github.com/VinceVibeCoding/omniscient

# 3. Set up: preview first (writes nothing), then apply
omniscient group setup
omniscient group setup --write     # hooks (settings backed up first) + widget download

# 4. Start the engine (leave this terminal open) ...
omniscient group serve
#    ... or run it as a service (needs systemd; in WSL2 set `systemd=true` in /etc/wsl.conf):
omniscient schedule install --write
systemctl --user enable --now omnigroup
```

From WSL, `--write` saves the installer in your **Windows** *Downloads* folder. **Run it from
Windows** (double-click, or `explorer.exe .` from that folder).

#### Then, on both paths: pair

Open **Omnigroup** from the Start menu, go to *Réglages › Demander un code*, type the 6-digit code
shown on your desktop, pick your AI and choose a look. Pin it to your taskbar (right-click › *Pin to
taskbar*): one click on that icon brings the widget back, even after you quit it.

`omniscient group setup` is safe to re-run at any time; its first line says whether the engine
answers on port 7341. Nothing else is required: Claude Code is what the hooks attach to (install it
from [claude.com/claude-code](https://claude.com/claude-code) to see its sessions), and herdr,
AgentRun, Docker and an API key are only for the idea factory (the engine stays quiet without them).

**Several Windows users on one PC?** Everything is per user (engine, hooks in `~/.claude`, widget
settings, the pairing token in that user's Credential Manager): repeat the steps for each user.

### The idea factory

```bash
uv tool install git+https://github.com/VinceVibeCoding/omniscient
omniscient init                   # home folder, profile, projects, keys
herdr                             # open herdr, then inside it:
omniscient studio                 # the idea board
```

The studio needs no API key. Details: [docs/factory.md](docs/factory.md).

## Omnigroup, the widget

One window, three tabs.

**Sessions.** Every agent you run in one list: Claude Code (terminal and VS Code), GitHub Copilot,
herdr panes and Omniscient's own runs. Open one to see its steps. Approve a permission, answer a
question or raise a budget cap without leaving what you are doing. If you do not answer in time,
the agent shows its normal prompt: the widget never blocks an agent.

**Chat.** Talk to the AI you chose, with or without a project:

- **It sees the page you see.** In Chrome, Edge, Brave, Vivaldi or Opera, the widget reads the page
  itself (text, headings, links, buttons, fields and *where each one is on screen*). **No browser
  extension.** Ask "where is the pay button?" and it answers from the real page.
- **It follows you.** Move to another page and the next message offers the new one.
- **Show me.** When the AI points at an element, a **Montrer** button frames it on your screen (the
  page scrolls to it if needed). The widget only draws a frame: it never clicks, types or navigates
  in your page.
- **Screenshot, only if you want.** An optional box adds a picture of that one browser window (never
  the rest of your screen) for questions where the look matters. It is off by default, sent for one
  message, and never saved.
- **Switch it all off.** One button, *Désactiver le suivi des pages*, stops the widget from
  remembering or reading any page. The choice survives restarts.
- **Continue a session.** Take a Claude Code session running in a terminal or IDE and continue it in
  the widget, on a copy.

**Réglages.** Your AI providers, your account (optional), the look (three skins, two gauges),
launch at login, the daemon address, and the first-run assistant.

The OSD (the small collapsed view) shows your Claude limits and live token rate; click it, or the
panel's header, to unfold and fold it. Right-click it for views, themes and the ticker.

Full guide, hooks, threat model and verified behaviour: [docs/omnigroup.md](docs/omnigroup.md) (in French).

### Extensions

Omniscient is not a sealed product: ask it for a command, theme, workflow or provider preset and it
builds it as a small data folder (never code) in `<home>/extensions/`. Type `/reload` in the widget
chat and keep going; `omniscient ext export` and `ext install` (with a full preview) share them.
See [docs/extensions.md](docs/extensions.md) (in French).

## Ideas, the factory

Omniscient reads the news, then helps you decide what to build.

```
news ──▶ ideas ──▶ council (debate + score) ──▶ game plan ──▶ prototype (PoC)
 Sense     Think          Think                    Plan          Build
                          ▲
             studio: you riff, fork, remix and judge ideas
```

- **Sense.** GitHub, Hacker News, and the Anthropic, OpenAI, Gemini and Meta AI news pages, boosted by
  your interests, with the topics you avoid dropped.
- **Think.** A visionary proposes ideas by crossing news with what is newly possible and with *your*
  projects. A council (challenger, simplifier, risk checker) debates each one and scores it on
  novelty, feasibility, impact, effort and fit.
- **Plan.** A strategist promotes the best ideas within your work-in-progress limit.
- **Build.** A builder makes the smallest testable version in a Docker box, never touching your
  real projects without your approval.
- **Learn.** What the agents learn becomes a knowledge base for the next cycle.

You steer it from the **studio**, a terminal idea board that runs inside
[herdr](https://herdr.dev): one *atelier* (workshop) per idea, with Claude Code ready to push the idea
further. Create an idea (`n`), riff on it, make a variant (`v`), remix two or three (`space`, `m`),
pursue or drop it (`p` / `x`). Ideas are plain Markdown notes you can open in Obsidian.

More: [docs/factory.md](docs/factory.md) (init, ateliers, AgentRun, daily schedule, themes, costs, architecture).

## Bring your own AI

| Provider | Needs | Notes |
|---|---|---|
| **Claude Code** | your Claude subscription | Can use tools in a project. A chat with a web page attached runs with no tools. |
| **Anthropic API** | an API key | Plain chat, no tools. |
| **OpenAI** | an API key | Plain chat, no tools. |
| **Gemini** | an API key | Plain chat, no tools. |
| **Local model** (Ollama, LM Studio, any OpenAI-compatible server) | nothing | Stays entirely on your machine. |

Keys are write-only (you can replace one, never read it back), kept in a file only you can read, and
sent only to the provider's own address. The widget's *Tester* button checks that a provider works.
Screenshots need a model that can see images.

## Accounts (optional, free)

An account only identifies your install: sign in with **Google**, **GitHub** or **e-mail and
password**, through [Supabase Auth](https://supabase.com/docs/guides/auth)'s free plan. Your AI keys
and conversations never leave your computer, and the widget works fully without an account.
Setup for the project owner: [docs/accounts.md](docs/accounts.md).

## Privacy and security

- Everything listens on `127.0.0.1` only. Two separate credentials: the agents' hooks can only post
  events, and only your paired widget can answer them.
- The widget reads a web page **only when you send a message with the box ticked**. Between messages
  it remembers just the title of your last browser window, in memory. Field values and passwords are
  never read; secrets in a page are masked before anything leaves.
- Text from a web page is treated as untrusted: a chat with a page attached has **no tools**, so a
  hostile page cannot steer your agent.
- Tokens live in the Windows Credential Manager; the daemon keeps only a hash.
- No analytics, no telemetry.

Threat model and reporting: [docs/omnigroup.md](docs/omnigroup.md) and [SECURITY.md](SECURITY.md).

## Requirements

| Tool | Needed for | Required? |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) and Python 3.12+ (tested on 3.12 and 3.14) | the engine | yes |
| Windows 10/11 x64 (WebView2 is installed for you if missing) | the widget | for the widget |
| Chrome, Edge, Brave, Vivaldi or Opera | reading the page you look at | optional |
| git | project registry, prototypes | for the factory |
| [Claude Code](https://claude.com/claude-code) | the default agent | optional |
| herdr | the studio | for the studio |
| [AgentRun](https://pypi.org/project/parcha-agentrun/) + Docker + an Anthropic API key | the factory loops | for the factory |

Node, TypeScript and Rust are only needed to **build** the widget from source: people who install
Omniscient get built files. `omniscient init` checks your setup and never installs anything for you.
Linux and WSL2 are the tested platforms for the engine.

## Roadmap

- **Now (V1).** Windows widget; Chromium-family browsers; Claude Code, Anthropic, OpenAI, Gemini and
  local models; accounts with Google, GitHub and e-mail.
- **V2.** A **macOS** app (menu-bar and Dock icon, signed and notarized) with page reading through the
  macOS accessibility API; Firefox.
- **Later.** More agents in the Sessions list; a translated interface.

Ideas and votes welcome: open an issue.

## Contributing

Contributions are welcome and every pull request is reviewed by the maintainer before it lands.
Open your pull request against the **`dev`** branch (`main` is what people install). Start with
[CONTRIBUTING.md](CONTRIBUTING.md); tests run fully offline (`uv run pytest -q`). Security issues:
[SECURITY.md](SECURITY.md).

```bash
git clone https://github.com/VinceVibeCoding/omniscient
cd omniscient
uv sync
uv run pytest -q
```

## License

[MIT](LICENSE).

---

## En français

**Omniscient** est une **usine à idées** et un **widget de bureau qui voit la page que tu regardes**.

- **Omnigroup (le widget Windows)** : tous tes agents IA dans une fenêtre, des approbations en un
  clic, et un chat avec l'IA de ton choix (Claude Code, API Anthropic / OpenAI / Gemini, ou un
  modèle local). Il lit lui-même la page web ouverte dans ton navigateur, **sans extension**, te
  montre où est un élément (« Montrer »), et peut joindre une capture de cette seule fenêtre si tu
  le demandes. Un bouton coupe tout le suivi des pages.
- **L'usine à idées** : elle lit l'actualité tech et IA, en tire des idées, les fait débattre et
  noter par un conseil d'agents, planifie les meilleures et construit des prototypes jetables. Tu la
  pilotes depuis le **studio**, dans herdr.

Installation du widget sous Windows, en une commande dans PowerShell (rien d'autre à installer) :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1 | iex"
```

Détails, désinstallation et dépannage : [docs/install.md](docs/install.md). L'usine, ensuite :

```bash
omniscient init                   # l'usine : dossier, profil, projets, clés
```

Gratuit, MIT. Tes clés et tes conversations restent sur ton ordinateur. L'interface est en français
pour l'instant ; les contributions pour l'anglais sont les bienvenues. Guide complet du widget :
[docs/omnigroup.md](docs/omnigroup.md).
