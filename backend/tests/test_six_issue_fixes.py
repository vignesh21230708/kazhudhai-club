"""
KAZHUDHAI CLUB — backend/tests/test_six_issue_fixes.py
Comprehensive regression test suite for the 6 targeted fixes:
1. Top-left Common Pile HUD removed; Room Code, Decks, and on-table Common Collected preserved.
2. Mobile Audio ON/OFF clearly visible, high-contrast, accessible, and functionally toggles audio.
3. Spectator messaging works across pre-match, in-match, post-match, and after transient reconnects,
   while preserving strict permission isolation and zero hidden-card leakage.
4. Play Again works reliably for 2-player and 10-player matches: fresh shuffle, zero stale cards,
   correct starting player, per-player personalized hands, zero hidden-card leakage, unready/disconnected
   rejection, duplicate protection, and client round-pause / DOM reset.
5. Temporary recent-message notification outside chat panel (~0.9s), handles rapid bursts,
   works for players and spectators, XSS-safe, preserves full chat history.
6. Host-controlled Restart Game resets server state atomically, broadcasts personalized hands to all
   players immediately, remains independent from Play Again, and enforces host-only authorization.
"""
import json
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.deck import expected_card_count, is_ace_of_spades
from game_engine.room_manager import room_manager

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _force_finish_match(room_code):
    """Configure hands so one normal round cleanly finishes the match via play_card."""
    room = room_manager.get_room(room_code)
    gs = room.game_state
    ranks = ['A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5']
    for idx, p in enumerate(gs.players):
        if idx < len(gs.players) - 1:
            p.hand = [{'id': f'stale_m1_s_{idx}', 'rank': ranks[idx], 'suit': 'S', 'deck_index': 0}]
        else:
            p.hand = [
                {'id': f'stale_m1_s_{idx}', 'rank': '2', 'suit': 'S', 'deck_index': 0},
                {'id': f'stale_m1_h_{idx}', 'rank': '3', 'suit': 'H', 'deck_index': 0},
            ]
    gs.current_player_idx = 0
    gs._start_new_round()


