/**
 * KAZHUDHAI CLUB — online-client.js
 * Complete SocketIO-based real-time multiplayer client for Stage 6.
 * Manages room lifecycle, authoritative synchronization, and card privacy.
 */
const OnlineClient = (() => {

  let _socket          = null;
  let _roomCode        = null;
  let _playerId        = null;
  let _playerName      = null;
  let _isHost          = false;
  let _reconnectToken  = null;
  let _isReconnecting  = false;
  let _initPromise     = null;
  let _isSpectator      = false;
  let _spectatorId      = null;
  let _spectatorName    = null;
  let _spectatorToken   = null;
  let _spectatingIntent = false;
  let _matchId          = null;
  let _postMatchStatus  = null;
  let _restartInFlight  = false;
  let _playAgainInFlight = false;

  function setSpectatingIntent(val) {
    _spectatingIntent = !!val;
  }

  function isConnected() {
    return !!_socket && _socket.connected;
  }

  function getRoomCode() {
    return _roomCode;
  }

  function isHost() {
    return _isHost && !_isSpectator;
  }

  function getPlayerId() {
    return _playerId;
  }

  function isSpectator() {
    return _isSpectator;
  }

  function getSpectatorId() {
    return _spectatorId;
  }

  function getCurrentSenderId() {
    return _isSpectator ? _spectatorId : _playerId;
  }

  function getPostMatchStatus() {
    return _postMatchStatus;
  }

  /**
   * Update the connection status dot and label in modal / UI.
   */
  function _updateConnectionStatusUI(status, text) {
    const dot = document.getElementById('online-server-status-dot');
    const label = document.getElementById('online-server-status-text');
    if (dot) {
      dot.className = `player-status-dot status-${status}`;
    }
    if (label) {
      label.textContent = text || (status === 'connected' ? 'Connected to server' : status === 'reconnecting' ? 'Connecting to server…' : 'Disconnected');
    }
  }

  /**
   * Wait for window.io to be available (e.g. while local script or CDN fallback finishes loading).
   * Resolves immediately if io is already defined.
   * Checks every 50ms and listens to script load events, up to maxWaitMs (default 3000ms).
   * Rejects if timeout is reached.
   */
  function _waitForSocketIO(maxWaitMs = 3000) {
    if (typeof io !== 'undefined') {
      return Promise.resolve(io);
    }

    return new Promise((resolve, reject) => {
      const startTime = Date.now();
      let intervalId = null;

      const cleanup = () => {
        if (intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
        if (typeof window !== 'undefined' && window.removeEventListener) {
          window.removeEventListener('load', onCheck);
        }
      };

      const onCheck = () => {
        if (typeof io !== 'undefined') {
          cleanup();
          resolve(io);
          return;
        }
        if (Date.now() - startTime >= maxWaitMs) {
          cleanup();
          reject(new Error('Socket.IO library failed to load within timeout'));
        }
      };

      intervalId = setInterval(onCheck, 50);

      if (typeof window !== 'undefined' && window.addEventListener) {
        window.addEventListener('load', onCheck);
      }
      if (typeof document !== 'undefined' && document.querySelectorAll) {
        try {
          const scripts = document.querySelectorAll('script');
          scripts.forEach((s) => {
            s.addEventListener('load', onCheck, { once: true });
          });
        } catch (_) {}
      }
    });
  }

  /**
   * Internal constructor for the Socket.IO instance and its event listeners.
   */
  function _setupSocketInstance() {
    if (_socket) return _socket;

    _updateConnectionStatusUI('reconnecting', 'Connecting to server…');

    const serverUrl = (typeof window !== 'undefined' && (window.location.protocol === 'file:' || !window.location.host))
      ? 'http://localhost:5000'
      : undefined;

    // Support production WebSockets with automatic HTTP long-polling fallback
    _socket = io(serverUrl, {
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      transports: ['websocket', 'polling'],
      timeout: 10000,
    });

    _socket.on('connect', () => {
      console.log('[OnlineClient] Connected to server, SID:', _socket.id);
      _updateConnectionStatusUI('connected', '🟢 Connected to server');
      if (typeof TableUI !== 'undefined') {
        TableUI.updatePlayerStatus(_playerId || 'human', 'connected');
      }

      // Restore active spectator or player session safely after reconnect
      if (_isSpectator && _roomCode && _spectatorToken) {
        reconnectSpectator();
      } else if (!_isSpectator && !_spectatingIntent) {
        const activeSession = (typeof Storage !== 'undefined' && Storage.getActiveSession)
          ? Storage.getActiveSession()
          : null;

        if (activeSession && activeSession.token) {
          reconnectSession(activeSession.token, activeSession.roomCode, activeSession.playerId);
        } else if (_reconnectToken && _roomCode) {
          reconnectSession(_reconnectToken, _roomCode, _playerId);
        }
      }
    });

    _socket.on('disconnect', (reason) => {
      console.log('[OnlineClient] Disconnected:', reason);
      _updateConnectionStatusUI('disconnected', '🔴 Disconnected - reconnecting…');
      if (typeof TableUI !== 'undefined') {
        TableUI.updatePlayerStatus(_playerId || 'human', 'disconnected');
      }
    });

    _socket.on('connect_error', (err) => {
      console.warn('[OnlineClient] Connection error:', err.message);
      _updateConnectionStatusUI('disconnected', '🔴 Connection failed - retrying…');
      _isReconnecting = false;
    });

    if (_socket.io) {
      _socket.io.on('reconnect_attempt', () => {
        _updateConnectionStatusUI('reconnecting', '🟡 Reconnecting…');
        if (typeof TableUI !== 'undefined') {
          TableUI.updatePlayerStatus(_playerId || 'human', 'reconnecting');
        }
      });
    }

    // Real-time lobby updates
    _socket.on('room_updated', (roomSummary) => {
      if (!_isSpectator && _playerId && roomSummary && roomSummary.host_id) {
        _isHost = (roomSummary.host_id === _playerId);
      }
      MenuUI.updateWaitingRoom(roomSummary, _isSpectator ? _spectatorId : _playerId, _isSpectator);
      if (App && App.handleSpectatorsUpdated && roomSummary) {
        App.handleSpectatorsUpdated({
          spectators: roomSummary.spectators || [],
          spectator_count: roomSummary.spectator_count || 0,
        });
      }
    });

    // Game started signal (for initial start, Play Again, and Host Restart Game)
    _socket.on('game_started', (data) => {
      _matchId = (data && data.match_id) || null;
      _postMatchStatus = null;
      _restartInFlight = false;
      _playAgainInFlight = false;

      if (typeof MenuUI !== 'undefined' && MenuUI.clearLobbyChat) {
        MenuUI.clearLobbyChat();
      }
      if (typeof App !== 'undefined' && App.clearStageChatsOnMatchStart) {
        App.clearStageChatsOnMatchStart();
      }
      if (typeof App !== 'undefined' && App.prepareForNewMatch) {
        App.prepareForNewMatch(data);
      }
      MenuUI.hideWaitingRoom();
      Screens.go('screen-game');
      if (!_isSpectator && typeof App !== 'undefined' && App.activateGameBackGuard) {
        App.activateGameBackGuard();
      }
      TableUI.init({
        roomCode:   (data && data.room_code) || _roomCode,
        deckCount:  (data && data.deck_count) || 1,
        playerName: _isSpectator ? (_spectatorName || 'Spectator') : _playerName,
      });
      if (typeof TableUI.setSpectatorMode === 'function') {
        TableUI.setSpectatorMode(_isSpectator);
      }
      if (typeof TableUI.setOnlineControlsVisible === 'function') {
        TableUI.setOnlineControlsVisible(true, _isSpectator);
      }
      // Spectators NEVER automatically join voice chat
      if (!_isSpectator && typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
        VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
      }
      const startReason = data && data.reason;
      const startMsg = _isSpectator
        ? (startReason === 'restart' ? 'Host restarted the match. Spectating live…' : 'Match started! Spectating live…')
        : (startReason === 'restart'
            ? 'Match restarted! Dealing fresh cards…'
            : (startReason === 'play_again'
                ? 'New match started! Dealing fresh cards…'
                : 'Game started! Distributing cards…'));
      showToast(startMsg, 'info', 2000);
    });

    // Authoritative personalized game state (players only)
    _socket.on('game_state', (state) => {
      if (_isSpectator) return;
      if (App && App.renderOnlineState) {
        App.renderOnlineState(state);
      }
    });

    // Stage 4: Server-sanitized public state (spectators only)
    _socket.on('spectator_state', (state) => {
      if (App && App.renderSpectatorState) {
        App.renderSpectatorState(state);
      }
    });

    // Stage 4: Live spectator count & display names
    _socket.on('spectators_updated', (summary) => {
      if (App && App.handleSpectatorsUpdated) {
        App.handleSpectatorsUpdated(summary);
      }
    });

    // Stage 2: Live post-match readiness & Play Again eligibility
    _socket.on('post_match_status', (status) => {
      _postMatchStatus = status;
      if (App && App.handlePostMatchStatus) {
        App.handlePostMatchStatus(status);
      }
    });

    // Stage 3: Independent stage chat messages (pre_match, in_match, post_match)
    _socket.on('chat_message', (msg) => {
      if (App && App.handleStageChatMessage) {
        App.handleStageChatMessage(msg);
      }
    });

    // Broadcast when ANY player places a card on the table
    _socket.on('card_played', (action) => {
      if (App && App.handleOnlineCardPlayed) {
        App.handleOnlineCardPlayed(action);
      }
    });

    // Broadcast when a round completes (attack or normal)
    _socket.on('round_resolved', (roundResult) => {
      if (App && App.handleOnlineRoundResolution) {
        App.handleOnlineRoundResolution(roundResult);
      }
    });

    // Game completed (KAZHUDHAI declared)
    _socket.on('game_over', (data) => {
      if (data && data.post_match_status) {
        _postMatchStatus = data.post_match_status;
      }
      if (App && App.showOnlineResults) {
        App.showOnlineResults(data);
      }
    });

    // Instant leave / disconnect notification (~5s display)
    _socket.on('player_departure', (data) => {
      if (App && App.handlePlayerDeparture) {
        App.handlePlayerDeparture(data);
      }
    });

    // Real-time player connection status indicator change
    _socket.on('player_status_change', (data) => {
      if (App && App.handlePlayerStatusChange) {
        App.handlePlayerStatusChange(data);
      }
    });

    // Real-time synchronized game activity history
    _socket.on('activity_logged', (act) => {
      if (App && App.handleActivityLogged) {
        App.handleActivityLogged(act);
      }
    });

    // Real-time multiplayer emoji reactions
    _socket.on('player_reaction', (data) => {
      if (App && App.handlePlayerReaction) {
        App.handlePlayerReaction(data);
      }
    });

    // Real-time lobby chat messages (backward-compatible pre-match broadcast)
    _socket.on('lobby_chat_message', (msg) => {
      if (typeof MenuUI !== 'undefined' && MenuUI.addLobbyChatMessage) {
        MenuUI.addLobbyChatMessage(msg, _isSpectator ? _spectatorId : _playerId);
      }
    });

    return _socket;
  }

  /**
   * Asynchronously ensure socket instance is created, waiting up to maxWaitMs
   * for the Socket.IO library to finish loading if needed.
   * Prevents duplicate initialization attempts.
   */
  function _ensureSocketAsync(maxWaitMs = 3000) {
    if (_socket) {
      return Promise.resolve(_socket);
    }
    if (_initPromise) {
      return _initPromise;
    }

    _initPromise = _waitForSocketIO(maxWaitMs)
      .then(() => {
        const socket = _setupSocketInstance();
        _initPromise = null;
        return socket;
      })
      .catch((err) => {
        _initPromise = null;
        if (typeof showToast === 'function') {
          showToast('Socket.IO library failed to load. Please check your connection.', 'error');
        }
        _updateConnectionStatusUI('disconnected', '🔴 Socket.IO library missing');
        console.error('[OnlineClient] Failed to load Socket.IO library:', err);
        throw err;
      });

    return _initPromise;
  }

  /**
   * Synchronously return existing socket instance, or initialize if io is defined.
   * If io is not yet defined, triggers asynchronous wait and returns null.
   */
  function _ensureSocket() {
    if (_socket) return _socket;
    if (typeof io !== 'undefined') {
      return _setupSocketInstance();
    }
    _ensureSocketAsync(3000).catch(() => {});
    return null;
  }

  // Network state listeners for unexpected connection loss & clean recovery
  let _reportedOffline = false;
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('offline', () => {
      console.warn('[OnlineClient] Network offline detected');
      _reportedOffline = true;
      if (!_isSpectator && _socket && _socket.connected && _roomCode && _playerId) {
        _socket.emit('client_connection_lost', {
          roomCode: _roomCode,
          playerId: _playerId,
        });
      }
      if (!_isSpectator && typeof TableUI !== 'undefined' && _playerId) {
        TableUI.updatePlayerStatus(_playerId, 'reconnecting');
      }
    });

    window.addEventListener('online', () => {
      console.log('[OnlineClient] Network online restored');
      const wasOffline = _reportedOffline;
      _reportedOffline = false;
      if (_socket && !_socket.connected) {
        _socket.connect();
      } else if (wasOffline && _socket && _socket.connected) {
        // Restore server-side connected=True status if browser briefly fired offline without dropping socket
        if (_isSpectator && _roomCode && _spectatorToken) {
          reconnectSpectator();
        } else if (!_isSpectator && _reconnectToken && _roomCode) {
          reconnectSession(_reconnectToken, _roomCode, _playerId);
        }
      }
    });
  }

  /**
   * Pre-warm / initialize socket connection with up to 3 seconds wait for library.
   * Deduplicates concurrent initialization attempts.
   */
  function initConnection() {
    return _ensureSocketAsync(3000);
  }

  /**
   * Ensure socket is connected before emitting, waiting with a timeout if connecting.
   */
  async function _ensureConnected(timeoutMs = 7000) {
    let socket = _socket;
    if (!socket) {
      socket = await _ensureSocketAsync(3000);
    }
    if (!socket) {
      throw new Error('Socket.IO library not loaded');
    }
    if (socket.connected) {
      return socket;
    }

    return new Promise((resolve, reject) => {
      let timer = null;

      const onConnect = () => {
        cleanup();
        resolve(socket);
      };

      const onError = (err) => {
        cleanup();
        reject(err || new Error('Connection failed'));
      };

      const onTimeout = () => {
        cleanup();
        reject(new Error('Connection timed out. Check hotspot / Wi-Fi connection.'));
      };

      function cleanup() {
        if (timer) clearTimeout(timer);
        socket.off('connect', onConnect);
        socket.off('connect_error', onError);
      }

      timer = setTimeout(onTimeout, timeoutMs);
      socket.once('connect', onConnect);
      socket.once('connect_error', onError);
    });
  }

  /**
   * Create a new room (Private or Public).
   */
  async function createRoom({ playerName, isPrivate = true, maxPlayers = 4, deckCount = 1 }, callback) {
    let socket = null;
    try {
      socket = await _ensureConnected();
    } catch (err) {
      console.error('[OnlineClient] createRoom connect error:', err);
      showToast(err.message || 'Cannot reach game server.', 'error', 4000);
      if (typeof callback === 'function') callback({ success: false, message: err.message });
      return;
    }

    _playerName = playerName;

    socket.emit('create_room', {
      playerName,
      isPrivate,
      maxPlayers,
      deckCount,
    }, (res) => {
      if (!res || !res.success) {
        const msg = res ? res.message : 'Failed to create room';
        showToast(msg, 'error', 3500);
        if (typeof callback === 'function') callback(res || { success: false, message: msg });
        return;
      }

      _roomCode         = res.room_code;
      _playerId         = res.player_id;
      _isHost           = true;
      _reconnectToken   = res.reconnect_token;
      _isSpectator      = false;
      _spectatorId      = null;
      _spectatorName    = null;
      _spectatorToken   = null;
      _spectatingIntent = false;
      _postMatchStatus  = null;

      // Save session in persistent Storage for resilient reconnect across app restarts
      if (typeof Storage !== 'undefined' && Storage.saveActiveSession) {
        Storage.saveActiveSession({
          roomCode:   _roomCode,
          playerId:   _playerId,
          playerName: _playerName,
          token:      _reconnectToken,
          isHost:     _isHost,
        });
      }

      // Successfully created: close lobby modal and show waiting room
      MenuUI.hideModal('modal-online-lobby');
      MenuUI.showWaitingRoom(res.room, _playerId);
      showToast(`Room ${res.room_code} created!`, 'success', 2500);

      if (typeof callback === 'function') callback(res);
    });
  }

  /**
   * Join an existing room with a room code.
   */
  async function joinRoom({ playerName, roomCode }, callback) {
    let socket = null;
    try {
      socket = await _ensureConnected();
    } catch (err) {
      console.error('[OnlineClient] joinRoom connect error:', err);
      showToast(err.message || 'Cannot reach game server.', 'error', 4000);
      if (typeof callback === 'function') callback({ success: false, message: err.message });
      return;
    }

    _playerName = playerName;
    const cleanRoomCode = (roomCode || '').replace(/\s+/g, '').toUpperCase();

    // Only supply reconnectToken if THIS tab holds an active session specifically for THIS room
    let tokenToSend = null;
    if (typeof Storage !== 'undefined') {
      const activeSession = Storage.getTabSession
        ? Storage.getTabSession()
        : (Storage.getActiveSession ? Storage.getActiveSession() : null);
      if (activeSession && activeSession.roomCode === cleanRoomCode) {
        tokenToSend = activeSession.token;
      }
    }

    socket.emit('join_room', {
      playerName,
      roomCode: cleanRoomCode,
      reconnectToken: tokenToSend,
    }, (res) => {
      if (!res || !res.success) {
        if (tokenToSend && typeof Storage !== 'undefined' && Storage.clearActiveSession) {
          Storage.clearActiveSession();
        }
        const msg = res ? res.message : 'Failed to join room';
        showToast(msg, 'error', 3500);
        if (typeof callback === 'function') callback(res || { success: false, message: msg });
        return;
      }

      _roomCode         = res.room_code;
      _playerId         = res.player_id;
      _playerName       = res.player_name || playerName;
      _isHost           = res.is_host;
      _reconnectToken   = res.reconnect_token;
      _isSpectator      = false;
      _spectatorId      = null;
      _spectatorName    = null;
      _spectatorToken   = null;
      _spectatingIntent = false;
      _postMatchStatus  = res.post_match_status || null;

      if (typeof Storage !== 'undefined' && Storage.saveActiveSession) {
        Storage.saveActiveSession({
          roomCode:   _roomCode,
          playerId:   _playerId,
          playerName: _playerName,
          token:      _reconnectToken,
          isHost:     _isHost,
        });
      }

      if (res.room_status === 'playing') {
        MenuUI.hideModal('modal-online-lobby');
        Screens.go('screen-game');
        if (typeof App !== 'undefined' && App.activateGameBackGuard) {
          App.activateGameBackGuard();
        }
        TableUI.init({
          roomCode:   _roomCode,
          deckCount:  res.room ? res.room.deck_count : 1,
          playerName: _playerName,
          isReconnect: true,
        });
        if (typeof TableUI.setSpectatorMode === 'function') {
          TableUI.setSpectatorMode(false);
        }
        if (typeof TableUI.setOnlineControlsVisible === 'function') {
          TableUI.setOnlineControlsVisible(true, false);
        }
        if (typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
          VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
        }
        showToast(`Re-joined room ${res.room_code}!`, 'success', 2500);
      } else if (res.room_status === 'finished') {
        MenuUI.hideModal('modal-online-lobby');
        if (typeof App !== 'undefined' && App.handlePostMatchStatus && res.post_match_status) {
          App.handlePostMatchStatus(res.post_match_status);
        }
        showToast(`Re-joined finished room ${res.room_code}`, 'success', 2500);
      } else {
        // Successfully joined waiting room
        MenuUI.hideModal('modal-online-lobby');
        MenuUI.showWaitingRoom(res.room, _playerId);
        showToast(`Joined room ${res.room_code}!`, 'success', 2500);
      }

      if (typeof callback === 'function') callback(res);
    });
  }

  /**
   * Host starts the game.
   */
  function startGame() {
    if (_isSpectator || !_socket || !_isHost || !_roomCode) return;

    _socket.emit('start_game', {
      roomCode: _roomCode,
      playerId: _playerId,
    }, (res) => {
      if (res && !res.success) {
        showToast(res.message || 'Cannot start game', 'error');
      }
    });
  }

  /**
   * Play a card in the online game.
   */
  function playCard(cardId) {
    if (_isSpectator) return;
    if (!_socket || !_roomCode || !_playerId) {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      return;
    }

    _socket.emit('play_card', {
      roomCode: _roomCode,
      playerId: _playerId,
      cardId:   cardId,
    }, (res) => {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      if (res && !res.success) {
        showToast(res.message || 'Illegal card play', 'error');
        // Resync authoritative state from server if play was rejected
        if (_socket && _roomCode) {
          _socket.emit('get_room_state', { roomCode: _roomCode, playerId: _playerId });
        }
      }
    });
  }

  /**
   * Restart game (host-controlled Restart Game — distinct from Play Again).
   * Shows feedback ONLY after the server confirms success or failure.
   */
  function restartGame(callback) {
    if (_isSpectator || !_socket || !_roomCode || !_playerId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not connected to room' });
      return;
    }
    if (!_isHost) {
      const msg = 'Only the host can restart the game';
      showToast(msg, 'info', 2500);
      if (typeof callback === 'function') callback({ success: false, message: msg });
      return;
    }
    if (!_socket.connected) {
      const msg = 'Reconnecting to server… please try restarting again in a moment.';
      showToast(msg, 'error', 3000);
      if (typeof callback === 'function') callback({ success: false, message: msg });
      return;
    }
    if (_restartInFlight) return;
    _restartInFlight = true;

    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      _restartInFlight = false;
      const msg = 'Restart request timed out. Please try again.';
      showToast(msg, 'error', 3000);
      if (typeof callback === 'function') callback({ success: false, message: msg });
    }, 6000);

    _socket.emit('restart_game', {
      roomCode: _roomCode,
      playerId: _playerId,
    }, (res) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      _restartInFlight = false;
      if (!res || !res.success) {
        showToast((res && res.message) || 'Cannot restart game', 'error', 3000);
      }
      if (typeof callback === 'function') callback(res || { success: false, message: 'Cannot restart game' });
    });
  }

  /**
   * Stage 2: Toggle post-match Ready / Not Ready status.
   */
  function setPostMatchReady(ready, callback) {
    if (_isSpectator || !_socket || !_roomCode || !_playerId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not eligible to set ready status' });
      return;
    }
    _socket.emit('set_post_match_ready', {
      roomCode: _roomCode,
      playerId: _playerId,
      ready:    !!ready,
    }, (res) => {
      if (res && res.success && res.post_match_status) {
        _postMatchStatus = res.post_match_status;
      }
      if (typeof callback === 'function') callback(res);
    });
  }

  /**
   * Stage 2: Request post-match Play Again (server validates all 4 conditions under lock).
   */
  function playAgain(callback) {
    if (_isSpectator || !_socket || !_roomCode || !_playerId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not eligible for Play Again' });
      return;
    }
    if (!_socket.connected) {
      const msg = 'Reconnecting to server… please wait a moment.';
      showToast(msg, 'error', 3000);
      if (typeof callback === 'function') callback({ success: false, message: msg });
      return;
    }
    if (_playAgainInFlight) return;
    _playAgainInFlight = true;

    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      _playAgainInFlight = false;
      const msg = 'Play Again request timed out. Please try again.';
      showToast(msg, 'error', 3000);
      if (typeof callback === 'function') callback({ success: false, message: msg });
    }, 6000);

    _socket.emit('play_again', {
      roomCode: _roomCode,
      playerId: _playerId,
    }, (res) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      _playAgainInFlight = false;
      if (!res || !res.success) {
        showToast((res && res.message) || 'Cannot start Play Again yet', 'info', 2500);
      }
      if (typeof callback === 'function') callback(res || { success: false, message: 'Cannot start Play Again yet' });
    });
  }

  /**
   * Stage 4: Join a waiting or active room as a live spectator.
   */
  async function joinAsSpectator({ roomCode, spectatorName }, callback) {
    _spectatingIntent = true;
    let socket = null;
    try {
      socket = await _ensureConnected();
    } catch (err) {
      console.error('[OnlineClient] joinAsSpectator connect error:', err);
      const msg = err.message || 'Cannot reach game server.';
      if (typeof callback === 'function') callback({ success: false, message: msg });
      return;
    }

    const cleanCode = (roomCode || '').trim().toUpperCase();
    const cleanName = (spectatorName || 'Spectator').trim() || 'Spectator';

    socket.emit('join_as_spectator', {
      roomCode: cleanCode,
      spectatorName: cleanName,
    }, (res) => {
      if (!res || !res.success) {
        const msg = (res && res.message) || 'Could not join room as spectator';
        if (typeof callback === 'function') callback({ success: false, message: msg });
        return;
      }

      _roomCode         = res.room_code;
      _playerId         = null;
      _playerName       = null;
      _isHost           = false;
      _reconnectToken   = null;
      _isSpectator      = true;
      _spectatorId      = res.spectator_id;
      _spectatorName    = res.spectator_name || cleanName;
      _spectatorToken   = res.spectator_token || null;
      _matchId          = res.match_id || null;
      _postMatchStatus  = null;

      MenuUI.hideModal('modal-spectate');

      if (res.room_status === 'waiting') {
        MenuUI.showWaitingRoom(res.room, _spectatorId, true);
        showToast(`Spectating lobby ${res.room_code}`, 'success', 2500);
      } else if (res.room_status === 'playing') {
        Screens.go('screen-game');
        TableUI.init({
          roomCode:   _roomCode,
          deckCount:  (res.room && res.room.deck_count) || (res.spectator_state && res.spectator_state.deck_count) || 1,
          playerName: _spectatorName,
        });
        if (typeof TableUI.setSpectatorMode === 'function') {
          TableUI.setSpectatorMode(true);
        }
        if (typeof TableUI.setOnlineControlsVisible === 'function') {
          TableUI.setOnlineControlsVisible(true, true);
        }
        if (typeof App !== 'undefined' && App.clearStageChatsOnMatchStart) {
          App.clearStageChatsOnMatchStart();
        }
        if (res.spectator_state && typeof App !== 'undefined' && App.renderSpectatorState) {
          App.renderSpectatorState(res.spectator_state);
        }
        showToast(`Spectating live match in ${res.room_code}`, 'success', 2500);
      }

      if (typeof App !== 'undefined' && App.handleSpectatorsUpdated) {
        App.handleSpectatorsUpdated({
          spectators: res.spectators || [],
          spectator_count: res.spectator_count || 0,
        });
      }

      if (typeof callback === 'function') callback(res);
    });
  }

  /**
   * Stage 4: Cleanly leave spectator mode.
   */
  function leaveSpectator(onComplete) {
    if (typeof MenuUI !== 'undefined' && MenuUI.clearLobbyChat) {
      MenuUI.clearLobbyChat();
    }
    if (_socket && _roomCode && _spectatorId) {
      _socket.emit('leave_spectator', {
        roomCode:    _roomCode,
        spectatorId: _spectatorId,
      }, () => {
        if (typeof onComplete === 'function') onComplete();
      });
    } else if (typeof onComplete === 'function') {
      onComplete();
    }
    _roomCode         = null;
    _spectatorId      = null;
    _spectatorName    = null;
    _spectatorToken   = null;
    _spectatingIntent = false;
    _isSpectator      = false;
    _matchId          = null;
    _postMatchStatus  = null;
  }

  /**
   * Re-attach an active spectator session seamlessly after a transient socket reconnect.
   */
  function reconnectSpectator() {
    if (!_socket || !_isSpectator || !_roomCode || !_spectatorToken) return;
    _socket.emit('reconnect_spectator', {
      roomCode:       _roomCode,
      spectatorToken: _spectatorToken,
    }, (res) => {
      if (res && res.success) {
        _spectatorId    = res.spectator_id || _spectatorId;
        _spectatorName  = res.spectator_name || _spectatorName;
        _spectatorToken = res.spectator_token || _spectatorToken;
        _matchId        = res.match_id || _matchId;
        if (res.spectator_state && typeof App !== 'undefined' && App.renderSpectatorState) {
          App.renderSpectatorState(res.spectator_state);
        }
        if (typeof App !== 'undefined' && App.handleSpectatorsUpdated) {
          App.handleSpectatorsUpdated({
            spectators: res.spectators || [],
            spectator_count: res.spectator_count || 0,
          });
        }
      }
    });
  }

  /**
   * Reconnect to an existing room using session token, room code, and player ID.
   */
  async function reconnectSession(token, targetRoomCode = null, targetPlayerId = null) {
    if (_isReconnecting) return;
    let socket = _socket;
    if (!socket) {
      try {
        socket = await _ensureSocketAsync(3000);
      } catch (err) {
        console.warn('[OnlineClient] Cannot reconnect session without Socket.IO:', err);
        return;
      }
    }
    if (!socket || !token) return;

    _isReconnecting = true;

    const payload = { reconnectToken: token };
    if (targetRoomCode) {
      payload.roomCode = targetRoomCode;
    }
    if (targetPlayerId) {
      payload.playerId = targetPlayerId;
    }

    socket.emit('reconnect_session', payload, (res) => {
      _isReconnecting = false;
      // Never allow an old player reconnect response to hijack an active spectator session
      if (_isSpectator || _spectatingIntent) {
        return;
      }
      if (res && res.success) {
        _roomCode        = res.room_code;
        _playerId        = res.player_id;
        _playerName      = res.player_name;
        _isHost          = res.is_host;
        _reconnectToken  = token;
        _isSpectator     = false;
        _spectatorId     = null;
        _postMatchStatus = res.post_match_status || null;

        if (typeof Storage !== 'undefined' && Storage.saveActiveSession) {
          Storage.saveActiveSession({
            roomCode:   _roomCode,
            playerId:   _playerId,
            playerName: _playerName,
            token:      token,
            isHost:     _isHost,
          });
        }

        console.log('[OnlineClient] Successfully reconnected to room', _roomCode);

        if (res.room_status === 'waiting') {
          MenuUI.showWaitingRoom(res.room, _playerId, false);
        } else if (res.room_status === 'playing') {
          Screens.go('screen-game');
          if (typeof App !== 'undefined' && App.activateGameBackGuard) {
            App.activateGameBackGuard();
          }
          TableUI.init({
            roomCode:   _roomCode,
            deckCount:  res.room ? res.room.deck_count : 1,
            playerName: _playerName,
            isReconnect: true,
          });
          if (typeof TableUI.setSpectatorMode === 'function') {
            TableUI.setSpectatorMode(false);
          }
          if (typeof TableUI.setOnlineControlsVisible === 'function') {
            TableUI.setOnlineControlsVisible(true, false);
          }
          if (typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
            VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
          }
        } else if (res.room_status === 'finished' && res.game_over) {
          if (typeof App !== 'undefined' && App.showOnlineResults) {
            App.showOnlineResults(res.game_over);
          }
        }
        showToast(`Reconnected to room ${_roomCode}`, 'success', 3000);
      } else {
        // Only clear stale session if this tab has not already joined/created a newer room
        const currentSess = (typeof Storage !== 'undefined' && Storage.getTabSession)
          ? Storage.getTabSession()
          : null;
        if (!currentSess || currentSess.token === token) {
          if (typeof Storage !== 'undefined' && Storage.clearActiveSession) {
            Storage.clearActiveSession();
          }
          if (!_roomCode) {
            _reconnectToken = null;
            if (typeof Screens !== 'undefined' && Screens.current && Screens.current() !== 'screen-menu') {
              Screens.go('screen-menu');
            }
          }
        }
      }
    });
  }

  /**
   * Send an emoji reaction to all players in the room.
   */
  function sendReaction(emoji) {
    if (_isSpectator) return;
    if (_socket && _socket.connected && _roomCode && _playerId) {
      _socket.emit('send_reaction', {
        roomCode: _roomCode,
        playerId: _playerId,
        emoji: emoji,
      });
    }
  }

  /**
   * Stage 3: Send a message in one of the three independent chat stages:
   * 'pre_match', 'in_match', or 'post_match'. Works for both players and spectators.
   */
  function sendStageChatMessage(stage, message, callback) {
    const senderId = getCurrentSenderId();
    if (!_socket || !_roomCode || !senderId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not connected to room' });
      return;
    }
    if (!_socket.connected) {
      if (typeof callback === 'function') callback({ success: false, message: 'Reconnecting to room… please try again in a moment.' });
      return;
    }
    const text = (message || '').trim();
    if (!text) {
      if (typeof callback === 'function') callback({ success: false, message: 'Message cannot be empty' });
      return;
    }

    const payload = {
      roomCode: _roomCode,
      senderId: senderId,
      stage:    stage,
      message:  text,
    };
    if (_isSpectator) {
      payload.spectatorId = _spectatorId;
    } else {
      payload.playerId = _playerId;
    }

    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      if (typeof callback === 'function') {
        callback({ success: false, message: 'Message could not be delivered. Please check your connection and try again.' });
      }
    }, 5000);

    _socket.emit('send_chat_message', payload, (res) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      if (typeof callback === 'function') {
        callback(res || { success: false, message: 'Server did not confirm message delivery.' });
      }
    });
  }

  /**
   * Send a real-time pre-match lobby chat message (players + spectators).
   */
  function sendLobbyChatMessage(message, callback) {
    const senderId = getCurrentSenderId();
    if (!_socket || !_roomCode || !senderId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not connected to room' });
      return;
    }
    if (!_socket.connected) {
      if (typeof callback === 'function') callback({ success: false, message: 'Reconnecting to room… please try again in a moment.' });
      return;
    }
    const text = (message || '').trim();
    if (!text) {
      if (typeof callback === 'function') callback({ success: false, message: 'Message cannot be empty' });
      return;
    }

    const payload = {
      roomCode: _roomCode,
      senderId: senderId,
      message:  text,
    };
    if (_isSpectator) {
      payload.spectatorId = _spectatorId;
    } else {
      payload.playerId = _playerId;
    }

    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      if (typeof callback === 'function') {
        callback({ success: false, message: 'Message could not be delivered. Please check your connection and try again.' });
      }
    }, 5000);

    _socket.emit('send_lobby_chat', payload, (res) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      if (typeof callback === 'function') {
        callback(res || { success: false, message: 'Server did not confirm message delivery.' });
      }
    });
  }

  /**
   * Leave the waiting room, game, post-match room, or spectator view cleanly.
   */
  function leaveRoom(reason = 'left', onComplete) {
    if (_isSpectator) {
      leaveSpectator(onComplete);
      return;
    }
    if (typeof VoiceClient !== 'undefined' && VoiceClient.leaveVoice) {
      VoiceClient.leaveVoice();
    }
    if (typeof MenuUI !== 'undefined' && MenuUI.clearLobbyChat) {
      MenuUI.clearLobbyChat();
    }
    if (_socket && _roomCode && _playerId) {
      _socket.emit('leave_room', {
        roomCode: _roomCode,
        playerId: _playerId,
        reason:   reason,
      }, () => {
        if (typeof onComplete === 'function') onComplete();
      });
    } else {
      if (typeof onComplete === 'function') onComplete();
    }
    _roomCode        = null;
    _playerId        = null;
    _isHost          = false;
    _reconnectToken  = null;
    _matchId         = null;
    _postMatchStatus = null;
    if (typeof Storage !== 'undefined' && Storage.clearActiveSession) {
      Storage.clearActiveSession();
    }
  }

  /**
   * Disconnect completely.
   */
  function disconnect() {
    _initPromise = null;
    leaveRoom('left', () => {
      if (_socket) {
        _socket.disconnect();
        _socket = null;
      }
    });
  }

  return {
    initConnection,
    isConnected,
    getRoomCode,
    isHost,
    getPlayerId,
    isSpectator,
    getSpectatorId,
    getCurrentSenderId,
    getPostMatchStatus,
    createRoom,
    joinRoom,
    joinAsSpectator,
    leaveSpectator,
    setSpectatingIntent,
    reconnectSpectator,
    startGame,
    restartGame,
    setPostMatchReady,
    playAgain,
    playCard,
    sendReaction,
    sendLobbyChatMessage,
    sendStageChatMessage,
    leaveRoom,
    reconnectSession,
    disconnect,
    _waitForSocketIO,
    _ensureSocketAsync,
  };
})();
