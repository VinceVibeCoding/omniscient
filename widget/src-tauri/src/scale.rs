//! Widget size: one factor for the OSD and the panel (resize grip, Ctrl + wheel, menu
//! « Taille »). The window is resized from its bottom-right anchor and the webview is
//! zoomed by the same factor, so every layout keeps its proportions. Saved in window.json.
//! The grip drag is measured here with the OS cursor (physical pixels): webview pointer
//! coordinates change units with the zoom, which made the size run away.

use crate::drag::schedule_save;
use crate::state::{lock, AppState};
use crate::window::set_mode;
use tauri::{AppHandle, Manager, Runtime, WebviewWindow};

/// Grip drag start: cursor (physical px), window size (physical px), factor.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Drag {
    pub cursor: (f64, f64),
    pub size: (f64, f64),
    pub scale: f64,
}

/// New factor after the cursor moved from `start.cursor` to `now`: moving up-left grows the
/// widget (it is anchored bottom-right); the larger of the two proportional changes wins.
pub fn dragged_scale(start: Drag, now: (f64, f64)) -> f64 {
    let (w, h) = (start.size.0.max(1.0), start.size.1.max(1.0));
    let grow_x = (w + start.cursor.0 - now.0) / w;
    let grow_y = (h + start.cursor.1 - now.1) / h;
    start.scale * grow_x.max(grow_y)
}

pub const MIN: f64 = 0.75;
pub const MAX: f64 = 1.6;
pub const DEFAULT: f64 = 1.0;
/// Menu presets, in percent.
pub const PRESETS: [u32; 4] = [85, 100, 125, 150];

/// A finite factor, clamped to MIN..=MAX and rounded to 1 %.
pub fn clamp(raw: f64) -> Result<f64, String> {
    if !raw.is_finite() {
        return Err("Taille invalide.".into());
    }
    Ok((raw.clamp(MIN, MAX) * 100.0).round() / 100.0)
}

/// Startup value from window.json (invalid or missing → DEFAULT).
pub fn initial(saved: Option<f64>) -> f64 {
    saved.and_then(|s| clamp(s).ok()).unwrap_or(DEFAULT)
}

/// Zooms the webview and resizes the window for the current mode.
pub fn apply_to<R: Runtime>(window: &WebviewWindow<R>) -> Result<(), String> {
    let state = window.state::<AppState>();
    let (scale, mode) = (*lock(&state.scale), *lock(&state.mode));
    window.set_zoom(scale).map_err(|err| format!("Zoom impossible : {err}"))?;
    set_mode(window, mode)
}

/// Sets the size factor, applies it and saves it (debounced). Returns the clamped value.
pub fn set<R: Runtime>(app: &AppHandle<R>, raw: f64) -> Result<f64, String> {
    let scale = clamp(raw)?;
    let state = app.state::<AppState>();
    let changed = {
        let mut current = lock(&state.scale);
        let changed = (*current - scale).abs() > f64::EPSILON;
        *current = scale;
        changed
    };
    if changed {
        let window = app.get_webview_window("main").ok_or("Fenêtre introuvable.")?;
        apply_to(&window)?;
        schedule_save(app);
    }
    Ok(scale)
}

#[tauri::command]
pub fn resize_start(app: AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("main").ok_or("Fenêtre introuvable.")?;
    let cursor = window.cursor_position().map_err(|err| format!("Curseur introuvable : {err}"))?;
    let size = window.outer_size().map_err(|err| format!("Taille inconnue : {err}"))?;
    let state = app.state::<AppState>();
    let scale = *lock(&state.scale);
    let drag = Drag { cursor: (cursor.x, cursor.y), size: (f64::from(size.width), f64::from(size.height)), scale };
    *lock(&state.resize) = Some(drag);
    Ok(())
}

/// Follows the cursor while the grip is held; returns the factor now applied.
#[tauri::command]
pub fn resize_move(app: AppHandle) -> Result<f64, String> {
    let state = app.state::<AppState>();
    let drag = *lock(&state.resize);
    let Some(drag) = drag else { return Ok(*lock(&state.scale)) };
    let window = app.get_webview_window("main").ok_or("Fenêtre introuvable.")?;
    let cursor = window.cursor_position().map_err(|err| format!("Curseur introuvable : {err}"))?;
    set(&app, dragged_scale(drag, (cursor.x, cursor.y)))
}

#[tauri::command]
pub fn resize_end(app: AppHandle) {
    *lock(&app.state::<AppState>().resize) = None;
}

#[tauri::command]
pub fn get_scale(app: AppHandle) -> f64 {
    let state = app.state::<AppState>();
    let scale = *lock(&state.scale);
    scale
}

#[tauri::command]
pub fn set_scale(app: AppHandle, scale: f64) -> Result<f64, String> {
    set(&app, scale)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn factors_are_clamped_and_rounded() {
        assert_eq!(clamp(1.234).unwrap(), 1.23);
        assert_eq!(clamp(0.1).unwrap(), MIN);
        assert_eq!(clamp(9.0).unwrap(), MAX);
        assert!(clamp(f64::NAN).is_err());
        assert!(clamp(f64::INFINITY).is_err());
    }

    #[test]
    fn startup_value_falls_back_to_default() {
        assert_eq!(initial(None), DEFAULT);
        assert_eq!(initial(Some(f64::NAN)), DEFAULT);
        assert_eq!(initial(Some(1.25)), 1.25);
        assert_eq!(initial(Some(5.0)), MAX);
    }

    #[test]
    fn dragging_up_left_grows_down_right_shrinks() {
        let start = Drag { cursor: (1000.0, 600.0), size: (300.0, 150.0), scale: 1.0 };
        assert_eq!(dragged_scale(start, (1000.0, 600.0)), 1.0);
        assert_eq!(dragged_scale(start, (700.0, 600.0)), 2.0); // 300 px left: twice as wide
        assert_eq!(dragged_scale(start, (1000.0, 450.0)), 2.0); // 150 px up: twice as tall
        assert_eq!(dragged_scale(start, (1150.0, 675.0)), 0.5);
        let zero = Drag { size: (0.0, 0.0), ..start };
        assert!(dragged_scale(zero, (990.0, 600.0)).is_finite());
    }

    #[test]
    fn presets_are_in_range() {
        for pct in PRESETS {
            let factor = f64::from(pct) / 100.0;
            assert_eq!(clamp(factor).unwrap(), factor);
        }
    }
}
