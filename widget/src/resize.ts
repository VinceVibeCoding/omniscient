// Resizing the widget: drag the top-left grip, or Ctrl + mouse wheel anywhere. Both set
// one size factor through Rust (`set_scale`), which zooms the webview and resizes the
// window from its bottom-right anchor, so the grip stays under the pointer.
// Positions are in physical pixels (screen CSS px × devicePixelRatio, which includes the
// zoom), so they stay comparable while the zoom changes under the drag.

const WHEEL_STEP = 0.05;

export interface ScaleApi {
  get(): Promise<number>;
  set(scale: number): Promise<number>;
}

interface Start {
  x: number;
  y: number;
  width: number;
  height: number;
  scale: number;
}

function physical(event: PointerEvent): { x: number; y: number } {
  const ratio = window.devicePixelRatio || 1;
  return { x: event.screenX * ratio, y: event.screenY * ratio };
}

export function installResize(grip: HTMLElement, api: ScaleApi, onError: (err: unknown) => void): void {
  let start: Start | null = null;
  let pending: number | null = null;
  let busy = false;

  const flush = (): void => {
    if (busy || pending === null) return;
    const next = pending;
    pending = null;
    busy = true;
    api
      .set(next)
      .catch(onError)
      .finally(() => {
        busy = false;
        flush();
      });
  };

  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    grip.setPointerCapture(event.pointerId);
    grip.classList.add("grip--active");
    const ratio = window.devicePixelRatio || 1;
    const at = physical(event);
    void api.get().then(
      (scale) => (start = { ...at, width: window.innerWidth * ratio, height: window.innerHeight * ratio, scale }),
      onError,
    );
  });

  grip.addEventListener("pointermove", (event) => {
    if (!start || (event.buttons & 1) === 0) return;
    const at = physical(event);
    // Moving up-left grows the widget: use the larger of the two proportional changes.
    const grow = Math.max((start.width + start.x - at.x) / start.width, (start.height + start.y - at.y) / start.height);
    pending = Math.round(start.scale * grow * 100) / 100;
    flush();
  });

  const end = (event: PointerEvent): void => {
    start = null;
    grip.classList.remove("grip--active");
    if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
  };
  grip.addEventListener("pointerup", end);
  grip.addEventListener("pointercancel", end);

  document.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const step = event.deltaY < 0 ? WHEEL_STEP : -WHEEL_STEP;
      void api.get().then((scale) => {
        pending = Math.round((scale + step) * 100) / 100;
        flush();
      }, onError);
    },
    { passive: false },
  );
}
