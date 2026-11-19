//! One Omnigroup at a time. A second launch (a click on the pinned taskbar icon, the Start menu
//! entry, the installer's own launch...) asks the running widget to show itself, then quits.
//!
//! Done with a **named mutex** (who owns the app) and a **named event** (« show yourself »), both
//! in the user's session (`Local\`). Unlike a TCP port, nothing else can occupy it, no firewall or
//! reserved port range matters, and Windows releases it by itself when the app dies, however it
//! died. (The first version used a loopback port: on some PCs that port could not be bound at all,
//! so every launch believed it was the only one and several widgets ran at once.)

use std::thread;
use windows::core::HSTRING;
use windows::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE, WAIT_OBJECT_0};
use windows::Win32::System::Threading::{
    CreateEventW, CreateMutexW, OpenEventW, SetEvent, WaitForSingleObject, EVENT_MODIFY_STATE, INFINITE,
};

const MUTEX_NAME: &str = "Local\\Omnigroup-single-instance";
const EVENT_NAME: &str = "Local\\Omnigroup-show-window";

/// What this process owns for as long as it runs (the handles are never closed on purpose: the
/// mutex must be held until the process ends). `event` is 0 when it could not be created.
pub struct Guard {
    event: isize,
}

pub enum Role {
    /// We are the widget.
    Primary(Guard),
    /// Another Omnigroup runs: it was asked to show itself, we quit.
    Secondary,
}

pub fn claim() -> Role {
    claim_named(MUTEX_NAME, EVENT_NAME)
}

pub fn claim_named(mutex_name: &str, event_name: &str) -> Role {
    // SAFETY: plain Win32 calls with strings that outlive them; every handle we do not keep is closed.
    unsafe {
        let mutex = match CreateMutexW(None, true, &HSTRING::from(mutex_name)) {
            Ok(handle) => handle,
            Err(err) => {
                // Never stop Omnigroup from opening because the guard failed.
                eprintln!("omnigroup: single-instance lock unavailable ({err}); starting anyway");
                return Role::Primary(Guard { event: 0 });
            }
        };
        if GetLastError() == ERROR_ALREADY_EXISTS {
            signal_show(event_name);
            let _ = CloseHandle(mutex);
            return Role::Secondary;
        }
        let event = CreateEventW(None, false, false, &HSTRING::from(event_name))
            .map(|handle| handle.0 as isize)
            .unwrap_or_else(|err| {
                eprintln!("omnigroup: single-instance event unavailable ({err})");
                0
            });
        Role::Primary(Guard { event })
    }
}

/// Wakes the running instance (best effort: it also shows itself at start-up).
unsafe fn signal_show(event_name: &str) {
    if let Ok(event) = OpenEventW(EVENT_MODIFY_STATE, false, &HSTRING::from(event_name)) {
        let _ = SetEvent(event);
        let _ = CloseHandle(event);
    }
}

/// Runs `on_show` on a thread of its own each time a second launch asks for it. Start it right
/// away (before the interface is up): the event is signalled and remembered even then.
pub fn serve<F>(guard: &Guard, on_show: F)
where
    F: Fn() + Send + 'static,
{
    if guard.event == 0 {
        return;
    }
    let event = guard.event;
    thread::spawn(move || loop {
        // SAFETY: the handle was created by `claim_named` and stays open for the process lifetime.
        let waited = unsafe { WaitForSingleObject(HANDLE(event as *mut core::ffi::c_void), INFINITE) };
        if waited != WAIT_OBJECT_0 {
            eprintln!("omnigroup: single-instance wait stopped ({waited:?})");
            break;
        }
        on_show();
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Duration;

    fn names(tag: &str) -> (String, String) {
        let id = std::process::id();
        (format!("Local\\omnigroup-test-{tag}-{id}-mutex"), format!("Local\\omnigroup-test-{tag}-{id}-event"))
    }

    #[test]
    fn a_second_launch_signals_the_first_and_quits() {
        let (mutex, event) = names("signal");
        let Role::Primary(guard) = claim_named(&mutex, &event) else { panic!("first launch must own the lock") };
        let (tx, rx) = mpsc::channel();
        serve(&guard, move || tx.send(()).expect("receiver alive"));
        assert!(matches!(claim_named(&mutex, &event), Role::Secondary));
        rx.recv_timeout(Duration::from_secs(2)).expect("the first instance was asked to show");
    }

    #[test]
    fn a_launch_during_the_first_ones_startup_is_still_recognised() {
        // The lock is taken before anything else, so even a second launch that comes before
        // `serve` is running sees the first one (the old port-based guard missed exactly this).
        let (mutex, event) = names("early");
        let Role::Primary(_guard) = claim_named(&mutex, &event) else { panic!("first launch must own the lock") };
        assert!(matches!(claim_named(&mutex, &event), Role::Secondary));
        assert!(matches!(claim_named(&mutex, &event), Role::Secondary));
    }

    #[test]
    fn different_names_do_not_collide() {
        let (m1, e1) = names("one");
        let (m2, e2) = names("two");
        assert!(matches!(claim_named(&m1, &e1), Role::Primary(_)));
        assert!(matches!(claim_named(&m2, &e2), Role::Primary(_)));
    }
}
