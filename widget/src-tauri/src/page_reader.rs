//! Reads the web page open in a Chromium browser window with Windows UI Automation: no
//! extension to install. Everything comes from the accessibility tree the browser already
//! publishes: the page's text, its headings, links, buttons and fields with their place on
//! screen, and the address bar.
//!
//! Never read: the value of a page field (so no password), and no password field at all.
//! Chrome only builds its tree for the page once a reader asks, so the first look can come
//! back empty: it is retried a few times. Call `read` on a thread of its own, with a
//! timeout (see page_watch.rs): a very large page can take a while.

use crate::page_logic::{tidy, Kind, RawItem, Rect};
use std::time::Duration;
use windows::core::Error;
use windows::Win32::Foundation::{E_FAIL, HWND, RECT};
use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED};
use windows::Win32::System::Variant::VARIANT;
use windows::Win32::UI::Accessibility::*;

pub const TEXT_MAX: i32 = 20_000;
const ATTEMPTS: u32 = 4;
const RETRY_WAIT: Duration = Duration::from_millis(400);
const ITEMS_MAX: i32 = 600;
const SCROLL_WAIT: Duration = Duration::from_millis(300);
/// UIA_HeadingLevel1..3: the values of the HeadingLevel property for h1..h3.
const HEADING_LEVELS: [i32; 3] = [80051, 80052, 80053];

pub struct Snapshot {
    pub address: Option<String>,
    pub text: String,
    pub items: Vec<RawItem>,
    pub view: Rect,
}

struct Com;

impl Com {
    fn init() -> Result<Self, String> {
        // SAFETY: plain COM initialisation of this (fresh) thread, undone in Drop.
        unsafe { CoInitializeEx(None, COINIT_MULTITHREADED).ok() }
            .map(|()| Com)
            .map_err(|err| format!("Accessibilité Windows indisponible : {err}"))
    }
}

impl Drop for Com {
    fn drop(&mut self) {
        // SAFETY: balances the successful CoInitializeEx in `init`.
        unsafe { CoUninitialize() }
    }
}

fn rect(r: RECT) -> Rect {
    Rect { left: r.left, top: r.top, right: r.right, bottom: r.bottom }
}

/// Reads the browser window `hwnd`. Blocking; run it off the UI thread.
pub fn read(hwnd: isize) -> Result<Snapshot, String> {
    let _com = Com::init()?;
    // SAFETY: UI Automation calls on this thread only, with elements it just obtained.
    unsafe { read_window(HWND(hwnd as *mut core::ffi::c_void)) }
        .map_err(|err| format!("Lecture de la page impossible : {err}"))
}

unsafe fn kind_condition(uia: &IUIAutomation, id: UIA_CONTROLTYPE_ID) -> windows::core::Result<IUIAutomationCondition> {
    uia.CreatePropertyCondition(UIA_ControlTypePropertyId, &VARIANT::from(id.0))
}

unsafe fn read_window(hwnd: HWND) -> windows::core::Result<Snapshot> {
    let uia: IUIAutomation = CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER)?;
    let window = uia.ElementFromHandle(hwnd)?;
    let (document, text) = wait_for_document(&uia, &window)?;
    let view = rect(document.CurrentBoundingRectangle()?);
    let items = collect_items(&uia, &document)?;
    let address = address_bar(&uia, &window, view);
    Ok(Snapshot { address, text, items, view })
}

/// The page's document and its text; Chrome fills both in only after the first request.
unsafe fn wait_for_document(uia: &IUIAutomation, window: &IUIAutomationElement) -> windows::core::Result<(IUIAutomationElement, String)> {
    let condition = kind_condition(uia, UIA_DocumentControlTypeId)?;
    let mut found = None;
    for attempt in 1..=ATTEMPTS {
        if let Ok(document) = window.FindFirst(TreeScope_Descendants, &condition) {
            let text = document_text(&document);
            let done = !text.trim().is_empty() || attempt == ATTEMPTS;
            found = Some((document, text));
            if done {
                break;
            }
        } else if attempt == ATTEMPTS {
            break;
        }
        std::thread::sleep(RETRY_WAIT);
    }
    found.ok_or_else(|| Error::new(E_FAIL, "aucune page web trouvée dans cette fenêtre"))
}

unsafe fn document_text(document: &IUIAutomationElement) -> String {
    let Ok(pattern) = document.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId) else {
        return String::new();
    };
    pattern.DocumentRange().and_then(|range| range.GetText(TEXT_MAX)).map(|text| text.to_string()).unwrap_or_default()
}

unsafe fn or(uia: &IUIAutomation, a: &IUIAutomationCondition, b: &IUIAutomationCondition) -> windows::core::Result<IUIAutomationCondition> {
    uia.CreateOrCondition(a, b)
}

/// Links, buttons, fields and h1-h3 headings: what the outline is made of.
unsafe fn items_condition(uia: &IUIAutomation) -> windows::core::Result<IUIAutomationCondition> {
    let mut condition = kind_condition(uia, UIA_HyperlinkControlTypeId)?;
    for id in [UIA_ButtonControlTypeId, UIA_EditControlTypeId] {
        condition = or(uia, &condition, &kind_condition(uia, id)?)?;
    }
    for level in HEADING_LEVELS {
        let heading = uia.CreatePropertyCondition(UIA_HeadingLevelPropertyId, &VARIANT::from(level))?;
        condition = or(uia, &condition, &heading)?;
    }
    Ok(condition)
}

