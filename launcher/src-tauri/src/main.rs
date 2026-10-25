// No console window on Windows release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(feature = "app")]
fn main() {
    leyline_lib::run();
}

#[cfg(not(feature = "app"))]
fn main() {
    eprintln!("Leyline was built without the `app` feature: only the core library is available.");
    std::process::exit(2);
}
