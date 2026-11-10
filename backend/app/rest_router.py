from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import limits
from app.config import settings
from app.engine import EngineError
from app.rate_limit import KeyedLimiter, client_ip
from app.rooms import room_manager


# Typed request bodies rather than `body: dict = Body(...)`. The dicts meant
# a missing or wrong-typed field surfaced as an unhandled KeyError/
# ValueError/AttributeError -- an HTTP 500 with a traceback in the log for
# what is really a client mistake. These turn the same input into a 422.
# The engine-level checks in rooms.py stay as the authoritative ones: the
# WebSocket path has no pydantic in front of it.
class CreateRoomBody(BaseModel):
    display_name: str
    small_blind: int = settings.default_small_blind
    big_blind: int = settings.default_big_blind
    starting_stack: int = settings.default_starting_stack
    raise_presets: list[float] = Field(default_factory=lambda: list(settings.default_raise_presets))
    rotate_dealer: bool = False


class JoinRoomBody(BaseModel):
    display_name: str


class RejoinRoomBody(BaseModel):
    player_token: str


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

# Router-level dependency, so every current *and future* endpoint under /api
# gets a flood backstop without anyone having to remember to add one. The
# per-endpoint limiters below are the tight, purpose-specific layer on top.
router = APIRouter(dependencies=[Depends(_global_dep)])


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/rooms")
async def create_room(
    body: CreateRoomBody,
    _rl: None = Depends(_create_dep),
):
    try:
        room, player = room_manager.create_room(
            display_name=body.display_name,
            small_blind=body.small_blind,
            big_blind=body.big_blind,
            starting_stack=body.starting_stack,
            raise_presets=body.raise_presets,
            rotate_dealer=body.rotate_dealer,
        )
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/join")
async def join_room(
    code: str,
    request: Request,
    body: JoinRoomBody,
    _rl: None = Depends(_join_dep),
):
    try:
        room, player = room_manager.join_room(code, display_name=body.display_name)
    except EngineError as e:
        _penalize_failed_lookup(limits.join, request, e)
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/rejoin")
async def rejoin_room(
    code: str,
    request: Request,
    body: RejoinRoomBody,
    _rl: None = Depends(_lookup_dep),
):
    try:
        room, player = room_manager.rejoin_room(code, player_token=body.player_token)
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
