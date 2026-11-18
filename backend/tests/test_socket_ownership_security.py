"""
KAZHUDHAI CLUB — backend/tests/test_socket_ownership_security.py
Security regression tests verifying Socket.IO connection-to-identity ownership binding:
- Every authenticated player event requires room.players[player_id].sid == request.sid.
- Every authenticated spectator event requires room.spectators[spectator_id].sid == request.sid.
- Client-supplied playerId / senderId / spectatorId are never trusted as proof of identity.
- Spoofed get_room_state and play_card (including error-resync path) leak ZERO hidden cards.
- Legitimate player actions, spectator actions, host controls, voice chat, and reconnects work.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.room_manager import room_manager


class TestSocketOwnershipSecurity(unittest.TestCase):

    def setUp(self):
        self._clients = []
        room_manager.rooms.clear()

    def tearDown(self):
        for c in self._clients:
            try:
                if c.is_connected():
                    c.disconnect()
            except Exception:
                pass
        self._clients.clear()
        for r in list(room_manager.rooms.values()):
            r.cancel_turn_timer()
        room_manager.rooms.clear()

    def _new_client(self):
        c = app_module.socketio.test_client(app_module.app)
        self._clients.append(c)
        return c

    def _setup_playing_match_with_spectator(self):
        c1 = self._new_client()
        c2 = self._new_client()
        spec = self._new_client()
        outsider = self._new_client()

        r1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        self.assertTrue(r1['success'])
        code = r1['room_code']
        id1 = r1['player_id']
        tok1 = r1['reconnect_token']

        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        self.assertTrue(r2['success'])
        id2 = r2['player_id']
        tok2 = r2['reconnect_token']

        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Watcher'}, callback=True)
        self.assertTrue(rs['success'])
        spec_id = rs['spectator_id']

        r_start = c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertTrue(r_start['success'])

        for c in (c1, c2, spec, outsider):
            c.get_received()

        room = room_manager.get_room(code)
        return {
            'room': room,
            'code': code,
            'c1': c1, 'id1': id1, 'tok1': tok1,
            'c2': c2, 'id2': id2, 'tok2': tok2,
            'spec': spec, 'spec_id': spec_id,
            'outsider': outsider,
        }

    def _finish_match_quickly(self, ctx):
        room = ctx['room']
        code = ctx['code']
        gs = room.game_state
        gs.players[0].hand = [{'id': 'fin_as', 'rank': 'A', 'suit': 'S', 'deck_index': 0}]
        gs.players[1].hand = [
            {'id': 'fin_ks', 'rank': 'K', 'suit': 'S', 'deck_index': 0},
            {'id': 'fin_2h', 'rank': '2', 'suit': 'H', 'deck_index': 0},
        ]
        gs.current_player_idx = 0
        gs._start_new_round()

        id_to_client = {ctx['id1']: ctx['c1'], ctx['id2']: ctx['c2']}
        for _ in range(2):
            cp = gs.current_player
            res = id_to_client[cp.id].emit('play_card', {
                'roomCode': code,
                'playerId': cp.id,
                'cardId': cp.hand[0]['id'],
            }, callback=True)
            self.assertTrue(res['success'])

        self.assertEqual(room.status, 'finished')
        for c in (ctx['c1'], ctx['c2'], ctx['spec'], ctx['outsider']):
            c.get_received()

    # ── 1. Hidden-Card Privacy on get_room_state ──

    def test_01_spoofed_get_room_state_leaks_zero_hidden_cards(self):
        ctx = self._setup_playing_match_with_spectator()
        room, code = ctx['room'], ctx['code']
        c1, id1 = ctx['c1'], ctx['id1']
        c2, id2 = ctx['c2'], ctx['id2']
        spec, spec_id = ctx['spec'], ctx['spec_id']
        outsider = ctx['outsider']

        p1_card_ids = {c['id'] for c in room.game_state._get_player(id1).hand}
        p2_card_ids = {c['id'] for c in room.game_state._get_player(id2).hand}
        all_hidden_ids = p1_card_ids | p2_card_ids
        self.assertEqual(len(all_hidden_ids), 52)

        # Attack A: Spectator spoofs Player 1's playerId on get_room_state
        res_spec_spoof = spec.emit('get_room_state', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertFalse(res_spec_spoof['success'])
        spec_evts = spec.get_received()
        self.assertEqual(spec_evts, [], "Spoofed spectator get_room_state must emit ZERO events")
        serialized = json.dumps({'res': res_spec_spoof, 'evts': spec_evts})
        for cid in all_hidden_ids:
            self.assertNotIn(cid, serialized)

        # Attack B: Opponent (Player 2) spoofs Player 1's playerId on get_room_state
        res_p2_spoof = c2.emit('get_room_state', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertFalse(res_p2_spoof['success'])
        p2_evts = c2.get_received()
        self.assertEqual(p2_evts, [], "Spoofed opponent get_room_state must emit ZERO events")
        serialized_p2 = json.dumps({'res': res_p2_spoof, 'evts': p2_evts})
        for cid in p1_card_ids:
            self.assertNotIn(cid, serialized_p2)

        # Attack C: Outsider spoofs Player 1 and Spectator on get_room_state
        res_out_p1 = outsider.emit('get_room_state', {'roomCode': code, 'playerId': id1}, callback=True)
        res_out_sp = outsider.emit('get_room_state', {'roomCode': code, 'playerId': spec_id}, callback=True)
        self.assertFalse(res_out_p1['success'])
        self.assertFalse(res_out_sp['success'])
        self.assertEqual(outsider.get_received(), [])

        # Legitimate Player 1 call succeeds and leaks zero Player 2 cards
        res_legit_p1 = c1.emit('get_room_state', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertTrue(res_legit_p1['success'])
        p1_evts = [e for e in c1.get_received() if e['name'] == 'game_state']
        self.assertEqual(len(p1_evts), 1)
        p1_state = p1_evts[0]['args'][0]
        self.assertEqual({c['id'] for c in p1_state['my_hand']}, p1_card_ids)
        serialized_p1 = json.dumps(p1_state)
        for cid in p2_card_ids:
            self.assertNotIn(cid, serialized_p1)

        # Legitimate Spectator call succeeds and leaks zero hidden cards
        res_legit_spec = spec.emit('get_room_state', {'roomCode': code, 'playerId': spec_id}, callback=True)
        self.assertTrue(res_legit_spec['success'])
        spec_evts_ok = spec.get_received()
        self.assertEqual([e['name'] for e in spec_evts_ok], ['spectator_state'])
        serialized_spec_ok = json.dumps(spec_evts_ok[0]['args'][0])
        for cid in all_hidden_ids:
            self.assertNotIn(cid, serialized_spec_ok)

    # ── 2. Hidden-Card Privacy & Move Integrity on play_card (including error-resync path) ──

    def test_02_spoofed_play_card_and_error_resync_leak_zero_hidden_cards(self):
        ctx = self._setup_playing_match_with_spectator()
        room, code = ctx['room'], ctx['code']
        c1, id1 = ctx['c1'], ctx['id1']
        c2, id2 = ctx['c2'], ctx['id2']
        spec = ctx['spec']
        outsider = ctx['outsider']

        current_player = room.game_state.current_player
        cp_id = current_player.id
        other_client = c2 if cp_id == id1 else c1
        owner_client = c1 if cp_id == id1 else c2
        other_id = id2 if cp_id == id1 else id1

        cp_card_ids = {c['id'] for c in current_player.hand}
        other_card_ids = {c['id'] for c in room.game_state._get_player(other_id).hand}
        valid_card_id = current_player.hand[0]['id']
        initial_hand_len = len(current_player.hand)

        # Attack A: Spectator spoofs current player's ID with a VALID card AND an INVALID card (error-resync probe)
        for test_card in (valid_card_id, 'NON_EXISTENT_CARD_999'):
            res = spec.emit('play_card', {'roomCode': code, 'playerId': cp_id, 'cardId': test_card}, callback=True)
            self.assertFalse(res['success'])
            evts = spec.get_received()
            self.assertEqual(evts, [], f"Spectator spoofed play_card ({test_card}) must emit ZERO events")
            serialized = json.dumps({'res': res, 'evts': evts})
            for cid in (cp_card_ids | other_card_ids):
                self.assertNotIn(cid, serialized)

        # Attack B: Opponent spoofs current player's ID with VALID card AND INVALID card (error-resync probe)
        for test_card in (valid_card_id, 'NON_EXISTENT_CARD_999'):
            res = other_client.emit('play_card', {'roomCode': code, 'playerId': cp_id, 'cardId': test_card}, callback=True)
            self.assertFalse(res['success'])
            evts = other_client.get_received()
            self.assertEqual(evts, [], f"Opponent spoofed play_card ({test_card}) must emit ZERO events")
            serialized = json.dumps({'res': res, 'evts': evts})
            for cid in cp_card_ids:
                self.assertNotIn(cid, serialized)

        # Attack C: Outsider spoofs current player's ID with INVALID card
        res_out = outsider.emit('play_card', {'roomCode': code, 'playerId': cp_id, 'cardId': 'BAD_CARD'}, callback=True)
        self.assertFalse(res_out['success'])
        self.assertEqual(outsider.get_received(), [])

        # Confirm game state was NOT modified by any spoof attempt
        self.assertEqual(room.game_state.current_player.id, cp_id)
        self.assertEqual(len(current_player.hand), initial_hand_len)

        # Legitimate owner sending an invalid card gets their own resync game_state (zero opponent cards)
        owner_client.get_received()
        res_bad_owner = owner_client.emit('play_card', {'roomCode': code, 'playerId': cp_id, 'cardId': 'BAD_CARD'}, callback=True)
        self.assertFalse(res_bad_owner['success'])
        resync_evts = [e for e in owner_client.get_received() if e['name'] == 'game_state']
        self.assertEqual(len(resync_evts), 1)
        serialized_resync = json.dumps(resync_evts[0]['args'][0])
        for cid in other_card_ids:
            self.assertNotIn(cid, serialized_resync)

        # Legitimate owner playing a valid card succeeds
        res_ok = owner_client.emit('play_card', {'roomCode': code, 'playerId': cp_id, 'cardId': valid_card_id}, callback=True)
        self.assertTrue(res_ok['success'])

    # ── 3. Host Controls & Post-Match Impersonation ──

    def test_03_host_and_post_match_events_reject_impersonation(self):
        c1, c2, spec, outsider = self._new_client(), self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host'}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Guest'}, callback=True)
        id2 = r2['player_id']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Eye'}, callback=True)
        spec_id = rs['spectator_id']
        room = room_manager.get_room(code)

        # Non-host, spectator, and outsider spoofing host's playerId on start_game -> rejected
        for attacker in (c2, spec, outsider):
            res = attacker.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertEqual(room.status, 'waiting')

        # Legitimate host starts game
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        self.assertEqual(room.status, 'playing')
        orig_match_id = room.match_id

        # Non-host, spectator, and outsider spoofing host's playerId on restart_game -> rejected
        for attacker in (c2, spec, outsider):
            res = attacker.emit('restart_game', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertEqual(room.match_id, orig_match_id)

        # Legitimate host restarts game
        self.assertTrue(c1.emit('restart_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        self.assertNotEqual(room.match_id, orig_match_id)

        # Finish match to test post-match ownership
        ctx = {
            'room': room, 'code': code,
            'c1': c1, 'id1': id1, 'c2': c2, 'id2': id2,
            'spec': spec, 'spec_id': spec_id, 'outsider': outsider,
        }
        self._finish_match_quickly(ctx)

        # Player 2, spectator, and outsider cannot toggle Player 1's ready status
        for attacker in (c2, spec, outsider):
            res = attacker.emit('set_post_match_ready', {'roomCode': code, 'playerId': id1, 'ready': True}, callback=True)
            self.assertFalse(res['success'])
        self.assertFalse(room.post_match_ready[id1])

        # Legitimate players mark themselves Ready
        self.assertTrue(c1.emit('set_post_match_ready', {'roomCode': code, 'playerId': id1, 'ready': True}, callback=True)['success'])
        self.assertTrue(c2.emit('set_post_match_ready', {'roomCode': code, 'playerId': id2, 'ready': True}, callback=True)['success'])

        # Spectator and outsider spoofing Player 1's ID on play_again -> rejected
        for attacker in (spec, outsider):
            res = attacker.emit('play_again', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertEqual(room.status, 'finished')

        # Player 2 spoofing Player 1's ID on play_again -> rejected
        res_p2_spoof = c2.emit('play_again', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertFalse(res_p2_spoof['success'])
        self.assertEqual(room.status, 'finished')

        # Legitimate Player 2 calling play_again with own ID -> succeeds!
        res_pa = c2.emit('play_again', {'roomCode': code, 'playerId': id2}, callback=True)
        self.assertTrue(res_pa['success'])
        self.assertEqual(room.status, 'playing')

    # ── 4. Chat & Reaction Impersonation ──

    def test_04_chat_and_reaction_reject_impersonation(self):
        c1, c2, spec, outsider = self._new_client(), self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Alice'}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        id2 = r2['player_id']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Eye'}, callback=True)
        spec_id = rs['spectator_id']

        # Pre-match lobby chat impersonation attempts
        self.assertFalse(spec.emit('send_lobby_chat', {'roomCode': code, 'playerId': id1, 'message': 'fake alice'}, callback=True)['success'])
        self.assertFalse(c2.emit('send_lobby_chat', {'roomCode': code, 'playerId': id1, 'message': 'fake alice'}, callback=True)['success'])
        self.assertFalse(outsider.emit('send_lobby_chat', {'roomCode': code, 'playerId': id1, 'message': 'fake'}, callback=True)['success'])
        self.assertFalse(c1.emit('send_lobby_chat', {'roomCode': code, 'spectatorId': spec_id, 'message': 'fake spec'}, callback=True)['success'])

        # Legitimate pre-match lobby chat works for both player and spectator
        ok_p1 = c1.emit('send_lobby_chat', {'roomCode': code, 'playerId': id1, 'message': 'hi from alice'}, callback=True)
        ok_sp = spec.emit('send_lobby_chat', {'roomCode': code, 'spectatorId': spec_id, 'message': 'hi from eye'}, callback=True)
        self.assertTrue(ok_p1['success'])
        self.assertFalse(ok_p1['message']['is_spectator'])
        self.assertTrue(ok_sp['success'])
        self.assertTrue(ok_sp['message']['is_spectator'])
        self.assertEqual(ok_sp['message']['display_name'], '[Spectator] Eye')

        # Start match and verify in-match send_chat_message + send_reaction
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        c1.get_received()
        c2.get_received()

        # Impersonation on send_chat_message
        self.assertFalse(spec.emit('send_chat_message', {'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'spoof'}, callback=True)['success'])
        self.assertFalse(c2.emit('send_chat_message', {'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'spoof'}, callback=True)['success'])
        self.assertFalse(c2.emit('send_chat_message', {'roomCode': code, 'senderId': spec_id, 'stage': 'in_match', 'message': 'spoof'}, callback=True)['success'])
        self.assertFalse(outsider.emit('send_chat_message', {'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'spoof'}, callback=True)['success'])

        # Legitimate in-match chat works for player and spectator
        self.assertTrue(c2.emit('send_chat_message', {'roomCode': code, 'senderId': id2, 'stage': 'in_match', 'message': 'real bob'}, callback=True)['success'])
        ok_sp_in = spec.emit('send_chat_message', {'roomCode': code, 'senderId': spec_id, 'stage': 'in_match', 'message': 'real eye'}, callback=True)
        self.assertTrue(ok_sp_in['success'])
        self.assertTrue(ok_sp_in['message']['is_spectator'])

        # Impersonation on send_reaction
        c1.get_received()
        self.assertFalse(spec.emit('send_reaction', {'roomCode': code, 'playerId': id1, 'emoji': '🔥'}, callback=True)['success'])
        self.assertFalse(c2.emit('send_reaction', {'roomCode': code, 'playerId': id1, 'emoji': '🔥'}, callback=True)['success'])
        self.assertFalse(outsider.emit('send_reaction', {'roomCode': code, 'playerId': id1, 'emoji': '🔥'}, callback=True)['success'])
        self.assertEqual([e for e in c1.get_received() if e['name'] == 'player_reaction'], [])

        # Legitimate reaction works
        self.assertTrue(c1.emit('send_reaction', {'roomCode': code, 'playerId': id1, 'emoji': '🔥'}, callback=True)['success'])
        rx = [e for e in c2.get_received() if e['name'] == 'player_reaction']
        self.assertEqual(len(rx), 1)
        self.assertEqual(rx[0]['args'][0]['player_id'], id1)

    # ── 5. Voice Chat Signaling Impersonation ──

    def test_05_voice_events_reject_impersonation(self):
        ctx = self._setup_playing_match_with_spectator()
        room, code = ctx['room'], ctx['code']
        c1, id1 = ctx['c1'], ctx['id1']
        c2, id2 = ctx['c2'], ctx['id2']
        spec = ctx['spec']
        outsider = ctx['outsider']

        # Spectator, Player 2, and Outsider cannot join voice as Player 1
        for attacker in (spec, c2, outsider):
            res = attacker.emit('voice_join', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertEqual(getattr(room, 'voice_peers', set()), set())

        # Legitimate Player 1 and Player 2 join voice
        self.assertTrue(c1.emit('voice_join', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        self.assertTrue(c2.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        c1.get_received()
        c2.get_received()

        # Spectator, Player 2, and Outsider cannot send voice_signal pretending to be Player 1
        for attacker in (spec, c2, outsider):
            res = attacker.emit('voice_signal', {
                'roomCode': code,
                'playerId': id1,
                'targetPeerId': id2,
                'signal': {'type': 'offer', 'sdp': 'spoofed'},
            }, callback=True)
            self.assertFalse(res['success'])
        self.assertEqual([e for e in c2.get_received() if e['name'] == 'voice_signal'], [])

        # Legitimate voice_signal from Player 1 to Player 2 succeeds
        res_sig = c1.emit('voice_signal', {
            'roomCode': code,
            'playerId': id1,
            'targetPeerId': id2,
            'signal': {'type': 'offer', 'sdp': 'legit'},
        }, callback=True)
        self.assertTrue(res_sig['success'])
        sigs = [e for e in c2.get_received() if e['name'] == 'voice_signal']
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['args'][0]['fromPeerId'], id1)

        # Spectator, Player 2, and Outsider cannot kick Player 1 out of voice via voice_leave
        c2.get_received()
        for attacker in (spec, c2, outsider):
            res = attacker.emit('voice_leave', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertIn(id1, room.voice_peers)
        self.assertEqual([e for e in c2.get_received() if e['name'] == 'voice_peer_left'], [])

        # Legitimate voice_leave removes Player 1 and notifies Player 2
        self.assertTrue(c1.emit('voice_leave', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        self.assertNotIn(id1, room.voice_peers)
        left_evts = [e for e in c2.get_received() if e['name'] == 'voice_peer_left']
        self.assertEqual(len(left_evts), 1)
        self.assertEqual(left_evts[0]['args'][0]['peerId'], id1)

    # ── 6. Leave & Connection Lost Impersonation ──

    def test_06_leave_and_connection_lost_reject_impersonation(self):
        ctx = self._setup_playing_match_with_spectator()
        room, code = ctx['room'], ctx['code']
        c1, id1 = ctx['c1'], ctx['id1']
        c2, id2 = ctx['c2'], ctx['id2']
        spec, spec_id = ctx['spec'], ctx['spec_id']
        outsider = ctx['outsider']

        # Attacker cannot mark Player 1 as connection_lost
        for attacker in (c2, spec, outsider):
            res = attacker.emit('client_connection_lost', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertTrue(room.players[id1].connected)
        self.assertEqual(room.players[id1].status, 'connected')

        # Attacker cannot force Player 1 to leave_room
        for attacker in (c2, spec, outsider):
            res = attacker.emit('leave_room', {'roomCode': code, 'playerId': id1}, callback=True)
            self.assertFalse(res['success'])
        self.assertTrue(room.players[id1].connected)
        self.assertEqual(room.players[id1].status, 'connected')

        # Attacker cannot force Spectator to leave_spectator
        for attacker in (c1, c2, outsider):
            res = attacker.emit('leave_spectator', {'roomCode': code, 'spectatorId': spec_id}, callback=True)
            self.assertFalse(res['success'])
        self.assertIn(spec_id, room.spectators)

        # Legitimate leave_spectator and leave_room succeed
        self.assertTrue(spec.emit('leave_spectator', {'roomCode': code, 'spectatorId': spec_id}, callback=True)['success'])
        self.assertNotIn(spec_id, room.spectators)
        self.assertTrue(c2.emit('leave_room', {'roomCode': code, 'playerId': id2, 'reason': 'left'}, callback=True)['success'])
        self.assertEqual(room.players[id2].status, 'left')

    # ── 7. Reconnect Rebinds Socket Ownership Cleanly ──

    def test_07_reconnect_session_and_join_room_rebind_sid_ownership(self):
        ctx = self._setup_playing_match_with_spectator()
        room, code = ctx['room'], ctx['code']
        c1, id1 = ctx['c1'], ctx['id1']
        c2, id2, tok2 = ctx['c2'], ctx['id2'], ctx['tok2']

        # Player 2 disconnects and reconnects on a brand-new socket via reconnect_session
        c2.disconnect()
        self.assertIsNone(room.players[id2].sid)

        c2_new = self._new_client()
        res_rec = c2_new.emit('reconnect_session', {
            'reconnectToken': tok2,
            'roomCode': code,
            'playerId': id2,
        }, callback=True)
        self.assertTrue(res_rec['success'])
        self.assertIsNotNone(room.players[id2].sid)

        # New socket can perform all authenticated actions as Player 2
        c2_new.get_received()
        self.assertTrue(c2_new.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertEqual(len([e for e in c2_new.get_received() if e['name'] == 'game_state']), 1)
        self.assertTrue(c2_new.emit('send_chat_message', {'roomCode': code, 'senderId': id2, 'stage': 'in_match', 'message': 'back!'}, callback=True)['success'])
        self.assertTrue(c2_new.emit('send_reaction', {'roomCode': code, 'playerId': id2, 'emoji': '👍'}, callback=True)['success'])
        self.assertTrue(c2_new.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)['success'])

        # Player 1 still cannot spoof Player 2 after reconnect
        self.assertFalse(c1.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])

        # Reconnect via join_room with reconnectToken on a third socket rebinds ownership and invalidates c2_new
        c2_rejoin = self._new_client()
        res_join = c2_rejoin.emit('join_room', {
            'roomCode': code,
            'playerName': 'Bob',
            'reconnectToken': tok2,
        }, callback=True)
        self.assertTrue(res_join['success'])

        # Stale socket c2_new is now rejected!
        c2_new.get_received()
        self.assertFalse(c2_new.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertEqual(c2_new.get_received(), [])

        # Latest socket c2_rejoin succeeds!
        c2_rejoin.get_received()
        self.assertTrue(c2_rejoin.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertEqual(len([e for e in c2_rejoin.get_received() if e['name'] == 'game_state']), 1)


if __name__ == '__main__':
    unittest.main()