class TestSixIssueFixes(unittest.TestCase):

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

    def _run_node(self, script: str):
        res = subprocess.run(
            ['node', '-e', script],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            res.returncode, 0,
            f"Node test failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        return res.stdout

    def _create_and_finish_match(self, num_players=2, deck_count=1, with_spectator=True):
        clients = [self._new_client() for _ in range(num_players)]
        r0 = clients[0].emit('create_room', {
            'playerName': 'HostP1',
            'isPrivate': True,
            'maxPlayers': max(4, num_players),
            'deckCount': deck_count,
        }, callback=True)
        self.assertTrue(r0['success'])
        code = r0['room_code']
        ids = [r0['player_id']]

        for i in range(1, num_players):
            rj = clients[i].emit('join_room', {
                'roomCode': code,
                'playerName': f'Player{i + 1}',
            }, callback=True)
            self.assertTrue(rj['success'])
            ids.append(rj['player_id'])

        spec = None
        spec_id = None
        spec_token = None
        if with_spectator:
            spec = self._new_client()
            rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'EyeOne'}, callback=True)
            self.assertTrue(rs['success'])
            spec_id = rs['spectator_id']
            spec_token = rs['spectator_token']

        r_start = clients[0].emit('start_game', {'roomCode': code, 'playerId': ids[0]}, callback=True)
        self.assertTrue(r_start['success'])

        room = room_manager.get_room(code)
        _force_finish_match(code)
        stale_ids = {c['id'] for p in room.game_state.players for c in p.hand}

        id_to_c = dict(zip(ids, clients))
        for _ in range(num_players + 2):
            if room.status == 'finished':
                break
            cp = room.game_state.current_player
            pr = id_to_c[cp.id].emit('play_card', {
                'roomCode': code,
                'playerId': cp.id,
                'cardId': cp.hand[0]['id'],
            }, callback=True)
            self.assertTrue(pr['success'], f"play_card failed: {pr}")

        self.assertEqual(room.status, 'finished')
        return {
            'code': code,
            'clients': clients,
            'ids': ids,
            'spec': spec,
            'spec_id': spec_id,
            'spec_token': spec_token,
            'room': room,
            'stale_ids': stale_ids,
        }

    # ── Issue 1: Remove unnecessary top-left Common Pile HUD, keep Room/Decks & Common Collected ──

    def test_01_issue1_redundant_hud_common_pile_removed_and_table_pile_preserved(self):
        with open(os.path.join(BASE_DIR, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()
        with open(os.path.join(BASE_DIR, 'frontend', 'js', 'ui', 'table.js'), 'r', encoding='utf-8') as f:
            table_js = f.read()

        self.assertNotIn('id="hud-common-count"', html)
        self.assertNotIn('>Common Pile<', html)
        self.assertIn('id="hud-room-code"', html)
        self.assertIn('id="hud-deck-count"', html)
        self.assertIn('id="common-collected-zone"', html)
        self.assertIn('id="common-pile-count"', html)
        self.assertIn('if (DOM.hudCommonCount)', table_js)

    # ── Issue 2: Mobile Audio ON/OFF clearly visible & functional toggle ──

    def test_02_issue2_audio_toggle_visibility_css_and_functional_state_in_node(self):
        with open(os.path.join(BASE_DIR, 'frontend', 'css', 'table.css'), 'r', encoding='utf-8') as f:
            table_css = f.read()
        with open(os.path.join(BASE_DIR, 'frontend', 'css', 'responsive.css'), 'r', encoding='utf-8') as f:
            resp_css = f.read()

        self.assertIn('.hud-voice-btn.voice-speaker-btn.audio-on', table_css)
        self.assertIn('.voice-speaker-btn', resp_css)
        self.assertIn('.hud-voice-btn', resp_css)

        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

function makeEl(id) {
  const classes = new Set();
  const attrs = {};
  return {
    id, textContent: '', title: '',
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      contains: (c) => classes.has(c),
    },
    setAttribute: (k, v) => { attrs[k] = v; },
    getAttribute: (k) => attrs[k],
    addEventListener: () => {},
  };
}
const els = {
  'hud-voice-controls': makeEl('hud-voice-controls'),
  'btn-voice-mic': makeEl('btn-voice-mic'),
  'btn-voice-speaker': makeEl('btn-voice-speaker'),
  'voice-mic-icon': makeEl('voice-mic-icon'),
  'voice-mic-label': makeEl('voice-mic-label'),
  'voice-speaker-icon': makeEl('voice-speaker-icon'),
  'voice-speaker-label': makeEl('voice-speaker-label'),
};

const ctx = {
  console,
  window: { AudioContext: class { resume() { return Promise.resolve(); } close() {} } },
  document: { getElementById: (id) => els[id] || null, addEventListener: () => {} },
  showToast: () => {},
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error,
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
ctx.VoiceClient.startVoice(fakeSocket, 'KZ1234', 'p1', 'Alice');

const mockAudio = { muted: false };
ctx.VoiceClient._peers.set('p2', { pc: { close: () => {} }, audioEl: mockAudio });

// Initially Audio On
if (ctx.VoiceClient.isDeafened() !== false) process.exit(1);
if (els['voice-speaker-icon'].textContent !== '🔊') process.exit(2);
if (els['voice-speaker-label'].textContent !== 'Audio On') process.exit(3);
if (!els['btn-voice-speaker'].classList.contains('audio-on')) process.exit(4);

// Toggle OFF
ctx.VoiceClient.toggleSpeaker();
if (ctx.VoiceClient.isDeafened() !== true) process.exit(5);
if (mockAudio.muted !== true) process.exit(6);
if (els['voice-speaker-icon'].textContent !== '🔇') process.exit(7);
if (els['voice-speaker-label'].textContent !== 'Audio Off') process.exit(8);
if (!els['btn-voice-speaker'].classList.contains('deafened')) process.exit(9);

// Toggle ON again
ctx.VoiceClient.toggleSpeaker();
if (ctx.VoiceClient.isDeafened() !== false || mockAudio.muted !== false) process.exit(10);
if (els['voice-speaker-label'].textContent !== 'Audio On') process.exit(11);

ctx.VoiceClient.leaveVoice();
console.log('AUDIO_TOGGLE_OK');
"""
        out = self._run_node(script)
        self.assertIn('AUDIO_TOGGLE_OK', out)

    # ── Issue 3: Spectator messaging across stages + reconnect recovery + strict privacy ──

    def test_03_issue3_spectator_messaging_all_stages_and_reconnect_recovery(self):
        c1, c2, spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Bob'}, callback=True)
        id2 = r2['player_id']

        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'SpectatorSam'}, callback=True)
        self.assertTrue(rs['success'])
        spec_id = rs['spectator_id']
        spec_token = rs['spectator_token']
        self.assertTrue(spec_token)

        for c in (c1, c2, spec):
            c.get_received()

        # 1. Pre-match lobby chat via send_lobby_chat with explicit spectatorId
        r_pre = spec.emit('send_lobby_chat', {
            'roomCode': code, 'spectatorId': spec_id, 'senderId': spec_id, 'message': 'Good luck in lobby!'
        }, callback=True)
        self.assertTrue(r_pre['success'], f"Spectator pre-match chat failed: {r_pre}")
        self.assertEqual(r_pre['message']['display_name'], '[Spectator] SpectatorSam')
        self.assertTrue(r_pre['message']['is_spectator'])

        # Both players and spectator receive it
        for cli in (c1, c2, spec):
            msgs = [e['args'][0] for e in cli.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]['display_name'], '[Spectator] SpectatorSam')

        # 2. Start match -> spectator simulates transient socket drop & reconnect_spectator
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        room = room_manager.get_room(code)
        hidden_ids = {c['id'] for p in room.game_state.players for c in p.hand}

        spec.disconnect()
        self.assertEqual(len(room.spectators), 0)

        spec_reconn = self._new_client()
        r_rec = spec_reconn.emit('reconnect_spectator', {
            'roomCode': code,
            'spectatorToken': spec_token,
        }, callback=True)
        self.assertTrue(r_rec['success'], f"Spectator reconnect failed: {r_rec}")
        self.assertEqual(r_rec['spectator_id'], spec_id)
        # Zero hidden card leakage on spectator reconnect!
        serialized_rec = json.dumps(r_rec)
        for cid in hidden_ids:
            self.assertNotIn(cid, serialized_rec)

        for cli in (c1, c2, spec_reconn):
            cli.get_received()

        # 3. In-match spectator messaging works cleanly after reconnect!
        r_in = spec_reconn.emit('send_chat_message', {
            'roomCode': code, 'spectatorId': spec_id, 'senderId': spec_id,
            'stage': 'in_match', 'message': 'Exciting match!'
        }, callback=True)
        self.assertTrue(r_in['success'], f"Spectator in-match chat failed after reconnect: {r_in}")
        self.assertEqual(r_in['message']['display_name'], '[Spectator] SpectatorSam')
        for cli in (c1, c2, spec_reconn):
            msgs = [e['args'][0] for e in cli.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]['text'], 'Exciting match!')

        # 4. Spectator STILL cannot spoof player identity or perform player actions
        self.assertFalse(spec_reconn.emit('send_chat_message', {
            'roomCode': code, 'senderId': id1, 'stage': 'in_match', 'message': 'impersonation'
        }, callback=True)['success'])
        self.assertFalse(spec_reconn.emit('play_card', {
            'roomCode': code, 'playerId': id1, 'cardId': next(iter(hidden_ids))
        }, callback=True)['success'])
        self.assertFalse(spec_reconn.emit('get_room_state', {
            'roomCode': code, 'playerId': id1
        }, callback=True)['success'])

        # 5. Explicit leave_spectator revokes reconnect token
        self.assertTrue(spec_reconn.emit('leave_spectator', {'roomCode': code, 'spectatorId': spec_id}, callback=True)['success'])
        spec_after_leave = self._new_client()
        self.assertFalse(spec_after_leave.emit('reconnect_spectator', {
            'roomCode': code, 'spectatorToken': spec_token
        }, callback=True)['success'])

    # ── Issue 4: Play Again (2-player, 10-player, personalized hands, no stale cards, guards) ──

    def test_04_issue4_two_player_play_again_fresh_hands_and_zero_leakage(self):
        ctx = self._create_and_finish_match(num_players=2, deck_count=1, with_spectator=True)
        code, clients, ids, spec, room, stale_ids = (
            ctx['code'], ctx['clients'], ctx['ids'], ctx['spec'], ctx['room'], ctx['stale_ids']
        )
        old_match_id = room.match_id

        # Unready rejection
        self.assertFalse(clients[0].emit('play_again', {'roomCode': code, 'playerId': ids[0]}, callback=True)['success'])

        # Both Ready
        self.assertTrue(clients[0].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[0], 'ready': True}, callback=True)['success'])
        self.assertTrue(clients[1].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[1], 'ready': True}, callback=True)['success'])

        for c in (*clients, spec):
            c.get_received()

        # Non-host initiates Play Again
        res = clients[1].emit('play_again', {'roomCode': code, 'playerId': ids[1]}, callback=True)
        self.assertTrue(res['success'])
        new_match_id = room.match_id
        self.assertNotEqual(new_match_id, old_match_id)

        # Verify fresh server state reset
        gs = room.game_state
        self.assertEqual(gs.round_number, 1)
        self.assertEqual(len(gs.common_pile), 0)
        self.assertEqual(len(gs.rankings), 0)
        self.assertEqual(len(gs.current_round.played_cards), 0)
        self.assertEqual(gs.num_decks, 1)

        # Starting player holds A♠
        starter = gs.current_player
        self.assertTrue(any(is_ace_of_spades(c) for c in starter.hand))

        # Every player receives game_started BEFORE game_state with new match_id, distinct hands, zero stale cards, zero leakage
        seen_hands = {}
        for idx, (cli, pid) in enumerate(zip(clients, ids)):
            evts = cli.get_received()
            names = [e['name'] for e in evts]
            self.assertIn('game_started', names)
            self.assertIn('game_state', names)
            self.assertLess(names.index('game_started'), names.index('game_state'))

            gs_evt = [e['args'][0] for e in evts if e['name'] == 'game_started'][-1]
            self.assertEqual(gs_evt['match_id'], new_match_id)
            self.assertEqual(gs_evt['reason'], 'play_again')

            st = [e['args'][0] for e in evts if e['name'] == 'game_state'][-1]
            self.assertEqual(st['match_id'], new_match_id)
            self.assertEqual(st['status'], 'playing')
            self.assertEqual(st['round_number'], 1)
            self.assertEqual(st['common_pile_count'], 0)
            self.assertEqual(st['played_cards'], [])
            self.assertEqual(st['current_player_id'], starter.id)

            my_card_ids = {c['id'] for c in st['my_hand']}
            self.assertEqual(len(my_card_ids), 26)
            self.assertTrue(my_card_ids.isdisjoint(stale_ids), "Stale Match 1 cards leaked into Match 2!")
            seen_hands[pid] = (my_card_ids, st)

        # Different hands delivered to the two players & zero cross-player leakage
        self.assertTrue(seen_hands[ids[0]][0].isdisjoint(seen_hands[ids[1]][0]))
        self.assertEqual(len(seen_hands[ids[0]][0] | seen_hands[ids[1]][0]), 52)
        p1_json = json.dumps(seen_hands[ids[0]][1])
        for opp_cid in seen_hands[ids[1]][0]:
            self.assertNotIn(opp_cid, p1_json)
        p2_json = json.dumps(seen_hands[ids[1]][1])
        for opp_cid in seen_hands[ids[0]][0]:
            self.assertNotIn(opp_cid, p2_json)

        # Spectator receives ONLY sanitized spectator_state with zero hidden cards
        spec_evts = spec.get_received()
        self.assertNotIn('game_state', [e['name'] for e in spec_evts])
        spec_states = [e['args'][0] for e in spec_evts if e['name'] == 'spectator_state']
        self.assertEqual(len(spec_states), 1)
        self.assertEqual(spec_states[0]['match_id'], new_match_id)
        spec_json = json.dumps(spec_states[0])
        for cid in (seen_hands[ids[0]][0] | seen_hands[ids[1]][0]):
            self.assertNotIn(cid, spec_json)

        # Duplicate Play Again request while match is already playing -> rejected
        self.assertFalse(clients[0].emit('play_again', {'roomCode': code, 'playerId': ids[0]}, callback=True)['success'])

    def test_05_issue4_ten_player_six_deck_play_again_and_disconnected_rejection(self):
        ctx = self._create_and_finish_match(num_players=10, deck_count=6, with_spectator=True)
        code, clients, ids, spec, room, stale_ids = (
            ctx['code'], ctx['clients'], ctx['ids'], ctx['spec'], ctx['room'], ctx['stale_ids']
        )

        # Mark 9 Ready, 10th still Not Ready -> rejected
        for i in range(9):
            self.assertTrue(clients[i].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[i], 'ready': True}, callback=True)['success'])
        self.assertFalse(clients[0].emit('play_again', {'roomCode': code, 'playerId': ids[0]}, callback=True)['success'])

        # 10th becomes Ready
        self.assertTrue(clients[9].emit('set_post_match_ready', {'roomCode': code, 'playerId': ids[9], 'ready': True}, callback=True)['success'])

        for c in (*clients, spec):
            c.get_received()

        # Trigger Play Again in 10-player / 6-deck room (307 cards)
        res = clients[4].emit('play_again', {'roomCode': code, 'playerId': ids[4]}, callback=True)
        self.assertTrue(res['success'], f"10-player Play Again failed: {res}")
        self.assertEqual(room.status, 'playing')
        self.assertEqual(room.game_state.num_decks, 6)

        all_delivered = set()
        starter = room.game_state.current_player
        self.assertTrue(any(is_ace_of_spades(c) for c in starter.hand))

        for cli, pid in zip(clients, ids):
            evts = cli.get_received()
            states = [e['args'][0] for e in evts if e['name'] == 'game_state']
            self.assertEqual(len(states), 1)
            hand_ids = {c['id'] for c in states[0]['my_hand']}
            self.assertIn(len(hand_ids), (30, 31))
            self.assertTrue(hand_ids.isdisjoint(stale_ids))
            self.assertTrue(hand_ids.isdisjoint(all_delivered), "Duplicate card delivered across players!")
            all_delivered |= hand_ids

        self.assertEqual(len(all_delivered), expected_card_count(6))

        # Spectator receives zero hidden cards out of all 307
        spec_states = [e['args'][0] for e in spec.get_received() if e['name'] == 'spectator_state']
        self.assertEqual(len(spec_states), 1)
        spec_json = json.dumps(spec_states[0])
        for cid in all_delivered:
            self.assertNotIn(cid, spec_json)

    def test_06_issue4_and_issue6_client_play_again_and_restart_never_stick_on_round_pause(self):
        """
        Reproduce the exact client bug:
        Match 1 ends -> round_resolved sets _isRoundPaused=true -> game_over calls _showResults ->
        Play Again sends game_started + game_state -> BOTH players must immediately clear old cards
        and render fresh Match 2 hands without getting stuck!
        """
        script = """
const fs = require('fs');
const vm = require('vm');
const mainJs = fs.readFileSync('frontend/js/main.js', 'utf8');

let renderedHands = [];
let resetCalled = 0;
let lastScreen = 'screen-game';
const elements = {};
function mk(id) {
  if (!elements[id]) {
    const classes = new Set();
    elements[id] = {
      id, textContent: '', innerHTML: '', value: '', disabled: false, dataset: {},
      style: {},
      classList: {
        add: (...c) => c.forEach(x => classes.add(x)),
        remove: (...c) => c.forEach(x => classes.delete(x)),
        toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
        contains: (c) => classes.has(c),
      },
      addEventListener: () => {},
      querySelector: () => null,
      appendChild: () => {},
      insertBefore: () => {},
      remove: () => {},
      offsetWidth: 100,
    };
  }
  return elements[id];
}

let savedState = null;
const ctx = {
  console,
  window: { history: { state: {}, pushState: () => {}, replaceState: () => {}, back: () => {}, go: () => {} }, location: { href: 'http://localhost/' }, addEventListener: () => {} },
  document: { getElementById: mk, addEventListener: () => {}, createElement: (t) => mk('el_' + Math.random()) },
  GameClient: { isActive: () => !!savedState, getState: () => savedState, setState: (s) => { savedState = s; }, reset: () => { savedState = null; } },
  OnlineClient: { getPlayerId: () => 'p2', isSpectator: () => false, getRoomCode: () => 'KZ1234', getCurrentSenderId: () => 'p2' },
  OfflineClient: { reset: () => {} },
  TableUI: {
    resetForNewMatch: () => { resetCalled++; },
    renderPlayers: () => {},
    renderHand: (hand) => { renderedHands.push(hand.map(c => c.id)); },
    setTurn: () => {}, setStatus: () => {}, updateTurnTimer: () => {},
    updateCommonPile: () => {}, updateDeckCount: () => {}, syncPlayedCards: () => {},
    showAttackBanner: () => {}, hideAttackBanner: () => {}, updatePlayerStatus: () => {},
    setOnlineControlsVisible: () => {}, updateSpectatorList: () => {}, resetPlayInFlight: () => {},
    clearPlayedCards: () => {}, flashSelfAvatar: () => {}, flashOpponentAvatar: () => {},
    hideExitConfirm: () => {},
  },
  MenuUI: { init: () => {}, hideModal: () => {} },
  VoiceClient: { leaveVoice: () => {} },
  CardRenderer: { cardLabel: () => 'A♠', suitSymbol: () => '♠' },
  Sound: { click: () => {}, attack: () => {}, playerFinish: () => {}, kazhudhai: () => {}, cardPlay: () => {} },
  Animations: { screenShake: () => {}, flashAttack: () => {}, confettiCelebration: () => {} },
  Storage: { getActiveSession: () => null },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Set, Map, Array, Object, String, Number, Boolean, Math, Error,
};
vm.createContext(ctx);
vm.runInContext(mainJs + '\\nglobalThis.App = App; globalThis.Screens = Screens;', ctx);

// 1. Match 1 final round resolves (sets _isRoundPaused = true)
ctx.App.handleOnlineRoundResolution({ match_id: 'match_1', is_attack: false, winner_id: 'p1', winner_name: 'Host', winning_card: { rank: 'A', suit: 'S' } });

// 2. Match 1 ends -> game_over shows results screen
ctx.App.showOnlineResults({ match_id: 'match_1', kazhudhai_name: 'Bob', rankings: [] });

// 3. Stale Match 1 finished game_state arrives after game_over -> must NOT break Match 2
ctx.App.renderOnlineState({ match_id: 'match_1', status: 'finished', players: [{ id: 'p1', name: 'Host' }, { id: 'p2', name: 'Bob' }], my_hand: [{ id: 'stale_1', rank: '3', suit: 'H' }] });

// 4. Play Again starts Match 2 -> game_started calls prepareForNewMatch, then game_state arrives
renderedHands = [];
ctx.App.prepareForNewMatch({ match_id: 'match_2', room_code: 'KZ1234', deck_count: 1, reason: 'play_again' });
ctx.Screens.go('screen-game');
ctx.App.renderOnlineState({
  match_id: 'match_2',
  status: 'playing',
  round_number: 1,
  current_player_id: 'p1',
  players: [{ id: 'p1', name: 'Host', cardCount: 26 }, { id: 'p2', name: 'Bob', cardCount: 26 }],
  my_hand: [{ id: 'fresh_2a', rank: 'K', suit: 'D' }, { id: 'fresh_2b', rank: '9', suit: 'C' }],
  played_cards: [],
  common_pile_count: 0,
});

if (resetCalled < 1) process.exit(1);
if (renderedHands.length !== 1) process.exit(2);
if (renderedHands[0].join(',') !== 'fresh_2a,fresh_2b') process.exit(3);

// 5. Late stale Match 1 state arrives after Match 2 started -> MUST BE IGNORED
ctx.App.renderOnlineState({
  match_id: 'match_1',
  status: 'playing',
  players: [{ id: 'p1', name: 'Host' }, { id: 'p2', name: 'Bob' }],
  my_hand: [{ id: 'stale_1', rank: '3', suit: 'H' }],
});
if (renderedHands.length !== 1) process.exit(4);

console.log('CLIENT_PLAY_AGAIN_RESET_OK');
process.exit(0);
"""
        out = self._run_node(script)
        self.assertIn('CLIENT_PLAY_AGAIN_RESET_OK', out)

    # ── Issue 5: Temporary recent-message notification outside chat panel ──

    def test_07_issue5_recent_message_notification_burst_xss_and_auto_dismiss_in_node(self):
        script = """
const fs = require('fs');
const vm = require('vm');
const mainJs = fs.readFileSync('frontend/js/main.js', 'utf8');

const elements = {};
function mk(id) {
  if (!elements[id]) {
    const classes = new Set(id === 'chat-recent-toast' || id === 'ingame-chat-drawer' ? ['hidden'] : []);
    elements[id] = {
      id, textContent: '', innerHTML: '', value: '', disabled: false, dataset: {},
      style: {}, children: [],
      classList: {
        add: (...c) => c.forEach(x => classes.add(x)),
        remove: (...c) => c.forEach(x => classes.delete(x)),
        toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
        contains: (c) => classes.has(c),
      },
      addEventListener: () => {},
      querySelector: () => null,
      appendChild: (ch) => { elements[id].children.push(ch); },
      offsetWidth: 100,
      scrollTop: 0, scrollHeight: 100,
    };
  }
  return elements[id];
}

// Pre-initialize key DOM nodes
['chat-recent-toast', 'chat-recent-sender', 'chat-recent-text', 'ingame-chat-drawer', 'ingame-chat-messages', 'ingame-chat-badge'].forEach(mk);

const timers = [];
let nextTimerId = 1;
const fakeSetTimeout = (fn, ms) => {
  const id = nextTimerId++;
  timers.push({ id, fn, ms, cleared: false });
  return id;
};
const fakeClearTimeout = (id) => {
  const t = timers.find(x => x.id === id);
  if (t) t.cleared = true;
};

const ctx = {
  console,
  window: { history: { state: {} }, location: { href: 'http://localhost/' }, addEventListener: () => {} },
  document: { getElementById: mk, addEventListener: () => {}, createElement: () => mk('el_' + Math.random()) },
  GameClient: { isActive: () => true, getState: () => null, setState: () => {}, reset: () => {} },
  OnlineClient: { getRoomCode: () => 'KZ1234', getCurrentSenderId: () => 'p1', isSpectator: () => false },
  MenuUI: { init: () => {}, addLobbyChatMessage: () => {} },
  setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, setInterval: () => 1, clearInterval: () => {},
  Date, Set, Map, Array, Object, String, Number, Boolean, Math, Error,
};
vm.createContext(ctx);
vm.runInContext(mainJs + '\\nglobalThis.App = App;', ctx);

// Message 1 from player
ctx.App.handleStageChatMessage({
  id: 'm1', room_code: 'KZ1234', stage: 'in_match',
  sender_id: 'p2', sender_name: 'Bob', display_name: 'Bob', is_spectator: false,
  text: 'First message', timestamp: '12:00 PM',
});
if (elements['chat-recent-toast'].classList.contains('hidden')) process.exit(1);
if (elements['chat-recent-sender'].textContent !== 'Bob:') process.exit(2);
if (elements['chat-recent-text'].textContent !== 'First message') process.exit(3);
const firstTimer = timers[timers.length - 1];
if (firstTimer.ms < 500 || firstTimer.ms > 1000) process.exit(4);

// Rapid Message 2 from spectator with XSS payload -> immediately replaces Message 1 & clears old timer
ctx.App.handleStageChatMessage({
  id: 'm2', room_code: 'KZ1234', stage: 'in_match',
  sender_id: 'spec_1', sender_name: 'Sam', display_name: '[Spectator] Sam', is_spectator: true,
  text: '<img src=x onerror=alert(1)>', timestamp: '12:00 PM',
});
if (!firstTimer.cleared) process.exit(5);
if (elements['chat-recent-sender'].textContent !== '[Spectator] Sam:') process.exit(6);
if (elements['chat-recent-text'].textContent !== '<img src=x onerror=alert(1)>') process.exit(7);
if (!elements['chat-recent-toast'].classList.contains('is-spectator')) process.exit(8);
if (elements['chat-recent-text'].innerHTML !== '') process.exit(9); // rendered purely via textContent

// Full chat history preserved in chat panel (both m1 and m2 appended)
if (elements['ingame-chat-messages'].children.length !== 2) process.exit(10);

// Running the latest timer dismisses the notification automatically
const latestTimer = timers[timers.length - 1];
latestTimer.fn();
if (!elements['chat-recent-toast'].classList.contains('hidden')) process.exit(11);

console.log('RECENT_CHAT_TOAST_OK');
"""
        out = self._run_node(script)
        self.assertIn('RECENT_CHAT_TOAST_OK', out)

    # ── Issue 6: Host-controlled Restart Game (atomic reset, broadcasts, distinct from Play Again) ──

    def test_08_issue6_host_restart_game_resets_state_and_broadcasts_fresh_hands(self):
        c1, c2, c3, spec = self._new_client(), self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host', 'maxPlayers': 4, 'deckCount': 2}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'P2'}, callback=True)
        id2 = r2['player_id']
        r3 = c3.emit('join_room', {'roomCode': code, 'playerName': 'P3'}, callback=True)
        id3 = r3['player_id']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Watch'}, callback=True)
        self.assertTrue(rs['success'])

        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        room = room_manager.get_room(code)
        first_match_id = room.match_id

        # Play one full normal round so common_pile > 0 and round_number == 2
        gs = room.game_state
        gs.players[0].hand[0] = {'id': 'r1_c0', 'rank': 'A', 'suit': 'S', 'deck_index': 0}
        gs.players[1].hand[0] = {'id': 'r1_c1', 'rank': 'K', 'suit': 'S', 'deck_index': 0}
        gs.players[2].hand[0] = {'id': 'r1_c2', 'rank': 'Q', 'suit': 'S', 'deck_index': 0}
        gs.current_player_idx = 0
        gs._start_new_round()
        id_to_c = {id1: c1, id2: c2, id3: c3}
        for _ in range(3):
            cp = gs.current_player
            self.assertTrue(id_to_c[cp.id].emit('play_card', {
                'roomCode': code, 'playerId': cp.id, 'cardId': cp.hand[0]['id']
            }, callback=True)['success'])
        self.assertEqual(gs.round_number, 2)
        self.assertEqual(len(gs.common_pile), 3)

        # Non-host and spectator CANNOT restart
        self.assertFalse(c2.emit('restart_game', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertFalse(spec.emit('restart_game', {'roomCode': code, 'playerId': rs['spectator_id']}, callback=True)['success'])
        self.assertEqual(room.match_id, first_match_id)

        for cli in (c1, c2, c3, spec):
            cli.get_received()

        # Host restarts game mid-match (no Ready required — distinct from Play Again)
        res = c1.emit('restart_game', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertTrue(res['success'], f"Host restart_game failed: {res}")
        new_match_id = room.match_id
        self.assertNotEqual(new_match_id, first_match_id)
        self.assertEqual(res['match_id'], new_match_id)
        self.assertEqual(res['deck_count'], 2)

        # Verify server state completely reset
        gs2 = room.game_state
        self.assertEqual(gs2.round_number, 1)
        self.assertEqual(len(gs2.common_pile), 0)
        self.assertEqual(len(gs2.rankings), 0)
        self.assertEqual(len(gs2.current_round.played_cards), 0)
        self.assertEqual(gs2.num_decks, 2)
        self.assertTrue(any(is_ace_of_spades(c) for c in gs2.current_player.hand))

        # Every player received game_started (reason='restart') + distinct personalized game_state
        delivered_cards = set()
        for cli, pid in ((c1, id1), (c2, id2), (c3, id3)):
            evts = cli.get_received()
            names = [e['name'] for e in evts]
            self.assertIn('game_started', names)
            self.assertIn('game_state', names)
            gs_evt = [e['args'][0] for e in evts if e['name'] == 'game_started'][-1]
            self.assertEqual(gs_evt['reason'], 'restart')
            self.assertEqual(gs_evt['match_id'], new_match_id)

            st = [e['args'][0] for e in evts if e['name'] == 'game_state'][-1]
            self.assertEqual(st['match_id'], new_match_id)
            self.assertEqual(st['round_number'], 1)
            self.assertEqual(st['common_pile_count'], 0)
            self.assertEqual(st['played_cards'], [])
            hand_ids = {c['id'] for c in st['my_hand']}
            self.assertTrue(hand_ids.isdisjoint(delivered_cards))
            delivered_cards |= hand_ids

        self.assertEqual(len(delivered_cards), expected_card_count(2))

        # Spectator received sanitized spectator_state with zero hidden cards
        spec_evts = spec.get_received()
        self.assertNotIn('game_state', [e['name'] for e in spec_evts])
        spec_st = [e['args'][0] for e in spec_evts if e['name'] == 'spectator_state'][-1]
        self.assertEqual(spec_st['match_id'], new_match_id)
        spec_json = json.dumps(spec_st)
        for cid in delivered_cards:
            self.assertNotIn(cid, spec_json)

    # ── Additional Bug A: In-Match Chat (Players + Spectators + Isolation + Security) ──

    def test_09_bugA_in_match_chat_player_and_spectator_delivery_isolation_and_security(self):
        c1, c2, spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'HostA', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        code, id1, tok1 = r1['room_code'], r1['player_id'], r1['reconnect_token']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'PlayerB'}, callback=True)
        id2, tok2 = r2['player_id'], r2['reconnect_token']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'WatchC'}, callback=True)
        self.assertTrue(rs['success'])
        spec_id = rs['spectator_id']

        # Pre-match message in lobby before game starts
        r_pre = c1.emit('send_lobby_chat', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'message': 'Lobby warmup'
        }, callback=True)
        self.assertTrue(r_pre['success'])

        # Start match -> pre-match chat cleared, stage becomes in_match
        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        room = room_manager.get_room(code)
        self.assertEqual(room.chat_stages['pre_match'], [])
        for cli in (c1, c2, spec):
            cli.get_received()

        # 1. Player-to-player & player-to-spectator in-match message
        res_p1 = c1.emit('send_chat_message', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'stage': 'in_match', 'message': 'Good move!'
        }, callback=True)
        self.assertTrue(res_p1['success'], f"P1 in-match chat failed: {res_p1}")
        self.assertEqual(res_p1['message']['display_name'], 'HostA')
        self.assertFalse(res_p1['message']['is_spectator'])
        for cli in (c1, c2, spec):
            msgs = [e['args'][0] for e in cli.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]['stage'], 'in_match')
            self.assertEqual(msgs[0]['text'], 'Good move!')

        # 2. Second player replies to player & spectator
        res_p2 = c2.emit('send_chat_message', {
            'roomCode': code, 'playerId': id2, 'senderId': id2, 'stage': 'in_match', 'message': 'Thanks HostA!'
        }, callback=True)
        self.assertTrue(res_p2['success'])
        for cli in (c1, c2, spec):
            msgs = [e['args'][0] for e in cli.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]['display_name'], 'PlayerB')

        # 3. Spectator-to-player in-match message preserves [Spectator] label
        res_sp = spec.emit('send_chat_message', {
            'roomCode': code, 'spectatorId': spec_id, 'senderId': spec_id, 'stage': 'in_match', 'message': 'Great round!'
        }, callback=True)
        self.assertTrue(res_sp['success'], f"Spectator in-match chat failed: {res_sp}")
        self.assertTrue(res_sp['message']['is_spectator'])
        self.assertEqual(res_sp['message']['display_name'], '[Spectator] WatchC')
        for cli in (c1, c2, spec):
            msgs = [e['args'][0] for e in cli.get_received() if e['name'] == 'chat_message']
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]['display_name'], '[Spectator] WatchC')
            self.assertEqual(msgs[0]['text'], 'Great round!')

        # 4. Stage routing isolation: pre_match and post_match are rejected during active match
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'stage': 'pre_match', 'message': 'wrong stage'
        }, callback=True)['success'])
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'stage': 'post_match', 'message': 'too early'
        }, callback=True)['success'])
        self.assertEqual(len(room.chat_stages['in_match']), 3)
        self.assertEqual(len(room.chat_stages['post_match']), 0)

        # 5. Server-side request.sid socket ownership security strictly enforced
        self.assertFalse(c2.emit('send_chat_message', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'stage': 'in_match', 'message': 'spoof p1'
        }, callback=True)['success'])
        self.assertFalse(spec.emit('send_chat_message', {
            'roomCode': code, 'playerId': id1, 'senderId': id1, 'stage': 'in_match', 'message': 'spec spoof p1'
        }, callback=True)['success'])
        self.assertFalse(c1.emit('send_chat_message', {
            'roomCode': code, 'spectatorId': spec_id, 'senderId': spec_id, 'stage': 'in_match', 'message': 'p1 spoof spec'
        }, callback=True)['success'])

        # 6. Transient offline -> client_connection_lost -> reconnect_session restores in-match chat
        c2.emit('client_connection_lost', {'roomCode': code, 'playerId': id2})
        self.assertFalse(c2.emit('send_chat_message', {
            'roomCode': code, 'playerId': id2, 'senderId': id2, 'stage': 'in_match', 'message': 'while offline'
        }, callback=True)['success'])
        rec = c2.emit('reconnect_session', {'roomCode': code, 'reconnectToken': tok2}, callback=True)
        self.assertTrue(rec['success'])
        res_after_rec = c2.emit('send_chat_message', {
            'roomCode': code, 'playerId': id2, 'senderId': id2, 'stage': 'in_match', 'message': 'Back online!'
        }, callback=True)
        self.assertTrue(res_after_rec['success'])

    # ── Additional Bug B: Voice Chat Signaling, Security, Reconnect & Cleanup ──

    def test_10_bugB_voice_chat_backend_auth_spectator_isolation_reconnect_and_cleanup(self):
        c1, c2, spec = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'LaptopHost', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'AndroidPeer'}, callback=True)
        id2, tok2 = r2['player_id'], r2['reconnect_token']
        rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'Listener'}, callback=True)
        spec_id = rs['spectator_id']

        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        for cli in (c1, c2, spec):
            cli.get_received()

        # 1. Both players join voice; spectator is blocked from voice_join
        vj1 = c1.emit('voice_join', {'roomCode': code, 'playerId': id1}, callback=True)
        self.assertTrue(vj1['success'])
        vj2 = c2.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)
        self.assertTrue(vj2['success'])
        self.assertEqual([p['peerId'] for p in vj2['peers']], [id1])
        self.assertFalse(spec.emit('voice_join', {'roomCode': code, 'playerId': spec_id}, callback=True)['success'])
        self.assertFalse(spec.emit('voice_join', {'roomCode': code, 'playerId': id1}, callback=True)['success'])

        c1_evts = c1.get_received()
        self.assertTrue(any(e['name'] == 'voice_peer_joined' and e['args'][0]['peerId'] == id2 for e in c1_evts))

        # 2. Bidirectional voice_signal relay works; spoofing & spectator targeting blocked
        c1.emit('voice_signal', {
            'roomCode': code, 'playerId': id1, 'targetPeerId': id2, 'signal': {'type': 'offer', 'sdp': 'v=0\r\na=ice-ufrag:u1'}
        })
        c2.emit('voice_signal', {
            'roomCode': code, 'playerId': id2, 'targetPeerId': id1, 'signal': {'type': 'answer', 'sdp': 'v=0\r\na=ice-ufrag:u2'}
        })
        self.assertTrue(any(e['name'] == 'voice_signal' and e['args'][0]['fromPeerId'] == id1 for e in c2.get_received()))
        self.assertTrue(any(e['name'] == 'voice_signal' and e['args'][0]['fromPeerId'] == id2 for e in c1.get_received()))

        # Spectator cannot send OR receive voice_signal
        spec.emit('voice_signal', {
            'roomCode': code, 'playerId': id1, 'targetPeerId': id2, 'signal': {'type': 'offer', 'sdp': 'spoof'}
        })
        c1.emit('voice_signal', {
            'roomCode': code, 'playerId': id1, 'targetPeerId': spec_id, 'signal': {'type': 'offer', 'sdp': 'to_spec'}
        })
        self.assertEqual([e for e in c2.get_received() if e['name'] == 'voice_signal'], [])
        self.assertEqual([e for e in spec.get_received() if e['name'] == 'voice_signal'], [])

        # 3. Android peer drops temporarily and reconnects on a new socket
        c2.disconnect()
        c1_left = [e for e in c1.get_received() if e['name'] == 'voice_peer_left']
        self.assertEqual(len(c1_left), 1)
        self.assertEqual(c1_left[0]['args'][0]['peerId'], id2)

        # Signal to disconnected peer is dropped silently
        c1.emit('voice_signal', {
            'roomCode': code, 'playerId': id1, 'targetPeerId': id2, 'signal': {'type': 'offer', 'sdp': 'stale'}
        })

        c2_new = self._new_client()
        rec2 = c2_new.emit('reconnect_session', {'roomCode': code, 'reconnectToken': tok2}, callback=True)
        self.assertTrue(rec2['success'])
        c1.get_received()
        c2_new.get_received()

        vj2_re = c2_new.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)
        self.assertTrue(vj2_re['success'])
        self.assertEqual([p['peerId'] for p in vj2_re['peers']], [id1])
        self.assertTrue(any(e['name'] == 'voice_peer_joined' and e['args'][0]['peerId'] == id2 for e in c1.get_received()))

        # Bidirectional relay works immediately after reconnect
        c1.emit('voice_signal', {
            'roomCode': code, 'playerId': id1, 'targetPeerId': id2, 'signal': {'type': 'offer', 'sdp': 'v=0\r\na=ice-ufrag:u3'}
        })
        c2_new.emit('voice_signal', {
            'roomCode': code, 'playerId': id2, 'targetPeerId': id1, 'signal': {'type': 'answer', 'sdp': 'v=0\r\na=ice-ufrag:u4'}
        })
        self.assertTrue(any(e['name'] == 'voice_signal' and e['args'][0]['fromPeerId'] == id1 for e in c2_new.get_received()))
        self.assertTrue(any(e['name'] == 'voice_signal' and e['args'][0]['fromPeerId'] == id2 for e in c1.get_received()))

        # 4. leave_room cleans up active_voice_peers and notifies remaining peer
        c1.get_received()
        c2_new.emit('leave_room', {'roomCode': code, 'playerId': id2})
        room = room_manager.get_room(code)
        self.assertNotIn(id2, getattr(room, 'voice_peers', set()))
        self.assertTrue(any(e['name'] == 'voice_peer_left' and e['args'][0]['peerId'] == id2 for e in c1.get_received()))

    def test_11_bugB_voice_client_stale_pc_reset_on_reconnect_without_peer_left_in_node(self):
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

function createHarness(localId) {
  let pcCount = 0;
  let closeCalls = 0;
  const emittedSignals = [];
  const listeners = {};
  class MockPC {
    constructor() {
      this.id = ++pcCount;
      this.signalingState = 'stable';
      this.connectionState = 'connected';
      this.localDescription = null;
      this.remoteDescription = null;
      this._transceivers = [];
    }
    addTransceiver() {
      const t = { mid: '0', direction: 'sendrecv', sender: { track: null, replaceTrack: async () => {} }, receiver: { track: { kind: 'audio' } } };
      this._transceivers.push(t);
      return t;
    }
    getTransceivers() { return this._transceivers; }
    async createOffer() { return { type: 'offer', sdp: 'v=0\\r\\na=ice-ufrag:offer_' + this.id }; }
    async createAnswer() { return { type: 'answer', sdp: 'v=0\\r\\na=ice-ufrag:answer_' + this.id }; }
    async setLocalDescription(d) {
      this.localDescription = d;
      if (d.type === 'offer') this.signalingState = 'have-local-offer';
      else if (d.type === 'answer') this.signalingState = 'stable';
    }
    async setRemoteDescription(d) {
      this.remoteDescription = d;
      if (d.type === 'offer') {
        if (this._transceivers.length === 0) this.addTransceiver();
        this.signalingState = 'have-remote-offer';
      } else if (d.type === 'answer') {
        this.signalingState = 'stable';
      }
    }
    close() { closeCalls++; this.connectionState = 'closed'; this.signalingState = 'closed'; }
  }
  const fakeSocket = {
    emit: (evt, ...args) => {
      const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
      if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
      if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
      if (evt === 'voice_signal') emittedSignals.push(args[0]);
    },
    on: (evt, fn) => { listeners[evt] = fn; },
  };
  const ctx = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    window: { AudioContext: class { resume() { return Promise.resolve(); } close() {} } },
    document: { getElementById: () => null, createElement: () => ({ style: {}, play: () => Promise.resolve() }), body: { appendChild: () => {} }, addEventListener: () => {} },
    RTCPeerConnection: MockPC,
    RTCSessionDescription: class { constructor(x) { Object.assign(this, x); } },
    RTCIceCandidate: class { constructor(x) { Object.assign(this, x); } },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error,
  };
  vm.createContext(ctx);
  vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);
  ctx.VoiceClient.startVoice(fakeSocket, 'KZ9999', localId, localId);
  return {
    vc: ctx.VoiceClient, listeners, emittedSignals,
    getPcCount: () => pcCount, getCloseCalls: () => closeCalls,
  };
}

(async () => {
  // 1. Offerer ('alice') has established PC with 'bob', then 'bob' rejoins without prior voice_peer_left
  const alice = createHarness('alice');
  alice.listeners['voice_peer_joined']({ peerId: 'bob' });
  await new Promise(r => setTimeout(r, 20));
  await alice.vc._handleAnswer('bob', { type: 'answer', sdp: 'v=0\\r\\na=ice-ufrag:bob_old' });
  if (alice.getPcCount() !== 1 || alice.emittedSignals.length !== 1) process.exit(1);

  alice.listeners['voice_peer_joined']({ peerId: 'bob' });
  await new Promise(r => setTimeout(r, 20));
  if (alice.getCloseCalls() !== 1) process.exit(2);
  if (alice.getPcCount() !== 2) process.exit(3);
  if (alice.emittedSignals.length !== 2) process.exit(4);
  if (!alice.emittedSignals[1].signal.sdp.includes('offer_2')) process.exit(5);

  // 2. Answerer ('bob') has established PC from 'alice' (ufrag=old), then receives fresh offer (ufrag=new)
  const bob = createHarness('bob');
  await bob.vc._handleOffer('alice', { type: 'offer', sdp: 'v=0\\r\\na=ice-ufrag:alice_old' });
  if (bob.getPcCount() !== 1 || bob.emittedSignals.length !== 1) process.exit(6);

  await bob.vc._handleOffer('alice', { type: 'offer', sdp: 'v=0\\r\\na=ice-ufrag:alice_new' });
  if (bob.getCloseCalls() !== 1) process.exit(7);
  if (bob.getPcCount() !== 2) process.exit(8);
  if (bob.emittedSignals.length !== 2) process.exit(9);
  if (!bob.emittedSignals[1].signal.sdp.includes('answer_2')) process.exit(10);

  alice.vc.leaveVoice();
  bob.vc.leaveVoice();
  console.log('STALE_PC_RESET_OK');
  process.exit(0);
})();
"""
        out = self._run_node(script)
        self.assertIn('STALE_PC_RESET_OK', out)

    def test_12_bugB_voice_client_ended_mic_recovery_autoplay_unmute_and_leave_cleanup_in_node(self):
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let gumCalls = 0;
let replaceTrackLog = [];
let playCalls = 0;
let removedAudio = 0;
let voiceJoinCalls = 0;
let stopCalls = 0;

class MockPC {
  constructor() {
    this.signalingState = 'stable';
    this.connectionState = 'connected';
    this.ontrack = null;
    this.onconnectionstatechange = null;
    this.sender = {
      track: null,
      replaceTrack: async (t) => { this.sender.track = t; replaceTrackLog.push(t ? t.id : null); },
    };
    this._transceivers = [{ mid: '0', direction: 'sendrecv', sender: this.sender, receiver: { track: { kind: 'audio' } } }];
  }
  addTransceiver() { return this._transceivers[0]; }
  getTransceivers() { return this._transceivers; }
  close() { this.connectionState = 'closed'; this.signalingState = 'closed'; }
}

function makeTrack(id) {
  return {
    id, kind: 'audio', enabled: true, readyState: 'live', onended: null,
    stop() { stopCalls++; this.readyState = 'ended'; },
  };
}

let createdAudio = null;
const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class { createMediaStreamSource() { return { connect() {} }; } createAnalyser() { return { fftSize: 256, frequencyBinCount: 128, getByteFrequencyData() {} }; } resume() { return Promise.resolve(); } close() {} } },
  navigator: {
    mediaDevices: {
      getUserMedia: async () => {
        gumCalls++;
        const tr = makeTrack('mic_' + gumCalls);
        return { getTracks: () => [tr], getAudioTracks: () => [tr] };
      },
    },
  },
  MediaStream: class { constructor(tracks) { this.tracks = tracks; } },
  document: {
    getElementById: () => null,
    createElement: () => {
      createdAudio = {
        style: {}, muted: false, paused: true, srcObject: null,
        play() { playCalls++; return Promise.resolve(); },
        remove() { removedAudio++; },
      };
      return createdAudio;
    },
    body: { appendChild: () => {} },
    addEventListener: () => {},
  },
  RTCPeerConnection: MockPC,
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error,
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join') { voiceJoinCalls++; if (cb) cb({ success: true, peers: [] }); }
  },
  on: () => {},
};

