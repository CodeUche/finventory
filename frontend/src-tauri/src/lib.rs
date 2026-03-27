/// Delete the WebView2 Service Worker database so old PWA SW registrations
/// (from previous builds that included vite-plugin-pwa) cannot intercept
/// fetch() calls and strip the Authorization header.
///
/// This runs BEFORE the event loop starts, meaning the webview has not yet
/// loaded the page, so deleting the SW directory takes full effect on this
/// launch. After this one-time cleanup the directory won't exist, and new
/// builds never register a SW in desktop mode, so this becomes a no-op.
#[cfg(target_os = "windows")]
fn clear_webview2_service_workers() {
  if let Ok(local) = std::env::var("LOCALAPPDATA") {
    // Tauri v2 stores WebView2 data under %LOCALAPPDATA%\<identifier>\EBWebView
    // Try both the bundle identifier and the product name.
    let candidates = [
      std::path::Path::new(&local).join("com.finventory.app").join("EBWebView"),
      std::path::Path::new(&local).join("Audity").join("EBWebView"),
    ];
    for base in &candidates {
      let sw_dir = base.join("Default").join("Service Worker");
      if sw_dir.exists() {
        let _ = std::fs::remove_dir_all(&sw_dir);
      }
    }
  }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  // Wipe any stale WebView2 Service Worker registrations before the webview
  // loads. Must run before tauri::Builder::run() to beat the page load.
  #[cfg(target_os = "windows")]
  clear_webview2_service_workers();

  tauri::Builder::default()
    .plugin(tauri_plugin_http::init())
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_fs::init())
    .plugin(tauri_plugin_shell::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
