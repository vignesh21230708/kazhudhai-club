"""
KAZHUDHAI CLUB — backend/tests/test_attack_lifecycle.py
Tests the complete attack-round card lifecycle, physical card ID uniqueness,
immediate card removal on play, deduplicated collection, and AI next-turn decisions.
"""
import unittest
import uuid
import sys
import os

# Ensure backend package on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.deck import build_deck, RANK_ORDER
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.game_state import GameState
from game_engine.ai_player import AIPlayer


class TestAttackRoundCardLifecycle(unittest.TestCase):
    """
    Validates:
      1. Immediate removal of physical card from player hand when played.
      2. No duplicate cards or duplicate physical IDs in hand.
      3. Exactly ONE copy of 6♠ in winner hand after attack collection.
      4. AI next-round decision reads the freshly updated hand.
      5. Distinguishing duplicate-looking cards across multiple decks using unique IDs.
    """

    def test_exact_scenario_lifecycle_single_deck(self):
        """
        Exact User Scenario:
          - Bot 1 plays 6♠ to start round 1.
          - Bot 2 has no Spades and attacks with off-suit card (K♦).
          - Bot 1 wins attack round.
          - All played cards are collected by Bot 1.
          - Verify hand before playing, after playing, after attack resolution, and before next turn.
          - Verify 6♠ is present only once and cannot be replayed without legitimate ownership.
        """
        card_6s = {'id': 'phys-6s-uuid', 'rank': '6', 'suit': 'S', 'deck_index': 0}
        card_8s = {'id': 'phys-8s-uuid', 'rank': '8', 'suit': 'S', 'deck_index': 0}
        card_kd = {'id': 'phys-kd-uuid', 'rank': 'K', 'suit': 'D', 'deck_index': 0}
        card_5d = {'id': 'phys-5d-uuid', 'rank': '5', 'suit': 'D', 'deck_index': 0}

        p1 = Player(id='bot1', name='Bot 1', is_ai=True)
        p2 = Player(id='bot2', name='Bot 2', is_ai=True)

        p1.hand = [card_6s.copy(), card_8s.copy()]
        p2.hand = [card_kd.copy(), card_5d.copy()]

        gs = GameState('game-test-1', [
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True}
        ], difficulty='medium')
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_player_idx = 0
        gs._start_new_round()

        # Phase 1: Hand BEFORE playing Round 1
        hand_before_play = [c['id'] for c in p1.hand]
        print(f"\n[Test Exact Scenario] 1. Hand BEFORE play: {[f'{c['rank']}{c['suit']}' for c in p1.hand]}")
        self.assertIn('phys-6s-uuid', hand_before_play)
        self.assertEqual(p1.count_card_id('phys-6s-uuid'), 1)
        self.assertEqual(len(p1.hand), 2)

        # Bot 1 plays 6♠
        res1 = gs.step_ai_turn()
        self.assertEqual(res1['action']['card']['id'], 'phys-6s-uuid')

        # Phase 2: Hand AFTER playing Round 1 (IMMEDIATE REMOVAL)
        print(f"[Test Exact Scenario] 2. Hand AFTER play: {[f'{c['rank']}{c['suit']}' for c in p1.hand]}")
        self.assertFalse(p1.has_card('phys-6s-uuid'))
        self.assertEqual(p1.count_card_id('phys-6s-uuid'), 0)
        self.assertEqual(len(p1.hand), 1)
        self.assertNotIn('phys-6s-uuid', [c['id'] for c in p1.hand])

        # Phase 3: Bot 2 attacks with K♦
        res2 = gs.step_ai_turn()
        self.assertTrue(res2['action']['is_attack'])
        self.assertTrue(res2['round_completed'])
        round_res = res2['last_round_result']
        self.assertEqual(round_res['winner_id'], 'bot1')
        self.assertEqual(round_res['collection_type'], 'winner_hand')

        # Phase 4: Hand AFTER attack resolution and collection
        print(f"[Test Exact Scenario] 3. Hand AFTER collection: {[f'{c['rank']}{c['suit']}' for c in p1.hand]}")
        self.assertTrue(p1.has_card('phys-6s-uuid'))
        # 6♠ MUST BE PRESENT EXACTLY ONCE
        self.assertEqual(p1.count_card_id('phys-6s-uuid'), 1)
        self.assertEqual(p1.count_card_id('phys-kd-uuid'), 1)
        self.assertEqual(p1.count_card_id('phys-8s-uuid'), 1)
        # No duplicates
        self.assertEqual(len(p1.hand), 3)
        self.assertEqual(len(p1.hand), len(set(c['id'] for c in p1.hand)))

        # Phase 5: BEFORE next turn (Round 2)
        print(f"[Test Exact Scenario] 4. Hand BEFORE Round 2 play: {[f'{c['rank']}{c['suit']}' for c in p1.hand]}")
        self.assertEqual(gs.round_number, 2)
        self.assertEqual(gs.current_player.id, 'bot1')
        self.assertEqual(p1.count_card_id('phys-6s-uuid'), 1)

        # Bot 1 executes Round 2 play
        res3 = gs.step_ai_turn()
        self.assertEqual(res3['action']['player_id'], 'bot1')
        played_card_r2 = res3['action']['card']

        # Because 6♠ is rank 4 and lowest among {6♠, 8♠, K♦}, Bot 1 legitimately plays 6♠
        self.assertEqual(played_card_r2['id'], 'phys-6s-uuid')

        # Phase 6: Hand AFTER Round 2 play
        print(f"[Test Exact Scenario] 5. Hand AFTER Round 2 play: {[f'{c['rank']}{c['suit']}' for c in p1.hand]}")
        # MUST BE 0 COPIES NOW
        self.assertFalse(p1.has_card('phys-6s-uuid'))
        self.assertEqual(p1.count_card_id('phys-6s-uuid'), 0)
        self.assertEqual(len(p1.hand), 2)
        # Cannot be played again
        valid_again, _ = gs.current_round.can_play(p1, card_6s)
        self.assertFalse(valid_again, "6♠ cannot be played again because player does not have it")

    def test_attack_lifecycle_with_lower_attack_card(self):
        """
        Verify that when Bot 2 attacks with a card LOWER than 6♠ (e.g. 2♣),
        the AI's updated hand in Round 2 correctly leads with 2♣ (the new lowest card),
        proving that AI decision reads the updated hand!
        """
        card_6s = {'id': 'phys-6s', 'rank': '6', 'suit': 'S', 'deck_index': 0}
        card_8s = {'id': 'phys-8s', 'rank': '8', 'suit': 'S', 'deck_index': 0}
        card_2c = {'id': 'phys-2c', 'rank': '2', 'suit': 'C', 'deck_index': 0}  # Rank 2 is lowest possible
        card_kd = {'id': 'phys-kd-2', 'rank': 'K', 'suit': 'D', 'deck_index': 0}

        p1 = Player(id='bot1', name='Bot 1', is_ai=True)
        p2 = Player(id='bot2', name='Bot 2', is_ai=True)
        p1.hand = [card_6s.copy(), card_8s.copy()]
        p2.hand = [card_2c.copy(), card_kd.copy()]

        gs = GameState('game-test-2', [
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True}
        ], difficulty='medium')
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_player_idx = 0
        gs._start_new_round()

        # Bot 1 plays 6♠
        gs.step_ai_turn()
        self.assertEqual(p1.count_card_id('phys-6s'), 0)

        # Bot 2 attacks (with highest card K♦ in medium difficulty, or lowest)
        # Let's ensure Bot 2 plays 2♣ by making Bot 2 have only clubs/diamonds
        # In medium difficulty attack: max rank is played. To make Bot 2 play 2♣ on attack,
        # Bot 2's highest off-suit card can be 2♣ and remaining card is lower or void.
        # Alternatively, if Bot 2 hand is [card_2c, card_2d], both are rank 2!
        p2.hand = [card_2c.copy(), {'id': 'phys-2d', 'rank': '2', 'suit': 'D', 'deck_index': 0}]
        gs.step_ai_turn()

        # Bot 1 collected 6♠ and the attack card
        self.assertEqual(p1.count_card_id('phys-6s'), 1)
        self.assertTrue(p1.count_card_id('phys-2c') == 1 or p1.count_card_id('phys-2d') == 1)

        # Bot 1 starts Round 2
        # Because rank 2 is lower rank than 6♠, Medium AI MUST choose a rank 2 card!
        res_r2 = gs.step_ai_turn()
        self.assertEqual(res_r2['action']['card']['rank'], '2')
        played_card_id = res_r2['action']['card']['id']

        # The rank 2 card is removed, 6♠ remains in hand with count 1
        self.assertEqual(p1.count_card_id(played_card_id), 0)
        self.assertEqual(p1.count_card_id('phys-6s'), 1)

    def test_repeated_lifecycle_50_iterations(self):
        """Run the exact scenario 50 times repeatedly to ensure consistency."""
        for i in range(50):
            p1_6s = {'id': f'6s-{i}', 'rank': '6', 'suit': 'S', 'deck_index': 0}
            p1_other = {'id': f'other-{i}', 'rank': '9', 'suit': 'S', 'deck_index': 0}
            p2_atk = {'id': f'atk-{i}', 'rank': 'K', 'suit': 'H', 'deck_index': 0}
            p2_reserve = {'id': f'res-{i}', 'rank': '3', 'suit': 'H', 'deck_index': 0}

            p1 = Player(id='bot1', name='Bot 1', is_ai=True, hand=[p1_6s.copy(), p1_other.copy()])
            p2 = Player(id='bot2', name='Bot 2', is_ai=True, hand=[p2_atk.copy(), p2_reserve.copy()])

            gs = GameState(f'sim-{i}', [{'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
                                         {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True}], difficulty='medium')
            gs.players = [p1, p2]
            gs.status = GameState.STATUS_PLAYING
            gs.round_number = 1
            gs.current_player_idx = 0
            gs._start_new_round()

            # 1. Before play
            self.assertEqual(p1.count_card_id(f'6s-{i}'), 1)

            # 2. Bot 1 plays 6♠
            res1 = gs.step_ai_turn()
            self.assertEqual(res1['action']['card']['id'], f'6s-{i}')
            self.assertEqual(p1.count_card_id(f'6s-{i}'), 0)

            # 3. Bot 2 attacks
            res2 = gs.step_ai_turn()
            self.assertTrue(res2['action']['is_attack'])
            self.assertFalse(res2['last_round_result']['game_finished'])

            # 4. After collection: 6♠ must be present EXACTLY ONCE
            self.assertEqual(p1.count_card_id(f'6s-{i}'), 1)
            self.assertEqual(len(p1.hand), len(set(c['id'] for c in p1.hand)))

            # 5. Round 2 play: Bot 1 legitimately plays 6♠ (rank 4 < 9 and K)
            res3 = gs.step_ai_turn()
            self.assertEqual(res3['action']['card']['id'], f'6s-{i}')
            # After Round 2 play, 6♠ count MUST BE 0
            self.assertEqual(p1.count_card_id(f'6s-{i}'), 0)

    def test_multi_deck_duplicate_looking_cards(self):
        """
        Verify that duplicate-looking cards from multiple decks (e.g. 6♠ from Deck 1 and 6♠ from Deck 2)
        have distinct physical IDs and are handled independently without cross-contamination.
        """
        card_6s_deck0 = {'id': 'deck0-6s-uuid', 'rank': '6', 'suit': 'S', 'deck_index': 0}
        card_6s_deck1 = {'id': 'deck1-6s-uuid', 'rank': '6', 'suit': 'S', 'deck_index': 1}
        card_kd = {'id': 'deck0-kd-uuid', 'rank': 'K', 'suit': 'D', 'deck_index': 0}

        p1 = Player(id='bot1', name='Bot 1', is_ai=True)
        p2 = Player(id='bot2', name='Bot 2', is_ai=True)

        # Bot 1 legitimately holds BOTH 6♠ cards
        p1.hand = [card_6s_deck0.copy(), card_6s_deck1.copy()]
        p2.hand = [card_kd.copy(), {'id': 'deck0-5d-uuid', 'rank': '5', 'suit': 'D', 'deck_index': 0}]

        self.assertEqual(p1.count_card_id('deck0-6s-uuid'), 1)
        self.assertEqual(p1.count_card_id('deck1-6s-uuid'), 1)
        self.assertEqual(len(p1.hand), 2)

        gs = GameState('game-multideck', [
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True}
        ], num_decks=2)
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_player_idx = 0
        gs._start_new_round()

        # Bot 1 plays one of the 6♠ cards (e.g. deck0-6s-uuid)
        res1 = gs.step_ai_turn()
        played_id = res1['action']['card']['id']

        # Played card must be 0 in hand, other 6♠ must remain 1 in hand!
        other_id = 'deck1-6s-uuid' if played_id == 'deck0-6s-uuid' else 'deck0-6s-uuid'
        self.assertEqual(p1.count_card_id(played_id), 0)
        self.assertEqual(p1.count_card_id(other_id), 1)
        self.assertEqual(len(p1.hand), 1)

        # Bot 2 attacks
        gs.step_ai_turn()

        # After collection, Bot 1 collects the played card back.
        # BOTH 6♠ cards must now be in hand, each appearing EXACTLY ONCE!
        self.assertEqual(p1.count_card_id(played_id), 1)
        self.assertEqual(p1.count_card_id(other_id), 1)
        self.assertEqual(p1.count_card_id('deck0-kd-uuid'), 1)
        self.assertEqual(len(p1.hand), 3)
        self.assertEqual(len(p1.hand), len(set(c['id'] for c in p1.hand)))

    def test_hand_deduplication_guardrails(self):
        """
        Verify player.add_cards and player.remove_card guarantee that identical physical card IDs
        can NEVER exist multiple times in a player's hand.
        """
        p = Player(id='p1', name='Player 1')
        c1 = {'id': 'card-1', 'rank': 'A', 'suit': 'S', 'deck_index': 0}
        c2 = {'id': 'card-2', 'rank': 'K', 'suit': 'S', 'deck_index': 0}

        p.add_cards([c1])
        self.assertEqual(p.count_card_id('card-1'), 1)

        # Adding same card ID again must be safely ignored
        p.add_cards([c1, c1, c2])
        self.assertEqual(p.count_card_id('card-1'), 1)
        self.assertEqual(p.count_card_id('card-2'), 1)
        self.assertEqual(len(p.hand), 2)

        # remove_card removes it cleanly
        rem = p.remove_card('card-1')
        self.assertEqual(rem['id'], 'card-1')
        self.assertEqual(p.count_card_id('card-1'), 0)
        self.assertEqual(len(p.hand), 1)


    def test_normal_round_removes_6s_permanently(self):
        """
        Verify that in a normal round, 6♠ goes to the common pile and
        Bot 1 CANNOT play it in Round 2 because it has 0 copies.
        """
        card_6s = {'id': 'phys-6s-norm', 'rank': '6', 'suit': 'S', 'deck_index': 0}
        card_8s = {'id': 'phys-8s-norm', 'rank': '8', 'suit': 'S', 'deck_index': 0}
        card_7s = {'id': 'phys-7s-norm', 'rank': '7', 'suit': 'S', 'deck_index': 0}
        card_ks = {'id': 'phys-ks-norm', 'rank': 'K', 'suit': 'S', 'deck_index': 0}

        p1 = Player(id='bot1', name='Bot 1', is_ai=True, hand=[card_6s.copy(), card_8s.copy()])
        p2 = Player(id='bot2', name='Bot 2', is_ai=True, hand=[card_7s.copy(), card_ks.copy()])

        gs = GameState('game-norm', [
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True}
        ], difficulty='medium')
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_player_idx = 0
        gs._start_new_round()

        # Bot 1 plays 6♠
        gs.step_ai_turn()
        self.assertEqual(p1.count_card_id('phys-6s-norm'), 0)

        # Bot 2 follows suit with 7♠ (normal round)
        res2 = gs.step_ai_turn()
        self.assertFalse(res2['action']['is_attack'])
        self.assertTrue(res2['round_completed'])
        self.assertEqual(res2['last_round_result']['collection_type'], 'common')

        # 6♠ is in common pile, NOT in Bot 1 hand
        self.assertEqual(p1.count_card_id('phys-6s-norm'), 0)
        self.assertTrue(any(c['id'] == 'phys-6s-norm' for c in gs.common_pile))

        # Bot 2 won the round (7♠ > 6♠), so Bot 2 starts Round 2
        self.assertEqual(gs.current_player.id, 'bot2')
        # Bot 1 does NOT legitimately own 6♠ and cannot play it
        valid, _ = gs.current_round.can_play(p1, card_6s)
        self.assertFalse(valid)

    def test_another_player_wins_attack_round(self):
        """
        Verify that if Bot 1 plays 6♠, Bot 2 attacks, but Bot 3 played K♠ (higher spade),
        Bot 3 wins the attack round and collects 6♠. Bot 1 does NOT collect 6♠ and cannot play it.
        """
        card_6s = {'id': 'phys-6s-p1', 'rank': '6', 'suit': 'S', 'deck_index': 0}
        card_8s = {'id': 'phys-8s-p1', 'rank': '8', 'suit': 'S', 'deck_index': 0}
        card_ks = {'id': 'phys-ks-p2', 'rank': 'K', 'suit': 'S', 'deck_index': 0}
        card_as = {'id': 'phys-as-p2', 'rank': 'A', 'suit': 'S', 'deck_index': 0}
        card_qd = {'id': 'phys-qd-p3', 'rank': 'Q', 'suit': 'D', 'deck_index': 0}  # attack
        card_3d = {'id': 'phys-3d-p3', 'rank': '3', 'suit': 'D', 'deck_index': 0}

        p1 = Player(id='bot1', name='Bot 1', is_ai=True, hand=[card_6s.copy(), card_8s.copy()])
        p2 = Player(id='bot2', name='Bot 2', is_ai=True, hand=[card_ks.copy(), card_as.copy()])
        p3 = Player(id='bot3', name='Bot 3', is_ai=True, hand=[card_qd.copy(), card_3d.copy()])

        gs = GameState('game-3p', [
            {'id': 'bot1', 'name': 'Bot 1', 'is_ai': True},
            {'id': 'bot2', 'name': 'Bot 2', 'is_ai': True},
            {'id': 'bot3', 'name': 'Bot 3', 'is_ai': True}
        ], difficulty='medium')
        gs.players = [p1, p2, p3]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_player_idx = 0
        gs._start_new_round()

        # Bot 1 plays 6♠
        gs.step_ai_turn()
        self.assertEqual(p1.count_card_id('phys-6s-p1'), 0)

        # Bot 2 plays K♠ (higher starting suit)
        gs.step_ai_turn()

        # Bot 3 attacks with Q♦
        res3 = gs.step_ai_turn()
        self.assertTrue(res3['action']['is_attack'])
        self.assertTrue(res3['round_completed'])

        # Bot 2 won the attack round because K♠ > 6♠!
        self.assertEqual(res3['last_round_result']['winner_id'], 'bot2')

        # Cards went to Bot 2, NOT Bot 1!
        self.assertEqual(p1.count_card_id('phys-6s-p1'), 0)
        self.assertEqual(p2.count_card_id('phys-6s-p1'), 1)
        self.assertFalse(p1.has_card('phys-6s-p1'))
        self.assertTrue(p2.has_card('phys-6s-p1'))


if __name__ == '__main__':
    unittest.main()
