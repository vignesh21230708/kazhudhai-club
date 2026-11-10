"""
KAZHUDHAI CLUB — backend/tests/test_multiplayer_improvements.py
Verification suite for the four multiplayer improvements:
1. Consistent Player Ordering across all connected devices (strictly room joining order).
2. Played cards clearing after every completed round (including consecutive wins by same player).
3. Removal of Game Activity UI button and popup panel.
4. Multiplayer Emoji Reactions (broadcast, validation, no-tamper).
"""

import unittest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.game_state import GameState
from game_engine.room_manager import room_manager, Room
from app import app, socketio


class TestMultiplayerImprovements(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        self.client = self.app.test_client()

    def test_01_consistent_player_ordering_4_players(self):
        """Verify players are strictly ordered according to room joining sequence across all devices."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)
        c3 = self.socketio.test_client(self.app)
        c4 = self.socketio.test_client(self.app)

        # Join players in known sequence: Alice (P1), Bob (P2), Charlie (P3), Dave (P4)
        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        res3 = c3.emit('join_room', {'roomCode': room_code, 'playerName': 'Charlie'}, callback=True)
        p3_id = res3['player_id']

        res4 = c4.emit('join_room', {'roomCode': room_code, 'playerName': 'Dave'}, callback=True)
        p4_id = res4['player_id']

        expected_order_ids = [p1_id, p2_id, p3_id, p4_id]
        expected_names = ['Alice', 'Bob', 'Charlie', 'Dave']

        # Start game
        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Inspect personalized game states received by EACH device
        clients = [c1, c2, c3, c4]
        for idx, client in enumerate(clients):
            events = client.get_received()
            state_events = [e for e in events if e['name'] == 'game_state']
            self.assertTrue(len(state_events) > 0, f"Device {idx+1} must receive game_state")
            state = state_events[-1]['args'][0]

            # Player sequence in state['players'] must be identical on all devices
            received_ids = [p['id'] for p in state['players']]
            received_names = [p['name'] for p in state['players']]
            positions = [p.get('position') for p in state['players']]

            self.assertEqual(received_ids, expected_order_ids,
                             f"Device {idx+1} player ID ordering mismatch: {received_ids} vs {expected_order_ids}")
            self.assertEqual(received_names, expected_names,
                             f"Device {idx+1} player names mismatch: {received_names} vs {expected_names}")
            self.assertEqual(positions, [1, 2, 3, 4],
                             f"Device {idx+1} positions mismatch: {positions}")

        c1.disconnect()
        c2.disconnect()
        c3.disconnect()
        c4.disconnect()

    def test_02_card_clearing_after_consecutive_rounds_won_by_same_player(self):
        """Verify that when a player wins consecutive rounds, previous cards are cleared."""
        configs = [
            {'id': 'P1', 'name': 'Player1', 'is_ai': False},
            {'id': 'P2', 'name': 'Player2', 'is_ai': False},
        ]
        gs = GameState('game_consec', configs, num_decks=1)
        gs.setup()

        # Custom hands for deterministic play: P1 holds K♠, A♠; P2 holds 2♠, 3♠
        p1 = gs.players[0]
        p2 = gs.players[1]
        p1.hand = [
            {'id': 'c_as', 'rank': 'A', 'suit': 'S', 'deck_index': 0},
            {'id': 'c_ks', 'rank': 'K', 'suit': 'S', 'deck_index': 0},
        ]
        p2.hand = [
            {'id': 'c_2s', 'rank': '2', 'suit': 'S', 'deck_index': 0},
            {'id': 'c_3s', 'rank': '3', 'suit': 'S', 'deck_index': 0},
        ]
        gs.current_player_idx = 0
        gs._start_new_round()

        # Round 1: P1 plays A♠, P2 plays 2♠ -> P1 wins round 1
        res1 = gs.play_card('P1', 'c_as')
        self.assertNotIn('error', res1)
        res2 = gs.play_card('P2', 'c_2s')
        self.assertTrue(res2['round_completed'])
        self.assertEqual(res2['last_round_result']['winner_id'], 'P1')

        # When new round starts, state['played_cards'] must be empty list
        state_r2 = gs.get_state_for_player('P1')
        self.assertEqual(state_r2['played_cards'], [],
                         "New round must have 0 played cards from previous round")
        self.assertEqual(state_r2['current_player_id'], 'P1',
                         "Winner P1 starts round 2")

        # Round 2: P1 plays K♠, P2 plays 3♠ -> P1 wins consecutive round 2
        res3 = gs.play_card('P1', 'c_ks')
        self.assertEqual(len(gs.current_round.played_cards), 1)
        res4 = gs.play_card('P2', 'c_3s')
        self.assertTrue(res4['round_completed'])
        self.assertEqual(res4['last_round_result']['winner_id'], 'P1')

    def test_03_game_activity_ui_removed(self):
        """Verify Game Activity button and popup are removed from frontend index.html and table.css."""
        project_root = Path(__file__).resolve().parent.parent.parent
        index_html = (project_root / "frontend" / "index.html").read_text(encoding="utf-8")
        table_css = (project_root / "frontend" / "css" / "table.css").read_text(encoding="utf-8")

        # Must NOT have in-game activity drawer or table history button
        self.assertNotIn('id="btn-table-history"', index_html)
        self.assertNotIn('id="activity-drawer"', index_html)
        self.assertNotIn('id="activity-backdrop"', index_html)

        # Must have emoji reaction button and picker
        self.assertIn('id="btn-table-emoji"', index_html)
        self.assertIn('id="emoji-picker-panel"', index_html)
        self.assertIn('.table-emoji-btn', table_css)
        self.assertIn('.emoji-picker-panel', table_css)

    def test_04_multiplayer_emoji_reactions(self):
        """Verify players can send emoji reactions and receive broadcast without altering game state."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Sender', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Receiver'}, callback=True)
        p2_id = res2['player_id']

        # Clear lobby events
        c1.get_received()
        c2.get_received()

        # Send valid emoji reaction
        res_emoji = c1.emit('send_reaction', {
            'roomCode': room_code,
            'playerId': p1_id,
            'emoji': '🔥',
        }, callback=True)
        self.assertTrue(res_emoji.get('success'), f"Emoji reaction failed: {res_emoji}")

        # Both clients must receive the reaction broadcast
        c1_events = [e for e in c1.get_received() if e['name'] == 'player_reaction']
        c2_events = [e for e in c2.get_received() if e['name'] == 'player_reaction']

        self.assertEqual(len(c1_events), 1)
        self.assertEqual(len(c2_events), 1)

        payload = c2_events[0]['args'][0]
        self.assertEqual(payload['player_id'], p1_id)
        self.assertEqual(payload['player_name'], 'Sender')
        self.assertEqual(payload['emoji'], '🔥')

        # Invalid emoji must be rejected
        res_invalid = c1.emit('send_reaction', {
            'roomCode': room_code,
            'playerId': p1_id,
            'emoji': 'INVALID_EMOJI_HACK',
        }, callback=True)
        self.assertFalse(res_invalid.get('success'))

        c1.disconnect()
        c2.disconnect()


if __name__ == '__main__':
    unittest.main()
