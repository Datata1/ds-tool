//! AP-Planer desktop shell: starts the Python API (`ap-planner-server`) as a sidecar on a free
//! local port with a random token and hands URL + token to the web frontend. All planning
//! logic lives in Python; this file only manages the process.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use rand::distributions::{Alphanumeric, DistString};
use serde::Serialize;
use tauri::{Manager, RunEvent, State};

#[derive(Clone, Serialize)]
struct BackendInfo {
    url: String,
    token: String,
}

struct Backend {
    info: Mutex<Result<BackendInfo, String>>,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn backend(state: State<'_, Backend>) -> Result<BackendInfo, String> {
    state.info.lock().map_err(|e| e.to_string())?.clone()
}

/// The bundled server binary next to the app (Tauri strips the target triple), if present.
fn sidecar_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let name = if cfg!(windows) { "ap-planner-server.exe" } else { "ap-planner-server" };
    let path = dir.join(name);
    path.exists().then_some(path)
}

/// Data folder shared with Claude Desktop (its plugin default is also `~/ap-planner`).
/// The player can choose another one; the choice is stored in the app's config folder.
fn default_data_folder() -> PathBuf {
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    home.join("ap-planner")
}

fn data_folder_file(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("data_folder.txt"))
}

fn data_folder(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(env) = std::env::var("AP_HOME") {
        if !env.trim().is_empty() {
            return PathBuf::from(env.trim());
        }
    }
    data_folder_file(app)
        .and_then(|f| std::fs::read_to_string(f).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(default_data_folder)
}

#[derive(Serialize)]
struct FolderInfo {
    current: String,
    default: String,
}

#[tauri::command]
fn get_data_folder(app: tauri::AppHandle) -> FolderInfo {
    FolderInfo {
        current: data_folder(&app).display().to_string(),
        default: default_data_folder().display().to_string(),
    }
}

/// Store another data folder and restart, so the planner service uses it.
#[tauri::command]
fn set_data_folder(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let file = data_folder_file(&app).ok_or("kein Konfigurationsordner")?;
    if let Some(dir) = file.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let path = path.trim();
    if !path.is_empty() {
        std::fs::create_dir_all(path).map_err(|e| format!("Ordner geht nicht: {e}"))?;
    }
    std::fs::write(&file, path).map_err(|e| e.to_string())?;
    if let Some(state) = app.try_state::<Backend>() {
        if let Ok(mut guard) = state.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
    app.restart();
}

fn server_command(token: &str, home: &PathBuf) -> Command {
    let mut cmd = match sidecar_path() {
        Some(path) => Command::new(path),
        None => {
            // Development: run the server from the Python project next to `desktop/`.
            let project = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
            let mut c = Command::new("uv");
            c.args(["run", "--project"]).arg(project).arg("ap-planner-server");
            c
        }
    };
    cmd.env("AP_HOME", home)
        .args(["--port", "0", "--token", token])
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// Start the server and wait for its `AP_SERVER_READY <port>` line.
fn start_server(home: &PathBuf) -> Result<(Child, BackendInfo), String> {
    let token = Alphanumeric.sample_string(&mut rand::thread_rng(), 32);
    let mut child = server_command(&token, home)
        .spawn()
        .map_err(|e| format!("Planer-Dienst startet nicht: {e}"))?;
    let stdout = child.stdout.take().ok_or("kein stdout")?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(port) = line.strip_prefix("AP_SERVER_READY ") {
                let _ = tx.send(port.trim().to_string());
            }
        }
    });
    let deadline = Instant::now() + Duration::from_secs(120);
    let port = loop {
        if let Ok(port) = rx.recv_timeout(Duration::from_millis(200)) {
            break port;
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("Planer-Dienst beendet ({status})"));
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            return Err("Planer-Dienst antwortet nicht".into());
        }
    };
    Ok((child, BackendInfo { url: format!("http://127.0.0.1:{port}"), token }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // WebKitGTK draws flickering lines while scrolling with some GPU drivers (esp. NVIDIA).
    // Its DMA-BUF renderer is the usual cause; the player can still override this variable.
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        // SAFETY: set once at startup, before any other thread exists.
        unsafe { std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1") };
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Window/taskbar icon also in development builds (Linux docks otherwise show a
            // generic icon until the app is installed with its .desktop file).
            if let Some(window) = app.get_webview_window("main") {
                if let Ok(icon) = tauri::image::Image::from_bytes(include_bytes!("../icons/icon.png")) {
                    let _ = window.set_icon(icon);
                }
            }
            let home = data_folder(app.handle());
            let (child, info) = match start_server(&home) {
                Ok((child, info)) => (Some(child), Ok(info)),
                Err(err) => (None, Err(err)),
            };
            app.manage(Backend { info: Mutex::new(info), child: Mutex::new(child) });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend, get_data_folder, set_data_folder])
        .build(tauri::generate_context!())
        .expect("AP-Planer konnte nicht starten");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut guard) = state.child.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}
