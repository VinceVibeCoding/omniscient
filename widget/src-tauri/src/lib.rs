//! Omnigroup widget: Rust side (networking, SSE, tray, notifications, docking).

mod auth_commands;
mod autostart;
mod client;
mod commands;
mod context_menu;
mod daemon_launch;
mod drag;
mod ext_commands;
mod highlight;
mod osd_commands;
mod osd_config;
mod page_logic;
mod page_reader;
mod page_watch;
mod pairing;
mod position;
mod proof;
mod provider_commands;
mod scale;
mod settings;
mod single_instance;
mod sse;
mod state;
mod stream;
mod tray;
mod vault;
mod window;
mod window_shot;

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
    page_watch::init(&config_dir);
    app.manage(AppState::new(http, config_dir, loaded.settings, token.unwrap_or_default(), placement));
    tray::build(app)?;
    page_watch::start(app.handle().clone());
    highlight::prepare(app.handle());
    let window = app.get_webview_window("main").ok_or("main window missing")?;
    scale::apply_to(&window)?; // zoom + size from window.json, docked on the anchor
    window.show()?;
    autostart::first_run(app.handle());
    daemon_launch::ensure_later(app.handle());
    stream::restart(app.handle());
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
/// The running app, set once `setup` starts: what a second launch asks to show.
static APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

pub fn run() {
    // A second launch (pinned taskbar icon, Start menu) shows the running widget and quits.
    let listener = match single_instance::claim() {
        single_instance::Role::Secondary => return,
        single_instance::Role::Primary(listener) => listener,
    };
    // Answer second launches from the very first moment: the port is already ours, and the
    // interface takes a second or two to come up. A second launch that got no answer in that
    // window used to think a stranger held the port and started anyway: two widgets at once.
    // The window is only shown when the app is ready (`APP` is filled in `setup`).
    if let Some(listener) = listener {
        single_instance::serve(listener, || {
            if let Some(app) = APP.get() {
                tray::show_window(app);
            }
        });
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, None))
        .setup(|app| {
            let _ = APP.set(app.handle().clone());
            setup(app)
        })
        .on_window_event(|window, event| match event {
            // Only the OSD / panel window is dragged: the menu moves to the cursor itself.
            WindowEvent::Moved(pos) if window.label() == "main" => {
                if let Some(webview) = window.app_handle().get_webview_window("main") {
                    drag::on_moved(&webview, *pos);
                }
            }
            // A close from the taskbar button (right-click › Close window) quits the app, like any
            // other app: the widget has no close button of its own.
            WindowEvent::CloseRequested { api, .. } if window.label() == "main" => {
                api.prevent_close();
                window.app_handle().exit(0);
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
            commands::finish_wizard,
            commands::pair_start,
            commands::pair_finish,
            commands::unpair,
            commands::set_window_mode,
            drag::start_drag,
            osd_commands::minimize_window,
            osd_commands::quit_app,
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
            osd_commands::chat_fork,
            osd_commands::browser_page,
            osd_commands::page_tracking,
            osd_commands::show_element,
            osd_commands::set_page_tracking,
            auth_commands::auth_status,
            auth_commands::auth_start,
            auth_commands::auth_password,
            auth_commands::auth_signout,
            provider_commands::providers_list,
            provider_commands::provider_save,
            provider_commands::provider_remove,
            provider_commands::provider_test,
            osd_commands::chat_send,
            osd_commands::chat_stop,
            osd_commands::chat_list,
            osd_commands::chat_get,
            osd_commands::session_transcript,
            ext_commands::ext_list,
            ext_commands::ext_reload,
            ext_commands::ext_set_enabled,
            ext_commands::ext_remove,
            ext_commands::ext_expand,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Omnigroup widget")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                daemon_launch::stop(app);
            }
        });
}
