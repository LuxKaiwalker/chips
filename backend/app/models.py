import time
from dataclasses import dataclass, field
from enum import Enum


class PlayerStatus(str, Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"
    SITTING_OUT = "sitting_out"
    BUSTED = "busted"


class RoomPhase(str, Enum):
    LOBBY = "lobby"
    IN_HAND = "in_hand"
    BETWEEN_HANDS = "between_hands"


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


# Number of community cards visible once a street is reached (for the dealing-stage banner).
STREET_CARD_COUNT = {
    Street.PREFLOP: 0,
    Street.FLOP: 3,
    Street.TURN: 4,
    Street.RIVER: 5,
    Street.SHOWDOWN: 5,
}


@dataclass
class Player:
    seat_id: int
    display_name: str
    stack: int
    status: PlayerStatus
    player_token: str = field(repr=False)
    connected: bool = True
    contrib_street: int = 0
    contrib_hand: int = 0
    is_button: bool = False
    disconnected_at: float | None = None
    joined_at: float = field(default_factory=time.time)
    # Self-requested, takes effect at the *next* start_new_hand() call --
    # never mutated mid-hand (would corrupt to_act_order/legal-action
    # logic for a player currently in a hand). Persists until the player
    # explicitly requests sitting back in.
    sit_out_next: bool = False


@dataclass
class RoomConfig:
    small_blind: int
    big_blind: int
    starting_stack: int
    raise_presets: list[float]
    blind_schedule: None = None  # extension point for future tournament mode; unused


@dataclass
class Pot:
    label: str
    amount: int
    eligible_seats: list[int]


@dataclass
class HandState:
    hand_number: int
    button_seat: int
    street: Street
    dealt_in_seats: list[int] = field(default_factory=list)
    current_bet: int = 0
    last_full_raise_increment: int = 0
    betting_reopened: bool = True
    capped_seats: set[int] = field(default_factory=set)
    to_act_seat: int | None = None
    to_act_order: list[int] = field(default_factory=list)
    pots: list[Pot] = field(default_factory=list)
    legal_actions: dict | None = None
    awaiting_runout_confirmation: bool = False
    action_log: list[str] = field(default_factory=list)
    last_result: dict | None = None  # set once a hand concludes, describing payouts
    concluded: bool = False


@dataclass
class Room:
    code: str
    config: RoomConfig
    host_seat_id: int
    phase: RoomPhase = RoomPhase.LOBBY
    players: dict[int, Player] = field(default_factory=dict)
    hand: HandState | None = None
    next_seat_id: int = 1
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    empty_since: float | None = None

    def touch(self) -> None:
        self.last_activity_at = time.time()
