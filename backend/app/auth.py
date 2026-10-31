import secrets
import time

from fastapi import Header, HTTPException

from app.config import settings

_session_tokens: dict[str, float] = {}


def check_passphrase(passphrase: str) -> str:
    if not secrets.compare_digest(passphrase, settings.passphrase):
        raise HTTPException(status_code=401, detail="Incorrect passphrase")
    token = secrets.token_urlsafe(24)
    _session_tokens[token] = time.time()
    return token


def _is_valid(token: str | None) -> bool:
    if not token:
        return False
    issued_at = _session_tokens.get(token)
    if issued_at is None:
        return False
    if time.time() - issued_at > settings.session_token_ttl_hours * 3600:
        del _session_tokens[token]
        return False
    return True


def require_session_token(x_session_token: str | None = Header(default=None)) -> str:
    if not _is_valid(x_session_token):
        raise HTTPException(status_code=401, detail="Missing or invalid session token")
    return x_session_token


def is_valid_session_token(token: str | None) -> bool:
    return _is_valid(token)
