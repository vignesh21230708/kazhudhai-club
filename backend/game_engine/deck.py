"""
KAZHUDHAI CLUB — game_engine/deck.py
Deck creation, shuffling, and A♠ deduplication.

Exact Specifications:
  - Number of decks: 1 to 5
  - 52 standard cards per deck (no jokers)
  - Retain exactly ONE Ace of Spades (A♠) across ALL selected decks
  - Remove all additional A♠ cards
  - Retain every other card, including duplicates from multiple decks
  - Formula: Total cards = (52 × N) − (N − 1)
      Decks | Total cards
      1     | 52
      2     | 103
      3     | 154
      4     | 205
      5     | 256
  - Every physical card receives a unique internal ID (UUID4)
  - Card ranking: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2
"""
from __future__ import annotations
import random
import secrets
import uuid

# Tracks the last match's shuffled card sequence to guarantee no order reuse
_last_shuffled_order: tuple[str, ...] | None = None

RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS = ['S', 'H', 'D', 'C']  # Spades, Hearts, Diamonds, Clubs

# Rank numerical values: '2'=0, '3'=1, ..., 'K'=11, 'A'=12
RANK_ORDER: dict[str, int] = {r: i for i, r in enumerate(RANKS)}

# Display order for suits in a player's hand (Spades, Hearts, Diamonds, Clubs)
SUIT_ORDER: dict[str, int] = {'S': 0, 'H': 1, 'D': 2, 'C': 3}

# Suit symbols
SUIT_SYMBOLS: dict[str, str] = {'S': '♠', 'H': '♥', 'D': '♦', 'C': '♣'}


def expected_card_count(num_decks: int) -> int:
    """Return the exact total number of cards for N decks according to rule."""
    if num_decks < 1 or num_decks > 5:
        raise ValueError(f"num_decks must be 1-5, got {num_decks}")
    return 52 * num_decks - (num_decks - 1)


def build_deck(num_decks: int, shuffle: bool = True, seed: int | None = None) -> list[dict]:
    """
    Build and return a deck of unique physical cards adhering to all Kazhudhai Club rules:

    1. Each deck has 52 standard cards (no jokers).
    2. Exactly ONE Ace of Spades (A♠) is retained across all decks.
    3. All additional A♠ cards are removed.
    4. All other cards (including duplicates from multiple decks) are retained.
    5. Each card receives a unique internal string ID.
    6. Cards are shuffled using Fisher-Yates (random.shuffle).

    Total cards = (52 × num_decks) − (num_decks − 1)
    """
    if num_decks < 1 or num_decks > 5:
        raise ValueError(f"num_decks must be 1-5, got {num_decks}")

    cards: list[dict] = []
    ace_spades_retained = False

    for deck_idx in range(num_decks):
        for suit in SUITS:
            for rank in RANKS:
                is_ace_spades = (rank == 'A' and suit == 'S')

                # A♠ Rule: Retain exactly ONE A♠ across all decks; remove duplicates
                if is_ace_spades:
                    if ace_spades_retained:
                        continue  # Remove duplicate A♠
                    ace_spades_retained = True

                cards.append({
                    'id':         str(uuid.uuid4()),
                    'rank':       rank,
                    'suit':       suit,
                    'deck_index': deck_idx,
                })

    expected = expected_card_count(num_decks)
    assert len(cards) == expected, (
        f"Deck size mismatch: expected {expected} for {num_decks} decks, got {len(cards)}"
    )

    # Validate that exactly one A♠ exists
    aces_of_spades = [c for c in cards if is_ace_of_spades(c)]
    assert len(aces_of_spades) == 1, (
        f"Expected exactly 1 A♠, found {len(aces_of_spades)}"
    )

    # Validate unique IDs
    ids = {c['id'] for c in cards}
    assert len(ids) == len(cards), "All physical cards must have unique internal IDs"

    if shuffle:
        cards = shuffle_deck(cards, seed=seed)

    return cards


