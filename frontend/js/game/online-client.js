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
   * Initialize socket connection if not already created.
   */
  function _ensureSocket() {
    if (_socket) return _socket;

    if (typeof io === 'undefined') {
      showToast('Socket.IO library failed to load. Please check your connection.', 'error');
      _updateConnectionStatusUI('disconnected', '🔴 Socket.IO library missing');
      return null;
    }

    _updateConnectionStatusUI('reconnecting', 'Connecting to server…');

    const serverUrl = (window.location.protocol === 'file:' || !window.location.host)
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

      // Check if we have an active reconnection token to restore session
      const savedToken = _reconnectToken || sessionStorage.getItem('kz_reconnect_token');
      if (savedToken) {
        reconnectSession(savedToken);
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

    return _socket;
  }

  // Network state listeners for unexpected connection loss
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

  /**
   * Pre-warm / initialize socket connection.
   */
  function initConnection() {
    return _ensureSocket();
  }

  /**
   * Ensure socket is connected before emitting, waiting with a timeout if connecting.
   */
  function _ensureConnected(timeoutMs = 7000) {
    return new Promise((resolve, reject) => {
      const socket = _ensureSocket();
      if (!socket) {
        return reject(new Error('Socket.IO library not loaded'));
      }
      if (socket.connected) {
        return resolve(socket);
      }

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

      // Save token in sessionStorage for quick reconnect
      sessionStorage.setItem('kz_reconnect_token', _reconnectToken);
      sessionStorage.setItem('kz_room_code', _roomCode);

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

    socket.emit('join_room', {
      playerName,
      roomCode,
    }, (res) => {
      if (!res || !res.success) {
        const msg = res ? res.message : 'Failed to join room';
        showToast(msg, 'error', 3500);
        if (typeof callback === 'function') callback(res || { success: false, message: msg });
        return;
      }

      _roomCode       = res.room_code;
      _playerId       = res.player_id;
      _isHost         = res.is_host;
      _reconnectToken = res.reconnect_token;

      sessionStorage.setItem('kz_reconnect_token', _reconnectToken);
      sessionStorage.setItem('kz_room_code', _roomCode);

      // Successfully joined: close lobby modal and show waiting room
      MenuUI.hideModal('modal-online-lobby');
      MenuUI.showWaitingRoom(res.room, _playerId);
      showToast(`Joined room ${res.room_code}!`, 'success', 2500);

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
   * Reconnect to an existing room using session token.
   */
  function reconnectSession(token) {
    const socket = _ensureSocket();
    if (!socket || !token) return;

    socket.emit('reconnect_session', { reconnectToken: token }, (res) => {
      if (res && res.success) {
        _roomCode       = res.room_code;
        _playerId       = res.player_id;
        _playerName     = res.player_name;
        _isHost         = res.is_host;
        _reconnectToken = token;

        sessionStorage.setItem('kz_reconnect_token', token);
        sessionStorage.setItem('kz_room_code', _roomCode);

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
          });
        }
        showToast(`Reconnected to room ${_roomCode}`, 'success', 3000);
      } else {
        sessionStorage.removeItem('kz_reconnect_token');
        sessionStorage.removeItem('kz_room_code');
        _reconnectToken = null;
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
   * Leave the waiting room or game.
   */
  function leaveRoom(reason = 'left', onComplete) {
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
    sessionStorage.removeItem('kz_reconnect_token');
    sessionStorage.removeItem('kz_room_code');
  }

  /**
   * Disconnect completely.
   */
  function disconnect() {
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
    leaveRoom,
    reconnectSession,
    disconnect,
  };
})();
