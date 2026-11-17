"""
KAZHUDHAI CLUB — backend/tests/test_turn_timer.py
Tests for Feature 5 (30-Second Turn Timer) and Feature 6 (Timer and Reconnection Integration):
- Server-authoritative 30s turn deadline in state.
- Card auto-selection Priority 1: highest rank card of starting suit.
- Card auto-selection Priority 2: highest rank card overall (attack) when suit missing.
- Card auto-selection Priority 3: random tie-break when multiple cards tie for highest rank.
- Round 1 A♠ rule preserved on auto-play.
- New round starter auto-plays highest rank card overall.
- Thread-safe play_lock prevents race conditions between manual play and timeout.
- Timer continues during disconnect; timeout executes auto-move if player does not return.
"""
import unittest
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.game_state import GameState
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.room_manager import room_manager
from app import app, socketio


class TestTurnTimerAndAutoPlay(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_01_priority_1_highest_card_of_starting_suit(self):
        """When player has starting suit cards, auto-play picks highest rank of that suit."""
        player = Player(id='p1', name='Alice')
        # Hand has [2H, 10H, KH] (Hearts) and [AS] (Spades)
        player.hand = [
            {'id': 'c1', 'rank': '2', 'suit': 'H'},
            {'id': 'c2', 'rank': '10', 'suit': 'H'},
            {'id': 'c3', 'rank': 'K', 'suit': 'H'},
            {'id': 'c4', 'rank': 'A', 'suit': 'S'},
        ]
        # Active round with starting suit 'H'
        current_round = RoundEngine([player], 0)
        current_round.starting_suit = 'H'

        chosen = GameState.select_auto_play_card(player, current_round, round_number=2)
        # Must pick KH (highest Heart), NOT AS!
        self.assertEqual(chosen['id'], 'c3')
        self.assertEqual(chosen['rank'], 'K')
        self.assertEqual(chosen['suit'], 'H')

    def test_02_priority_2_highest_card_overall_on_attack(self):
        """When player has no cards of starting suit, auto-play picks highest card overall."""
        player = Player(id='p1', name='Alice')
        # Starting suit is Diamonds, but player has only Spades and Clubs
        player.hand = [
            {'id': 'c1', 'rank': '3', 'suit': 'S'},
            {'id': 'c2', 'rank': 'J', 'suit': 'C'},
            {'id': 'c3', 'rank': 'A', 'suit': 'S'},
            {'id': 'c4', 'rank': '9', 'suit': 'C'},
        ]
        current_round = RoundEngine([player], 0)
        current_round.starting_suit = 'D'

        chosen = GameState.select_auto_play_card(player, current_round, round_number=2)
        # Must pick AS (highest overall card in hand)
        self.assertEqual(chosen['id'], 'c3')
        self.assertEqual(chosen['rank'], 'A')

    def test_03_priority_3_random_tie_break_among_equal_highest_ranks(self):
        """When multiple cards tie for highest rank, auto-play picks randomly among them."""
        player = Player(id='p1', name='Alice')
        # Multi-deck scenario: two Aces of Hearts, one King of Hearts
        player.hand = [
            {'id': 'c1', 'rank': 'A', 'suit': 'H'},
            {'id': 'c2', 'rank': 'A', 'suit': 'H'},
            {'id': 'c3', 'rank': 'K', 'suit': 'H'},
        ]
        current_round = RoundEngine([player], 0)
        current_round.starting_suit = 'H'

        chosen_ids = set()
        for _ in range(50):
            card = GameState.select_auto_play_card(player, current_round, round_number=2)
            chosen_ids.add(card['id'])

        # Both Ace cards c1 and c2 should be selected over 50 trials
        self.assertIn('c1', chosen_ids)
        self.assertIn('c2', chosen_ids)
        self.assertNotIn('c3', chosen_ids)

    def test_04_round_1_starter_holding_ace_of_spades(self):
        """In Round 1, starter holding A♠ must auto-play A♠ per Rule 5."""
        player = Player(id='p1', name='Alice')
        player.hand = [
            {'id': 'c1', 'rank': 'K', 'suit': 'H'},
            {'id': 'c2', 'rank': 'A', 'suit': 'S'},
            {'id': 'c3', 'rank': 'A', 'suit': 'D'},
        ]
        current_round = None  # No round started yet

        chosen = GameState.select_auto_play_card(player, current_round, round_number=1)
        self.assertEqual(chosen['id'], 'c2')
        self.assertEqual(chosen['rank'], 'A')
        self.assertEqual(chosen['suit'], 'S')

    def test_05_new_round_starter_highest_rank_overall(self):
        """When starting a new round (round > 1), auto-plays highest card overall."""
        player = Player(id='p1', name='Alice')
        player.hand = [
            {'id': 'c1', 'rank': '5', 'suit': 'H'},
            {'id': 'c2', 'rank': 'K', 'suit': 'D'},
            {'id': 'c3', 'rank': '2', 'suit': 'S'},
        ]
        current_round = None

        chosen = GameState.select_auto_play_card(player, current_round, round_number=2)
        self.assertEqual(chosen['id'], 'c2')
        self.assertEqual(chosen['rank'], 'K')

    def test_06_turn_deadline_in_game_state_and_timer_continues_on_disconnect(self):
        """turn_deadline is set on server, returned in state, and continues across disconnect."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        t1 = res1['reconnect_token']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        room = room_manager.get_room(room_code)
        self.assertIsNotNone(room.turn_deadline)
        initial_deadline = room.turn_deadline
        # Deadline should be roughly 30 seconds from now
        self.assertTrue(initial_deadline > time.time() + 20)

        # Alice disconnects
        c1.disconnect()

        # Timer deadline remains the same on server
        self.assertEqual(room.turn_deadline, initial_deadline)

        # Alice reconnects
        c1_new = self.socketio.test_client(self.app)
        c1_new.emit('reconnect_session', {'reconnectToken': t1}, callback=True)

        events = c1_new.get_received()
        state = [e for e in events if e['name'] == 'game_state'][-1]['args'][0]
        self.assertIn('turn_deadline', state)
        self.assertEqual(state['turn_deadline'], initial_deadline)
        self.assertEqual(state['turn_duration'], 30.0)

        room.cancel_turn_timer()

    def test_07_auto_play_execution_on_timeout(self):
        """When auto_play_current_turn is called, valid card is played and round advances."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        room = room_manager.get_room(room_code)
        current_turn_player = room.game_state.current_player
        initial_card_count = current_turn_player.card_count

        # Execute auto-play
        with room.play_lock:
            res = room.game_state.auto_play_current_turn()

        self.assertTrue(res['is_auto_play'])
        self.assertEqual(current_turn_player.card_count, initial_card_count - 1)
        self.assertEqual(len(room.game_state.current_round.played_cards), 1)

        room.cancel_turn_timer()

    def test_08_timer_thread_broadcasts_state_without_context_error(self):
        """When timer fires in its own background thread, state and card_played are delivered via socketio.emit."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        room = room_manager.get_room(room_code)

        # Clear initial events
        c1.get_received()
        c2.get_received()

        initial_seq = room.turn_sequence
        # Re-trigger with a fast 0.05s timer using the room's stored timeout callback
        cb = room.timeout_callback
        room.cancel_turn_timer()
        room.start_turn_timer(cb, timeout_seconds=0.05)

        # Wait for the background timer thread to execute
        time.sleep(0.25)

        # Verify turn sequence advanced
        self.assertTrue(room.turn_sequence > initial_seq)

        # Verify Alice and Bob received card_played and game_state events from the background thread!
        events1 = c1.get_received()
        cards_played_events = [e for e in events1 if e['name'] == 'card_played']
        self.assertEqual(len(cards_played_events), 1)
        self.assertTrue(cards_played_events[0]['args'][0]['is_auto_play'])

        state_events = [e for e in events1 if e['name'] == 'game_state']
        self.assertTrue(len(state_events) > 0)
        self.assertIn('my_hand', state_events[-1]['args'][0])

        events2 = c2.get_received()
        self.assertTrue(any(e['name'] == 'card_played' for e in events2))
        self.assertTrue(any(e['name'] == 'game_state' for e in events2))

        room.cancel_turn_timer()


if __name__ == '__main__':
    unittest.main()
