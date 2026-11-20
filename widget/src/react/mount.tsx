// Mounts the React screens into a plain DOM element owned by the existing widget.
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";
import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { AboutScreen, type AboutScreenProps } from "./AboutScreen";

/** Draws the About screen in `host`; returns the function that removes it. */
export function mountAbout(host: HTMLElement, props: AboutScreenProps): () => void {
  const root = createRoot(host);
  flushSync(() =>
    root.render(
      <Theme theme={neutralTheme} mode="system">
        <AboutScreen {...props} />
      </Theme>,
    ),
  );
  // The screen replaces the one the user was on: move the keyboard focus onto it.
  const title = host.querySelector("h1");
  title?.setAttribute("tabindex", "-1");
  title?.focus();
  return () => root.unmount();
}
