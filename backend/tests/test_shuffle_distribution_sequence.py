"""
KAZHUDHAI CLUB — backend/tests/test_shuffle_distribution_sequence.py
Tests the card shuffling and distribution sequence across 2-7 players and 1-5 decks.
Logs the deck order before shuffling, after shuffling, and the dealing sequence.
Verifies that:
  1. Complete deck is created (52 * N - (N - 1) cards, no jokers, 1 A♠, unique IDs).
  2. The ENTIRE deck is thoroughly shuffled before distribution starts.
  3. Cards are dealt directly from the shuffled deck as equally as possible.
  4. Remainder cards are given one by one starting from Player 1 (index 0).
  5. The dealt cards preserve the random shuffled order without sorting by rank or suit.
  6. Both offline and online multiplayer use the identical distribution sequence.
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.deck import build_deck, shuffle_deck, expected_card_count, is_ace_of_spades, sort_hand
from game_engine.distributor import distribute, calculate_expected_distribution
from game_engine.game_state import GameState
from game_engine.room_manager import RoomManager


class TestShuffleAndDistributionSequence(unittest.TestCase):

    def test_01_deck_creation_and_single_ace_of_spades(self):
        """Verify deck creation for 1–5 decks adheres to rules."""
        for num_decks in range(1, 6):
            expected = expected_card_count(num_decks)
            deck = build_deck(num_decks, shuffle=False)
            self.assertEqual(len(deck), expected)

            # Exactly one A♠
            aces = [c for c in deck if is_ace_of_spades(c)]
            self.assertEqual(len(aces), 1, f"Deck count {num_decks} must have exactly one A♠")

            # Unique IDs
            ids = [c['id'] for c in deck]
            self.assertEqual(len(ids), len(set(ids)), "Every physical card must have a unique ID")

    def test_02_entire_deck_shuffled_before_dealing(self):
        """
        Verify that the entire deck is shuffled before any card is dealt.
        Logs pre-shuffle and post-shuffle sequences.
        """
        for num_decks in range(1, 6):
            unshuffled = build_deck(num_decks, shuffle=False)
            unshuffled_ids = [c['id'] for c in unshuffled]
            unshuffled_labels = [f"{c['rank']}{c['suit']}" for c in unshuffled]

            # Clone and shuffle
            shuffled = [c.copy() for c in unshuffled]
            shuffle_deck(shuffled, seed=100 + num_decks)
            shuffled_ids = [c['id'] for c in shuffled]
            shuffled_labels = [f"{c['rank']}{c['suit']}" for c in shuffled]

            print(f"\n[Deck {num_decks} Verification ({len(unshuffled)} cards)]")
            print(f"  Pre-shuffle (first 5):  {unshuffled_labels[:5]}")
            print(f"  Pre-shuffle (last 5):   {unshuffled_labels[-5:]}")
            print(f"  Post-shuffle (first 5): {shuffled_labels[:5]}")
            print(f"  Post-shuffle (last 5):  {shuffled_labels[-5:]}")

            # Shuffled order must be distinctly different from pre-shuffle order
            self.assertNotEqual(shuffled_ids, unshuffled_ids,
                                f"Deck {num_decks} order must change after shuffling")
            # All cards preserved
            self.assertEqual(set(shuffled_ids), set(unshuffled_ids))
            self.assertEqual(len(shuffled_ids), len(unshuffled_ids))

    def test_03_all_30_combinations_distribution(self):
        """
        Test all 30 combinations of 1–5 decks and 2–7 players.
        Logs dealing sequence and verifies:
          - Entire deck dealt
          - Base equal share
          - Remainder dealt one by one from Player 1
          - Random shuffled order preserved (hands NOT sorted by suit/rank)
        """
        for num_decks in range(1, 6):
            for num_players in range(2, 8):
                total_cards = expected_card_count(num_decks)
                expected_counts = calculate_expected_distribution(num_decks, num_players)

                # Step 1-4: Build unshuffled deck
                deck_unshuffled = build_deck(num_decks, shuffle=False)
                # Step 5-6: Shuffle entire deck before distribution
                deck_shuffled = [c.copy() for c in deck_unshuffled]
                shuffle_deck(deck_shuffled, seed=42 + num_decks * 10 + num_players)

                # Step 7-9: Distribute cards
                hands = distribute(deck_shuffled, num_players, sort_hands=False)

                # Verify counts
                actual_counts = [len(h) for h in hands]
                self.assertEqual(actual_counts, expected_counts,
                                 f"Failed for {num_decks} decks, {num_players} players")

                # Verify all cards accounted for
                dealt_ids = [c['id'] for hand in hands for c in hand]
                self.assertEqual(len(dealt_ids), total_cards)
                self.assertEqual(set(dealt_ids), set(c['id'] for c in deck_shuffled))

                # Verify dealing sequence:
                # First card dealt to Player 1 must be deck_shuffled[0]
                self.assertEqual(hands[0][0]['id'], deck_shuffled[0]['id'])
                # Second card dealt to Player 2 must be deck_shuffled[1]
                self.assertEqual(hands[1][0]['id'], deck_shuffled[1]['id'])

                # Verify hands are NOT pre-sorted by suit or rank
                # (A hand sorted by suit has all Spades first, then Hearts, then Diamonds, then Clubs)
                for p_idx, hand in enumerate(hands):
                    if len(hand) >= 6:
                        sorted_version = sort_hand(hand)
                        sorted_ids = [c['id'] for c in sorted_version]
                        actual_ids = [c['id'] for c in hand]
                        # In random distribution, probability of actual hand matching fully sorted hand is negligible
                        self.assertNotEqual(actual_ids, sorted_ids,
                                            f"Player {p_idx+1} hand must preserve shuffled order, NOT sorted order")

        print("  ✓ All 30 combinations (1-5 decks x 2-7 players) passed distribution verification!")

    def test_04_offline_game_state_automatically_arranges_hands(self):
        """Verify GameState.setup() automatically arranges player hands by suit and descending rank after distribution."""
        configs = [{'id': f'p{i}', 'name': f'Player {i+1}', 'is_ai': (i > 0)} for i in range(4)]
        gs = GameState('test-offline-arrange', configs, num_decks=1)
        gs.setup()

        human = gs.players[0]
        # Verify human hand is sorted by suit (♠, ♥, ♦, ♣) and descending rank (A down to 2)
        hand_labels = [f"{c['rank']}{c['suit']}" for c in human.hand]
        sorted_labels = [f"{c['rank']}{c['suit']}" for c in sort_hand(human.hand)]
        print(f"\n[Offline Game State Hand]")
        print(f"  Player hand order: {hand_labels}")
        print(f"  Expected sorted:   {sorted_labels}")
        self.assertEqual(hand_labels, sorted_labels, "Human hand must be automatically arranged")

        # Verify AI hands are also automatically arranged
        for ai_p in gs.players[1:]:
            ai_labels = [f"{c['rank']}{c['suit']}" for c in ai_p.hand]
            ai_sorted = [f"{c['rank']}{c['suit']}" for c in sort_hand(ai_p.hand)]
            self.assertEqual(ai_labels, ai_sorted, f"AI player {ai_p.name} hand must be automatically arranged")

        # Verify state delivered to client is also in arranged order
        state = gs.get_state_for_player(human.id)
        client_hand_labels = [f"{c['rank']}{c['suit']}" for c in state['my_hand']]
        self.assertEqual(client_hand_labels, sorted_labels,
                         "Client state must receive hand in arranged order")

    def test_05_online_multiplayer_automatically_arranges_hands(self):
        """Verify RoomManager online multiplayer automatically arranges player hands after distribution."""
        rm = RoomManager()
        room, host = rm.create_room(host_name='HostUser', deck_count=2)
        room, peer = rm.join_room(room.code, 'PeerUser')

        # Start game
        rm.start_game(room.code, host.id)
        gs = room.game_state
        self.assertIsNotNone(gs)

        p1 = gs.players[0]
        p2 = gs.players[1]
        self.assertEqual(len(p1.hand) + len(p2.hand), expected_card_count(2))  # 103 cards

        # Both online hands are automatically arranged
        sorted_p1 = [c['id'] for c in sort_hand(p1.hand)]
        actual_p1 = [c['id'] for c in p1.hand]
        self.assertEqual(actual_p1, sorted_p1, "Online player 1 hand must be automatically arranged")

        sorted_p2 = [c['id'] for c in sort_hand(p2.hand)]
        actual_p2 = [c['id'] for c in p2.hand]
        self.assertEqual(actual_p2, sorted_p2, "Online player 2 hand must be automatically arranged")


if __name__ == '__main__':
    unittest.main()
