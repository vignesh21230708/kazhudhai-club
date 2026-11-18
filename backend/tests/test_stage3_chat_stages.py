"""
KAZHUDHAI CLUB — backend/tests/test_stage3_chat_stages.py
Stage 3 automated test suite:
  - Pre-match chat send & receive (players + spectators with [Spectator] label)
  - In-match chat send & receive (players + spectators with [Spectator] label)
  - Post-match chat send & receive (players + spectators with [Spectator] label)
  - Independent empty history at each stage transition
  - Room and match isolation (no cross-room or cross-match leaks)
  - Membership validation, XSS neutralization, length-limit enforcement
  - Chat never triggers or alters gameplay state
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.room_manager import room_manager


class TestStage3ChatStages(unittest.TestCase):

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

    def _setup_room_with_spectator(self):
        c1, c2, c_spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        code = r1['room_code']
        id1 = r1['player_id']

        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        id2 = r2['player_id']

        rs = c_spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Watcher'}, callback=True)
        self.assertTrue(rs['success'])
        spec_id = rs['spectator_id']

        for c in (c1, c2, c_spec):
            c.get_received()

        return code, (c1, c2, c_spec), (id1, id2, spec_id), room_manager.get_room(code)

    # ── 1. Pre-Match, In-Match, Post-Match Send/Receive + [Spectator] Label + Independent Stages ──

    def test_01_three_independent_chat_stages_and_spectator_prefix(self):
        code, (c1, c2, c_spec), (id1, id2, spec_id), room = self._setup_room_with_spectator()

        # ── STAGE A: Pre-Match Chat ──
        r_pre_p = c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'pre_match', 'message': 'Pre-match hello!'
        }, callback=True)
        self.assertTrue(r_pre_p['success'])
        self.assertEqual(r_pre_p['message']['stage'], 'pre_match')
        self.assertFalse(r_pre_p['message']['is_spectator'])

        r_pre_s = c_spec.emit('send_chat_message', {
            'roomCode': code, 'senderId': spec_id, 'stage': 'pre_match', 'message': 'Good luck players!'
        }, callback=True)
        self.assertTrue(r_pre_s['success'])
        self.assertTrue(r_pre_s['message']['is_spectator'])
        self.assertTrue(r_pre_s['message']['display_name'].startswith('[Spectator]'))
        self.assertEqual(r_pre_s['message']['display_name'], '[Spectator] Watcher')

        # Wrong stage (in_match / post_match) rejected while waiting
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'Too early'
        }, callback=True)['success'])
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'post_match', 'message': 'Too early'
        }, callback=True)['success'])

        # All 3 clients received both pre-match messages
        for c in (c1, c2, c_spec):
            msgs = [e['args'][0] for e in c.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[1]['display_name'], '[Spectator] Watcher')

        self.assertEqual(len(room.chat_stages['pre_match']), 2)
        self.assertEqual(len(room.chat_stages['in_match']), 0)
        self.assertEqual(len(room.chat_stages['post_match']), 0)

        # ── STAGE B: Match Starts -> Fresh Empty In-Match Chat ──
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        self.assertEqual(len(room.chat_stages['pre_match']), 0)
        self.assertEqual(len(room.chat_stages['in_match']), 0)
        self.assertEqual(len(room.chat_stages['post_match']), 0)
        match_id_1 = room.match_id
        self.assertIsNotNone(match_id_1)

        for c in (c1, c2, c_spec):
            c.get_received()

        # Pre-match & post-match rejected during active match
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'pre_match', 'message': 'Blocked'
        }, callback=True)['success'])
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'post_match', 'message': 'Blocked'
        }, callback=True)['success'])

        # In-match chat works for players AND spectators
        r_in_p = c2.emit('send_chat_message', {
            'roomCode': code, 'senderId': id2, 'stage': 'in_match', 'message': 'Nice card!'
        }, callback=True)
        r_in_s = c_spec.emit('send_chat_message', {
            'roomCode': code, 'senderId': spec_id, 'stage': 'in_match', 'message': 'Intense round!'
        }, callback=True)
        self.assertTrue(r_in_p['success'] and r_in_s['success'])
        self.assertEqual(r_in_p['message']['match_id'], match_id_1)
        self.assertEqual(r_in_s['message']['display_name'], '[Spectator] Watcher')

        for c in (c1, c2, c_spec):
            msgs = [e['args'][0] for e in c.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 2)
            self.assertTrue(all(m['stage'] == 'in_match' for m in msgs))

        # ── STAGE C: Match Ends -> Fresh Empty Post-Match Chat ──
        gs = room.game_state
        gs.players[0].hand = [{'id': 'c_a', 'rank': 'A', 'suit': 'S', 'deck_index': 0}]
        gs.players[1].hand = [
            {'id': 'c_k', 'rank': 'K', 'suit': 'S', 'deck_index': 0},
            {'id': 'c_h', 'rank': '2', 'suit': 'H', 'deck_index': 0},
        ]
        gs.current_player_idx = 0
        gs._start_new_round()
        id_to_c = {id1: c1, id2: c2}
        for _ in range(2):
            cp = gs.current_player
            id_to_c[cp.id].emit('play_card', {'roomCode': code, 'playerId': cp.id, 'cardId': cp.hand[0]['id']}, callback=True)
        self.assertEqual(room.status, 'finished')

        # In-match chat cleared and post-match chat starts completely empty
        self.assertEqual(len(room.chat_stages['in_match']), 0)
        self.assertEqual(len(room.chat_stages['post_match']), 0)

        for c in (c1, c2, c_spec):
            c.get_received()

        # In-match & pre-match rejected after match end
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'Too late'
        }, callback=True)['success'])

        # Post-match chat works for players AND spectators
        r_post_p = c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'post_match', 'message': 'GG!'
        }, callback=True)
        r_post_s = c_spec.emit('send_chat_message', {
            'roomCode': code, 'senderId': spec_id, 'stage': 'post_match', 'message': 'Great match to watch!'
        }, callback=True)
        self.assertTrue(r_post_p['success'] and r_post_s['success'])
        self.assertEqual(r_post_s['message']['display_name'], '[Spectator] Watcher')
        self.assertEqual(len(room.chat_stages['post_match']), 2)

        for c in (c1, c2, c_spec):
            msgs = [e['args'][0] for e in c.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 2)
            self.assertTrue(all(m['stage'] == 'post_match' for m in msgs))

        # Play Again -> clears post-match chat and creates new match_id
        c1.emit('set_post_match_ready', {'roomCode': code, 'playerId': id1, 'ready': True}, callback=True)
        c2.emit('set_post_match_ready', {'roomCode': code, 'playerId': id2, 'ready': True}, callback=True)
        c1.emit('play_again', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertNotEqual(room.match_id, match_id_1)
        self.assertEqual(len(room.chat_stages['post_match']), 0)
        self.assertEqual(len(room.chat_stages['in_match']), 0)

    # ── 2. Cross-Room Isolation ──

    def test_02_messages_never_leak_across_rooms(self):
        cA1, cA2 = self._new_client(), self._new_client()
        cB1, cB2 = self._new_client(), self._new_client()

        rA = cA1.emit('create_room', {'playerName': 'A1'}, callback=True)
        codeA, idA1 = rA['room_code'], rA['player_id']
        cA2.emit('join_room', {'roomCode': codeA, 'playerName': 'A2'}, callback=True)

        rB = cB1.emit('create_room', {'playerName': 'B1'}, callback=True)
        codeB, idB1 = rB['room_code'], rB['player_id']
        cB2.emit('join_room', {'roomCode': codeB, 'playerName': 'B2'}, callback=True)

        cA1.emit('start_game', {'roomCode': codeA, 'playerId': idA1}, callback=True)
        cB1.emit('start_game', {'roomCode': codeB, 'playerId': idB1}, callback=True)

        for c in (cA1, cA2, cB1, cB2):
            c.get_received()

        cA1.emit('send_chat_message', {
            'roomCode': codeA, 'senderId': idA1, 'stage': 'in_match', 'message': 'Secret Room A message'
        }, callback=True)

        roomA_msgs = [e for e in cA2.get_received() if e['name'] == 'chat_message']
        roomB_msgs = [e for e in cB1.get_received() if e['name'] == 'chat_message']
        self.assertEqual(len(roomA_msgs), 1)
        self.assertEqual(len(roomB_msgs), 0)

    # ── 3. Invalid Users, XSS & Message Length Validation ──

    def test_03_invalid_user_xss_and_length_validation(self):
        code, (c1, c2, _), (id1, id2, _), room = self._setup_room_with_spectator()
        outsider = self._new_client()

        # Outsider rejected
        res_out = outsider.emit('send_chat_message', {
            'roomCode': code, 'senderId': 'fake_id', 'stage': 'pre_match', 'message': 'Intrusion'
        }, callback=True)
        self.assertFalse(res_out['success'])

        # Empty / whitespace rejected
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'pre_match', 'message': '   '
        }, callback=True)['success'])

        # Over-length (> 200 chars) rejected
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'pre_match', 'message': 'X' * 201
        }, callback=True)['success'])

        # XSS payload neutralized
        res_xss = c1.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'pre_match', 'message': '<script>alert("xss")</script>'
        }, callback=True)
        self.assertTrue(res_xss['success'])
        self.assertNotIn('<script>', res_xss['message']['text'])
        self.assertIn('&lt;script&gt;', res_xss['message']['text'])

    # ── 4. Chat Never Triggers or Mutates Gameplay State ──

    def test_04_in_match_chat_never_affects_gameplay(self):
        code, (c1, c2, c_spec), (id1, id2, spec_id), room = self._setup_room_with_spectator()
        c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)

        gs = room.game_state
        before_turn = gs.current_player.id
        before_round = gs.round_number
        before_hands = {p.id: [c['id'] for c in p.hand] for p in gs.players}
        before_common = len(gs.common_pile)
        before_rankings = list(gs.rankings)

        # Send multiple player & spectator in-match messages
        for _ in range(5):
            self.assertTrue(c1.emit('send_chat_message', {
                'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'play card attack!'
            }, callback=True)['success'])
            self.assertTrue(c_spec.emit('send_chat_message', {
                'roomCode': code, 'senderId': spec_id, 'stage': 'in_match', 'message': 'watching!'
            }, callback=True)['success'])

        self.assertEqual(gs.current_player.id, before_turn)
        self.assertEqual(gs.round_number, before_round)
        self.assertEqual({p.id: [c['id'] for c in p.hand] for p in gs.players}, before_hands)
        self.assertEqual(len(gs.common_pile), before_common)
        self.assertEqual(gs.rankings, before_rankings)


if __name__ == '__main__':
    unittest.main()
