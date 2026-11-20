// Glue between the hand-written DOM screens and the React ones. main.ts only calls these.
import type { LinkStatus } from "../types";

/** Id of the element a React screen is drawn into. */
export const REACT_HOST = "react-host";

/** Marks the button that opens the About screen, so focus can return to it. */
export const ABOUT_BUTTON = "data-about-button";

let unmount: (() => void) | null = null;

/** Removes the React screen currently shown, if any. Call before the DOM is rebuilt. */
export function clearReact(): void {
  unmount?.();
  unmount = null;
}

export interface AboutHostProps {
  readonly version: string;
  readonly link: LinkStatus;
  readonly onBack: () => void;
}

/** The React screens are a separate chunk, fetched only when one is opened. */
export async function showAbout(app: HTMLElement, props: AboutHostProps): Promise<void> {
  const host = app.querySelector<HTMLElement>(`#${REACT_HOST}`);
  if (!host) return;
  const { mountAbout } = await import("./mount");
  if (!host.isConnected) return; // another screen replaced this one while the chunk loaded
  unmount = mountAbout(host, props);
}
