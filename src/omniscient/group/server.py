"""omniscient daemon: a local HTTP + SSE API over the store (stdlib only).

Security: binds 127.0.0.1 only; each route names the credential it takes (api.Route.auth):
the hook credential only reaches POST /hook and, with its wait ticket, the wait on the
pending that call opened; a paired widget's token reaches the rest; presenting the
wrong one is a 403. The Host header must be a loopback name (DNS rebinding); browser
origins other than the Tauri widget are refused; bodies are size-limited JSON objects;
route ids are validated; at most MAX_CONNECTIONS requests and MAX_STREAMS streams at once.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlsplit

from omniscient.group import api, api_auth, api_stream, workers
from omniscient.group.api import ApiError
from omniscient.group.credentials import (
    WidgetTokens,
    db_path,
    load_or_create_hook_token,
    same_secret,
    secure_dir,
)
from omniscient.group.gates import Presence, TicketBook
from omniscient.group.pairing import PairingDesk, show_code_on_windows
from omniscient.group.procctl import install_stop_signals
from omniscient.group.store import Store
from omniscient.home import Home

log = logging.getLogger(__name__)

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 7341
TICKET_HEADER = "X-Omniscient-Ticket"
MAX_CONNECTIONS = 64
ALLOWED_ORIGINS = frozenset(
    {"http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"}
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})


def allowed_origins() -> frozenset[str]:
    """The widget's webview origins: nothing else may call the daemon from a page."""
    return ALLOWED_ORIGINS


SOCKET_TIMEOUT_S = 30
HEARTBEAT_S = 15.0
SERVE_POLL_S = 0.1
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,199}$")


class Collector(Protocol):
    name: str

    def run(self, store: Store, stop: threading.Event) -> None: ...

    def answer(self, pending: Any, answer: dict[str, Any]) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class App:
    """Everything a request handler needs (fakes are injected in tests)."""

    home: Home
    store: Store
    hook_token: str
    widgets: WidgetTokens
    collectors: tuple[Collector, ...] = ()
    translate: Callable[[str, dict[str, Any]], Any] | None = None
    actions: Any = None
    heartbeat_s: float = HEARTBEAT_S
    stopping: threading.Event = field(default_factory=threading.Event)
    # One hook_usage.UsageCursor per session (daemon memory only), under usage_lock.
    usage_cursors: dict[str, Any] = field(default_factory=dict)
    usage_lock: threading.Lock = field(default_factory=threading.Lock)
    tickets: TicketBook = field(default_factory=TicketBook)
    presence: Presence = field(default_factory=Presence)
    pairing: PairingDesk = field(default_factory=PairingDesk)
    show_code: Callable[[str], bool] = show_code_on_windows
    allow_terminal_pairing: bool = False
    osd: Any = None  # osd.OsdState: limits, live tok/min, ticker, widget config
    chat: Any = None  # chat.ChatManager: headless Claude chats from the widget
    providers: Any = None  # providers.ProviderStore: other LLM providers and their keys
    extensions: Any = None  # ext_store.ExtensionStore: declarative extensions
    auth: Any = (
        None  # auth.AuthService: sign-in with Google / GitHub / e-mail (Supabase Auth)
    )


# ---- HTTP ------------------------------------------------------------------------------


