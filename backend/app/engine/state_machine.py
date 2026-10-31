import time

from app.engine import EngineError
from app.engine.pots import compute_pots
from app.engine.rules import compute_legal_actions
from app.models import HandState, Player, PlayerStatus, Pot, Room, RoomPhase, Street

_STREET_ORDER = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER, Street.SHOWDOWN]


def _next_street(street: Street) -> Street:
    return _STREET_ORDER[_STREET_ORDER.index(street) + 1]


def _seat_after(seats: list[int], seat: int) -> int:
    idx = seats.index(seat)
    return seats[(idx + 1) % len(seats)]


def _order_starting_after(seats: list[int], seat: int) -> list[int]:
    idx = seats.index(seat)
    return seats[idx + 1:] + seats[: idx + 1]


def _active_seats_in_order(order_full: list[int], players: dict[int, Player]) -> list[int]:
    return [s for s in order_full if players[s].status == PlayerStatus.ACTIVE]


def _non_folded_seats(room: Room) -> list[int]:
    return [sid for sid, p in room.players.items() if p.status != PlayerStatus.FOLDED]


def _recompute(room: Room) -> None:
    """Recompute derived fields (pots, legal_actions) after any mutation."""
    hand = room.hand
    if hand is None:
        return
    hand.pots = compute_pots(room.players)
    hand.legal_actions = compute_legal_actions(hand, room.players)


def start_new_hand(room: Room) -> None:
    if room.phase == RoomPhase.IN_HAND:
        raise EngineError("HAND_IN_PROGRESS", "A hand is already in progress")

    for p in room.players.values():
        if p.stack <= 0:
            p.status = PlayerStatus.BUSTED
        elif p.sit_out_next:
            p.status = PlayerStatus.SITTING_OUT
        else:
            p.status = PlayerStatus.ACTIVE
        p.contrib_street = 0
        p.contrib_hand = 0
        p.is_button = False

    dealt_in = sorted(sid for sid, p in room.players.items() if p.status == PlayerStatus.ACTIVE)
    if len(dealt_in) < 2:
        raise EngineError("NOT_ENOUGH_PLAYERS", "Need at least 2 players with chips to start a hand")

    if room.hand is None:
        button_seat = dealt_in[0]
    else:
        prev_button = room.hand.button_seat
        if prev_button in dealt_in:
            button_seat = _seat_after(dealt_in, prev_button)
        else:
            candidates = [s for s in dealt_in if s > prev_button] or dealt_in
            button_seat = candidates[0]

    room.players[button_seat].is_button = True

    if len(dealt_in) == 2:
        # Heads-up: the button IS the small blind and acts first preflop,
        # but last on every postflop street.
        sb_seat = button_seat
        bb_seat = _seat_after(dealt_in, button_seat)
    else:
        sb_seat = _seat_after(dealt_in, button_seat)
        bb_seat = _seat_after(dealt_in, sb_seat)

    hand_number = (room.hand.hand_number + 1) if room.hand else 1
    hand = HandState(
        hand_number=hand_number,
        button_seat=button_seat,
        street=Street.PREFLOP,
        dealt_in_seats=dealt_in,
        last_full_raise_increment=room.config.big_blind,
    )
    room.hand = hand

    _post_blind(room.players[sb_seat], room.config.small_blind)
    _post_blind(room.players[bb_seat], room.config.big_blind)
    hand.current_bet = room.players[bb_seat].contrib_street

    preflop_order_full = _order_starting_after(dealt_in, bb_seat)
    hand.to_act_order = _active_seats_in_order(preflop_order_full, room.players)
    hand.to_act_seat = hand.to_act_order[0] if hand.to_act_order else None

    room.phase = RoomPhase.IN_HAND
    hand.action_log.append(
        f"Hand #{hand_number}: button seat {button_seat}, blinds {room.config.small_blind}/{room.config.big_blind}"
    )

    if hand.to_act_seat is None:
        _advance_past_betting(room)
    else:
        _recompute(room)
    room.touch()


def _post_blind(player: Player, amount: int) -> None:
    actual = min(amount, player.stack)
    player.stack -= actual
    player.contrib_street += actual
    player.contrib_hand += actual
    if player.stack == 0:
        player.status = PlayerStatus.ALL_IN


