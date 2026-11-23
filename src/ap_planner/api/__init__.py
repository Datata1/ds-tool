"""HTTP API for the desktop app: every use case of ``usecases.py`` under one endpoint.

    GET  /api/health                 -> {"ok": true, "version": ...}
    GET  /api/usecases               -> name, description and JSON schema of the arguments
    POST /api/call/<name>  {kwargs}  -> {"result": ...}   (400 {"error": "..."} for player errors)

The app starts the server on 127.0.0.1 with a random port and a random token (header
``Authorization: Bearer <token>``), so other programs on the computer cannot use it. The
Docker variant serves the built frontend from the same server (``--static``).
"""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError, validate_call

from ap_planner import __version__, usecases

# Tauri (Windows/Linux and macOS) and the Vite dev server.
APP_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


def _schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON schema of a use case's arguments (for the frontend forms)."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        prop = TypeAdapter(annotation).json_schema()
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = jsonable_encoder(param.default)
        props[name] = prop
    return {"type": "object", "properties": props, "required": required}


def create_app(token: str | None = None, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="ap-planner", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=APP_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    callers = {name: validate_call(fn) for name, fn in usecases.REGISTRY.items()}

    @app.middleware("http")
    async def check_token(request: Request, call_next: Callable[..., Any]) -> Any:  # noqa: ANN401
        protected = token and request.url.path.startswith("/api/") and request.method != "OPTIONS"
        if protected and request.headers.get("authorization") != f"Bearer {token}":
            return JSONResponse({"error": "Nicht berechtigt."}, status_code=401)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/api/usecases")
    def list_usecases() -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": inspect.getdoc(fn) or "",
                "parameters": _schema(fn),
                "app_only": name in usecases.APP_ONLY,
            }
            for name, fn in usecases.REGISTRY.items()
        ]

    # Plain (sync) handler: FastAPI runs it in a worker thread, so slow use cases (solver,
    # Discord, Google login) never block the server.
    @app.post("/api/call/{name}")
    def call(name: str, kwargs: dict[str, Any] | None = None) -> JSONResponse:
        fn = callers.get(name)
        if fn is None:
            return JSONResponse({"error": f"Unbekannte Funktion: {name}"}, status_code=404)
        try:
            result = fn(**(kwargs or {}))
        except ValidationError as err:
            return JSONResponse(
                {"error": "Ungültige Eingabe.", "details": jsonable_encoder(err.errors())},
                status_code=422,
            )
        except usecases.EXPECTED_ERRORS as err:
            return JSONResponse({"error": str(err) or type(err).__name__}, status_code=400)
        return JSONResponse({"result": jsonable_encoder(result)})

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="app")
    return app
