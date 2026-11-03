"""
KAZHUDHAI CLUB — backend/tests/test_fresh_shuffle_consecutive_matches.py
Unit and integration tests for Fresh Deck Shuffling and 20+ Consecutive Matches.

Requirements Tested:
  1. Complete deck created according to selected deck count (1-5).
  2. Exclude jokers and retain exactly ONE physical Ace of Spades (A♠).
  3. Unique ID assigned to every physical card.
  4. Unbiased Fisher-Yates shuffle algorithm used to randomly shuffle the entire deck.
  5. Fresh random shuffle generated for every new match using secure random number generator (CSPRNG).
  6. Never reuse previous match's shuffled deck order.
  7. Cards distributed equally among players only after shuffle is complete.
  8. Remaining cards distributed one by one starting with Player 1.
  9. Cards NOT sorted by rank or suit before or after distribution.
  10. Applied to offline games, AI games, and online multiplayer.
  11. Tested across at least 20 consecutive new matches.
  12. Verified no cards duplicated and no cards missing.
"""
import unittest
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.deck import (
    build_deck,
    shuffle_deck,
    expected_card_count,
    is_ace_of_spades,
    sort_hand,
    get_last_shuffled_order,
    reset_shuffle_history,
)
from game_engine.distributor import distribute, calculate_expected_distribution
from game_engine.game_state import GameState
from game_engine.room_manager import RoomManager


