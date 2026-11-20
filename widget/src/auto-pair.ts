// When the widget is not paired (or the daemon does not recognize it), it asks for the pairing
// code by itself, once per launch. The code is still typed by the user: nothing is bypassed.
import type { LinkStatus } from "./types";

export const PAIR_PROMPT = "Tape le code à 6 chiffres affiché sur ton bureau.";

const NOT_RECOGNIZED = /ne reconna[iî]t pas le widget/i;

/** True when the link says "pair me" and no code was requested yet during this launch. */
export function needsPairingCode(link: LinkStatus, alreadyRequested: boolean): boolean {
  if (alreadyRequested) return false;
  if (link.state === "unpaired") return true;
  return link.state === "unauthorized" && NOT_RECOGNIZED.test(link.message);
}
