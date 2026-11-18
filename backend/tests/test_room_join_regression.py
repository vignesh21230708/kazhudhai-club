"""
KAZHUDHAI CLUB — backend/tests/test_room_join_regression.py
Regression tests for Room Joining & Multi-Tab Session Isolation:
  - Same-browser Tab 2 never hijacks Tab 1's active room session from shared localStorage
  - Same-tab reload preserves and restores the tab's own exact session via sessionStorage
  - Full app/browser restart (after owner tab closes/expires) still recovers session from localStorage
  - Clearing Tab 2's session does not wipe Tab 1's active session
  - Private and public Create Room -> Join Room with trimmed/lowercase codes and distinct identities
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from game_engine.room_manager import room_manager


class TestRoomJoinRegression(unittest.TestCase):

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

    def test_01_multi_tab_session_isolation_and_restart_recovery_in_node(self):
        """Verify Storage isolates live tabs via sessionStorage + heartbeat while preserving restart recovery."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        storage_js_path = os.path.join(base_dir, 'frontend', 'js', 'utils', 'storage.js').replace('\\', '/')

        node_script = f"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const code = fs.readFileSync('{storage_js_path}', 'utf8') + '\\nmodule.exports = Storage;';

function makeStore() {{
  const map = new Map();
  return {{
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _map: map,
  }};
}}

const sharedLocal = makeStore();

function loadTab(existingSessionStore) {{
  const sess = existingSessionStore || makeStore();
  const listeners = {{}};
  const sandbox = {{
    localStorage: sharedLocal,
    sessionStorage: sess,
    window: {{
      addEventListener: (ev, fn) => {{ listeners[ev] = listeners[ev] || []; listeners[ev].push(fn); }},
    }},
    setInterval: () => 1,
    clearInterval: () => {{}},
    Date,
    Math,
    JSON,
    Object,
    String,
    Boolean,
    module: {{ exports: {{}} }},
  }};
  vm.runInNewContext(code, sandbox);
  return {{ Storage: sandbox.module.exports, sessionStorage: sess, listeners }};
}}

// 1. Tab 1 creates a room and saves session
const tab1 = loadTab();
tab1.Storage.saveActiveSession({{
  roomCode: 'KZ1234',
  playerId: 'usr_host',
  playerName: 'Host',
  token: 'tok_host',
  isHost: true,
}});
assert.strictEqual(tab1.Storage.getActiveSession().playerId, 'usr_host');
assert.strictEqual(tab1.Storage.getTabSession().token, 'tok_host');

// 2. Tab 2 opens in SAME browser (shared localStorage, fresh sessionStorage)
const tab2 = loadTab();
assert.strictEqual(tab2.Storage.getTabSession(), null, 'Tab 2 must not see Tab 1 tab session');
assert.strictEqual(tab2.Storage.getActiveSession(), null, 'Tab 2 must NOT hijack live Tab 1 session');

// 3. Tab 2 joins as Guest and saves its own session; Tab 1 still keeps its own session!
tab2.Storage.saveActiveSession({{
  roomCode: 'KZ1234',
  playerId: 'usr_guest',
  playerName: 'Guest',
  token: 'tok_guest',
  isHost: false,
}});
assert.strictEqual(tab1.Storage.getTabSession().playerId, 'usr_host');
assert.strictEqual(tab2.Storage.getTabSession().playerId, 'usr_guest');

// 4. Tab 1 reloads (same sessionStorage preserved) -> restores exact Host slot
const tab1Reloaded = loadTab(tab1.sessionStorage);
assert.strictEqual(tab1Reloaded.Storage.getActiveSession().playerId, 'usr_host');
assert.strictEqual(tab1Reloaded.Storage.getActiveSession().token, 'tok_host');

// 5. Tab 2 leaves and clears its session -> Tab 1 session remains intact
tab2.Storage.clearActiveSession();
assert.strictEqual(tab2.Storage.getTabSession(), null);
assert.strictEqual(tab1Reloaded.Storage.getActiveSession().playerId, 'usr_host');

// 6. Tab 1 closes (pagehide clears live heartbeat) -> brand-new app launch recovers session from localStorage
tab1Reloaded.Storage.saveActiveSession({{
  roomCode: 'KZ1234',
  playerId: 'usr_host',
  playerName: 'Host',
  token: 'tok_host',
  isHost: true,
}});
(tab1Reloaded.listeners.pagehide || []).forEach(fn => fn());

const restartedApp = loadTab(); // Fresh empty sessionStorage (simulates Android TWA / browser restart)
const recovered = restartedApp.Storage.getActiveSession();
assert.ok(recovered, 'Restarted app must recover closed tab session from localStorage');
assert.strictEqual(recovered.roomCode, 'KZ1234');
assert.strictEqual(recovered.playerId, 'usr_host');
assert.strictEqual(recovered.token, 'tok_host');

console.log('STORAGE_MULTI_TAB_OK');
"""
        proc = subprocess.run(
            ['node', '-e', node_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, f"Node test failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        self.assertIn('STORAGE_MULTI_TAB_OK', proc.stdout)

    def test_02_private_and_public_create_and_join_with_validation(self):
        # Private room create -> join with spaces & lowercase
        c1, c2 = self._new_client(), self._new_client()
        r1 = c1.emit('create_room', {'playerName': 'HostPriv', 'isPrivate': True, 'maxPlayers': 4, 'deckCount': 2}, callback=True)
        self.assertTrue(r1['success'])
        code = r1['room_code']

        # Invalid room code rejected
        bad = c2.emit('join_room', {'playerName': 'GuestPriv', 'roomCode': 'KZXXXX'}, callback=True)
        self.assertFalse(bad['success'])
        self.assertIn('does not exist', bad['message'].lower())

        # Valid room code with whitespace and lowercase accepted
        r2 = c2.emit('join_room', {'playerName': 'GuestPriv', 'roomCode': f'  {code.lower()}  '}, callback=True)
        self.assertTrue(r2['success'])
        self.assertNotEqual(r2['player_id'], r1['player_id'])
        self.assertNotEqual(r2['reconnect_token'], r1['reconnect_token'])
        self.assertEqual(r2['room']['player_count'], 2)

        # Public room create -> visible via /api/rooms/public -> join
        c3, c4 = self._new_client(), self._new_client()
        r3 = c3.emit('create_room', {'playerName': 'HostPub', 'isPrivate': False, 'maxPlayers': 3, 'deckCount': 1}, callback=True)
        self.assertTrue(r3['success'])
        pub_code = r3['room_code']

        http_client = app_module.app.test_client()
        pub_list = http_client.get('/api/rooms/public').get_json()
        self.assertTrue(any(r['code'] == pub_code for r in pub_list))

        r4 = c4.emit('join_room', {'playerName': 'GuestPub', 'roomCode': pub_code}, callback=True)
        self.assertTrue(r4['success'])
        self.assertNotEqual(r4['player_id'], r3['player_id'])
        self.assertEqual(r4['room']['player_count'], 2)


if __name__ == '__main__':
    unittest.main()
