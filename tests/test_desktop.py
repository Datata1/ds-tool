"""Claude Desktop: data folder resolution, .env writing and the extension bundle."""

import base64
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from ap_planner.config import Settings, app_home
from ap_planner.discord_bot import BOT_PERMISSIONS, application_id, invite_url, pick_by_name
from ap_planner.services import write_env
from ap_planner.troop_collect import clipboard_command

ROOT = Path(__file__).resolve().parents[1]


def test_app_home_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_HOME", str(tmp_path / "daten"))
    assert app_home() == (tmp_path / "daten").resolve()
    assert (tmp_path / "daten").is_dir()


def test_app_home_keeps_project_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("AP_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AP_WORLD=de1\n")
    assert app_home() == tmp_path


def test_app_home_fallback_in_user_folder(tmp_path, monkeypatch):
    # Claude Desktop without AP_HOME starts in "/" - never write data there.
    monkeypatch.setenv("AP_HOME", "  ")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert app_home() == (tmp_path / "home" / "ap-planner").resolve()


def test_empty_env_does_not_hide_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_env({"AP_WORLD": "de260", "AP_DISCORD_BOT_TOKEN": "geheim"})
    write_env({"AP_WORLD": "de261"})
    monkeypatch.setenv("AP_DISCORD_BOT_TOKEN", "")  # empty extension field
    s = Settings()
    assert (s.world, s.discord_bot_token) == ("de261", "geheim")
    assert (tmp_path / ".env").read_text().count("AP_WORLD") == 1


@pytest.fixture
def build_module():
    spec = importlib.util.spec_from_file_location("build_mcpb", ROOT / "scripts/build_mcpb.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_contains_server_and_skills(build_module, tmp_path, monkeypatch):
    monkeypatch.setattr(build_module, "DIST", tmp_path)
    build_module.main()
    with zipfile.ZipFile(tmp_path / "ap-planner.mcpb") as z:  # extension
        names = set(z.namelist())
    manifest = build_module.manifest("1.0.0")
    assert manifest["server"]["entry_point"] in names
    assert {"manifest.json", "pyproject.toml", "uv.lock", "README.md", "LICENSE"} <= names
    assert any(n.startswith(".claude/skills/neue-operation/") for n in names)
    assert not any("__pycache__" in n for n in names)
    env = manifest["server"]["mcp_config"]["env"]
    assert env["AP_HOME"] == "${user_config.data_folder}"


def test_clipboard_command_per_platform():
    win = clipboard_command("win32")
    assert win is not None
    assert win[0] == "powershell"
    assert "UTF8" in win[-1]
    assert clipboard_command("darwin") == ["pbpaste"]


def test_discord_invite_from_token():
    app = "1234567890123456789"
    token = base64.b64encode(app.encode()).decode().rstrip("=") + ".abc.def"
    assert application_id(token) == app
    assert application_id("kein-token") is None
    assert f"client_id={app}" in invite_url(app)
    assert f"permissions={BOT_PERMISSIONS}" in invite_url(app)


def test_pick_channel_by_name_or_id():
    chans = [
        {"id": "1", "name": "sf-review"},
        {"id": "2", "name": "ankündigungen"},
        {"id": "3", "name": "review-alt"},
    ]
    assert pick_by_name(chans, "#SF-Review") == chans[0]
    assert pick_by_name(chans, "2") == chans[1]
    assert pick_by_name(chans, "ankünd") == chans[1]
    assert pick_by_name(chans, "review") is None  # two partial matches: ask instead of guess


def test_plugin_zip_layout(build_module, tmp_path, monkeypatch):
    monkeypatch.setattr(build_module, "DIST", tmp_path)
    build_module.main()
    with zipfile.ZipFile(tmp_path / "ap-planner-plugin.zip") as z:
        names = set(z.namelist())
        manifest = json.loads(z.read(".claude-plugin/plugin.json"))
    assert "skills/einrichtung/SKILL.md" in names
    assert "server/src/ap_planner/mcp_server.py" in names
    assert "server/uv.lock" in names
    assert not any(n.startswith("server/.claude") for n in names)
    server = manifest["mcpServers"]["ap-planner"]
    assert "${CLAUDE_PLUGIN_ROOT}/server" in server["args"]
    assert server["env"]["AP_DSU_API_KEY"] == "${user_config.dsu_api_key}"
    assert manifest["userConfig"]["dsu_api_key"]["sensitive"] is True
    assert all("default" not in opt for opt in manifest["userConfig"].values())


def test_unfilled_plugin_options_count_as_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AP_HOME", "${user_config.data_folder}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AP_DSU_API_KEY", "${user_config.dsu_api_key}")
    assert app_home() == (tmp_path / "home" / "ap-planner").resolve()
    assert Settings().dsu_api_key == ""


def test_skill_descriptions_pass_plugin_validation():
    # Claude's plugin upload rejects descriptions that look like XML tags, e.g. "<welt>".
    for skill in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        front = skill.read_text(encoding="utf-8").split("---")[1]
        description = next(ln for ln in front.splitlines() if ln.startswith("description:"))
        assert "<" not in description, skill.parent.name
        assert ">" not in description, skill.parent.name