def shuffle_deck(cards: list[dict], seed: int | None = None) -> list[dict]:
    """
    Shuffle the ENTIRE deck randomly before dealing any cards.
    Uses an unbiased Fisher-Yates (Knuth) in-place shuffle algorithm backed by
    Python's cryptographically secure random number generator (secrets.randbelow)
    when seed is None.

    Fisher-Yates Shuffle Algorithm:
      For i from len(cards) - 1 down to 1:
        j = randbelow(i + 1)  # uniform integer 0 <= j <= i
        swap cards[i], cards[j]

    Guarantees:
      1. Every permutation of the entire deck has an exactly equal (1/n!) probability.
      2. Card count is strictly conserved.
      3. Card physical UUID set is strictly conserved (no cards lost or duplicated).
      4. Shuffled deck order is verified to differ from the pre-shuffle factory order.
      5. Shuffled deck order is freshly generated and never reused from the previous match.
    """
    global _last_shuffled_order
    n = len(cards)
    if n <= 1:
        return cards

    before_ids = [c['id'] for c in cards]

    if seed is not None:
        # Deterministic Fisher-Yates shuffle strictly for legacy unit tests with fixed seed
        rng = random.Random(seed)
        for i in range(n - 1, 0, -1):
            j = rng.randint(0, i)
            cards[i], cards[j] = cards[j], cards[i]
    else:
        # Unbiased Fisher-Yates using cryptographically secure random number generator (CSPRNG)
        for i in range(n - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            cards[i], cards[j] = cards[j], cards[i]

    after_ids = [c['id'] for c in cards]

    # Verify integrity and order randomization
    assert len(after_ids) == len(before_ids), "Card count must be preserved during shuffle"
    assert set(after_ids) == set(before_ids), "All physical cards must be preserved during shuffle"
    if n > 10:
        # A full deck of 52-256 cards should never remain in identical order after random shuffle
        assert after_ids != before_ids, "Shuffled deck order must differ from pre-shuffle order"

        # Verify deck order is never reused from previous match
        card_sig = tuple(f"{c['rank']}{c['suit']}" for c in cards)
        if _last_shuffled_order is not None and seed is None:
            assert card_sig != _last_shuffled_order, "Shuffled deck order must never be reused from previous match"
        _last_shuffled_order = card_sig

    return cards


def get_last_shuffled_order() -> tuple[str, ...] | None:
    """Return the card signature sequence of the most recently shuffled match."""
    return _last_shuffled_order


def reset_shuffle_history() -> None:
    """Reset shuffle history tracking (useful in isolated tests)."""
    global _last_shuffled_order
    _last_shuffled_order = None


def is_ace_of_spades(card: dict) -> bool:
    """Return True if the card is the Ace of Spades (A♠)."""
    return card['rank'] == 'A' and card['suit'] == 'S'


def find_ace_of_spades(cards: list[dict]) -> dict | None:
    """Return the A♠ card object from a list of cards, or None if not present."""
    for c in cards:
        if is_ace_of_spades(c):
            return c
    return None


def compare_ranks(rank_a: str, rank_b: str) -> int:
    """
    Compare two card ranks based on the hierarchy:
    A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2.

    Returns:
      positive int if rank_a > rank_b
      negative int if rank_a < rank_b
      0 if rank_a == rank_b
    """
    return RANK_ORDER[rank_a] - RANK_ORDER[rank_b]


def sort_hand(cards: list[dict]) -> list[dict]:
    """
    Sort a player's hand cleanly:
    First by Suit (♠ Spades, ♥ Hearts, ♦ Diamonds, ♣ Clubs),
    Then by Rank descending (A down to 2).
    """
    return sorted(
        cards,
        key=lambda c: (SUIT_ORDER[c['suit']], -RANK_ORDER[c['rank']])
    )


def card_display_name(card: dict) -> str:
    """Human-readable card representation, e.g. 'A♠', '10♥'."""
    return f"{card['rank']}{SUIT_SYMBOLS.get(card['suit'], card['suit'])}"
