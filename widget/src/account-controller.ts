// State and actions of the account screens (Réglages and the first-run assistant).
// Immutable model; `changed()` re-renders. The password lives only in its field until it
// is sent: the draft keeps the mode and the e-mail, never the password.
import * as api from "./api-auth";
import type { AuthProvider, AuthStatus } from "./types";

export interface AccountDraft {
  mode: "signin" | "signup";
  email: string;
}

export interface AccountModel {
  status: AuthStatus;
  draft: AccountDraft;
  busy: boolean;
  /** The last error, shown next to the form (the toast is easy to miss). */
  error: string;
}

export interface AccountHandlers {
  start(provider: AuthProvider): void;
  password(mode: AccountDraft["mode"], email: string, password: string): void;
  signout(): void;
  setDraft(patch: Partial<AccountDraft>): void;
  /** Switch between signing in and creating an account (redraws, keeps the e-mail). */
  setMode(mode: AccountDraft["mode"]): void;
}

export class AccountController {
  private state: AccountModel = { status: api.SIGNED_OUT, draft: { mode: "signin", email: "" }, busy: false, error: "" };
  readonly handlers: AccountHandlers;

  constructor(
    private readonly changed: () => void,
    private readonly fail: (err: unknown) => void,
  ) {
    this.handlers = {
      start: (provider) => void this.start(provider),
      password: (mode, email, password) => void this.password(mode, email, password),
      signout: () => void this.run(async () => this.set({ status: await api.authSignout() })),
      setDraft: (patch) => {
        this.state = { ...this.state, draft: { ...this.state.draft, ...patch } }; // no re-render while typing
      },
      setMode: (mode) => this.set({ draft: { ...this.state.draft, mode }, error: "" }),
    };
  }

  get view(): AccountModel {
    return this.state;
  }

  private set(patch: Partial<AccountModel>): void {
    this.state = { ...this.state, ...patch };
    this.changed();
  }

  private async run(work: () => Promise<void>): Promise<void> {
    this.set({ busy: true, error: "" });
    try {
      await work();
      this.set({ busy: false });
    } catch (err) {
      this.set({ busy: false, error: err instanceof Error ? err.message : String(err) });
      this.fail(err);
    }
  }

  async load(): Promise<void> {
    try {
      this.set({ status: await api.authStatus() });
    } catch (err) {
      this.fail(err);
    }
  }

  /** SSE `auth`: a browser sign-in finished, or the session changed. */
  onEvent(data: unknown): void {
    this.set({ status: api.toAuthStatus(data), error: "" });
  }

  private async start(provider: AuthProvider): Promise<void> {
    await this.run(async () => {
      await api.authStart(provider);
      this.set({ status: await api.authStatus() }); // `pending` now true: "finish in your browser"
    });
  }

  private async password(mode: AccountDraft["mode"], email: string, password: string): Promise<void> {
    await this.run(async () => this.set({ status: await api.authPassword(mode, email, password), draft: { mode, email } }));
  }
}