class TestFreshShuffleConsecutiveMatches(unittest.TestCase):

    def setUp(self):
        reset_shuffle_history()

    def test_01_fisher_yates_csprng_properties(self):
        """Verify unbiased Fisher-Yates CSPRNG shuffle properties."""
        for num_decks in range(1, 6):
            expected_total = expected_card_count(num_decks)
            deck = build_deck(num_decks, shuffle=False)
            self.assertEqual(len(deck), expected_total)

            pre_ids = [c['id'] for c in deck]
            pre_order = [f"{c['rank']}{c['suit']}" for c in deck]

            # Perform Fisher-Yates shuffle with CSPRNG (seed=None)
            shuffled = shuffle_deck(deck)
            post_ids = [c['id'] for c in shuffled]
            post_order = [f"{c['rank']}{c['suit']}" for c in shuffled]

            # 1. Total count preserved
            self.assertEqual(len(post_ids), expected_total)
            # 2. All physical card IDs preserved (no card lost, no card added)
            self.assertEqual(set(post_ids), set(pre_ids))
            # 3. Order strictly randomized from factory order
            self.assertNotEqual(post_order, pre_order)
            # 4. Exactly one Ace of Spades
            aces_of_spades = [c for c in shuffled if is_ace_of_spades(c)]
            self.assertEqual(len(aces_of_spades), 1)

    def test_02_twenty_five_consecutive_matches_fresh_shuffle(self):
        """
        Test 25 consecutive new matches across diverse deck counts (1-5) and player counts (2-7).
        Verify:
          - Every match freshly shuffles the entire deck before dealing.
          - Never reuses previous match's shuffled order.
          - No cards duplicated or missing.
          - Remainder distributed one-by-one from Player 1.
          - Hands are not pre-sorted.
        """
        match_orders: list[tuple[str, ...]] = []
        ace_spades_positions: list[int] = []

        print(f"\n{'='*70}")
        print(f"  RUNNING 25 CONSECUTIVE MATCH VERIFICATION")
        print(f"{'='*70}")

        for match_num in range(1, 26):
            # Rotate deck counts 1..5 and player counts 2..7
            num_decks = ((match_num - 1) % 5) + 1
            num_players = ((match_num - 1) % 6) + 2
            total_cards = expected_card_count(num_decks)

            # Step 1-3: Assemble deck with unique IDs, 1 A♠, no jokers
            pre_deck = build_deck(num_decks, shuffle=False)
            self.assertEqual(len(pre_deck), total_cards)
            self.assertEqual(len({c['id'] for c in pre_deck}), total_cards, "All card IDs must be unique")
            self.assertEqual(len([c for c in pre_deck if is_ace_of_spades(c)]), 1, "Must have exactly 1 A♠")

            # Step 4-6: Fresh unbiased Fisher-Yates CSPRNG shuffle
            shuffled_deck = shuffle_deck(pre_deck)
            shuffled_order = tuple(f"{c['rank']}{c['suit']}" for c in shuffled_deck)

            # Track Ace of Spades position in shuffled deck
            as_idx = next(i for i, c in enumerate(shuffled_deck) if is_ace_of_spades(c))
            ace_spades_positions.append(as_idx)

            # Verify deck order is unique and NEVER matches any previous match
            self.assertNotIn(
                shuffled_order,
                match_orders,
                f"Match {match_num} deck order duplicates a previous match's order!"
            )
            match_orders.append(shuffled_order)

            # Step 7-9: Distribute cards after shuffle
            hands = distribute(shuffled_deck, num_players, sort_hands=False)

            # Check 1: Distribution equality and remainder handling
            expected_counts = calculate_expected_distribution(num_decks, num_players)
            actual_counts = [len(h) for h in hands]
            self.assertEqual(actual_counts, expected_counts,
                             f"Match {match_num} distribution mismatch: got {actual_counts}, expected {expected_counts}")

            # Check 2: No cards duplicated or missing
            all_dealt_cards = [c for h in hands for c in h]
            self.assertEqual(len(all_dealt_cards), total_cards, f"Match {match_num} missing cards")
            all_dealt_ids = [c['id'] for c in all_dealt_cards]
            self.assertEqual(len(set(all_dealt_ids)), total_cards, f"Match {match_num} has duplicate card IDs")

            # Check 3: Preserved natural dealing order (not sorted)
            if len(hands[0]) >= 5:
                p1_labels = [f"{c['rank']}{c['suit']}" for c in hands[0]]
                p1_sorted = [f"{c['rank']}{c['suit']}" for c in sort_hand(hands[0])]
                self.assertNotEqual(p1_labels, p1_sorted,
                                    f"Match {match_num} Player 1 hand must NOT be pre-sorted")

            print(f"  Match {match_num:02d}: {num_decks} deck(s) ({total_cards} cards) | {num_players} players | "
                  f"P1 gets {actual_counts[0]} cards | A♠ at pos {as_idx:03d} | Shuffled OK (unique)")

        self.assertEqual(len(match_orders), 25, "All 25 matches must have unique shuffled deck sequences")
        # Check that A♠ appears at diverse positions across matches (not fixed)
        unique_as_positions = len(set(ace_spades_positions))
        self.assertGreaterEqual(unique_as_positions, 15,
                                f"A♠ positions should be widely distributed, got {unique_as_positions} unique positions")
        print(f"{'='*70}\n")

    def test_03_consecutive_restarts_on_same_gamestate(self):
        """Verify that calling restart() on GameState creates a fresh random shuffle every time."""
        configs = [{'id': f'p_{i}', 'name': f'Player {i}', 'is_ai': (i > 0)} for i in range(4)]
        gs = GameState(game_id='restart_test', player_configs=configs, num_decks=2)

        seen_first_hands: list[tuple[str, ...]] = []

        for rematch_num in range(1, 11):
            if rematch_num == 1:
                gs.setup()
            else:
                gs.restart()

            self.assertEqual(gs.status, GameState.STATUS_PLAYING)
            self.assertEqual(gs.round_number, 1)

            # Player hands must have fresh cards
            p0_hand_ids = tuple(c['id'] for c in gs.players[0].hand)
            p0_hand_labels = tuple(f"{c['rank']}{c['suit']}" for c in gs.players[0].hand)

            # Verify no rematch produces the identical hand order
            self.assertNotIn(p0_hand_ids, seen_first_hands)
            seen_first_hands.append(p0_hand_ids)

            # Verify hand count equals expected
            self.assertEqual(len(gs.players[0].hand), 26)  # 103 // 4 = 25, rem = 3 -> p0 gets 26

            # Verify exactly 1 A♠ in total game
            all_cards = [c for p in gs.players for c in p.hand]
            self.assertEqual(len(all_cards), 103)
            self.assertEqual(len([c for c in all_cards if is_ace_of_spades(c)]), 1)
            self.assertEqual(len({c['id'] for c in all_cards}), 103)

    def test_04_online_room_manager_consecutive_rematches(self):
        """Verify RoomManager restart_game produces fresh random shuffle for every rematch."""
        rm = RoomManager()
        room, host = rm.create_room(host_name='HostPlayer', max_players=3, deck_count=1)
        rm.join_room(room.code, 'Player2')
        rm.join_room(room.code, 'Player3')

        seen_deck_signatures: list[tuple[str, ...]] = []

        for match_idx in range(1, 6):
            if match_idx == 1:
                rm.start_game(room.code, host.id)
            else:
                rm.restart_game(room.code, host.id)

            gs = room.game_state
            self.assertIsNotNone(gs)
            self.assertEqual(room.status, 'playing')

            # Collect cards across all players
            room_cards = [c for p in gs.players for c in p.hand]
            self.assertEqual(len(room_cards), 52)
            self.assertEqual(len({c['id'] for c in room_cards}), 52)

            # Signature of dealing order
            deck_sig = tuple(c['id'] for c in room_cards)
            self.assertNotIn(deck_sig, seen_deck_signatures)
            seen_deck_signatures.append(deck_sig)


if __name__ == '__main__':
    unittest.main()
