"""
KAZHUDHAI CLUB — game_engine/distributor.py
Card distribution logic adhering strictly to the official game rules.

Rules:
  1. Minimum 2 players, Maximum 7 players.
  2. Distribute cards equally among all players first (base share = total // num_players).
  3. Distribute remaining cards one by one (remainder = total % num_players).
  4. Start giving remaining cards from Player 1 (index 0).
  5. Continue in player order until all cards are distributed.
  6. Total cards distributed must equal total available cards in the deck.

Example:
  5 players and 3 decks = 154 cards.
  Base share = 154 // 5 = 30 cards per player.
  Remaining cards = 154 % 5 = 4 cards.
  Final distribution:
    - Player 1: 31 cards
    - Player 2: 31 cards
    - Player 3: 31 cards
    - Player 4: 31 cards
    - Player 5: 30 cards
"""
from __future__ import annotations
from game_engine.deck import expected_card_count, sort_hand


def calculate_expected_distribution(num_decks: int, num_players: int) -> list[int]:
    """
    Calculate and return the expected card count for each player (0..num_players-1).

    Example for 3 decks (154 cards) and 5 players:
      returns [31, 31, 31, 31, 30]
    """
    if num_players < 2 or num_players > 7:
        raise ValueError(f"num_players must be 2-7, got {num_players}")

    total = expected_card_count(num_decks)
    base = total // num_players
    remain = total % num_players

    counts = [base] * num_players
    for i in range(remain):
        counts[i] += 1

    return counts


def distribute(cards: list[dict], num_players: int, sort_hands: bool = False) -> list[list[dict]]:
    """
    Distribute cards from the shuffled deck among joined players according to the rules:
      1. Minimum 2 players, Maximum 7 players.
      2. Distribute cards as equally as possible (base share = total // num_players).
      3. Distribute remaining cards one by one starting from Player 1 (index 0) in player order.
      4. Preserves the random shuffled order during distribution without sorting.

    :param cards: List of card dicts (shuffled before distribution).
    :param num_players: Number of joined players (2 to 7).
    :param sort_hands: Default False. If False, preserves the exact random dealing order.
    :returns: List of hands (list of lists of cards), index 0 = Player 1.
    """
    if num_players < 2 or num_players > 7:
        raise ValueError(f"num_players must be 2-7, got {num_players}")

    total = len(cards)
    base = total // num_players
    remain = total % num_players

    hands: list[list[dict]] = [[] for _ in range(num_players)]

    # 1. Distribute base equal share
    # Each player receives 'base' cards
    card_idx = 0
    for _ in range(base):
        for p in range(num_players):
            hands[p].append(cards[card_idx])
            card_idx += 1

    # 2. Distribute remaining cards one by one starting from Player 1 (index 0)
    for p in range(remain):
        hands[p].append(cards[card_idx])
        card_idx += 1

    # Verify all cards in deck have been distributed
    assert card_idx == total, f"Expected to distribute {total} cards, distributed {card_idx}"
    distributed_total = sum(len(h) for h in hands)
    assert distributed_total == total, (
        f"Distribution integrity error: distributed {distributed_total} != deck {total}"
    )

    # Verify exact remainder distribution counts
    for p in range(num_players):
        expected_len = base + (1 if p < remain else 0)
        assert len(hands[p]) == expected_len, (
            f"Player {p + 1} expected {expected_len} cards, got {len(hands[p])}"
        )

    # 3. Optional sort hands by suit and rank for clear player visibility
    if sort_hands:
        hands = [sort_hand(h) for h in hands]

    return hands
