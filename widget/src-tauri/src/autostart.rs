//! Launch at Windows login (tauri-plugin-autostart: a per-user Run registry entry). It is
//! switched on once, on the first run, so the widget is "always there"; after that only
//! the owner changes it (menu « Lancer au démarrage » or Réglages).

use crate::settings;
use crate::state::{lock, AppState};
use tauri::{AppHandle, Manager};
use tauri_plugin_autostart::ManagerExt;

pub fn is_enabled(app: &AppHandle) -> bool {
    app.autolaunch().is_enabled().unwrap_or_else(|err| {
        eprintln!("omniscient: autostart state unreadable: {err}");
        false
    })
}

pub fn set(app: &AppHandle, enabled: bool) -> Result<bool, String> {
    let manager = app.autolaunch();
    let result = if enabled { manager.enable() } else { manager.disable() };
    result.map_err(|err| format!("Lancement au démarrage impossible à changer : {err}"))?;
    Ok(is_enabled(app))
}

/// First run: switch autostart on and remember it was done (never forced again).
pub fn first_run(app: &AppHandle) {
    let state = app.state::<AppState>();
    let current = lock(&state.settings).clone();
    if current.autostart_init {
        return;
    }
    if let Err(err) = set(app, true) {
        eprintln!("omniscient: {err}");
        return;
    }
    let next = settings::Settings { autostart_init: true, ..current };
    match settings::save(&state.config_dir, &next) {
        Ok(()) => *lock(&state.settings) = next,
        Err(err) => eprintln!("omniscient: {err}"),
    }
}

#[tauri::command]
pub fn get_autostart(app: AppHandle) -> bool {
    is_enabled(&app)
}

#[tauri::command]
pub fn set_autostart(app: AppHandle, enabled: bool) -> Result<bool, String> {
    set(&app, enabled)
}
