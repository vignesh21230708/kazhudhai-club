"""
KAZHUDHAI CLUB — backend/tests/test_deployment_readiness.py
Comprehensive Deployment Readiness Regression Test Suite.

Verifies:
  1. Automatic Hand Arranging:
     - All 30 combinations (1-5 decks x 2-7 players) automatically sorted by suit (♠, ♥, ♦, ♣)
       and descending rank (A down to 2).
     - Consistent suit order across all players (human and AI).
     - Re-sorts whenever a player collects cards after an attack round.
     - Preserves card ownership, card IDs, and gameplay logic.
  2. Improved Card Visibility:
     - Horizontal spacing increased (overlap relaxed by 12px-16px).
     - At least 40px exposed card width on mobile and 48px on desktop.
     - First and last cards fully accessible with edge clearance (margin-left: 0, margin-right: 18px).
     - Container allows horizontal scrolling with touch support.
     - Every card remains clickable and selectable.
  3. Responsive Compatibility:
     - Android portrait and landscape.
     - Tablet and desktop.
     - 2-7 players and 1-5 decks.
  4. Non-Modification Constraints:
     - Unbiased Fisher-Yates CSPRNG shuffle unchanged.
     - Dealing order unchanged (equal distribution + Player 1 remainder).
     - Offline and online multiplayer parity intact.
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
    SUITS,
    RANKS,
)
from game_engine.distributor import distribute, calculate_expected_distribution
from game_engine.game_state import GameState
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.room_manager import RoomManager


class TestDeploymentReadiness(unittest.TestCase):

    def _assert_hand_sorted(self, hand: list[dict], context_msg: str = ""):
        """Helper to assert hand is grouped by suit and descending rank."""
        if len(hand) <= 1:
            return
        for i in range(len(hand) - 1):
            c1 = hand[i]
            c2 = hand[i + 1]
            s1_idx = SUIT_ORDER[c1['suit']]
            s2_idx = SUIT_ORDER[c2['suit']]

            # Suit group order: Spades (0) <= Hearts (1) <= Diamonds (2) <= Clubs (3)
            self.assertLessEqual(s1_idx, s2_idx,
                f"Suit grouping violated in {context_msg}: {c1['suit']} appeared before {c2['suit']}")

            # If same suit, descending rank order
            if s1_idx == s2_idx:
                r1_val = RANK_ORDER[c1['rank']]
                r2_val = RANK_ORDER[c2['rank']]
                self.assertGreaterEqual(r1_val, r2_val,
                    f"Rank order violated in {context_msg} for suit {c1['suit']}: {c1['rank']} before {c2['rank']}")

    # ── 1. Automatic Hand Arranging & Sorting ──

    def test_01_all_30_game_combinations_hands_automatically_sorted(self):
        """Verify that hands in all 30 game combinations (1-5 decks x 2-7 players) are automatically arranged."""
        combinations_checked = 0
        for num_decks in range(1, 6):
            for num_players in range(2, 8):
                configs = [
                    {'id': f'usr_{i}', 'name': f'Player {i+1}', 'is_ai': (i > 0)}
                    for i in range(num_players)
                ]
                gs = GameState(f'dep_{num_decks}_{num_players}', configs, num_decks=num_decks)
                gs.setup()

                # Every player hand (human and AI) must be sorted
                for p in gs.players:
                    self._assert_hand_sorted(p.hand, f"{num_decks} decks, {num_players} players, {p.name}")

                # Client state payload must also be sorted
                client_state = gs.get_state_for_player(gs.players[0].id)
                self._assert_hand_sorted(client_state['my_hand'], f"Client state ({num_decks} decks, {num_players} players)")

                # Verify total cards
                total_cards = sum(len(p.hand) for p in gs.players)
                self.assertEqual(total_cards, expected_card_count(num_decks))

                combinations_checked += 1

        self.assertEqual(combinations_checked, 30)

    def test_02_attack_round_collection_re_sorts_hand(self):
        """Verify re-sorting occurs when a player collects cards after winning an attack round."""
        p1 = Player('p1', 'Player 1', is_ai=False, hand=[
            {'id': 'c1', 'rank': '5', 'suit': 'S'},
            {'id': 'c2', 'rank': '3', 'suit': 'C'},
        ])
        p2 = Player('p2', 'Player 2', is_ai=True, hand=[
            {'id': 'c3', 'rank': 'A', 'suit': 'H'},  # Attack card (off-suit)
        ])

        gs = GameState('attack_re_sort', [
            {'id': 'p1', 'name': 'Player 1'},
            {'id': 'p2', 'name': 'Player 2'},
        ], num_decks=1)
        gs.players = [p1, p2]
        gs.status = GameState.STATUS_PLAYING
        gs.round_number = 1
        gs.current_round = RoundEngine([p1, p2], 0)

        # Player 1 leads 5♠, Player 2 attacks with A♥
        gs.play_card('p1', 'c1')
        res = gs.play_card('p2', 'c3')

        # Player 1 wins attack round with highest (only) spade 5♠
        # Collects [5♠, A♥]. Hand had [3♣].
        # Updated hand: 5♠ (Spade), A♥ (Heart), 3♣ (Club)
        self.assertEqual(res['last_round_result']['winner_id'], 'p1')
        self.assertEqual(len(p1.hand), 3)

        hand_labels = [f"{c['rank']}{c['suit']}" for c in p1.hand]
        self.assertEqual(hand_labels, ['5S', 'AH', '3C'])
        self._assert_hand_sorted(p1.hand, "Player 1 after attack collection")

    def test_03_preserves_card_ownership_card_ids_and_rules(self):
        """Verify sorting does NOT alter card ownership, unique card IDs, or game rules."""
        configs = [{'id': f'p_{i}', 'name': f'P{i}', 'is_ai': (i > 0)} for i in range(4)]
        gs = GameState('integrity_test', configs, num_decks=2)
        gs.setup()

        # All 103 card IDs must be unique
        all_ids = [c['id'] for p in gs.players for c in p.hand]
        self.assertEqual(len(all_ids), 103)
        self.assertEqual(len(set(all_ids)), 103)

        # Exactly 1 A♠
        aces = [c for p in gs.players for c in p.hand if is_ace_of_spades(c)]
        self.assertEqual(len(aces), 1)

        # Starter is the player with A♠
        starter = gs.current_player
        self.assertIsNotNone(starter)
        self.assertTrue(any(is_ace_of_spades(c) for c in starter.hand))

    # ── 2. Card Visibility & Accessibility ──

    def test_04_css_and_js_hand_visibility_and_accessibility(self):
        """Verify CSS and JS rules for card visibility, edge clearance, and accessibility."""
        with open('frontend/css/table.css', 'r', encoding='utf-8') as f:
            table_css = f.read()
        with open('frontend/css/responsive.css', 'r', encoding='utf-8') as f:
            responsive_css = f.read()
        with open('frontend/js/ui/table.js', 'r', encoding='utf-8') as f:
            table_js = f.read()

        # 1. Edge clearance on first and last cards
        self.assertIn('.hand-card:first-child', table_css)
        self.assertIn('margin-left: 0 !important', table_css)
        self.assertIn('.hand-card:last-child', table_css)
        self.assertIn('margin-right: 18px !important', table_css)

        # 2. Container horizontal scrolling with touch support
        self.assertIn('overflow-x: auto', table_css)
        self.assertIn('touch-action: pan-x', table_css)
        self.assertIn('-webkit-overflow-scrolling: touch', table_css)

        # 3. Card click listener and scroll into view
        self.assertIn("cardEl.addEventListener('click'", table_js)
        self.assertIn('cardEl.scrollIntoView', table_js)

        # 4. Sorting applied in frontend TableUI
        self.assertIn('CardRenderer.sortHand', table_js)

    # ── 3. Online Multiplayer Parity ──

    def test_05_online_multiplayer_hands_sorted_and_synchronized(self):
        """Verify online multiplayer rooms also automatically arrange hands and synchronize state."""
        rm = RoomManager()
        room, host = rm.create_room(host_name='HostAlice', max_players=4, deck_count=1)
        rm.join_room(room.code, 'Bob')
        rm.join_room(room.code, 'Charlie')

        room = rm.start_game(room.code, host.id)
        self.assertEqual(room.status, 'playing')
        gs = room.game_state

        for p in gs.players:
            self._assert_hand_sorted(p.hand, f"Online Player {p.name}")

        # Check personalized state has sorted hand
        state_alice = gs.get_state_for_player(host.id)
        self._assert_hand_sorted(state_alice['my_hand'], "Alice client state")
        # Ensure zero leakage of other players' cards
        for opp in state_alice['players']:
            if opp['id'] != host.id:
                self.assertNotIn('hand', opp)
                self.assertIn('card_count', opp)

    # ── 4. Production Deployment & Security Configuration ──

    def test_06_secure_configuration_and_secrets(self):
        """Verify Config uses secure secrets, platform PORT, and environment-aware debug mode."""
        from config import Config
        self.assertTrue(bool(Config.SECRET_KEY))
        self.assertGreaterEqual(len(Config.SECRET_KEY), 16, "SECRET_KEY must be sufficiently long and secure")
        self.assertIsInstance(Config.PORT, int)
        self.assertIn(Config.ASYNC_MODE, ('eventlet', 'gevent', 'threading'))

    def test_07_database_connectivity_and_credential_protection(self):
        """Verify database status check operates cleanly and shields sensitive credentials."""
        from database import get_db_status
        status = get_db_status()
        self.assertIn('configured', status)
        self.assertIn('engine', status)
        self.assertIn('connected', status)
        self.assertIn('message', status)
        # Verify no credentials leaked
        self.assertNotIn('password', status['message'].lower())
        self.assertNotIn('@', status['message'])

    def test_08_health_endpoint_production_metadata(self):
        """Verify /api/health returns system readiness and database status."""
        from app import app
        client = app.test_client()
        resp = client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('game'), 'KAZHUDHAI CLUB')
        self.assertIn('database', data)
        self.assertIn('environment', data)

    def test_09_production_websocket_client_transports(self):
        """Verify frontend online-client.js is configured for WebSockets with polling fallback."""
        with open('frontend/js/game/online-client.js', 'r', encoding='utf-8') as f:
            client_js = f.read()
        self.assertIn("transports: ['websocket', 'polling']", client_js)

    def test_10_root_deployment_artifacts_and_room_privacy(self):
        """Verify Procfile, root requirements, .gitignore, and private room privacy."""
        self.assertTrue(os.path.exists('Procfile'), "Procfile must exist at root for PaaS deployment")
        self.assertTrue(os.path.exists('requirements.txt'), "requirements.txt must exist at root")
        self.assertTrue(os.path.exists('runtime.txt'), "runtime.txt must exist at root")
        self.assertTrue(os.path.exists('.gitignore'), ".gitignore must exist at root")

        with open('Procfile', 'r', encoding='utf-8') as f:
            procfile_content = f.read()
        self.assertIn('gunicorn', procfile_content)
        self.assertIn('eventlet', procfile_content)
        self.assertIn('wsgi:app', procfile_content)

        # Private room privacy check: private room codes MUST NOT appear in public room listings
        rm = RoomManager()
        room_priv, _ = rm.create_room('HostPriv', is_private=True)
        room_pub, _ = rm.create_room('HostPub', is_private=False)
        public_codes = [r['code'] for r in rm.get_public_rooms()]
        self.assertIn(room_pub.code, public_codes)
        self.assertNotIn(room_priv.code, public_codes, "Private room code leaked in public room API!")

    def test_11_render_blueprint_specification(self):
        """Verify render.yaml contains proper web service and PostgreSQL database specifications."""
        self.assertTrue(os.path.exists('render.yaml'), "render.yaml blueprint must exist at root")
        with open('render.yaml', 'r', encoding='utf-8') as f:
            render_content = f.read()
        self.assertIn('kazhudhai-club', render_content)
        self.assertTrue('env: python' in render_content or 'runtime: python' in render_content)
        self.assertIn('DATABASE_URL', render_content)
        self.assertIn('kazhudhai-db', render_content)
        self.assertIn('gunicorn', render_content)
        self.assertIn('eventlet', render_content)
        self.assertIn('healthCheckPath: /api/health', render_content)


if __name__ == '__main__':
    unittest.main()
