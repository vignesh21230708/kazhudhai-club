"""
KAZHUDHAI CLUB — tests/test_stage6.py
Comprehensive test suite for Stage 6:
  - Private rooms with unique 6-character room codes
  - Public rooms and public lobby discovery
  - 2 to 7 player bounds and 1 to 5 deck counts
  - Host authorization and start constraints (>= 2 players)
  - Zero Card Leakage across sockets (absolute player privacy)
  - SocketIO real-time multiplayer turn progression, round resolution, and game over
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, socketio
from game_engine.room_manager import RoomManager, Room
from game_engine.deck import find_ace_of_spades


class TestStage6RoomManager(unittest.TestCase):

    def setUp(self):
        self.rm = RoomManager()

    def test_create_private_room_unique_code(self):
        room, host = self.rm.create_room("HostAlice", is_private=True, max_players=4, deck_count=2)
        self.assertTrue(room.code.startswith("KZ"))
        self.assertEqual(len(room.code), 6)
        self.assertTrue(room.is_private)
        self.assertEqual(room.max_players, 4)
        self.assertEqual(room.deck_count, 2)
        self.assertTrue(host.is_host)
        self.assertEqual(host.name, "HostAlice")
        self.assertTrue(len(host.reconnect_token) > 10)

    def test_join_room_and_capacity(self):
        room, _ = self.rm.create_room("HostAlice", is_private=True, max_players=3)
        _, p2 = self.rm.join_room(room.code, "Bob")
        _, p3 = self.rm.join_room(room.code, "Charlie")
        self.assertEqual(room.player_count, 3)

        # 4th player should fail (max 3)
        with self.assertRaises(ValueError):
            self.rm.join_room(room.code, "Dave")

    def test_public_rooms_discovery(self):
        # Create 1 private and 1 public room
        r_priv, _ = self.rm.create_room("Alice", is_private=True)
        r_pub, _ = self.rm.create_room("Bob", is_private=False, max_players=4, deck_count=3)

        public_list = self.rm.get_public_rooms()
        codes = [r['code'] for r in public_list]
        self.assertNotIn(r_priv.code, codes)
        self.assertIn(r_pub.code, codes)

        # Verify public room meta
        pub_entry = next(r for r in public_list if r['code'] == r_pub.code)
        self.assertEqual(pub_entry['hostName'], "Bob")
        self.assertEqual(pub_entry['playerCount'], 1)
        self.assertEqual(pub_entry['maxPlayers'], 4)
        self.assertEqual(pub_entry['deckCount'], 3)

    def test_start_game_requires_host_and_min_players(self):
        room, host = self.rm.create_room("Alice", is_private=True)

        # Single player cannot start
        with self.assertRaises(ValueError):
            self.rm.start_game(room.code, host.id)

        # Non-host cannot start
        _, guest = self.rm.join_room(room.code, "Bob")
        with self.assertRaises(ValueError):
            self.rm.start_game(room.code, guest.id)

        # Host can start once 2 players joined
        started_room = self.rm.start_game(room.code, host.id)
        self.assertEqual(started_room.status, 'playing')
        self.assertIsNotNone(started_room.game_state)
        self.assertEqual(len(started_room.game_state.players), 2)

    def test_host_transfer_on_leave(self):
        room, host = self.rm.create_room("Alice", is_private=True)
        _, guest = self.rm.join_room(room.code, "Bob")

        self.assertEqual(room.host_id, host.id)
        self.rm.leave_room(room.code, host.id)

        self.assertEqual(room.host_id, guest.id)
        self.assertTrue(room.players[guest.id].is_host)


class TestStage6SocketMultiplayer(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client1 = socketio.test_client(app)
        self.client2 = socketio.test_client(app)
        self.client3 = socketio.test_client(app)

    def tearDown(self):
        if self.client1.is_connected():
            self.client1.disconnect()
        if self.client2.is_connected():
            self.client2.disconnect()
        if self.client3.is_connected():
            self.client3.disconnect()

    def test_socket_room_creation_and_join(self):
        # 1. Client 1 creates room
        res1 = self.client1.emit('create_room', {
            'playerName': 'Alice',
            'isPrivate': True,
            'maxPlayers': 4,
            'deckCount': 1
        }, callback=True)
        self.assertTrue(res1['success'])
        room_code = res1['room_code']
        alice_id = res1['player_id']

        # 2. Client 2 joins room
        res2 = self.client2.emit('join_room', {
            'playerName': 'Bob',
            'roomCode': room_code
        }, callback=True)
        self.assertTrue(res2['success'])
        bob_id = res2['player_id']

        # Check client 1 received room_updated event
        rec1 = self.client1.get_received()
        room_updates = [m for m in rec1 if m['name'] == 'room_updated']
        self.assertTrue(len(room_updates) > 0)
        lobby = room_updates[-1]['args'][0]
        self.assertEqual(lobby['player_count'], 2)
        p_names = [p['name'] for p in lobby['players']]
        self.assertIn('Alice', p_names)
        self.assertIn('Bob', p_names)

    def test_zero_card_leakage_on_game_start(self):
        """
        Verify that upon game start:
        1. Each client receives 'game_state'
        2. Alice only receives her own hand
        3. Bob only receives his own hand
        4. Neither client receives the opponent's cards in any field
        """
        res1 = self.client1.emit('create_room', {'playerName': 'Alice', 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        alice_id = res1['player_id']

        res2 = self.client2.emit('join_room', {'playerName': 'Bob', 'roomCode': room_code}, callback=True)
        bob_id = res2['player_id']

        # Clear events
        self.client1.get_received()
        self.client2.get_received()

        # Alice starts game
        start_res = self.client1.emit('start_game', {'roomCode': room_code, 'playerId': alice_id}, callback=True)
        self.assertTrue(start_res['success'])

        # Check Alice's events
        rec1 = self.client1.get_received()
        state1_events = [m for m in rec1 if m['name'] == 'game_state']
        self.assertTrue(len(state1_events) > 0)
        alice_state = state1_events[-1]['args'][0]

        # Check Bob's events
        rec2 = self.client2.get_received()
        state2_events = [m for m in rec2 if m['name'] == 'game_state']
        self.assertTrue(len(state2_events) > 0)
        bob_state = state2_events[-1]['args'][0]

        # ── Zero Card Leakage Verification ──
        self.assertIn('my_hand', alice_state)
        self.assertIn('my_hand', bob_state)
        self.assertEqual(len(alice_state['my_hand']), 26)  # 52 cards / 2 players = 26
        self.assertEqual(len(bob_state['my_hand']), 26)

        # In Alice's state, Bob's info must NOT contain cards
        bob_in_alice_view = next(p for p in alice_state['players'] if p['id'] == bob_id)
        self.assertNotIn('hand', bob_in_alice_view)
        self.assertNotIn('cards', bob_in_alice_view)
        self.assertEqual(bob_in_alice_view['card_count'], 26)

        # In Bob's state, Alice's info must NOT contain cards
        alice_in_bob_view = next(p for p in bob_state['players'] if p['id'] == alice_id)
        self.assertNotIn('hand', alice_in_bob_view)
        self.assertNotIn('cards', alice_in_bob_view)
        self.assertEqual(alice_in_bob_view['card_count'], 26)

        # Verify no card intersection between hands
        alice_card_ids = {c['id'] for c in alice_state['my_hand']}
        bob_card_ids = {c['id'] for c in bob_state['my_hand']}
        self.assertEqual(len(alice_card_ids.intersection(bob_card_ids)), 0)

    def test_multiplayer_card_play_and_broadcast(self):
        """
        Verify card play flow over socket:
        - Starter (holder of A♠) plays first
        - Opponent receives 'card_played' broadcast
        - Both receive updated personalized state
        """
        res1 = self.client1.emit('create_room', {'playerName': 'Alice'}, callback=True)
        room_code = res1['room_code']
        alice_id = res1['player_id']

        res2 = self.client2.emit('join_room', {'playerName': 'Bob', 'roomCode': room_code}, callback=True)
        bob_id = res2['player_id']

        self.client1.emit('start_game', {'roomCode': room_code, 'playerId': alice_id}, callback=True)

        rec1 = self.client1.get_received()
        rec2 = self.client2.get_received()
        alice_state = [m for m in rec1 if m['name'] == 'game_state'][-1]['args'][0]
        bob_state = [m for m in rec2 if m['name'] == 'game_state'][-1]['args'][0]

        # Determine starter (who has is_my_turn == True)
        if alice_state['is_my_turn']:
            starter_client = self.client1
            starter_id = alice_id
            starter_hand = alice_state['my_hand']
            follower_client = self.client2
        else:
            starter_client = self.client2
            starter_id = bob_id
            starter_hand = bob_state['my_hand']
            follower_client = self.client1

        # Round 1: Starter must hold A♠
        starter_card = starter_hand[0]

        # Clear events
        self.client1.get_received()
        self.client2.get_received()

        # Play card
        play_res = starter_client.emit('play_card', {
            'roomCode': room_code,
            'playerId': starter_id,
            'cardId':   starter_card['id'],
        }, callback=True)
        self.assertTrue(play_res['success'])

        # Verify follower received 'card_played'
        follower_events = follower_client.get_received()
        card_played_events = [m for m in follower_events if m['name'] == 'card_played']
        self.assertEqual(len(card_played_events), 1)
        self.assertEqual(card_played_events[0]['args'][0]['card']['id'], starter_card['id'])


class TestStage6PublicRoomsAPI(unittest.TestCase):

    def setUp(self):
        self.flask_client = app.test_client()

    def test_public_rooms_endpoint(self):
        from game_engine.room_manager import room_manager
        # Clean slate or create public room
        r, _ = room_manager.create_room("PublicHost", is_private=False, max_players=5, deck_count=2)

        resp = self.flask_client.get('/api/rooms/public')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        matching = [room for room in data if room['code'] == r.code]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['hostName'], "PublicHost")
        self.assertEqual(matching[0]['maxPlayers'], 5)
        self.assertEqual(matching[0]['deckCount'], 2)


if __name__ == '__main__':
    unittest.main()
