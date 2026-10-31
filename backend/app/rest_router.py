from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.auth import check_passphrase, require_session_token
from app.config import settings
from app.engine import EngineError
from app.rate_limit import FixedWindowLimiter, client_ip
from app.rooms import room_manager

router = APIRouter()

# ~1 attempt per 6s/IP, small burst -- generous for a mistyped passphrase,
# far too slow to brute-force even a short one. Exists independently of
# nginx's own (tighter) limit in the public-deployment mode (see
# DEPLOYMENT.md) specifically so the plain LAN quick-start mode, which has
# no nginx in front of it at all, isn't left with zero protection on the
# one brute-forceable secret in this app.
_passphrase_limiter = FixedWindowLimiter(max_hits=10, window_seconds=60)
# Coarser general limit across the other REST endpoints -- not brute-force
# protection, just a guard against one client flooding this single-process
# backend with room create/join/rejoin spam.
_general_limiter = FixedWindowLimiter(max_hits=30, window_seconds=10)


def _enforce_passphrase_limit(request: Request) -> None:
    if not _passphrase_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")


def _enforce_general_limit(request: Request) -> None:
    if not _general_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests, slow down")


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/auth/passphrase")
async def auth_passphrase(body: dict = Body(...), _rl: None = Depends(_enforce_passphrase_limit)):
    token = check_passphrase(body.get("passphrase", ""))
    return {"session_token": token}


@router.post("/rooms")
async def create_room(
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_enforce_general_limit),
):
    room, player = room_manager.create_room(
        display_name=body["display_name"],
        small_blind=int(body.get("small_blind", settings.default_small_blind)),
        big_blind=int(body.get("big_blind", settings.default_big_blind)),
        starting_stack=int(body.get("starting_stack", settings.default_starting_stack)),
        raise_presets=list(body.get("raise_presets", settings.default_raise_presets)),
        rotate_dealer=bool(body.get("rotate_dealer", False)),
    )
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/join")
async def join_room(
    code: str,
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_enforce_general_limit),
):
    try:
        room, player = room_manager.join_room(code, display_name=body["display_name"])
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/rejoin")
async def rejoin_room(
    code: str,
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_enforce_general_limit),
):
    try:
        room, player = room_manager.rejoin_room(code, player_token=body["player_token"])
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id}


def _engine_error_response(e: EngineError):
    from fastapi.responses import JSONResponse

    status = 404 if e.code in ("ROOM_NOT_FOUND", "PLAYER_NOT_FOUND") else 400
    return JSONResponse(status_code=status, content={"code": e.code, "message": e.message})