def apply_action(room: Room, seat_id: int, action: str, amount: int | None = None) -> None:
    hand = room.hand
    if hand is None or room.phase != RoomPhase.IN_HAND:
        raise EngineError("NO_HAND_IN_PROGRESS", "No hand is currently in progress")
    if hand.to_act_seat != seat_id:
        raise EngineError("NOT_YOUR_TURN", "It is not your turn to act")

    player = room.players[seat_id]
    legal = compute_legal_actions(hand, room.players)

    if action == "fold":
        player.status = PlayerStatus.FOLDED
        hand.action_log.append(f"{player.display_name} folds")
        hand.to_act_order.pop(0)
        if len(_non_folded_seats(room)) == 1:
            _award_fold_out(room)
            room.touch()
            return

    elif action == "check":
        if not legal["can_check"]:
            raise EngineError("ILLEGAL_ACTION", "You cannot check")
        hand.action_log.append(f"{player.display_name} checks")
        hand.to_act_order.pop(0)

    elif action == "call":
        if not legal["can_call"]:
            raise EngineError("ILLEGAL_ACTION", "You cannot call")
        amt = legal["call_amount"]
        player.stack -= amt
        player.contrib_street += amt
        player.contrib_hand += amt
        if player.stack == 0:
            player.status = PlayerStatus.ALL_IN
        hand.action_log.append(f"{player.display_name} calls {amt}")
        hand.to_act_order.pop(0)

    elif action in ("bet", "raise"):
        if not legal["can_bet_or_raise"]:
            raise EngineError("ILLEGAL_ACTION", "You cannot bet or raise")
        if amount is None:
            raise EngineError("INVALID_AMOUNT", "An amount is required")
        min_to, max_to = legal["min_to"], legal["max_to"]
        to_amount = min(amount, max_to)
        if to_amount < min_to:
            raise EngineError("INVALID_AMOUNT", f"Amount must be between {min_to} and {max_to}")
        hand.to_act_order.pop(0)
        _apply_bet_or_raise(room, seat_id, to_amount)

    else:
        raise EngineError("UNKNOWN_ACTION", f"Unknown action {action!r}")

    hand.to_act_seat = hand.to_act_order[0] if hand.to_act_order else None
    if hand.to_act_seat is None:
        _advance_past_betting(room)
    else:
        _recompute(room)
    room.touch()


def _apply_bet_or_raise(room: Room, seat_id: int, to_amount: int) -> None:
    hand = room.hand
    player = room.players[seat_id]

    raise_increment = to_amount - hand.current_bet
    is_full_raise = raise_increment >= hand.last_full_raise_increment

    delta = to_amount - player.contrib_street
    player.stack -= delta
    player.contrib_street = to_amount
    player.contrib_hand += delta
    if player.stack == 0:
        player.status = PlayerStatus.ALL_IN

    hand.current_bet = to_amount
    verb = "bets" if raise_increment == to_amount else "raises to"
    hand.action_log.append(f"{player.display_name} {verb} {to_amount}")

    if is_full_raise:
        hand.last_full_raise_increment = raise_increment
        hand.capped_seats.clear()

    # Anchored at the raiser (not the button) so re-queued players resume in
    # the correct clockwise order continuing from whoever just acted.
    order_full = _order_starting_after(hand.dealt_in_seats, seat_id)
    currently_queued = set(hand.to_act_order)
    reappend = [
        s
        for s in order_full
        if s != seat_id and room.players[s].status == PlayerStatus.ACTIVE and s not in currently_queued
    ]
    for s in reappend:
        hand.to_act_order.append(s)
        if not is_full_raise:
            hand.capped_seats.add(s)


def _advance_past_betting(room: Room) -> None:
    """Called whenever the to-act queue empties: either open betting on the
    next street, or (if the street is fully decided / showdown-bound) wait
    for a manual runout confirmation instead."""
    hand = room.hand
    if hand.street == Street.RIVER:
        _go_to_showdown(room)
        return
    hand.street = _next_street(hand.street)
    _begin_street(room)


def advance_runout(room: Room, seat_id: int) -> None:
    hand = room.hand
    if hand is None or room.phase != RoomPhase.IN_HAND:
        raise EngineError("NO_HAND_IN_PROGRESS", "No hand is currently in progress")
    if not hand.awaiting_runout_confirmation:
        raise EngineError("ILLEGAL_ACTION", "Not awaiting a runout confirmation")
    if room.players[seat_id].status == PlayerStatus.FOLDED:
        raise EngineError("ILLEGAL_ACTION", "Folded players cannot advance the runout")

    hand.awaiting_runout_confirmation = False
    if hand.street == Street.RIVER:
        _go_to_showdown(room)
    else:
        hand.street = _next_street(hand.street)
        _begin_street(room)
    room.touch()


