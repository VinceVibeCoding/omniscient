<div align="center">

<img src="widget/src-tauri/icons/128x128@2x.png" alt="Omniscient: a golden eye on a deep-blue tile" width="112" />

# Omniscient

**A desktop widget for your AI agents: see them, approve them, and chat about the page you are looking at.**

[![CI](https://github.com/VinceVibeCoding/omniscient/actions/workflows/ci.yml/badge.svg)](https://github.com/VinceVibeCoding/omniscient/actions/workflows/ci.yml)
[![Widget build](https://github.com/VinceVibeCoding/omniscient/actions/workflows/widget.yml/badge.svg)](https://github.com/VinceVibeCoding/omniscient/actions/workflows/widget.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB.svg)](https://www.python.org/)

[Quick start](#quick-start) · [What it does](#omniscient-the-widget) · [Bring your own AI](#bring-your-own-ai) · [Privacy](#privacy-and-security) · [Roadmap](#roadmap) · [Contributing](#contributing)

</div>

---

Omniscient is a small always-on-top Windows widget and the local engine behind it. Use it to:

- **Watch every AI agent you run** (Claude Code, GitHub Copilot and more) from outside your IDE, and
  approve their requests.
- **Monitor your LLM usage** against your subscriptions.
- **Chat with the AI of your choice about the web page you are looking at.**

Free and MIT-licensed. Bring your own AI: Claude Code, an API key, or a local model. Your keys and
conversations stay on your computer.

> **Language.** The interface is currently in **French**. Making the UI translatable is a welcome contribution
> (strings live in `widget/src` and `src/omniscient`).

## Quick start

### Which install is for me?

| You are on | Run | You get |
|---|---|---|
| Windows 10/11 | the PowerShell one-liner | the full app: engine and widget |
| WSL (inside Windows) | `install.sh` | the engine in WSL and the Windows widget |
| Linux (native) or macOS | `install.sh` | the engine and the terminal only (no widget yet; Mac is V2) |
| Any, step by step | the manual install below (`uv tool install`) | the engine; `omniscient group setup --write` downloads the widget installer, which you run yourself |

On Windows, SmartScreen may show a warning because the installer is not code-signed yet; see
[docs/install.md](docs/install.md#dépannage) (in French).

### One command

| Windows 10/11 (PowerShell) | Linux, macOS, WSL (any shell) |
|---|---|
| `powershell -ExecutionPolicy ByPass -c "iex ((irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1) -join [char]10)"` | `curl -fsSL https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.sh \| sh` |

**Linux, macOS, WSL:** no root, no git, no Python needed (uv fetches it). The script installs uv, the
engine (SHA-256 verified), starts the daemon (systemd user service when available), writes the Claude
Code hooks (settings backed up first) and, on WSL, installs the Windows widget. On native Linux and
macOS there is no widget yet (Mac: V2): use `omniscient` in the terminal. Details, update and
uninstall: [docs/install.md](docs/install.md#linux-macos-et-wsl-installsh).

#### Windows 10/11

Open **PowerShell** (Start menu › type *PowerShell*), paste, press Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "iex ((irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1) -join [char]10)"
```

That is the whole install. It needs Windows 10/11 and an internet connection, nothing else (no
admin rights, no git, no Python: the script fetches what is missing; Claude Code is optional, it is
only needed for coding chats). It installs uv, the engine (SHA-256 verified, no git), starts the
engine at every logon, writes the Claude Code hooks (settings backed up first) and installs the
Omniscient widget.

**Update:** `omniscient update` (engine and widget; `--check` only compares, `--dry-run` shows the plan).

Then open **Omniscient** from the Start menu. The first-run assistant has a *Connexion* form: type your
e-mail, type the 6-digit code you receive by e-mail, and you stay signed in across sessions (the
token is kept in the Windows Credential Manager). Then pick your AI and choose a look. No e-mail or
offline? Fall back to *Réglages › Demander un code* and type the 6-digit code shown on your desktop.
Pin it to your taskbar (right-click › *Pin to taskbar*).

**Uninstall:** Windows *Settings › Apps › Omniscient › Uninstall*, then
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

`--write` downloads the Omniscient installer into your *Downloads* folder and verifies its SHA-256.
**Run that installer** (it adds *Omniscient* to the Start menu; WebView2 is installed if missing).

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
systemctl --user enable --now omniscient
```

From WSL, `--write` saves the installer in your **Windows** *Downloads* folder. **Run it from
Windows** (double-click, or `explorer.exe .` from that folder).

#### Then, on both paths: sign in

Open **Omniscient** from the Start menu. In the *Connexion* form (first-run assistant, or
*Réglages*), type your e-mail, then the 6-digit code you receive by e-mail: you stay signed in
across sessions. If you have no e-mail or are offline, use the fallback: *Réglages › Demander un
code* and type the 6-digit code shown on your desktop. Then pick your AI and choose a look. Pin it to your taskbar (right-click › *Pin to
taskbar*): one click on that icon brings the widget back, even after you quit it.

`omniscient group setup` is safe to re-run at any time; its first line says whether the engine
answers on port 7341. Nothing else is required: Claude Code is what the hooks attach to (install it
from [claude.com/claude-code](https://claude.com/claude-code) to see its sessions).

**Several Windows users on one PC?** Everything is per user (engine, hooks in `~/.claude`, widget
settings, the pairing token in that user's Credential Manager): repeat the steps for each user.

## Omniscient, the widget

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

Full guide, hooks, threat model and verified behaviour: [docs/omniscient.md](docs/omniscient.md) (in French).

### Extensions

Omniscient is not a sealed product: ask it for a command, theme, workflow or provider preset and it
builds it as a small data folder (never code) in `<home>/extensions/`. Type `/reload` in the widget
chat and keep going; `omniscient ext export` and `ext install` (with a full preview) share them.
See [docs/extensions.md](docs/extensions.md) (in French).

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

An account only identifies your install. Sign in with an **e-mail code** (the main path) through
[Supabase Auth](https://supabase.com/docs/guides/auth)'s free plan. Google and GitHub sign-in are built
in too, but each only works once the project owner enables that provider in Supabase. The
accounts project ships preconfigured in the app, so you configure nothing; people who self-host can
override it. Your AI keys and conversations never leave your computer, and the widget works fully
without an account. Details and self-hosting: [docs/accounts.md](docs/accounts.md).

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

Threat model and reporting: [docs/omniscient.md](docs/omniscient.md) and [SECURITY.md](SECURITY.md).
How the Windows installer is built and signed: [docs/code-signing-policy.md](docs/code-signing-policy.md).

## Requirements

| Tool | Needed for | Required? |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) and Python 3.12+ (tested on 3.12 and 3.14) | the engine | yes |
| Windows 10/11 x64 (WebView2 is installed for you if missing) | the widget | for the widget |
| Chrome, Edge, Brave, Vivaldi or Opera | reading the page you look at | optional |
| [Claude Code](https://claude.com/claude-code) | the default agent | optional |

Node, TypeScript and Rust are only needed to **build** the widget from source: people who install
Omniscient get built files.
Linux and WSL2 are the tested platforms for the engine.

## Roadmap

Planned, not done yet:

- Automatic first-run pairing (no code to type).
- The engine bundled in the widget installer.
- In-app auto-update.
- winget, Scoop and Homebrew packages.
- A tray icon and a terminal command to open the widget.
- Code signing through the SignPath Foundation (application in progress).

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

**Omniscient** est un **widget de bureau Windows** pour tes agents IA : tous tes agents dans une
fenêtre, des approbations en un clic, ton usage des modèles face à tes abonnements, et un chat avec
l'IA de ton choix (Claude Code, API Anthropic / OpenAI / Gemini, ou un modèle local). Il lit
lui-même la page web ouverte dans ton navigateur, **sans extension**, te montre où est un élément
(« Montrer »), et peut joindre une capture de cette seule fenêtre si tu le demandes. Un bouton coupe
tout le suivi des pages.

Installation du widget sous Windows, en une commande dans PowerShell (rien d'autre à installer) :

```powershell
powershell -ExecutionPolicy ByPass -c "iex ((irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1) -join [char]10)"
```

Mettre à jour : `omniscient update`. Détails, désinstallation et dépannage : [docs/install.md](docs/install.md).

Gratuit, MIT. Tes clés et tes conversations restent sur ton ordinateur. L'interface est en français
pour l'instant ; les contributions pour l'anglais sont les bienvenues. Guide complet du widget :
[docs/omniscient.md](docs/omniscient.md).
