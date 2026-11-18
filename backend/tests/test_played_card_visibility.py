"""
KAZHUDHAI CLUB — backend/tests/test_played_card_visibility.py
Comprehensive regression test suite for the played-card visibility bug:
- Every player must see their own played card on their own table (both mid-round
  and round-completing / attack plays).
- Every other player and spectator must continue seeing that same played card.
- The played card must disappear from the playing player's hand immediately.
- No duplicate cards may be rendered.
- Tested across 2, 3, 4 (exact ♦3/♦5/♦6/♦8 scenario), 7, and 10 players,
  plus round resolution, attack-card collection, reconnect, spectator privacy,
  Play Again, Host Restart Game, and real frontend TableUI + App DOM in Node VM.
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.room_manager import room_manager

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


class TestPlayedCardVisibility(unittest.TestCase):

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

    def _create_started_room(self, num_players: int, deck_count: int = 1, with_spectator: bool = True):
        clients = [self._new_client() for _ in range(num_players)]
        r0 = clients[0].emit('create_room', {
            'playerName': 'P1',
            'isPrivate': True,
            'maxPlayers': max(2, num_players),
            'deckCount': deck_count,
        }, callback=True)
        self.assertTrue(r0['success'], f"create_room failed: {r0}")
        code = r0['room_code']
        ids = [r0['player_id']]
        tokens = [r0['reconnect_token']]

        for i in range(1, num_players):
            rj = clients[i].emit('join_room', {
                'roomCode': code,
                'playerName': f'P{i + 1}',
            }, callback=True)
            self.assertTrue(rj['success'], f"join_room P{i + 1} failed: {rj}")
            ids.append(rj['player_id'])
            tokens.append(rj['reconnect_token'])

        spec = None
        spec_id = None
        if with_spectator:
            spec = self._new_client()
            rs = spec.emit('join_as_spectator', {'roomCode': code, 'spectatorName': 'SpecEye'}, callback=True)
            self.assertTrue(rs['success'])
            spec_id = rs['spectator_id']

        r_start = clients[0].emit('start_game', {'roomCode': code, 'playerId': ids[0]}, callback=True)
        self.assertTrue(r_start['success'], f"start_game failed: {r_start}")
        room = room_manager.get_room(code)

        for c in clients:
            c.get_received()
        if spec:
            spec.get_received()

        return {
            'code': code,
            'room': room,
            'clients': clients,
            'ids': ids,
            'tokens': tokens,
            'id_to_client': dict(zip(ids, clients)),
            'spec': spec,
            'spec_id': spec_id,
        }

    def _verify_full_round_for_player_count(self, num_players: int, deck_count: int = 1):
        """
        Play one full normal round where every player plays a Diamond card in order.
        Verify at every step that:
          - Server emits `card_played` to the playing player AND every other player & spectator.
          - Played card disappears from the playing player's personalized `my_hand`.
          - Mid-round `game_state.played_cards` and `spectator_state.played_cards` match across all clients.
          - On round completion, `round_resolved.played_cards` contains ALL N played cards in exact order
            with zero duplicates, and every client receives the exact same sequence.
          - Spectator never receives any hidden card IDs from any player's hand.
        """
        ctx = self._create_started_room(num_players=num_players, deck_count=deck_count, with_spectator=True)
        code, room, clients, id_to_c, spec = ctx['code'], ctx['room'], ctx['clients'], ctx['id_to_client'], ctx['spec']
        gs = room.game_state

        # Deterministic round: every player holds a unique Diamond card + one filler Club card
        ranks = ['3', '5', '6', '8', '9', '10', 'J', 'Q', 'K', 'A']
        planned_card_ids = []
        for idx, gp in enumerate(gs.players):
            cid = f'd_r1_p{idx}'
            filler_id = f'c_keep_p{idx}'
            gp.hand = [
                {'id': cid, 'rank': ranks[idx], 'suit': 'D', 'deck_index': 0},
                {'id': filler_id, 'rank': '2', 'suit': 'C', 'deck_index': 0},
            ]
            planned_card_ids.append(cid)
        gs.round_number = 2  # Any suit can lead
        gs.current_player_idx = 0
        gs._start_new_round()

        expected_so_far = []
        for step_idx in range(num_players):
            cp = gs.current_player
            cid = planned_card_ids[step_idx]
            expected_so_far.append(cid)
            is_last_card_of_round = (step_idx == num_players - 1)

            res = id_to_c[cp.id].emit('play_card', {
                'roomCode': code,
                'playerId': cp.id,
                'cardId': cid,
            }, callback=True)
            self.assertTrue(res['success'], f"{num_players}p step {step_idx} play_card failed: {res}")

            # Every player (INCLUDING the playing player) must receive card_played for cid
            for p_idx, cli in enumerate(clients):
                evts = cli.get_received()
                cp_evts = [e['args'][0] for e in evts if e['name'] == 'card_played']
                self.assertEqual(len(cp_evts), 1, f"{num_players}p: P{p_idx + 1} missing card_played at step {step_idx}")
                self.assertEqual(cp_evts[0]['card']['id'], cid)
                self.assertEqual(cp_evts[0]['player_id'], cp.id)
                self.assertEqual(cp_evts[0]['match_id'], room.match_id)

                gs_evts = [e['args'][0] for e in evts if e['name'] == 'game_state']
                self.assertEqual(len(gs_evts), 1)
                st = gs_evts[0]

                # Playing player's hand no longer contains the played card
                if ctx['ids'][p_idx] == cp.id:
                    my_ids = [c['id'] for c in st['my_hand']]
                    self.assertNotIn(cid, my_ids, f"{num_players}p: played card stayed in player's hand")

                if not is_last_card_of_round:
                    table_ids = [pc['card']['id'] for pc in st['played_cards']]
                    self.assertEqual(table_ids, expected_so_far)
                    self.assertEqual(len(table_ids), len(set(table_ids)), "Duplicate card in game_state.played_cards")
                else:
                    rr_evts = [e['args'][0] for e in evts if e['name'] == 'round_resolved']
                    self.assertEqual(len(rr_evts), 1)
                    rr_ids = [pc['card']['id'] for pc in rr_evts[0]['played_cards']]
                    self.assertEqual(rr_ids, expected_so_far)
                    self.assertEqual(len(rr_ids), len(set(rr_ids)), "Duplicate card in round_resolved.played_cards")
                    # Next round starts empty on server
                    self.assertEqual(st['played_cards'], [])

            # Spectator sees played card and ZERO hidden hand cards
            spec_evts = spec.get_received()
            self.assertNotIn('game_state', [e['name'] for e in spec_evts])
            spec_cp = [e['args'][0] for e in spec_evts if e['name'] == 'card_played']
            self.assertEqual(len(spec_cp), 1)
            self.assertEqual(spec_cp[0]['card']['id'], cid)

            spec_states = [e['args'][0] for e in spec_evts if e['name'] == 'spectator_state']
            self.assertEqual(len(spec_states), 1)
            spec_json = json.dumps(spec_states[0])
            # None of the unplayed hidden hand cards may leak to spectator
            remaining_hidden = {c['id'] for p in gs.players for c in p.hand}
            for hidden_id in remaining_hidden:
                self.assertNotIn(hidden_id, spec_json)

        # After normal round completes, all N cards moved to common pile
        self.assertEqual(len(gs.common_pile), num_players)
        return ctx

    # ── 1. Multi-player backend & Socket.IO tests (2, 3, 4, 7, 10 players) ──

    def test_01_two_player_played_card_visibility(self):
        self._verify_full_round_for_player_count(2, deck_count=1)

    def test_02_three_player_played_card_visibility(self):
        self._verify_full_round_for_player_count(3, deck_count=1)

    def test_03_four_player_exact_diamonds_scenario(self):
        self._verify_full_round_for_player_count(4, deck_count=1)

    def test_04_seven_player_played_card_visibility(self):
        self._verify_full_round_for_player_count(7, deck_count=2)

    def test_05_ten_player_six_deck_played_card_visibility(self):
        self._verify_full_round_for_player_count(10, deck_count=6)

    # ── 2. Attack-card collection, Reconnect, Play Again & Host Restart ──

    def test_06_attack_play_visibility_and_collection(self):
        ctx = self._create_started_room(num_players=4, deck_count=1, with_spectator=True)
        code, room, clients, id_to_c, spec = ctx['code'], ctx['room'], ctx['clients'], ctx['id_to_client'], ctx['spec']
        gs = room.game_state

        gs.players[0].hand = [{'id': 'atk_d3', 'rank': '3', 'suit': 'D'}, {'id': 'keep0', 'rank': '2', 'suit': 'C'}]
        gs.players[1].hand = [{'id': 'atk_d9', 'rank': '9', 'suit': 'D'}, {'id': 'keep1', 'rank': '4', 'suit': 'C'}]
        gs.players[2].hand = [{'id': 'atk_hK', 'rank': 'K', 'suit': 'H'}, {'id': 'keep2', 'rank': '5', 'suit': 'C'}]
        gs.players[3].hand = [{'id': 'atk_d7', 'rank': '7', 'suit': 'D'}, {'id': 'keep3', 'rank': '6', 'suit': 'C'}]
        gs.round_number = 2
        gs.current_player_idx = 0
        gs._start_new_round()

        # P1 plays ♦3, P2 plays ♦9, P3 attacks with ♥K (immediately resolves round; P2 collects ♦3, ♦9, ♥K)
        for p_idx, cid in ((0, 'atk_d3'), (1, 'atk_d9'), (2, 'atk_hK')):
            pid = gs.players[p_idx].id
            res = id_to_c[pid].emit('play_card', {'roomCode': code, 'playerId': pid, 'cardId': cid}, callback=True)
            self.assertTrue(res['success'])
            if p_idx < 2:
                for cli in (*clients, spec):
                    cli.get_received()

        # On P3's attack play, P3 itself AND all other players & spectator receive card_played + round_resolved
        attacker_id = gs.players[2].id
        winner_id = gs.players[1].id
        for idx, cli in enumerate(clients):
            evts = cli.get_received()
            cp = [e['args'][0] for e in evts if e['name'] == 'card_played'][-1]
            self.assertEqual(cp['card']['id'], 'atk_hK')
            self.assertEqual(cp['player_id'], attacker_id)
            self.assertTrue(cp['is_attack'])

            rr = [e['args'][0] for e in evts if e['name'] == 'round_resolved'][-1]
            self.assertTrue(rr['is_attack'])
            self.assertEqual(rr['winner_id'], winner_id)
            self.assertEqual([x['card']['id'] for x in rr['played_cards']], ['atk_d3', 'atk_d9', 'atk_hK'])

            st = [e['args'][0] for e in evts if e['name'] == 'game_state'][-1]
            my_ids = {c['id'] for c in st['my_hand']}
            if ctx['ids'][idx] == attacker_id:
                self.assertNotIn('atk_hK', my_ids)
            elif ctx['ids'][idx] == winner_id:
                self.assertTrue({'atk_d3', 'atk_d9', 'atk_hK'}.issubset(my_ids))

        # Spectator sees attack card & zero hidden cards
        spec_evts = spec.get_received()
        spec_st = [e['args'][0] for e in spec_evts if e['name'] == 'spectator_state'][-1]
        self.assertNotIn('keep0', json.dumps(spec_st))
        self.assertNotIn('keep1', json.dumps(spec_st))

    def test_07_reconnect_preserves_played_cards_including_own_card(self):
        ctx = self._create_started_room(num_players=4, deck_count=1, with_spectator=False)
        code, room, clients, ids, tokens = ctx['code'], ctx['room'], ctx['clients'], ctx['ids'], ctx['tokens']
        gs = room.game_state

        for idx, gp in enumerate(gs.players):
            gp.hand = [
                {'id': f'rec_d{idx}', 'rank': ['3', '5', '6', '8'][idx], 'suit': 'D'},
                {'id': f'rec_c{idx}', 'rank': '2', 'suit': 'C'},
            ]
        gs.round_number = 2
        gs.current_player_idx = 0
        gs._start_new_round()

        p1_id = gs.players[0].id
        p2_id = gs.players[1].id
        p1_idx = ids.index(p1_id)
        p2_idx = ids.index(p2_id)

        self.assertTrue(clients[p1_idx].emit('play_card', {'roomCode': code, 'playerId': p1_id, 'cardId': 'rec_d0'}, callback=True)['success'])
        self.assertTrue(clients[p2_idx].emit('play_card', {'roomCode': code, 'playerId': p2_id, 'cardId': 'rec_d1'}, callback=True)['success'])

        # P2 refreshes / reconnects mid-round and must see BOTH P1's card and P2's OWN card on the table
        clients[p2_idx].disconnect()
        p2_reconn = self._new_client()
        rec = p2_reconn.emit('reconnect_session', {'roomCode': code, 'reconnectToken': tokens[p2_idx]}, callback=True)
        self.assertTrue(rec['success'])
        evts = p2_reconn.get_received()
        st = [e['args'][0] for e in evts if e['name'] == 'game_state'][-1]
        self.assertEqual([pc['card']['id'] for pc in st['played_cards']], ['rec_d0', 'rec_d1'])
        self.assertNotIn('rec_d1', [c['id'] for c in st['my_hand']])

    def test_08_play_again_and_host_restart_preserve_played_card_visibility(self):
        ctx = self._create_started_room(num_players=2, deck_count=1, with_spectator=True)
        code, room, clients, ids, id_to_c, spec = (
            ctx['code'], ctx['room'], ctx['clients'], ctx['ids'], ctx['id_to_client'], ctx['spec']
        )
        gs = room.game_state

        # Finish Match 1 quickly
        gs.players[0].hand = [{'id': 'm1_a', 'rank': 'A', 'suit': 'S'}]
        gs.players[1].hand = [{'id': 'm1_2', 'rank': '2', 'suit': 'S'}, {'id': 'm1_3', 'rank': '3', 'suit': 'H'}]
        gs.current_player_idx = 0
        gs._start_new_round()
        for _ in range(2):
            cp = gs.current_player
            self.assertTrue(id_to_c[cp.id].emit('play_card', {'roomCode': code, 'playerId': cp.id, 'cardId': cp.hand[0]['id']}, callback=True)['success'])
        self.assertEqual(room.status, 'finished')

        # Ready + Play Again -> Match 2
        for pid in ids:
            self.assertTrue(id_to_c[pid].emit('set_post_match_ready', {'roomCode': code, 'playerId': pid, 'ready': True}, callback=True)['success'])
        self.assertTrue(id_to_c[ids[1]].emit('play_again', {'roomCode': code, 'playerId': ids[1]}, callback=True)['success'])
        for c in (*clients, spec):
            c.get_received()

        # First play in Match 2: starter plays A♠, both clients + spectator receive card_played with Match 2 match_id
        cp2 = room.game_state.current_player
        ace_card = next(c for c in cp2.hand if c['rank'] == 'A' and c['suit'] == 'S')
        self.assertTrue(id_to_c[cp2.id].emit('play_card', {'roomCode': code, 'playerId': cp2.id, 'cardId': ace_card['id']}, callback=True)['success'])
        for cli in (*clients, spec):
            evts = cli.get_received()
            cp_evts = [e['args'][0] for e in evts if e['name'] == 'card_played']
            self.assertEqual(len(cp_evts), 1)
            self.assertEqual(cp_evts[0]['card']['id'], ace_card['id'])
            self.assertEqual(cp_evts[0]['match_id'], room.match_id)

        # Host Restart Game -> Match 3
        self.assertTrue(id_to_c[ids[0]].emit('restart_game', {'roomCode': code, 'playerId': ids[0]}, callback=True)['success'])
        for c in (*clients, spec):
            c.get_received()

        cp3 = room.game_state.current_player
        ace3 = next(c for c in cp3.hand if c['rank'] == 'A' and c['suit'] == 'S')
        self.assertTrue(id_to_c[cp3.id].emit('play_card', {'roomCode': code, 'playerId': cp3.id, 'cardId': ace3['id']}, callback=True)['success'])
        for cli in (*clients, spec):
            evts = cli.get_received()
            cp_evts = [e['args'][0] for e in evts if e['name'] == 'card_played']
            self.assertEqual(len(cp_evts), 1)
            self.assertEqual(cp_evts[0]['card']['id'], ace3['id'])
            self.assertEqual(cp_evts[0]['match_id'], room.match_id)

    # ── 3. Real Frontend DOM Tests in Node VM (main.js + table.js + card-renderer.js) ──

    def test_09_frontend_exact_four_player_own_played_card_visible_and_no_duplicates_in_node(self):
        """
        Loads real card-renderer.js + table.js + main.js in Node VM and verifies:
        1. Exact 4-player scenario (P1 ♦3, P2 ♦5, P3 ♦6, P4 ♦8) on P4's own client:
           - P4 sees ♦3, ♦5, ♦6 as P1–P3 play.
           - When P4 plays ♦8 (which triggers card_played -> round_resolved -> game_state):
             * ♦8 IMMEDIATELY disappears from P4's #hand-row and selfCardCount decrements.
             * ♦8 IMMEDIATELY appears on P4's #played-cards-row alongside ♦3, ♦5, ♦6 (all 4 cards in order).
             * Duplicate card_played or syncPlayedCards NEVER renders duplicates.
             * Multi-deck distinct physical copies of the same rank+suit (different card IDs) BOTH render.
             * Cards remain visible until the 1800ms round-resolution timer fires.
             * A fast Round 2 card played during the 380ms collectPlayedCards animation is NOT wiped out.
        2. Attack play by local player renders attack card on own table + shows Attack banner.
        3. Spectator client renders all 4 public played cards and zero hidden hand cards.
        """
        script = r"""
