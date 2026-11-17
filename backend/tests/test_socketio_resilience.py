"""
KAZHUDHAI CLUB — backend/tests/test_socketio_resilience.py
Automated test suite verifying Socket.IO resilient loading and deduplication:
1. Service worker stale-while-revalidate caching for /js/lib/ vendor scripts.
2. Immediate Socket.IO initialization when window.io is already loaded.
3. Delayed Socket.IO initialization resolving cleanly within 3 seconds.
4. Timeout failure triggering error toast only after timeout expires.
5. Repeated concurrent initialization deduplication (single promise, single socket).
6. Disconnect resetting initialization state for subsequent connections.
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend'))
ONLINE_CLIENT_PATH = os.path.join(FRONTEND_DIR, 'js', 'game', 'online-client.js')
SERVICE_WORKER_PATH = os.path.join(FRONTEND_DIR, 'service-worker.js')


class TestSocketIOResilience(unittest.TestCase):

    def test_01_service_worker_caches_and_revalidates_vendor_scripts(self):
        """Verify service-worker.js precaches /js/lib/socket.io.min.js and uses _staleWhileRevalidate for /js/lib/."""
        self.assertTrue(os.path.isfile(SERVICE_WORKER_PATH), 'Missing frontend/service-worker.js')
        with open(SERVICE_WORKER_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        # Cache name versioning preserved
        self.assertIn("const CACHE_NAME = 'kazhudhai-club-v3';", content)

        # Precache includes local socket.io script
        self.assertIn("'/js/lib/socket.io.min.js'", content)

        # Fetch handler routes /js/lib/ to _staleWhileRevalidate
        self.assertTrue(
            "url.pathname.startsWith('/js/lib/')" in content,
            "Service worker fetch event must route /js/lib/ via stale-while-revalidate"
        )
        self.assertIn("_staleWhileRevalidate", content)

    def test_02_online_client_static_structure(self):
        """Verify online-client.js implements _waitForSocketIO, _ensureSocketAsync, and deduplication."""
        self.assertTrue(os.path.isfile(ONLINE_CLIENT_PATH), 'Missing frontend/js/game/online-client.js')
        with open(ONLINE_CLIENT_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('_waitForSocketIO', content)
        self.assertIn('_ensureSocketAsync', content)
        self.assertIn('_initPromise', content)
        self.assertIn('maxWaitMs = 3000', content)
        self.assertIn('Socket.IO library failed to load', content)

    def _run_node_script(self, script: str):
        """Helper to run a Node.js verification script and return stdout or raise on error."""
        res = subprocess.run(
            ['node', '-e', script],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
            capture_output=True,
            text=True,
            timeout=15
        )
        self.assertEqual(
            res.returncode, 0,
            f"Node test script failed (exit code {res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
        return res.stdout

    def test_03_immediate_socketio_loading_in_node(self):
        """Verify OnlineClient.initConnection() resolves immediately when io is already available."""
        script = """
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/game/online-client.js', 'utf8');
let ioCalls = 0;
const fakeSocket = { id: 'test_sid_1', connected: false, on: () => {}, off: () => {}, once: () => {}, emit: () => {}, disconnect: () => {} };
const fakeIo = () => { ioCalls++; return fakeSocket; };

