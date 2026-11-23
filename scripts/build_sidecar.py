"""Build the Python API as one executable for the desktop app (Tauri sidecar).

    uv run --with pyinstaller python scripts/build_sidecar.py [--target <rust-target-triple>]

Writes ``desktop/src-tauri/binaries/ap-planner-server-<target>[.exe]`` - Tauri bundles it
next to the app and starts it on launch. With ``AP_GOOGLE_CLIENT_ID`` /
``AP_GOOGLE_CLIENT_SECRET`` in the environment, the Google login is built in
(``src/ap_planner/builtin.py`` is written for the build and restored afterwards).
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = ROOT / "src" / "ap_planner" / "builtin.py"
OUT_DIR = ROOT / "desktop" / "src-tauri" / "binaries"
SEP = ";" if sys.platform == "win32" else ":"


def host_target() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(ln.split(": ", 1)[1] for ln in out.splitlines() if ln.startswith("host: "))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=os.environ.get("TAURI_TARGET") or None)
    args = parser.parse_args()
    target = args.target or host_target()
    exe = ".exe" if "windows" in target else ""

    original = BUILTIN.read_text(encoding="utf-8")
    client_id = os.environ.get("AP_GOOGLE_CLIENT_ID", "")
    secret = os.environ.get("AP_GOOGLE_CLIENT_SECRET", "")
    if client_id:
        BUILTIN.write_text(
            original.replace('GOOGLE_CLIENT_ID = ""', f"GOOGLE_CLIENT_ID = {client_id!r}").replace(
                'GOOGLE_CLIENT_SECRET = ""', f"GOOGLE_CLIENT_SECRET = {secret!r}"
            ),
            encoding="utf-8",
        )
    work = ROOT / "build" / "sidecar"
    try:
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                "--noconfirm", "--clean", "--onefile",
                "--name", "ap-planner-server",
                "--distpath", str(work / "dist"),
                "--workpath", str(work / "build"),
                "--specpath", str(work),
                "--paths", str(ROOT / "src"),
                "--collect-all", "ortools",
                "--collect-submodules", "ap_planner",
                "--collect-data", "ap_planner",
                "--hidden-import", "tzdata",
                "--add-data", f"{ROOT / 'docs'}{SEP}docs",
                "--add-data", f"{ROOT / '.claude' / 'skills'}{SEP}.claude/skills",
                str(ROOT / "src" / "ap_planner" / "api" / "server.py"),
            ],
            check=True,
        )  # fmt: skip
    finally:
        BUILTIN.write_text(original, encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"ap-planner-server-{target}{exe}"
    shutil.copy2(work / "dist" / f"ap-planner-server{exe}", dest)
    print(dest)


if __name__ == "__main__":
    main()
