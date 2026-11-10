from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app import limits
from app.auth import check_passphrase, require_session_token
from app.config import settings
from app.engine import EngineError
from app.rate_limit import KeyedLimiter, client_ip
from app.rooms import room_manager

# ~1 attempt per 6s/IP, small burst -- generous for a mistyped passphrase,
# far too slow to brute-force even a short one. Exists independently of
# nginx's own (tighter) limit in the public-deployment mode (see
# DEPLOYMENT.md) specifically so the plain LAN quick-start mode, which has
# no nginx in front of it at all, isn't left with zero protection on the
# one brute-forceable secret in this app.
_passphrase_limiter = KeyedLimiter(max_hits=10, window_seconds=60, name="passphrase")


def _enforce(limiter: KeyedLimiter, detail: str):
    """Build a FastAPI dependency that rate-limits by client IP.

    429s carry Retry-After so a client can back off by the real remaining
    window instead of guessing (and so they match what nginx returns once
    limit_req_status is set -- see deploy/nginx-chips.conf).
    """

    def dep(request: Request) -> None:
        key = client_ip(request)
        if not limiter.allow(key):
            raise HTTPException(
                status_code=429,
                detail=detail,
                headers={"Retry-After": str(limiter.retry_after(key))},
            )

    return dep


_global_dep = _enforce(limits.rest_global, "Too many requests, slow down")
_create_dep = _enforce(limits.create_room, "Too many rooms created, try again later")
_join_dep = _enforce(limits.join, "Too many join attempts, try again later")
_lookup_dep = _enforce(limits.lookup, "Too many requests, try again later")
_passphrase_dep = _enforce(_passphrase_limiter, "Too many attempts, try again later")

# Router-level dependency, so every current *and future* endpoint under /api
# gets a flood backstop without anyone having to remember to add one. The
# per-endpoint limiters below are the tight, purpose-specific layer on top.
router = APIRouter(dependencies=[Depends(_global_dep)])


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/auth/passphrase")
async def auth_passphrase(body: dict = Body(...), _rl: None = Depends(_passphrase_dep)):
    token = check_passphrase(body.get("passphrase", ""))
    return {"session_token": token}


@router.post("/rooms")
async def create_room(
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_create_dep),
):
    try:
        room, player = room_manager.create_room(
            display_name=body["display_name"],
            small_blind=int(body.get("small_blind", settings.default_small_blind)),
            big_blind=int(body.get("big_blind", settings.default_big_blind)),
            starting_stack=int(body.get("starting_stack", settings.default_starting_stack)),
            raise_presets=list(body.get("raise_presets", settings.default_raise_presets)),
            rotate_dealer=bool(body.get("rotate_dealer", False)),
        )
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/join")
async def join_room(
    code: str,
    request: Request,
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_join_dep),
):
    try:
        room, player = room_manager.join_room(code, display_name=body["display_name"])
    except EngineError as e:
        _penalize_failed_lookup(limits.join, request, e)
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/rejoin")
async def rejoin_room(
    code: str,
    request: Request,
    body: dict = Body(...),
    _session: str = Depends(require_session_token),
    _rl: None = Depends(_lookup_dep),
):
    try:
        room, player = room_manager.rejoin_room(code, player_token=body["player_token"])
    except EngineError as e:
        _penalize_failed_lookup(limits.lookup, request, e)
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id}


def _penalize_failed_lookup(limiter: KeyedLimiter, request: Request, e: EngineError) -> None:
    """Charge extra budget for an attempt that named a room that isn't there.

    Legitimate use hits this rarely (a mistyped code, or a room swept after a
    restart); code enumeration hits it on essentially every request. Making
    the failure cost several slots is what turns a 30/min allowance into ~5
    probes/min without ever throttling a real table.
    """
    if e.code in ("ROOM_NOT_FOUND", "PLAYER_NOT_FOUND"):
        limiter.penalize(client_ip(request), settings.failed_lookup_penalty)


def _engine_error_response(e: EngineError):
    from fastapi.responses import JSONResponse

    if e.code == "SERVER_AT_CAPACITY":
        return JSONResponse(
            status_code=503,
            content={"code": e.code, "message": e.message},
            headers={"Retry-After": "60"},
        )
    status = 404 if e.code in ("ROOM_NOT_FOUND", "PLAYER_NOT_FOUND") else 400
    return JSONResponse(status_code=status, content={"code": e.code, "message": e.message})
