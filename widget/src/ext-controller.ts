// State and actions of the extensions (Réglages › Extensions, slash commands, themes,
// provider presets). Immutable model; calls `changed()` so main.ts re-renders.
import * as api from "./api-ext";
import { EMPTY_EXTENSIONS, type ExtensionsView } from "./api-ext";
import { applyChoice, currentChoice, resetTheme, syncTheme, type ThemeChoice } from "./ext-theme";

export interface ExtModel {
  view: ExtensionsView;
  /** The extension whose « Retirer » waits for its confirmation. */
  confirming: string | null;
  /** The theme currently applied (extension id + theme id). */
  theme: ThemeChoice | null;
  busy: boolean;
}

export interface ExtHandlers {
  refresh(): void;
  reload(): void;
  setEnabled(id: string, enabled: boolean): void;
  askRemove(id: string | null): void;
  remove(id: string): void;
  applyTheme(choice: ThemeChoice): void;
  resetTheme(): void;
}

export class ExtController {
  private state: ExtModel = { view: EMPTY_EXTENSIONS, confirming: null, theme: null, busy: false };
  readonly handlers: ExtHandlers;

  constructor(
    private readonly changed: () => void,
    private readonly fail: (err: unknown) => void,
    private readonly toast: (message: string) => void,
  ) {
    this.handlers = {
      refresh: () => void this.load(),
      reload: () => void this.reload(),
      setEnabled: (id, enabled) => void this.run(() => api.setExtensionEnabled(id, enabled)),
      askRemove: (confirming) => this.set({ confirming }),
      remove: (id) => void this.run(() => api.removeExtension(id)),
      applyTheme: (choice) => this.pickTheme(choice),
      resetTheme: () => {
        resetTheme();
        this.set({ theme: null });
      },
    };
  }

  get view(): ExtModel {
    return this.state;
  }

  private set(patch: Partial<ExtModel>): void {
    this.state = { ...this.state, ...patch };
    this.changed();
  }

  /** A fresh list from the daemon (also the SSE `extensions` payload): themes follow it. */
  private accept(view: ExtensionsView): ExtensionsView {
    syncTheme(view);
    this.set({ view, confirming: null, theme: currentChoice() });
    return view;
  }

  /** Raw SSE `extensions` payload. */
  onEvent(raw: unknown): void {
    this.accept(api.toExtensionsView(raw));
  }

  async load(): Promise<void> {
    await this.run(api.listExtensions);
  }

  /** POST /extensions/reload; null when it failed (the error is already shown). */
  async reload(): Promise<ExtensionsView | null> {
    return this.run(api.reloadExtensions);
  }

  private async run(work: () => Promise<ExtensionsView>): Promise<ExtensionsView | null> {
    this.set({ busy: true });
    try {
      const view = this.accept(await work());
      this.set({ busy: false });
      return view;
    } catch (err) {
      this.set({ busy: false });
      this.fail(err);
      return null;
    }
  }

  private pickTheme(choice: ThemeChoice): void {
    if (!applyChoice(this.state.view, choice)) {
      this.toast("Ce thème n'a aucune couleur valide à appliquer.");
      return;
    }
    this.set({ theme: currentChoice() });
  }
}
