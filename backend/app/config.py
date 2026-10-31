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
    room_code_length: int = 4
    # Excludes 0/O/1/I to avoid ambiguous codes read aloud across a table.
    room_code_alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

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
