//! Right-click menu of the OSD, drawn by the widget itself (Omniscient look, current
//! skin) in a second, borderless webview window labelled "menu" (menu.html):
//! « OSD View » Bars / Gauge, « Thème » Default / Terminal / Dashboard, « Taille »,
//! « Afficher le ticker », « Lancer au démarrage », « Replacer dans le coin », « Quitter ». Keys fixed in ~/.claude/settings.json
//! are shown locked. The menu opens at the cursor and closes on a pick, Escape or as soon
//! as it loses focus. A pick is sent to the daemon (PUT /config, which persists it) and
//! the new effective view is pushed to the OSD as a `config` group://event.

use crate::commands::daemon_for;
use crate::osd_config::{menu_size, parse_menu_id, validate_patch, MenuAction, MenuSnapshot, MENU_ID_MAX, MENU_PREFIX};
use crate::position::popup_origin;
use crate::state::{lock, AppState};
use crate::stream::STREAM_EVENT;
use crate::window::work_area;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, EventTarget, LogicalSize, Manager, PhysicalPosition, WebviewWindow};

pub const MENU_LABEL: &str = "menu";
/// Sent to the menu webview with the MenuSnapshot just before it is shown.
const OPEN_EVENT: &str = "menu://open";

/// PUT /config with a validated patch; caches and returns the new effective view.
pub async fn put_config(state: &AppState, patch: &Value) -> Result<Value, String> {
    let clean = validate_patch(patch)?;
    let daemon = daemon_for(state)?;
    let view = daemon.put(&["config"], &clean).await.map_err(|err| err.message())?;
    *lock(&state.config) = Some(view.clone());
    Ok(view)
}

fn snapshot(app: &AppHandle) -> MenuSnapshot {
    let state = app.state::<AppState>();
    let cached = lock(&state.config).clone();
    let scale = *lock(&state.scale);
    MenuSnapshot {
        scale_pct: (scale * 100.0).round() as u32,
        autostart: crate::autostart::is_enabled(app),
        ..MenuSnapshot::from_view(cached.as_ref())
    }
}

/// Refreshes the cached view when possible (the menu still opens with defaults if not).
async fn refresh(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Ok(daemon) = daemon_for(&state) else { return };
    match daemon.get(&["config"]).await {
        Ok(view) => *lock(&state.config) = Some(view),
        Err(err) => eprintln!("omnigroup: config not refreshed: {}", err.message()),
    }
}

fn menu_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window(MENU_LABEL).ok_or_else(|| "Menu introuvable.".to_string())
}

/// Sizes the menu and puts it at the cursor, flipped to stay on the cursor's monitor.
fn place_at_cursor(app: &AppHandle, menu: &WebviewWindow) -> Result<(), String> {
    let (width, height) = *lock(&app.state::<AppState>().menu_size);
    menu.set_size(LogicalSize::new(width, height))
        .map_err(|err| format!("Menu impossible à dimensionner : {err}"))?;
    let cursor = menu.cursor_position().map_err(|err| format!("Curseur introuvable : {err}"))?;
    let point = (cursor.x.round() as i32, cursor.y.round() as i32);
    let (area, scale) = work_area(menu, Some(point)).ok_or("Écran introuvable.")?;
    let size = ((width * scale).round() as i32, (height * scale).round() as i32);
    let (x, y) = popup_origin(area, size, point);
    menu.set_position(PhysicalPosition::new(x, y))
        .map_err(|err| format!("Menu impossible à placer : {err}"))
}

/// Opens the menu at the cursor with the current config.
pub async fn popup(app: AppHandle) -> Result<(), String> {
    refresh(&app).await;
    let menu = menu_window(&app)?;
    menu.emit_to(EventTarget::webview_window(MENU_LABEL), OPEN_EVENT, snapshot(&app))
        .map_err(|err| format!("Menu impossible à préparer : {err}"))?;
    place_at_cursor(&app, &menu)?;
    menu.show().map_err(|err| format!("Menu impossible à afficher : {err}"))?;
    if let Err(err) = menu.set_focus() {
        eprintln!("omnigroup: menu not focused: {err}");
    }
    Ok(())
}

/// Hides the menu (pick, Escape, focus lost).
pub fn close(app: &AppHandle) {
    let Some(menu) = app.get_webview_window(MENU_LABEL) else { return };
    if let Err(err) = menu.hide() {
        eprintln!("omnigroup: menu not hidden: {err}");
    }
}

/// The menu webview measured itself: remember its size (applied on the next opening).
pub fn fit(app: &AppHandle, width: f64, height: f64) -> Result<(), String> {
    let size = menu_size(width, height)?;
    *lock(&app.state::<AppState>().menu_size) = size;
    Ok(())
}

fn emit(app: &AppHandle, kind: &str, data: Value) {
    if let Err(err) = app.emit(STREAM_EVENT, json!({ "type": kind, "data": data })) {
        eprintln!("omnigroup: {kind} event not delivered: {err}");
    }
}

async fn apply(app: AppHandle, patch: Value) {
    let state = app.state::<AppState>();
    match put_config(&state, &patch).await {
        Ok(view) => emit(&app, "config", view),
        Err(message) => {
            eprintln!("omnigroup: config not saved: {message}");
            emit(&app, "menu_error", json!({ "message": message }));
        }
    }
}

/// A pick from the menu webview: closes the menu, then applies it. Unknown ids are refused.
pub fn pick(app: &AppHandle, id: &str) -> Result<(), String> {
    if id.len() > MENU_ID_MAX || !id.starts_with(MENU_PREFIX) {
        return Err("Choix de menu inconnu.".into());
    }
    let action = parse_menu_id(id, &snapshot(app)).ok_or("Choix de menu inconnu.")?;
    close(app);
    match action {
        MenuAction::Patch(patch) => {
            tauri::async_runtime::spawn(apply(app.clone(), patch));
        }
        MenuAction::Scale(pct) => {
            if let Err(err) = crate::scale::set(app, f64::from(pct) / 100.0) {
                emit(app, "menu_error", json!({ "message": err }));
            }
        }
        MenuAction::Autostart(enabled) => {
            if let Err(err) = crate::autostart::set(app, enabled) {
                emit(app, "menu_error", json!({ "message": err }));
            }
        }
        MenuAction::Corner => crate::drag::reset(app),
        MenuAction::Hide => crate::tray::hide_window(app),
        MenuAction::Quit => app.exit(0),
    }
    Ok(())
}
