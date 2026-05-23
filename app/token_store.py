from __future__ import annotations

import hashlib
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

TOKEN_PREFIX = "pii_"
TOKEN_RANDOM_HEX_LEN = 40
MASTER_KEY_HEX_LEN = 32


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_or_generate_master_key() -> str:
    key = os.environ.get("PII_MASTER_KEY", "").strip()
    if key:
        return key
    generated = secrets.token_hex(MASTER_KEY_HEX_LEN // 2)
    os.environ["PII_MASTER_KEY"] = generated
    print(
        "[token_store] PII_MASTER_KEY not set — generated ephemeral master key: "
        f"{generated}",
        flush=True,
    )
    return generated


class TokenStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, dict] = {}
        self._hash_to_id: dict[str, str] = {}
        self.master_key: str = _load_or_generate_master_key()
        self.require_api_key: bool = (
            os.environ.get("REQUIRE_API_KEY", "false").lower() == "true"
        )

    def create_token(self) -> dict:
        raw = TOKEN_PREFIX + secrets.token_hex(TOKEN_RANDOM_HEX_LEN // 2)
        token_id = str(uuid.uuid4())
        token_hash = _hash_token(raw)
        created_at = _now_iso()
        prefix = raw[: len(TOKEN_PREFIX) + 2]

        with self._lock:
            self._tokens[token_id] = {
                "id": token_id,
                "hash": token_hash,
                "prefix": prefix,
                "created_at": created_at,
                "last_used": None,
            }
            self._hash_to_id[token_hash] = token_id

        return {"token": raw, "id": token_id, "created_at": created_at}

    def list_tokens(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": t["id"],
                    "prefix": t["prefix"],
                    "created_at": t["created_at"],
                    "last_used": t["last_used"],
                }
                for t in self._tokens.values()
            ]

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            entry = self._tokens.pop(token_id, None)
            if entry is None:
                return False
            self._hash_to_id.pop(entry["hash"], None)
            return True

    def verify_token(self, raw_token: Optional[str]) -> bool:
        if not raw_token:
            return False
        token_hash = _hash_token(raw_token)
        with self._lock:
            token_id = self._hash_to_id.get(token_hash)
            if not token_id:
                return False
            self._tokens[token_id]["last_used"] = _now_iso()
            return True

    def seed_token(self, raw_token: str) -> None:
        """Register a pre-existing raw token (e.g. from PII_INITIAL_TOKEN env).

        Idempotent: if the token hash already exists, this is a no-op.
        """
        token_hash = _hash_token(raw_token)
        with self._lock:
            if token_hash in self._hash_to_id:
                return  # already seeded
            token_id = str(uuid.uuid4())
            prefix = raw_token[: len(TOKEN_PREFIX) + 2]
            self._tokens[token_id] = {
                "id": token_id,
                "hash": token_hash,
                "prefix": prefix,
                "created_at": _now_iso(),
                "last_used": None,
            }
            self._hash_to_id[token_hash] = token_id
        print(f"[token_store] Seeded initial token ({prefix}...)", flush=True)

    def verify_master_key(self, raw_key: Optional[str]) -> bool:
        if not raw_key:
            return False
        return secrets.compare_digest(raw_key, self.master_key)


_store: TokenStore | None = None


def get_store() -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore()
    return _store
