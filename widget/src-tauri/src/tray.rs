//! Tray icon: left click toggles the widget (a second launch of the app shows it); menu « Afficher / masquer »,
//! « Replacer dans le coin » (forget where it was dragged) and « Quitter ».

use crate::state::{lock, AppState};
use crate::window::dock;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{App, AppHandle, Manager};

const TOGGLE_ID: &str = "toggle";
const CORNER_ID: &str = "corner";
const QUIT_ID: &str = "quit";

pub fn build(app: &App) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, TOGGLE_ID, "Afficher / masquer", true, None::<&str>)?;
    let corner = MenuItem::with_id(app, CORNER_ID, "Replacer dans le coin", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT_ID, "Quitter", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle, &corner, &quit])?;
    let mut builder = TrayIconBuilder::with_id("omnigroup")
        .tooltip("Omnigroup")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            TOGGLE_ID => toggle_window(app),
            CORNER_ID => crate::drag::reset(app),
            QUIT_ID => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Shows the widget (docked where it belongs). Also what a second launch asks for.
pub fn show_window(app: &AppHandle) {
    let Some(state) = app.try_state::<AppState>() else { return }; // still starting: it shows itself
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("omnigroup: main window missing");
        return;
    };
    let mode = *lock(&state.mode);
    let shown = dock(&window, mode).and_then(|()| window.show().map_err(|err| err.to_string()));
    if let Err(err) = shown {
        eprintln!("omnigroup: show failed: {err}");
    }
}

fn toggle_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("omnigroup: main window missing");
        return;
    };
    if !window.is_visible().unwrap_or(false) {
        show_window(app);
    } else if let Err(err) = window.hide() {
        eprintln!("omnigroup: tray toggle failed: {err}");
    }
}
