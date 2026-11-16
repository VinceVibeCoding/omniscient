"""Widget chat (mode A): headless Claude Code conversations run by the daemon.

A chat is bound to one project of the Omniscient registry (or the home itself): the
widget names the project, never a path, so Claude only ever runs in a folder the owner
registered. Each turn is `chat_runner.run_turn` on a worker thread; the first turn starts
a new Claude session, the next ones `--resume` it. Events go to the SSE stream as
`chat` events; chats persist as one 0600 JSON file each under `<home>/.omniscient/chats/`.

Security: a widget token can run Claude Code as the owner, in any registered project.
Claude always runs with `--permission-mode default` (chat_runner), so tool calls that
need approval go through Claude Code's PermissionRequest hook to the widget; with the
hooks not installed or no widget answering, headless Claude denies them. Each turn is
capped (`--max-budget-usd`, DEFAULT_MAX_BUDGET_USD) and so is the number of turns per
hour; messages kept or sent to the widget are clipped to MAX_MESSAGE_CHARS.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from omniscient.group import chat_runner, llm_chat
from omniscient.group.chat_runner import RunnerEvent, TurnHandle, TurnOutcome, TurnSpec
from omniscient.group.chat_store import (
    Chat,
    Message,
    ProjectRef,
    dump,
    list_projects,
    load,
    path_label,
    write_private,
)
from omniscient.group.credentials import secure_dir
from omniscient.group.models import iso, utcnow
from omniscient.group.page_context import PageContext, PageError, clean_page
from omniscient.group.page_context import render as render_page
from omniscient.group.providers import CLAUDE_CODE, ProviderStore
from omniscient.home import Home
from omniscient.redact import redact_secrets

log = logging.getLogger(__name__)

MAX_TEXT = 20_000
MAX_RUNNING = 2
MAX_CHATS = 200
TITLE_MAX = 60
MAX_MESSAGE_CHARS = 8000  # one assistant / tool / error message (~8 KB)
DEFAULT_MAX_BUDGET_USD = 2.0  # per turn, passed to claude --max-budget-usd
MAX_TURNS_PER_HOUR = 30
HOUR_S = 3600.0
CHAT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
Publish = Callable[[str, dict[str, Any]], None]
Runner = Callable[[TurnSpec, Callable[[RunnerEvent], None], TurnHandle], TurnOutcome]


class ChatError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _text(raw: Any) -> str:
    if not isinstance(raw, str) or len(raw) > MAX_TEXT:
        raise ChatError(400, f"text : texte de {MAX_TEXT} caractères au plus attendu")
    if not raw.strip():
        raise ChatError(400, "text ne doit pas être vide")
    return raw


def _claude_session_id(raw: Any) -> str:
    if not isinstance(raw, str) or not chat_runner.SESSION_ID.match(raw):
        raise ChatError(400, "Identifiant de session Claude invalide.")
    return raw


def _page_context(page: Any) -> PageContext | None:
    """The page of a request, validated (a ready PageContext passes as is); None = no page."""
    if page is None or isinstance(page, PageContext):
        return page
    try:
        return clean_page(page)
    except PageError as exc:
        raise ChatError(exc.status, exc.message) from exc


def _page_fields(block: str) -> tuple[str, str]:
    """(title, url) written in a rendered page block: each page line shows its own page."""
    title = url = ""
    for line in block.splitlines():
        if line.startswith("Title: ") and not title:
            title = line[len("Title: ") :]
        elif line.startswith("URL: ") and not url:
            url = line[len("URL: ") :]
    return title, url


def _shown(chat: Chat, message: Message) -> dict[str, Any]:
    """A message as the widget sees it; an attached page shows as one line, never its text."""
    if message.role != "context":
        return message.to_json()
    title, url = _page_fields(message.text)
    label = title or url or "page"
    return {
        "role": "tool",
        "tool": "Page",
        "text": f"Page jointe : {label} — {url}" if url else f"Page jointe : {label}",
        "at": iso(message.at),
    }


def _clip(text: str) -> str:
    return (
        text if len(text) <= MAX_MESSAGE_CHARS else text[: MAX_MESSAGE_CHARS - 1] + "…"
    )


def _resolve(claude: Sequence[str]) -> tuple[str, ...]:
    """Resolve a bare `claude` command once through the daemon's PATH (logged)."""
    argv = tuple(claude)
    if not argv or "/" in argv[0]:
        return argv
    found = shutil.which(argv[0])
    if found is None:
        log.warning("omnigroup chat: %s not found in the daemon PATH", argv[0])
        return argv
    log.info("omnigroup chat: using %s", found)
    return (found, *argv[1:])


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1] + "…"