(async () => {
  ctx.VoiceClient.startVoice(fakeSocket, 'KZ7777', 'alice', 'Alice');
  const pc = ctx.VoiceClient._createPeerConnection('bob');

  // 1. Remote track arrives muted/paused -> track.onunmute retries playback
  const remoteTrack = { kind: 'audio', onunmute: null };
  pc.ontrack({ track: remoteTrack, streams: [] });
  if (!createdAudio || playCalls !== 1) process.exit(1);
  if (typeof remoteTrack.onunmute !== 'function') process.exit(2);
  remoteTrack.onunmute();
  if (playCalls !== 2) process.exit(3);
  ctx.VoiceClient.unlockAudioPlayback();
  if (playCalls !== 3) process.exit(4);

  // 2. Acquire mic, simulate Android OS ending the mic track, then toggleMic re-acquires fresh stream
  await ctx.VoiceClient.toggleMic();
  if (gumCalls !== 1 || replaceTrackLog[replaceTrackLog.length - 1] !== 'mic_1') process.exit(5);

  const liveTrack = pc.sender.track;
  liveTrack.readyState = 'ended';
  if (typeof liveTrack.onended === 'function') liveTrack.onended();

  await ctx.VoiceClient.toggleMic();
  if (gumCalls !== 2 || replaceTrackLog[replaceTrackLog.length - 1] !== 'mic_2') process.exit(6);

  // 3. ICE failed schedules recovery, but leaveVoice cancels timer & cleans up tracks/audio/peers
  pc.connectionState = 'failed';
  pc.onconnectionstatechange();
  const joinsBeforeLeave = voiceJoinCalls;
  ctx.VoiceClient.leaveVoice();
  if (ctx.VoiceClient._peers.size !== 0) process.exit(7);
  if (removedAudio < 1 || stopCalls < 1) process.exit(8);

  await new Promise(r => setTimeout(r, 1350));
  if (voiceJoinCalls !== joinsBeforeLeave) process.exit(9);

  console.log('VOICE_LIFECYCLE_RECOVERY_OK');
  process.exit(0);
})();
"""
        out = self._run_node(script)
        self.assertIn('VOICE_LIFECYCLE_RECOVERY_OK', out)

    # ── Final Hardening Fixes: Stale game_over Guard & Clear Stale SID on Leave ──

    def test_13_hardening_stale_game_over_cannot_overwrite_current_match_in_node(self):
        script = """
