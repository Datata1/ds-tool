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

fn server_command(token: &str) -> Command {
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
    cmd.args(["--port", "0", "--token", token])
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
fn start_server() -> Result<(Child, BackendInfo), String> {
    let token = Alphanumeric.sample_string(&mut rand::thread_rng(), 32);
    let mut child = server_command(&token)
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
    let app = tauri::Builder::default()
        .setup(|app| {
            let (child, info) = match start_server() {
                Ok((child, info)) => (Some(child), Ok(info)),
                Err(err) => (None, Err(err)),
            };
            app.manage(Backend { info: Mutex::new(info), child: Mutex::new(child) });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend])
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
