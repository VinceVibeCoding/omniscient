// Mounts the React screens into a plain DOM element owned by the existing widget.
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";
import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { createRoot } from "react-dom/client";
import { AboutScreen, type AboutScreenProps } from "./AboutScreen";

/** Draws the About screen in `host`; returns the function that removes it. */
export function mountAbout(host: HTMLElement, props: AboutScreenProps): () => void {
  const root = createRoot(host);
  root.render(
    <Theme theme={neutralTheme} mode="system">
      <AboutScreen {...props} />
    </Theme>,
  );
  return () => root.unmount();
}