unsafe fn item_cache(uia: &IUIAutomation) -> windows::core::Result<IUIAutomationCacheRequest> {
    let cache = uia.CreateCacheRequest()?;
    for property in [UIA_NamePropertyId, UIA_ControlTypePropertyId, UIA_BoundingRectanglePropertyId, UIA_HeadingLevelPropertyId, UIA_IsPasswordPropertyId] {
        cache.AddProperty(property)?;
    }
    Ok(cache)
}

/// What an element of `items_condition` is for the outline; None for a password field.
unsafe fn classify(element: &IUIAutomationElement) -> Option<Kind> {
    if element.CachedIsPassword().map(|b| b.as_bool()).unwrap_or(true) {
        return None;
    }
    let level = element.GetCachedPropertyValue(UIA_HeadingLevelPropertyId).ok().and_then(|v| i32::try_from(&v).ok());
    let control = element.CachedControlType().ok()?;
    if level.is_some_and(|l| HEADING_LEVELS.contains(&l)) {
        Some(Kind::Heading)
    } else if control == UIA_HyperlinkControlTypeId {
        Some(Kind::Link)
    } else if control == UIA_ButtonControlTypeId {
        Some(Kind::Button)
    } else if control == UIA_EditControlTypeId {
        Some(Kind::Field)
    } else {
        None
    }
}

unsafe fn collect_items(uia: &IUIAutomation, document: &IUIAutomationElement) -> windows::core::Result<Vec<RawItem>> {
    let found = document.FindAllBuildCache(TreeScope_Descendants, &items_condition(uia)?, &item_cache(uia)?)?;
    let mut items = Vec::new();
    for index in 0..found.Length()?.min(ITEMS_MAX) {
        let element = found.GetElement(index)?;
        let Some(kind) = classify(&element) else { continue };
        items.push(RawItem { kind, name: element.CachedName()?.to_string(), rect: rect(element.CachedBoundingRectangle()?) });
    }
    Ok(items)
}

/// Where an element is on the screen right now (physical pixels).
pub struct Located {
    pub rect: Rect,
}

/// Finds the element again by what it is and its text (the closest one to where it was), scrolls
/// it into view when it is below or above the visible page, and returns its screen rectangle.
/// Blocking, like `read`.
pub fn locate(hwnd: isize, kind: Kind, text: &str, near: Rect) -> Result<Located, String> {
    let _com = Com::init()?;
    // SAFETY: UI Automation calls on this thread only, with elements it just obtained.
    unsafe { locate_in(HWND(hwnd as *mut core::ffi::c_void), kind, text, near) }
        .map_err(|err| format!("Élément introuvable : {err}"))?
        .ok_or_else(|| "Cet élément n'est plus sur la page.".to_string())
}

unsafe fn locate_in(hwnd: HWND, kind: Kind, text: &str, near: Rect) -> windows::core::Result<Option<Located>> {
    let uia: IUIAutomation = CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER)?;
    let window = uia.ElementFromHandle(hwnd)?;
    let (document, _) = wait_for_document(&uia, &window)?;
    let found = document.FindAllBuildCache(TreeScope_Descendants, &items_condition(&uia)?, &item_cache(&uia)?)?;
    let wanted = tidy(text);
    let mut best: Option<(i64, IUIAutomationElement)> = None;
    for index in 0..found.Length()?.min(ITEMS_MAX) {
        let element = found.GetElement(index)?;
        if classify(&element) != Some(kind) || tidy(&element.CachedName()?.to_string()) != wanted {
            continue;
        }
        let distance = i64::from((element.CachedBoundingRectangle()?.top - near.top).abs());
        if best.as_ref().is_none_or(|(d, _)| distance < *d) {
            best = Some((distance, element));
        }
    }
    let Some((_, element)) = best else { return Ok(None) };
    let view = rect(document.CurrentBoundingRectangle()?);
    let mut at = rect(element.CurrentBoundingRectangle()?);
    if at.bottom <= view.top || at.top >= view.bottom {
        // Only brings it into view (a scroll): never clicks or types in the page.
        if let Ok(pattern) = element.GetCurrentPatternAs::<IUIAutomationScrollItemPattern>(UIA_ScrollItemPatternId) {
            pattern.ScrollIntoView()?;
            std::thread::sleep(SCROLL_WAIT);
            at = rect(element.CurrentBoundingRectangle()?);
        }
    }
    let visible = at.right > at.left && at.bottom > view.top && at.top < view.bottom;
    Ok(visible.then_some(Located { rect: at }))
}

/// The browser's address bar: the first text box that sits above the page. Skipped while it
/// has the keyboard focus (what is there may be a search being typed, not the page's address).
unsafe fn address_bar(uia: &IUIAutomation, window: &IUIAutomationElement, view: Rect) -> Option<String> {
    let edit = window.FindFirst(TreeScope_Descendants, &kind_condition(uia, UIA_EditControlTypeId).ok()?).ok()?;
    let at = edit.CurrentBoundingRectangle().ok()?;
    if at.bottom > view.top + 2 || edit.CurrentHasKeyboardFocus().ok()?.as_bool() {
        return None;
    }
    let pattern = edit.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId).ok()?;
    pattern.CurrentValue().ok().map(|value| value.to_string())
}
