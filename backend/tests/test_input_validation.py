"""Regressions for the input-validation holes found in the security audit.

See SECURITY-AUDIT.md findings C1 (NaN/float bet amounts) and M1
(unvalidated room config minting chips).
"""

import json
import math

import pytest
from fastapi.testclient import TestClient

from app.engine import EngineError
from app.engine.state_machine import apply_action, rebuy, start_new_hand
from app.main import app
from tests.helpers import make_room


# --- C1: a bet amount that is not a finite integer ---------------------------


@pytest.mark.parametrize(
    "amount",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        10.5,
        True,
        "20",
        None,
        [20],
        {"amount": 20},
    ],
    ids=["nan", "inf", "-inf", "fractional", "bool", "string", "none", "list", "dict"],
)
def test_non_integer_bet_amount_is_rejected(amount):
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    seat = room.hand.to_act_seat
    with pytest.raises(EngineError) as exc:
        apply_action(room, seat, "raise", amount)
    assert exc.value.code == "INVALID_AMOUNT"


def test_nan_bet_cannot_corrupt_stacks_or_pots():
    # The specific disaster this guards: min(nan, max_to) is nan and
    # `nan < min_to` is False, so a NaN sailed through the bound check,
    # poisoned every stack and pot, and then serialized as bare `NaN` --
    # which JSON.parse rejects, breaking every client in the room at once.
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    seat = room.hand.to_act_seat
    with pytest.raises(EngineError):
        apply_action(room, seat, "raise", float("nan"))

    for player in room.players.values():
        assert isinstance(player.stack, int)
        assert isinstance(player.contrib_street, int)
        assert isinstance(player.contrib_hand, int)
    total = sum(pot.amount for pot in room.hand.pots)
    assert isinstance(total, int) and not math.isnan(total)
    # And the whole state still round-trips through strict JSON.
    from app.rooms import serialize_room

    json.loads(json.dumps(serialize_room(room), allow_nan=False))


def test_integral_float_bet_is_accepted_and_narrowed():
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    seat = room.hand.to_act_seat
    apply_action(room, seat, "raise", 10.0)
    assert isinstance(room.players[seat].contrib_street, int)
    assert room.players[seat].contrib_street == 10


def test_rebuy_amount_must_be_a_finite_integer():
    room = make_room({1: 100, 2: 100})
    room.players[1].stack = 0
    with pytest.raises(EngineError) as exc:
        rebuy(room, 1, float("nan"))
    assert exc.value.code == "INVALID_AMOUNT"
    assert room.players[1].stack == 0


# --- M1: room config bounds --------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"small_blind": -5},
        {"small_blind": 0},
        {"big_blind": -2},
        {"big_blind": 0},
        {"starting_stack": -100},
        {"starting_stack": 0},
        {"small_blind": 10, "big_blind": 2},  # bb below sb
        {"starting_stack": 1, "big_blind": 50},  # stack below one bb
        {"small_blind": 10**12},
        {"raise_presets": []},
        {"raise_presets": [0]},
        {"raise_presets": [-1]},
        {"raise_presets": [1000]},
        {"raise_presets": [0.5] * 20},
    ],
)
def test_out_of_range_room_config_is_rejected(overrides):
    client = TestClient(app)
    body = {"display_name": "Ada", "small_blind": 1, "big_blind": 2, "starting_stack": 200, **overrides}
    r = client.post("/api/rooms", json=body)
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_CONFIG"


def test_negative_blind_cannot_mint_chips():
    # _post_blind does `actual = min(amount, stack); stack -= actual`, so a
    # negative blind used to *increase* the poster's stack.
    client = TestClient(app)
    r = client.post(
        "/api/rooms",
        json={"display_name": "Ada", "small_blind": -50, "big_blind": -50, "starting_stack": 200},
    )
    assert r.status_code == 400
    from app.rooms import room_manager

    assert room_manager.rooms == {}


def test_malformed_body_is_a_422_not_a_500():
    client = TestClient(app)
    # Missing display_name, then a non-string one, then an uncoercible int.
    assert client.post("/api/rooms", json={}).status_code == 422
    assert client.post("/api/rooms", json={"display_name": {"a": 1}}).status_code == 422
    assert client.post("/api/rooms", json={"display_name": "Ada", "small_blind": "abc"}).status_code == 422
    assert client.post("/api/rooms/000000/join", json={}).status_code == 422
    assert client.post("/api/rooms/000000/rejoin", json={}).status_code == 422


def test_non_ascii_player_token_does_not_500():
    # secrets.compare_digest raises TypeError on non-ASCII str, which used to
    # surface as a 500 instead of a plain not-found.
    client = TestClient(app)
    r = client.post("/api/rooms/000000/rejoin", json={"player_token": "tøken-ünicode"})
    assert r.status_code == 404
