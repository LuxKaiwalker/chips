import pytest

from app.engine import EngineError
from app.engine.state_machine import advance_runout, apply_action, declare_winners, start_new_hand, toggle_sit_out
from app.models import PlayerStatus, RoomPhase, Street
from tests.helpers import make_room


def test_button_rotation_3plus_and_blinds():
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    assert room.hand.button_seat == 1
    # sb=2, bb=3, utg=1 acts first preflop
    assert room.players[2].contrib_street == 1
    assert room.players[3].contrib_street == 2
    assert room.hand.to_act_seat == 1

    apply_action(room, 1, "call")
    apply_action(room, 2, "call")
    apply_action(room, 3, "check")
    assert room.hand.street == Street.FLOP
    # postflop starts left of button (button=1) -> seat 2 first
    assert room.hand.to_act_seat == 2

    start_new_hand_from_between(room)


def start_new_hand_from_between(room):
    # finish the hand cheaply by folding everyone but one, then start again
    while room.phase == RoomPhase.IN_HAND:
        seat = room.hand.to_act_seat
        apply_action(room, seat, "fold")
    start_new_hand(room)
    assert room.hand.button_seat == 2  # rotated from 1 -> 2


def test_heads_up_button_rules():
    room = make_room({1: 100, 2: 100})
    start_new_hand(room)
    assert room.hand.button_seat == 1
    # heads-up: button posts SB and acts first preflop
    assert room.players[1].contrib_street == 1
    assert room.players[2].contrib_street == 2
    assert room.hand.to_act_seat == 1

    apply_action(room, 1, "call")
    apply_action(room, 2, "check")
    assert room.hand.street == Street.FLOP
    # postflop: bb (seat 2) acts first, button last
    assert room.hand.to_act_seat == 2


def test_not_your_turn_rejected():
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    with pytest.raises(EngineError) as exc:
        apply_action(room, 2, "call")
    assert exc.value.code == "NOT_YOUR_TURN"


def test_min_raise_and_short_allin_caps_already_acted_players():
    room = make_room({1: 100, 2: 100, 3: 15, 4: 100})
    start_new_hand(room)
    # button=1, sb=2(1), bb=3(2), preflop order: utg=4, then 1, 2, 3
    assert room.hand.to_act_seat == 4
    apply_action(room, 4, "raise", 10)  # full raise to 10 (increment 8 >= bb 2)
    assert room.hand.last_full_raise_increment == 8
    assert room.hand.to_act_seat == 1
    apply_action(room, 1, "call")
    assert room.hand.to_act_seat == 2
    apply_action(room, 2, "call")
    assert room.hand.to_act_seat == 3
    # seat 3 only has 15 total stack, all-in for 15 is a short raise (increment 5 < 8)
    apply_action(room, 3, "raise", 15)
    assert room.players[3].status == PlayerStatus.ALL_IN
    assert room.hand.betting_reopened is False or 3 not in room.hand.capped_seats
    # seats 4, 1, 2 already acted and must be re-queued, capped from raising
    assert set(room.hand.to_act_order) == {4, 1, 2}
    assert room.hand.capped_seats == {4, 1, 2}

    legal_4 = None
    # simulate seat 4's turn
    from app.engine.rules import compute_legal_actions

    legal = compute_legal_actions(room.hand, room.players)
    assert legal["seat_id"] == 4
    assert legal["can_bet_or_raise"] is False
    assert legal["can_call"] is True


def test_full_raise_clears_caps():
    # 5-handed so a short all-in happens early, leaving later players "fresh"
    # (never having acted) and able to fully reopen the betting afterward.
    room = make_room({1: 300, 2: 300, 3: 300, 4: 300, 5: 15})
    start_new_hand(room)
    # button=1, sb=2, bb=3, order: utg=4, 5, 1, 2, 3(bb, last)
    assert room.hand.to_act_seat == 4
    apply_action(room, 4, "raise", 10)  # full raise (increment 8 >= bb 2)
    assert room.hand.to_act_seat == 5
    apply_action(room, 5, "raise", 15)  # short all-in (increment 5 < 8); only seat 4 already acted
    assert room.players[5].status == PlayerStatus.ALL_IN
    assert room.hand.capped_seats == {4}
    assert room.hand.to_act_seat == 1  # fresh player, unaffected by the cap
    apply_action(room, 1, "raise", 25)  # full raise (increment 10 >= 8) reopens betting for everyone
    assert room.hand.capped_seats == set()
    assert 4 in room.hand.to_act_order


