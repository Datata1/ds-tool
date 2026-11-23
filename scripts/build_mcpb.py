"""Build the Claude packages for players without a terminal:

- ``dist/ap-planner.mcpb``: Claude Desktop extension (Windows/macOS: Einstellungen →
  Erweiterungen). Claude Desktop installs Python and all packages itself.
- ``dist/ap-planner-plugin.zip``: Claude plugin (Plugin-Upload, e.g. Claude Desktop on Linux).
  Brings the skills as real skills plus the MCP server; needs ``uv`` on the computer.

    uv run python scripts/build_mcpb.py

Server type "uv": Claude Desktop installs Python and the dependencies itself, the player
needs nothing but Claude Desktop. Player data lives outside the extension (AP_HOME, default
Documents/ap-planner), so updates never touch it.
"""

import json
import tomllib
import zipfile
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
# Everything `uv run` needs to build and start the server, plus the skills (served as prompts).
INCLUDE = [
    "pyproject.toml", "uv.lock", "README.md", "LICENSE", "src", ".claude/skills", "docs",
]  # fmt: skip
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}

# Values the server reads (AP_*), filled from the plugin/extension options.
SERVER_ENV = {
    "AP_HOME": "${user_config.data_folder}",
    "AP_DISCORD_BOT_TOKEN": "${user_config.discord_bot_token}",
    "AP_DSU_API_KEY": "${user_config.dsu_api_key}",
}

LONG_DESCRIPTION = """\
Plane Adelungen, Fakes und Flexdeff für Die Stämme im Chat mit Claude. Das Tool rechnet
Laufzeiten und Abschickzeiten auf die Sekunde, prüft die Reihenfolge (nie ein AG ohne Off davor),
legt die Pläne bei DS Ultimate an und schreibt die Discord-Nachrichten.

Kein Botting: Es werden nur öffentliche Weltdaten, Truppen, die du selbst kopierst und in den
Chat einfügst, und DS-Ultimate-Links genutzt. Zum Start einfach schreiben:
„Hilf mir mit dem Angriffsplaner“.
"""


def manifest(version: str) -> dict[str, object]:
    return {
        "manifest_version": "0.4",
        "name": "ap-planner",
        "display_name": "AP-Planner (Die Stämme)",
        "version": version,
        "description": "Angriffsplaner für Die Stämme: Adeln, Fakes, DS Ultimate, Discord.",
        "long_description": LONG_DESCRIPTION,
        "author": {"name": "Datata1", "url": "https://github.com/Datata1/ds-tool"},
        "repository": {"type": "git", "url": "https://github.com/Datata1/ds-tool"},
        "homepage": "https://github.com/Datata1/ds-tool",
        "documentation": "https://github.com/Datata1/ds-tool/blob/main/docs/claude-desktop.md",
        "license": "MIT",
        "keywords": ["die-staemme", "tribal-wars", "ds-ultimate", "angriffsplaner"],
        "server": {
            "type": "uv",
            "entry_point": "src/ap_planner/mcp_server.py",
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    "${__dirname}",
                    "--frozen",
                    "--no-dev",
                    "--quiet",
                    "ap-planner-mcp",
                ],
                "env": SERVER_ENV,
            },
        },
        "tools_generated": True,
        "prompts_generated": True,
        "user_config": {
            "data_folder": {
                "type": "directory",
                "title": "Datenordner",
                "description": "Hier speichert der Planer Weltdaten, Truppen und Operationen. "
                "Bleibt bei Updates erhalten.",
                "default": "${HOME}/ap-planner",
                "required": False,
            },
            "discord_bot_token": {
                "type": "string",
                "title": "Discord-Bot-Token (optional)",
                "description": "Nur nötig, wenn der Planer Nachrichten selbst in Discord "
                "senden soll. Leer lassen, wenn du die Texte lieber kopierst.",
                "sensitive": True,
                "required": False,
            },
            "dsu_api_key": {
                "type": "string",
                "title": "DS-Ultimate-API-Key (optional)",
                "description": "Persönlicher Key von den DS-Ultimate-Admins. Damit legt der "
                "Planer Pläne über die offizielle Schnittstelle an und zeigt, wer schon "
                "abgehakt hat. Nie weitergeben. Ohne Key geht alles über die normale Seite.",
                "sensitive": True,
                "required": False,
            },
        },
        "compatibility": {
            "platforms": ["darwin", "win32", "linux"],
            "runtimes": {"python": ">=3.12"},
        },
    }


def files() -> list[Path]:
    out: list[Path] = []
    for name in INCLUDE:
        path = ROOT / name
        if path.is_file():
            out.append(path)
            continue
        out += [
            p
            for p in sorted(path.rglob("*"))
            if p.is_file() and not SKIP_PARTS & set(p.parts) and p.suffix != ".pyc"
        ]
    return out


def plugin_manifest(version: str) -> dict[str, object]:
    """``.claude-plugin/plugin.json``: same server and options as the extension.

    The server lives in ``server/``; its virtualenv goes to the plugin data folder, so it
    survives plugin updates. Without a data folder the server uses ~/ap-planner.
    """
    ext = manifest(version)
    user_config = cast("dict[str, dict[str, object]]", ext["user_config"])
    # no "default": the extension's ${HOME} placeholder is not a plugin variable
    options = {
        key: {k: v for k, v in opt.items() if k != "default"} for key, opt in user_config.items()
    }
    options["data_folder"]["description"] = (
        "Hier speichert der Planer Weltdaten, Truppen und Operationen. Leer lassen = Ordner "
        "ap-planner in deinem Benutzerordner."
    )
    return {
        "name": "ap-planner",
        "displayName": ext["display_name"],
        "version": version,
        "description": ext["description"],
        "author": ext["author"],
        "homepage": ext["homepage"],
        "repository": "https://github.com/Datata1/ds-tool",
        "license": "MIT",
        "keywords": ext["keywords"],
        "mcpServers": {
            "ap-planner": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    "${CLAUDE_PLUGIN_ROOT}/server",
                    "--frozen",
                    "--no-dev",
                    "--quiet",
                    "ap-planner-mcp",
                ],
                "env": {**SERVER_ENV, "UV_PROJECT_ENVIRONMENT": "${CLAUDE_PLUGIN_DATA}/venv"},
            }
        },
        "userConfig": options,
    }


def build_extension(version: str) -> Path:
    out = DIST / "ap-planner.mcpb"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(version), ensure_ascii=False, indent=2))
        for f in files():
            z.write(f, f.relative_to(ROOT).as_posix())
    return out


def build_plugin(version: str) -> Path:
    out = DIST / "ap-planner-plugin.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            ".claude-plugin/plugin.json",
            json.dumps(plugin_manifest(version), ensure_ascii=False, indent=2),
        )
        for f in files():
            rel = f.relative_to(ROOT)
            if rel.is_relative_to(".claude/skills"):
                z.write(f, ("skills" / rel.relative_to(".claude/skills")).as_posix())
            else:
                z.write(f, ("server" / rel).as_posix())
    return out


def main() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    DIST.mkdir(exist_ok=True)
    for out in (build_extension(version), build_plugin(version)):
        print(f"{out} ({out.stat().st_size // 1024} KB, Version {version})")


if __name__ == "__main__":
    main()
