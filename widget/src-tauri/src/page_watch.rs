//! Which browser window the person was last in, and reading its page on request.
//!
//! Once the widget has the keyboard focus (to type a question) it is the foreground
//! window, so the browser has to be remembered *before*. A small thread watches the
//! foreground window every few hundred ms: only Chromium browsers are remembered, only
//! their window title is kept, in memory. The page itself (text, links, address) is read
//! once, when a question is sent with « Joindre la page du navigateur » ticked.

use crate::page_logic::{browser_label, build_outline, clean_title, normalize_url};
use crate::page_reader::{self, Snapshot};
use crate::state::lock;
use crate::stream::STREAM_EVENT;
use serde_json::{json, Value};
use std::fs;
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use windows::core::PWSTR;
use windows::Win32::Foundation::{CloseHandle, HWND};
use windows::Win32::System::Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION};
use windows::Win32::UI::WindowsAndMessaging::{GetAncestor, GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId, IsWindow, GA_ROOTOWNER};

const POLL: Duration = Duration::from_millis(400);
const READ_TIMEOUT: Duration = Duration::from_secs(6);
const PATH_MAX: usize = 1024;
const TITLE_MAX: usize = 512;
/// A file in the app config folder: present = the person switched page tracking off.
const OFF_MARKER: &str = "page-tracking-off";

static TRACKING: AtomicBool = AtomicBool::new(true);

fn marker_says_off(dir: &Path) -> bool {
    dir.join(OFF_MARKER).exists()
}

fn write_marker(dir: &Path, tracking: bool) -> io::Result<()> {
    let marker = dir.join(OFF_MARKER);
    if tracking {
        match fs::remove_file(&marker) {
            Err(err) if err.kind() != io::ErrorKind::NotFound => Err(err),
            _ => Ok(()),
        }
    } else {
        fs::create_dir_all(dir)?;
        fs::write(&marker, b"")
    }
}

/// Reads the saved choice (call once at start-up, before `start`).
pub fn init(config_dir: &Path) {
    TRACKING.store(!marker_says_off(config_dir), Ordering::SeqCst);
}

/// False when the person switched page tracking off: nothing is remembered or read.
pub fn tracking() -> bool {
    TRACKING.load(Ordering::SeqCst)
}

