"""
KAZHUDHAI CLUB — backend/tests/test_played_cards_sync.py
Tests for Feature 4 (Preserve Played Cards After Network Reconnection):
- Table played_cards preserved on server and sent on reconnection.
- Associating each card with player_name, player_id, and is_attack status.
- Authoritative preservation of round_number, current_player_id, starting_suit, attacker_name.
- Security: Opponent hands strictly hidden on reconnect (zero leakage).
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import room_manager
from app import app, socketio


class TestPlayedCardsSync(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_01_played_cards_preserved_on_reconnect_mid_round(self):
        """When player plays a card and reconnects, played_cards on table are preserved."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        t1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']
        t2 = res2['reconnect_token']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        room = room_manager.get_room(room_code)
        starter = room.game_state.current_player
        self.assertIsNotNone(starter)

        # The starting player plays their legal card
        card_to_play = starter.hand[0]
        active_client = c1 if starter.id == p1_id else c2
        play_res = active_client.emit('play_card', {
            'roomCode': room_code,
            'playerId': starter.id,
            'cardId': card_to_play['id'],
        }, callback=True)
        self.assertTrue(play_res['success'])

        # Now 1 card is on the table
        self.assertEqual(len(room.game_state.current_round.played_cards), 1)
        played_card_entry = room.game_state.current_round.played_cards[0]
        self.assertEqual(played_card_entry['player'].id, starter.id)
        self.assertEqual(played_card_entry['card']['id'], card_to_play['id'])

        # The non-playing or playing player disconnects and reconnects
        target_token = t1 if starter.id != p1_id else t2
        target_client = c1 if starter.id != p1_id else c2
        target_client.disconnect()

        c_new = self.socketio.test_client(self.app)
        rec_res = c_new.emit('reconnect_session', {'reconnectToken': target_token}, callback=True)
        self.assertTrue(rec_res['success'])

        # Check the received game_state event
        events = c_new.get_received()
        state_events = [e for e in events if e['name'] == 'game_state']
        self.assertTrue(len(state_events) > 0)
        reconnected_state = state_events[-1]['args'][0]

        # Verify played cards on table are preserved!
        self.assertIn('played_cards', reconnected_state)
        self.assertEqual(len(reconnected_state['played_cards']), 1)
        table_card = reconnected_state['played_cards'][0]
        self.assertEqual(table_card['player_id'], starter.id)
        self.assertEqual(table_card['player_name'], starter.name)
        self.assertEqual(table_card['card']['id'], card_to_play['id'])

        # Verify round number and starting suit
        self.assertEqual(reconnected_state['round_number'], 1)
        self.assertEqual(reconnected_state['starting_suit'], card_to_play['suit'])

    def test_02_zero_opponent_hand_leakage_on_reconnect(self):
        """Reconnected state MUST NEVER expose opponent hands."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        t1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        c1.disconnect()

        c1_new = self.socketio.test_client(self.app)
        c1_new.emit('reconnect_session', {'reconnectToken': t1}, callback=True)

        events = c1_new.get_received()
        state = [e for e in events if e['name'] == 'game_state'][-1]['args'][0]

        # Alice's own hand is present
        self.assertIn('my_hand', state)
        self.assertTrue(len(state['my_hand']) > 0)

        # Opponents' hands MUST NOT be in public players list
        for p in state['players']:
            if p['id'] == p2_id:
                self.assertNotIn('hand', p)
                self.assertIn('card_count', p)


if __name__ == '__main__':
    unittest.main()
