from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.pii_engine import SUPPORTED_LANGUAGES, get_engine, warm_start
from app.token_store import get_store


class MaskRequest(BaseModel):
    text: str = Field(..., description="Text to mask")
    language: str = Field(default="en", description="Language code: en or es")
    return_entities: bool = Field(
        default=True,
        description=(
            "When true (default), return the detected entities including their "
            "original values and placeholder tokens so the caller can restore "
            "the PII. Set to false to receive only the masked text and avoid "
            "echoing PII back."
        ),
    )


class EntitySpan(BaseModel):
    text: str
    label: str
    token: str
    start: int
    end: int


class MaskResponse(BaseModel):
    masked: str
    entities: list[EntitySpan] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    models: list[str]


class TokenCreateResponse(BaseModel):
    token: str
    id: str
    created_at: str


class TokenInfo(BaseModel):
    id: str
    prefix: str
    created_at: str
    last_used: Optional[str] = None


class TokenListResponse(BaseModel):
    tokens: list[TokenInfo]


class RevokeResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = get_store()
    # Seed a pre-provisioned token so the container self-provisions on every restart.
    # PII_API_TOKEN is fetched from Infisical by entrypoint.sh and exported as env var.
    initial = os.environ.get("PII_API_TOKEN", "").strip()
    if initial:
        store.seed_token(initial)
    warm_start()
    yield


app = FastAPI(
    title="PII Masking Service",
    description="Masks PII in text using Microsoft Presidio before forwarding to LLMs.",
    version="1.0.0",
    lifespan=lifespan,
)


def require_api_key(
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    store = get_store()
    if not store.require_api_key:
        return
    # Prefer X-API-Key; fall back to Authorization: Bearer <token>
    token = x_api_key
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value
    if not store.verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def require_master_key(x_master_key: Optional[str] = Header(default=None)) -> None:
    store = get_store()
    if not store.verify_master_key(x_master_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Master-Key",
        )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", models=SUPPORTED_LANGUAGES)


@app.post("/mask", response_model=MaskResponse, dependencies=[Depends(require_api_key)])
def mask(req: MaskRequest) -> MaskResponse:
    try:
        result = get_engine().mask(req.text, language=req.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entities = result["entities"] if req.return_entities else []
    return MaskResponse(masked=result["masked"], entities=entities)


@app.post(
    "/tokens",
    response_model=TokenCreateResponse,
    dependencies=[Depends(require_master_key)],
)
def create_token() -> TokenCreateResponse:
    created = get_store().create_token()
    return TokenCreateResponse(**created)


@app.get(
    "/tokens",
    response_model=TokenListResponse,
    dependencies=[Depends(require_master_key)],
)
def list_tokens() -> TokenListResponse:
    return TokenListResponse(tokens=[TokenInfo(**t) for t in get_store().list_tokens()])


@app.delete(
    "/tokens/{token_id}",
    response_model=RevokeResponse,
    dependencies=[Depends(require_master_key)],
)
def revoke_token(token_id: str) -> RevokeResponse:
    if not get_store().revoke(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return RevokeResponse(status="revoked")
