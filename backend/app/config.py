import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


class Settings:
    passphrase: str = os.environ.get("CHIPS_PASSPHRASE", "pokernight")
    passphrase_is_default: bool = "CHIPS_PASSPHRASE" not in os.environ

    session_token_ttl_hours: int = _env_int("SESSION_TOKEN_TTL_HOURS", 24)

    max_seats: int = _env_int("MAX_SEATS", 10)
    # Digits only, 6 long -- easier to read aloud/type on a phone keypad
    # than a mixed alphanumeric code, at the cost of a smaller code space
    # (1,000,000 possibilities vs. 4 chars from a 32-symbol alphabet,
    # ~1.05M -- about the same, just all-numeric instead of mixed).
    room_code_length: int = 6
    room_code_alphabet: str = "0123456789"

    # Hard ceiling on resident rooms. Bounds memory against a room-creation
    # flood, and keeps RoomManager._generate_code()'s retry loop from
    # spinning as the 10^6 code space fills up.
    max_rooms: int = _env_int("MAX_ROOMS", 200)
    max_ws_connections_per_ip: int = _env_int("MAX_WS_CONNECTIONS_PER_IP", 20)
    # uvicorn's own ws_max_size defaults to 16 MiB and nginx's
    # client_max_body_size does not apply to WebSocket frames, so without
    # this a single message can force a 16 MiB JSON parse -- a CPU/alloc DoS
    # that no count-based limiter catches. run.sh and run-prod.sh also pass
    # --ws-max-size; this is the app-level backstop.
    ws_max_message_bytes: int = _env_int("WS_MAX_MESSAGE_BYTES", 8192)

    # Rate limits. Sized for the PUBLIC deployment, where the whole table
    # sits behind one NAT address and CF-Connecting-IP collapses every
    # player into a single key -- anything sized per-player breaks a real
    # game night. See backend/app/limits.py for the per-limiter rationale.
    rl_rest_global_max: int = _env_int("RL_REST_GLOBAL_MAX", 120)
    rl_create_max: int = _env_int("RL_CREATE_MAX", 5)
    rl_join_max: int = _env_int("RL_JOIN_MAX", 30)
    rl_lookup_max: int = _env_int("RL_LOOKUP_MAX", 90)
    rl_ws_connect_max: int = _env_int("RL_WS_CONNECT_MAX", 30)
    rl_ws_message_max: int = _env_int("RL_WS_MESSAGE_MAX", 15)
    rl_ws_message_hard_max: int = _env_int("RL_WS_MESSAGE_HARD_MAX", 60)
    # A failed room lookup costs this many slots instead of one, so probing
    # for live room codes is far more expensive than legitimate use.
    failed_lookup_penalty: int = _env_int("FAILED_LOOKUP_PENALTY", 5)

    cleanup_sweep_interval_seconds: int = _env_int("CLEANUP_SWEEP_INTERVAL_SECONDS", 60)
    room_empty_grace_seconds: int = _env_int("ROOM_EMPTY_GRACE_SECONDS", 600)
    room_idle_timeout_seconds: int = _env_int("ROOM_IDLE_TIMEOUT_SECONDS", 14400)
    stale_seat_min_disconnect_seconds: int = _env_int("STALE_SEAT_MIN_DISCONNECT_SECONDS", 300)

    default_small_blind: int = 1
    default_big_blind: int = 2
    default_starting_stack: int = 200
    default_raise_presets: list = [0.33, 0.5, 0.75, 1.0]

    static_dir: Path = Path(__file__).resolve().parent / "static"


settings = Settings()
