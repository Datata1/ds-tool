"""HTTP API for the desktop app and the Google Doc use case with the app's own login."""

import gzip
import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from ap_planner import services, usecases
from ap_planner.api import create_app
from ap_planner.config import Settings
from ap_planner.google_client import DOCS, DRIVE, TOKEN_URL, UPLOAD, GoogleClient, OAuthClient
from ap_planner.ingest.store import WorldStore
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TOKEN = "t0ken"
ALLIES = "1,Raketen,RAK,2,3,0,0,1\n2,Feind,SWRE,1,1,0,0,2\n"
PLAYERS = "10,Graf,1,2,0,1\n20,Basol,2,1,0,3\n"
VILLAGES = "1,A,478,535,10,5000,0\n4,D,481,521,20,4000,0\n"


@pytest.fixture
def world(tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(world="de260", data_dir=tmp_path / "data", discord_bot_token="")
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("config.xml", "units.xml"):
        shutil.copy(fixtures_dir / name, raw / name)
    for name, text in (("ally", ALLIES), ("player", PLAYERS), ("village", VILLAGES)):
        (raw / f"{name}.txt.gz").write_bytes(gzip.compress(text.encode()))
    settings.world_dir.mkdir(parents=True)
    WorldStore(settings.db_path).load_raw(raw, "de260")
    monkeypatch.setattr(usecases, "settings", settings)
    return settings


@pytest.fixture
def client() -> TestClient:
    c = TestClient(create_app(token=TOKEN))
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    return c


def test_token_required() -> None:
    anon = TestClient(create_app(token=TOKEN))
    assert anon.get("/api/health").status_code == 401
    assert anon.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"}).json()["ok"]


def test_lists_every_usecase_with_schema(client: TestClient) -> None:
    items = {u["name"]: u for u in client.get("/api/usecases").json()}
    assert set(items) == set(usecases.REGISTRY)
    assert items["google_doc_sync"]["app_only"]
    assert not items["strategie_ziele"]["app_only"]
    params = items["strategie_ziele"]["parameters"]
    assert params["required"] == ["gegner"]
    assert params["properties"]["max_ag_laufzeit_h"]["default"] == 12


def test_call_results_and_errors(client: TestClient, world: Settings) -> None:
    r = client.post("/api/call/find_villages", json={"player": "Graf"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]
    r = client.post("/api/call/player_info", json={"name": "Niemand"})
    assert r.status_code == 400
    assert r.json()["error"]
    assert client.post("/api/call/nope", json={}).status_code == 404
    r = client.post("/api/call/strategie_ziele", json={"gegner": "SWRE", "limit": "viele"})
    assert r.status_code == 422


def test_google_doc_hidden_from_claude() -> None:
    import asyncio  # noqa: PLC0415

    from ap_planner import mcp_server  # noqa: PLC0415

    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert "google_doc_sync" not in names
    assert "strategie_ziele" in names


# --- Google -------------------------------------------------------------------------


def _google(tmp_path: Path) -> GoogleClient:
    token = tmp_path / "google_token.json"
    token.write_text(
        json.dumps({"access_token": "old", "refresh_token": "r1", "expires_at": 0}), "utf-8"
    )
    return GoogleClient(OAuthClient("cid", "csec"), token, http=httpx.Client())


@respx.mock
def test_google_client_refresh_upload_share_update(tmp_path: Path) -> None:
    refresh = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    )
    upload = respx.post(UPLOAD).mock(return_value=httpx.Response(200, json={"id": "DOC1"}))
    share = respx.post(f"{DRIVE}/files/DOC1/permissions").mock(
        return_value=httpx.Response(200, json={"id": "anyoneWithLink"})
    )
    respx.get(f"{DOCS}/DOC1").mock(
        return_value=httpx.Response(
            200, json={"body": {"content": [{"endIndex": 1}, {"endIndex": 77}]}}
        )
    )
    batch = respx.post(f"{DOCS}/DOC1:batchUpdate").mock(return_value=httpx.Response(200, json={}))
    g = _google(tmp_path)
    assert g.create_doc_from_html("OP Test", "<p>Hallo</p>") == "DOC1"
    assert refresh.call_count == 1  # token refreshed once, then cached
    sent = upload.calls[0].request
    assert sent.headers["Authorization"] == "Bearer new"
    assert b"application/vnd.google-apps.document" in sent.content
    assert b"<p>Hallo</p>" in sent.content
    g.share_anyone_reader("DOC1")
    assert json.loads(share.calls[0].request.content) == {"type": "anyone", "role": "reader"}
    assert g.doc_end_index("DOC1") == 77
    g.batch_update("DOC1", [{"n": i} for i in range(450)])
    chunks = [len(json.loads(c.request.content)["requests"]) for c in batch.calls]
    assert chunks == [400, 50]  # in order, in chunks
    assert refresh.call_count == 1
    stored = json.loads((tmp_path / "google_token.json").read_text())
    assert stored["refresh_token"] == "r1"
    assert stored["expires_at"] > time.time()


def test_google_not_logged_in(tmp_path: Path) -> None:
    g = GoogleClient(OAuthClient("cid", ""), tmp_path / "none.json")
    assert not g.logged_in
    with pytest.raises(RuntimeError, match="nicht bei Google angemeldet"):
        g.access_token()


class FakeGoogle(GoogleClient):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def create_doc_from_html(self, title: str, html: str) -> str:
        self.calls.append(("create", title))
        return "D" * 30

    def share_anyone_reader(self, file_id: str) -> None:
        self.calls.append(("share", file_id))

    def doc_end_index(self, doc_id: str) -> int:
        return 50

    def batch_update(self, doc_id: str, requests: list[dict[str, Any]]) -> None:
        self.calls.append(("update", doc_id, requests[0]))


def _write_op(settings: Settings, axe: int = 5000) -> None:
    folder = settings.world_dir / "ops" / "test"
    folder.mkdir(parents=True, exist_ok=True)
    op = Operation.model_validate(
        {
            "name": "RAK Aktion",
            "world": "de260",
            "arrival": "2026-11-12 09:00:00",
            "targets": [{"coord": "481|521", "offs": 1}],
        }
    )
    if not (folder / "operation.yaml").exists():
        services.save_operation(op, folder / "operation.yaml")
    t0 = datetime(2026, 11, 12, 9, tzinfo=ZoneInfo("Europe/Berlin"))
    cmd = PlannedCommand(
        source_id=1, target_id=4, units={Unit.AXE: axe, Unit.RAM: 200}, slowest_unit=Unit.RAM,
        type=CommandType.ATTACK, arrival=t0, send=t0 - timedelta(hours=3),
        travel=timedelta(hours=3), note="Graf -> D",
    )  # fmt: skip
    plan = Plan(world="de260", name="Test", created_at=datetime.now(UTC), commands=[cmd])
    (folder / "plan.json").write_text(plan.model_dump_json(), "utf-8")


def test_doc_sync_creates_shares_then_rewrites_same_doc(
    world: Settings, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGoogle()
    monkeypatch.setattr(usecases, "_google", lambda: fake)
    _write_op(world)
    r = client.post("/api/call/google_doc_sync", json={"name": "test"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["aktion"] == ["angelegt", "freigegeben (jeder mit Link: ansehen)"]
    assert r.json()["result"]["link"].endswith("/view")
    assert [c[0] for c in fake.calls] == ["create", "share"]

    again = client.post("/api/call/google_doc_sync", json={"name": "test"}).json()["result"]
    assert again["aktion"] == ["schon aktuell"]

    _write_op(world, axe=6000)  # re-planned
    r = client.post("/api/call/google_doc_sync", json={"name": "test"}).json()["result"]
    assert r["aktion"] == ["neu befüllt"]
    assert fake.calls[-1][0] == "update"
    assert fake.calls[-1][2] == {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 49}}}
    assert sum(1 for c in fake.calls if c[0] == "create") == 1  # never a second doc


def test_operation_form_roundtrip_keeps_links(world: Settings, client: TestClient) -> None:
    _write_op(world)
    path = world.world_dir / "ops" / "test" / "operation.yaml"
    op = services.load_operation(path).model_copy(update={"gdoc_id": "G" * 30})
    services.save_operation(op, path)
    form = client.post("/api/call/operation_form", json={"name": "test"}).json()["result"]
    data = form["operation"]
    data["targets"][0]["offs"] = 2
    r = client.post("/api/call/save_operation_form", json={"name": "test", "operation": data})
    assert r.status_code == 200, r.text
    saved = services.load_operation(path)
    assert saved.targets[0].offs == 2
    assert saved.gdoc_id == "G" * 30  # not lost by the form

    new = client.post("/api/call/operation_form", json={}).json()["result"]
    assert new["neu"]
    bad = dict(new["operation"], name="Neu")  # target without coordinate
    r = client.post("/api/call/save_operation_form", json={"name": "neu", "operation": bad})
    assert r.status_code == 400
    assert not (world.world_dir / "ops" / "neu").exists()
