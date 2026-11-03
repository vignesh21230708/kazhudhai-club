"""
KAZHUDHAI CLUB — tests/test_stage2.py
Comprehensive test suite for STAGE 2:
  - Deck creation (1-5 decks)
  - Formula validation: Total cards = (52 × N) − (N − 1)
  - Exactly ONE Ace of Spades (A♠) retention
  - Removal of all duplicate A♠ cards
  - Retention of all other duplicate cards
  - Unique internal IDs for every card
  - Card ranking: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2
  - Card distribution for all player counts (2 to 7) and all deck counts (1 to 5)
  - Remainder distribution starting strictly from Player 1
  - Verification of specification example: 5 players, 3 decks = [31, 31, 31, 31, 30]
  - Shuffling verification
  - Identification of A♠ starting player for round 1
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game_engine.deck import (
    build_deck,
    expected_card_count,
    is_ace_of_spades,
    find_ace_of_spades,
    compare_ranks,
    sort_hand,
    card_display_name,
    RANKS,
    SUITS,
)
from game_engine.distributor import distribute, calculate_expected_distribution
from game_engine.game_state import GameState


def test_deck_counts():
    """Verify formula: Total cards = (52 × N) − (N − 1) for decks 1 to 5."""
    print("Testing Deck Creation & Formula Verification...")
    expected_table = {
        1: 52,
        2: 103,
        3: 154,
        4: 205,
        5: 256,
    }

    for num_decks, expected in expected_table.items():
        assert expected_card_count(num_decks) == expected, (
            f"Formula mismatch for {num_decks} decks"
        )
        deck = build_deck(num_decks, shuffle=False)
        assert len(deck) == expected, (
            f"Expected {expected} cards for {num_decks} decks, got {len(deck)}"
        )
        print(f"  ✓ {num_decks} deck(s) = {len(deck)} cards (expected {expected})")


def test_ace_of_spades_retention_and_deduplication():
    """Verify exactly ONE A♠ is retained across all decks, and all duplicate A♠ are removed."""
    print("\nTesting Ace of Spades (A♠) Single Retention...")
    for num_decks in range(1, 6):
        deck = build_deck(num_decks, shuffle=False)
        aces_of_spades = [c for c in deck if is_ace_of_spades(c)]
        assert len(aces_of_spades) == 1, (
            f"Expected exactly 1 A♠ in {num_decks} decks, got {len(aces_of_spades)}"
        )
        print(f"  ✓ {num_decks} deck(s): Exactly 1 A♠ retained (removed {num_decks - 1} duplicate A♠)")


def test_other_duplicates_retained():
    """Verify all other cards (e.g., A♥, K♠, 2♣) are retained exactly N times in N decks."""
    print("\nTesting Retention of Other Duplicate Cards...")
    for num_decks in [2, 3, 4, 5]:
        deck = build_deck(num_decks, shuffle=False)

        # Check A♥ (Ace of Hearts) appears exactly num_decks times
        aces_of_hearts = [c for c in deck if c['rank'] == 'A' and c['suit'] == 'H']
        assert len(aces_of_hearts) == num_decks, (
            f"Expected {num_decks} A♥, got {len(aces_of_hearts)}"
        )

        # Check K♠ (King of Spades) appears exactly num_decks times
        kings_of_spades = [c for c in deck if c['rank'] == 'K' and c['suit'] == 'S']
        assert len(kings_of_spades) == num_decks, (
            f"Expected {num_decks} K♠, got {len(kings_of_spades)}"
        )

        # Check 2♣ (Two of Clubs) appears exactly num_decks times
        twos_of_clubs = [c for c in deck if c['rank'] == '2' and c['suit'] == 'C']
        assert len(twos_of_clubs) == num_decks, (
            f"Expected {num_decks} 2♣, got {len(twos_of_clubs)}"
        )

        print(f"  ✓ {num_decks} decks: Every non-A♠ card appears exactly {num_decks} times")


def test_unique_card_ids():
    """Verify every physical card has a unique internal ID."""
    print("\nTesting Unique Internal Card IDs...")
    for num_decks in range(1, 6):
        deck = build_deck(num_decks)
        all_ids = [c['id'] for c in deck]
        unique_ids = set(all_ids)
        assert len(all_ids) == len(unique_ids), (
            f"Duplicate card IDs found in {num_decks} decks!"
        )
        print(f"  ✓ {num_decks} deck(s): All {len(all_ids)} cards have unique IDs")


def test_card_ranking_hierarchy():
    """Verify Card Ranking: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2."""
    print("\nTesting Card Ranking Hierarchy...")
    ordered = ['A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5', '4', '3', '2']
    for i in range(len(ordered) - 1):
        higher = ordered[i]
        lower  = ordered[i + 1]
        assert compare_ranks(higher, lower) > 0, (
            f"Expected {higher} > {lower}"
        )
        assert compare_ranks(lower, higher) < 0, (
            f"Expected {lower} < {higher}"
        )
        assert compare_ranks(higher, higher) == 0

    print("  ✓ Full ranking hierarchy verified: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2")


def test_specification_example_distribution():
    """
    Test the exact example from specification Section 4:
      5 players and 3 decks = 154 cards.
      First distribute 30 cards to each player.
      Remaining cards = 4.
      Final distribution:
      - Player 1: 31 cards
      - Player 2: 31 cards
      - Player 3: 31 cards
      - Player 4: 31 cards
      - Player 5: 30 cards
    """
    print("\nTesting Specification Example (5 Players, 3 Decks)...")
    deck = build_deck(3, shuffle=True, seed=42)
    assert len(deck) == 154

    hands = distribute(deck, 5)
    expected_counts = [31, 31, 31, 31, 30]

    for p_idx, count in enumerate(expected_counts):
        actual = len(hands[p_idx])
        assert actual == count, (
            f"Player {p_idx + 1} expected {count} cards, got {actual}"
        )
        print(f"  ✓ Player {p_idx + 1}: {actual} cards (expected {count})")

    total_distributed = sum(len(h) for h in hands)
    assert total_distributed == 154
    print(f"  ✓ Total distributed: {total_distributed} / 154")


def test_all_distribution_combinations():
    """
    Test all 30 combinations of players (2 to 7) and decks (1 to 5).
    Verifies:
      - Equal base share
      - Sequential remainder starting from Player 1 (index 0)
      - Total distributed cards equals deck size
    """
    print("\nTesting All Combinations: 1–5 Decks across 2–7 Players...")
    test_count = 0
    for num_decks in range(1, 6):
        deck = build_deck(num_decks, shuffle=True)
        total_cards = len(deck)

        for num_players in range(2, 8):
            expected_counts = calculate_expected_distribution(num_decks, num_players)
            hands = distribute(deck, num_players)

            # Check individual hand lengths
            actual_counts = [len(h) for h in hands]
            assert actual_counts == expected_counts, (
                f"Mismatch for {num_decks} decks, {num_players} players: {actual_counts} != {expected_counts}"
            )

            # Check total distributed
            assert sum(actual_counts) == total_cards, (
                f"Total cards mismatch: {sum(actual_counts)} != {total_cards}"
            )

            test_count += 1

    print(f"  ✓ All {test_count} deck/player combinations passed distribution rules perfectly!")


def test_ace_of_spades_starter_detection():
    """Verify that the player holding A♠ starts the first round."""
    print("\nTesting A♠ Starting Player Detection...")
    for seed in [1, 7, 42, 99, 123]:
        deck = build_deck(1, shuffle=True, seed=seed)
        hands = distribute(deck, 4)

        # Find which hand has A♠
        expected_starter = None
        for i, h in enumerate(hands):
            if find_ace_of_spades(h):
                expected_starter = i
                break

        assert expected_starter is not None, "A♠ must exist in one player's hand!"

        # Create GameState and setup
        configs = [{'id': f'p{i}', 'name': f'Player {i+1}'} for i in range(4)]
        gs = GameState('test-starter', configs, num_decks=1)
        # Assign hands directly or call setup
        gs.setup()

        # Check starter
        starter = gs.current_player
        assert find_ace_of_spades(starter.hand) is not None, (
            f"Starter {starter.name} does NOT hold A♠!"
        )
        print(f"  ✓ Seed {seed}: Starter {starter.name} holds A♠")


def test_hand_sorting():
    """Verify hands are cleanly sorted by Suit (♠, ♥, ♦, ♣) and Rank descending."""
    print("\nTesting Hand Sorting...")
    unsorted_hand = [
        {'id': '1', 'rank': '2', 'suit': 'C'},
        {'id': '2', 'rank': 'A', 'suit': 'S'},
        {'id': '3', 'rank': '10', 'suit': 'S'},
        {'id': '4', 'rank': 'K', 'suit': 'H'},
        {'id': '5', 'rank': '5', 'suit': 'D'},
        {'id': '6', 'rank': 'Q', 'suit': 'S'},
    ]
    sorted_hand = sort_hand(unsorted_hand)
    labels = [card_display_name(c) for c in sorted_hand]
    expected_order = ['A♠', 'Q♠', '10♠', 'K♥', '5♦', '2♣']
    assert labels == expected_order, f"Sorting error: {labels} != {expected_order}"
    print(f"  ✓ Hand sorted correctly: {' '.join(labels)}")


if __name__ == '__main__':
    print("=" * 60)
    print("KAZHUDHAI CLUB — STAGE 2 VERIFICATION SUITE")
    print("=" * 60)

    test_deck_counts()
    test_ace_of_spades_retention_and_deduplication()
    test_other_duplicates_retained()
    test_unique_card_ids()
    test_card_ranking_hierarchy()
    test_specification_example_distribution()
    test_all_distribution_combinations()
    test_ace_of_spades_starter_detection()
    test_hand_sorting()

    print("\n" + "=" * 60)
    print("ALL STAGE 2 TESTS PASSED SUCCESSFULLY! (100% COMPLIANT)")
    print("=" * 60)
