"""
Test mobile online flow:
Verifies Socket.IO connection over polling transport,
mobile private room creation, laptop joining, validation of room code,
and bidirectional multiplayer synchronization.
"""
import unittest
from backend.app import app, socketio
from game_engine.room_manager import room_manager


class TestMobileOnlineFlow(unittest.TestCase):

    def setUp(self):
        room_manager.rooms.clear()

    def test_mobile_create_and_laptop_join_over_socket(self):
        # 1. Simulate mobile client connecting
        mobile_client = socketio.test_client(app)
        self.assertTrue(mobile_client.is_connected())

        # 2. Mobile creates private room
        mobile_client.emit('create_room', {
            'playerName': 'AndroidUser',
            'isPrivate': True,
            'maxPlayers': 4,
            'deckCount': 1,
        })
        room = list(room_manager.rooms.values())[0]
        room_code = room.code
        self.assertTrue(room_code.startswith('KZ'))
        self.assertEqual(room.host.name, 'AndroidUser')
        self.assertEqual(len(room.players), 1)

        # 3. Simulate laptop client connecting
        laptop_client = socketio.test_client(app)
        self.assertTrue(laptop_client.is_connected())

        # 4. Laptop tries invalid room code
        laptop_client.emit('join_room', {
            'playerName': 'LaptopUser',
            'roomCode': 'NONEXISTENT',
        })
        self.assertEqual(len(room.players), 1)

        # 5. Laptop joins valid room code
        laptop_client.emit('join_room', {
            'playerName': 'LaptopUser',
            'roomCode': room_code,
        })

        # 6. Check room state
        self.assertEqual(len(room.players), 2)
        p_ids = list(room.players.keys())
        self.assertEqual(room.players[p_ids[0]].name, 'AndroidUser')
        self.assertEqual(room.players[p_ids[1]].name, 'LaptopUser')

        # 7. Check room_updated event received by mobile client
        mobile_events = mobile_client.get_received()
        event_names = [e['name'] for e in mobile_events]
        self.assertIn('room_updated', event_names)
        self.assertIn('activity_logged', event_names)

        # 8. Start game by host
        mobile_client.emit('start_game', {
            'roomCode': room_code,
            'playerId': p_ids[0],
        })
        self.assertEqual(room.status, 'playing')

        # 9. Verify both received game_started and game_state
        mobile_events = mobile_client.get_received()
        laptop_events = laptop_client.get_received()
        self.assertIn('game_started', [e['name'] for e in mobile_events])
        self.assertIn('game_started', [e['name'] for e in laptop_events])
        self.assertIn('game_state', [e['name'] for e in mobile_events])
        self.assertIn('game_state', [e['name'] for e in laptop_events])

        mobile_client.disconnect()
        laptop_client.disconnect()

    def test_laptop_create_and_mobile_join(self):
        laptop_client = socketio.test_client(app)
        mobile_client = socketio.test_client(app)

        laptop_client.emit('create_room', {
            'playerName': 'LaptopHost',
            'isPrivate': True,
            'maxPlayers': 3,
            'deckCount': 1,
        })
        room = list(room_manager.rooms.values())[0]
        room_code = room.code

        mobile_client.emit('join_room', {
            'playerName': 'AndroidPlayer',
            'roomCode': room_code.lower(),  # Verify case-insensitivity
        })

        self.assertEqual(len(room.players), 2)
        laptop_events = laptop_client.get_received()
        self.assertIn('room_updated', [e['name'] for e in laptop_events])

        laptop_client.disconnect()
        mobile_client.disconnect()

    def test_mobile_session_reconnect(self):
        # When 2 players are in room and game has started
        mobile_client = socketio.test_client(app)
        laptop_client = socketio.test_client(app)

        mobile_client.emit('create_room', {
            'playerName': 'MobileUser',
            'isPrivate': True,
            'maxPlayers': 4,
            'deckCount': 1,
        })
        room = list(room_manager.rooms.values())[0]
        host = room.host
        reconnect_token = host.reconnect_token

        laptop_client.emit('join_room', {
            'playerName': 'LaptopPeer',
            'roomCode': room.code,
        })

        # Host starts game
        mobile_client.emit('start_game', {
            'roomCode': room.code,
            'playerId': host.id,
        })
        self.assertEqual(room.status, 'playing')

        # Mobile loses connection unexpectedly
        mobile_client.disconnect()
        self.assertFalse(host.connected)
        self.assertEqual(host.status, 'disconnected')

        # Reconnect with session token on new socket
        new_mobile_client = socketio.test_client(app)
        new_mobile_client.emit('reconnect_session', {
            'reconnectToken': reconnect_token,
        })
        self.assertTrue(host.connected)
        self.assertEqual(host.status, 'connected')

        new_mobile_client.disconnect()
        laptop_client.disconnect()


if __name__ == '__main__':
    unittest.main()
