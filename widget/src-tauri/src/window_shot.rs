//! A picture of one window (the browser the person is on), for the optional « capture » box.
//!
//! `PrintWindow` asks the window to draw itself, so only that window is captured (never the
//! rest of the screen, and what covers it does not matter). The picture is shrunk and kept
//! as a small JPEG; the daemon uses it for one turn and never stores it.

use crate::page_logic::{bgra_to_rgb, downscale_rgb};
use windows::Win32::Foundation::{HWND, RECT};
use windows::Win32::Graphics::Gdi::{
    CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC, GetDIBits, ReleaseDC, SelectObject, BITMAPINFO,
    BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, HGDIOBJ,
};
use windows::Win32::Storage::Xps::{PrintWindow, PRINT_WINDOW_FLAGS};
use windows::Win32::UI::WindowsAndMessaging::{GetWindowRect, IsIconic};

const MAX_EDGE: usize = 1280;
/// PW_RENDERFULLCONTENT: also captures what a GPU-drawn browser window shows.
const RENDER_FULL_CONTENT: u32 = 2;
const QUALITIES: [u8; 3] = [72, 55, 40];
const JPEG_MAX_BYTES: usize = 1_000_000;

/// The window as a JPEG (at most `MAX_EDGE` pixels on its longest side).
pub fn capture(hwnd: isize) -> Result<Vec<u8>, String> {
    let window = HWND(hwnd as *mut core::ffi::c_void);
    // SAFETY: plain GDI calls on a window handle; every object created is released below.
    let (bgra, width, height) = unsafe { draw(window) }?;
    let (rgb, w, h) = downscale_rgb(&bgra_to_rgb(&bgra), width, height, MAX_EDGE);
    encode(&rgb, w, h)
}

fn encode(rgb: &[u8], width: usize, height: usize) -> Result<Vec<u8>, String> {
    let (w, h) = (u16::try_from(width).map_err(|e| e.to_string())?, u16::try_from(height).map_err(|e| e.to_string())?);
    for quality in QUALITIES {
        let mut jpeg = Vec::new();
        jpeg_encoder::Encoder::new(&mut jpeg, quality)
            .encode(rgb, w, h, jpeg_encoder::ColorType::Rgb)
            .map_err(|err| format!("Capture impossible : {err}"))?;
        if jpeg.len() <= JPEG_MAX_BYTES {
            return Ok(jpeg);
        }
    }
    Err("La capture est trop volumineuse.".into())
}

unsafe fn draw(window: HWND) -> Result<(Vec<u8>, usize, usize), String> {
    if IsIconic(window).as_bool() {
        return Err("La fenêtre du navigateur est réduite : ouvrez-la pour la capturer.".into());
    }
    let mut frame = RECT::default();
    GetWindowRect(window, &mut frame).map_err(|err| format!("Capture impossible : {err}"))?;
    let (width, height) = ((frame.right - frame.left).max(0) as usize, (frame.bottom - frame.top).max(0) as usize);
    if width == 0 || height == 0 {
        return Err("La fenêtre du navigateur n'a pas de taille.".into());
    }
    let screen = GetDC(None);
    let memory = CreateCompatibleDC(Some(screen));
    let bitmap = CreateCompatibleBitmap(screen, width as i32, height as i32);
    let previous = SelectObject(memory, HGDIOBJ(bitmap.0));
    let drawn = PrintWindow(window, memory, PRINT_WINDOW_FLAGS(RENDER_FULL_CONTENT)).as_bool();
    let mut info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width as i32,
            biHeight: -(height as i32), // top-down rows
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB.0,
            ..Default::default()
        },
        ..Default::default()
    };
    let mut pixels = vec![0u8; width * height * 4];
    let rows = GetDIBits(memory, bitmap, 0, height as u32, Some(pixels.as_mut_ptr().cast()), &mut info, DIB_RGB_COLORS);
    SelectObject(memory, previous);
    let _ = DeleteObject(HGDIOBJ(bitmap.0));
    let _ = DeleteDC(memory);
    ReleaseDC(None, screen);
    if !drawn || rows == 0 {
        return Err("La fenêtre du navigateur n'a pas pu être capturée.".into());
    }
    Ok((pixels, width, height))
}
