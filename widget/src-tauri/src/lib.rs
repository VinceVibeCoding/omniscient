//! Omnigroup widget: Rust side (networking, SSE, tray, notifications, docking).

mod autostart;
mod client;
mod commands;
mod context_menu;
mod daemon_launch;
mod drag;
mod osd_commands;
mod osd_config;
mod pairing;
mod position;
mod proof;
mod scale;
mod settings;
mod sse;
mod state;
mod stream;
mod tray;
mod vault;
mod window;

use state::AppState;
use tauri::{Manager, RunEvent, WindowEvent};

fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let config_dir = app.path().app_config_dir()?;
    let loaded = settings::load(&config_dir).unwrap_or_else(|err| {
        eprintln!("omnigroup: {err} — default settings used");
        settings::Loaded { settings: settings::Settings::default(), legacy: false }
    });
    if loaded.legacy {
        // An older version kept a token in plain text: rewrite the file without it.
        if let Err(err) = settings::save(&config_dir, &loaded.settings) {
            eprintln!("omnigroup: legacy settings not rewritten: {err}");
        }
    }
    let token = vault::load().unwrap_or_else(|err| {
        eprintln!("omnigroup: {err}");
        None
    });
    let http = client::http_client()?;
    let placement = position::load(&config_dir);
    app.manage(AppState::new(http, config_dir, loaded.settings, token.unwrap_or_default(), placement));
    tray::build(app)?;
    let window = app.get_webview_window("main").ok_or("main window missing")?;
    scale::apply_to(&window)?; // zoom + size from window.json, docked on the anchor
    window.show()?;
    autostart::first_run(app.handle());
    daemon_launch::ensure_later(app.handle());
    stream::restart(app.handle());
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, None))
        .setup(setup)
        .on_window_event(|window, event| match event {
            // Only the OSD / panel window is dragged: the menu moves to the cursor itself.
            WindowEvent::Moved(pos) if window.label() == "main" => {
                if let Some(webview) = window.app_handle().get_webview_window("main") {
                    drag::on_moved(&webview, *pos);
                }
            }
            WindowEvent::Focused(false) if window.label() == context_menu::MENU_LABEL => {
                context_menu::close(window.app_handle());
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_sessions,
            commands::get_session,
            commands::get_usage,
            commands::get_theme,
            commands::answer_pending,
            commands::dismiss_session,
            commands::jump_session,
            commands::prompt_session,
            commands::get_settings,
            commands::link_status,
            commands::save_settings,
            commands::pair_start,
            commands::pair_finish,
            commands::unpair,
            commands::set_window_mode,
            drag::start_drag,
            osd_commands::get_osd,
            osd_commands::get_config,
            osd_commands::set_config,
            osd_commands::show_context_menu,
            osd_commands::menu_pick,
            osd_commands::menu_close,
            osd_commands::menu_fit,
            scale::get_scale,
            scale::set_scale,
            scale::resize_start,
            scale::resize_move,
            scale::resize_end,
            autostart::get_autostart,
            autostart::set_autostart,
            osd_commands::list_projects,
            osd_commands::chat_create,
            osd_commands::chat_send,
            osd_commands::chat_stop,
            osd_commands::chat_list,
            osd_commands::chat_get,
            osd_commands::session_transcript,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Omnigroup widget")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                daemon_launch::stop(app);
            }
        });
}