class GroupServer(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR on Windows lets a second process share a busy port (a silent hijack):
    # there the port is taken exclusively instead (see server_bind).
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, app: App, port: int) -> None:
        self.app = app
        self._workers: list[threading.Thread] = []
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__((BIND_HOST, port), Handler)

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:  # Windows only
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def process_request(self, request: Any, client_address: Any) -> None:
        """At most MAX_CONNECTIONS requests at once; the next ones are closed (M10)."""
        if not self._slots.acquire(blocking=False):
            log.warning("omniscient: too many connections, one refused")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def start_background(self) -> None:
        """Collectors, the janitor and the HTTP loop, each on a daemon thread."""
        for collector in self.app.collectors:
            self._spawn(
                f"collector-{collector.name}",
                workers.run_collector,
                collector,
                self.app,
            )
        self._spawn("janitor", workers.janitor, self.app)
        if self.app.osd is not None:
            from omniscient.group.osd import OsdWorker

            worker = OsdWorker(self.app.osd, self.app.store._publish)
            self._spawn("osd", worker.run, self.app.stopping)
        self._spawn("http", self.serve_forever, SERVE_POLL_S)

    def _spawn(self, name: str, target: Callable[..., None], *args: Any) -> None:
        thread = threading.Thread(
            target=target, args=args, name=f"omniscient-{name}", daemon=True
        )
        thread.start()
        self._workers.append(thread)

    def stop(self) -> None:
        self.app.stopping.set()
        self.shutdown()
        self.server_close()

    def close_all(self) -> None:
        """Stop serving and any running chat turn, then close the databases."""
        self.stop()
        if self.app.chat is not None:
            self.app.chat.stop_all()
        self.app.store.close()
        self.app.widgets.close()