const fs = require('fs');
const vm = require('vm');
const mainJs = fs.readFileSync('frontend/js/main.js', 'utf8');

const elements = {};
function mk(id) {
  if (!elements[id]) {
    const classes = new Set();
    elements[id] = {
      id, textContent: '', innerHTML: '', value: '', disabled: false, dataset: {},
      style: {}, children: [],
      classList: {
        add: (...c) => c.forEach(x => classes.add(x)),
        remove: (...c) => c.forEach(x => classes.delete(x)),
        toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
        contains: (c) => classes.has(c),
      },
      addEventListener: () => {},
      querySelector: () => null,
      appendChild: (ch) => { elements[id].children.push(ch); },
      insertBefore: () => {},
      remove: () => {},
      offsetWidth: 100,
    };
  }
  return elements[id];
}
['screen-menu', 'screen-game', 'screen-results', 'kazhudhai-name', 'results-rankings'].forEach(mk);

let savedState = null;
const ctx = {
  console,
  window: { history: { state: {}, pushState: () => {}, replaceState: () => {}, back: () => {}, go: () => {} }, location: { href: 'http://localhost/' }, addEventListener: () => {} },
  document: { getElementById: mk, querySelectorAll: () => [], addEventListener: () => {}, createElement: () => mk('el_' + Math.random()) },
  GameClient: { isActive: () => !!savedState, getState: () => savedState, setState: (s) => { savedState = s; }, reset: () => { savedState = null; } },
  OnlineClient: { getPlayerId: () => 'p1', isSpectator: () => false, getRoomCode: () => 'KZ5555', getPostMatchStatus: () => null, playAgain: () => {} },
  OfflineClient: { reset: () => {} },
  TableUI: {
    resetForNewMatch: () => {}, updateTurnTimer: () => {}, hideExitConfirm: () => {},
    renderPlayers: () => {}, renderHand: () => {}, setTurn: () => {}, setStatus: () => {},
    updateCommonPile: () => {}, updateDeckCount: () => {}, syncPlayedCards: () => {},
    showAttackBanner: () => {}, hideAttackBanner: () => {}, updatePlayerStatus: () => {},
    setOnlineControlsVisible: () => {}, updateSpectatorList: () => {}, resetPlayInFlight: () => {},
    clearPlayedCards: () => {},
  },
  MenuUI: { init: () => {}, hideModal: () => {} },
  VoiceClient: { leaveVoice: () => {} },
  CardRenderer: { cardLabel: () => 'A♠', suitSymbol: () => '♠' },
  Sound: { click: () => {}, attack: () => {}, playerFinish: () => {}, kazhudhai: () => {}, cardPlay: () => {} },
  Animations: { screenShake: () => {}, flashAttack: () => {}, confettiCelebration: () => {} },
  Storage: { getActiveSession: () => null },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Set, Map, Array, Object, String, Number, Boolean, Math, Error,
};
vm.createContext(ctx);
vm.runInContext(mainJs + '\\nglobalThis.App = App; globalThis.Screens = Screens;', ctx);

