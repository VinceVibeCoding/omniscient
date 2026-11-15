// Resizing the widget: drag the top-left grip, or Ctrl + mouse wheel anywhere. Rust does
// the measuring: it reads the OS cursor at the start and on every move (webview pointer
// coordinates change with the zoom), zooms the webview and resizes the window from its
// bottom-right anchor, so the grip stays under the pointer. Moves are coalesced: at most
// one call in flight.

const WHEEL_STEP = 0.05;

export interface ResizeApi {
  start(): Promise<void>;
  move(): Promise<number>;
  end(): Promise<void>;
  get(): Promise<number>;
  set(scale: number): Promise<number>;
}

export function installResize(grip: HTMLElement, api: ResizeApi, onError: (err: unknown) => void): void {
  let active = false;
  let busy = false;
  let again = false;

  const follow = (): void => {
    if (!active) return;
    if (busy) {
      again = true;
      return;
    }
    busy = true;
    api
      .move()
      .catch(onError)
      .finally(() => {
        busy = false;
        if (again) {
          again = false;
          follow();
        }
      });
  };

  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    grip.setPointerCapture(event.pointerId);
    grip.classList.add("grip--active");
    api.start().then(() => (active = true), onError);
  });

  grip.addEventListener("pointermove", (event) => {
    if ((event.buttons & 1) !== 0) follow();
  });

  const end = (event: PointerEvent): void => {
    if (!active && !grip.classList.contains("grip--active")) return;
    active = false;
    grip.classList.remove("grip--active");
    if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
    api.end().catch(onError);
  };
  grip.addEventListener("pointerup", end);
  grip.addEventListener("pointercancel", end);

  document.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const step = event.deltaY < 0 ? WHEEL_STEP : -WHEEL_STEP;
      api
        .get()
        .then((scale) => api.set(Math.round((scale + step) * 100) / 100))
        .catch(onError);
    },
    { passive: false },
  );
}
