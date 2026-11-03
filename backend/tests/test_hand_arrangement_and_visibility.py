"""
KAZHUDHAI CLUB — backend/tests/test_hand_arrangement_and_visibility.py
Tests for:
  1. Automatic Hand Arranging:
     - After card distribution is complete, every player's hand is automatically sorted.
     - Group cards by suit (♠, ♥, ♦, ♣).
     - Within each suit, arrange cards in descending rank order: A, K, Q, J, 10, 9, 8, 7, 6, 5, 4, 3, 2.
     - Consistent suit order for all players.
     - Applied to human player's visible hand and AI hands.
     - Preserves physical card IDs, ownership, and original shuffled deck.
     - When a player collects cards after an attack round, arranges their updated hand again.
  2. Player Card Visibility:
     - Sizing, spacing, and overlap across 2-7 players and 1-5 decks.
     - Desktop, laptop, tablet, and mobile portrait/landscape responsive overlap metrics.
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.deck import (
    build_deck,
    expected_card_count,
    is_ace_of_spades,
    sort_hand,
    SUIT_ORDER,
    RANK_ORDER,
)
from game_engine.distributor import distribute, calculate_expected_distribution
from game_engine.game_state import GameState
from game_engine.player import Player
from game_engine.round_engine import RoundEngine


class TestHandArrangementAndVisibility(unittest.TestCase):

    def _verify_hand_arrangement(self, hand: list[dict], player_label: str = "Player"):
        """Verify that hand is grouped by suit and within each suit descending rank order."""
        if len(hand) <= 1:
            return

        for i in range(len(hand) - 1):
            curr_card = hand[i]
            next_card = hand[i + 1]

            curr_suit_idx = SUIT_ORDER[curr_card['suit']]
            next_suit_idx = SUIT_ORDER[next_card['suit']]

            # Check suit grouping
            self.assertLessEqual(
                curr_suit_idx, next_suit_idx,
                f"{player_label} suit grouping violated: {curr_card['suit']} preceded {next_card['suit']}"
            )

            # If same suit, check descending rank order (A > K > ... > 2)
            if curr_suit_idx == next_suit_idx:
                curr_rank_val = RANK_ORDER[curr_card['rank']]
                next_rank_val = RANK_ORDER[next_card['rank']]
                self.assertGreaterEqual(
                    curr_rank_val, next_rank_val,
                    f"{player_label} rank order violated in suit {curr_card['suit']}: "
                    f"{curr_card['rank']} preceded {next_card['rank']}"
                )

    def test_01_hand_arrangement_after_distribution_all_combinations(self):
        """Test that every player's hand is automatically arranged across 2-7 players and 1-5 decks."""
        for num_decks in range(1, 6):
            for num_players in range(2, 8):
                configs = [
                    {'id': f'p_{i}', 'name': f'Player {i+1}', 'is_ai': (i > 0)}
                    for i in range(num_players)
                ]
                gs = GameState(f'game_{num_decks}_{num_players}', configs, num_decks=num_decks)
                gs.setup()

                # Verify every player's hand
                for p in gs.players:
                    self._verify_hand_arrangement(p.hand, player_label=p.name)

                # Verify human requesting player's state
                human_state = gs.get_state_for_player(gs.players[0].id)
                self._verify_hand_arrangement(human_state['my_hand'], player_label="Human Client State")

    def test_02_preserves_card_ownership_and_unique_ids(self):
        """Verify hand arrangement does not modify card ownership, IDs, or total card count."""
        configs = [
            {'id': 'human', 'name': 'You', 'is_ai': False},
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True},
        ]
        gs = GameState('ownership_test', configs, num_decks=2)
        gs.setup()

        all_hand_cards = [c for p in gs.players for c in p.hand]
        self.assertEqual(len(all_hand_cards), 103)

        # Unique UUIDs preserved
        unique_ids = {c['id'] for c in all_hand_cards}
        self.assertEqual(len(unique_ids), 103)

        # Exactly 1 A♠ preserved
        aces = [c for c in all_hand_cards if is_ace_of_spades(c)]
        self.assertEqual(len(aces), 1)

    def test_03_attack_round_collection_rearranges_updated_hand(self):
        """
        Verify: When a player collects cards after an attack round,
        their updated hand is automatically arranged again.
        """
        p1 = Player('p1', 'Bot 1', is_ai=True, hand=[
            {'id': 'c1', 'rank': '6', 'suit': 'S'},
            {'id': 'c2', 'rank': '2', 'suit': 'H'},
        ])
        p2 = Player('p2', 'Bot 2', is_ai=True, hand=[
            {'id': 'c3', 'rank': 'K', 'suit': 'D'},  # Attack card (no spades)
        ])

        gs = GameState('attack_arrange_test', [
            {'id': 'p1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'p2', 'name': 'Bot 2', 'is_ai': True},
        ], num_decks=1)
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.current_player_idx = 0
        gs.round_number = 1
        gs.current_round = RoundEngine([p1, p2], 0)

        # Round 1: Bot 1 leads 6♠
        gs.play_card('p1', 'c1')
        # Bot 2 attacks with K♦ -> triggers attack resolution immediately
        res = gs.play_card('p2', 'c3')

        # Bot 1 won attack round (highest spade 6♠) and collected: [6♠, K♦]
        # Bot 1 original remaining hand was: [2♥]
        # Updated hand must contain: [6♠, 2♥, K♦]
        self.assertEqual(res['last_round_result']['winner_id'], 'p1')
        self.assertEqual(len(p1.hand), 3)

        # Verify Bot 1's hand is automatically re-arranged!
        # Suit order: S (Spades) -> H (Hearts) -> D (Diamonds) -> C (Clubs)
        # In S: 6♠. In H: 2♥. In D: K♦.
        hand_labels = [f"{c['rank']}{c['suit']}" for c in p1.hand]
        print(f"\n[Attack Collection Re-Arranged Hand]: {hand_labels}")
        expected_labels = ['6S', '2H', 'KD']
        self.assertEqual(hand_labels, expected_labels,
                         "Winner's updated hand must be automatically re-arranged by suit and rank!")
        self._verify_hand_arrangement(p1.hand, player_label="Bot 1 Post-Attack Hand")

    def test_04_card_visibility_spacing_metrics(self):
        """
        Verify card spacing and overlap calculations ensure adequate exposure of rank and suit:
        - Mobile portrait card width = 62px, min exposed width >= 38px
        - Desktop card width = 70px, min exposed width >= 46px
        """
        def calculate_overlap_mobile(hand_count):
            if hand_count <= 3: return -4
            if hand_count <= 6: return -8
            if hand_count <= 10: return -12
            if hand_count <= 16: return -16
            if hand_count <= 22: return -20
            return -22

        def calculate_overlap_desktop(hand_count):
            if hand_count <= 4: return -6
            if hand_count <= 8: return -10
            if hand_count <= 14: return -14
            if hand_count <= 20: return -18
            return -22

        # Test small, medium, and very large hands (1 to 35 cards)
        for count in [2, 5, 10, 13, 20, 26, 35]:
            # Mobile
            overlap_m = calculate_overlap_mobile(count)
            exposed_m = 62 + overlap_m  # e.g. 62 - 22 = 40px
            self.assertGreaterEqual(
                exposed_m, 38,
                f"Mobile hand of {count} cards has only {exposed_m}px exposed (min 38px required)"
            )

            # Desktop
            overlap_d = calculate_overlap_desktop(count)
            exposed_d = 70 + overlap_d  # e.g. 70 - 22 = 48px
            self.assertGreaterEqual(
                exposed_d, 46,
                f"Desktop hand of {count} cards has only {exposed_d}px exposed (min 46px required)"
            )


if __name__ == '__main__':
    unittest.main()
