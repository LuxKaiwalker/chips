import secrets
import time

from app.config import settings
from app.engine import EngineError
from app.models import Player, PlayerStatus, Room, RoomConfig, RoomPhase, current_dealer_seat


def _validate_name(display_name: str) -> str:
    display_name = display_name.strip()
    if not display_name:
        raise EngineError("INVALID_NAME", "Name cannot be empty")
    if len(display_name) > 24:
        raise EngineError("INVALID_NAME", "Name is too long (max 24 characters)")
    return display_name


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def _generate_code(self) -> str:
        while True:
            code = "".join(secrets.choice(settings.room_code_alphabet) for _ in range(settings.room_code_length))
            if code not in self.rooms:
                return code

    def create_room(
        self,
        display_name: str,
        small_blind: int,
        big_blind: int,
        starting_stack: int,
        raise_presets: list[float],
        rotate_dealer: bool = False,
    ) -> tuple[Room, Player]:
        display_name = _validate_name(display_name)
        code = self._generate_code()
        config = RoomConfig(
            small_blind=small_blind,
            big_blind=big_blind,
            starting_stack=starting_stack,
            raise_presets=raise_presets,
            rotate_dealer=rotate_dealer,
        )
        room = Room(code=code, config=config, host_seat_id=1)
        player = Player(
            seat_id=1,
            display_name=display_name,
            stack=starting_stack,
            status=PlayerStatus.SITTING_OUT,
            player_token=secrets.token_urlsafe(16),
        )
        room.players[1] = player
        room.next_seat_id = 2
        self.rooms[code] = room
        return room, player

    def get_room(self, code: str) -> Room:
        room = self.rooms.get(code.upper())
        if room is None:
            raise EngineError("ROOM_NOT_FOUND", "No room with that code exists")
        return room

    def join_room(self, code: str, display_name: str) -> tuple[Room, Player]:
        display_name = _validate_name(display_name)
        room = self.get_room(code)
        if len(room.players) >= settings.max_seats:
            raise EngineError("ROOM_FULL", "This room is full")
        if any(p.display_name.casefold() == display_name.casefold() for p in room.players.values()):
            raise EngineError("NAME_TAKEN", f"{display_name!r} is already taken in this room")
        seat_id = room.next_seat_id
        room.next_seat_id += 1
        status = PlayerStatus.SITTING_OUT
        player = Player(
            seat_id=seat_id,
            display_name=display_name,
            stack=room.config.starting_stack,
            status=status,
            player_token=secrets.token_urlsafe(16),
        )
        room.players[seat_id] = player
        room.touch()
        return room, player

    def rejoin_room(self, code: str, player_token: str) -> tuple[Room, Player]:
        room = self.get_room(code)
        for player in room.players.values():
            if secrets.compare_digest(player.player_token, player_token):
                return room, player
        raise EngineError("PLAYER_NOT_FOUND", "That player token is not recognized in this room")

    def remove_stale_seat(self, room: Room, requester_seat_id: int, target_seat_id: int) -> None:
        if requester_seat_id != room.host_seat_id:
            raise EngineError("NOT_HOST", "Only the host can remove a seat")
        if room.phase == RoomPhase.IN_HAND:
            raise EngineError("ILLEGAL_ACTION", "Cannot remove a seat while a hand is in progress")
        target = room.players.get(target_seat_id)
        if target is None:
            raise EngineError("PLAYER_NOT_FOUND", "No such seat")
        if target.connected:
            raise EngineError("ILLEGAL_ACTION", "That player is currently connected")
        if target.disconnected_at is None or (time.time() - target.disconnected_at) < settings.stale_seat_min_disconnect_seconds:
            raise EngineError("ILLEGAL_ACTION", "That seat has not been disconnected long enough to remove")
        del room.players[target_seat_id]
        room.touch()

    def update_config(
        self,
        room: Room,
        requester_seat_id: int,
        small_blind: int,
        big_blind: int,
        starting_stack: int,
        raise_presets: list[float],
        rotate_dealer: bool = False,
    ) -> None:
        if requester_seat_id != room.host_seat_id:
            raise EngineError("NOT_HOST", "Only the host can edit room configuration")
        if room.phase != RoomPhase.LOBBY:
            raise EngineError("ILLEGAL_ACTION", "Configuration can only change before the first hand")
        room.config.small_blind = small_blind
        room.config.big_blind = big_blind
        room.config.starting_stack = starting_stack
        room.config.raise_presets = raise_presets
        room.config.rotate_dealer = rotate_dealer
        for player in room.players.values():
            player.stack = starting_stack
        room.touch()

    def delete_room(self, code: str) -> None:
        self.rooms.pop(code, None)


room_manager = RoomManager()


def serialize_room(room: Room) -> dict:
    return {
        "code": room.code,
        "phase": room.phase.value,
        "host_seat_id": room.host_seat_id,
        "current_dealer_seat": current_dealer_seat(room),
        "config": {
            "small_blind": room.config.small_blind,
            "big_blind": room.config.big_blind,
            "starting_stack": room.config.starting_stack,
            "raise_presets": room.config.raise_presets,
            "rotate_dealer": room.config.rotate_dealer,
        },
        "players": [
            {
                "seat_id": p.seat_id,
                "display_name": p.display_name,
                "stack": p.stack,
                "status": p.status.value,
                "connected": p.connected,
                "contrib_street": p.contrib_street,
                "contrib_hand": p.contrib_hand,
                "is_button": p.is_button,
                "sit_out_next": p.sit_out_next,
            }
            for p in sorted(room.players.values(), key=lambda p: p.seat_id)
        ],
        "hand": _serialize_hand(room.hand) if room.hand else None,
    }


def _serialize_hand(hand) -> dict:
    return {
        "hand_number": hand.hand_number,
        "button_seat": hand.button_seat,
        "street": hand.street.value,
        "current_bet": hand.current_bet,
        "to_act_seat": hand.to_act_seat,
        "pots": [
            {"label": pot.label, "amount": pot.amount, "eligible_seats": pot.eligible_seats} for pot in hand.pots
        ],
        "total_pot": sum(pot.amount for pot in hand.pots),
        "legal_actions": hand.legal_actions,
        "awaiting_runout_confirmation": hand.awaiting_runout_confirmation,
        "action_log": hand.action_log[-20:],
        "last_result": hand.last_result,
        "concluded": hand.concluded,
    }
