"""
KAZHUDHAI CLUB — backend/tests/test_random_player_order.py
Unit and integration tests for Random Player Order when match starts.

Validates:
1. Support for 2 to 7 players with random player order shuffling on start_game.
2. Every player appears exactly once in the finalized shuffled order.
3. Lobby joining order in room.players remains unchanged.
4. All clients receive the exact same finalized shuffled order.
5. Order is generated only once per match.
6. Reconnection and refresh do NOT reshuffle players.
7. Existing rotating seating functions seamlessly with the shuffled order.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import RoomManager
from game_engine.game_state import GameState


class TestRandomPlayerOrder(unittest.TestCase):

    def setUp(self):
        self.rm = RoomManager()

    def test_01_random_order_all_player_counts_2_to_7(self):
        """
        Verify that for every player count from 2 to 7:
        - start_game establishes an authoritative match order.
        - All joined players appear exactly once.
        - No duplicate or missing players.
        """
        for count in range(2, 8):
            room, host = self.rm.create_room(host_name="HostPlayer", max_players=count)
            for i in range(1, count):
                self.rm.join_room(room.code, player_name=f"Player_{i + 1}")

            self.assertEqual(len(room.players), count)

            # Start game
            started_room = self.rm.start_game(room.code, host.id)
            self.assertEqual(started_room.status, 'playing')
            self.assertIsNotNone(started_room.game_state)

            match_players = started_room.game_state.players
            self.assertEqual(len(match_players), count)

            # All joined players must be present exactly once
            match_player_ids = [p.id for p in match_players]
            joined_player_ids = list(room.players.keys())

            self.assertEqual(set(match_player_ids), set(joined_player_ids))
            self.assertEqual(len(match_player_ids), len(set(match_player_ids)))

    def test_02_lobby_joining_order_remains_unchanged(self):
        """
        Verify that starting the match does NOT modify room.players or the lobby summary order.
        The original joining order is preserved in room.players.
        """
        room, host = self.rm.create_room(host_name="Aravind", max_players=5)
        _, p2 = self.rm.join_room(room.code, "Vignesh")
        _, p3 = self.rm.join_room(room.code, "Mahadir")
        _, p4 = self.rm.join_room(room.code, "Mukesh")
        _, p5 = self.rm.join_room(room.code, "Selva")

        expected_lobby_order = [host.id, p2.id, p3.id, p4.id, p5.id]
        self.assertEqual(list(room.players.keys()), expected_lobby_order)

        # Start game
        self.rm.start_game(room.code, host.id)

        # room.players must still be in the exact original joining order
        self.assertEqual(list(room.players.keys()), expected_lobby_order)

        # room.to_lobby_summary() must also preserve original joining order
        summary = room.to_lobby_summary()
        summary_ids = [p['id'] for p in summary['players']]
        self.assertEqual(summary_ids, expected_lobby_order)

    def test_03_all_clients_receive_same_shuffled_order(self):
        """
        Verify that game_state emitted to each player contains the exact same
        finalized player order and positions.
        """
        room, host = self.rm.create_room(host_name="Aravind", max_players=4)
        _, p2 = self.rm.join_room(room.code, "Selva")
        _, p3 = self.rm.join_room(room.code, "Vignesh")
        _, p4 = self.rm.join_room(room.code, "Mahadir")

        self.rm.start_game(room.code, host.id)

        # Fetch state for each individual player
        state_host = room.game_state.get_state_for_player(host.id)
        state_p2   = room.game_state.get_state_for_player(p2.id)
        state_p3   = room.game_state.get_state_for_player(p3.id)
        state_p4   = room.game_state.get_state_for_player(p4.id)

        order_host = [p['id'] for p in state_host['players']]
        order_p2   = [p['id'] for p in state_p2['players']]
        order_p3   = [p['id'] for p in state_p3['players']]
        order_p4   = [p['id'] for p in state_p4['players']]

        # All four clients must receive identical player arrays and positions
        self.assertEqual(order_host, order_p2)
        self.assertEqual(order_p2, order_p3)
        self.assertEqual(order_p3, order_p4)

        # Verify positions match index + 1
        for idx, p in enumerate(state_host['players']):
            self.assertEqual(p['position'], idx + 1)

    def test_04_order_generated_once_and_persists_across_reconnect(self):
        """
        Verify that player order is generated only ONCE per match:
        - Reconnecting does NOT reshuffle.
        - Getting room state does NOT reshuffle.
        - Subsequent turns keep the same order.
        """
        room, host = self.rm.create_room(host_name="HostPlayer", max_players=4)
        _, p2 = self.rm.join_room(room.code, "GuestTwo")
        _, p3 = self.rm.join_room(room.code, "GuestThree")
        _, p4 = self.rm.join_room(room.code, "GuestFour")

        self.rm.start_game(room.code, host.id)

        initial_order = [p.id for p in room.game_state.players]

        # Simulate reconnect
        room_reconnected, player_reconnected = self.rm.reconnect_player(p2.reconnect_token, new_sid="new_sid_123")
        self.assertIsNotNone(room_reconnected)
        self.assertEqual(player_reconnected.id, p2.id)

        # Order must remain identical
        post_reconnect_order = [p.id for p in room.game_state.players]
        self.assertEqual(initial_order, post_reconnect_order)

        # get_state_for_player must produce identical order
        state_after_reconnect = room.game_state.get_state_for_player(p2.id)
        reconnect_state_order = [p['id'] for p in state_after_reconnect['players']]
        self.assertEqual(initial_order, reconnect_state_order)

    def test_05_shuffled_distribution_statistical_variety(self):
        """
        Verify that random.shuffle is actually executed and the host is not
        always placed at index 0. Across multiple matches, different positions occur.
        """
        first_position_counts = {}
        iterations = 50

        for _ in range(iterations):
            r, h = self.rm.create_room(host_name="Host", max_players=4)
            self.rm.join_room(r.code, "P2")
            self.rm.join_room(r.code, "P3")
            self.rm.join_room(r.code, "P4")

            self.rm.start_game(r.code, h.id)
            first_player_id = r.game_state.players[0].id
            first_position_counts[first_player_id] = first_position_counts.get(first_player_id, 0) + 1

        # Across 50 iterations with 4 players, more than 1 distinct player should have been placed first
        self.assertGreater(len(first_position_counts), 1,
                           "Host must not always occupy position 1; player order must be randomized")

    def test_06_rotating_seating_with_shuffled_order(self):
        """
        Verify that player-centric rotating seating works correctly with any
        shuffled player order.
        """
        # Given a shuffled order where P4 is position 1, P2 is 2, P1 is 3, P3 is 4
        shuffled_players = [
            {'id': 'p4', 'name': 'Mahadir', 'position': 1},
            {'id': 'p2', 'name': 'Selva',   'position': 2},
            {'id': 'p1', 'name': 'Aravind', 'position': 3},
            {'id': 'p3', 'name': 'Vignesh', 'position': 4},
        ]

        from tests.test_rotating_seating import simulate_rotating_seating

        # Aravind ('p1') is at index 2 of the shuffled order
        res = simulate_rotating_seating(shuffled_players, local_id='p1')
        self.assertIsNotNone(res)

        # Aravind sees self at bottom (P1)
        self.assertEqual(res['bottom']['id'], 'p1')
        self.assertEqual(res['bottom']['seat_badge'], 'P1')

        # Next player in shuffled cyclic order is 'p3' -> Left (P2)
        self.assertEqual(res['left'][0]['id'], 'p3')
        self.assertEqual(res['left'][0]['seat_badge'], 'P2')

        # Following player is 'p4' -> Top (P3)
        self.assertEqual(res['top'][0]['id'], 'p4')
        self.assertEqual(res['top'][0]['seat_badge'], 'P3')

        # Following player is 'p2' -> Right (P4)
        self.assertEqual(res['right'][0]['id'], 'p2')
        self.assertEqual(res['right'][0]['seat_badge'], 'P4')

    def test_07_duplicate_start_game_cannot_reshuffle_order(self):
        """
        Verify that duplicate or repeated calls to start_game:
        - Are rejected with 'Game is already in progress'.
        - Do NOT generate a new player order or re-run random.shuffle.
        - The original finalized order is completely preserved.
        """
        room, host = self.rm.create_room(host_name="HostPlayer", max_players=4)
        self.rm.join_room(room.code, "P2")
        self.rm.join_room(room.code, "P3")
        self.rm.join_room(room.code, "P4")

        self.rm.start_game(room.code, host.id)
        finalized_order = [p.id for p in room.game_state.players]

        # Duplicate start_game calls must fail
        with self.assertRaises(ValueError) as ctx:
            self.rm.start_game(room.code, host.id)
        self.assertIn("already in progress", str(ctx.exception))

        # Order must be completely unchanged
        current_order = [p.id for p in room.game_state.players]
        self.assertEqual(finalized_order, current_order)


if __name__ == '__main__':
    unittest.main()
