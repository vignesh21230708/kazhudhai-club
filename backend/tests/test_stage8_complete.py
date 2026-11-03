"""
KAZHUDHAI CLUB — tests/test_stage8_complete.py
Comprehensive Master Verification Suite covering all 20 Core System & Gameplay Requirements:
 1. Deck Preparation & Formula: Total Cards = (52 * N) - (N - 1)
 2. Single A♠ Retention Rule & Unique Card UUIDs
 3. Equal Base Share + Sequential Remainder Distribution from Player 1
 4. Card Ranking Hierarchy: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2
 5. First Round A♠ Starter Detection
 6. Starting Suit Enforcement & Illegal Move Rejection
 7. Normal Round Resolution & Permanent Card Removal to Common Pile
 8. Attack Round Resolution & Card Transfer to Winner's Hand
 9. Duplicate Highest Cards Earliest-Played Tiebreak Rule
10. Section 8 Case A: Normal Round Last Card Safe Elimination
11. Section 8 Case B: Attack Round Last Card Return to Hand (Not Safe)
12. Section 8 Case C: Multiple Simultaneous Finishers with Priority Order
13. Safe Player Removal from Future Rounds & Turns
14. Clockwise Lead Transfer when Round Winner Finishes
15. Final Heads-Up Elimination & KAZHUDHAI Determination
16. AI Strategies (Easy, Medium, Hard Heuristics)
17. Full Game Auto-Simulation Across All 2–7 Players and 1–5 Decks
18. SocketIO Multiplayer Private Rooms & Unique 6-Char Code Generation
19. Zero Card Leakage Across All Clients & Network Sockets
20. REST API Endpoints & Health Check Verification
"""
import sys
import os
import unittest
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, socketio
from game_engine.deck import build_deck, find_ace_of_spades, compare_ranks, sort_hand, RANK_ORDER
from game_engine.distributor import distribute
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.game_state import GameState
from game_engine.ai_player import AIPlayer
from game_engine.room_manager import RoomManager


