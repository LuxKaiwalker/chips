from app.models import Player, Pot, PlayerStatus


def compute_pots(players: dict[int, Player]) -> list[Pot]:
    """Splits all chips committed this hand into a main pot plus a side pot per
    distinct all-in contribution tier. Folded players' chips stay dead in
    whichever pots they contributed to, without being added to eligible_seats.
    """
    contributors = {sid: p.contrib_hand for sid, p in players.items() if p.contrib_hand > 0}
    if not contributors:
        return []

    levels = sorted(set(contributors.values()))
    pots: list[Pot] = []
    prev_level = 0
    for level in levels:
        tier_amount = level - prev_level
        tier_contributors = [sid for sid, c in contributors.items() if c >= level]
        pot_amount = tier_amount * len(tier_contributors)
        eligible = [sid for sid in tier_contributors if players[sid].status != PlayerStatus.FOLDED]
        if pot_amount > 0:
            pots.append(Pot(label="", amount=pot_amount, eligible_seats=eligible))
        prev_level = level

    merged: list[Pot] = []
    for pot in pots:
        if merged and merged[-1].eligible_seats == pot.eligible_seats:
            merged[-1].amount += pot.amount
        else:
            merged.append(pot)

    for i, pot in enumerate(merged):
        pot.label = "Main Pot" if i == 0 else f"Side Pot {i}"

    return merged


def total_pot_amount(players: dict[int, Player]) -> int:
    return sum(p.contrib_hand for p in players.values())
