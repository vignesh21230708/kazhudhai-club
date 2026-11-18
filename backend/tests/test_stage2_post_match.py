"""
KAZHUDHAI CLUB — backend/tests/test_stage2_post_match.py
Stage 2 automated test suite:
  - Post-match Ready / Not Ready status toggling and live broadcasts
  - Play Again strict 4-condition validation & concurrency lock
  - Disconnect & reconnect during post-match (must select Ready again)
  - Rejection of replacement player for a missing previous-match player
  - Preservation of previous-match players and deck configuration on Play Again
  - Create New Room always available regardless of readiness/departures
  - Preservation of existing host-controlled Restart Game
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.deck import expected_card_count, is_ace_of_spades
from game_engine.room_manager import room_manager


def _force_finish_room_match(room_code):
    """Helper: configure hands so a single normal round finishes the match cleanly via play_card."""
    room = room_manager.get_room(room_code)
    gs = room.game_state
    # Every player except the last gets 1 Spade; last player gets 1 Spade + 1 Heart (becomes KAZHUDHAI)
    ranks = ['A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5']
    for idx, p in enumerate(gs.players):
        if idx < len(gs.players) - 1:
            p.hand = [{'id': f'end_s_{idx}', 'rank': ranks[idx], 'suit': 'S', 'deck_index': 0}]
        else:
            p.hand = [
                {'id': f'end_s_{idx}', 'rank': '2', 'suit': 'S', 'deck_index': 0},
                {'id': f'end_h_{idx}', 'rank': '3', 'suit': 'H', 'deck_index': 0},
            ]
    gs.current_player_idx = 0
    gs._start_new_round()


class TestStage2PostMatch(unittest.TestCase):

    def setUp(self):
        self._clients = []

    def tearDown(self):
        for c in self._clients:
            try:
                if c.is_connected():
                    c.disconnect()
            except Exception:
                pass
        self._clients.clear()

    def _new_client(self):
        c = app_module.socketio.test_client(app_module.app)
        self._clients.append(c)
        return c

    def _create_and_finish_match(self, num_players=2, deck_count=3):
        clients = [self._new_client() for _ in range(num_players)]
        res_host = clients[0].emit('create_room', {
            'playerName': 'HostP1',
            'isPrivate': True,
            'maxPlayers': max(4, num_players),
            'deckCount': deck_count,
        }, callback=True)
        self.assertTrue(res_host['success'])
        code = res_host['room_code']
        ids = [res_host['player_id']]
        tokens = [res_host['reconnect_token']]

        for i in range(1, num_players):
            rj = clients[i].emit('join_room', {
                'roomCode': code,
                'playerName': f'Player{i+1}',
            }, callback=True)
            self.assertTrue(rj['success'])
            ids.append(rj['player_id'])
            tokens.append(rj['reconnect_token'])

        rs = clients[0].emit('start_game', {'roomCode': code, 'playerId': ids[0]}, callback=True)
        self.assertTrue(rs['success'])

        room = room_manager.get_room(code)
        _force_finish_room_match(code)

        # Map player_id -> client so we play in active turn order
        id_to_client = {pid: cli for pid, cli in zip(ids, clients)}
        for _ in range(num_players + 2):
            if room.status == 'finished':
                break
            cp = room.game_state.current_player
            card_id = cp.hand[0]['id']
            pr = id_to_client[cp.id].emit('play_card', {
                'roomCode': code,
                'playerId': cp.id,
                'cardId': card_id,
            }, callback=True)
            self.assertTrue(pr['success'], f"play_card failed: {pr}")

        self.assertEqual(room.status, 'finished')
        return code, clients, ids, tokens, room

    # ── 1. Default Not Ready & Partial Ready ──

    def test_01_all_not_ready_and_one_not_ready_disable_play_again(self):
        code, clients, ids, _, room = self._create_and_finish_match(num_players=3, deck_count=2)

        # Default: all Not Ready
        status = room.get_post_match_status()
        self.assertFalse(status['can_play_again'])
        self.assertEqual(status['ready_count'], 0)
        for p in status['players']:
            self.assertFalse(p['ready'])

        res_pa = clients[0].emit('play_again', {'roomCode': code, 'playerId': ids[0]}, callback=True)
        self.assertFalse(res_pa['success'])

        # Two of three Ready -> still disabled (one Not Ready)
        r1 = clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        r2 = clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
        self.assertTrue(r1['success'] and r2['success'])
        self.assertFalse(r2['post_match_status']['can_play_again'])
        self.assertEqual(r2['post_match_status']['ready_count'], 2)

        res_pa2 = clients[1].emit('play_again', {'roomCode': code, 'playerId': ids[1]}, callback=True)
        self.assertFalse(res_pa2['success'])

    # ── 2. All Ready -> Any previous-match player triggers Play Again ──

    def test_02_all_ready_play_again_preserves_players_and_decks(self):
        code, clients, ids, _, room = self._create_and_finish_match(num_players=3, deck_count=3)
        old_match_id = room.match_id

        # Toggle Ready -> Not Ready -> Ready
        clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
        clients[2].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[2], 'ready': True}, callback=True)

        # Switching back to Not Ready immediately disables Play Again
        r_unready = clients[2].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[2], 'ready': False}, callback=True)
        self.assertFalse(r_unready['post_match_status']['can_play_again'])

        # Ready again -> enabled
        r_ready = clients[2].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[2], 'ready': True}, callback=True)
        self.assertTrue(r_ready['post_match_status']['can_play_again'])

        # Clear queues, then non-host player (Player 3) triggers Play Again
        for c in clients:
            c.get_received()

        res_pa = clients[2].emit('play_again', {'roomCode': code, 'playerId': ids[2]}, callback=True)
        self.assertTrue(res_pa['success'], f"Play Again failed: {res_pa}")
        self.assertEqual(room.status, 'playing')
        self.assertNotEqual(room.match_id, old_match_id)

        # Same previous-match players & same deck count (3 decks = 154 cards, 1 A♠)
        self.assertEqual(set(p.id for p in room.game_state.players), set(ids))
        self.assertEqual(room.game_state.num_decks, 3)
        all_cards = [c for p in room.game_state.players for c in p.hand]
        self.assertEqual(len(all_cards), expected_card_count(3))
        self.assertEqual(sum(1 for c in all_cards if is_ace_of_spades(c)), 1)
        self.assertEqual(len(room.game_state.common_pile), 0)
        self.assertEqual(len(room.game_state.rankings), 0)

        # Every player received game_started & game_state
        for c in clients:
            names = [e['name'] for e in c.get_received()]
            self.assertIn('game_started', names)
            self.assertIn('game_state', names)

    # ── 3. Player leaves after becoming Ready -> Play Again disabled ──

    def test_03_player_leaves_after_ready_disables_play_again(self):
        code, clients, ids, _, room = self._create_and_finish_match(num_players=2, deck_count=2)
        clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
        self.assertTrue(room.get_post_match_status()['can_play_again'])

        clients[0].get_received()
        clients[1].emit('leave_room', {'roomCode': code, 'playerId': ids[1], 'reason': 'left'}, callback=True)

        self.assertFalse(room.get_post_match_status()['can_play_again'])
        events = clients[0].get_received()
        pm_events = [e for e in events if e['name'] == 'post_match_status']
        self.assertTrue(len(pm_events) >= 1)
        self.assertFalse(pm_events[-1]['args'][0]['can_play_again'])

        res_pa = clients[0].emit('play_again', {'roomCode': code, 'playerId': ids[0]}, callback=True)
        self.assertFalse(res_pa['success'])

    # ── 4. Disconnect & Reconnect (same identity) -> must select Ready again ──

    def test_04_disconnect_and_same_identity_reconnect_requires_ready_again(self):
        code, clients, ids, tokens, room = self._create_and_finish_match(num_players=2, deck_count=1)
        clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
        self.assertTrue(room.get_post_match_status()['can_play_again'])

        # Player 2 disconnects temporarily
        clients[1].disconnect()
        self.assertFalse(room.get_post_match_status()['can_play_again'])
        self.assertFalse(room.post_match_ready[ids[1]])

        # Same previous-match player reconnects with original reconnect token
        reconnected_c2 = self._new_client()
        rc_res = reconnected_c2.emit('reconnect_session', {
            'reconnectToken': tokens[1],
            'roomCode': code,
            'playerId': ids[1],
        }, callback=True)
        self.assertTrue(rc_res['success'])
        self.assertEqual(rc_res['player_id'], ids[1])
        self.assertEqual(rc_res['room_status'], 'finished')

        # Must select Ready again — still NOT ready right after reconnect
        self.assertFalse(room.get_post_match_status()['can_play_again'])
        self.assertFalse(room.post_match_ready[ids[1]])

        # Re-select Ready -> Play Again becomes enabled again!
        r_again = reconnected_c2.emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
        self.assertTrue(r_again['post_match_status']['can_play_again'])

        res_pa = reconnected_c2.emit('play_again', {'roomCode': code, 'playerId': ids[1]}, callback=True)
        self.assertTrue(res_pa['success'])
        self.assertEqual(room.status, 'playing')

    # ── 5. Attempt to replace a missing player is rejected ──

    def test_05_replacement_player_cannot_join_or_unlock_play_again(self):
        code, clients, ids, _, room = self._create_and_finish_match(num_players=2, deck_count=1)
        clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        clients[1].emit('leave_room', {'roomCode': code, 'playerId': ids[1], 'reason': 'left'}, callback=True)

        # Intruder tries to join finished room with same name or different name
        intruder = self._new_client()
        j_res = intruder.emit('join_room', {
            'roomCode': code,
            'playerName': 'Player2',
        }, callback=True)
        self.assertFalse(j_res['success'])
        self.assertFalse(room.get_post_match_status()['can_play_again'])

    # ── 6. Simultaneous Play Again clicks protected by server-side lock ──

    def test_06_simultaneous_play_again_atomic_single_restart(self):
        code, clients, ids, _, room = self._create_and_finish_match(num_players=2, deck_count=2)
        clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
        clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)

        barrier = threading.Barrier(2)
        results = []
        res_lock = threading.Lock()

        def _invoke(pid):
            barrier.wait()
            try:
                room_manager.play_again(code, pid)
                with res_lock:
                    results.append(True)
            except ValueError:
                with res_lock:
                    results.append(False)

        t1 = threading.Thread(target=_invoke, args=(ids[0],))
        t2 = threading.Thread(target=_invoke, args=(ids[1],))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results.count(True), 1, f"Exactly one Play Again must succeed, got {results}")
        self.assertEqual(results.count(False), 1)
        self.assertEqual(room.status, 'playing')

    # ── 7. Create New Room always available regardless of readiness/departures ──

    def test_07_create_new_room_always_works_across_all_post_match_states(self):
        # Case A: Everyone Ready
        # Case B: Someone Not Ready
        # Case C: A player has left
        for scenario in ('all_ready', 'not_ready', 'player_left'):
            code, clients, ids, _, room = self._create_and_finish_match(num_players=2, deck_count=4)
            if scenario == 'all_ready':
                clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)
                clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)
            elif scenario == 'player_left':
                clients[1].emit('leave_room', {'roomCode': code, 'playerId': ids[1], 'reason': 'left'}, callback=True)

            # Player 1 clicks Create New Room: cleanly leaves old room and creates a brand new room
            lr = clients[0].emit('leave_room', {'roomCode': code, 'playerId': ids[0], 'reason': 'left'}, callback=True)
            self.assertTrue(lr['success'])

            cr = clients[0].emit('create_room', {
                'playerName': 'HostP1',
                'isPrivate': True,
                'maxPlayers': 6,
                'deckCount': 2,
            }, callback=True)
            self.assertTrue(cr['success'], f"Create New Room failed in scenario {scenario}: {cr}")
            self.assertNotEqual(cr['room_code'], code)
            self.assertEqual(cr['room']['max_players'], 6)
            self.assertEqual(cr['room']['deck_count'], 2)
            self.assertEqual(cr['room']['player_count'], 1)  # Did NOT carry over old players

        # Verify frontend Create New Room button & normal creation workflow exist
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()
        with open(os.path.join(base_dir, 'frontend', 'js', 'main.js'), 'r', encoding='utf-8') as f:
            main_js = f.read()
        with open(os.path.join(base_dir, 'frontend', 'js', 'ui', 'menu.js'), 'r', encoding='utf-8') as f:
            menu_js = f.read()

        self.assertIn('id="btn-create-new-room"', html)
        self.assertIn('id="btn-toggle-ready"', html)
        self.assertIn('handleCreateNewRoom', main_js)
        self.assertIn('openCreatePrivateRoomWorkflow', menu_js)
        self.assertIn('tab-create-private', menu_js)

    # ── 8. Existing Host-Controlled Restart Game Preserved ──

    def test_08_existing_host_restart_game_preserved(self):
        c1, c2 = self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host', 'maxPlayers': 4, 'deckCount': 2}, callback=True)
        code = r1['room_code']
        h_id = r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Guest'}, callback=True)
        g_id = r2['player_id']

        c1.emit('start_game', {'roomCode': code, 'playerId': h_id}, callback=True)
        room = room_manager.get_room(code)
        first_match_id = room.match_id

        # Non-host cannot trigger host Restart Game
        res_guest = c2.emit('restart_game', {'roomCode': code, 'playerId': g_id}, callback=True)
        self.assertFalse(res_guest['success'])

        # Host CAN trigger Restart Game mid-match
        res_host = c1.emit('restart_game', {'roomCode': code, 'playerId': h_id}, callback=True)
        self.assertTrue(res_host['success'])
        self.assertEqual(room.status, 'playing')
        self.assertNotEqual(room.match_id, first_match_id)


if __name__ == '__main__':
    unittest.main()
