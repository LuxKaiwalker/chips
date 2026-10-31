from fastapi import APIRouter, Body, Depends

from app.auth import check_passphrase, require_session_token
from app.config import settings
from app.engine import EngineError
from app.rooms import room_manager

router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/auth/passphrase")
async def auth_passphrase(body: dict = Body(...)):
    token = check_passphrase(body.get("passphrase", ""))
    return {"session_token": token}


@router.post("/rooms")
async def create_room(body: dict = Body(...), _session: str = Depends(require_session_token)):
    room, player = room_manager.create_room(
        display_name=body["display_name"],
        small_blind=int(body.get("small_blind", settings.default_small_blind)),
        big_blind=int(body.get("big_blind", settings.default_big_blind)),
        starting_stack=int(body.get("starting_stack", settings.default_starting_stack)),
        raise_presets=list(body.get("raise_presets", settings.default_raise_presets)),
    )
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/join")
async def join_room(code: str, body: dict = Body(...), _session: str = Depends(require_session_token)):
    try:
        room, player = room_manager.join_room(code, display_name=body["display_name"])
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id, "player_token": player.player_token}


@router.post("/rooms/{code}/rejoin")
async def rejoin_room(code: str, body: dict = Body(...), _session: str = Depends(require_session_token)):
    try:
        room, player = room_manager.rejoin_room(code, player_token=body["player_token"])
    except EngineError as e:
        return _engine_error_response(e)
    return {"room_code": room.code, "seat_id": player.seat_id}


def _engine_error_response(e: EngineError):
    from fastapi.responses import JSONResponse

    status = 404 if e.code in ("ROOM_NOT_FOUND", "PLAYER_NOT_FOUND") else 400
    return JSONResponse(status_code=status, content={"code": e.code, "message": e.message})
