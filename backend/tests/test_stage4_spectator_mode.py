"""
KAZHUDHAI CLUB — backend/tests/test_stage4_spectator_mode.py
Stage 4 automated test suite:
  - Join as spectator before match start (waiting room) and auto-transition on start
  - Join as spectator during active match (live sync without interfering)
  - Reject spectator join for invalid rooms and finished rooms
  - Live spectator count and names updates on join, leave, and disconnect
  - STRICT PRIVACY: zero hidden card IDs, zero hidden ranks/suits, zero my_hand sent
  - Server-side rejection of ALL player-only actions from spectators
  - Spectators never occupy player seats, never count toward 2–10 limit, never affect dealing
  - Voice chat remains completely untouched for players and blocked for spectators
  - Existing spectators stay for post-match screen & post-match chat
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.distributor import calculate_expected_distribution
from game_engine.room_manager import room_manager


class TestStage4SpectatorMode(unittest.TestCase):

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

    # ── 1. Join Before Start, Live Updates & Auto-Transition ──

    def test_01_join_before_match_start_and_auto_transition(self):
        c1, c2, spec1, spec2 = self._new_client(), self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host', 'maxPlayers': 2, 'deckCount': 2}, callback=True)
        code, h_id = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Guest'}, callback=True)
        self.assertTrue(r2['success'])

        # Room is at max player capacity (2/2), yet spectators MUST still be able to join!
        rs1 = spec1.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'EyeOne'}, callback=True)
        self.assertTrue(rs1['success'])
        self.assertEqual(rs1['room_status'], 'waiting')
        self.assertEqual(rs1['room']['player_count'], 2)
        self.assertEqual(rs1['room']['max_players'], 2)
        self.assertEqual(rs1['room']['deck_count'], 2)
        self.assertEqual(rs1['spectator_count'], 1)
        self.assertEqual([s['name'] for s in rs1['spectators']], ['EyeOne'])

        rs2 = spec2.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'EyeTwo'}, callback=True)
        self.assertTrue(rs2['success'])
        self.assertEqual(rs2['spectator_count'], 2)
        self.assertEqual({s['name'] for s in rs2['spectators']}, {'EyeOne', 'EyeTwo'})

        room = room_manager.get_room(code)
        self.assertEqual(len(room.players), 2)
        self.assertEqual(len(room.spectators), 2)

        for c in (c1, c2, spec1, spec2):
            c.get_received()

        # Host starts match -> spectators auto-receive game_started + sanitized spectator_state
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': h_id}, callback=True)['success'])

        # Card distribution unaffected by spectators (2 decks = 103 cards -> [52, 51])
        self.assertEqual([len(p.hand) for p in room.game_state.players], calculate_expected_distribution(2, 2))

        for sc in (spec1, spec2):
            evts = sc.get_received()
            names = [e['name'] for e in evts]
            self.assertIn('game_started', names)
            self.assertIn('spectator_state', names)
            self.assertNotIn('game_state', names)

    # ── 2. Join During Active Match & Zero Hidden Card Leakage ──

    def test_02_join_during_active_match_and_strict_privacy(self):
        c1, c2 = self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 4, 'deckCount': 2}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        id2 = r2['player_id']
        c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)

        room = room_manager.get_room(code)
        match_id_before = room.match_id

        # Collect ALL hidden card IDs currently in players' hands
        hidden_card_ids = {c['id'] for p in room.game_state.players for c in p.hand}
        self.assertEqual(len(hidden_card_ids), 103)

        # Spectator joins mid-match
        spec = self._new_client()
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'MidWatcher'}, callback=True)
        self.assertTrue(rs['success'])
        self.assertEqual(rs['room_status'], 'playing')
        self.assertEqual(room.match_id, match_id_before)  # Did NOT restart match

        spec_state = rs['spectator_state']
        self.assertIsNotNone(spec_state)
        self.assertTrue(spec_state['is_spectator'])
        self.assertNotIn('my_hand', spec_state)
        self.assertEqual(len(spec_state['players']), 2)
        for p in spec_state['players']:
            self.assertNotIn('hand', p)
            self.assertGreater(p['cardCount'], 0)

        # CRITICAL SECURITY CHECK: Zero hidden card IDs anywhere in serialized spectator payload!
        serialized = json.dumps(rs)
        for cid in hidden_card_ids:
            self.assertNotIn(cid, serialized, f"Hidden card ID {cid} leaked to spectator!")

        # Spectator calling get_room_state still receives ONLY spectator_state (never game_state)
        spec.get_received()
        gr = spec.emit('get_room_state', {'roomCode': code, 'playerId': rs['spectator_id']}, callback=True)
        self.assertTrue(gr['success'])
        evts = spec.get_received()
        self.assertNotIn('game_state', [e['name'] for e in evts])
        spec_evts = [e['args'][0] for e in evts if e['name'] == 'spectator_state']
        self.assertEqual(len(spec_evts), 1)
        serialized2 = json.dumps(spec_evts[0])
        for cid in hidden_card_ids:
            self.assertNotIn(cid, serialized2)

        # When a player plays a card, spectator receives live update with ONLY that face-up played card
        cp = room.game_state.current_player
        played_card = cp.hand[0]
        remaining_hidden_ids = hidden_card_ids - {played_card['id']}
        spec.get_received()
        actor = c1 if cp.id == id1 else c2
        self.assertTrue(actor.emit('play_card', {'roomCode': code, 'playerId': cp.id, 'cardId': played_card['id']}, callback=True)['success'])

        live_evts = spec.get_received()
        self.assertIn('card_played', [e['name'] for e in live_evts])
        self.assertIn('spectator_state', [e['name'] for e in live_evts])
        self.assertNotIn('game_state', [e['name'] for e in live_evts])
        latest_spec_state = [e['args'][0] for e in live_evts if e['name'] == 'spectator_state'][-1]
        self.assertEqual(len(latest_spec_state['played_cards']), 1)
        self.assertEqual(latest_spec_state['played_cards'][0]['card']['id'], played_card['id'])

        serialized_live = json.dumps(latest_spec_state)
        for cid in remaining_hidden_ids:
            self.assertNotIn(cid, serialized_live)

    # ── 3. Reject Invalid Rooms & Finished Rooms; Existing Spectators Remain for Post-Match ──

    def test_03_reject_invalid_and_finished_rooms_and_keep_existing_spectator(self):
        bad_spec = self._new_client()
        r_bad = bad_spec.emit('join_as_spectator', {'roomCode': 'KZ9999', 'spectatorName': 'Lost'}, callback=True)
        self.assertFalse(r_bad['success'])
        self.assertIn('does not exist', r_bad['message'].lower())

        # Start and finish a room with an existing spectator
        c1, c2, existing_spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'P1'}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'P2'}, callback=True)
        id2 = r2['player_id']
        rs = existing_spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'EarlyEye'}, callback=True)
        self.assertTrue(rs['success'])
        spec_id = rs['spectator_id']

        c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)
        room = room_manager.get_room(code)
        gs = room.game_state
        gs.players[0].hand = [{'id': 'f_1', 'rank': 'A', 'suit': 'S', 'deck_index': 0}]
        gs.players[1].hand = [
            {'id': 'f_2', 'rank': 'K', 'suit': 'S', 'deck_index': 0},
            {'id': 'f_3', 'rank': '2', 'suit': 'H', 'deck_index': 0},
        ]
        gs.current_player_idx = 0
        gs._start_new_round()

        existing_spec.get_received()
        id_to_c = {id1: c1, id2: c2}
        for _ in range(2):
            cp = gs.current_player
            id_to_c[cp.id].emit('play_card', {'roomCode': code, 'playerId': cp.id, 'cardId': cp.hand[0]['id']}, callback=True)

        self.assertEqual(room.status, 'finished')

        # Existing spectator received game_over and can send post-match chat
        spec_evts = existing_spec.get_received()
        self.assertIn('game_over', [e['name'] for e in spec_evts])
        r_chat = existing_spec.emit('send_chat_message', {
            'roomCode': code, 'senderId': spec_id, 'stage': 'post_match', 'message': 'GG everyone!'
        }, callback=True)
        self.assertTrue(r_chat['success'])
        self.assertEqual(r_chat['message']['display_name'], '[Spectator] EarlyEye')

        # NEW spectator join after match finish MUST be rejected
        late_spec = self._new_client()
        r_late = late_spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'LateEye'}, callback=True)
        self.assertFalse(r_late['success'])
        self.assertIn('finished', r_late['message'].lower())

    # ── 4. Server-Side Rejection of All Player-Only Actions & Voice Isolation ──

    def test_04_spectator_cannot_perform_player_actions_or_join_voice(self):
        c1, c2, spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Alice'}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        id2 = r2['player_id']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Sneaky'}, callback=True)
        spec_id = rs['spectator_id']

        # Spectator cannot start game
        self.assertFalse(spec.emit('start_game', {'roomCode': code, 'playerId': spec_id}, callback=True)['success'])

        # Host starts game
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        room = room_manager.get_room(code)
        any_card_id = room.game_state.players[0].hand[0]['id']

        # Spectator cannot play card, restart game, react, join voice, or signal voice
        self.assertFalse(spec.emit('play_card', {'roomCode': code, 'playerId': spec_id, 'cardId': any_card_id}, callback=True)['success'])
        self.assertFalse(spec.emit('restart_game', {'roomCode': code, 'playerId': spec_id}, callback=True)['success'])
        self.assertFalse(spec.emit('send_reaction', {'roomCode': code, 'playerId': spec_id, 'emoji': '🔥'}, callback=True)['success'])
        self.assertFalse(spec.emit('voice_join', {'roomCode': code, 'playerId': spec_id}, callback=True)['success'])
        self.assertFalse(spec.emit('voice_signal', {'roomCode': code, 'playerId': spec_id, 'targetPeerId': id1, 'signal': {'type': 'offer'}}, callback=True)['success'])

        # Meanwhile real players' voice chat works completely unchanged!
        vj1 = c1.emit('voice_join', {'roomCode': code, 'playerId': id1}, callback=True)
        vj2 = c2.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)
        self.assertTrue(vj1['success'] and vj2['success'])
        self.assertEqual([p['peerId'] for p in vj2['peers']], [id1])

    # ── 5. Live Spectator Count & Names Update on Leave and Disconnect ──

    def test_05_spectator_list_updates_live_on_leave_and_disconnect(self):
        c1, c2, s1, s2 = self._new_client(), self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host'}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        c2.emit('join_room', {'roomCode': code, 'playerName': 'Guest'}, callback=True)
        c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)

        rs1 = s1.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'SpecA'}, callback=True)
        rs2 = s2.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'SpecB'}, callback=True)
        self.assertEqual(rs2['spectator_count'], 2)

        c1.get_received()
        # SpecA explicitly leaves
        s1.emit('leave_spectator', {'roomCode': code, 'spectatorId': rs1['spectator_id']}, callback=True)
        evts = [e['args'][0] for e in c1.get_received() if e['name'] == 'spectators_updated']
        self.assertEqual(evts[-1]['spectator_count'], 1)
        self.assertEqual([s['name'] for s in evts[-1]['spectators']], ['SpecB'])

        # SpecB disconnects abruptly
        s2.disconnect()
        evts2 = [e['args'][0] for e in c1.get_received() if e['name'] == 'spectators_updated']
        self.assertEqual(evts2[-1]['spectator_count'], 0)
        self.assertEqual(evts2[-1]['spectators'], [])

    # ── 6. 10-Player Room + Spectators (Stage 1 + Stage 4 Integration) ──

    def test_06_ten_players_plus_spectators_do_not_collide(self):
        players = [self._new_client() for _ in range(10)]
        r0 = players[0].emit('create_room', {'playerName': 'P1', 'maxPlayers': 10, 'deckCount': 6}, callback=True)
        code, h_id = r0['room_code'], r0['player_id']
        for i in range(1, 10):
            self.assertTrue(players[i].emit('join_room', {'roomCode': code, 'playerName': f'P{i+1}'}, callback=True)['success'])

        # Add 2 spectators to a full 10-player / 6-deck room
        s1, s2 = self._new_client(), self._new_client()
        self.assertTrue(s1.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'VIP1'}, callback=True)['success'])
        self.assertTrue(s2.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'VIP2'}, callback=True)['success'])

        # Start 10-player, 6-deck match (307 cards)
        self.assertTrue(players[0].emit('start_game', {'roomCode': code, 'playerId': h_id}, callback=True)['success'])
        room = room_manager.get_room(code)
        self.assertEqual(len(room.game_state.players), 10)
        self.assertEqual(sum(len(p.hand) for p in room.game_state.players), 307)
        self.assertEqual(len(room.spectators), 2)

        # Verify frontend spectator UI hooks exist
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()
        self.assertIn('id="btn-spectate-menu"', html)
        self.assertIn('id="modal-spectate"', html)
        self.assertIn('id="btn-spectator-list"', html)
        self.assertIn('id="spectator-list-popover"', html)
        self.assertIn('id="spectator-mode-banner"', html)


if __name__ == '__main__':
    unittest.main()
