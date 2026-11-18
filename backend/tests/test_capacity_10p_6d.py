"""
KAZHUDHAI CLUB — backend/tests/test_capacity_10p_6d.py
Comprehensive Stage 1 test suite verifying:
  - Player capacity: 2 to 10 players (online & offline)
  - Deck capacity: 1 to 6 decks (52, 103, 154, 205, 256, 307 cards; single A♠)
  - All 54 combinations (2..10 players x 1..6 decks)
  - Offline 10-player / 6-deck game with 1 human + 9 unique AI players
  - Online 10-player / 6-deck room creation, joining, full rejection, and start
  - 10-player / 6-deck multi-round gameplay card conservation
  - Frontend selectors (2–10 players, 1–6 decks) and responsive 8/9/10-player layouts
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from game_engine.deck import build_deck, expected_card_count, is_ace_of_spades
from game_engine.distributor import calculate_expected_distribution, distribute
from game_engine.game_state import GameState
from game_engine.room_manager import RoomManager
import app as app_module


class TestCapacity10Players6Decks(unittest.TestCase):

    # ── 1. Config Constraints ──

    def test_01_config_limits(self):
        self.assertEqual(Config.MIN_PLAYERS, 2)
        self.assertEqual(Config.MAX_PLAYERS, 10)
        self.assertEqual(Config.MIN_DECKS, 1)
        self.assertEqual(Config.MAX_DECKS, 6)

    # ── 2. Deck Building & Exact Card Counts (1–6 Decks) ──

    def test_02_deck_counts_and_single_ace_of_spades_1_to_6(self):
        expected_totals = {
            1: 52,
            2: 103,
            3: 154,
            4: 205,
            5: 256,
            6: 307,
        }
        for num_decks, exp_total in expected_totals.items():
            self.assertEqual(expected_card_count(num_decks), exp_total)
            deck = build_deck(num_decks, shuffle=True)
            self.assertEqual(len(deck), exp_total)

            # Exactly ONE Ace of Spades
            aces_of_spades = [c for c in deck if is_ace_of_spades(c)]
            self.assertEqual(len(aces_of_spades), 1, f"{num_decks} decks must contain exactly 1 A♠")

            # Unique physical IDs for every card
            ids = {c['id'] for c in deck}
            self.assertEqual(len(ids), exp_total, f"{num_decks} decks must have {exp_total} unique IDs")

            # Every non-A♠ (rank, suit) appears exactly num_decks times
            counts_by_face = {}
            for c in deck:
                key = (c['rank'], c['suit'])
                counts_by_face[key] = counts_by_face.get(key, 0) + 1
            self.assertEqual(len(counts_by_face), 52)
            for key, cnt in counts_by_face.items():
                if key == ('A', 'S'):
                    self.assertEqual(cnt, 1)
                else:
                    self.assertEqual(cnt, num_decks, f"Card {key} expected {num_decks} copies, got {cnt}")

    def test_03_deck_out_of_range_rejected(self):
        for bad_decks in (0, -1, 7, 10):
            with self.assertRaises(ValueError):
                expected_card_count(bad_decks)
            with self.assertRaises(ValueError):
                build_deck(bad_decks)

    def test_04_distributor_out_of_range_rejected(self):
        sample_deck = build_deck(1, shuffle=False)
        for bad_players in (0, 1, 11, 15):
            with self.assertRaises(ValueError):
                calculate_expected_distribution(1, bad_players)
            with self.assertRaises(ValueError):
                distribute(sample_deck, bad_players)

    # ── 3. All 54 Combinations (2..10 Players x 1..6 Decks) ──

    def test_05_all_54_combinations_exact_distribution_and_setup(self):
        combinations_checked = 0
        for num_decks in range(1, 7):
            exp_total = 52 * num_decks - (num_decks - 1)
            for num_players in range(2, 11):
                combinations_checked += 1

                # Verify expected distribution math: equal base + remainder from Player 1
                base = exp_total // num_players
                rem = exp_total % num_players
                expected_counts = [base + (1 if i < rem else 0) for i in range(num_players)]
                self.assertEqual(
                    calculate_expected_distribution(num_decks, num_players),
                    expected_counts,
                )

                # Full GameState setup
                configs = [
                    {'id': f'p_{i+1}', 'name': f'Player {i+1}', 'is_ai': (i > 0)}
                    for i in range(num_players)
                ]
                gs = GameState(f'combo_{num_players}p_{num_decks}d', configs, num_decks=num_decks)
                gs.setup()

                actual_counts = [len(p.hand) for p in gs.players]
                self.assertEqual(
                    actual_counts,
                    expected_counts,
                    f"Distribution mismatch for {num_players}P/{num_decks}D: {actual_counts} != {expected_counts}",
                )

                all_cards = [c for p in gs.players for c in p.hand]
                self.assertEqual(len(all_cards), exp_total)
                self.assertEqual(len({c['id'] for c in all_cards}), exp_total)

                aces = [c for c in all_cards if is_ace_of_spades(c)]
                self.assertEqual(len(aces), 1)

                # Current player must hold A♠
                cp = gs.current_player
                self.assertIsNotNone(cp)
                self.assertTrue(
                    any(is_ace_of_spades(c) for c in cp.hand),
                    f"Starting player must hold A♠ for {num_players}P/{num_decks}D",
                )

                # Personalized state: deck_count and zero leakage
                state = gs.get_state_for_player('p_1')
                self.assertEqual(state['deck_count'], num_decks)
                self.assertEqual(len(state['players']), num_players)
                self.assertEqual(len(state['my_hand']), expected_counts[0])
                for p_pub in state['players']:
                    self.assertNotIn('hand', p_pub)

        self.assertEqual(combinations_checked, 54)

    # ── 4. Offline 10-Player / 6-Deck REST API ──

    def test_06_offline_10_players_6_decks_unique_ai_names(self):
        client = app_module.app.test_client()
        resp = client.post('/api/offline/start', json={
            'playerName': 'HostUser',
            'playerCount': 10,
            'deckCount': 6,
            'difficulty': 'medium',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertEqual(data['deck_count'], 6)
        self.assertEqual(len(data['players']), 10)

        human_players = [p for p in data['players'] if not p['isAI']]
        ai_players = [p for p in data['players'] if p['isAI']]
        self.assertEqual(len(human_players), 1)
        self.assertEqual(len(ai_players), 9)

        # All 9 AI names must be unique
        ai_names = [p['name'] for p in ai_players]
        self.assertEqual(len(set(ai_names)), 9, f"Duplicate AI names detected: {ai_names}")

        # Total cards across all players + common pile + played cards == 307
        total_cards = (
            sum(p['cardCount'] for p in data['players'])
            + data.get('common_pile_count', 0)
            + len(data.get('played_cards', []))
        )
        self.assertEqual(total_cards, 307)

        # Verify expected 307 / 10 = [31]*7 + [30]*3
        self.assertEqual([p['cardCount'] for p in data['players']], [31] * 7 + [30] * 3)

    def test_07_offline_clamping_boundaries(self):
        client = app_module.app.test_client()

        # Over-maximum inputs clamp to 10 players and 6 decks
        resp_high = client.post('/api/offline/start', json={
            'playerName': 'HighCap',
            'playerCount': 14,
            'deckCount': 9,
        })
        self.assertEqual(resp_high.status_code, 200)
        high_data = resp_high.get_json()
        self.assertEqual(len(high_data['players']), 10)
        self.assertEqual(high_data['deck_count'], 6)

        # Under-minimum inputs clamp to 2 players and 1 deck
        resp_low = client.post('/api/offline/start', json={
            'playerName': 'LowCap',
            'playerCount': 1,
            'deckCount': 0,
        })
        self.assertEqual(resp_low.status_code, 200)
        low_data = resp_low.get_json()
        self.assertEqual(len(low_data['players']), 2)
        self.assertEqual(low_data['deck_count'], 1)

    # ── 5. Online 10-Player / 6-Deck RoomManager & Socket.IO ──

    def test_08_online_room_manager_10_players_6_decks(self):
        rm = RoomManager()
        room, host = rm.create_room(
            host_name='Host1',
            is_private=False,
            max_players=10,
            deck_count=6,
            sid='sid_1',
        )
        self.assertEqual(room.max_players, 10)
        self.assertEqual(room.deck_count, 6)

        # Join 9 more players (total 10)
        for i in range(2, 11):
            rm.join_room(room.code, f'Player{i}', sid=f'sid_{i}')

        self.assertEqual(len(room.players), 10)

        # 11th player must be rejected
        with self.assertRaises(ValueError) as ctx:
            rm.join_room(room.code, 'Player11', sid='sid_11')
        self.assertIn('full', str(ctx.exception).lower())

        # Start game
        rm.start_game(room.code, host.id)
        self.assertEqual(room.status, 'playing')
        self.assertEqual(room.game_state.num_decks, 6)
        self.assertEqual(len(room.game_state.players), 10)
        self.assertEqual(sum(len(p.hand) for p in room.game_state.players), 307)

        # Verify Room clamping above limits
        clamped_room, _ = rm.create_room(
            host_name='ClampHost',
            is_private=True,
            max_players=25,
            deck_count=12,
            sid='sid_clamp',
        )
        self.assertEqual(clamped_room.max_players, 10)
        self.assertEqual(clamped_room.deck_count, 6)

    def test_09_online_socketio_10_players_6_decks_flow(self):
        clients = [
            app_module.socketio.test_client(app_module.app)
            for _ in range(11)
        ]
        try:
            # Host creates 10-player, 6-deck private room
            res = clients[0].emit('create_room', {
                'playerName': 'HostP1',
                'isPrivate': True,
                'maxPlayers': 10,
                'deckCount': 6,
            }, callback=True)
            self.assertTrue(res['success'])
            room_code = res['room_code']
            host_id = res['player_id']
            self.assertEqual(res['room']['max_players'], 10)
            self.assertEqual(res['room']['deck_count'], 6)

            # Players 2..10 join
            player_ids = [host_id]
            for idx in range(1, 10):
                jres = clients[idx].emit('join_room', {
                    'playerName': f'OnlineP{idx+1}',
                    'roomCode': room_code,
                }, callback=True)
                self.assertTrue(jres['success'], f"Player {idx+1} failed to join: {jres}")
                player_ids.append(jres['player_id'])

            # 11th player rejected
            j11 = clients[10].emit('join_room', {
                'playerName': 'OverflowP11',
                'roomCode': room_code,
            }, callback=True)
            self.assertFalse(j11['success'])
            self.assertIn('full', j11['message'].lower())

            # Clear queued lobby updates before starting
            for c in clients[:10]:
                c.get_received()

            # Host starts the 10-player, 6-deck match
            sres = clients[0].emit('start_game', {
                'roomCode': room_code,
                'playerId': host_id,
            }, callback=True)
            self.assertTrue(sres['success'], f"start_game failed: {sres}")

            # Every one of the 10 players receives game_started and isolated game_state
            all_seen_card_ids = set()
            ace_spades_count = 0
            for idx in range(10):
                events = clients[idx].get_received()
                names = [e['name'] for e in events]
                self.assertIn('game_started', names)
                self.assertIn('game_state', names)

                gs_event = next(e for e in events if e['name'] == 'game_state')
                state = gs_event['args'][0]
                self.assertEqual(state['deck_count'], 6)
                self.assertEqual(len(state['players']), 10)

                # Zero hand leakage
                for p in state['players']:
                    self.assertNotIn('hand', p)

                for card in state['my_hand']:
                    all_seen_card_ids.add(card['id'])
                    if is_ace_of_spades(card):
                        ace_spades_count += 1

            self.assertEqual(len(all_seen_card_ids), 307)
            self.assertEqual(ace_spades_count, 1)
        finally:
            # Clean up room and sockets
            for c in clients:
                if c.is_connected():
                    c.disconnect()

    # ── 6. 10-Player / 6-Deck Gameplay Round Simulation ──

    def test_10_gameplay_simulation_10_players_6_decks(self):
        configs = [
            {'id': f'bot_{i+1}', 'name': f'Bot {i+1}', 'is_ai': True}
            for i in range(10)
        ]
        gs = GameState('sim_10p_6d', configs, num_decks=6, difficulty='medium')
        gs.setup()

        # Player holding A♠ must start Round 1
        starter = gs.current_player
        self.assertIsNotNone(starter)
        self.assertTrue(any(is_ace_of_spades(c) for c in starter.hand))

        # First turn is played by the A♠ holder
        first_res = gs.step_ai_turn()
        self.assertEqual(first_res['action']['player_id'], starter.id)

        # Simulate 60 turns (multiple normal & attack rounds) verifying strict card conservation
        for _ in range(60):
            if gs.status != GameState.STATUS_PLAYING:
                break
            gs.step_ai_turn()
            in_hands = sum(len(p.hand) for p in gs.players)
            in_round = len(gs.current_round.played_cards) if gs.current_round else 0
            in_common = len(gs.common_pile)
            self.assertEqual(
                in_hands + in_round + in_common,
                307,
                "Card conservation violated during 10-player / 6-deck play",
            )

    # ── 7. Frontend Selectors & Responsive Layout for 8–10 Players ──

    def test_11_frontend_selectors_and_responsive_layout_8_to_10(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            index_html = f.read()
        with open(os.path.join(base_dir, 'frontend', 'js', 'ui', 'table.js'), 'r', encoding='utf-8') as f:
            table_js = f.read()
        with open(os.path.join(base_dir, 'frontend', 'js', 'main.js'), 'r', encoding='utf-8') as f:
            main_js = f.read()
        with open(os.path.join(base_dir, 'frontend', 'css', 'table.css'), 'r', encoding='utf-8') as f:
            table_css = f.read()
        with open(os.path.join(base_dir, 'frontend', 'css', 'responsive.css'), 'r', encoding='utf-8') as f:
            responsive_css = f.read()

        # 1. Verify all 3 player-count selectors include values 2..10
        for sel_id in ('player-count-selector', 'online-private-players', 'online-public-players'):
            m = re.search(rf'id="{sel_id}"[^>]*>(.*?)</div>', index_html, re.S)
            self.assertIsNotNone(m, f"Selector #{sel_id} not found")
            vals = re.findall(r'data-value="(\d+)"', m.group(1))
            self.assertEqual(vals, [str(v) for v in range(2, 11)], f"#{sel_id} values mismatch: {vals}")

        # 2. Verify all 3 deck-count selectors include values 1..6
        for sel_id in ('deck-count-selector', 'online-private-decks', 'online-public-decks'):
            m = re.search(rf'id="{sel_id}"[^>]*>(.*?)</div>', index_html, re.S)
            self.assertIsNotNone(m, f"Selector #{sel_id} not found")
            vals = re.findall(r'data-value="(\d+)"', m.group(1))
            self.assertEqual(vals, [str(v) for v in range(1, 7)], f"#{sel_id} values mismatch: {vals}")

        # Labels updated
        self.assertNotIn('Max Players (2–7)', index_html)
        self.assertEqual(index_html.count('Max Players (2–10)'), 2)

        # 3. Verify explicit distribution cases for 7, 8, 9 opponents in table.js
        self.assertIn('case 7:', table_js)
        self.assertIn('case 8:', table_js)
        self.assertIn('case 9:', table_js)
        self.assertIn('updateDeckCount', table_js)
        self.assertIn('TableUI.updateDeckCount', main_js)

        # 4. Verify CSS rules exist for .players-8, .players-9, .players-10
        for cls in ('.players-8', '.players-9', '.players-10'):
            self.assertIn(cls, table_css)
            self.assertIn(f'.table-inner{cls}', responsive_css)

        # 5. Dimension fit verification for 8, 9, 10 players across mobile portrait, landscape & desktop
        # Mobile portrait (360 x 740): left_col=44, right_col=44, top_slot=44, gap=3, padding=8
        portrait_configs = {
            8:  {'left': 2, 'top': 3, 'right': 2},
            9:  {'left': 3, 'top': 2, 'right': 3},
            10: {'left': 3, 'top': 3, 'right': 3},
        }
        for total_p, cfg in portrait_configs.items():
            self.assertEqual(cfg['left'] + cfg['top'] + cfg['right'], total_p - 1)
            top_w = cfg['top'] * 44 + (cfg['top'] - 1) * 3
            total_w = 8 + 44 + 44 + max(top_w, 135) + 6
            self.assertLessEqual(total_w, 360, f"{total_p}P portrait width {total_w}px > 360px")
            # Vertical check for side slots in portrait (available height ~420px)
            side_h = cfg['left'] * 72 + (cfg['left'] - 1) * 2
            self.assertLessEqual(side_h, 420, f"{total_p}P portrait side height {side_h}px > 420px")

        # Mobile landscape (740 x 360): horizontal compact side pills for 9-10P (height ~24px, width 126px)
        for total_p, cfg in portrait_configs.items():
            side_w = 54 if total_p == 8 else 126
            side_slot_h = 46 if total_p == 8 else 24
            top_w = cfg['top'] * 54 + (cfg['top'] - 1) * 6
            total_w = 12 + side_w + side_w + max(top_w, 160) + 12
            self.assertLessEqual(total_w, 740, f"{total_p}P landscape width {total_w}px > 740px")
            side_h = cfg['left'] * side_slot_h + (cfg['left'] - 1) * 2
            self.assertLessEqual(side_h, 150, f"{total_p}P landscape side height {side_h}px > 150px")

        # Desktop (1366 x 768)
        for total_p, cfg in portrait_configs.items():
            top_w = cfg['top'] * 70 + (cfg['top'] - 1) * 8
            total_w = 20 + 68 + 68 + max(top_w, 260) + 12
            self.assertLessEqual(total_w, 1366, f"{total_p}P desktop width {total_w}px > 1366px")


if __name__ == '__main__':
    unittest.main()
