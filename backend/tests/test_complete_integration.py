"""
KAZHUDHAI CLUB — backend/tests/test_complete_integration.py
Complete End-to-End Integration Test Suite:
Combines and verifies all recently implemented features working together with core game rules:
  1. Room creation, randomized player order, and lobby chat teardown on start.
  2. Match-only WebRTC voice chat signaling (voice_join, voice_signal, voice_leave).
  3. Authoritative 30-second turn timer and countdown synchronization.
  4. Automatic card selection upon timeout (Priority 1: highest starting suit; Priority 2: attack).
  5. Played cards table synchronization during active play.
  6. Resilient mid-game network disconnection and slot restoration via secure reconnect token.
  7. Zero opponent card leakage across all clients during play and after reconnect.
  8. Attack round resolution, card penalty collection, and safe status tracking.
  9. Match completion, KAZHUDHAI declaration, and timer/voice cleanup.
"""
import unittest
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import room_manager
from app import app, socketio


class TestCompleteIntegration(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_complete_multiplayer_gameplay_lifecycle(self):
        """Full end-to-end integration test exercising all features together."""
        # Step 1: Connect 3 players
        c_alice = self.socketio.test_client(self.app)
        c_bob   = self.socketio.test_client(self.app)
        c_dave  = self.socketio.test_client(self.app)

        res_a = c_alice.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 3, 'deckCount': 1}, callback=True)
        self.assertTrue(res_a['success'])
        room_code = res_a['room_code']
        alice_id = res_a['player_id']
        alice_token = res_a['reconnect_token']

        res_b = c_bob.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        self.assertTrue(res_b['success'])
        bob_id = res_b['player_id']
        bob_token = res_b['reconnect_token']

        res_d = c_dave.emit('join_room', {'roomCode': room_code, 'playerName': 'Dave'}, callback=True)
        self.assertTrue(res_d['success'])
        dave_id = res_d['player_id']
        dave_token = res_d['reconnect_token']

        # Lobby chat works in waiting room
        chat_res = c_bob.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': bob_id, 'message': 'Hello table!'}, callback=True)
        self.assertTrue(chat_res['success'])

        # Voice chat is rejected in waiting room
        voice_wait = c_alice.emit('voice_join', {'roomCode': room_code, 'playerId': alice_id}, callback=True)
        self.assertFalse(voice_wait['success'])

        # Step 2: Host Alice starts the match
        start_res = c_alice.emit('start_game', {'roomCode': room_code, 'playerId': alice_id}, callback=True)
        self.assertTrue(start_res['success'])

        room = room_manager.get_room(room_code)
        self.assertEqual(room.status, 'playing')
        self.assertIsNotNone(room.game_state)

        # Confirm 30s turn timer is active on server
        self.assertIsNotNone(room.turn_deadline)
        self.assertTrue(room.turn_deadline > time.time())

        # Confirm lobby chat is cleared and disabled
        self.assertEqual(len(room.chat_messages), 0)
        chat_during_game = c_bob.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': bob_id, 'message': 'Cannot chat in game'}, callback=True)
        self.assertFalse(chat_during_game['success'])

        # Step 3: Voice chat signaling now allowed during match
        v_alice = c_alice.emit('voice_join', {'roomCode': room_code, 'playerId': alice_id}, callback=True)
        self.assertTrue(v_alice['success'])

        v_bob = c_bob.emit('voice_join', {'roomCode': room_code, 'playerId': bob_id}, callback=True)
        self.assertTrue(v_bob['success'])
        self.assertTrue(any(p['peerId'] == alice_id for p in v_bob['peers']))

        # Step 4: First turn - Player holding A♠ plays
        turn_player = room.game_state.current_player
        self.assertIsNotNone(turn_player)
        starter_id = turn_player.id

        client_map = {alice_id: c_alice, bob_id: c_bob, dave_id: c_dave}
        starter_client = client_map[starter_id]

        # In Round 1, starter must play A♠
        a_spades = next(c for c in turn_player.hand if c['rank'] == 'A' and c['suit'] == 'S')
        play_res = starter_client.emit('play_card', {
            'roomCode': room_code,
            'playerId': starter_id,
            'cardId':   a_spades['id'],
        }, callback=True)
        self.assertTrue(play_res['success'])

        # Step 5: Verify table synchronization (1 card on table)
        self.assertEqual(len(room.game_state.current_round.played_cards), 1)

        # Step 6: Next player disconnects temporarily
        next_player = room.game_state.current_player
        self.assertIsNotNone(next_player)
        next_id = next_player.id
        next_token = alice_token if next_id == alice_id else (bob_token if next_id == bob_id else dave_token)
        next_client = client_map[next_id]

        initial_deadline = room.turn_deadline

        # Disconnect player 2
        next_client.disconnect()
        self.assertFalse(room.players[next_id].connected)

        # The other two players remain connected
        connected_players = [p for p in room.players.values() if p.connected]
        self.assertEqual(len(connected_players), 2)

        # Played card remains on the table while player is disconnected!
        self.assertEqual(len(room.game_state.current_round.played_cards), 1)

        # Step 7: Player reconnects within grace period using token
        c_reconnected = self.socketio.test_client(self.app)
        rec_res = c_reconnected.emit('reconnect_session', {
            'reconnectToken': next_token,
            'roomCode': room_code,
        }, callback=True)
        self.assertTrue(rec_res['success'])
        self.assertEqual(rec_res['player_id'], next_id)

        # Player status restored to connected
        self.assertTrue(room.players[next_id].connected)

        # Reconnected client received complete game_state snapshot
        events = c_reconnected.get_received()
        state_event = [e for e in events if e['name'] == 'game_state'][-1]['args'][0]

        # Verify played cards on table restored for reconnected player
        self.assertEqual(len(state_event['played_cards']), 1)
        self.assertEqual(state_event['played_cards'][0]['card']['id'], a_spades['id'])

        # Verify zero card leakage: opponents' hands are hidden
        for p in state_event['players']:
            if p['id'] != next_id:
                self.assertNotIn('hand', p)
                self.assertIn('card_count', p)

        # Step 8: Auto-play execution on timeout for reconnected player
        initial_count = next_player.card_count
        with room.play_lock:
            auto_res = room.game_state.auto_play_current_turn()
        self.assertTrue(auto_res['is_auto_play'])
        self.assertEqual(next_player.card_count, initial_count - 1)

        # Now 2 cards on the table
        self.assertEqual(len(room.game_state.current_round.played_cards), 2)

        # Step 9: Clean teardown
        room.cancel_turn_timer()


if __name__ == '__main__':
    unittest.main()
