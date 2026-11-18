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
  let _isVoiceActive    = false;
  let _isMicActive      = false;
  let _isMicConnecting  = false;
  let _isMicDenied      = false;
  let _isDeafened       = false;

  // peerId -> { pc, sender, audioEl, analyser, stream, candidateQueue, makingOffer, handlingOffer, lastOfferTime, offerSentCount }
  const _peers = new Map();
  const _pendingPlayAudioElements = new Set();

  /**
   * Deterministic offerer role:
   * The peer with the lexicographically smaller ID initiates the SDP offer.
   * Asymmetric and deterministic across all participants.
   */
  function _isOfferer(peerId) {
    if (!_localPlayerId || !peerId) return false;
    return String(_localPlayerId) < String(peerId);
  }

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

  function _cleanupVoiceResources() {
    if (_speakingCheckInterval) {
      clearInterval(_speakingCheckInterval);
      _speakingCheckInterval = null;
    }

    _pendingPlayAudioElements.clear();

    if (_localStream && typeof _localStream.getTracks === 'function') {
      _localStream.getTracks().forEach(t => {
        if (t && typeof t.stop === 'function') t.stop();
      });
    } else if (_localTrack && typeof _localTrack.stop === 'function') {
      _localTrack.stop();
    }
    _localStream   = null;
    _localTrack    = null;
    _localAnalyser = null;

    _peers.forEach((peerData, peerId) => {
      try {
        peerData.pc.close();
      } catch (e) {}
      if (peerData.audioEl) {
        peerData.audioEl.srcObject = null;
        if (typeof peerData.audioEl.remove === 'function') {
          peerData.audioEl.remove();
        }
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

    _isMicActive     = false;
    _isMicConnecting = false;
    _isMicDenied     = false;
    _isDeafened      = false;
  }

  /**
   * Initialize voice chat for an active match.
   */
  function startVoice(socket, roomCode, playerId, playerName) {
    if (!socket || !roomCode || !playerId) return;

    // Clean up any stale peer connections and microphone state before (re)initializing
    _cleanupVoiceResources();

    _cacheDOM();
    _socket          = socket;
    _roomCode        = roomCode;
    _localPlayerId   = playerId;
    _localPlayerName = playerName;
    _isVoiceActive   = true;

    // Show voice controls in active match HUD
    if (_containerEl) {
      _containerEl.classList.remove('hidden');
    }
    _updateMicUI();
    _updateSpeakerUI();

    _bindControlEvents();

    // Register voice signaling listeners immediately so no incoming offer or candidate is dropped
    _registerSignalingListeners();

    // Fetch authoritative ICE server configuration from server
    _socket.emit('get_ice_servers', (res) => {
      if (!_isVoiceActive) return;
      if (res && res.success && Array.isArray(res.iceServers) && res.iceServers.length > 0) {
        _iceServers = res.iceServers;
      }
      _joinVoiceSession();
    });

    _startSpeakingCheckLoop();
  }

  function _attemptAudioPlayback(audio, peerId) {
    if (!audio) return;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => {
          _pendingPlayAudioElements.delete(audio);
        })
        .catch((err) => {
          console.warn(`[VoiceClient] Autoplay blocked for peer ${peerId}:`, err.message);
          _pendingPlayAudioElements.add(audio);
        });
    }
  }

  function unlockAudioPlayback() {
    _getAudioContext();

    if (_pendingPlayAudioElements.size > 0) {
      _pendingPlayAudioElements.forEach((audio) => {
        if (audio && audio.srcObject) {
          audio.play()
            .then(() => {
              _pendingPlayAudioElements.delete(audio);
              console.log('[VoiceClient] Autoplay recovered on user interaction');
            })
            .catch(() => {});
        } else {
          _pendingPlayAudioElements.delete(audio);
        }
      });
    }
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

    // Android / iOS user gesture unlock across multiple touch/click interactions
    if (typeof document !== 'undefined' && document.addEventListener && !document._voiceGestureBound) {
      document._voiceGestureBound = true;
      const userGestures = ['click', 'touchstart', 'pointerdown'];
      userGestures.forEach((evtName) => {
        document.addEventListener(evtName, unlockAudioPlayback, { passive: true });
      });
    }
  }

  function _joinVoiceSession() {
    if (!_isVoiceActive || !_socket) return;
    _socket.emit('voice_join', {
      roomCode: _roomCode,
      playerId: _localPlayerId,
    }, (res) => {
      if (!_isVoiceActive) return;
      if (!res || !res.success) {
        console.log('[VoiceClient] voice_join notice:', res ? res.message : 'failed');
        return;
      }
      // Connect to existing peers in room deterministically
      if (Array.isArray(res.peers)) {
        res.peers.forEach(peer => {
          if (peer.peerId && peer.peerId !== _localPlayerId) {
            if (_isOfferer(peer.peerId)) {
              _initiatePeerConnection(peer.peerId);
            } else {
              _createPeerConnection(peer.peerId);
            }
          }
        });
      }
    });
  }

  function _registerSignalingListeners() {
    if (!_socket || _socket._voiceListenersBound) return;
    _socket._voiceListenersBound = true;

    _socket.on('voice_peer_joined', (data) => {
      if (!_isVoiceActive) return;
      if (data && data.peerId && data.peerId !== _localPlayerId) {
        if (_isOfferer(data.peerId)) {
          _initiatePeerConnection(data.peerId);
        } else {
          _createPeerConnection(data.peerId);
        }
      }
    });

    _socket.on('voice_signal', async (data) => {
      if (!_isVoiceActive) return;
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
      if (!_isVoiceActive) return;
      if (data && data.peerId) {
        _removePeer(data.peerId);
      }
    });
  }

  function _ensureOffererAudioTransceiver(peerData) {
    if (!peerData || !peerData.pc) return null;
    const pc = peerData.pc;

    if (typeof pc.getTransceivers === 'function') {
      const existing = (pc.getTransceivers() || []).find(
        t => t && (
          (t.receiver && t.receiver.track && t.receiver.track.kind === 'audio') ||
          (t.sender && t.sender.track && t.sender.track.kind === 'audio') ||
          t === peerData.transceiver
        )
      );
      if (existing) {
        existing.direction = 'sendrecv';
        peerData.transceiver = existing;
        peerData.sender = existing.sender;
        if (_isMicActive && _localTrack && peerData.sender && typeof peerData.sender.replaceTrack === 'function') {
          peerData.sender.replaceTrack(_localTrack).catch(() => {});
        }
        return existing;
      }
    }

    if (peerData.sender) {
      return peerData.transceiver || null;
    }

    try {
      const transceiver = pc.addTransceiver('audio', {
        direction: 'sendrecv',
        streams: (_isMicActive && _localStream) ? [_localStream] : [],
      });
      peerData.transceiver = transceiver;
      peerData.sender = transceiver.sender;
      if (_isMicActive && _localTrack && peerData.sender && typeof peerData.sender.replaceTrack === 'function') {
        peerData.sender.replaceTrack(_localTrack).catch(() => {});
      }
      return transceiver;
    } catch (e) {
      console.warn('[VoiceClient] addTransceiver fallback:', e);
      if (_isMicActive && _localStream && _localTrack && pc.addTrack) {
        try {
          peerData.sender = pc.addTrack(_localTrack, _localStream);
        } catch (_) {}
      }
      return null;
    }
  }

  function _bindAnswererAudioTransceiver(peerData) {
    if (!peerData || !peerData.pc) return null;
    const pc = peerData.pc;

    let transceiver = null;
    if (typeof pc.getTransceivers === 'function') {
      const transceivers = pc.getTransceivers() || [];
      // Bind strictly to the transceiver associated with the incoming offer's audio m-line (mid !== null)
      transceiver = transceivers.find(
        t => t && t.mid !== null && t.mid !== undefined &&
             t.receiver && t.receiver.track && t.receiver.track.kind === 'audio'
      ) || transceivers.find(
        t => t && t.receiver && t.receiver.track && t.receiver.track.kind === 'audio'
      ) || transceivers.find(
        t => t && t.mid !== null && t.mid !== undefined
      ) || transceivers[0] || null;
    }

    if (transceiver) {
      // Ensure negotiated answer SDP permits the answerer to both send and receive audio
      transceiver.direction = 'sendrecv';
      peerData.transceiver = transceiver;
      peerData.sender = transceiver.sender;
      if (_isMicActive && _localTrack && transceiver.sender && typeof transceiver.sender.replaceTrack === 'function') {
        transceiver.sender.replaceTrack(_localTrack).catch((err) => {
          console.warn('[VoiceClient] Answerer replaceTrack error:', err);
        });
      }
      return transceiver;
    }

    if (!peerData.sender && typeof pc.getSenders === 'function') {
      const senders = pc.getSenders() || [];
      peerData.sender = senders.find(s => s && (s.track === null || (s.track && s.track.kind === 'audio'))) || null;
    }
    return null;
  }

  function _getAudioSender(peerData) {
    if (!peerData || !peerData.pc) return null;
    const pc = peerData.pc;

    if (typeof pc.getTransceivers === 'function') {
      const transceivers = pc.getTransceivers() || [];
      // Always prefer a negotiated audio transceiver (mid !== null) over any unassociated transceiver
      const negotiated = transceivers.find(
        t => t && t.mid !== null && t.mid !== undefined && (
          (t.receiver && t.receiver.track && t.receiver.track.kind === 'audio') ||
          (t.sender && t.sender.track && t.sender.track.kind === 'audio') ||
          t === peerData.transceiver
        )
      );
      if (negotiated && negotiated.sender) {
        peerData.transceiver = negotiated;
        peerData.sender = negotiated.sender;
        return negotiated.sender;
      }
    }

    if (peerData.sender) {
      return peerData.sender;
    }

    if (typeof pc.getSenders === 'function') {
      const senders = pc.getSenders() || [];
      const found = senders.find(s => s && (s.track === null || (s.track && s.track.kind === 'audio')));
      if (found) {
        peerData.sender = found;
        return found;
      }
    }
    return null;
  }

  function _createPeerConnection(peerId) {
    if (_peers.has(peerId)) {
      const existing = _peers.get(peerId);
      if (existing.pc && existing.pc.connectionState !== 'closed' && existing.pc.signalingState !== 'closed') {
        return existing.pc;
      }
      _removePeer(peerId);
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
      transceiver: null,
      sender: null,
      audioEl: null,
      analyser: null,
      stream: null,
      candidateQueue: [],
      makingOffer: false,
      handlingOffer: false,
      lastOfferTime: 0,
      offerSentCount: 0,
    };
    _peers.set(peerId, peerData);

    // Pre-allocate sendrecv audio transceiver ONLY for the offerer.
    // The answerer binds to the remote offer's negotiated audio transceiver in _handleOffer()
    // so Unified Plan never leaves an orphaned mid=null transceiver.
    if (_isOfferer(peerId)) {
      _ensureOffererAudioTransceiver(peerData);
    } else if (_isMicActive && _localStream && _localTrack && typeof pc.addTrack === 'function') {
      // If answerer already enabled mic before offer arrives, addTrack() creates a transceiver
      // that Unified Plan associates automatically when setRemoteDescription(offer) runs.
      try {
        peerData.sender = pc.addTrack(_localTrack, _localStream);
      } catch (e) {
        console.warn('[VoiceClient] Answerer pre-offer addTrack error:', e);
      }
    }

    pc.onicecandidate = (event) => {
      if (event.candidate && _isVoiceActive && _socket && _roomCode) {
        _socket.emit('voice_signal', {
          roomCode:     _roomCode,
          playerId:     _localPlayerId,
          targetPeerId: peerId,
          signal:       { candidate: event.candidate },
        });
      }
    };

    pc.ontrack = (event) => {
      if (!event.track) return;
      let remoteStream = null;
      if (event.streams && event.streams.length > 0 && event.streams[0]) {
        remoteStream = event.streams[0];
      } else {
        // Fallback: wrap raw track into a new MediaStream
        remoteStream = new MediaStream([event.track]);
      }
      peerData.stream = remoteStream;
      _attachRemoteAudio(peerId, remoteStream);
    };

    pc.onconnectionstatechange = () => {
      const current = _peers.get(peerId);
      if (!current || current.pc !== pc) return;
      // Allow transient 'disconnected' state to recover; clean up only on terminal states
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        _removePeer(peerId);
      }
    };

    return pc;
  }

  function _attachRemoteAudio(peerId, remoteStream) {
    const peerData = _peers.get(peerId);
    if (!peerData) return;

    let audio = peerData.audioEl;
    if (!audio) {
      audio = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(`voice-audio-${peerId}`)
        : null;
      if (!audio && typeof document !== 'undefined' && document.createElement) {
        audio = document.createElement('audio');
        audio.id = `voice-audio-${peerId}`;
        audio.autoplay = true;
        audio.playsInline = true;
        audio.style.display = 'none';
        if (document.body && document.body.appendChild) {
          document.body.appendChild(audio);
        }
      }
      peerData.audioEl = audio;
    }

    if (audio) {
      audio.muted = _isDeafened;
      if (audio.srcObject !== remoteStream) {
        audio.srcObject = remoteStream;
      }
      _attemptAudioPlayback(audio, peerId);
    }

    _setupRemoteAnalyser(peerId, remoteStream);
  }

  function _setupRemoteAnalyser(peerId, remoteStream) {
    const peerData = _peers.get(peerId);
    if (!peerData) return;
    try {
      const ctx = _getAudioContext();
      if (ctx && remoteStream) {
        const source = ctx.createMediaStreamSource(remoteStream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        peerData.analyser = analyser;
      }
    } catch (e) {
      console.warn('[VoiceClient] Analyser setup error for peer', peerId, e);
    }
  }

  async function _initiatePeerConnection(peerId) {
    if (!_isVoiceActive) return;
    const pc = _createPeerConnection(peerId);
    if (!pc) return;
    const peerData = _peers.get(peerId);

    // If already in have-local-offer, do not blindly recreate or retransmit on duplicate join events
    if (pc.signalingState === 'have-local-offer') {
      const now = Date.now();
      const timeSinceOffer = (peerData && peerData.lastOfferTime) ? (now - peerData.lastOfferTime) : 0;
      // Retry only when signaling flow confirms that previous offer may have been missed (e.g. >= 1500ms elapsed without answer)
      if (timeSinceOffer >= 1500 && peerData && (peerData.offerSentCount || 1) < 3 && pc.localDescription) {
        peerData.lastOfferTime = now;
        peerData.offerSentCount = (peerData.offerSentCount || 1) + 1;
        _socket.emit('voice_signal', {
          roomCode:     _roomCode,
          playerId:     _localPlayerId,
          targetPeerId: peerId,
          signal:       { type: pc.localDescription.type, sdp: pc.localDescription.sdp },
        });
      }
      return;
    }

    if (pc.signalingState !== 'stable') {
      return;
    }

    try {
      if (peerData) peerData.makingOffer = true;
      _ensureOffererAudioTransceiver(peerData);
      const offer = await pc.createOffer();
      if (!_isVoiceActive || pc.signalingState !== 'stable') {
        return;
      }
      await pc.setLocalDescription(offer);

      if (peerData) {
        peerData.lastOfferTime = Date.now();
        peerData.offerSentCount = 1;
      }

      if (_isVoiceActive && _socket && _roomCode) {
        _socket.emit('voice_signal', {
          roomCode:     _roomCode,
          playerId:     _localPlayerId,
          targetPeerId: peerId,
          signal:       offer,
        });
      }
    } catch (err) {
      console.warn('[VoiceClient] createOffer failed for peer', peerId, err);
    } finally {
      if (peerData) peerData.makingOffer = false;
    }
  }

  async function _handleOffer(peerId, offer) {
    if (!_isVoiceActive) return;
    const pc = _createPeerConnection(peerId);
    if (!pc) return;
    const peerData = _peers.get(peerId);
    if (!peerData) return;

    // Prevent concurrent _handleOffer() operations for the same peer
    if (peerData.handlingOffer) {
      return;
    }

    // Safely ignore a duplicate incoming offer while an existing remote offer is being answered
    if (pc.signalingState === 'have-remote-offer') {
      return;
    }

    peerData.handlingOffer = true;
    try {
      // Glare safety: perform rollback ONLY when signalingState is exactly 'have-local-offer'
      if (pc.signalingState === 'have-local-offer') {
        if (!_isOfferer(peerId)) {
          await pc.setLocalDescription({ type: 'rollback' });
        } else {
          return;
        }
      } else if (pc.signalingState !== 'stable') {
        return;
      }

      await pc.setRemoteDescription(new RTCSessionDescription(offer));
      // Bind to the offer-associated audio transceiver (mid !== null) and set direction='sendrecv'
      // BEFORE createAnswer() so the answer SDP permits bidirectional audio.
      _bindAnswererAudioTransceiver(peerData);
      await _drainCandidateQueue(peerData);

      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      if (_isVoiceActive && _socket && _roomCode) {
        _socket.emit('voice_signal', {
          roomCode:     _roomCode,
          playerId:     _localPlayerId,
          targetPeerId: peerId,
          signal:       answer,
        });
      }
    } catch (err) {
      console.warn('[VoiceClient] Error handling offer from', peerId, err);
    } finally {
      peerData.handlingOffer = false;
    }
  }

  async function _handleAnswer(peerId, answer) {
    const peerData = _peers.get(peerId);
    if (peerData && peerData.pc) {
      try {
        if (peerData.pc.signalingState === 'have-local-offer') {
          peerData.offerSentCount = 0;
          peerData.lastOfferTime = 0;
          await peerData.pc.setRemoteDescription(new RTCSessionDescription(answer));
          await _drainCandidateQueue(peerData);
        }
      } catch (err) {
        console.warn('[VoiceClient] Error handling answer from', peerId, err);
      }
    }
  }

  async function _handleCandidate(peerId, candidate) {
    if (!candidate) return;
    let peerData = _peers.get(peerId);
    if (!peerData) {
      _createPeerConnection(peerId);
      peerData = _peers.get(peerId);
    }
    if (!peerData || !peerData.pc) return;

    const pc = peerData.pc;
    if (!pc.remoteDescription || !pc.remoteDescription.type) {
      peerData.candidateQueue.push(candidate);
      return;
    }

    try {
      await pc.addIceCandidate(new RTCIceCandidate(candidate));
    } catch (e) {
      console.warn('[VoiceClient] addIceCandidate error:', peerId, e);
    }
  }

  async function _drainCandidateQueue(peerData) {
    if (!peerData || !peerData.pc || !peerData.candidateQueue || !peerData.candidateQueue.length) return;
    const queue = peerData.candidateQueue.splice(0);
    for (const cand of queue) {
      try {
        await peerData.pc.addIceCandidate(new RTCIceCandidate(cand));
      } catch (err) {
        console.warn('[VoiceClient] Draining candidate error:', err);
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
        if (typeof peerData.audioEl.remove === 'function') {
          peerData.audioEl.remove();
        }
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

    unlockAudioPlayback();

    if (_localStream && _localTrack) {
      // Toggle existing track
      _isMicActive = !_isMicActive;
      _localTrack.enabled = _isMicActive;
      _updateMicUI();

      // Seamless track replacement without renegotiation
      _peers.forEach((peerData) => {
        const sender = _getAudioSender(peerData);
        if (sender && typeof sender.replaceTrack === 'function') {
          sender.replaceTrack(_isMicActive ? _localTrack : null).catch(() => {});
        }
      });

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

      if (!_isVoiceActive) {
        if (stream && typeof stream.getTracks === 'function') {
          stream.getTracks().forEach(t => { if (t && typeof t.stop === 'function') t.stop(); });
        }
        _isMicConnecting = false;
        return;
      }

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

      // Seamlessly replace track on all negotiated peer senders without renegotiation
      _peers.forEach((peerData) => {
        const sender = _getAudioSender(peerData);

        if (sender && typeof sender.replaceTrack === 'function') {
          sender.replaceTrack(_localTrack).catch((err) => {
            console.warn('[VoiceClient] replaceTrack error:', err);
          });
        } else if (peerData.pc && peerData.pc.addTrack) {
          // Fallback if no sender/transceiver existed yet (e.g., answerer before offer arrives)
          try {
            peerData.sender = peerData.pc.addTrack(_localTrack, _localStream);
          } catch (e) {
            console.warn('[VoiceClient] addTrack fallback error:', e);
          }
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

    if (!_isDeafened) {
      unlockAudioPlayback();
    }

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
    const prevSocket   = _socket;
    const prevRoomCode = _roomCode;
    const prevPlayerId = _localPlayerId;

    _isVoiceActive = false;
    _cleanupVoiceResources();

    if (prevSocket && prevRoomCode && prevPlayerId) {
      prevSocket.emit('voice_leave', {
        roomCode: prevRoomCode,
        playerId: prevPlayerId,
      });
    }

    _roomCode = null;

    if (_containerEl) {
      _containerEl.classList.add('hidden');
    }
  }

  return {
    startVoice,
    toggleMic,
    toggleSpeaker,
    leaveVoice,
    unlockAudioPlayback,
    _isOfferer,
    _createPeerConnection,
    _handleOffer,
    _handleAnswer,
    _handleCandidate,
    _drainCandidateQueue,
    _attachRemoteAudio,
    _attemptAudioPlayback,
    _peers,
  };
})();