def test_side_pots_three_way_allin():
    room = make_room({1: 50, 2: 20, 3: 100})
    start_new_hand(room)
    # button=1, sb=2(1->19 left), bb=3(2->98 left), preflop order utg=1 first
    assert room.hand.to_act_seat == 1
    apply_action(room, 1, "raise", 50)  # seat1 all-in for 50
    assert room.players[1].status == PlayerStatus.ALL_IN
    apply_action(room, 2, "call")  # seat2 can only call all-in for 20 (less than the 50 bet)
    assert room.players[2].status == PlayerStatus.ALL_IN
    apply_action(room, 3, "call")  # seat3 calls up to 50 total

    # Only seat 3 has stack left (50) but no one to act against (1,2 all-in) -> awaiting runout
    assert room.hand.awaiting_runout_confirmation is True
    assert room.hand.street == Street.FLOP

    pots = room.hand.pots
    assert len(pots) == 2
    main, side = pots
    assert main.label == "Main Pot"
    assert main.amount == 60  # 20*3
    assert set(main.eligible_seats) == {1, 2, 3}
    assert side.amount == 60  # (50-20)*2
    assert set(side.eligible_seats) == {1, 3}

    # run out remaining streets
    advance_runout(room, 3)
    assert room.hand.street == Street.TURN
    advance_runout(room, 3)
    assert room.hand.street == Street.RIVER
    advance_runout(room, 3)
    assert room.hand.street == Street.SHOWDOWN

    declare_winners(room, 1, [  # seat 1 is host (make_room's host_seat_id = min seat)
        {"pot_index": 0, "winner_seats": [3]},
        {"pot_index": 1, "winner_seats": [3]},
    ])
    assert room.phase == RoomPhase.BETWEEN_HANDS
    assert room.players[3].stack == 100 - 50 + 120  # started 100, put in 50, won both pots (120)


def test_sit_out_excludes_from_next_hand_but_not_current_one():
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    # seat 2 requests to sit out mid-hand -- must NOT disturb the hand in progress
    toggle_sit_out(room, 2)
    assert room.players[2].sit_out_next is True
    assert room.players[2].status == PlayerStatus.ACTIVE  # unchanged mid-hand

    # finish the hand normally (everyone checks/calls through)
    apply_action(room, 1, "call")
    apply_action(room, 2, "call")
    apply_action(room, 3, "check")
    check_through_to_showdown(room)
    declare_winners(room, 1, [{"pot_index": 0, "winner_seats": [1]}])

    # next hand: seat 2 should be sitting out, not dealt in
    start_new_hand(room)
    assert room.players[2].status == PlayerStatus.SITTING_OUT
    assert 2 not in room.hand.dealt_in_seats

    # toggling back takes effect on the hand after that
    toggle_sit_out(room, 2)
    assert room.players[2].sit_out_next is False
    # finish this hand (2-way, seats 1 and 3) and start the next
    while room.phase == RoomPhase.IN_HAND:
        apply_action(room, room.hand.to_act_seat, "fold")
    start_new_hand(room)
    assert room.players[2].status == PlayerStatus.ACTIVE
    assert 2 in room.hand.dealt_in_seats


def test_fold_out_auto_awards_without_showdown():
    room = make_room({1: 100, 2: 100, 3: 100})
    start_new_hand(room)
    apply_action(room, 1, "fold")
    apply_action(room, 2, "fold")
    assert room.phase == RoomPhase.BETWEEN_HANDS
    assert room.hand.last_result["reason"] == "fold_out"
    assert room.players[3].stack == 101  # kept own bb(2) back plus seat2's sb(1)


def test_declare_winners_requires_host():
    room = make_room({1: 50, 2: 50, 3: 50})
    start_new_hand(room)
    apply_action(room, 1, "call")
    apply_action(room, 2, "call")
    apply_action(room, 3, "check")
    check_through_to_showdown(room)
    with pytest.raises(EngineError) as exc:
        declare_winners(room, 2, [{"pot_index": 0, "winner_seats": [2]}])  # seat 2 is not host
    assert exc.value.code == "NOT_HOST"
    # host (seat 1) can still declare
    declare_winners(room, 1, [{"pot_index": 0, "winner_seats": [2]}])
    assert room.phase == RoomPhase.BETWEEN_HANDS


def test_full_hand_runs_to_showdown_via_checks():
    room = make_room({1: 50, 2: 50, 3: 50})
    start_new_hand(room)
    apply_action(room, 1, "call")
    apply_action(room, 2, "call")
    apply_action(room, 3, "check")
    check_through_to_showdown(room)
    assert room.hand.street == Street.SHOWDOWN
    assert room.hand.pots[0].amount == 6
    declare_winners(room, 1, [{"pot_index": 0, "winner_seats": [2, 3]}])
    assert room.players[2].stack + room.players[3].stack == (50 - 2) * 2 + 6


def test_odd_chip_distribution_order():
    from app.engine.pots import compute_pots

    room = make_room({1: 50, 2: 50, 3: 50})
    start_new_hand(room)
    for seat_id in (1, 2, 3):
        p = room.players[seat_id]
        p.contrib_hand = 3
        p.stack = 47
    room.hand.street = Street.SHOWDOWN
    room.hand.pots = compute_pots(room.players)
    assert len(room.hand.pots) == 1
    assert room.hand.pots[0].amount == 9
    declare_winners(room, 1, [{"pot_index": 0, "winner_seats": [1, 2]}])
    # order starting after button(1): seat2, seat3, seat1 -> among winners {1,2}, seat2 is first -> gets odd chip
    assert room.players[2].stack == 47 + 5
    assert room.players[1].stack == 47 + 4


def check_through_to_showdown(room):
    while room.hand.street != Street.SHOWDOWN:
        if room.hand.awaiting_runout_confirmation:
            any_seat = next(iter(room.players))
            advance_runout(room, any_seat)
        elif room.hand.to_act_seat is not None:
            apply_action(room, room.hand.to_act_seat, "check")
        else:
            raise RuntimeError("stuck: no to_act_seat and not awaiting runout")