/// The button: switches tracking on or off, and remembers the choice across restarts.
/// Off forgets the remembered window at once.
pub fn set_tracking(app: &AppHandle, config_dir: &Path, on: bool) -> Result<(), String> {
    write_marker(config_dir, on).map_err(|err| format!("Réglage non enregistré : {err}"))?;
    TRACKING.store(on, Ordering::SeqCst);
    if !on {
        *lock(slot()) = None;
        announce(app, None);
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Remembered {
    hwnd: isize,
    browser: &'static str,
    title: String,
}

fn slot() -> &'static Mutex<Option<Remembered>> {
    static SLOT: OnceLock<Mutex<Option<Remembered>>> = OnceLock::new();
    SLOT.get_or_init(|| Mutex::new(None))
}

/// What the Chat tab shows: the remembered browser window (title only), or not available.
fn view(remembered: Option<&Remembered>) -> Value {
    match remembered {
        Some(r) => json!({ "available": true, "url": "", "origin": r.browser, "title": r.title }),
        None => json!({ "available": false }),
    }
}

pub fn current() -> Value {
    let remembered = lock(slot()).clone();
    view(remembered.as_ref())
}

fn announce(app: &AppHandle, remembered: Option<&Remembered>) {
    let event = json!({ "type": "browser_page", "data": view(remembered) });
    if let Err(err) = app.emit(STREAM_EVENT, event) {
        eprintln!("omnigroup: browser window event failed: {err}");
    }
}

/// Starts the watcher thread (it lives as long as the app).
pub fn start(app: AppHandle) {
    std::thread::spawn(move || loop {
        if tracking() {
            // SAFETY: GetForegroundWindow has no preconditions.
            let foreground = unsafe { GetForegroundWindow() };
            if !foreground.0.is_null() {
                observe(&app, foreground);
            }
            forget_if_closed(&app);
        }
        std::thread::sleep(POLL);
    });
}

fn observe(app: &AppHandle, foreground: HWND) {
    // A bubble, a dialog or a pop-up of the browser belongs to its main window: remember that one.
    // SAFETY: GetAncestor accepts any window handle.
    let owner = unsafe { GetAncestor(foreground, GA_ROOTOWNER) };
    let window = if owner.0.is_null() { foreground } else { owner };
    let mut pid = 0u32;
    // SAFETY: `window` is a handle just returned by the system; `pid` outlives the call.
    unsafe { GetWindowThreadProcessId(window, Some(&mut pid)) };
    if pid == 0 || pid == std::process::id() {
        return; // not a window we can know, or our own widget
    }
    let hwnd = window.0 as isize;
    let known = lock(slot()).clone();
    let browser = match known.as_ref().filter(|r| r.hwnd == hwnd) {
        Some(r) => r.browser,
        None => match exe_name(pid).as_deref().and_then(browser_label) {
            Some(label) => label,
            None => return, // another app: keep what we remembered
        },
    };
    let next = Remembered { hwnd, browser, title: clean_title(&window_title(window)) };
    if known.as_ref() != Some(&next) {
        *lock(slot()) = Some(next.clone());
        announce(app, Some(&next));
    }
}

fn forget_if_closed(app: &AppHandle) {
    let Some(known) = lock(slot()).clone() else { return };
    // SAFETY: IsWindow accepts any handle value.
    let alive = unsafe { IsWindow(Some(HWND(known.hwnd as *mut core::ffi::c_void))) }.as_bool();
    if !alive {
        *lock(slot()) = None;
        announce(app, None);
    }
}

fn window_title(window: HWND) -> String {
    let mut buffer = [0u16; TITLE_MAX];
    // SAFETY: the buffer is valid for TITLE_MAX UTF-16 units.
    let len = unsafe { GetWindowTextW(window, &mut buffer) };
    String::from_utf16_lossy(&buffer[..usize::try_from(len).unwrap_or(0)])
}

/// The executable's file name (« chrome.exe ») of a process, or None when it can't be read.
fn exe_name(pid: u32) -> Option<String> {
    // SAFETY: the process handle is closed on every path after the query.
    unsafe {
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buffer = [0u16; PATH_MAX];
        let mut size = PATH_MAX as u32;
        let queried = QueryFullProcessImageNameW(process, PROCESS_NAME_WIN32, PWSTR(buffer.as_mut_ptr()), &mut size);
        let _ = CloseHandle(process);
        queried.ok()?;
        let path = String::from_utf16_lossy(&buffer[..size as usize]);
        path.rsplit(['\\', '/']).next().map(str::to_owned)
    }
}

fn payload(remembered: &Remembered, snapshot: Snapshot) -> Value {
    let mut page = json!({
        "title": remembered.title,
        "text": snapshot.text.chars().take(page_reader::TEXT_MAX as usize).collect::<String>(),
        "outline": build_outline(&snapshot.items, snapshot.view),
    });
    if let Some(url) = snapshot.address.as_deref().and_then(normalize_url) {
        page["url"] = json!(url);
    }
    page
}

/// Reads the remembered browser window's page, for the daemon's `page` field.
pub async fn read_current() -> Result<Value, String> {
    if !tracking() {
        return Err("Le suivi de la page est désactivé : réactivez-le dans l'onglet Chat.".into());
    }
    let Some(remembered) = lock(slot()).clone() else {
        return Err("Aucune page de navigateur à joindre : ouvrez une page dans Chrome ou Edge, ou décochez « Joindre ».".into());
    };
    let hwnd = remembered.hwnd;
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(page_reader::read(hwnd));
    });
    let waited = tauri::async_runtime::spawn_blocking(move || rx.recv_timeout(READ_TIMEOUT))
        .await
        .map_err(|err| format!("Lecture de la page interrompue : {err}"))?;
    let snapshot = waited.map_err(|_| "La lecture de la page a pris trop de temps.".to_string())??;
    Ok(payload(&remembered, snapshot))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("omnigroup-{name}-{}", std::process::id()))
    }

    #[test]
    fn the_choice_survives_a_restart() {
        let dir = temp_dir("tracking-a");
        assert!(!marker_says_off(&dir)); // nothing saved: tracking is on
        write_marker(&dir, false).expect("switch off");
        assert!(marker_says_off(&dir));
        write_marker(&dir, true).expect("switch on");
        assert!(!marker_says_off(&dir));
        write_marker(&dir, true).expect("switching on twice is fine");
        let _ = fs::remove_dir_all(&dir);
    }
}