class Handler(BaseHTTPRequestHandler):
    server: GroupServer
    timeout = SOCKET_TIMEOUT_S
    server_version = "omniscient"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("omniscient %s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        try:
            self._guard()
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        if self.headers.get("Origin") not in allowed_origins():
            self._send_json(403, {"error": "origine refusée"})
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- dispatch ----------------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        try:
            self._guard()
            url = urlsplit(self.path)
            route, params = api.match(method, url.path)
            ids = {k: _route_id(v) for k, v in params.items()}
            self._authorize(route.auth, ids)
            if route.name == "stream":
                self._stream()
                return
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            body = self._read_body(route.max_body) if method in ("POST", "PUT") else {}
            status, payload = route.handler(self.server.app, ids, query, body)
            if api_auth.HTML_KEY in payload:
                self._send_html(status, payload[api_auth.HTML_KEY])
            else:
                self._send_json(status, payload)
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except (BrokenPipeError, ConnectionResetError):
            log.debug("omniscient: client went away")
        except Exception:
            log.exception("omniscient: %s %s failed", method, self.path.split("?")[0])
            self._send_json(500, {"error": "erreur interne"})

    def _guard(self) -> None:
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if name not in LOOPBACK_HOSTS:
            raise ApiError(421, "hôte refusé")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in allowed_origins():
            raise ApiError(403, "origine refusée")

    def _caller(self) -> str | None:
        """ "hook", "widget" or None, from `Authorization: Bearer <token>`."""
        header = self.headers.get("Authorization") or ""
        scheme, _, given = header.partition(" ")
        given = given.strip()
        if scheme.lower() != "bearer" or not given:
            return None
        app = self.server.app
        if same_secret(given, app.hook_token):
            return "hook"
        return "widget" if app.widgets.is_valid(given) else None

    def _authorize(self, auth: str, ids: dict[str, str]) -> None:
        if auth == "none":
            return
        caller = self._caller()
        if caller is None:
            raise ApiError(401, "jeton manquant ou invalide")
        wanted = "hook" if auth in ("hook", "ticket") else "widget"
        if caller != wanted:
            raise ApiError(403, "ce jeton ne donne pas accès à cette route")
        if auth == "ticket":
            ticket = (self.headers.get(TICKET_HEADER) or "").strip()
            if not self.server.app.tickets.redeem(ids.get("id", ""), ticket):
                raise ApiError(403, "ticket d'attente manquant ou invalide")

    def _read_body(self, limit: int) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "Content-Length requis")
        raw_length = self.headers.get("Content-Length") or "0"
        if not raw_length.isdigit():
            raise ApiError(400, "Content-Length invalide")
        length = int(raw_length)
        if length > limit:
            self.close_connection = True
            raise ApiError(413, "requête trop volumineuse")
        if length == 0:
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(415, "Content-Type application/json requis")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "JSON invalide") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "le corps doit être un objet JSON")
        return data

    # ---- responses ---------------------------------------------------------------

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _common_headers(self, ctype: str) -> None:
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors_headers()

    def _send_html(self, status: int, page: str) -> None:
        """A fixed page for the browser (sign-in landing): nothing may load or run in it."""
        data = page.encode("utf-8")
        try:
            self.send_response(status)
            self._common_headers("text/html; charset=utf-8")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'",
            )
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            log.debug("omniscient: client went away before the page")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self._common_headers("application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            log.debug("omniscient: client went away before the response")

    def _stream(self) -> None:
        """Server-sent events until the client leaves or the daemon stops."""
        app = self.server.app
        if not app.presence.enter():
            self._send_json(503, {"error": "trop de flux ouverts"})
            return
        q = app.store.subscribe()
        try:
            self.send_response(200)
            self._common_headers("text/event-stream; charset=utf-8")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._write(": connecté\n\n")
            api_stream.pump_events(app, q, self._write)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            log.debug("omniscient: stream client went away")
        finally:
            app.store.unsubscribe(q)
            app.presence.leave()
            self.close_connection = True

    def _write(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8"))
        self.wfile.flush()


def _route_id(raw: str) -> str:
    value = unquote(raw)
    if not _ID.match(value) or set(value) <= {"."}:
        raise ApiError(400, "identifiant invalide")
    return value


# ---- entry points --------------------------------------------------------------------


def create_server(
    home: Home,
    port: int = DEFAULT_PORT,
    collectors: Sequence[Collector] = (),
    *,
    translate: Callable[[str, dict[str, Any]], Any] | None = None,
    actions: Any = None,
    heartbeat_s: float = HEARTBEAT_S,
    show_code: Callable[[str], bool] | None = None,
    allow_terminal_pairing: bool = False,
) -> GroupServer:
    """A bound (not yet serving) daemon; port 0 picks a free port."""
    secure_dir(home.state)
    from omniscient.group.auth import AuthService
    from omniscient.group.chat import ChatManager
    from omniscient.group.ext_store import ExtensionStore, extensions_root
    from omniscient.group.osd import OsdState
    from omniscient.group.providers import ProviderStore

    store = Store(db_path(home))
    providers = ProviderStore(home.state)
    app = App(
        home=home,
        hook_token=load_or_create_hook_token(home),
        store=store,
        widgets=WidgetTokens(db_path(home)),
        collectors=tuple(collectors),
        translate=translate,
        actions=actions,
        heartbeat_s=heartbeat_s,
        show_code=show_code or show_code_on_windows,
        allow_terminal_pairing=allow_terminal_pairing,
        osd=OsdState(state_dir=home.state),
        chat=ChatManager(home, store._publish, providers=providers),
        providers=providers,
        extensions=ExtensionStore(extensions_root(home.root), home.state),
        auth=AuthService(home.state, store._publish),
    )
    server = GroupServer(app, port)
    app.auth.set_port(
        server.port
    )  # the browser comes back to this daemon's own address
    return server


def serve(
    home: Home,
    port: int = DEFAULT_PORT,
    collectors: Sequence[Collector] | None = None,
    allow_terminal_pairing: bool = False,
) -> None:
    """Run the daemon in the foreground until Ctrl-C (`omniscient group serve`)."""
    chosen = (
        workers.default_collectors(home) if collectors is None else tuple(collectors)
    )
    server = create_server(
        home, port, chosen, allow_terminal_pairing=allow_terminal_pairing
    )
    server.start_background()
    print(
        f"omniscient écoute sur http://{BIND_HOST}:{server.port} (Ctrl-C pour arrêter)",
        flush=True,
    )
    try:
        install_stop_signals(server.app.stopping)
        # a timed wait: on Windows an untimed Event.wait() ignores Ctrl-C
        while not server.app.stopping.wait(SERVE_POLL_S):
            pass
    except KeyboardInterrupt:
        print("\nArrêt d'omniscient.")
    finally:
        server.close_all()
