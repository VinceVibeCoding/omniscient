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
    let mut builder = TrayIconBuilder::with_id("omniscient")
        .tooltip("Omniscient")
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

/// Shows the widget (docked where it belongs), also when it was minimized to the taskbar. This
/// is what a second launch of the app and a click on the tray icon ask for.
pub fn show_window(app: &AppHandle) {
    let Some(state) = app.try_state::<AppState>() else { return }; // still starting: it shows itself
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("omniscient: main window missing");
        return;
    };
    let mode = *lock(&state.mode);
    if window.is_minimized().unwrap_or(false) {
        if let Err(err) = window.unminimize() {
            eprintln!("omniscient: unminimize failed: {err}");
        }
    }
    let shown = dock(&window, mode).and_then(|()| window.show().map_err(|err| err.to_string()));
    if let Err(err) = shown {
        eprintln!("omniscient: show failed: {err}");
    }
}

/// Gets the widget off the screen but keeps its taskbar button, so one click brings it back
/// (the Windows-wide habit: a minimized app stays in the taskbar).
pub fn hide_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("omniscient: main window missing");
        return;
    };
    if let Err(err) = window.minimize() {
        eprintln!("omniscient: minimize failed: {err}");
    }
}

fn toggle_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("omniscient: main window missing");
        return;
    };
    let showing = window.is_visible().unwrap_or(false) && !window.is_minimized().unwrap_or(false);
    if showing {
        hide_window(app);
    } else {
        show_window(app);
    }
}
