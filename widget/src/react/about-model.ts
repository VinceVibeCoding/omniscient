// What the About screen shows, as plain data: the React component only draws it.
import type { LinkState, LinkStatus } from "../types.ts";

export interface AboutRow {
  readonly label: string;
  readonly value: string;
}

const LINK_LABEL: Readonly<Record<LinkState, string>> = {
  connecting: "Connexion…",
  connected: "Connecté",
  unpaired: "Non connecté",
  unauthorized: "Accès refusé",
  offline: "Hors ligne",
};

export function aboutRows(version: string, link: LinkStatus): readonly AboutRow[] {
  return [
    { label: "Version du widget", value: version || "inconnue" },
    { label: "Moteur local", value: link.message || LINK_LABEL[link.state] },
  ];
}
