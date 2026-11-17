/**
 * KAZHUDHAI CLUB — online-client.js
 * Complete SocketIO-based real-time multiplayer client for Stage 6.
 * Manages room lifecycle, authoritative synchronization, and card privacy.
 */
const OnlineClient = (() => {

  let _socket         = null;
  let _roomCode       = null;
  let _playerId       = null;
  let _playerName     = null;
  let _isHost         = false;
  let _reconnectToken = null;
  let _isReconnecting = false;
  let _initPromise    = null;

  function isConnected() {
    return !!_socket && _socket.connected;
  }

  function getRoomCode() {
    return _roomCode;
  }

  function isHost() {
    return _isHost;
  }

  function getPlayerId() {
    return _playerId;
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

      // Check if we have an active reconnection session to restore
      const activeSession = (typeof Storage !== 'undefined' && Storage.getActiveSession)
        ? Storage.getActiveSession()
        : null;

      if (activeSession && activeSession.token) {
        reconnectSession(activeSession.token, activeSession.roomCode, activeSession.playerId);
      } else if (_reconnectToken && _roomCode) {
        reconnectSession(_reconnectToken, _roomCode, _playerId);
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
      MenuUI.updateWaitingRoom(roomSummary, _playerId);
    });

    // Game started signal
    _socket.on('game_started', (data) => {
      if (typeof MenuUI !== 'undefined' && MenuUI.clearLobbyChat) {
        MenuUI.clearLobbyChat();
      }
      MenuUI.hideWaitingRoom();
      Screens.go('screen-game');
      if (typeof App !== 'undefined' && App.activateGameBackGuard) {
        App.activateGameBackGuard();
      }
      TableUI.init({
        roomCode:   _roomCode,
        deckCount:  1,
        playerName: _playerName,
      });
      if (typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
        VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
      }
      showToast('Game started! Distributing cards…', 'info', 2000);
    });

    // Authoritative personalized game state
    _socket.on('game_state', (state) => {
      if (App && App.renderOnlineState) {
        App.renderOnlineState(state);
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

    // Real-time lobby chat messages
    _socket.on('lobby_chat_message', (msg) => {
      if (typeof MenuUI !== 'undefined' && MenuUI.addLobbyChatMessage) {
        MenuUI.addLobbyChatMessage(msg, _playerId);
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

  // Network state listeners for unexpected connection loss
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('offline', () => {
      console.warn('[OnlineClient] Network offline detected');
      if (_socket && _socket.connected && _roomCode && _playerId) {
        _socket.emit('client_connection_lost', {
          roomCode: _roomCode,
          playerId: _playerId,
        });
      }
      if (typeof TableUI !== 'undefined') {
        TableUI.updatePlayerStatus(_playerId, 'reconnecting');
      }
    });

    window.addEventListener('online', () => {
      console.log('[OnlineClient] Network online restored');
      if (_socket && !_socket.connected) {
        _socket.connect();
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

      _roomCode       = res.room_code;
      _playerId       = res.player_id;
      _isHost         = true;
      _reconnectToken = res.reconnect_token;

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
    const cleanRoomCode = (roomCode || '').trim().toUpperCase();

    // Only supply reconnectToken if there is an active session specifically for THIS room
    let tokenToSend = null;
    if (typeof Storage !== 'undefined' && Storage.getActiveSession) {
      const activeSession = Storage.getActiveSession();
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

      _roomCode       = res.room_code;
      _playerId       = res.player_id;
      _playerName     = res.player_name || playerName;
      _isHost         = res.is_host;
      _reconnectToken = res.reconnect_token;

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
        if (typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
          VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
        }
        showToast(`Re-joined room ${res.room_code}!`, 'success', 2500);
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
    if (!_socket || !_isHost || !_roomCode) return;

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
   * Restart game (host only)
   */
  function restartGame() {
    if (!_socket || !_roomCode || !_playerId) return;
    if (_isHost) {
      _socket.emit('start_game', {
        roomCode: _roomCode,
        playerId: _playerId,
      }, (res) => {
        if (res && !res.success) {
          showToast(res.message || 'Cannot restart game', 'error');
        }
      });
    } else {
      showToast('Only the host can restart the game', 'info');
    }
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
      if (res && res.success) {
        _roomCode       = res.room_code;
        _playerId       = res.player_id;
        _playerName     = res.player_name;
        _isHost         = res.is_host;
        _reconnectToken = token;

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
          MenuUI.showWaitingRoom(res.room, _playerId);
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
          if (typeof VoiceClient !== 'undefined' && VoiceClient.startVoice) {
            VoiceClient.startVoice(_socket, _roomCode, _playerId, _playerName);
          }
        }
        showToast(`Reconnected to room ${_roomCode}`, 'success', 3000);
      } else {
        if (typeof Storage !== 'undefined' && Storage.clearActiveSession) {
          Storage.clearActiveSession();
        }
        _reconnectToken = null;
        Screens.go('screen-menu');
      }
    });
  }

  /**
   * Send an emoji reaction to all players in the room.
   */
  function sendReaction(emoji) {
    if (_socket && _socket.connected && _roomCode && _playerId) {
      _socket.emit('send_reaction', {
        roomCode: _roomCode,
        playerId: _playerId,
        emoji: emoji,
      });
    }
  }

  /**
   * Send a real-time lobby chat message.
   */
  function sendLobbyChatMessage(message, callback) {
    if (!_socket || !_roomCode || !_playerId) {
      if (typeof callback === 'function') callback({ success: false, message: 'Not connected to room' });
      return;
    }
    const text = (message || '').trim();
    if (!text) {
      if (typeof callback === 'function') callback({ success: false, message: 'Message cannot be empty' });
      return;
    }
    _socket.emit('send_lobby_chat', {
      roomCode: _roomCode,
      playerId: _playerId,
      message: text,
    }, (res) => {
      if (typeof callback === 'function') callback(res);
    });
  }

  /**
   * Leave the waiting room or game.
   */
  function leaveRoom(reason = 'left', onComplete) {
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
      }, (res) => {
        if (typeof onComplete === 'function') onComplete();
      });
    } else {
      if (typeof onComplete === 'function') onComplete();
    }
    _roomCode = null;
    _playerId = null;
    _isHost   = false;
    _reconnectToken = null;
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
    createRoom,
    joinRoom,
    startGame,
    restartGame,
    playCard,
    sendReaction,
    sendLobbyChatMessage,
    leaveRoom,
    reconnectSession,
    disconnect,
    _waitForSocketIO,
    _ensureSocketAsync,
  };
})();
