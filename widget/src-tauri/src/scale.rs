//! Widget size: one factor for the OSD and the panel (resize grip, Ctrl + wheel, menu
//! « Taille »). The window is resized from its bottom-right anchor and the webview is
//! zoomed by the same factor, so every layout keeps its proportions. Saved in window.json.

use crate::drag::schedule_save;
use crate::state::{lock, AppState};
use crate::window::set_mode;
use tauri::{AppHandle, Manager, Runtime, WebviewWindow};

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
    fn presets_are_in_range() {
        for pct in PRESETS {
            let factor = f64::from(pct) / 100.0;
            assert_eq!(clamp(factor).unwrap(), factor);
        }
    }
}
