//! « Montrer »: a click-through frame drawn on the screen around an element of the page.
//!
//! One small transparent window (`highlight.html`), always on top, that never takes the
//! focus or the mouse. It only draws a rectangle for a few seconds: the widget never clicks
//! or types in the page.

use crate::page_logic::Rect;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize};

const LABEL: &str = "highlight";
/// The frame is drawn this many physical pixels outside the element.
const PAD_PX: i32 = 6;
const MIN_PX: i32 = 24;
const SHOWN_FOR: Duration = Duration::from_secs(4);

static SEQ: AtomicU64 = AtomicU64::new(0);

/// Makes the window click-through and focus-less (call once at start-up).
pub fn prepare(app: &AppHandle) {
    let Some(window) = app.get_webview_window(LABEL) else { return };
    if let Err(err) = window.set_ignore_cursor_events(true) {
        eprintln!("omniscient: highlight window not click-through: {err}");
    }
    if let Err(err) = window.set_focusable(false) {
        eprintln!("omniscient: highlight window still focusable: {err}");
    }
}

/// Draws the frame around `rect` (screen pixels) and hides it again after a few seconds.
pub fn show(app: &AppHandle, rect: Rect) -> Result<(), String> {
    let window = app.get_webview_window(LABEL).ok_or("Fenêtre de surlignage absente.")?;
    let width = (rect.right - rect.left + 2 * PAD_PX).max(MIN_PX);
    let height = (rect.bottom - rect.top + 2 * PAD_PX).max(MIN_PX);
    let shown = window
        .set_size(PhysicalSize::new(width as u32, height as u32))
        .and_then(|()| window.set_position(PhysicalPosition::new(rect.left - PAD_PX, rect.top - PAD_PX)))
        .and_then(|()| window.show());
    shown.map_err(|err| format!("Surlignage impossible : {err}"))?;
    let mine = SEQ.fetch_add(1, Ordering::SeqCst) + 1;
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(SHOWN_FOR).await;
        if SEQ.load(Ordering::SeqCst) == mine {
            let _ = window.hide(); // a later « Montrer » keeps its own frame
        }
    });
    Ok(())
}
