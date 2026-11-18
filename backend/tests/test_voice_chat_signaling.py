"""
KAZHUDHAI CLUB — backend/tests/test_voice_chat_signaling.py
Tests for Feature 1 (Match-Only WebRTC Voice Chat):
- ICE servers endpoint returns STUN servers + TURN from environment variables.
- Voice chat available ONLY after match start (rejected in lobby).
- Signaling relay for voice_join, voice_signal (offer/answer/candidate), and voice_leave.
- Automatic voice cleanup on player departure / disconnect.
"""
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.room_manager import room_manager
from app import app, socketio


class TestVoiceChatSignaling(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.socketio = socketio
        room_manager.rooms.clear()

    def test_01_ice_servers_default_and_turn_env(self):
        """get_ice_servers returns STUN and dynamically appends TURN from env vars."""
        c1 = self.socketio.test_client(self.app)

        # 1. Default without TURN
        res = c1.emit('get_ice_servers', callback=True)
        self.assertTrue(res['success'])
        self.assertTrue(any('stun:' in str(url) for s in res['iceServers'] for url in s.get('urls', [])))

        # 2. With TURN env vars
        os.environ['TURN_SERVER_URL'] = 'turn:relay.kazhudhai.club:3478'
        os.environ['TURN_USERNAME']   = 'testuser'
        os.environ['TURN_CREDENTIAL'] = 'testsecret'

        try:
            res_turn = c1.emit('get_ice_servers', callback=True)
            self.assertTrue(res_turn['success'])
            turn_entry = next((s for s in res_turn['iceServers'] if 'relay.kazhudhai.club' in str(s.get('urls'))), None)
            self.assertIsNotNone(turn_entry)
            self.assertEqual(turn_entry['username'], 'testuser')
            self.assertEqual(turn_entry['credential'], 'testsecret')
        finally:
            os.environ.pop('TURN_SERVER_URL', None)
            os.environ.pop('TURN_USERNAME', None)
            os.environ.pop('TURN_CREDENTIAL', None)

    def test_02_voice_chat_rejected_in_lobby_waiting_room(self):
        """Voice chat is forbidden in the lobby before the match starts."""
        c1 = self.socketio.test_client(self.app)
        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        # Attempt to join voice while room.status == 'waiting'
        voice_res = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertFalse(voice_res['success'])
        self.assertIn('only available during an active match', voice_res['message'])

    def test_03_voice_join_and_signaling_relay_during_match(self):
        """When match starts, voice_join succeeds and voice_signal relays offers/answers."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Clear initial received events
        c1.get_received()
        c2.get_received()

        # Alice joins voice (Bob has NOT joined voice yet)
        res_v1 = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertTrue(res_v1['success'])
        self.assertEqual(res_v1['peers'], [])

        # Bob is NOT in voice yet, so he must NOT receive voice_peer_joined prematurely
        c2_events = c2.get_received()
        joined_events_before = [e for e in c2_events if e['name'] == 'voice_peer_joined']
        self.assertEqual(len(joined_events_before), 0)

        # Bob joins voice - returns Alice as active peer and notifies Alice (existing voice participant)
        c1.get_received()
        res_v2 = c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)
        self.assertTrue(res_v2['success'])
        self.assertTrue(any(p['peerId'] == p1_id for p in res_v2['peers']))

        c1_joined = [e for e in c1.get_received() if e['name'] == 'voice_peer_joined']
        self.assertEqual(len(c1_joined), 1)
        self.assertEqual(c1_joined[0]['args'][0]['peerId'], p2_id)

        # Bob sends SDP offer to Alice via voice_signal
        c1.get_received()
        mock_offer = {'type': 'offer', 'sdp': 'v=0\r\no=mock...'}
        sig_res = c2.emit('voice_signal', {
            'roomCode': room_code,
            'playerId': p2_id,
            'targetPeerId': p1_id,
            'signal': mock_offer,
        }, callback=True)
        self.assertTrue(sig_res['success'])

        # Alice must receive the relayed voice_signal
        c1_events = c1.get_received()
        sig_events = [e for e in c1_events if e['name'] == 'voice_signal']
        self.assertEqual(len(sig_events), 1)
        self.assertEqual(sig_events[0]['args'][0]['fromPeerId'], p2_id)
        self.assertEqual(sig_events[0]['args'][0]['signal']['type'], 'offer')

    def test_04_voice_leave_and_disconnect_broadcast(self):
        """voice_leave and socket disconnect emit voice_peer_left."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)

        c1.get_received()

        # Bob leaves voice
        c2.emit('voice_leave', {'roomCode': room_code, 'playerId': p2_id}, callback=True)

        # Alice receives voice_peer_left
        events = c1.get_received()
        left_events = [e for e in events if e['name'] == 'voice_peer_left']
        self.assertEqual(len(left_events), 1)
        self.assertEqual(left_events[0]['args'][0]['peerId'], p2_id)

    def test_05_ice_servers_comma_separated_turn_urls(self):
        """get_ice_servers supports comma-separated TURN URLs for multiple transports."""
        c1 = self.socketio.test_client(self.app)
        os.environ['TURN_SERVER_URL'] = 'turn:relay1.kazhudhai.club:3478?transport=udp,turn:relay2.kazhudhai.club:3478?transport=tcp'
        os.environ['TURN_USERNAME']   = 'testuser'
        os.environ['TURN_CREDENTIAL'] = 'testsecret'

        try:
            res_turn = c1.emit('get_ice_servers', callback=True)
            self.assertTrue(res_turn['success'])
            turn_entry = next((s for s in res_turn['iceServers'] if 'relay1.kazhudhai.club' in str(s.get('urls'))), None)
            self.assertIsNotNone(turn_entry)
            self.assertIsInstance(turn_entry['urls'], list)
            self.assertEqual(len(turn_entry['urls']), 2)
            self.assertEqual(turn_entry['username'], 'testuser')
            self.assertEqual(turn_entry['credential'], 'testsecret')
        finally:
            os.environ.pop('TURN_SERVER_URL', None)
            os.environ.pop('TURN_USERNAME', None)
            os.environ.pop('TURN_CREDENTIAL', None)

    def _run_node_script(self, script: str):
        res = subprocess.run(
            ['node', '-e', script],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(
            res.returncode, 0,
            f"Node test script failed (exit code {res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
        return res.stdout

    def test_06_deterministic_offerer_selection_in_node(self):
        """Deterministic offerer selection: smaller ID creates offer, other waits."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

const ctx = {
  console,
  window: { AudioContext: class {} },
  document: { getElementById: () => null, addEventListener: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
const aliceVsBob = ctx.VoiceClient._isOfferer('bob');
ctx.VoiceClient.leaveVoice();

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'bob', 'Bob');
const bobVsAlice = ctx.VoiceClient._isOfferer('alice');
ctx.VoiceClient.leaveVoice();

if (aliceVsBob !== true || bobVsAlice !== false) {
  process.exit(1);
}
console.log('SUCCESS_OFFERER');
process.exit(0);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_OFFERER', stdout)

    def test_07_ice_candidate_buffering_and_draining_in_node(self):
        """Incoming ICE candidates buffer when remoteDescription is unset and drain on setRemoteDescription."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let candidatesAdded = [];
class MockRTCSessionDescription { constructor(i) { Object.assign(this, i); } }
class MockRTCIceCandidate { constructor(i) { Object.assign(this, i); } }
class MockRTCPeerConnection {
  constructor() { this.signalingState = 'stable'; this.remoteDescription = null; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createAnswer() { return { type: 'answer', sdp: 'm' }; }
  async setLocalDescription() { this.signalingState = 'stable'; }
  async setRemoteDescription(d) { this.remoteDescription = d; }
  async addIceCandidate(c) { candidatesAdded.push(c); }
  close() {}
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockRTCPeerConnection,
  RTCSessionDescription: MockRTCSessionDescription,
  RTCIceCandidate: MockRTCIceCandidate,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
ctx.VoiceClient._createPeerConnection('bob');
const peerData = ctx.VoiceClient._peers.get('bob');

// Candidates arrive before remoteDescription
ctx.VoiceClient._handleCandidate('bob', { candidate: 'cand_1' });
ctx.VoiceClient._handleCandidate('bob', { candidate: 'cand_2' });

if (peerData.candidateQueue.length !== 2 || candidatesAdded.length !== 0) {
  process.exit(1);
}

// Offer sets remoteDescription and drains queue
ctx.VoiceClient._handleOffer('bob', { type: 'offer', sdp: 'mock' }).then(() => {
  if (peerData.candidateQueue.length !== 0 || candidatesAdded.length !== 2) {
    process.exit(2);
  }
  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_BUFFER_DRAIN');
  process.exit(0);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_BUFFER_DRAIN', stdout)

    def test_08_mic_track_replacement_without_renegotiation_in_node(self):
        """Toggling microphone replaces track on sender without emitting renegotiation offers."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

class MockMediaStream {
  constructor(tracks) { this.tracks = tracks || []; }
  getTracks() { return this.tracks; }
  getAudioTracks() { return this.tracks; }
}
let sender = { track: null, replaceTrack: async (t) => { sender.track = t; } };
class MockRTCPeerConnection {
  constructor() { this.signalingState = 'stable'; }
  addTransceiver() { return { sender }; }
  getSenders() { return [sender]; }
  close() {}
}

let emittedOffers = [];
const fakeSocket = {
  emit: (evt, data) => {
    if (evt === 'voice_signal' && data.signal && data.signal.type === 'offer') emittedOffers.push(data);
  },
  on: () => {}
};

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class { resume() { return Promise.resolve(); } } },
  document: { getElementById: () => null, addEventListener: () => {} },
  RTCPeerConnection: MockRTCPeerConnection,
  MediaStream: MockMediaStream,
  navigator: { mediaDevices: { getUserMedia: async () => new MockMediaStream([{ kind: 'audio', enabled: true, stop: () => {} }]) } },
  showToast: () => {},
  TableUI: { setPlayerSpeaking: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
ctx.VoiceClient._createPeerConnection('bob');

ctx.VoiceClient.toggleMic().then(() => {
  if (!sender.track || sender.track.kind !== 'audio') process.exit(1);
  if (emittedOffers.length !== 0) process.exit(2);
  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_REPLACE_TRACK');
  process.exit(0);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_REPLACE_TRACK', stdout)

    def test_09_remote_track_fallback_and_single_audio_element_in_node(self):
        """ontrack falls back to MediaStream([track]) and maintains a single audio element."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

class MockMediaStream {
  constructor(tracks) { this.tracks = tracks || []; }
}
class MockRTCPeerConnection {
  constructor() { this.signalingState = 'stable'; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  close() {}
}

const audioElements = [];
const fakeDoc = {
  getElementById: (id) => audioElements.find(a => a.id === id) || null,
  createElement: (tag) => {
    const el = { id: '', style: {}, srcObject: null, play: async () => {} };
    audioElements.push(el);
    return el;
  },
  body: { appendChild: () => {} },
  addEventListener: () => {}
};

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: fakeDoc,
  RTCPeerConnection: MockRTCPeerConnection,
  MediaStream: MockMediaStream,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
const pc = ctx.VoiceClient._createPeerConnection('bob');
const peerData = ctx.VoiceClient._peers.get('bob');

const mockTrack = { kind: 'audio', id: 't_raw' };
pc.ontrack({ track: mockTrack, streams: [] });

if (!peerData.stream || !peerData.audioEl || audioElements.length !== 1) {
  process.exit(1);
}

// Second event should reuse existing audio element
pc.ontrack({ track: mockTrack, streams: [] });
if (audioElements.length !== 1) {
  process.exit(2);
}

ctx.VoiceClient.leaveVoice();
console.log('SUCCESS_TRACK_FALLBACK');
process.exit(0);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_TRACK_FALLBACK', stdout)

    def test_10_autoplay_failure_recovery_on_user_gesture_in_node(self):
        """Autoplay rejection is tracked and recovered upon unlockAudioPlayback invocation."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

class MockMediaStream { constructor(t) { this.tracks = t || []; } }
class MockRTCPeerConnection {
  constructor() { this.signalingState = 'stable'; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  close() {}
}

let playShouldFail = true;
let playCallCount = 0;
const audioElements = [];
const fakeDoc = {
  getElementById: (id) => audioElements.find(a => a.id === id) || null,
  createElement: () => {
    const el = {
      id: '',
      style: {},
      srcObject: null,
      play: async () => {
        playCallCount++;
        if (playShouldFail) throw new Error('NotAllowedError');
      }
    };
    audioElements.push(el);
    return el;
  },
  body: { appendChild: () => {} },
  addEventListener: () => {}
};

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class { resume() { return Promise.resolve(); } } },
  document: fakeDoc,
  RTCPeerConnection: MockRTCPeerConnection,
  MediaStream: MockMediaStream,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
const pc = ctx.VoiceClient._createPeerConnection('bob');

pc.ontrack({ track: { kind: 'audio' }, streams: [] });

setTimeout(() => {
  if (playCallCount !== 1) process.exit(1);

  // User interacts with screen: unlockAudioPlayback retries
  playShouldFail = false;
  ctx.VoiceClient.unlockAudioPlayback();

  setTimeout(() => {
    if (playCallCount !== 2) process.exit(2);
    ctx.VoiceClient.leaveVoice();
    console.log('SUCCESS_AUTOPLAY_RECOVERY');
    process.exit(0);
  }, 15);
}, 15);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_AUTOPLAY_RECOVERY', stdout)

    def test_11_offer_collision_polite_rollback_handling_in_node(self):
        """Offer collision on polite peer initiates rollback and creates answer."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

class MockRTCSessionDescription { constructor(i) { Object.assign(this, i); } }
let rollbackTriggered = false;
class MockRTCPeerConnection {
  constructor() { this.signalingState = 'have-local-offer'; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createAnswer() { return { type: 'answer', sdp: 'ans' }; }
  async setLocalDescription(d) {
    if (d.type === 'rollback') { rollbackTriggered = true; this.signalingState = 'stable'; }
    else if (d.type === 'answer') { this.signalingState = 'stable'; }
  }
  async setRemoteDescription(d) { this.signalingState = 'have-remote-offer'; }
  close() {}
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockRTCPeerConnection,
  RTCSessionDescription: MockRTCSessionDescription,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

const fakeSocket = { emit: () => {}, on: () => {} };
// 'bob' is polite peer when communicating with 'alice' ('alice' < 'bob')
ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'bob', 'Bob');
ctx.VoiceClient._createPeerConnection('alice');

ctx.VoiceClient._handleOffer('alice', { type: 'offer', sdp: 'colliding_offer' }).then(() => {
  if (!rollbackTriggered) process.exit(1);
  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_ROLLBACK');
  process.exit(0);
});
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_ROLLBACK', stdout)

    def test_12_backend_active_voice_peers_tracking(self):
        """Backend tracks actual voice participants and cleans up on leave/disconnect."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)

        # Alice joins voice: Bob has NOT joined yet, so peers must be empty!
        res_v1 = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertTrue(res_v1['success'])
        self.assertEqual(res_v1['peers'], [])

        # Bob joins voice: Alice ALREADY joined, so peers contains Alice!
        res_v2 = c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)
        self.assertTrue(res_v2['success'])
        self.assertEqual(len(res_v2['peers']), 1)
        self.assertEqual(res_v2['peers'][0]['peerId'], p1_id)

        # Alice leaves voice
        c1.emit('voice_leave', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        room = room_manager.get_room(room_code)
        self.assertNotIn(p1_id, getattr(room, 'voice_peers', set()))
        self.assertIn(p2_id, getattr(room, 'voice_peers', set()))

    def test_13_laptop_joining_before_android_signaling_flow_in_node(self):
        """Signaling race: Laptop (offerer) joins first with delayed Android get_ice_servers."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

function createClient(id, name) {
  let listeners = {};
  let socket = {
    emit: (evt, data, cb) => handleServer(id, evt, data, cb),
    on: (evt, fn) => { listeners[evt] = fn; },
    _deliver: (evt, data) => { if (listeners[evt]) listeners[evt](data); }
  };

  class MockPC {
    constructor(cfg) {
      this.cfg = cfg;
      this.signalingState = 'stable';
      this.remoteDescription = null;
      this.localDescription = null;
      this.connectionState = 'new';
      this.iceConnectionState = 'new';
      this.onicecandidate = null;
      this.ontrack = null;
    }
    addTransceiver() { return { sender: { track: null, replaceTrack: async () => {} } }; }
    async createOffer() { return { type: 'offer', sdp: 'offer_from_' + id }; }
    async createAnswer() { return { type: 'answer', sdp: 'answer_from_' + id }; }
    async setLocalDescription(desc) {
      this.localDescription = desc;
      if (desc.type === 'offer') this.signalingState = 'have-local-offer';
      if (desc.type === 'answer') this.signalingState = 'stable';
      if (desc.type === 'rollback') this.signalingState = 'stable';
    }
    async setRemoteDescription(desc) {
      this.remoteDescription = desc;
      if (desc.type === 'offer') this.signalingState = 'have-remote-offer';
      if (desc.type === 'answer') {
        this.signalingState = 'stable';
        this.connectionState = 'connected';
      }
    }
    async addIceCandidate() {}
    close() { this.signalingState = 'closed'; }
  }

  const ctx = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    window: { AudioContext: class {} },
    document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
    RTCPeerConnection: MockPC,
    RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
    RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
    MediaStream: class { constructor(t){ this.tracks = t || []; } },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
  };
  vm.createContext(ctx);
  vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

  return { id, name, socket, ctx, client: ctx.VoiceClient };
}

let clients = {};
let joinedVoice = new Set();

function handleServer(fromId, evt, data, cb) {
  if (evt === 'get_ice_servers') {
    const delay = fromId === 'usr_bbb' ? 60 : 10;
    setTimeout(() => {
      const fn = typeof data === 'function' ? data : cb;
      if (fn) fn({ success: true, iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
    }, delay);
  } else if (evt === 'voice_join') {
    const existingVoiceIds = Array.from(joinedVoice).filter(k => k !== fromId);
    const activePeers = existingVoiceIds.map(k => ({ peerId: k, name: clients[k].name }));
    joinedVoice.add(fromId);
    existingVoiceIds.forEach(k => {
      clients[k].socket._deliver('voice_peer_joined', { peerId: fromId, name: clients[fromId].name });
    });
    if (cb) cb({ success: true, peers: activePeers });
  } else if (evt === 'voice_signal') {
    const target = data.targetPeerId;
    if (clients[target]) {
      clients[target].socket._deliver('voice_signal', {
        fromPeerId: fromId,
        signal: data.signal
      });
    }
  }
}

const laptop = createClient('usr_aaa', 'Laptop');
const android = createClient('usr_bbb', 'Android');
clients['usr_aaa'] = laptop;
clients['usr_bbb'] = android;

laptop.client.startVoice(laptop.socket, 'ROOM1', 'usr_aaa', 'Laptop');
android.client.startVoice(android.socket, 'ROOM1', 'usr_bbb', 'Android');

setTimeout(() => {
  const lp = laptop.client._peers.get('usr_bbb');
  const ap = android.client._peers.get('usr_aaa');
  const success = lp && ap && lp.pc.signalingState === 'stable' && lp.pc.connectionState === 'connected' && ap.pc.signalingState === 'stable';
  laptop.client.leaveVoice();
  android.client.leaveVoice();
  if (!success) {
    process.exit(1);
  }
  console.log('SUCCESS_LAPTOP_FIRST');
  process.exit(0);
}, 250);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_LAPTOP_FIRST', stdout)

    def test_14_android_joining_before_laptop_signaling_flow_in_node(self):
        """Signaling race: Android (answerer) joins first, followed by Laptop (offerer)."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

function createClient(id, name) {
  let listeners = {};
  let socket = {
    emit: (evt, data, cb) => handleServer(id, evt, data, cb),
    on: (evt, fn) => { listeners[evt] = fn; },
    _deliver: (evt, data) => { if (listeners[evt]) listeners[evt](data); }
  };

  class MockPC {
    constructor(cfg) {
      this.cfg = cfg;
      this.signalingState = 'stable';
      this.remoteDescription = null;
      this.localDescription = null;
      this.connectionState = 'new';
      this.iceConnectionState = 'new';
      this.onicecandidate = null;
      this.ontrack = null;
    }
    addTransceiver() { return { sender: { track: null, replaceTrack: async () => {} } }; }
    async createOffer() { return { type: 'offer', sdp: 'offer_from_' + id }; }
    async createAnswer() { return { type: 'answer', sdp: 'answer_from_' + id }; }
    async setLocalDescription(desc) {
      this.localDescription = desc;
      if (desc.type === 'offer') this.signalingState = 'have-local-offer';
      if (desc.type === 'answer') this.signalingState = 'stable';
      if (desc.type === 'rollback') this.signalingState = 'stable';
    }
    async setRemoteDescription(desc) {
      this.remoteDescription = desc;
      if (desc.type === 'offer') this.signalingState = 'have-remote-offer';
      if (desc.type === 'answer') {
        this.signalingState = 'stable';
        this.connectionState = 'connected';
      }
    }
    async addIceCandidate() {}
    close() { this.signalingState = 'closed'; }
  }

  const ctx = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    window: { AudioContext: class {} },
    document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
    RTCPeerConnection: MockPC,
    RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
    RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
    MediaStream: class { constructor(t){ this.tracks = t || []; } },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
  };
  vm.createContext(ctx);
  vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

  return { id, name, socket, ctx, client: ctx.VoiceClient };
}

let clients = {};
let joinedVoice = new Set();

function handleServer(fromId, evt, data, cb) {
  if (evt === 'get_ice_servers') {
    const delay = fromId === 'usr_aaa' ? 60 : 10;
    setTimeout(() => {
      const fn = typeof data === 'function' ? data : cb;
      if (fn) fn({ success: true, iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
    }, delay);
  } else if (evt === 'voice_join') {
    const existingVoiceIds = Array.from(joinedVoice).filter(k => k !== fromId);
    const activePeers = existingVoiceIds.map(k => ({ peerId: k, name: clients[k].name }));
    joinedVoice.add(fromId);
    existingVoiceIds.forEach(k => {
      clients[k].socket._deliver('voice_peer_joined', { peerId: fromId, name: clients[fromId].name });
    });
    if (cb) cb({ success: true, peers: activePeers });
  } else if (evt === 'voice_signal') {
    const target = data.targetPeerId;
    if (clients[target]) {
      clients[target].socket._deliver('voice_signal', {
        fromPeerId: fromId,
        signal: data.signal
      });
    }
  }
}

const laptop = createClient('usr_aaa', 'Laptop');
const android = createClient('usr_bbb', 'Android');
clients['usr_aaa'] = laptop;
clients['usr_bbb'] = android;

android.client.startVoice(android.socket, 'ROOM1', 'usr_bbb', 'Android');
laptop.client.startVoice(laptop.socket, 'ROOM1', 'usr_aaa', 'Laptop');

setTimeout(() => {
  const lp = laptop.client._peers.get('usr_bbb');
  const ap = android.client._peers.get('usr_aaa');
  const success = lp && ap && lp.pc.signalingState === 'stable' && lp.pc.connectionState === 'connected' && ap.pc.signalingState === 'stable';
  laptop.client.leaveVoice();
  android.client.leaveVoice();
  if (!success) {
    process.exit(1);
  }
  console.log('SUCCESS_ANDROID_FIRST');
  process.exit(0);
}, 250);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_ANDROID_FIRST', stdout)

    def test_15_delayed_get_ice_servers_and_immediate_listener_registration_in_node(self):
        """Voice signaling listeners bind immediately in startVoice, receiving early offers."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let listeners = {};
let iceCb = null;
const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers') iceCb = cb;
  },
  on: (evt, fn) => { listeners[evt] = fn; }
};

let offerHandled = false;
class MockPC {
  constructor() { this.signalingState = 'stable'; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createAnswer() { return { type: 'answer', sdp: 'ans' }; }
  async setLocalDescription() { this.signalingState = 'stable'; }
  async setRemoteDescription() { offerHandled = true; this.signalingState = 'have-remote-offer'; }
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
  RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'bob', 'Bob');

if (typeof listeners['voice_signal'] !== 'function') {
  process.exit(1);
}

// Early offer arrives while get_ice_servers is still pending!
listeners['voice_signal']({
  fromPeerId: 'alice',
  signal: { type: 'offer', sdp: 'alice_offer' }
});

setTimeout(() => {
  if (!offerHandled) {
    process.exit(2);
  }
  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_EARLY_LISTENER');
  process.exit(0);
}, 50);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_EARLY_LISTENER', stdout)

    def test_16_duplicate_voice_peer_joined_handling_in_node(self):
        """Duplicate voice_peer_joined events do not spam offers, but retry if unanswered >1500ms."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let emittedSignals = [];
let listeners = {};
const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    const data = typeof args[0] === 'object' ? args[0] : {};
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
    if (evt === 'voice_signal') emittedSignals.push(data);
  },
  on: (evt, fn) => { listeners[evt] = fn; }
};

class MockPC {
  constructor() {
    this.signalingState = 'stable';
    this.localDescription = null;
    this.remoteDescription = null;
  }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createOffer() { return { type: 'offer', sdp: 'sdp_offer' }; }
  async setLocalDescription(d) {
    this.localDescription = d;
    if (d.type === 'offer') this.signalingState = 'have-local-offer';
  }
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
  RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');

// First peer joined
listeners['voice_peer_joined']({ peerId: 'bob' });

setTimeout(() => {
  if (emittedSignals.length !== 1) process.exit(1);

  // Rapid duplicate peer joined (50ms later)
  listeners['voice_peer_joined']({ peerId: 'bob' });

  setTimeout(() => {
    // Should NOT have spammed duplicate offer
    if (emittedSignals.length !== 1) process.exit(2);

    // After >1500ms without answer, peer re-announces
    const peerData = ctx.VoiceClient._peers.get('bob');
    peerData.lastOfferTime = Date.now() - 2000;

    listeners['voice_peer_joined']({ peerId: 'bob' });

    setTimeout(() => {
      // Confirmed missed offer: retransmitted
      if (emittedSignals.length !== 2) process.exit(3);
      ctx.VoiceClient.leaveVoice();
      console.log('SUCCESS_DUPLICATE_AND_RETRY');
      process.exit(0);
    }, 20);
  }, 50);
}, 50);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_DUPLICATE_AND_RETRY', stdout)

    def test_17_only_actual_voice_participants_receive_voice_peer_joined(self):
        """voice_peer_joined reaches ONLY existing voice participants, never unjoined room players."""
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)
        c3 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 3}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']

        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        res3 = c3.emit('join_room', {'roomCode': room_code, 'playerName': 'Charlie'}, callback=True)
        p3_id = res3['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c1.get_received()
        c2.get_received()
        c3.get_received()

        # 1. Alice joins voice: neither Bob nor Charlie is in voice yet
        res_v1 = c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        self.assertTrue(res_v1['success'])
        self.assertEqual(res_v1['peers'], [])
        self.assertEqual([e for e in c2.get_received() if e['name'] == 'voice_peer_joined'], [])
        self.assertEqual([e for e in c3.get_received() if e['name'] == 'voice_peer_joined'], [])

        # 2. Bob joins voice: Alice receives voice_peer_joined; Charlie (not in voice) does NOT
        res_v2 = c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)
        self.assertTrue(res_v2['success'])
        self.assertEqual([p['peerId'] for p in res_v2['peers']], [p1_id])

        c1_joined = [e for e in c1.get_received() if e['name'] == 'voice_peer_joined']
        c3_joined = [e for e in c3.get_received() if e['name'] == 'voice_peer_joined']
        self.assertEqual(len(c1_joined), 1)
        self.assertEqual(c1_joined[0]['args'][0]['peerId'], p2_id)
        self.assertEqual(len(c3_joined), 0)

        # 3. Charlie joins voice: both Alice and Bob receive voice_peer_joined; Charlie gets both in peers
        res_v3 = c3.emit('voice_join', {'roomCode': room_code, 'playerId': p3_id}, callback=True)
        self.assertTrue(res_v3['success'])
        self.assertEqual({p['peerId'] for p in res_v3['peers']}, {p1_id, p2_id})

        c1_joined_2 = [e for e in c1.get_received() if e['name'] == 'voice_peer_joined']
        c2_joined_2 = [e for e in c2.get_received() if e['name'] == 'voice_peer_joined']
        self.assertEqual(len(c1_joined_2), 1)
        self.assertEqual(c1_joined_2[0]['args'][0]['peerId'], p3_id)
        self.assertEqual(len(c2_joined_2), 1)
        self.assertEqual(c2_joined_2[0]['args'][0]['peerId'], p3_id)

    def test_18_disconnect_cleanup_with_departure_notified_and_no_duplicates(self):
        """Disconnect emits voice_peer_left even when departure_notified is True, with zero duplicates."""
        # Scenario A: client_connection_lost sets departure_notified=True before socket disconnect
        c1 = self.socketio.test_client(self.app)
        c2 = self.socketio.test_client(self.app)

        res1 = c1.emit('create_room', {'playerName': 'Alice', 'maxPlayers': 2}, callback=True)
        room_code = res1['room_code']
        p1_id = res1['player_id']
        res2 = c2.emit('join_room', {'roomCode': room_code, 'playerName': 'Bob'}, callback=True)
        p2_id = res2['player_id']

        c1.emit('start_game', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c1.emit('voice_join', {'roomCode': room_code, 'playerId': p1_id}, callback=True)
        c2.emit('voice_join', {'roomCode': room_code, 'playerId': p2_id}, callback=True)
        c1.get_received()

        # Simulate connection lost (sets departure_notified=True), then actual socket disconnect
        c2.emit('client_connection_lost', {'roomCode': room_code, 'playerId': p2_id})
        c2.disconnect()

        room = room_manager.get_room(room_code)
        self.assertNotIn(p2_id, getattr(room, 'voice_peers', set()))
        left_events = [e for e in c1.get_received() if e['name'] == 'voice_peer_left']
        self.assertEqual(len(left_events), 1)
        self.assertEqual(left_events[0]['args'][0]['peerId'], p2_id)

        # Scenario B: voice_leave -> leave_room -> disconnect produces only ONE voice_peer_left
        c3 = self.socketio.test_client(self.app)
        c4 = self.socketio.test_client(self.app)
        res3 = c3.emit('create_room', {'playerName': 'Carol', 'maxPlayers': 2}, callback=True)
        room_code2 = res3['room_code']
        p3_id = res3['player_id']
        res4 = c4.emit('join_room', {'roomCode': room_code2, 'playerName': 'Dave'}, callback=True)
        p4_id = res4['player_id']

        c3.emit('start_game', {'roomCode': room_code2, 'playerId': p3_id}, callback=True)
        c3.emit('voice_join', {'roomCode': room_code2, 'playerId': p3_id}, callback=True)
        c4.emit('voice_join', {'roomCode': room_code2, 'playerId': p4_id}, callback=True)
        c3.get_received()

        c4.emit('voice_leave', {'roomCode': room_code2, 'playerId': p4_id}, callback=True)
        c4.emit('leave_room', {'roomCode': room_code2, 'playerId': p4_id}, callback=True)
        c4.disconnect()

        left_events_b = [e for e in c3.get_received() if e['name'] == 'voice_peer_left']
        self.assertEqual(len(left_events_b), 1)
        self.assertEqual(left_events_b[0]['args'][0]['peerId'], p4_id)

    def test_19_simultaneous_voice_join_calls(self):
        """Concurrent voice_join calls under room.play_lock safely register all participants without races."""
        clients = [self.socketio.test_client(self.app) for _ in range(4)]
        res0 = clients[0].emit('create_room', {'playerName': 'P0', 'maxPlayers': 4}, callback=True)
        room_code = res0['room_code']
        player_ids = [res0['player_id']]

        for idx in range(1, 4):
            r = clients[idx].emit('join_room', {'roomCode': room_code, 'playerName': f'P{idx}'}, callback=True)
            player_ids.append(r['player_id'])

        clients[0].emit('start_game', {'roomCode': room_code, 'playerId': player_ids[0]}, callback=True)
        for c in clients:
            c.get_received()

        barrier = threading.Barrier(4)
        results = [None] * 4
        errors = []

        def worker(i):
            try:
                barrier.wait(timeout=5)
                results[i] = clients[i].emit('voice_join', {'roomCode': room_code, 'playerId': player_ids[i]}, callback=True)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])
        for r in results:
            self.assertIsNotNone(r)
            self.assertTrue(r['success'])

        room = room_manager.get_room(room_code)
        self.assertEqual(getattr(room, 'voice_peers', set()), set(player_ids))

        # Every participant must discover every other participant via either active_peers or voice_peer_joined
        for i in range(4):
            seen_from_res = {p['peerId'] for p in results[i]['peers']}
            seen_from_evt = {
                e['args'][0]['peerId']
                for e in clients[i].get_received()
                if e['name'] == 'voice_peer_joined'
            }
            expected_others = set(player_ids) - {player_ids[i]}
            self.assertEqual(seen_from_res | seen_from_evt, expected_others)

    def test_20_no_phantom_peer_connection_after_leave_voice_in_node(self):
        """After leaveVoice(), incoming voice_peer_joined and voice_signal events are ignored."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let listeners = {};
let emittedSignals = [];
const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
    if (evt === 'voice_signal') emittedSignals.push(args[0]);
  },
  on: (evt, fn) => { listeners[evt] = fn; }
};

let pcCreatedCount = 0;
class MockPC {
  constructor() { pcCreatedCount++; this.signalingState = 'stable'; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createOffer() { return { type: 'offer', sdp: 'o' }; }
  async createAnswer() { return { type: 'answer', sdp: 'a' }; }
  async setLocalDescription() {}
  async setRemoteDescription() {}
  close() {}
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
  RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
ctx.VoiceClient.leaveVoice();

// Stray events arriving AFTER leaveVoice() must NOT create phantom peer connections
listeners['voice_peer_joined']({ peerId: 'bob', name: 'Bob' });
listeners['voice_signal']({ fromPeerId: 'charlie', signal: { type: 'offer', sdp: 'stray' } });

setTimeout(() => {
  if (pcCreatedCount !== 0 || ctx.VoiceClient._peers.size !== 0 || emittedSignals.length !== 0) {
    process.exit(1);
  }
  console.log('SUCCESS_NO_PHANTOM_PC');
  process.exit(0);
}, 30);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_NO_PHANTOM_PC', stdout)

    def test_21_duplicate_offer_in_have_remote_offer_and_rollback_guard_in_node(self):
        """Ignore duplicate offers in have-remote-offer & concurrent _handleOffer; rollback only in have-local-offer."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let rollbackCount = 0;
let setRemoteCount = 0;
let answersEmitted = 0;

const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
    if (evt === 'voice_signal' && args[0] && args[0].signal && args[0].signal.type === 'answer') {
      answersEmitted++;
    }
  },
  on: () => {}
};

class MockPC {
  constructor() { this.signalingState = 'stable'; this.remoteDescription = null; }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  async createAnswer() { return { type: 'answer', sdp: 'ans' }; }
  async setLocalDescription(d) {
    if (d.type === 'rollback') {
      if (this.signalingState !== 'have-local-offer') {
        throw new Error('InvalidStateError: rollback outside have-local-offer');
      }
      rollbackCount++;
      this.signalingState = 'stable';
    } else if (d.type === 'answer') {
      this.signalingState = 'stable';
    }
  }
  async setRemoteDescription(d) {
    setRemoteCount++;
    await new Promise(r => setTimeout(r, 25));
    this.remoteDescription = d;
    this.signalingState = 'have-remote-offer';
  }
  close() {}
}

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, createElement: () => ({ style: {} }), body: { appendChild: () => {} }, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
  RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

(async () => {
  // 'bob' is polite relative to 'alice' ('alice' < 'bob')
  ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'bob', 'Bob');
  const pc = ctx.VoiceClient._createPeerConnection('alice');

  // Case 1: Already in 'have-remote-offer' -> duplicate offer ignored without rollback
  pc.signalingState = 'have-remote-offer';
  await ctx.VoiceClient._handleOffer('alice', { type: 'offer', sdp: 'dup_offer' });
  if (rollbackCount !== 0 || setRemoteCount !== 0 || answersEmitted !== 0) {
    process.exit(1);
  }

  // Case 2: Two concurrent _handleOffer calls on 'stable' -> second is ignored
  pc.signalingState = 'stable';
  const p1 = ctx.VoiceClient._handleOffer('alice', { type: 'offer', sdp: 'offer_1' });
  const p2 = ctx.VoiceClient._handleOffer('alice', { type: 'offer', sdp: 'offer_2' });
  await Promise.all([p1, p2]);
  if (setRemoteCount !== 1 || answersEmitted !== 1 || rollbackCount !== 0) {
    process.exit(2);
  }

  // Case 3: In 'have-local-offer' on polite peer -> rollback IS executed and answered
  pc.signalingState = 'have-local-offer';
  await ctx.VoiceClient._handleOffer('alice', { type: 'offer', sdp: 'glare_offer' });
  if (rollbackCount !== 1 || setRemoteCount !== 2 || answersEmitted !== 2) {
    process.exit(3);
  }

  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_OFFER_STATE_GUARDS');
  process.exit(0);
})();
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_OFFER_STATE_GUARDS', stdout)

    def test_22_reconnect_cleans_stale_peers_and_mic_state_in_node(self):
        """Calling startVoice() again after reconnect closes stale PCs and stops old mic tracks."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let closedPCs = 0;
let stoppedTracks = 0;
let getUserMediaCalls = 0;

class MockMediaStream {
  constructor(tracks) { this.tracks = tracks; }
  getTracks() { return this.tracks; }
  getAudioTracks() { return this.tracks; }
}

class MockPC {
  constructor() { this.signalingState = 'stable'; this.connectionState = 'connected'; }
  addTransceiver() { return { sender: { track: null, replaceTrack: async () => {} } }; }
  getSenders() { return []; }
  close() { closedPCs++; this.connectionState = 'closed'; this.signalingState = 'closed'; }
}

const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
  },
  on: () => {}
};

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class { resume() { return Promise.resolve(); } close() {} } },
  document: { getElementById: () => null, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  MediaStream: MockMediaStream,
  navigator: {
    mediaDevices: {
      getUserMedia: async () => {
        getUserMediaCalls++;
        return new MockMediaStream([{ kind: 'audio', enabled: true, stop: () => { stoppedTracks++; } }]);
      }
    }
  },
  showToast: () => {},
  TableUI: { setPlayerSpeaking: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

(async () => {
  ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
  ctx.VoiceClient._createPeerConnection('bob');
  await ctx.VoiceClient.toggleMic();

  if (ctx.VoiceClient._peers.size !== 1 || getUserMediaCalls !== 1) {
    process.exit(1);
  }

  // Simulate in-page reconnect invoking startVoice() again without prior leaveVoice()
  ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');

  if (closedPCs !== 1 || stoppedTracks !== 1 || ctx.VoiceClient._peers.size !== 0) {
    process.exit(2);
  }

  // Toggling mic after reconnect must cleanly request a fresh track (not reuse stopped track)
  await ctx.VoiceClient.toggleMic();
  if (getUserMediaCalls !== 2) {
    process.exit(3);
  }

  ctx.VoiceClient.leaveVoice();
  console.log('SUCCESS_RECONNECT_CLEANUP');
  process.exit(0);
})();
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_RECONNECT_CLEANUP', stdout)

    def test_23_unified_plan_bidirectional_transceivers_and_mic_toggle_in_node(self):
        """Strict RFC 8829 Unified Plan: offerer & answerer negotiate sendrecv on mid=0, attach mics & toggle without renegotiation."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let emittedOffers = [];
let emittedAnswers = [];

function createUnifiedPlanClient(id, name) {
  let listeners = {};
  const audioElements = [];
  let micCounter = 0;

  class MockMediaStream {
    constructor(tracks) { this.tracks = tracks || []; }
    getTracks() { return this.tracks; }
    getAudioTracks() { return this.tracks; }
  }

  class MockUnifiedPlanPC {
    constructor() {
      this.signalingState = 'stable';
      this.connectionState = 'new';
      this.localDescription = null;
      this.remoteDescription = null;
      this.transceivers = [];
      this.onicecandidate = null;
      this.ontrack = null;
      this.onconnectionstatechange = null;
    }
    _makeTransceiver(kind, direction, createdByAddTrack, initialTrack) {
      const sender = {
        track: initialTrack || null,
        replaceTrack: async (t) => { sender.track = t; }
      };
      const receiver = { track: { kind, id: 'remote_' + kind + '_' + id } };
      const t = { mid: null, direction, currentDirection: null, createdByAddTrack, sender, receiver };
      this.transceivers.push(t);
      return t;
    }
    addTransceiver(kind, opts) {
      return this._makeTransceiver(kind, (opts && opts.direction) || 'sendrecv', false, null);
    }
    addTrack(track) {
      return this._makeTransceiver(track.kind, 'sendrecv', true, track).sender;
    }
    getTransceivers() { return this.transceivers; }
    getSenders() { return this.transceivers.map(t => t.sender); }
    async createOffer() {
      // Assign mid="0" to first audio transceiver
      const t = this.transceivers[0];
      if (!t) throw new Error('No transceiver for offer');
      if (t.mid === null) t.mid = '0';
      return {
        type: 'offer',
        sdp: `v=0\\r\\nm=audio 9 UDP/TLS/RTP/SAVPF 111\\r\\na=mid:${t.mid}\\r\\na=${t.direction}\\r\\n`,
        _mlines: [{ mid: t.mid, kind: 'audio', direction: t.direction }]
      };
    }
    async setLocalDescription(desc) {
      this.localDescription = desc;
      if (desc.type === 'offer') {
        this.signalingState = 'have-local-offer';
      } else if (desc.type === 'answer') {
        this.signalingState = 'stable';
        // Compute currentDirection for answerer
        const t = this.transceivers.find(x => x.mid === '0');
        if (t && desc._mlines && desc._mlines[0]) {
          t.currentDirection = desc._mlines[0].direction;
        }
      }
    }
    async setRemoteDescription(desc) {
      this.remoteDescription = desc;
      if (desc.type === 'offer') {
        this.signalingState = 'have-remote-offer';
        // RFC 8829 Section 5.10: ONLY associate unassociated transceivers created via addTrack (NOT addTransceiver!)
        for (const m of (desc._mlines || [])) {
          let t = this.transceivers.find(x => x.mid === m.mid);
          if (!t) {
            t = this.transceivers.find(x => x.mid === null && x.createdByAddTrack === true && x.receiver.track.kind === m.kind);
          }
          if (!t) {
            // Chromium creates a new recvonly transceiver bound to the offer's mid
            t = this._makeTransceiver(m.kind, 'recvonly', false, null);
          }
          t.mid = m.mid;
          if (this.ontrack) {
            this.ontrack({ track: t.receiver.track, streams: [] });
          }
        }
      } else if (desc.type === 'answer') {
        this.signalingState = 'stable';
        this.connectionState = 'connected';
        for (const m of (desc._mlines || [])) {
          const t = this.transceivers.find(x => x.mid === m.mid);
          if (t) {
            // If answer is sendrecv and offer is sendrecv -> negotiated sendrecv; if answer is recvonly -> sendonly
            t.currentDirection = (m.direction === 'sendrecv' && t.direction === 'sendrecv') ? 'sendrecv' : 'sendonly';
            if (m.direction === 'sendrecv' && this.ontrack) {
              this.ontrack({ track: t.receiver.track, streams: [] });
            }
          }
        }
      }
    }
    async createAnswer() {
      const t = this.transceivers.find(x => x.mid === '0');
      if (!t) throw new Error('No negotiated transceiver for answer');
      return {
        type: 'answer',
        sdp: `v=0\\r\\nm=audio 9 UDP/TLS/RTP/SAVPF 111\\r\\na=mid:${t.mid}\\r\\na=${t.direction}\\r\\n`,
        _mlines: [{ mid: t.mid, kind: 'audio', direction: t.direction }]
      };
    }
    async addIceCandidate() {}
    close() { this.signalingState = 'closed'; this.connectionState = 'closed'; }
  }

  const fakeDoc = {
    getElementById: (elId) => audioElements.find(a => a.id === elId) || null,
    createElement: () => {
      const el = { id: '', style: {}, srcObject: null, muted: false, play: async () => {} };
      audioElements.push(el);
      return el;
    },
    body: { appendChild: () => {} },
    addEventListener: () => {}
  };

  const socket = {
    emit: (evt, data, cb) => handleServer(id, evt, data, cb),
    on: (evt, fn) => { listeners[evt] = fn; },
    _deliver: (evt, data) => { if (listeners[evt]) listeners[evt](data); }
  };

  const ctx = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    window: { AudioContext: class { resume() { return Promise.resolve(); } close() {} } },
    document: fakeDoc,
    RTCPeerConnection: MockUnifiedPlanPC,
    RTCSessionDescription: class { constructor(x){ Object.assign(this, x); } },
    RTCIceCandidate: class { constructor(x){ Object.assign(this, x); } },
    MediaStream: MockMediaStream,
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          micCounter++;
          return new MockMediaStream([{ kind: 'audio', id: 'mic_' + id + '_' + micCounter, enabled: true, stop: () => {} }]);
        }
      }
    },
    showToast: () => {},
    TableUI: { setPlayerSpeaking: () => {} },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
  };
  vm.createContext(ctx);
  vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

  return { id, name, socket, client: ctx.VoiceClient, audioElements };
}

const clients = {};
const joinedVoice = new Set();

function handleServer(fromId, evt, data, cb) {
  if (evt === 'get_ice_servers') {
    const fn = typeof data === 'function' ? data : cb;
    setTimeout(() => fn && fn({ success: true, iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] }), 5);
  } else if (evt === 'voice_join') {
    const existing = Array.from(joinedVoice).filter(k => k !== fromId);
    const activePeers = existing.map(k => ({ peerId: k, name: clients[k].name }));
    joinedVoice.add(fromId);
    existing.forEach(k => clients[k].socket._deliver('voice_peer_joined', { peerId: fromId, name: clients[fromId].name }));
    if (cb) cb({ success: true, peers: activePeers });
  } else if (evt === 'voice_signal') {
    if (data.signal && data.signal.type === 'offer') emittedOffers.push({ from: fromId, signal: data.signal });
    if (data.signal && data.signal.type === 'answer') emittedAnswers.push({ from: fromId, signal: data.signal });
    const target = clients[data.targetPeerId];
    if (target) target.socket._deliver('voice_signal', { fromPeerId: fromId, signal: data.signal });
  }
}

const offerer = createUnifiedPlanClient('usr_aaa', 'Laptop');
const answerer = createUnifiedPlanClient('usr_bbb', 'Android');
clients['usr_aaa'] = offerer;
clients['usr_bbb'] = answerer;

// Start both peers (answerer joins first, then offerer)
answerer.client.startVoice(answerer.socket, 'ROOM1', 'usr_bbb', 'Android');
setTimeout(() => {
  offerer.client.startVoice(offerer.socket, 'ROOM1', 'usr_aaa', 'Laptop');
}, 15);

setTimeout(async () => {
  const offererPeer = offerer.client._peers.get('usr_bbb');
  const answererPeer = answerer.client._peers.get('usr_aaa');

  if (!offererPeer || !answererPeer) process.exit(1);

  const offTransceivers = offererPeer.pc.getTransceivers();
  const ansTransceivers = answererPeer.pc.getTransceivers();

  // 1. Exactly ONE negotiated transceiver (mid="0") on EACH peer; ZERO orphaned mid=null transceivers
  if (offTransceivers.length !== 1 || offTransceivers[0].mid !== '0') process.exit(2);
  if (ansTransceivers.length !== 1 || ansTransceivers[0].mid !== '0') process.exit(3);

  // 2. Both negotiated directions permit bidirectional sendrecv audio
  if (offTransceivers[0].currentDirection !== 'sendrecv') process.exit(4);
  if (ansTransceivers[0].currentDirection !== 'sendrecv') process.exit(5);
  if (emittedAnswers.length !== 1 || !emittedAnswers[0].signal.sdp.includes('a=sendrecv')) process.exit(6);

  // 3. Both peers received remote audio tracks and attached streams
  if (!offererPeer.stream || !answererPeer.stream) process.exit(7);

  // 4. Both peers enable microphone: tracks MUST attach to the negotiated mid="0" sender with ZERO renegotiation
  const offersBeforeMic = emittedOffers.length;
  await offerer.client.toggleMic();
  await answerer.client.toggleMic();

  if (!offTransceivers[0].sender.track || offTransceivers[0].sender.track.id !== 'mic_usr_aaa_1') process.exit(8);
  if (!ansTransceivers[0].sender.track || ansTransceivers[0].sender.track.id !== 'mic_usr_bbb_1') process.exit(9);

  // 5. Mute and unmute repeatedly on BOTH peers without triggering renegotiation offers
  await offerer.client.toggleMic(); // mute
  await answerer.client.toggleMic(); // mute
  if (offTransceivers[0].sender.track !== null || ansTransceivers[0].sender.track !== null) process.exit(10);

  await offerer.client.toggleMic(); // unmute
  await answerer.client.toggleMic(); // unmute
  if (!offTransceivers[0].sender.track || !ansTransceivers[0].sender.track) process.exit(11);
  if (emittedOffers.length !== offersBeforeMic) process.exit(12);

  offerer.client.leaveVoice();
  answerer.client.leaveVoice();
  console.log('SUCCESS_UNIFIED_PLAN_BIDIRECTIONAL');
  process.exit(0);
}, 150);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_UNIFIED_PLAN_BIDIRECTIONAL', stdout)

    def test_24_transient_disconnected_recovery_vs_failed_cleanup_in_node(self):
        """Transient 'disconnected' state preserves peer for recovery; 'failed' and 'closed' clean up."""
        script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync('frontend/js/game/voice-client.js', 'utf8');

let closeCalls = 0;
class MockPC {
  constructor() {
    this.signalingState = 'stable';
    this.connectionState = 'connected';
    this.onconnectionstatechange = null;
  }
  addTransceiver() { return { sender: { replaceTrack: async () => {} } }; }
  close() { closeCalls++; this.connectionState = 'closed'; this.signalingState = 'closed'; }
}

const fakeSocket = {
  emit: (evt, ...args) => {
    const cb = typeof args[args.length - 1] === 'function' ? args[args.length - 1] : null;
    if (evt === 'get_ice_servers' && cb) cb({ success: true, iceServers: [] });
    if (evt === 'voice_join' && cb) cb({ success: true, peers: [] });
  },
  on: () => {}
};

const ctx = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: { AudioContext: class {} },
  document: { getElementById: () => null, addEventListener: () => {} },
  RTCPeerConnection: MockPC,
  setTimeout, clearTimeout, setInterval, clearInterval, Date, Promise, Error
};
vm.createContext(ctx);
vm.runInContext(code + '\\nglobalThis.VoiceClient = VoiceClient;', ctx);

ctx.VoiceClient.startVoice(fakeSocket, 'ROOM1', 'alice', 'Alice');
const pc1 = ctx.VoiceClient._createPeerConnection('bob');

// 1. Transient 'disconnected' must NOT remove or close peer
pc1.connectionState = 'disconnected';
pc1.onconnectionstatechange();
if (!ctx.VoiceClient._peers.has('bob') || closeCalls !== 0) {
  process.exit(1);
}

// 2. Recovery back to 'connected' keeps peer intact
pc1.connectionState = 'connected';
pc1.onconnectionstatechange();
if (!ctx.VoiceClient._peers.has('bob') || closeCalls !== 0) {
  process.exit(2);
}

// 3. Terminal 'failed' state removes and closes peer
pc1.connectionState = 'failed';
pc1.onconnectionstatechange();
if (ctx.VoiceClient._peers.has('bob') || closeCalls !== 1) {
  process.exit(3);
}

// 4. Terminal 'closed' state also cleans up peer
const pc2 = ctx.VoiceClient._createPeerConnection('charlie');
pc2.connectionState = 'closed';
pc2.onconnectionstatechange();
if (ctx.VoiceClient._peers.has('charlie') || closeCalls !== 2) {
  process.exit(4);
}

ctx.VoiceClient.leaveVoice();
console.log('SUCCESS_DISCONNECTED_RECOVERY');
process.exit(0);
"""
        stdout = self._run_node_script(script)
        self.assertIn('SUCCESS_DISCONNECTED_RECOVERY', stdout)


if __name__ == '__main__':
    unittest.main()