const ctx = {
  console,
  window: { location: { protocol: 'https:', host: 'kazhudhai.club' }, addEventListener: () => {}, removeEventListener: () => {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  showToast: () => {},
  Storage: { getActiveSession: () => null, saveActiveSession: () => {}, clearActiveSession: () => {} },
  TableUI: { updatePlayerStatus: () => {} },
  MenuUI: { updateWaitingRoom: () => {}, clearLobbyChat: () => {}, hideWaitingRoom: () => {} },
  Screens: { go: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error,
  io: fakeIo
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.OnlineClient = OnlineClient;', ctx);

const start = Date.now();
ctx.OnlineClient.initConnection().then(sock => {
  const elapsed = Date.now() - start;
  if (!sock || sock !== fakeSocket) process.exit(1);
  if (ioCalls !== 1) process.exit(2);
  if (elapsed > 50) process.exit(3);
  console.log('SUCCESS');
}).catch(err => {
  console.error(err);
  process.exit(4);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS', stdout)

    def test_04_delayed_socketio_loading_within_3s_in_node(self):
        """Verify OnlineClient.initConnection() waits for delayed io loading (e.g. at 150ms) and succeeds."""
        script = """
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/game/online-client.js', 'utf8');
let ioCalls = 0;
const fakeSocket = { id: 'test_sid_2', connected: false, on: () => {}, off: () => {}, once: () => {}, emit: () => {}, disconnect: () => {} };
const fakeIo = () => { ioCalls++; return fakeSocket; };

const ctx = {
  console,
  window: { location: { protocol: 'https:', host: 'kazhudhai.club' }, addEventListener: () => {}, removeEventListener: () => {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  showToast: () => {},
  Storage: { getActiveSession: () => null, saveActiveSession: () => {}, clearActiveSession: () => {} },
  TableUI: { updatePlayerStatus: () => {} },
  MenuUI: { updateWaitingRoom: () => {}, clearLobbyChat: () => {}, hideWaitingRoom: () => {} },
  Screens: { go: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.OnlineClient = OnlineClient;', ctx);

// io is initially undefined, loaded after 150ms
setTimeout(() => {
  ctx.io = fakeIo;
}, 150);

const start = Date.now();
ctx.OnlineClient.initConnection().then(sock => {
  const elapsed = Date.now() - start;
  if (!sock || sock !== fakeSocket) process.exit(1);
  if (ioCalls !== 1) process.exit(2);
  if (elapsed < 140 || elapsed > 1500) process.exit(3);
  console.log('SUCCESS_DELAYED_' + elapsed);
}).catch(err => {
  console.error(err);
  process.exit(4);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_DELAYED_', stdout)

    def test_05_timeout_failure_displays_error_after_wait_in_node(self):
        """Verify OnlineClient._ensureSocketAsync(300) rejects and shows toast only after timeout."""
        script = """
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/game/online-client.js', 'utf8');
let toasts = [];

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { location: { protocol: 'https:', host: 'kazhudhai.club' }, addEventListener: () => {}, removeEventListener: () => {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  showToast: (msg, type) => { toasts.push({ msg, type }); },
  Storage: { getActiveSession: () => null, saveActiveSession: () => {}, clearActiveSession: () => {} },
  TableUI: { updatePlayerStatus: () => {} },
  MenuUI: { updateWaitingRoom: () => {}, clearLobbyChat: () => {}, hideWaitingRoom: () => {} },
  Screens: { go: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.OnlineClient = OnlineClient;', ctx);

// io remains undefined
const start = Date.now();
ctx.OnlineClient._ensureSocketAsync(300).then(() => {
  process.exit(1); // Should not succeed
}).catch(err => {
  const elapsed = Date.now() - start;
  if (elapsed < 280) process.exit(2); // Should not fail prematurely
  if (!toasts.length || !toasts[0].msg.includes('Socket.IO library failed to load')) process.exit(3);
  console.log('SUCCESS_TIMEOUT_' + elapsed);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_TIMEOUT_', stdout)

    def test_06_repeated_concurrent_initialization_deduplication_in_node(self):
        """Verify concurrent calls to initConnection() share the same promise and create only 1 socket."""
        script = """
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/game/online-client.js', 'utf8');
let ioCalls = 0;
const fakeSocket = { id: 'test_sid_dup', connected: false, on: () => {}, off: () => {}, once: () => {}, emit: () => {}, disconnect: () => {} };
const fakeIo = () => { ioCalls++; return fakeSocket; };

const ctx = {
  console,
  window: { location: { protocol: 'https:', host: 'kazhudhai.club' }, addEventListener: () => {}, removeEventListener: () => {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  showToast: () => {},
  Storage: { getActiveSession: () => null, saveActiveSession: () => {}, clearActiveSession: () => {} },
  TableUI: { updatePlayerStatus: () => {} },
  MenuUI: { updateWaitingRoom: () => {}, clearLobbyChat: () => {}, hideWaitingRoom: () => {} },
  Screens: { go: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.OnlineClient = OnlineClient;', ctx);

setTimeout(() => {
  ctx.io = fakeIo;
}, 100);

const p1 = ctx.OnlineClient.initConnection();
const p2 = ctx.OnlineClient.initConnection();
const p3 = ctx.OnlineClient.initConnection();
const p4 = ctx.OnlineClient.initConnection();
const p5 = ctx.OnlineClient.initConnection();

if (p1 !== p2 || p2 !== p3 || p3 !== p4 || p4 !== p5) {
  process.exit(1);
}

Promise.all([p1, p2, p3, p4, p5]).then(results => {
  if (ioCalls !== 1) process.exit(2);
  if (results.some(s => s !== fakeSocket)) process.exit(3);
  console.log('SUCCESS_DEDUP_5');
}).catch(err => {
  console.error(err);
  process.exit(4);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_DEDUP_5', stdout)

    def test_07_disconnect_resets_init_promise_for_future_reconnect(self):
        """Verify calling disconnect() resets _initPromise allowing clean re-connection."""
        script = """
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/game/online-client.js', 'utf8');
let ioCalls = 0;
let disconnected = false;
const fakeSocket = {
  id: 'test_sid_disc',
  connected: true,
  on: () => {},
  off: () => {},
  once: () => {},
  emit: (evt, data, cb) => { if (cb) cb({ success: true }); },
  disconnect: () => { disconnected = true; }
};
const fakeIo = () => { ioCalls++; return fakeSocket; };

const ctx = {
  console,
  window: { location: { protocol: 'https:', host: 'kazhudhai.club' }, addEventListener: () => {}, removeEventListener: () => {} },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  showToast: () => {},
  Storage: { getActiveSession: () => null, saveActiveSession: () => {}, clearActiveSession: () => {} },
  TableUI: { updatePlayerStatus: () => {} },
  MenuUI: { updateWaitingRoom: () => {}, clearLobbyChat: () => {}, hideWaitingRoom: () => {} },
  Screens: { go: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error,
  io: fakeIo
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.OnlineClient = OnlineClient;', ctx);

ctx.OnlineClient.initConnection().then(() => {
  if (ioCalls !== 1) process.exit(1);
  ctx.OnlineClient.disconnect();
  if (!disconnected) process.exit(2);

  // Re-initialize after disconnect
  return ctx.OnlineClient.initConnection();
}).then(() => {
  if (ioCalls !== 2) process.exit(3);
  console.log('SUCCESS_RECONNECT_AFTER_DISCONNECT');
}).catch(err => {
  console.error(err);
  process.exit(4);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_RECONNECT_AFTER_DISCONNECT', stdout)


if __name__ == '__main__':
    unittest.main()
