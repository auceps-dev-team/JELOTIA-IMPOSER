"""FastAPI activation endpoint.

    uvicorn activation_server.app:app --host 0.0.0.0 --port 8080

Configuration (env), so no secret is ever committed:
  JELOTIA_SIGNING_KEY_B64   the base64 private key directly (takes precedence), or
  JELOTIA_SIGNING_KEY_FILE  a path to it (default ~/Jelotia/license_signing_key.b64)
  JELOTIA_ACTIVATION_DB     token store path (default ~/Jelotia/activation.db)

The private key stays in this process only. The app never receives it — just the
signed license the endpoint returns.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from activation_server.issuer import activate
from activation_server.store import TokenStore


class ActivateRequest(BaseModel):
    purchase_token: str = Field(..., min_length=1)
    fingerprint: str = Field(..., min_length=1)
    app_version: str = ""


class ActivateResponse(BaseModel):
    license_key: str
    tier: str
    licensee: str
    reactivation: bool


def _load_private_key() -> str:
    inline = os.environ.get("JELOTIA_SIGNING_KEY_B64", "").strip()
    if inline:
        return inline
    path = Path(
        os.environ.get("JELOTIA_SIGNING_KEY_FILE")
        or (Path.home() / "Jelotia" / "license_signing_key.b64")
    )
    if not path.exists():
        raise RuntimeError(
            f"Clé de signature introuvable ({path}). Définissez "
            "JELOTIA_SIGNING_KEY_B64 ou JELOTIA_SIGNING_KEY_FILE."
        )
    return path.read_text(encoding="utf-8").strip()


def _default_db_path() -> str:
    return os.environ.get("JELOTIA_ACTIVATION_DB") or str(
        Path.home() / "Jelotia" / "activation.db"
    )


def create_app(
    store: Optional[TokenStore] = None,
    private_key_b64: Optional[str] = None,
) -> FastAPI:
    """Build the ASGI app. Tests inject `store` and `private_key_b64`; in
    production both are resolved from the environment on first use."""
    app = FastAPI(title="JELOTIA Activation", version="1.0")
    app.state.store = store
    app.state.private_key = private_key_b64

    def _store() -> TokenStore:
        if app.state.store is None:
            app.state.store = TokenStore(_default_db_path())
        return app.state.store

    def _key() -> str:
        if not app.state.private_key:
            app.state.private_key = _load_private_key()
        return app.state.private_key

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/activate", response_model=ActivateResponse)
    def activate_endpoint(req: ActivateRequest) -> ActivateResponse:
        result = activate(_store(), _key(), req.purchase_token, req.fingerprint)
        if not result.ok:
            raise HTTPException(status_code=400, detail=result.error)
        return ActivateResponse(
            license_key=result.license_key,
            tier=result.tier,
            licensee=result.licensee,
            reactivation=result.reactivation,
        )

    return app


# Module-level ASGI app for `uvicorn activation_server.app:app`.
app = create_app()