const fs = require('fs');
const vm = require('vm');

const cardRendererJs = fs.readFileSync('frontend/js/ui/card-renderer.js', 'utf8');
const tableJs = fs.readFileSync('frontend/js/ui/table.js', 'utf8');
const mainJs = fs.readFileSync('frontend/js/main.js', 'utf8');

class MockElement {
  constructor(tag, id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = '';
    this.textContent = '';
    this._innerHTML = '';
    this.style = { setProperty: () => {} };
    this.dataset = {};
    this.children = [];
    this.parentNode = null;
    this.disabled = false;
    this.value = '';
    this.classList = {
      add: (...cls) => {
        const s = new Set(this.className.split(/\s+/).filter(Boolean));
        cls.forEach(c => s.add(c));
        this.className = Array.from(s).join(' ');
      },
      remove: (...cls) => {
        const s = new Set(this.className.split(/\s+/).filter(Boolean));
        cls.forEach(c => s.delete(c));
        this.className = Array.from(s).join(' ');
      },
      toggle: (c, force) => {
        const has = this.classList.contains(c);
        const next = (force === undefined) ? !has : !!force;
        if (next) this.classList.add(c); else this.classList.remove(c);
      },
      contains: (c) => this.className.split(/\s+/).filter(Boolean).includes(c),
    };
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(val) {
    this._innerHTML = String(val);
    this.children = [];
    if (this._innerHTML.includes('empty-zone-hint')) {
      const hint = new MockElement('div');
      hint.className = 'empty-zone-hint';
      hint.textContent = 'Waiting for first card…';
      this.appendChild(hint);
    }
  }
  appendChild(ch) {
    if (ch.parentNode) ch.remove();
    ch.parentNode = this;
    this.children.push(ch);
    return ch;
  }
  insertBefore(ch, ref) {
    return this.appendChild(ch);
  }
  remove() {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx !== -1) this.parentNode.children.splice(idx, 1);
      this.parentNode = null;
    }
  }
  addEventListener() {}
  setAttribute() {}
  scrollIntoView() {}
  _matches(sel) {
    const parts = sel.split(',').map(s => s.trim());
    return parts.some(p => {
      if (p === '[data-clearing="1"]') return this.dataset.clearing === '1';
      if (p.startsWith('.')) return this.classList.contains(p.slice(1));
      return false;
    });
  }
  closest(sel) {
    let cur = this;
    while (cur) {
      if (cur._matches(sel)) return cur;
      cur = cur.parentNode;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (node) => {
      for (const ch of node.children) {
        if (ch._matches(sel)) out.push(ch);
        walk(ch);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }
}

function createClientHarness(localPlayerId, isSpectator = false) {
  const byId = {};
  const getEl = (id) => {
    if (!byId[id]) byId[id] = new MockElement('div', id);
    return byId[id];
  };
  [
    'hud-room-code', 'hud-deck-count', 'hud-status', 'turn-text', 'turn-indicator',
    'turn-timer-badge', 'turn-timer-text', 'opponents-top', 'opponents-left',
    'opponents-right', 'played-cards-row', 'attack-banner', 'attack-sub',
    'common-pile-count', 'self-avatar', 'self-name', 'self-card-count',
    'self-attack-zone', 'self-attack-count', 'hand-row', 'hand-container',
    'action-bar', 'action-hint', 'btn-play-card', 'ingame-menu', 'menu-backdrop',
    'confirm-exit', 'btn-table-emoji', 'table-emoji-panel', 'btn-ingame-chat',
    'hud-spectator-pill', 'hud-spectator-count', 'spectator-banner',
    'spectator-popover', 'spectator-popover-list', 'table-felt', 'screen-game',
    'screen-results', 'screen-menu', 'activity-log-list',
  ].forEach(getEl);

  const timers = [];
  let nextTimer = 1;
  const fakeSetTimeout = (fn, ms) => {
    const id = nextTimer++;
    timers.push({ id, fn, ms, cleared: false, ran: false });
    return id;
  };
  const fakeClearTimeout = (id) => {
    const t = timers.find(x => x.id === id);
    if (t) t.cleared = true;
  };

  let soundCardPlayCount = 0;
  let attackBannerShown = [];
  let savedState = null;

  const ctx = {
    console,
    window: {
      innerWidth: 1366, innerHeight: 768,
      history: { state: {}, pushState: () => {}, replaceState: () => {}, back: () => {}, go: () => {} },
      location: { href: 'http://localhost/' },
      addEventListener: () => {},
    },
    document: {
      readyState: 'complete',
      getElementById: getEl,
      createElement: (tag) => new MockElement(tag),
      querySelector: (sel) => (sel === '.self-info-row' ? getEl('self-info-row') : null),
      querySelectorAll: () => [],
      addEventListener: () => {},
    },
    Storage: {
      getSettings: () => ({ animations: true, sound: true }),
      getActiveSession: () => null,
    },
    Sound: {
      click: () => {},
      cardPlay: () => { soundCardPlayCount++; },
      attack: () => {},
      playerFinish: () => {},
      kazhudhai: () => {},
    },
    Animations: {
      dealHand: () => {},
      collectPlayedCards: (cards, cb) => {
        fakeSetTimeout(() => { if (cb) cb(); }, 380);
      },
      flash: () => {},
      flashAttack: () => {},
      screenShake: () => {},
      confettiCelebration: () => {},
    },
    GameClient: {
      isActive: () => !!savedState,
      getState: () => savedState,
      setState: (s) => { savedState = s; },
      reset: () => { savedState = null; },
    },
    OnlineClient: {
      getPlayerId: () => (isSpectator ? null : localPlayerId),
      isSpectator: () => isSpectator,
      getRoomCode: () => 'KZ4444',
      getCurrentSenderId: () => (isSpectator ? 'spec_1' : localPlayerId),
      playCard: () => {},
    },
    OfflineClient: { reset: () => {} },
    MenuUI: { init: () => {}, hideModal: () => {} },
    VoiceClient: { leaveVoice: () => {} },
    setTimeout: fakeSetTimeout,
    clearTimeout: fakeClearTimeout,
    setInterval: () => 1,
    clearInterval: () => {},
    Date, Set, Map, Array, Object, String, Number, Boolean, Math, Error,
  };

  vm.createContext(ctx);
  vm.runInContext(
    cardRendererJs + '\n' + tableJs + '\n' + mainJs +
    '\nglobalThis.CardRenderer = CardRenderer; globalThis.TableUI = TableUI; globalThis.App = App; globalThis.Screens = Screens;',
    ctx
  );

  // Spy on showAttackBanner
  const origBanner = ctx.TableUI.showAttackBanner;
  ctx.TableUI.showAttackBanner = (name) => {
    attackBannerShown.push(name);
    origBanner(name);
  };

  ctx.TableUI.init({ roomCode: 'KZ4444', deckCount: 1, playerName: isSpectator ? 'Spec' : localPlayerId });
  ctx.App.prepareForNewMatch({ match_id: 'match_4p', room_code: 'KZ4444', deck_count: 1, reason: 'start' });
  ctx.Screens.go('screen-game');

  const getPlayedIds = () =>
    byId['played-cards-row'].querySelectorAll('.playing-card').filter(e => !e.closest('[data-clearing="1"]')).map(e => e.dataset.cardId);
  const getHandIds = () =>
    byId['hand-row'].querySelectorAll('.playing-card').map(e => e.dataset.cardId);

  return {
    ctx, byId, timers, getPlayedIds, getHandIds,
    getSoundCount: () => soundCardPlayCount,
    getAttackBanners: () => attackBannerShown,
  };
}

// ── Test A: Exact 4-player scenario on P4's own client (P1 ♦3, P2 ♦5, P3 ♦6, P4 ♦8) ──
const p4 = createClientHarness('p4', false);
const players = [
  { id: 'p1', name: 'Player 1', cardCount: 2, position: 1 },
  { id: 'p2', name: 'Player 2', cardCount: 2, position: 2 },
  { id: 'p3', name: 'Player 3', cardCount: 2, position: 3 },
  { id: 'p4', name: 'Player 4', cardCount: 2, position: 4 },
];
const d3 = { id: 'card_d3', rank: '3', suit: 'D' };
const d5 = { id: 'card_d5', rank: '5', suit: 'D' };
const d6 = { id: 'card_d6', rank: '6', suit: 'D' };
const d8 = { id: 'card_d8', rank: '8', suit: 'D' };
const c2 = { id: 'card_c2', rank: '2', suit: 'C' };

// Initial state for P4: holds ♦8 and ♣2
p4.ctx.App.renderOnlineState({
  match_id: 'match_4p', status: 'playing', round_number: 2,
  current_player_id: 'p1', players, my_hand: [d8, c2], played_cards: [], common_pile_count: 0,
});
if (p4.getHandIds().join(',') !== 'card_d8,card_c2') process.exit(1);

// P1, P2, P3 play ♦3, ♦5, ♦6
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p1', player_name: 'Player 1', card: d3, is_attack: false });
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p2', player_name: 'Player 2', card: d5, is_attack: false });
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p3', player_name: 'Player 3', card: d6, is_attack: false });
if (p4.getPlayedIds().join(',') !== 'card_d3,card_d5,card_d6') process.exit(2);

// P4 plays ♦8 (completes the round -> server emits card_played, then round_resolved, then next-round game_state)
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p4', player_name: 'Player 4', card: d8, is_attack: false });

// Immediately after card_played: ♦8 MUST be visible on P4's table AND removed from P4's hand!
if (p4.getPlayedIds().join(',') !== 'card_d3,card_d5,card_d6,card_d8') process.exit(3);
if (p4.getHandIds().join(',') !== 'card_c2') process.exit(4);
if (p4.byId['self-card-count'].textContent !== '1 card') process.exit(5);

// Duplicate card_played must NOT duplicate ♦8
const soundBeforeDup = p4.getSoundCount();
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p4', player_name: 'Player 4', card: d8, is_attack: false });
if (p4.getPlayedIds().join(',') !== 'card_d3,card_d5,card_d6,card_d8') process.exit(6);
if (p4.getSoundCount() !== soundBeforeDup) process.exit(7);

// round_resolved arrives (sets _isRoundPaused=true) and next-round game_state arrives (played_cards=[])
p4.ctx.App.handleOnlineRoundResolution({
  match_id: 'match_4p', is_attack: false, winner_id: 'p4', winner_name: 'Player 4',
  winning_card: d8,
  played_cards: [
    { player_id: 'p1', player_name: 'Player 1', card: d3, is_attack: false },
    { player_id: 'p2', player_name: 'Player 2', card: d5, is_attack: false },
    { player_id: 'p3', player_name: 'Player 3', card: d6, is_attack: false },
    { player_id: 'p4', player_name: 'Player 4', card: d8, is_attack: false },
  ],
});
p4.ctx.App.renderOnlineState({
  match_id: 'match_4p', status: 'playing', round_number: 3,
  current_player_id: 'p4', players, my_hand: [c2], played_cards: [], common_pile_count: 4,
});

// During the 1800ms pause, all 4 played cards MUST remain visible on P4's table!
if (p4.getPlayedIds().join(',') !== 'card_d3,card_d5,card_d6,card_d8') process.exit(8);

// Fire the 1800ms round-resolution timer -> schedules 380ms collectPlayedCards animation
const resTimer = p4.timers.find(t => !t.cleared && t.ms === 1800);
if (!resTimer) process.exit(9);
resTimer.fn();

// Fast Round 2 card played BEFORE the 380ms clear callback fires -> must NOT be wiped by old callback!
p4.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p4', player_name: 'Player 4', card: c2, is_attack: false });
const collectTimer = p4.timers.find(t => !t.cleared && t.ms === 380);
if (collectTimer) collectTimer.fn();
if (p4.getPlayedIds().join(',') !== 'card_c2') process.exit(10);

// ── Test B: Multi-deck duplicate rank+suit (two distinct card IDs) both render cleanly ──
const d8Deck2 = { id: 'card_d8_deck2', rank: '8', suit: 'D' };
p4.ctx.TableUI.clearPlayedCards(false);
p4.ctx.TableUI.addPlayedCard(d8, 'Player 1', false);
p4.ctx.TableUI.addPlayedCard(d8Deck2, 'Player 2', false);
if (p4.getPlayedIds().join(',') !== 'card_d8,card_d8_deck2') process.exit(11);

// ── Test C: Local player attack play renders card on own table + shows attack banner ──
const p3 = createClientHarness('p3', false);
const hK = { id: 'card_hK', rank: 'K', suit: 'H' };
p3.ctx.App.renderOnlineState({
  match_id: 'match_4p', status: 'playing', round_number: 2,
  current_player_id: 'p3', players, my_hand: [hK, c2], played_cards: [{ player_id: 'p1', player_name: 'Player 1', card: d3, is_attack: false }], common_pile_count: 0,
});
p3.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p3', player_name: 'Player 3', card: hK, is_attack: true });
if (p3.getPlayedIds().join(',') !== 'card_d3,card_hK') process.exit(12);
if (p3.getHandIds().join(',') !== 'card_c2') process.exit(13);
if (!p3.getAttackBanners().includes('Player 3')) process.exit(14);

// ── Test D: Spectator sees all 4 public played cards and zero hidden hand cards ──
const spec = createClientHarness(null, true);
spec.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p1', player_name: 'Player 1', card: d3, is_attack: false });
spec.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p2', player_name: 'Player 2', card: d5, is_attack: false });
spec.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p3', player_name: 'Player 3', card: d6, is_attack: false });
spec.ctx.App.handleOnlineCardPlayed({ match_id: 'match_4p', player_id: 'p4', player_name: 'Player 4', card: d8, is_attack: false });
if (spec.getPlayedIds().join(',') !== 'card_d3,card_d5,card_d6,card_d8') process.exit(15);
if (spec.getHandIds().length !== 0) process.exit(16);

console.log('FRONTEND_PLAYED_CARD_VISIBILITY_OK');
process.exit(0);
"""
        out = self._run_node(script)
        self.assertIn('FRONTEND_PLAYED_CARD_VISIBILITY_OK', out)


if __name__ == '__main__':
    unittest.main()