def _begin_street(room: Room) -> None:
    """Opens the given (already-advanced-to) street for betting, unless at
    most one player can still act — in which case no more betting is
    possible and we wait for a manual runout confirmation instead."""
    hand = room.hand
    if hand.street == Street.SHOWDOWN:
        _go_to_showdown(room)
        return

    for p in room.players.values():
        p.contrib_street = 0
    hand.current_bet = 0
    hand.last_full_raise_increment = room.config.big_blind
    hand.capped_seats.clear()
    hand.betting_reopened = True

    live_actable = [sid for sid, p in room.players.items() if p.status == PlayerStatus.ACTIVE]
    if len(live_actable) <= 1:
        hand.to_act_order = []
        hand.to_act_seat = None
        hand.awaiting_runout_confirmation = True
        _recompute(room)
        return

    order_full = _order_starting_after(hand.dealt_in_seats, hand.button_seat)
    hand.to_act_order = _active_seats_in_order(order_full, room.players)
    hand.to_act_seat = hand.to_act_order[0] if hand.to_act_order else None
    _recompute(room)


def _go_to_showdown(room: Room) -> None:
    hand = room.hand
    hand.street = Street.SHOWDOWN
    hand.to_act_seat = None
    hand.to_act_order = []
    hand.awaiting_runout_confirmation = False
    _recompute(room)


def _winner_order(room: Room, winner_seats: list[int]) -> list[int]:
    order_full = _order_starting_after(room.hand.dealt_in_seats, room.hand.button_seat)
    return sorted(winner_seats, key=order_full.index)


def _award_fold_out(room: Room) -> None:
    hand = room.hand
    survivor = _non_folded_seats(room)[0]
    pots = compute_pots(room.players)
    payouts: dict[int, int] = {survivor: 0}
    for pot in pots:
        payouts[survivor] += pot.amount
        room.players[survivor].stack += pot.amount

    hand.pots = pots
    hand.to_act_seat = None
    hand.to_act_order = []
    hand.awaiting_runout_confirmation = False
    hand.legal_actions = None
    hand.concluded = True
    hand.last_result = {"reason": "fold_out", "payouts": payouts}
    room.phase = RoomPhase.BETWEEN_HANDS


def declare_winners(room: Room, seat_id: int, assignments: list[dict]) -> None:
    hand = room.hand
    if hand is None or hand.street != Street.SHOWDOWN:
        raise EngineError("ILLEGAL_ACTION", "No showdown is in progress")
    if seat_id != room.host_seat_id:
        raise EngineError("NOT_HOST", "Only the host can declare the winner")
    if room.players[seat_id].status == PlayerStatus.FOLDED:
        raise EngineError("ILLEGAL_ACTION", "Folded players cannot declare winners")

    pots = hand.pots
    covered: set[int] = set()
    for a in assignments:
        pot_index = a.get("pot_index")
        winner_seats = a.get("winner_seats") or []
        if pot_index is None or not (0 <= pot_index < len(pots)):
            raise EngineError("INVALID_AMOUNT", f"Invalid pot_index {pot_index!r}")
        if pot_index in covered:
            raise EngineError("ILLEGAL_ACTION", f"Pot {pot_index} assigned more than once")
        if not winner_seats:
            raise EngineError("ILLEGAL_ACTION", f"Pot {pot_index} needs at least one winner")
        pot = pots[pot_index]
        for ws in winner_seats:
            if ws not in pot.eligible_seats:
                raise EngineError("ILLEGAL_ACTION", f"Seat {ws} is not eligible for pot {pot_index}")
        covered.add(pot_index)

    if covered != set(range(len(pots))):
        raise EngineError("NOT_ALL_POTS_ASSIGNED", "Every pot must be assigned a winner")

    payouts: dict[int, int] = {}
    for a in assignments:
        pot = pots[a["pot_index"]]
        winners = _winner_order(room, a["winner_seats"])
        share = pot.amount // len(winners)
        remainder = pot.amount % len(winners)
        for i, w in enumerate(winners):
            amt = share + (1 if i < remainder else 0)
            room.players[w].stack += amt
            payouts[w] = payouts.get(w, 0) + amt

    hand.to_act_seat = None
    hand.legal_actions = None
    hand.concluded = True
    hand.last_result = {"reason": "showdown", "payouts": payouts}
    room.phase = RoomPhase.BETWEEN_HANDS
    room.touch()


def rebuy(room: Room, seat_id: int, amount: int) -> None:
    if amount <= 0:
        raise EngineError("INVALID_AMOUNT", "Rebuy amount must be positive")
    player = room.players[seat_id]
    if player.stack != 0:
        raise EngineError("ILLEGAL_ACTION", "Can only rebuy when your stack is 0")
    if room.phase == RoomPhase.IN_HAND:
        raise EngineError("ILLEGAL_ACTION", "Can only rebuy between hands")
    player.stack = amount
    player.status = PlayerStatus.SITTING_OUT
    player.sit_out_next = False  # rebuying implies wanting back in
    room.touch()


def toggle_sit_out(room: Room, seat_id: int) -> None:
    """Self-service, takes effect at the next hand -- never touches the
    player's status mid-hand (see Player.sit_out_next's docstring)."""
    player = room.players[seat_id]
    player.sit_out_next = not player.sit_out_next
    room.touch()