// Start Match 2 and enter game screen
ctx.App.prepareForNewMatch({ match_id: 'match_2', room_code: 'KZ5555', deck_count: 1, reason: 'play_again' });
ctx.Screens.go('screen-game');
if (ctx.Screens.current() !== 'screen-game') process.exit(1);

// 1. Late stale game_over from match_1 MUST be ignored (must not navigate to results or overwrite)
ctx.App.showOnlineResults({
  match_id: 'match_1',
  kazhudhai_name: 'OldMatchLoser',
  rankings: [{ name: 'OldMatchLoser', is_kazhudhai: true }],
});
if (ctx.Screens.current() !== 'screen-game') process.exit(2);
if (elements['kazhudhai-name'].textContent === 'OldMatchLoser') process.exit(3);

// 2. Valid current-match game_over for match_2 displays normally
ctx.App.showOnlineResults({
  match_id: 'match_2',
  kazhudhai_name: 'CurrentMatchLoser',
  rankings: [
    { name: 'WinnerP1', is_kazhudhai: false },
    { name: 'CurrentMatchLoser', is_kazhudhai: true },
  ],
});
if (ctx.Screens.current() !== 'screen-results') process.exit(4);
if (elements['kazhudhai-name'].textContent !== 'CurrentMatchLoser') process.exit(5);

