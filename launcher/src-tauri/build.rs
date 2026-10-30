fn main() {
    // The Tauri build step (icons, capabilities, the Windows resource) only runs for the desktop app.
    #[cfg(feature = "app")]
    tauri_build::build();
}
