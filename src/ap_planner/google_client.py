"""Google Docs without Claude: own login (OAuth for desktop apps) with the smallest scope.

Used by the desktop app (and anyone without the Claude Google connectors). Scope is only
``drive.file``: the planner sees nothing but the docs it created itself, and Google needs no
app review for it. The flow is the standard "installed app" flow with PKCE: the browser opens
Google's login, Google redirects to a one-time local address (127.0.0.1) where we pick up the
code. The token is stored in the player's folder (``google_token.json``), never sent anywhere
else.

The OAuth client (``AP_GOOGLE_CLIENT_ID`` / ``AP_GOOGLE_CLIENT_SECRET``) belongs to the
maintainer's Google Cloud project and is built into the app (see ``docs/google.md``). For
desktop clients Google treats the "secret" as public.
"""

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOCS = "https://docs.googleapis.com/v1/documents"
SCOPE = "https://www.googleapis.com/auth/drive.file"
DOC_MIME = "application/vnd.google-apps.document"
# Docs batchUpdate: send big rewrites in chunks, always in the given order.
BATCH_CHUNK = 400
LOGIN_TIMEOUT_S = 300


class GoogleError(RuntimeError):
    """Google refused a request (message is meant for the player)."""


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


class _LoginServer(HTTPServer):
    result: dict[str, str]


class _CodeCatcher(BaseHTTPRequestHandler):
    """Answers Google's redirect once and keeps the query on the server object."""

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        server = self.server
        if isinstance(server, _LoginServer):
            server.result = {k: v[0] for k, v in query.items()}
        ok = "code" in query
        body = (
            "Angemeldet - du kannst dieses Fenster schließen und zum AP-Planer zurückgehen."
            if ok
            else "Anmeldung abgebrochen. Bitte im AP-Planer nochmal versuchen."
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h3>{body}</h3></body></html>".encode())

    def log_message(self, format: str, *args: Any) -> None:  # noqa: ANN401
        return


class GoogleClient:
    def __init__(
        self,
        oauth: OAuthClient,
        token_path: Path,
        http: httpx.Client | None = None,
        open_browser: Callable[[str], object] = webbrowser.open,
    ) -> None:
        self.oauth = oauth
        self.token_path = token_path
        self.http = http or httpx.Client(timeout=30.0)
        self.open_browser = open_browser

    # --- token handling -------------------------------------------------------------

    def _load(self) -> dict[str, Any] | None:
        if not self.token_path.exists():
            return None
        try:
            return json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self, token: dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(token), encoding="utf-8")
        self.token_path.chmod(0o600)

    @property
    def logged_in(self) -> bool:
        token = self._load()
        return bool(token and token.get("refresh_token"))

    def logout(self) -> None:
        self.token_path.unlink(missing_ok=True)

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        data = {**data, "client_id": self.oauth.client_id}
        if self.oauth.client_secret:
            data["client_secret"] = self.oauth.client_secret
        r = self.http.post(TOKEN_URL, data=data)
        if r.status_code != 200:
            msg = f"Google-Anmeldung fehlgeschlagen ({r.status_code}): {r.text[:200]}"
            raise GoogleError(msg)
        token = r.json()
        token["expires_at"] = time.time() + float(token.get("expires_in", 3600)) - 60
        return token

    def access_token(self) -> str:
        token = self._load()
        if not token or not token.get("refresh_token"):
            msg = "Noch nicht bei Google angemeldet - in den Einstellungen „Mit Google anmelden“."
            raise GoogleError(msg)
        if token.get("access_token") and float(token.get("expires_at", 0)) > time.time():
            return str(token["access_token"])
        fresh = self._token_request(
            {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}
        )
        fresh.setdefault("refresh_token", token["refresh_token"])
        self._save(fresh)
        return str(fresh["access_token"])

    def login(self, timeout_s: float = LOGIN_TIMEOUT_S) -> None:
        """Open Google's login in the browser and wait for the redirect to 127.0.0.1."""
        if not self.oauth.client_id:
            msg = "In dieser Installation ist kein Google-Zugang eingebaut (AP_GOOGLE_CLIENT_ID)."
            raise GoogleError(msg)
        server = _LoginServer(("127.0.0.1", 0), _CodeCatcher)
        server.result = {}
        server.timeout = 1.0
        redirect = f"http://127.0.0.1:{server.server_port}/"
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.oauth.client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        self.open_browser(f"{AUTH_URL}?{urlencode(params)}")
        deadline = time.monotonic() + timeout_s
        try:
            while time.monotonic() < deadline:
                server.handle_request()
                if server.result:
                    break
        finally:
            server.server_close()
        result = server.result
        if not result:
            msg = "Google-Anmeldung: Zeit abgelaufen - bitte nochmal versuchen."
            raise GoogleError(msg)
        if result.get("state") != state or "code" not in result:
            msg = f"Google-Anmeldung abgebrochen ({result.get('error', 'kein Code')})."
            raise GoogleError(msg)
        token = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect,
            }
        )
        self._save(token)

    # --- API calls ------------------------------------------------------------------

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:  # noqa: ANN401
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        r = self.http.request(method, url, headers=headers, **kwargs)
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("error", {}).get("message", "")
            except ValueError:
                detail = r.text[:200]
            msg = f"Google-Fehler {r.status_code}: {detail}".rstrip(": ")
            raise GoogleError(msg)
        return r.json() if r.content else None

    def create_doc_from_html(self, title: str, html: str) -> str:
        """Upload HTML; Google converts it into a normal Doc. Returns the doc id."""
        boundary = "ap-planner-" + secrets.token_hex(8)
        meta = json.dumps({"name": title, "mimeType": DOC_MIME})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        return str(self._upload(body, boundary)["id"])

    def _upload(self, body: bytes, boundary: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }
        r = self.http.post(
            UPLOAD, params={"uploadType": "multipart", "fields": "id"}, content=body,
            headers=headers,
        )  # fmt: skip
        if r.status_code >= 400:
            msg = f"Google-Fehler {r.status_code} beim Hochladen: {r.text[:200]}"
            raise GoogleError(msg)
        return r.json()

    def share_anyone_reader(self, file_id: str) -> None:
        """Everyone with the link can view (nothing more)."""
        self._call(
            "POST",
            f"{DRIVE}/files/{file_id}/permissions",
            json={"type": "anyone", "role": "reader"},
        )

    def doc_end_index(self, doc_id: str) -> int:
        doc = self._call("GET", f"{DOCS}/{doc_id}", params={"fields": "body(content(endIndex))"})
        content = (doc.get("body") or {}).get("content") or [{"endIndex": 1}]
        return int(content[-1].get("endIndex", 1))

    def batch_update(self, doc_id: str, requests: list[dict[str, Any]]) -> None:
        for i in range(0, len(requests), BATCH_CHUNK):
            self._call(
                "POST",
                f"{DOCS}/{doc_id}:batchUpdate",
                json={"requests": requests[i : i + BATCH_CHUNK]},
            )