console.log('STALE_GAME_OVER_GUARD_OK');
process.exit(0);
"""
        out = self._run_node(script)
        self.assertIn('STALE_GAME_OVER_GUARD_OK', out)

    def test_14_hardening_leave_room_clears_stale_sid_while_preserving_other_players_and_reconnect(self):
        c1, c2, c3 = self._new_client(), self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'Host1', 'maxPlayers': 4, 'deckCount': 1}, callback=True)
        code, id1 = r1['room_code'], r1['player_id']
        r2 = c2.emit('join_room', {'roomCode': code, 'playerName': 'Leaver2'}, callback=True)
        id2, tok2 = r2['player_id'], r2['reconnect_token']
        r3 = c3.emit('join_room', {'roomCode': code, 'playerName': 'Reconnector3'}, callback=True)
        id3, tok3 = r3['player_id'], r3['reconnect_token']

        self.assertTrue(c1.emit('start_game', {'roomCode': code, 'playerId': id1}, callback=True)['success'])
        room = room_manager.get_room(code)

        sid1_before = room.players[id1].sid
        sid3_before = room.players[id3].sid
        self.assertIsNotNone(sid1_before)
        self.assertIsNotNone(room.players[id2].sid)
        self.assertIsNotNone(sid3_before)

        # 1. P2 explicitly leaves the active match (even if socket stays open)
        leave_res = c2.emit('leave_room', {'roomCode': code, 'playerId': id2}, callback=True)
        self.assertTrue(leave_res['success'])

        # Stale SID cleared on P2; P1 and P3 untouched
        self.assertIsNone(room.players[id2].sid)
        self.assertFalse(room.players[id2].connected)
        self.assertEqual(room.players[id2].status, 'left')
        self.assertEqual(room.players[id1].sid, sid1_before)
        self.assertTrue(room.players[id1].connected)
        self.assertEqual(room.players[id3].sid, sid3_before)
        self.assertTrue(room.players[id3].connected)

        # P2's old socket can no longer act on id2 after leaving
        self.assertFalse(c2.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertFalse(c2.emit('voice_join', {'roomCode': code, 'playerId': id2}, callback=True)['success'])
        self.assertFalse(c2.emit('play_card', {'roomCode': code, 'playerId': id2, 'cardId': 'any'}, callback=True)['success'])

        # 2. Reconnecting players still reconnect cleanly via reconnect_token (both transient disconnect & mid-match leave)
        c3.disconnect()
        self.assertIsNone(room.players[id3].sid)
        c3_new = self._new_client()
        rec3 = c3_new.emit('reconnect_session', {'roomCode': code, 'reconnectToken': tok3}, callback=True)
        self.assertTrue(rec3['success'])
        self.assertIsNotNone(room.players[id3].sid)
        self.assertTrue(room.players[id3].connected)

        c2_new = self._new_client()
        rec2 = c2_new.emit('reconnect_session', {'roomCode': code, 'reconnectToken': tok2}, callback=True)
        self.assertTrue(rec2['success'])
        self.assertIsNotNone(room.players[id2].sid)
        self.assertTrue(room.players[id2].connected)
        self.assertTrue(c2_new.emit('get_room_state', {'roomCode': code, 'playerId': id2}, callback=True)['success'])


if __name__ == '__main__':
    unittest.main()
