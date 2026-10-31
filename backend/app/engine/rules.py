from app.models import HandState, Player


def compute_legal_actions(hand: HandState, players: dict[int, Player]) -> dict | None:
    """Authoritative legal-action bounds for whoever's turn it currently is.

    `min_to`/`max_to` are TOTAL chips the player will have contributed this
    street if they bet/raise to that amount (not the incremental raise size).
    """
    seat = hand.to_act_seat
    if seat is None:
        return None
    player = players[seat]
    full_stack_to = player.contrib_street + player.stack
    owed = hand.current_bet - player.contrib_street

    result = {
        "seat_id": seat,
        "can_fold": True,
        "can_check": owed <= 0,
        "can_call": owed > 0,
        "call_amount": max(0, min(owed, player.stack)),
        "can_bet_or_raise": False,
        "action_label": "bet" if hand.current_bet == 0 else "raise",
        "min_to": None,
        "max_to": None,
    }

    if player.stack <= 0:
        return result

    if hand.current_bet == 0:
        result["min_to"] = min(hand.last_full_raise_increment, full_stack_to)
        result["max_to"] = full_stack_to
        result["can_bet_or_raise"] = full_stack_to > 0
    elif seat not in hand.capped_seats:
        raw_min_to = hand.current_bet + hand.last_full_raise_increment
        result["min_to"] = min(raw_min_to, full_stack_to)
        result["max_to"] = full_stack_to
        result["can_bet_or_raise"] = full_stack_to > hand.current_bet

    return result
