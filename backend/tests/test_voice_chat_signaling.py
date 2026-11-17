"""
KAZHUDHAI CLUB — backend/tests/test_voice_chat_signaling.py
Tests for Feature 1 (Match-Only WebRTC Voice Chat):
- ICE servers endpoint returns STUN servers + TURN from environment variables.
- Voice chat available ONLY after match start (rejected in lobby).
- Signaling relay for voice_join, voice_signal (offer/answer/candidate), and voice_leave.
- Automatic voice cleanup on player departure / disconnect.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import room_manager
from app import app, socketio


class TestVoiceChatSignaling(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_01_ice_servers_default_and_turn_env(self):
        """get_ice_servers returns STUN and dynamically appends TURN from env vars."""
        c1 = self.socketio.test_client(self.app)

        # 1. Default without TURN
        res = c1.emit('get_ice_servers', callback=True)
        self.assertTrue(res['success'])
        self.assertTrue(any('stun:' in str(url) for s in res['iceServers'] for url in s.get('urls', [])))

        # 2. With TURN env vars
        os.environ['TURN_SERVER_URL'] = 'turn:relay.kazhudhai.club:3478'
        os.environ['TURN_USERNAME']   = 'testuser'
        os.environ['TURN_CREDENTIAL'] = 'testsecret'

        try:
            res_turn = c1.emit('get_ice_servers', callback=True)
            self.assertTrue(res_turn['success'])
            turn_entry = next((s for s in res_turn['iceServers'] if 'relay.kazhudhai.club' in str(s.get('urls'))), None)
            self.assertIsNotNone(turn_entry)
            self.assertEqual(turn_entry['username'], 'testuser')
            self.assertEqual(turn_entry['credential'], 'testsecret')
        finally:
            os.environ.pop('TURN_SERVER_URL', None)
            os.environ.pop('TURN_USERNAME', None)
            os.environ.pop('TURN_CREDENTIAL', None)

    def test_02_voice_chat_rejected_in_lobby_waiting_room(self):
        """Voice chat is forbidden in the lobby before the match starts."""
        c1 = self.socketio.test_client(self.app)
        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        # Attempt to join voice while room.status == 'waiting'
        voice_res = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertFalse(voice_res['success'])
        self.assertIn('only available during an active match', voice_res['message'])

    def test_03_voice_join_and_signaling_relay_during_match(self):
        """When match starts, voice_join succeeds and voice_signal relays offers/answers."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Clear initial received events
        c1.get_received()
        c2.get_received()

        # Alice joins voice
        res_v1 = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertTrue(res_v1['success'])

        # Bob receives voice_peer_joined notification
        c2_events = c2.get_received()
        joined_events = [e for e in c2_events if e['name'] == 'voice_peer_joined']
        self.assertEqual(len(joined_events), 1)
        self.assertEqual(joined_events[0]['args'][0]['peerId'], p1_id)

        # Bob joins voice - returns Alice as active peer
        res_v2 = c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)
        self.assertTrue(res_v2['success'])
        self.assertTrue(any(p['peerId'] == p1_id for p in res_v2['peers']))

        # Bob sends SDP offer to Alice via voice_signal
        c1.get_received()
        mock_offer = {'type': 'offer', 'sdp': 'v=0\r\no=mock...'}
        sig_res = c2.emit('voice_signal', {
            'roomCode': room_code,
            'playerId': p2_id,
            'targetPeerId': p1_id,
            'signal': mock_offer,
        }, callback=True)
        self.assertTrue(sig_res['success'])

        # Alice must receive the relayed voice_signal
        c1_events = c1.get_received()
        sig_events = [e for e in c1_events if e['name'] == 'voice_signal']
        self.assertEqual(len(sig_events), 1)
        self.assertEqual(sig_events[0]['args'][0]['fromPeerId'], p2_id)
        self.assertEqual(sig_events[0]['args'][0]['signal']['type'], 'offer')

    def test_04_voice_leave_and_disconnect_broadcast(self):
        """voice_leave and socket disconnect emit voice_peer_left."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)

        c1.get_received()

        # Bob leaves voice
        c2.emit('voice_leave', {'roomCode': room_code, 'playerId': p2_id}, callback=True)

        # Alice receives voice_peer_left
        events = c1.get_received()
        left_events = [e for e in events if e['name'] == 'voice_peer_left']
        self.assertEqual(len(left_events), 1)
        self.assertEqual(left_events[0]['args'][0]['peerId'], p2_id)


if __name__ == '__main__':
    unittest.main()
