/**
 * KAZHUDHAI CLUB — voice-client.js
 * Match-Only WebRTC Voice Chat Client.
 *
 * Features & Architecture:
 * - Match-Only: Available only during active gameplay screen. Never in lobby.
 * - Full-mesh audio over WebRTC RTCPeerConnection (2–7 players).
 * - Signaling over Socket.IO: 'get_ice_servers', 'voice_join', 'voice_signal', 'voice_leave'.
 * - Lazy Microphone Activation: Requests mic permission only when user clicks Mic button.
 * - Listen-Only by default: Can hear other players without granting mic permission.
 * - Speaker Mute / Deafen Control.
 * - Real-time Speaking Indicators: Web Audio API (AnalyserNode) detects volume of local & remote
 *   voices and triggers smooth green pulse animations on avatars.
 * - Android TWA & Mobile Support: Touch-unlocked AudioContext, playsinline audio, error recovery.
 * - Complete disposal on game end / leave.
 */
const VoiceClient = (() => {

  let _socket          = null;
  let _roomCode        = null;
  let _localPlayerId   = null;
  let _localPlayerName = null;
  let _iceServers      = [
    { urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] }
  ];

  let _localStream      = null;
  let _localTrack       = null;
  let _isMicActive      = false;
  let _isMicConnecting  = false;
  let _isMicDenied      = false;
  let _isDeafened       = false;

  // peerId -> { pc, audioEl, analyser, stream }
  const _peers = new Map();

  let _audioContext          = null;
  let _localAnalyser         = null;
  let _speakingCheckInterval = null;
  const SPEAKING_THRESHOLD   = 0.032;

  // DOM elements cached
  let _containerEl  = null;
  let _btnMic       = null;
  let _btnSpeaker   = null;
  let _micIcon      = null;
  let _micLabel     = null;
  let _speakerIcon  = null;
  let _speakerLabel = null;

  function _cacheDOM() {
    _containerEl  = document.getElementById('hud-voice-controls');
    _btnMic       = document.getElementById('btn-voice-mic');
    _btnSpeaker   = document.getElementById('btn-voice-speaker');
    _micIcon      = document.getElementById('voice-mic-icon');
    _micLabel     = document.getElementById('voice-mic-label');
    _speakerIcon  = document.getElementById('voice-speaker-icon');
    _speakerLabel = document.getElementById('voice-speaker-label');
  }

  function _getAudioContext() {
    if (!_audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        _audioContext = new AudioCtx();
      }
    }
    if (_audioContext && _audioContext.state === 'suspended') {
      _audioContext.resume().catch(() => {});
    }
    return _audioContext;
  }

  /**
   * Update visual state of Microphone button:
   * - Muted / Off (normal)
   * - Active / On (green glow)
   * - Connecting / Requesting (yellow pulse)
   * - Denied / Error (red)
   */
  function _updateMicUI() {
    if (!_btnMic) _cacheDOM();
    if (!_btnMic) return;

    _btnMic.classList.remove('active', 'connecting', 'error');

    if (_isMicDenied) {
      _btnMic.classList.add('error');
      if (_micIcon)  _micIcon.textContent  = '⚠️';
      if (_micLabel) _micLabel.textContent = 'Mic Blocked';
      _btnMic.title = 'Microphone access denied';
    } else if (_isMicConnecting) {
      _btnMic.classList.add('connecting');
      if (_micIcon)  _micIcon.textContent  = '⏳';
      if (_micLabel) _micLabel.textContent = 'Connecting…';
      _btnMic.title = 'Requesting microphone permission…';
    } else if (_isMicActive) {
      _btnMic.classList.add('active');
      if (_micIcon)  _micIcon.textContent  = '🎤';
      if (_micLabel) _micLabel.textContent = 'Mic On';
      _btnMic.title = 'Microphone active (click to mute)';
    } else {
      if (_micIcon)  _micIcon.textContent  = '🎤';
      if (_micLabel) _micLabel.textContent = 'Mic Off';
      _btnMic.title = 'Microphone muted (click to unmute)';
    }
  }

  /**
   * Update visual state of Speaker button:
   * - Audio On (normal)
   * - Deafened / Audio Off (red/muted)
   */
  function _updateSpeakerUI() {
    if (!_btnSpeaker) _cacheDOM();
    if (!_btnSpeaker) return;

    if (_isDeafened) {
      _btnSpeaker.classList.add('deafened');
      if (_speakerIcon)  _speakerIcon.textContent  = '🔇';
      if (_speakerLabel) _speakerLabel.textContent = 'Deafened';
      _btnSpeaker.title = 'Audio deafened (click to hear players)';
    } else {
      _btnSpeaker.classList.remove('deafened');
      if (_speakerIcon)  _speakerIcon.textContent  = '🔊';
      if (_speakerLabel) _speakerLabel.textContent = 'Audio On';
      _btnSpeaker.title = 'Audio active (click to deafen)';
    }
  }

  /**
   * Initialize voice chat for an active match.
   */
  function startVoice(socket, roomCode, playerId, playerName) {
    if (!socket || !roomCode || !playerId) return;

    _cacheDOM();
    _socket          = socket;
    _roomCode        = roomCode;
    _localPlayerId   = playerId;
    _localPlayerName = playerName;
    _isMicDenied     = false;
    _isMicConnecting = false;
    _isMicActive     = false;
    _isDeafened      = false;

    // Show voice controls in active match HUD
    if (_containerEl) {
      _containerEl.classList.remove('hidden');
    }
    _updateMicUI();
    _updateSpeakerUI();

    _bindControlEvents();

    // Fetch authoritative ICE server configuration from server
    _socket.emit('get_ice_servers', (res) => {
      if (res && res.success && Array.isArray(res.iceServers) && res.iceServers.length > 0) {
        _iceServers = res.iceServers;
      }
      _joinVoiceSession();
    });

    _startSpeakingCheckLoop();
  }

  function _bindControlEvents() {
    if (_btnMic && !_btnMic._bound) {
      _btnMic._bound = true;
      _btnMic.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMic();
      });
    }

    if (_btnSpeaker && !_btnSpeaker._bound) {
      _btnSpeaker._bound = true;
      _btnSpeaker.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSpeaker();
      });
    }

    // Android / iOS user gesture unlock
    document.addEventListener('click', () => {
      _getAudioContext();
    }, { once: true });
  }

  function _joinVoiceSession() {
    _socket.emit('voice_join', {
      roomCode: _roomCode,
      playerId: _localPlayerId,
    }, (res) => {
      if (!res || !res.success) {
        console.log('[VoiceClient] voice_join notice:', res ? res.message : 'failed');
        return;
      }
      // Connect to existing peers in room
      if (Array.isArray(res.peers)) {
        res.peers.forEach(peer => {
          if (peer.peerId && peer.peerId !== _localPlayerId) {
            _initiatePeerConnection(peer.peerId);
          }
        });
      }
    });

    _registerSignalingListeners();
  }

  function _registerSignalingListeners() {
    if (!_socket || _socket._voiceListenersBound) return;
    _socket._voiceListenersBound = true;

    _socket.on('voice_peer_joined', (data) => {
      if (data && data.peerId && data.peerId !== _localPlayerId) {
        // A new peer joined. The existing peer initiates offer.
        _initiatePeerConnection(data.peerId);
      }
    });

    _socket.on('voice_signal', async (data) => {
      if (!data || !data.fromPeerId || !data.signal) return;
      const { fromPeerId, signal } = data;

      try {
        if (signal.type === 'offer') {
          await _handleOffer(fromPeerId, signal);
        } else if (signal.type === 'answer') {
          await _handleAnswer(fromPeerId, signal);
        } else if (signal.candidate) {
          await _handleCandidate(fromPeerId, signal.candidate);
        }
      } catch (err) {
        console.warn('[VoiceClient] Error processing signal from', fromPeerId, err);
      }
    });

    _socket.on('voice_peer_left', (data) => {
      if (data && data.peerId) {
        _removePeer(data.peerId);
      }
    });
  }

  function _createPeerConnection(peerId) {
    if (_peers.has(peerId)) {
      return _peers.get(peerId).pc;
    }

    let pc;
    try {
      pc = new RTCPeerConnection({ iceServers: _iceServers });
    } catch (e) {
      console.error('[VoiceClient] RTCPeerConnection failed:', e);
      return null;
    }

    const peerData = {
      pc,
      audioEl: null,
      analyser: null,
      stream: null,
    };
    _peers.set(peerId, peerData);

    // If local track is already active, attach it to peer
    if (_localStream && _localTrack) {
      try {
        pc.addTrack(_localTrack, _localStream);
      } catch (e) {
        console.warn('[VoiceClient] addTrack error:', e);
      }
    }

    pc.onicecandidate = (event) => {
      if (event.candidate && _socket && _roomCode) {
        _socket.emit('voice_signal', {
          roomCode:     _roomCode,
          playerId:     _localPlayerId,
          targetPeerId: peerId,
          signal:       { candidate: event.candidate },
        });
      }
    };

    pc.ontrack = (event) => {
      if (!event.streams || !event.streams[0]) return;
      const remoteStream = event.streams[0];
      peerData.stream = remoteStream;

      // Create / attach audio element
      let audio = peerData.audioEl;
      if (!audio) {
        audio = document.createElement('audio');
        audio.autoplay = true;
        audio.playsInline = true;
        audio.muted = _isDeafened;
        audio.style.display = 'none';
        document.body.appendChild(audio);
        peerData.audioEl = audio;
      }
      audio.srcObject = remoteStream;
      audio.play().catch(() => {});

      // Setup Web Audio Analyser for speaking level detection
      try {
        const ctx = _getAudioContext();
        if (ctx) {
          const source = ctx.createMediaStreamSource(remoteStream);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 256;
          source.connect(analyser);
          peerData.analyser = analyser;
        }
      } catch (e) {
        console.warn('[VoiceClient] Analyser setup error for peer', peerId, e);
      }
    };

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        _removePeer(peerId);
      }
    };

    return pc;
  }

  async function _initiatePeerConnection(peerId) {
    const pc = _createPeerConnection(peerId);
    if (!pc) return;

    try {
      const offer = await pc.createOffer({
        offerToReceiveAudio: true,
      });
      await pc.setLocalDescription(offer);

      _socket.emit('voice_signal', {
        roomCode:     _roomCode,
        playerId:     _localPlayerId,
        targetPeerId: peerId,
        signal:       offer,
      });
    } catch (err) {
      console.warn('[VoiceClient] createOffer failed for peer', peerId, err);
    }
  }

  async function _handleOffer(peerId, offer) {
    const pc = _createPeerConnection(peerId);
    if (!pc) return;

    await pc.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    _socket.emit('voice_signal', {
      roomCode:     _roomCode,
      playerId:     _localPlayerId,
      targetPeerId: peerId,
      signal:       answer,
    });
  }

  async function _handleAnswer(peerId, answer) {
    const peerData = _peers.get(peerId);
    if (peerData && peerData.pc) {
      await peerData.pc.setRemoteDescription(new RTCSessionDescription(answer));
    }
  }

  async function _handleCandidate(peerId, candidate) {
    const peerData = _peers.get(peerId);
    if (peerData && peerData.pc) {
      try {
        await peerData.pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (e) {
        console.warn('[VoiceClient] addIceCandidate error:', e);
      }
    }
  }

  function _removePeer(peerId) {
    const peerData = _peers.get(peerId);
    if (peerData) {
      try {
        peerData.pc.close();
      } catch (e) {}
      if (peerData.audioEl) {
        peerData.audioEl.srcObject = null;
        peerData.audioEl.remove();
      }
      _peers.delete(peerId);
    }
    if (typeof TableUI !== 'undefined' && TableUI.setPlayerSpeaking) {
      TableUI.setPlayerSpeaking(peerId, false);
    }
  }

  /**
   * Lazy Microphone Activation:
   * Requests permission ONLY on user click.
   */
  async function toggleMic() {
    if (_isMicConnecting) return;

    _getAudioContext();

    if (_localStream && _localTrack) {
      // Toggle existing track
      _isMicActive = !_isMicActive;
      _localTrack.enabled = _isMicActive;
      _updateMicUI();
      if (!_isMicActive && typeof TableUI !== 'undefined' && TableUI.setPlayerSpeaking) {
        TableUI.setPlayerSpeaking('self', false);
      }
      return;
    }

    // First time requesting microphone
    _isMicConnecting = true;
    _isMicDenied     = false;
    _updateMicUI();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl:  true,
        },
        video: false,
      });

      _localStream = stream;
      _localTrack  = stream.getAudioTracks()[0];
      _isMicActive = true;
      _isMicConnecting = false;
      _updateMicUI();

      // Setup local audio analyser for local speaking indicator
      try {
        const ctx = _getAudioContext();
        if (ctx) {
          const src = ctx.createMediaStreamSource(stream);
          _localAnalyser = ctx.createAnalyser();
          _localAnalyser.fftSize = 256;
          src.connect(_localAnalyser);
        }
      } catch (err) {
        console.warn('[VoiceClient] Local analyser setup error:', err);
      }

      // Attach track to all existing peer connections and renegotiate
      _peers.forEach(async (peerData, peerId) => {
        try {
          peerData.pc.addTrack(_localTrack, _localStream);
          const offer = await peerData.pc.createOffer();
          await peerData.pc.setLocalDescription(offer);
          _socket.emit('voice_signal', {
            roomCode:     _roomCode,
            playerId:     _localPlayerId,
            targetPeerId: peerId,
            signal:       offer,
          });
        } catch (e) {
          console.warn('[VoiceClient] Add track to peer error:', peerId, e);
        }
      });

      if (typeof showToast === 'function') {
        showToast('Microphone enabled', 'success', 2000);
      }

    } catch (err) {
      console.warn('[VoiceClient] Microphone access error:', err);
      _isMicConnecting = false;
      _isMicActive     = false;
      _isMicDenied     = true;
      _updateMicUI();

      if (typeof showToast === 'function') {
        showToast('Microphone access denied. You can still hear other players.', 'info', 4000);
      }
    }
  }

  /**
   * Speaker Mute / Deafen Control:
   * Mute / unmute all incoming audio elements.
   */
  function toggleSpeaker() {
    _isDeafened = !_isDeafened;
    _updateSpeakerUI();

    _peers.forEach(peerData => {
      if (peerData.audioEl) {
        peerData.audioEl.muted = _isDeafened;
      }
    });

    if (typeof showToast === 'function') {
      showToast(_isDeafened ? 'Audio deafened' : 'Audio enabled', 'info', 2000);
    }
  }

  /**
   * Background volume level polling loop (~100ms):
   * Inspects AnalyserNodes and sets avatar speaking animation.
   */
  function _startSpeakingCheckLoop() {
    if (_speakingCheckInterval) clearInterval(_speakingCheckInterval);

    _speakingCheckInterval = setInterval(() => {
      if (typeof TableUI === 'undefined' || !TableUI.setPlayerSpeaking) return;

      // Local speaking detection
      if (_isMicActive && _localTrack && _localTrack.enabled && _localAnalyser) {
        const data = new Uint8Array(_localAnalyser.frequencyBinCount);
        _localAnalyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          sum += data[i] * data[i];
        }
        const rms = Math.sqrt(sum / data.length) / 255;
        TableUI.setPlayerSpeaking('self', rms > SPEAKING_THRESHOLD);
      } else {
        TableUI.setPlayerSpeaking('self', false);
      }

      // Remote peers speaking detection
      _peers.forEach((peerData, peerId) => {
        if (!_isDeafened && peerData.analyser) {
          const data = new Uint8Array(peerData.analyser.frequencyBinCount);
          peerData.analyser.getByteFrequencyData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            sum += data[i] * data[i];
          }
          const rms = Math.sqrt(sum / data.length) / 255;
          TableUI.setPlayerSpeaking(peerId, rms > SPEAKING_THRESHOLD);
        } else {
          TableUI.setPlayerSpeaking(peerId, false);
        }
      });

    }, 110);
  }

  /**
   * Cleanly leave voice chat, release microphone, and disconnect all peers.
   */
  function leaveVoice() {
    if (_speakingCheckInterval) {
      clearInterval(_speakingCheckInterval);
      _speakingCheckInterval = null;
    }

    if (_localStream) {
      _localStream.getTracks().forEach(t => t.stop());
      _localStream = null;
      _localTrack  = null;
    }

    _peers.forEach((peerData, peerId) => {
      try {
        peerData.pc.close();
      } catch (e) {}
      if (peerData.audioEl) {
        peerData.audioEl.srcObject = null;
        peerData.audioEl.remove();
      }
      if (typeof TableUI !== 'undefined' && TableUI.setPlayerSpeaking) {
        TableUI.setPlayerSpeaking(peerId, false);
      }
    });
    _peers.clear();

    if (typeof TableUI !== 'undefined' && TableUI.setPlayerSpeaking) {
      TableUI.setPlayerSpeaking('self', false);
    }

    if (_audioContext) {
      try {
        _audioContext.close();
      } catch (e) {}
      _audioContext = null;
    }

    if (_socket && _roomCode && _localPlayerId) {
      _socket.emit('voice_leave', {
        roomCode: _roomCode,
        playerId: _localPlayerId,
      });
    }

    _isMicActive     = false;
    _isMicConnecting = false;
    _isMicDenied     = false;
    _isDeafened      = false;

    if (_containerEl) {
      _containerEl.classList.add('hidden');
    }
  }

  return {
    startVoice,
    toggleMic,
    toggleSpeaker,
    leaveVoice,
  };
})();
