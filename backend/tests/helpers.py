from app.models import Player, PlayerStatus, Room, RoomConfig


def make_room(stacks: dict[int, int], small_blind: int = 1, big_blind: int = 2) -> Room:
    config = RoomConfig(
        small_blind=small_blind,
        big_blind=big_blind,
        starting_stack=max(stacks.values()),
        raise_presets=[0.5, 1.0],
    )
    room = Room(code="TEST", config=config, host_seat_id=min(stacks))
    for seat_id, stack in stacks.items():
        room.players[seat_id] = Player(
            seat_id=seat_id,
            display_name=f"P{seat_id}",
            stack=stack,
            status=PlayerStatus.ACTIVE,
            player_token=f"tok{seat_id}",
        )
    return room
