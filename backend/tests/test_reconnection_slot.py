"""
KAZHUDHAI CLUB — backend/tests/test_reconnection_slot.py
Tests for Secure Reconnection and Disconnection Status:
- Valid token securely restores original player slot, hand, seat, and host identity.
- Missing token cannot reclaim or take over an existing player slot.
- Invalid token cannot reclaim or take over an existing player slot.
- Another player attempting to use the same name without valid token is rejected.
- 2-minute reconnection grace period enforcement.
- Stale socket disconnect protection: old socket disconnect must NOT override newer active connection.
- Single player disconnect does not cause room-wide disconnect.
"""
import unittest
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import room_manager, GRACE_PERIOD_SECONDS
from app import app, socketio


class TestSecureReconnectionSlotAndStatus(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_01_valid_token_restores_player_slot_after_disconnect_or_refresh(self):
        """Normal reconnect using valid token restores exact player slot, seat, hand, and host identity."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'HostAlice', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        token1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'GuestBob'}, callback=True)
        p2_id = res2['player_id']

        # Start match
        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        room = room_manager.get_room(room_code)
        self.assertEqual(room.status, 'playing')

        alice_player = room.game_state._get_player(p1_id)
        initial_hand = list(alice_player.hand)
        self.assertTrue(len(initial_hand) > 0)

        # HostAlice disconnects (e.g. page refresh or network drop)
        c1.disconnect()

        room_player = room.players[p1_id]
        self.assertFalse(room_player.connected)
        self.assertIsNotNone(room_player.disconnected_at)

        # Alice reconnects using valid token
        c1_new = self.socketio.test_client(self.app)
        res_reconnect = c1_new.emit('reconnect_session', {'reconnectToken': token1}, callback=True)

        self.assertTrue(res_reconnect['success'])
        self.assertEqual(res_reconnect['player_id'], p1_id)
        self.assertTrue(res_reconnect['is_host'])

        # Player status restored to connected
        self.assertTrue(room_player.connected)
        self.assertEqual(room_player.status, 'connected')
        self.assertIsNone(room_player.disconnected_at)

        # Hand and player count remain identical
        self.assertEqual(alice_player.hand, initial_hand)
        self.assertEqual(len(room.players), 2)

    def test_02_missing_token_cannot_take_over_slot(self):
        """If token is missing, client cannot take over an existing player's slot in an active match."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'HostAlice', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'GuestBob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Bob disconnects
        c2.disconnect()

        # Reconnect session with missing token (None or empty string) is rejected
        c3 = self.socketio.test_client(self.app)
        res_rec_none = c3.emit('reconnect_session', {'reconnectToken': None}, callback=True)
        self.assertFalse(res_rec_none['success'])

        res_rec_empty = c3.emit('reconnect_session', {'reconnectToken': ''}, callback=True)
        self.assertFalse(res_rec_empty['success'])

        # Joining active room without token fails with game in progress
        res_join = c3.emit('join_room', {
            'roomCode': room_code,
            'playerName': 'GuestBob',
        }, callback=True)
        self.assertFalse(res_join['success'])
        self.assertIn('already in progress', res_join['message'])

    def test_03_invalid_token_cannot_take_over_slot(self):
        """If token is invalid or fabricated, reconnect fails and slot cannot be taken over."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'HostAlice', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'GuestBob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c2.disconnect()

        c3 = self.socketio.test_client(self.app)

        # Reconnect with invalid token fails
        res_rec = c3.emit('reconnect_session', {'reconnectToken': 'fabricated_token_12345'}, callback=True)
        self.assertFalse(res_rec['success'])
        self.assertIn('Invalid session', res_rec['message'])

        # Join room with invalid token fails
        res_join = c3.emit('join_room', {
            'roomCode': room_code,
            'playerName': 'GuestBob',
            'reconnectToken': 'fake_token_abcdef',
        }, callback=True)
        self.assertFalse(res_join['success'])
        self.assertIn('already in progress', res_join['message'])

    def test_04_another_player_attempting_same_name_cannot_take_over_slot(self):
        """A player attempting to join an active room with the same name without the token cannot take over the slot."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'HostAlice', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'GuestBob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        room = room_manager.get_room(room_code)
        bob_game_player = room.game_state._get_player(p2_id)
        original_bob_hand = list(bob_game_player.hand)

        # Bob disconnects
        c2.disconnect()

        # Another player attempts to take over Bob's slot by typing "GuestBob"
        impostor_client = self.socketio.test_client(self.app)
        res_impostor = impostor_client.emit('join_room', {
            'roomCode': room_code,
            'playerName': 'GuestBob',
        }, callback=True)

        # Must be REJECTED — impostor cannot reclaim Bob's slot!
        self.assertFalse(res_impostor['success'])
        self.assertIn('already in progress', res_impostor['message'])

        # Bob's slot, player ID, and hand remain completely untampered
        self.assertEqual(room.players[p2_id].id, p2_id)
        self.assertEqual(bob_game_player.hand, original_bob_hand)
        self.assertEqual(len(room.players), 2)

    def test_05_grace_period_enforcement(self):
        """Valid token restores within 120s grace period; rejected once grace period has elapsed."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'HostAlice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'GuestBob'}, callback=True)
        p2_id = res2['player_id']
        token2 = res2['reconnect_token']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        room = room_manager.get_room(room_code)

        # Bob disconnects
        c2.disconnect()

        # 1. Within grace period: disconnected 60s ago
        room.players[p2_id].disconnected_at = time.time() - 60.0

        c2_new = self.socketio.test_client(self.app)
        res_ok = c2_new.emit('reconnect_session', {'reconnectToken': token2}, callback=True)
        self.assertTrue(res_ok['success'])
        self.assertEqual(res_ok['player_id'], p2_id)

        # Bob disconnects again
        c2_new.disconnect()

        # 2. Grace period expired: disconnected 125s ago (> 120s)
        room.players[p2_id].disconnected_at = time.time() - (GRACE_PERIOD_SECONDS + 5.0)

        c2_expired = self.socketio.test_client(self.app)
        res_expired = c2_expired.emit('reconnect_session', {'reconnectToken': token2}, callback=True)
        self.assertFalse(res_expired['success'])

        # join_room with expired grace period also fails
        res_join_expired = c2_expired.emit('join_room', {
            'roomCode': room_code,
            'playerName': 'GuestBob',
            'reconnectToken': token2,
        }, callback=True)
        self.assertFalse(res_join_expired['success'])

    def test_06_stale_socket_disconnect_does_not_override_active_connection(self):
        """If player reconnects on new socket before old socket triggers disconnect, old disconnect is ignored."""
        c1 = self.socketio.test_client(self.app)
        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        token1 = res1['reconnect_token']

        room = room_manager.get_room(room_code)
        player = room.players[p1_id]
        old_sid = player.sid

        # New socket connects and reconnects player FIRST
        c1_new = self.socketio.test_client(self.app)
        new_res = c1_new.emit('reconnect_session', {'reconnectToken': token1}, callback=True)
        self.assertTrue(new_res['success'])
        new_sid = player.sid
        self.assertNotEqual(old_sid, new_sid)
        self.assertTrue(player.connected)

        # Now, simulated delayed disconnect of the old socket arrives
        room_manager.handle_disconnect(old_sid, reason='disconnected')

        # Player must REMAIN connected because their active socket is new_sid!
        self.assertTrue(player.connected)
        self.assertEqual(player.status, 'connected')

    def test_07_single_player_disconnect_does_not_affect_other_players(self):
        """When one player disconnects, only that player's status changes. Others remain connected."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        room = room_manager.get_room(room_code)

        # Bob disconnects
        c2.disconnect()

        # Verify: Bob is disconnected, but Alice is STILL connected
        self.assertFalse(room.players[p2_id].connected)
        self.assertTrue(room.players[p1_id].connected)
        self.assertEqual(room.players[p1_id].status, 'connected')

    def test_08_token_from_room_a_cannot_reconnect_to_room_b(self):
        """A valid token from Room A cannot be used to reconnect or reclaim a slot in Room B."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)
        c3 = self.socketio.test_client(self.app)
        c4 = self.socketio.test_client(self.app)

        # Room A
        res_a1 = c1.emit('create_room', {'playerName': 'AliceA', 'maxPlayers': 2}, callback=True)
        room_a = res_a1['room_code']
        p_a1 = res_a1['player_id']
        token_a1 = res_a1['reconnect_token']

        res_a2 = c2.emit('join_room', {'roomCode': room_a, 'playerName': 'BobA'}, callback=True)
        p_a2 = res_a2['player_id']
        token_a2 = res_a2['reconnect_token']

        c1.emit('start_game', {'roomCode': room_a, 'playerId': p_a1}, callback=True)

        # Room B
        res_b1 = c3.emit('create_room', {'playerName': 'CharlieB', 'maxPlayers': 2}, callback=True)
        room_b = res_b1['room_code']
        p_b1 = res_b1['player_id']

        res_b2 = c4.emit('join_room', {'roomCode': room_b, 'playerName': 'DaveB'}, callback=True)
        p_b2 = res_b2['player_id']
        token_b2 = res_b2['reconnect_token']

        c3.emit('start_game', {'roomCode': room_b, 'playerId': p_b1}, callback=True)

        # Dave from Room B disconnects
        c4.disconnect()

        # Attacker / client with BobA's token (from Room A) attempts to reconnect targeting Room B
        c_attacker = self.socketio.test_client(self.app)
        res_rec = c_attacker.emit('reconnect_session', {
            'reconnectToken': token_a2,
            'roomCode': room_b,
        }, callback=True)

        self.assertFalse(res_rec['success'])
        self.assertIn('Invalid session', res_rec['message'])

        # Attacker attempts join_room to Room B using BobA's token
        res_join = c_attacker.emit('join_room', {
            'roomCode': room_b,
            'playerName': 'DaveB',
            'reconnectToken': token_a2,
        }, callback=True)

        self.assertFalse(res_join['success'])
        self.assertIn('already in progress', res_join['message'])

        # Dave in Room B remains untouched and can still legitimately reconnect with his own token
        c_dave = self.socketio.test_client(self.app)
        res_dave = c_dave.emit('reconnect_session', {
            'reconnectToken': token_b2,
            'roomCode': room_b,
        }, callback=True)
        self.assertTrue(res_dave['success'])
        self.assertEqual(res_dave['player_id'], p_b2)

    def test_09_player1_token_cannot_restore_player2_slot_in_same_room(self):
        """Player 1's token cannot restore Player 2's slot even in the same room."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        token1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']
        token2 = res2['reconnect_token']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Bob disconnects
        c2.disconnect()

        # Someone tries to use token1 (Alice's token)
        c_test = self.socketio.test_client(self.app)
        res = c_test.emit('reconnect_session', {'reconnectToken': token1, 'roomCode': room_code}, callback=True)

        # It restores ALICE's slot (p1_id), NOT Bob's (p2_id)!
        self.assertTrue(res['success'])
        self.assertEqual(res['player_id'], p1_id)
        self.assertNotEqual(res['player_id'], p2_id)

        # Bob's slot is still disconnected
        room = room_manager.get_room(room_code)
        self.assertFalse(room.players[p2_id].connected)

    def test_10_joining_different_room_generates_new_identity_and_token(self):
        """Joining a different waiting room creates a fresh player identity with a distinct token."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'AliceA', 'maxPlayers': 2}, callback=True)
        room_a = res1['room_code']
        token_a = res1['reconnect_token']

        # Room B is waiting
        res2 = c2.emit('create_room', {'playerName': 'HostB', 'maxPlayers': 3}, callback=True)
        room_b = res2['room_code']

        # Client presents token_a to join Room B as 'NewGuest'
        c3 = self.socketio.test_client(self.app)
        res_join_b = c3.emit('join_room', {
            'roomCode': room_b,
            'playerName': 'NewGuest',
            'reconnectToken': token_a,
        }, callback=True)

        self.assertTrue(res_join_b['success'])
        # New player receives a distinct token, NOT token_a
        self.assertNotEqual(res_join_b['reconnect_token'], token_a)
        self.assertNotEqual(res_join_b['player_id'], res1['player_id'])
        self.assertEqual(res_join_b['room_code'], room_b)

    def test_11_reconnect_session_validates_player_id_room_code_and_token(self):
        """reconnect_session securely validates token, room_code, and player_id together."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        token1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']
        token2 = res2['reconnect_token']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Bob disconnects
        c2.disconnect()

        # 1. Valid token + correct roomCode + correct playerId -> SUCCESS
        c2_new = self.socketio.test_client(self.app)
        res_ok = c2_new.emit('reconnect_session', {
            'reconnectToken': token2,
            'roomCode': room_code,
            'playerId': p2_id,
        }, callback=True)
        self.assertTrue(res_ok['success'])
        self.assertEqual(res_ok['player_id'], p2_id)

        # Bob disconnects again
        c2_new.disconnect()

        # 2. Valid token + correct roomCode + WRONG playerId -> REJECTED
        c_impostor = self.socketio.test_client(self.app)
        res_bad_id = c_impostor.emit('reconnect_session', {
            'reconnectToken': token2,
            'roomCode': room_code,
            'playerId': 'wrong_player_id_999',
        }, callback=True)
        self.assertFalse(res_bad_id['success'])
        self.assertIn('Invalid session', res_bad_id['message'])

        # 3. Valid token + WRONG roomCode + correct playerId -> REJECTED
        res_bad_room = c_impostor.emit('reconnect_session', {
            'reconnectToken': token2,
            'roomCode': 'KZ9999',
            'playerId': p2_id,
        }, callback=True)
        self.assertFalse(res_bad_room['success'])
        self.assertIn('Invalid session', res_bad_room['message'])


if __name__ == '__main__':
    unittest.main()