# ---- manager -------------------------------------------------------------------------


class ChatManager:
    """Chats in memory (under a lock) mirrored to disk; one worker thread per turn."""

    def __init__(
        self,
        home: Home,
        publish: Publish,
        claude: Sequence[str] = ("claude",),
        runner: Runner = chat_runner.run_turn,
        max_running: int = MAX_RUNNING,
        max_chats: int = MAX_CHATS,
        timeout_s: float = chat_runner.DEFAULT_TIMEOUT_S,
        max_budget_usd: float | None = DEFAULT_MAX_BUDGET_USD,
        max_turns_per_hour: int = MAX_TURNS_PER_HOUR,
        clock: Callable[[], float] = time.monotonic,
        providers: ProviderStore | None = None,
        llm: Callable[..., str] = llm_chat.complete,
    ) -> None:
        self.home = home
        self._providers = providers or ProviderStore(home.state)
        self._llm = llm
        self._publish = publish
        self._claude = _resolve(claude)
        self._runner = runner
        self._max_running = max_running
        self._max_chats = max_chats
        self._timeout_s = timeout_s
        self._budget = max_budget_usd
        self._max_per_hour = max_turns_per_hour
        self._clock = clock
        self._turns: deque[float] = deque()  # start times of the last hour's turns
        self._lock = threading.Lock()
        self._running: dict[str, TurnHandle] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._dir = home.state / "chats"
        self._chats: dict[str, Chat] = self._load_all()

    # -- public API (raises ChatError) --

    def create(
        self, project: Any, text: Any, provider: Any = None, page: Any = None
    ) -> str:
        """A new chat. `provider`: Claude Code (a project is required, it runs there) or a
        saved provider id (plain chat, no tools; the project is optional). None = the
        person's default provider. `page` (from the browser extension) attaches a web page
        as untrusted context: the chat then runs without any tool, and needs no project."""
        context = _page_context(page)
        engine = self._engine(provider)
        needs_project = engine == CLAUDE_CODE and context is None
        ref = self._project(project) if needs_project or project else self._home_ref()
        prompt = _text(text)
        now = utcnow()
        chat = Chat(
            str(uuid.uuid4()),
            ref.name,
            _title(prompt),
            "running",
            now,
            now,
            provider=engine,
            read_only=context is not None,
            page_url=context.url if context else None,
            page_title=context.title if context else None,
        )
        if context is not None:
            chat = chat.with_message(Message("context", render_page(context), now))
            prompt_for_claude = f"{render_page(context)}\n\n{prompt}"
        else:
            prompt_for_claude = prompt
        with self._lock:
            self._reserve_slot()
            self._chats[chat.chat_id] = chat.with_message(Message("user", prompt, now))
            self._running[chat.chat_id] = TurnHandle()
        self._prune()
        self._start(chat.chat_id, ref, prompt_for_claude, None)
        return chat.chat_id

    def fork(self, session_native_id: Any, cwd: Any, text: Any) -> str:
        """Continue a session running elsewhere (terminal, IDE) in a widget chat: Claude
        resumes a copy of it (`--resume <id> --fork-session`) in the session's own folder,
        which must lie inside a known project. The chat only learns the copy's id once
        Claude reports it, so a turn that fails earlier can never resume the original."""
        native = _claude_session_id(session_native_id)
        ref = self._project_of(cwd)
        prompt = _text(text)
        now = utcnow()
        chat = Chat(str(uuid.uuid4()), ref.name, _title(prompt), "running", now, now)
        with self._lock:
            self._reserve_slot()
            self._chats[chat.chat_id] = chat.with_message(Message("user", prompt, now))
            self._running[chat.chat_id] = TurnHandle()
        self._prune()
        self._start(chat.chat_id, ref, prompt, native, fork=True)
        return chat.chat_id

    def send(self, chat_id: str, text: Any, page: Any = None) -> None:
        """A follow-up. `page` attaches the page the person is on now (untrusted context): only
        to a chat that already runs without tools, or to a plain provider (it has none); a
        Claude Code chat with tools is refused, since page text could steer them."""
        prompt = _text(text)
        context = _page_context(page)
        with self._lock:
            chat = self._get(chat_id)
            if chat_id in self._running:
                raise ChatError(409, "Claude répond encore : attends la fin du tour.")
            if (
                context is not None
                and chat.provider == CLAUDE_CODE
                and not chat.read_only
            ):
                raise ChatError(
                    409,
                    "Cette conversation peut utiliser des outils : commence-en une nouvelle "
                    "pour y joindre une page web.",
                )
            ref = self._project(chat.project)
            self._reserve_slot()
            now = utcnow()
            if context is not None:
                chat = replace(
                    chat.with_message(Message("context", render_page(context), now)),
                    read_only=True,
                    page_url=context.url or None,
                    page_title=context.title or None,
                )
            chat = replace(
                chat.with_message(Message("user", prompt, now)), state="running"
            )
            self._chats[chat_id] = chat
            self._running[chat_id] = TurnHandle()
        sent = f"{render_page(context)}\n\n{prompt}" if context is not None else prompt
        self._start(chat_id, ref, sent, chat.claude_session_id)

    def stop(self, chat_id: str) -> bool:
        with self._lock:
            self._get(chat_id)
            handle = self._running.get(chat_id)
        if handle is None:
            return False
        handle.stop()
        return True

    def stop_all(self) -> int:
        """Stop every running turn (daemon shutdown); returns how many were stopped."""
        with self._lock:
            handles = list(self._running.values())
        for handle in handles:
            handle.stop()
        return len(handles)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            chats = sorted(
                self._chats.values(), key=lambda c: c.updated_at, reverse=True
            )
        return [c.summary() for c in chats]

    def get(self, chat_id: str) -> tuple[Chat, dict[str, Any]]:
        with self._lock:
            chat = self._get(chat_id)
        return chat, {
            "chat": chat.summary(),
            "messages": [_shown(chat, m) for m in chat.messages],
        }

    def join(self, chat_id: str, timeout: float | None = None) -> None:
        """Wait for the chat's running turn (tests, shutdown)."""
        thread = self._threads.get(chat_id)
        if thread is not None:
            thread.join(timeout)

    def projects(self) -> tuple[ProjectRef, ...]:
        return list_projects(self.home)

    # -- internals --

    def _engine(self, requested: Any) -> str:
        """The provider id to use: validated, with a key when it needs one."""
        view = self._providers.listing()
        engine = view["default"] if requested is None else requested
        if not isinstance(engine, str):
            raise ChatError(400, "provider : identifiant attendu")
        if engine == CLAUDE_CODE:
            return engine
        found = self._providers.get(engine)
        if found is None:
            raise ChatError(
                404, "Fournisseur inconnu : choisissez-en un dans les réglages."
            )
        provider, key = found
        if key is None and provider.kind != "openai-compatible":
            raise ChatError(400, "Ajoutez la clé de ce fournisseur dans les réglages.")
        if not provider.model:
            raise ChatError(
                400, "Choisissez un modèle pour ce fournisseur dans les réglages."
            )
        return engine

    def _home_ref(self) -> ProjectRef:
        return next(
            r for r in list_projects(self.home) if r.name == self.home.root.name
        )

    def _project(self, name: Any) -> ProjectRef:
        if not isinstance(name, str):
            raise ChatError(400, "project : nom de projet attendu")
        found = next((r for r in list_projects(self.home) if r.name == name), None)
        if found is None:
            raise ChatError(404, f"projet inconnu : {name[:80]}")
        return found

    def _project_of(self, cwd: Any) -> ProjectRef:
        """The session's folder, if it is a known project or inside one (never elsewhere)."""
        if not isinstance(cwd, str) or not cwd.strip():
            raise ChatError(400, "Cette session n'a pas de dossier connu.")
        try:
            folder = Path(cwd).resolve(strict=True)
        except (OSError, RuntimeError):
            raise ChatError(404, "Le dossier de cette session n'existe plus.") from None
        if not folder.is_dir():
            raise ChatError(404, "Le dossier de cette session n'existe plus.")
        for ref in sorted(list_projects(self.home), key=lambda r: -len(r.path.parts)):
            root = ref.path.resolve()
            if folder == root or root in folder.parents:
                return ProjectRef(ref.name, folder, ref.path_label)
        raise ChatError(404, "Cette session n'est dans aucun projet connu.")

    def _get(self, chat_id: str) -> Chat:
        chat = self._chats.get(chat_id) if CHAT_ID.match(chat_id or "") else None
        if chat is None:
            raise ChatError(404, "conversation inconnue")
        return chat

    def _reserve_slot(self) -> None:
        """Under the lock: refuse a turn over the concurrency or hourly cap."""
        if len(self._running) >= self._max_running:
            raise ChatError(
                429, f"Déjà {self._max_running} conversation(s) en cours : attends."
            )
        now = self._clock()
        while self._turns and now - self._turns[0] >= HOUR_S:
            self._turns.popleft()
        if len(self._turns) >= self._max_per_hour:
            raise ChatError(
                429,
                f"Limite de {self._max_per_hour} tours par heure atteinte : réessaie plus tard.",
            )
        self._turns.append(now)

    def _start(
        self,
        chat_id: str,
        ref: ProjectRef,
        prompt: str,
        resume: str | None,
        fork: bool = False,
    ) -> None:
        self._save(chat_id)
        self._emit(chat_id, "state", state="running")
        if self._chats[chat_id].provider == CLAUDE_CODE:
            target, args = self._run, (chat_id, ref, prompt, resume, fork)
        else:
            target, args = self._run_plain, (chat_id,)
        thread = threading.Thread(
            target=target, args=args, daemon=True, name=f"omnigroup-chat-{chat_id[:8]}",
        )  # fmt: skip
        self._threads[chat_id] = thread
        thread.start()

    def _run(
        self,
        chat_id: str,
        ref: ProjectRef,
        prompt: str,
        resume: str | None,
        fork: bool = False,
    ) -> None:
        handle = self._running[chat_id]
        try:
            with self._lock:
                tools_off = self._chats[chat_id].read_only
            argv = chat_runner.build_argv(
                self._claude, resume, self._budget, fork, tools_off=tools_off
            )
            spec = TurnSpec(argv, ref.path, prompt, self._timeout_s)
            outcome = self._runner(spec, lambda e: self._on_event(chat_id, e), handle)
        except Exception as exc:  # never leave a chat stuck in "running"
            log.exception("omnigroup chat: turn crashed")
            outcome = TurnOutcome(
                False, error=f"Erreur interne du démon : {type(exc).__name__}"
            )
        self._finish(chat_id, outcome)

    def _run_plain(self, chat_id: str) -> None:
        """One turn with a non-Claude-Code provider: the whole conversation in, one reply out."""
        handle = self._running[chat_id]
        try:
            with self._lock:
                chat = self._chats[chat_id]
            found = self._providers.get(chat.provider)
            if found is None:
                raise llm_chat.LlmError(
                    "Ce fournisseur a été retiré : choisissez-en un autre."
                )
            provider, key = found
            turns = llm_chat.build_turns(chat.messages)
            reply = self._llm(provider, key, turns, resolver=self._providers.resolver)
            if handle.stop_requested.is_set():
                outcome = TurnOutcome(False, error="Tour arrêté.", stopped=True)
            else:
                self._on_event(chat_id, RunnerEvent("text", text=reply))
                self._on_event(chat_id, RunnerEvent("result"))
                outcome = TurnOutcome(True)
        except llm_chat.LlmError as exc:
            outcome = TurnOutcome(False, error=exc.message)
        except Exception as exc:  # never leave a chat stuck in "running"
            log.exception("omnigroup chat: provider turn crashed")
            outcome = TurnOutcome(
                False, error=f"Erreur interne du démon : {type(exc).__name__}"
            )
        self._finish(chat_id, outcome)

    def _on_event(self, chat_id: str, event: RunnerEvent) -> None:
        now = utcnow()
        message: Message | None = None
        if event.kind == "text" and event.text:
            text = _clip(redact_secrets(event.text, keep_paths=True))
            message = Message("assistant", text, now)
        elif event.kind == "tool":
            message = Message("tool", _clip(event.text or ""), now, event.tool)
        with self._lock:
            chat = self._chats[chat_id]
            if event.session_id:
                chat = replace(chat, claude_session_id=event.session_id)
            if event.kind == "result" and event.cost_usd is not None:
                chat = replace(chat, cost_usd=event.cost_usd)
            if message is not None:
                chat = chat.with_message(message)
            self._chats[chat_id] = chat
        if message is not None:
            self._emit(
                chat_id,
                "text" if message.role == "assistant" else "tool",
                text=message.text,
                tool=message.tool,
            )
        elif event.kind == "result":
            self._emit(
                chat_id,
                "error" if event.is_error else "result",
                cost_usd=event.cost_usd,
            )

    def _finish(self, chat_id: str, outcome: TurnOutcome) -> None:
        state = "idle" if outcome.ok or outcome.stopped else "error"
        with self._lock:
            chat = replace(self._chats[chat_id], state=state)
            if outcome.session_id:
                chat = replace(chat, claude_session_id=outcome.session_id)
            if not outcome.ok and not outcome.stopped:
                error = _clip(outcome.error)
                chat = chat.with_message(Message("error", error, utcnow()))
            self._chats[chat_id] = chat
            self._running.pop(chat_id, None)
        if not outcome.ok and not outcome.stopped:
            self._emit(chat_id, "error", text=_clip(outcome.error))
        self._save(chat_id)
        self._emit(chat_id, "state", state=state)

    def _emit(self, chat_id: str, kind: str, **fields: Any) -> None:
        data = {"chat_id": chat_id, "kind": kind, "at": iso(utcnow())}
        data.update({k: v for k, v in fields.items() if v is not None})
        try:
            self._publish("chat", data)
        except Exception:
            log.exception("omnigroup chat: event not published")

    def _save(self, chat_id: str) -> None:
        with self._lock:
            chat = self._chats.get(chat_id)
        if chat is None:
            return
        try:
            write_private(secure_dir(self._dir) / f"{chat_id}.json", dump(chat))
        except OSError:
            log.exception("omnigroup chat: %s not saved", chat_id)

    def _prune(self) -> None:
        with self._lock:
            idle = sorted(
                (c for c in self._chats.values() if c.chat_id not in self._running),
                key=lambda c: c.updated_at,
            )
            extra = max(0, len(self._chats) - self._max_chats)
            dropped = [c.chat_id for c in idle[:extra]]
            for chat_id in dropped:
                self._chats.pop(chat_id, None)
        for chat_id in dropped:
            try:
                (self._dir / f"{chat_id}.json").unlink(missing_ok=True)
            except OSError:
                log.exception("omnigroup chat: %s not deleted", chat_id)

    def _load_all(self) -> dict[str, Chat]:
        chats: dict[str, Chat] = {}
        if not self._dir.is_dir():
            return chats
        for file in self._dir.glob("*.json"):
            if not CHAT_ID.match(file.stem):
                continue
            try:
                chat = load(file.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("omnigroup chat: %s ignored (%s)", file.name, exc)
                continue
            chats[chat.chat_id] = chat
        return chats


__all__ = [
    "Chat",
    "ChatError",
    "ChatManager",
    "Message",
    "ProjectRef",
    "list_projects",
    "path_label",
]