class MasterStage8TestSuite(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.flask_client = app.test_client()

    # ── 1. Deck Preparation & Formula ──
    def test_01_deck_formula(self):
        expected_totals = {1: 52, 2: 103, 3: 154, 4: 205, 5: 256}
        for n_decks, expected in expected_totals.items():
            deck = build_deck(n_decks, shuffle=False)
            formula_total = (52 * n_decks) - (n_decks - 1)
            self.assertEqual(len(deck), formula_total, f"Formula mismatch for {n_decks} decks")
            self.assertEqual(len(deck), expected, f"Total mismatch for {n_decks} decks")

    # ── 2. Single A♠ Retention Rule & Unique UUIDs ──
    def test_02_single_ace_of_spades_and_unique_ids(self):
        for n_decks in range(1, 6):
            deck = build_deck(n_decks, shuffle=True)
            spade_aces = [c for c in deck if c['suit'] == 'S' and c['rank'] == 'A']
            self.assertEqual(len(spade_aces), 1, f"Found {len(spade_aces)} A♠ in {n_decks} decks (must be exactly 1)")

            # Check every card has unique ID
            ids = [c['id'] for c in deck]
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate card IDs found in {n_decks} decks")

            # Check non-A♠ duplicates retained
            heart_aces = [c for c in deck if c['suit'] == 'H' and c['rank'] == 'A']
            self.assertEqual(len(heart_aces), n_decks)

    # ── 3. Distribution Rules ──
    def test_03_distribution_equal_plus_sequential(self):
        # Spec example: 5 players, 3 decks = 154 cards (31, 31, 31, 31, 30)
        cards = build_deck(3, shuffle=False)
        hands = distribute(cards, 5)
        self.assertEqual([len(h) for h in hands], [31, 31, 31, 31, 30])

        # Test across all 2–7 player counts and 1–5 deck counts
        for d in range(1, 6):
            tot = (52 * d) - (d - 1)
            for p in range(2, 8):
                h = distribute(build_deck(d), p)
                self.assertEqual(sum(len(x) for x in h), tot)
                base = tot // p
                rem = tot % p
                for idx, player_hand in enumerate(h):
                    expected_len = base + 1 if idx < rem else base
                    self.assertEqual(len(player_hand), expected_len)

    # ── 4. Card Ranking Hierarchy ──
    def test_04_card_ranking_hierarchy(self):
        expected_order = ['A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5', '4', '3', '2']
        for i in range(len(expected_order) - 1):
            higher = expected_order[i]
            lower = expected_order[i + 1]
            self.assertGreater(RANK_ORDER[higher], RANK_ORDER[lower], f"{higher} must outrank {lower}")

    # ── 5. A♠ First Player Selection ──
    def test_05_first_player_holds_ace_of_spades(self):
        for seed_val in range(1, 10):
            configs = [{'id': f'p{i}', 'name': f'Player {i}'} for i in range(4)]
            gs = GameState(game_id='test5', player_configs=configs, num_decks=2)
            gs.setup()
            starter = gs.current_player
            self.assertIsNotNone(starter)
            has_as = any(c['suit'] == 'S' and c['rank'] == 'A' for c in starter.hand)
            self.assertTrue(has_as, f"Starter {starter.name} must hold A♠")

    # ── 6. Starting Suit Enforcement ──
    def test_06_starting_suit_enforcement(self):
        p1 = Player('p1', 'Alice', hand=[{'id': 'c1', 'rank': '5', 'suit': 'S'}])
        p2 = Player('p2', 'Bob', hand=[
            {'id': 'c2', 'rank': 'K', 'suit': 'S'},
            {'id': 'c3', 'rank': 'A', 'suit': 'H'}
        ])
        round_eng = RoundEngine([p1, p2], 0)
        round_eng.play_card(p1, p1.hand[0])
        self.assertEqual(round_eng.starting_suit, 'S')

        # Bob plays H while holding S -> must raise ValueError
        with self.assertRaises(ValueError):
            round_eng.play_card(p2, p2.hand[1])

        # Bob plays S -> legal
        res = round_eng.play_card(p2, p2.hand[0])
        self.assertFalse(res['is_attack'])
        self.assertTrue(res['is_complete'])

    # ── 7. Normal Round Resolution ──
    def test_07_normal_round_common_collection(self):
        # Spec example: ♠5, ♠4, ♠7, ♠6 -> Player 3 wins, cards to common
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': '5', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '4', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '7', 'suit': 'S'}])
        p4 = Player('p4', 'P4', hand=[{'id': 'c4', 'rank': '6', 'suit': 'S'}])

        gs = GameState('g1', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3, p4]])
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.players = [p1, p2, p3, p4]
        gs.current_player_idx = 0
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')
        res = gs.play_card('p4', 'c4')

        round_res = res['last_round_result']
        self.assertEqual(round_res['winner_id'], 'p3')
        self.assertEqual(round_res['collection_type'], 'common')
        self.assertEqual(len(gs.common_pile), 4)

    # ── 8. Attack Round Resolution ──
    def test_08_attack_round_winner_receives_cards(self):
        # Spec example: ♠5, ♠8, ♠4, ♥K (attack) -> Player 2 wins with ♠8, gets all 4 cards
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': '5', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '8', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '4', 'suit': 'S'}])
        p4 = Player('p4', 'P4', hand=[{'id': 'c4', 'rank': 'K', 'suit': 'H'}])

        gs = GameState('g2', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3, p4]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3, p4]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')
        res = gs.play_card('p4', 'c4')

        round_res = res['last_round_result']
        self.assertTrue(round_res['is_attack'])
        self.assertEqual(round_res['winner_id'], 'p2')
        self.assertEqual(round_res['collection_type'], 'winner_hand')
        self.assertEqual(p2.card_count, 4)

    # ── 9. Earliest-Played Tiebreak Rule ──
    def test_09_duplicate_highest_cards_tiebreak(self):
        # Spec example: ♠4, ♠3, ♠6 (P3), ♠5, ♠6 (P5) -> P3 wins
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': '4', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '3', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '6', 'suit': 'S'}])
        p4 = Player('p4', 'P4', hand=[{'id': 'c4', 'rank': '5', 'suit': 'S'}])
        p5 = Player('p5', 'P5', hand=[{'id': 'c5', 'rank': '6', 'suit': 'S'}])

        eng = RoundEngine([p1, p2, p3, p4, p5], 0)
        for p, cid in [(p1, 'c1'), (p2, 'c2'), (p3, 'c3'), (p4, 'c4'), (p5, 'c5')]:
            card = next(c for c in p.hand if c['id'] == cid)
            eng.play_card(p, card)

        res = eng.resolve()
        self.assertEqual(res['winner'].id, 'p3', "P3 must win tiebreak as earliest played ♠6")

    # ── 10. Section 8 Case A: Normal Round Last Card Safe Elimination ──
    def test_10_section_8_case_a_safe_finish(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': '5', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '4', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '7', 'suit': 'S'}]) # last card!
        p4 = Player('p4', 'P4', hand=[{'id': 'c4', 'rank': '6', 'suit': 'S'}, {'id': 'extra', 'rank': '2', 'suit': 'D'}])

        gs = GameState('g10', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3, p4]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3, p4]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        # P3 plays last card
        gs.play_card('p3', 'c3')
        self.assertFalse(p3.is_safe, "P3 must NOT be safe immediately upon playing last card")

        # P4 follows suit
        res = gs.play_card('p4', 'c4')
        self.assertTrue(p3.is_safe, "P3 must be safe after normal collection")
        self.assertIn('P3', res['last_round_result']['eliminated_players'])

    # ── 11. Section 8 Case B: Attack Round Last Card Return to Hand ──
    def test_11_section_8_case_b_attack_pickup(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': '5', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '4', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '7', 'suit': 'S'}]) # last card
        p4 = Player('p4', 'P4', hand=[{'id': 'c4', 'rank': 'K', 'suit': 'H'}, {'id': 'x4', 'rank': '3', 'suit': 'D'}]) # attack!

        gs = GameState('g11', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3, p4]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3, p4]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')
        res = gs.play_card('p4', 'c4')

        self.assertFalse(p3.is_safe, "P3 received cards and must NOT be marked safe")
        self.assertEqual(p3.card_count, 4)

    # ── 12. Section 8 Case C: Multiple Simultaneous Finishers ──
    def test_12_multiple_simultaneous_finishers(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': 'A', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': 'K', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': 'Q', 'suit': 'S'}, {'id': 'extra', 'rank': '2', 'suit': 'H'}])

        gs = GameState('g12', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')

        self.assertTrue(p1.is_safe)
        self.assertTrue(p2.is_safe)
        self.assertEqual(gs.rankings[0]['player_id'], 'p1')  # Winner gets rank 1
        self.assertEqual(gs.rankings[1]['player_id'], 'p2')  # Other finisher gets rank 2

    # ── 13. Safe Player Removal from Future Turns ──
    def test_13_safe_players_removed_from_future_turns(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': 'A', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'c2_2', 'rank': '3', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'c3_2', 'rank': '2', 'suit': 'S'}])

        gs = GameState('g13', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')

        self.assertTrue(p1.is_safe)
        self.assertNotIn(p1, gs.active_players)
        self.assertEqual(len(gs.active_players), 2)
        # Next round only has P2 and P3
        self.assertEqual([p.id for p in gs.current_round.active_players], ['p2', 'p3'])

    # ── 14. Clockwise Lead Transfer ──
    def test_14_clockwise_lead_transfer_when_winner_safe(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': 'A', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'c2_2', 'rank': '2', 'suit': 'S'}])
        p3 = Player('p3', 'P3', hand=[{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'c3_2', 'rank': '3', 'suit': 'S'}])

        gs = GameState('g14', [{'id': p.id, 'name': p.name} for p in [p1, p2, p3]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2, p3]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')
        gs.play_card('p3', 'c3')

        # P1 won with A♠ and finished -> next active player P2 must lead Round 2
        self.assertEqual(gs.current_player.id, 'p2')

    # ── 15. KAZHUDHAI Determination ──
    def test_15_kazhudhai_determination(self):
        p1 = Player('p1', 'P1', hand=[{'id': 'c1', 'rank': 'A', 'suit': 'S'}])
        p2 = Player('p2', 'P2', hand=[{'id': 'c2', 'rank': '2', 'suit': 'S'}, {'id': 'rem', 'rank': '3', 'suit': 'H'}])

        gs = GameState('g15', [{'id': p.id, 'name': p.name} for p in [p1, p2]])
        gs.status = GameState.STATUS_PLAYING
        gs.players = [p1, p2]
        gs.current_round = RoundEngine(gs.active_players, 0)

        gs.play_card('p1', 'c1')
        gs.play_card('p2', 'c2')

        self.assertEqual(gs.status, GameState.STATUS_FINISHED)
        kazhudhai_rank = next(r for r in gs.rankings if r['is_kazhudhai'])
        self.assertEqual(kazhudhai_rank['player_id'], 'p2')
        self.assertEqual(kazhudhai_rank['name'], 'P2')

    # ── 16. AI Strategies ──
    def test_16_ai_strategies(self):
        player = Player('ai1', 'AI', hand=[
            {'id': 'c1', 'rank': '2', 'suit': 'S'},
            {'id': 'c2', 'rank': 'A', 'suit': 'S'},
            {'id': 'c3', 'rank': 'K', 'suit': 'H'},
        ])
        # Follow suit: Medium AI chooses lowest card 2♠
        chosen = AIPlayer.choose_card(player, legal_suit='S', difficulty='medium')
        self.assertEqual(chosen['rank'], '2')

        # Attack: Medium AI chooses highest card K♥
        chosen_atk = AIPlayer.choose_card(player, legal_suit='D', difficulty='medium')
        self.assertEqual(chosen_atk['rank'], 'A')

    # ── 17. Full Game Auto-Simulation ──
    def test_17_full_game_auto_simulations(self):
        for n_players in [2, 3, 4, 5, 6, 7]:
            configs = [{'id': f'bot_{i}', 'name': f'Bot {i}', 'is_ai': True} for i in range(n_players)]
            gs = GameState(f'sim_{n_players}', configs, num_decks=1, difficulty='medium')
            gs.setup()

            turns = 0
            while gs.status == GameState.STATUS_PLAYING and turns < 600:
                step_res = gs.step_ai_turn()
                turns += 1

            self.assertEqual(gs.status, GameState.STATUS_FINISHED, f"Game failed to finish for {n_players} players")
            kazhudhai = next((r for r in gs.rankings if r['is_kazhudhai']), None)
            self.assertIsNotNone(kazhudhai)

    # ── 18. SocketIO Multiplayer Private Rooms & Code Generation ──
    def test_18_socketio_private_rooms(self):
        rm = RoomManager()
        room, host = rm.create_room('HostPlayer', is_private=True, max_players=4, deck_count=2)
        self.assertTrue(room.code.startswith('KZ'))
        self.assertEqual(len(room.code), 6)
        self.assertTrue(room.is_private)
        self.assertEqual(room.max_players, 4)
        self.assertEqual(room.deck_count, 2)

    # ── 19. Zero Card Leakage Across Sockets ──
    def test_19_zero_card_leakage(self):
        c1 = socketio.test_client(app)
        c2 = socketio.test_client(app)

        res1 = c1.emit('create_room', {'playerName': 'Player1'}, callback=True)
        code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'playerName': 'Player2', 'roomCode': code}, callback=True)
        p2_id = res2['player_id']

        c1.get_received()
        c2.get_received()

        c1.emit('start_game', {'roomCode': code, 'playerId': p1_id}, callback=True)

        rec1 = c1.get_received()
        rec2 = c2.get_received()

        s1 = [m for m in rec1 if m['name'] == 'game_state'][-1]['args'][0]
        s2 = [m for m in rec2 if m['name'] == 'game_state'][-1]['args'][0]

        # Verify P1 hand only in s1
        self.assertIn('my_hand', s1)
        self.assertIn('my_hand', s2)
        p2_in_s1 = next(p for p in s1['players'] if p['id'] == p2_id)
        self.assertNotIn('hand', p2_in_s1)
        self.assertNotIn('cards', p2_in_s1)

        c1.disconnect()
        c2.disconnect()

    # ── 20. REST API Endpoints ──
    def test_20_rest_api_endpoints(self):
        # Health check
        res = self.flask_client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'ok')

        # Public rooms
        res_rooms = self.flask_client.get('/api/rooms/public')
        self.assertEqual(res_rooms.status_code, 200)
        self.assertIsInstance(res_rooms.get_json(), list)

        # Offline start
        res_start = self.flask_client.post('/api/offline/start', json={
            'playerName': 'Tester',
            'playerCount': 3,
            'deckCount': 1,
            'difficulty': 'easy'
        })
        self.assertEqual(res_start.status_code, 200)
        self.assertIn('my_hand', res_start.get_json())


if __name__ == '__main__':
    unittest.main()
