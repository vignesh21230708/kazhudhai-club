"""
KAZHUDHAI CLUB — test_departure_activity.py
Comprehensive test suite verifying:
1. Instant leave & disconnect notifications (5000ms duration, correct messages)
2. Real-time player connection status indicators (connected, reconnecting, disconnected, left)
3. Different departure messages (leave vs disconnect vs connection lost vs reconnect)
4. Game activity history (chronological, newest first, real-time sync, zero private card leaks)
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import RoomManager, RoomPlayer
from game_engine.game_state import GameState
from sockets.game_events import register_socket_events
from flask import Flask
from flask_socketio import SocketIO


class TestDepartureAndActivity(unittest.TestCase):

    def setUp(self):
        self.rm = RoomManager()

    def test_room_player_initial_status(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=4, deck_count=1)
        self.assertEqual(host.status, 'connected')
        self.assertTrue(host.connected)
        self.assertIsNone(host.departure_reason)

        summary = host.to_summary()
        self.assertEqual(summary['status'], 'connected')
        self.assertTrue(summary['connected'])

    def test_activity_logging(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=4, deck_count=1)
        entry1 = room.add_activity('join', "Vignesh joined the room.", player_name="Vignesh", icon='🟢')
        self.assertEqual(entry1['type'], 'join')
        self.assertIn("Vignesh joined", entry1['message'])
        self.assertIn("M", entry1['timestamp'])  # AM or PM

        entry2 = room.add_activity('start', "Game started.", icon='🚀')
        self.assertEqual(len(room.activity_log), 2)

        # Check lobby summary returns newest first
        lobby = room.to_lobby_summary()
        self.assertEqual(lobby['activity_log'][0]['message'], "Game started.")
        self.assertEqual(lobby['activity_log'][1]['message'], "Vignesh joined the room.")

    def test_activity_log_capped(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=4, deck_count=1)
        for i in range(250):
            room.add_activity('test', f"Event {i}")
        self.assertEqual(len(room.activity_log), 200)
        self.assertEqual(room.activity_log[-1]['message'], "Event 249")

    def test_different_departure_reasons_in_game(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=2, deck_count=1)
        room, p2 = self.rm.join_room(room.code, "Arun")

        # Start game
        self.rm.start_game(room.code, host.id)
        self.assertEqual(room.status, 'playing')

        # Arun disconnects unexpectedly
        p2_record = room.remove_player(p2.id, reason='disconnected')
        self.assertEqual(p2_record.status, 'disconnected')
        self.assertFalse(p2_record.connected)
        self.assertEqual(p2_record.departure_reason, 'disconnected')

        # Verify game state player also updated
        p_game = room.game_state._get_player(p2.id)
        self.assertEqual(p_game.connection_status, 'disconnected')
        pub_dict = p_game.to_public_dict()
        self.assertEqual(pub_dict['connection_status'], 'disconnected')

        # Vignesh explicitly clicks exit
        p1_record = room.remove_player(host.id, reason='left')
        self.assertEqual(p1_record.status, 'left')
        self.assertEqual(p1_record.departure_reason, 'left')

        p1_game = room.game_state._get_player(host.id)
        self.assertEqual(p1_game.connection_status, 'left')

    def test_reconnect_restores_status(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=2, deck_count=1)
        room, p2 = self.rm.join_room(room.code, "Arun")
        self.rm.start_game(room.code, host.id)

        # Mark Arun as disconnected
        room.remove_player(p2.id, reason='disconnected')
        self.assertEqual(room.players[p2.id].status, 'disconnected')

        # Reconnect with token
        reconnected_room, reconnected_player = self.rm.reconnect_player(p2.reconnect_token, "new_sid_123")
        self.assertIsNotNone(reconnected_player)
        self.assertEqual(reconnected_player.status, 'connected')
        self.assertTrue(reconnected_player.connected)
        self.assertIsNone(reconnected_player.departure_reason)
        self.assertEqual(reconnected_player.sid, "new_sid_123")

        # Game state updated
        p2_game = room.game_state._get_player(p2.id)
        self.assertEqual(p2_game.connection_status, 'connected')

    def test_zero_card_leak_in_activity(self):
        room, host = self.rm.create_room(host_name="Vignesh", is_private=True, max_players=2, deck_count=1)
        room, p2 = self.rm.join_room(room.code, "Arun")
        self.rm.start_game(room.code, host.id)

        # Log typical card play activity
        room.add_activity('play', "Vignesh played 5♠.", player_name="Vignesh", icon='🃏')
        room.add_activity('attack', "⚔️ Attack triggered by Arun with 9♥!", player_name="Arun", icon='⚔️')

        # Check personalized state does NOT leak hidden opponent cards
        vignesh_state = room.game_state.get_state_for_player(host.id)
        vignesh_state['activity_log'] = room.activity_log[::-1]

        # Check that players list only has public card counts, no hidden hands
        for p in vignesh_state['players']:
            self.assertNotIn('hand', p)
            self.assertIn('card_count', p)
            self.assertIn('connection_status', p)

        # Check activity log contains only played card info, never entire hands
        for act in vignesh_state['activity_log']:
            self.assertNotIn('hand', act)
            self.assertNotIn('cards', act)


class TestSocketDepartureEvents(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test_secret'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_socket_events(self.socketio)

    def test_socket_departure_flow(self):
        client1 = self.socketio.test_client(self.app)
        client2 = self.socketio.test_client(self.app)

        # Client 1 creates room
        res1 = client1.emit('create_room', {'playerName': 'Vignesh', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        self.assertTrue(res1['success'])
        room_code = res1['room_code']
        p1_id = res1['player_id']

        # Client 2 joins room
        res2 = client2.emit('join_room', {'playerName': 'Arun', 'roomCode': room_code}, callback=True)
        self.assertTrue(res2['success'])
        p2_id = res2['player_id']

        # Check client 1 received room_updated and activity_logged for join
        received1 = client1.get_received()
        join_acts = [msg for msg in received1 if msg['name'] == 'activity_logged']
        self.assertTrue(len(join_acts) >= 1)
        self.assertIn("Arun joined the room.", join_acts[-1]['args'][0]['message'])

        # Start game
        res_start = client1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertTrue(res_start['success'])

        # Clear received queues
        client1.get_received()
        client2.get_received()

        # Client 2 loses connection
        client2.emit('client_connection_lost', {'roomCode': room_code, 'playerId': p2_id})
        received1_after_lost = client1.get_received()

        dep_events = [msg for msg in received1_after_lost if msg['name'] == 'player_departure']
        status_events = [msg for msg in received1_after_lost if msg['name'] == 'player_status_change']
        act_events = [msg for msg in received1_after_lost if msg['name'] == 'activity_logged']

        self.assertEqual(len(dep_events), 1)
        self.assertEqual(dep_events[0]['args'][0]['reason'], 'connection_lost')
        self.assertEqual(dep_events[0]['args'][0]['duration'], 5000)
        self.assertIn("🟡 Arun lost connection.", dep_events[0]['args'][0]['message'])

        self.assertEqual(len(status_events), 1)
        self.assertEqual(status_events[0]['args'][0]['status'], 'reconnecting')

        self.assertEqual(len(act_events), 1)
        self.assertEqual(act_events[0]['args'][0]['type'], 'connection_lost')

        # Client 2 leaves explicitly
        client2.emit('leave_room', {'roomCode': room_code, 'playerId': p2_id, 'reason': 'left'})
        received1_after_leave = client1.get_received()

        dep_leave = [msg for msg in received1_after_leave if msg['name'] == 'player_departure']
        self.assertTrue(len(dep_leave) >= 1)
        self.assertEqual(dep_leave[0]['args'][0]['reason'], 'left')
        self.assertIn("🔴 Arun left the game.", dep_leave[0]['args'][0]['message'])
        self.assertEqual(dep_leave[0]['args'][0]['duration'], 5000)

        # Disconnecting client 2 socket should NOT send duplicate departure
        client2.disconnect()
        received1_after_disconnect = client1.get_received()
        dep_dup = [msg for msg in received1_after_disconnect if msg['name'] == 'player_departure']
        self.assertEqual(len(dep_dup), 0, "Should prevent duplicate departure notification on socket disconnect")

        client1.disconnect()


if __name__ == '__main__':
    unittest.main()
