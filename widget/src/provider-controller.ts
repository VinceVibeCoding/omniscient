// State and actions of the AI-provider screens (Réglages and the first-run assistant).
// Immutable model; calls `changed()` so main.ts re-renders. The API key lives only in the
// form field until it is sent; nothing here keeps it.
import * as api from "./api-providers";
import type { ProviderList } from "./types";

/** What the add form shows: survives re-renders. The API key is deliberately not here. */
export interface AddDraft {
  kind: NewProvider["kind"];
  label: string;
  base_url: string;
  model: string;
}

export interface ProviderModel {
  list: ProviderList;
  draft: AddDraft;
  /** Models the last test found, by provider id. */
  models: Readonly<Record<string, readonly string[]>>;
  busy: boolean;
  notice: string;
}

export interface NewProvider {
  kind: Exclude<api.ProviderPatch["kind"], undefined>;
  label: string;
  base_url: string;
  /** Prefilled by an extension's preset; empty to let the person choose after the test. */
  model: string;
  api_key: string;
}

export interface ProviderHandlers {
  add(form: NewProvider): void;
  test(id: string): void;
  remove(id: string): void;
  makeDefault(id: string): void;
  chooseModel(id: string, model: string): void;
  setDraft(patch: Partial<AddDraft>): void;
}

const EMPTY: ProviderList = { providers: [], default: "claude-code" };

/** An id not used yet: the kind, then kind-2, kind-3… (ids are 1–32 of a-z 0-9 -). */
export function freshId(kind: string, taken: readonly string[]): string {
  if (!taken.includes(kind)) return kind;
  for (let n = 2; n < 100; n += 1) if (!taken.includes(`${kind}-${n}`)) return `${kind}-${n}`;
  return `${kind}-${Date.now().toString(36)}`.slice(0, 32);
}

export class ProviderController {
  private state: ProviderModel = {
    list: EMPTY,
    draft: { kind: "gemini", label: "", base_url: "", model: "" },
    models: {},
    busy: false,
    notice: "",
  };
  readonly handlers: ProviderHandlers;

  constructor(
    private readonly changed: () => void,
    private readonly fail: (err: unknown) => void,
  ) {
    this.handlers = {
      add: (form) => void this.add(form),
      test: (id) => void this.test(id),
      remove: (id) => void this.run(async () => this.set({ list: await api.removeProvider(id) })),
      makeDefault: (id) => void this.makeDefault(id),
      chooseModel: (id, model) => void this.run(async () => this.set({ list: await api.saveProvider(id, { model }) })),
      setDraft: (patch) => {
        this.state = { ...this.state, draft: { ...this.state.draft, ...patch } }; // no re-render while typing
      },
    };
  }

  get view(): ProviderModel {
    return this.state;
  }

  private set(patch: Partial<ProviderModel>): void {
    this.state = { ...this.state, ...patch };
    this.changed();
  }

  private async run(work: () => Promise<void>): Promise<void> {
    try {
      await work();
    } catch (err) {
      this.set({ busy: false });
      this.fail(err);
    }
  }

  async load(): Promise<void> {
    await this.run(async () => this.set({ list: await api.listProviders() }));
  }

  private async makeDefault(id: string): Promise<void> {
    if (id === "claude-code") {
      // Claude Code is the built-in fallback: forgetting any other default restores it.
      const other = this.state.list.providers.find((p) => !p.builtin && this.state.list.default === p.id);
      if (!other) return;
    }
    await this.run(async () => this.set({ list: await api.saveProvider(id, { default: true }) }));
  }

  private async add(form: NewProvider): Promise<void> {
    const taken = this.state.list.providers.map((p) => p.id);
    const id = freshId(form.kind, taken);
    const patch: api.ProviderPatch = { kind: form.kind, api_key: form.api_key };
    if (form.label) patch.label = form.label;
    if (form.model) patch.model = form.model;
    if (form.kind === "openai-compatible") patch.base_url = form.base_url;
    if (form.kind === "openai-compatible" && !form.api_key) delete patch.api_key; // local models need none
    this.set({ busy: true, notice: "" });
    await this.run(async () => {
      this.set({ list: await api.saveProvider(id, patch), draft: { kind: form.kind, label: "", base_url: "", model: "" } });
      await this.test(id);
    });
    this.set({ busy: false });
  }

  async test(id: string): Promise<void> {
    this.set({ busy: true });
    try {
      const result = await api.testProvider(id);
      const models = result.models.length > 0 ? { ...this.state.models, [id]: result.models } : this.state.models;
      this.set({ models, busy: false, notice: result.ok ? "Connexion réussie." : "Connexion impossible." });
    } catch (err) {
      this.set({ busy: false, notice: "" });
      this.fail(err);
    }
  }
}
