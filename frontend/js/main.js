/**
 * KAZHUDHAI CLUB — main.js
 * Application entry point, screen routing, and offline game loop coordinator.
 * Manages step-by-step turn execution, attack alerts, round collections, and victory screens.
 */

// ── Global toast helper ──
function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const typeClass = type === 'error' ? 'toast-error' :
                    type === 'success' ? 'toast-success' :
                    type === 'attack' ? 'toast-attack' :
                    type === 'departure' ? 'toast-departure' : '';
  toast.className = `toast ${typeClass}`.trim();
  toast.textContent = message;

  // Custom animation timing when duration is specified
  if (duration !== 3000) {
    const fadeStart = Math.max(0.4, (duration - 400) / 1000);
    toast.style.animation = `toastIn 0.3s ease, toastOut 0.4s ease ${fadeStart}s forwards`;
  }

  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration + 400);
}

// ── Screen Manager ──
const Screens = (() => {
  let _current = null;

  function go(screenId) {
    if (_current) {
      document.getElementById(_current)?.classList.remove('active');
      document.getElementById(_current)?.classList.add('hidden');
    }
    const next = document.getElementById(screenId);
    if (next) {
      next.classList.remove('hidden');
      next.classList.add('active');
    }
    _current = screenId;
  }

  function current() { return _current; }

  return { go, current };
})();

// ── Main Application Controller ──
const App = (() => {

  let _currentConfig   = null;
  let _isOffline       = true;
  let _aiStepTimeout   = null;
  let _roundResolutionTimer = null;
  let _isStepping      = false;
  let _isRoundPaused   = false;
  let _pendingNextState = null;
  let _unreadActivityCount = 0;
  let _hasGameBackGuard = false;
  let _activeModalGuard = null;
  let _suppressNextPopCount = 0;
  let _suppressResetTimer = null;
  let _backNavBound = false;

  function _clearRoundTimer() {
    if (_roundResolutionTimer) {
      clearTimeout(_roundResolutionTimer);
      _roundResolutionTimer = null;
    }
  }

  const MAIN_MENU_MODALS = [
    'modal-offline-setup',
    'modal-online-lobby',
    'modal-spectate',
    'modal-rules',
    'modal-settings',
  ];

  function _isSupportedModal(modalId) {
    return MAIN_MENU_MODALS.includes(modalId);
  }

  function _isModalVisible(modalId) {
    const el = document.getElementById(modalId);
    return !!(el && !el.classList.contains('hidden'));
  }

  function _getOpenModalId() {
    for (const id of MAIN_MENU_MODALS) {
      if (_isModalVisible(id)) return id;
    }
    return null;
  }

  function _hideOpenModal(modalId, options) {
    if (typeof MenuUI !== 'undefined' && typeof MenuUI.hideModal === 'function') {
      MenuUI.hideModal(modalId, options);
    } else {
      const el = document.getElementById(modalId);
      if (el) el.classList.add('hidden');
      onModalClosed(modalId, options);
    }
  }

  function isActivelyPlayingGame() {
    if (Screens.current() !== 'screen-game') return false;
    if (!GameClient.isActive()) return false;
    const state = GameClient.getState();
    return !state || state.status === 'playing';
  }

  function activateGameBackGuard() {
    if (typeof window === 'undefined' || !window.history || typeof window.history.pushState !== 'function') {
      return;
    }
    if (Screens.current() !== 'screen-game') return;

    if (_suppressResetTimer) {
      clearTimeout(_suppressResetTimer);
      _suppressResetTimer = null;
    }
    _suppressNextPopCount = 0;

    if (_hasGameBackGuard) return;
    if (window.history.state && window.history.state.kzBackGuard === 'game') {
      _hasGameBackGuard = true;
      return;
    }

    const nextState = Object.assign({}, window.history.state || {}, { kzBackGuard: 'game' });
    window.history.pushState(nextState, '', window.location.href);
    _hasGameBackGuard = true;
  }

  function onModalOpened(modalId) {
    if (!_isSupportedModal(modalId)) {
      return;
    }
    if (typeof window === 'undefined' || !window.history || typeof window.history.pushState !== 'function') {
      return;
    }

    const inGame = isActivelyPlayingGame();
    if (inGame) {
      // Ensure base game back guard exists first
      activateGameBackGuard();
    }

    // Prevent duplicate entries for the same modal
    if (_activeModalGuard === modalId) {
      return;
    }

    const statePayload = { kzModalGuard: modalId };
    if (inGame) {
      statePayload.kzBackGuard = 'game';
    }

    const baseState = Object.assign({}, window.history.state || {});
    if (!inGame) {
      delete baseState.kzBackGuard;
    }

    // If another modal entry is already active, replace it so we never stack multiple modal entries
    if (_activeModalGuard || (window.history.state && window.history.state.kzModalGuard)) {
      _activeModalGuard = modalId;
      const nextState = Object.assign(baseState, statePayload);
      if (typeof window.history.replaceState === 'function') {
        window.history.replaceState(nextState, '', window.location.href);
      }
      return;
    }

    // Push dedicated modal history entry
    _activeModalGuard = modalId;
    const nextState = Object.assign(baseState, statePayload);
    window.history.pushState(nextState, '', window.location.href);
  }

  function onModalClosed(modalId, options) {
    if (!_isSupportedModal(modalId)) {
      return;
    }

    // If closed via Back button (popstate), the modal history entry was already consumed by the browser
    if (options && options.fromPopState) {
      if (_activeModalGuard === modalId) {
        _activeModalGuard = null;
      }
      return;
    }

    // Modal was closed manually (X button, backdrop click, or programmatic close)
    const isGuardedState = !!(typeof window !== 'undefined' && window.history && window.history.state && window.history.state.kzModalGuard === modalId);
    if (_activeModalGuard === modalId || isGuardedState) {
      _activeModalGuard = null;
      _suppressNextPopCount += 1;
      if (_suppressResetTimer) clearTimeout(_suppressResetTimer);
      _suppressResetTimer = setTimeout(() => {
        _suppressNextPopCount = 0;
        _suppressResetTimer = null;
      }, 300);
      window.history.back();
    }
  }

  function _releaseGameBackGuard() {
    _activeModalGuard = null;
    _hasGameBackGuard = false;
    if (typeof window === 'undefined' || !window.history) return;

    const hasModal = !!(window.history.state && window.history.state.kzModalGuard);
    const hasGame = !!(window.history.state && window.history.state.kzBackGuard === 'game');
    if (hasModal || hasGame) {
      const delta = (hasModal && hasGame) ? -2 : -1;
      _suppressNextPopCount += 1;
      if (_suppressResetTimer) clearTimeout(_suppressResetTimer);
      _suppressResetTimer = setTimeout(() => {
        _suppressNextPopCount = 0;
        _suppressResetTimer = null;
      }, 300);
      if (typeof window.history.go === 'function') {
        window.history.go(delta);
      } else if (typeof window.history.back === 'function') {
        window.history.back();
      }
    }
  }

  function _handlePopState() {
    if (_suppressNextPopCount > 0) {
      _suppressNextPopCount -= 1;
      if (_suppressNextPopCount === 0 && _suppressResetTimer) {
        clearTimeout(_suppressResetTimer);
        _suppressResetTimer = null;
      }
      _hasGameBackGuard = !!(window.history.state && window.history.state.kzBackGuard === 'game');
      const visibleModal = _getOpenModalId();
      if (visibleModal && !_activeModalGuard) {
        onModalOpened(visibleModal);
      }
      return;
    }

    // Priority 1: If any popup modal was open or guarded, Back button must close that modal first
    const modalToClose = _activeModalGuard || _getOpenModalId();

    if (modalToClose) {
      _activeModalGuard = null;
      _hideOpenModal(modalToClose, { fromPopState: true });
      MAIN_MENU_MODALS.forEach(id => {
        if (_isModalVisible(id)) _hideOpenModal(id, { fromPopState: true });
      });

      // If in active gameplay, verify base game guard is active on the current history entry
      if (isActivelyPlayingGame()) {
        _hasGameBackGuard = !!(window.history.state && window.history.state.kzBackGuard === 'game');
        if (!_hasGameBackGuard) {
          activateGameBackGuard();
        }
      } else {
        _hasGameBackGuard = false;
      }
      return;
    }

    // Retain normal navigation when no game is active (and no modal is open)
    if (!isActivelyPlayingGame()) {
      _hasGameBackGuard = false;
      _activeModalGuard = null;
      return;
    }

    // Browser popped the game entry
    _hasGameBackGuard = false;

    // Priority 2: Prevent multiple confirmation dialogs if already visible
    if (typeof TableUI !== 'undefined' && TableUI.isExitConfirmOpen && TableUI.isExitConfirmOpen()) {
      activateGameBackGuard();
      return;
    }

    // Priority 3: Close open in-game drawer menu first
    if (typeof TableUI !== 'undefined' && TableUI.isInGameMenuOpen && TableUI.isInGameMenuOpen()) {
      TableUI.closeInGameMenu();
      activateGameBackGuard();
      return;
    }

    // Priority 4: Keep back navigation guarded and open Leave Game confirmation
    activateGameBackGuard();
    if (typeof TableUI !== 'undefined' && TableUI.showExitConfirm) {
      TableUI.showExitConfirm();
    } else {
      document.getElementById('confirm-exit')?.classList.remove('hidden');
    }
  }

  // ── Authoritative check if it is the local player's turn ──
  function isCurrentPlayerTurn() {
    const state = GameClient.getState();
    if (!state || state.status !== 'playing') return false;
    const myId = _isOffline ? 'human' : OnlineClient.getPlayerId();
    if (state.current_player_id && myId && state.current_player_id === myId) {
      return true;
    }
    return !!state.is_my_turn;
  }

  // ── Stage 3: Independent Chat Stages State ──
  let _unreadInMatchChatCount = 0;
  let _seenInMatchMsgIds = new Set();
  let _seenPostMatchMsgIds = new Set();
  let _localPostMatchReady = false;

  function _updateInMatchChatBadge() {
    const badge = document.getElementById('ingame-chat-badge');
    if (!badge) return;
    if (_unreadInMatchChatCount > 0) {
      badge.textContent = String(_unreadInMatchChatCount > 99 ? '99+' : _unreadInMatchChatCount);
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  }

  function toggleInMatchChat() {
    const drawer = document.getElementById('ingame-chat-drawer');
    if (!drawer) return;
    const willOpen = drawer.classList.contains('hidden');
    drawer.classList.toggle('hidden');
    if (willOpen) {
      _unreadInMatchChatCount = 0;
      _updateInMatchChatBadge();
      const input = document.getElementById('ingame-chat-input');
      if (input) input.focus();
    }
  }

  function closeInMatchChat() {
    const drawer = document.getElementById('ingame-chat-drawer');
    if (drawer) drawer.classList.add('hidden');
  }

  function _clearStageChatUI(stage) {
    if (stage === 'in_match') {
      _seenInMatchMsgIds.clear();
      _unreadInMatchChatCount = 0;
      _updateInMatchChatBadge();
      const list = document.getElementById('ingame-chat-messages');
      if (list) list.innerHTML = '<div class="empty-chat-hint">In-match chat is fresh for this game. Say hello!</div>';
      const input = document.getElementById('ingame-chat-input');
      if (input) input.value = '';
    } else if (stage === 'post_match') {
      _seenPostMatchMsgIds.clear();
      const list = document.getElementById('post-match-chat-messages');
      if (list) list.innerHTML = '<div class="empty-chat-hint">Match finished! Say GG to everyone.</div>';
      const input = document.getElementById('post-match-chat-input');
      if (input) input.value = '';
    }
  }

  function clearStageChatsOnMatchStart() {
    closeInMatchChat();
    _clearStageChatUI('in_match');
    _clearStageChatUI('post_match');
    _localPostMatchReady = false;
  }

  function _appendChatItem(listEl, msg, mySenderId) {
    if (!listEl || !msg) return;
    const hint = listEl.querySelector('.empty-chat-hint');
    if (hint) hint.remove();

    const isSelf = !!(mySenderId && msg.sender_id === mySenderId);
    const isSpec = !!msg.is_spectator;
    const displayLabel = msg.display_name || (isSpec ? `[Spectator] ${msg.sender_name}` : msg.sender_name);

    const item = document.createElement('div');
    item.className = `lobby-chat-msg${isSelf ? ' is-self' : ''}${isSpec ? ' is-spectator' : ''}`;

    const senderSpan = document.createElement('span');
    senderSpan.className = 'lobby-chat-sender';
    senderSpan.textContent = isSelf ? `${displayLabel} (You):` : `${displayLabel}:`;

    const textSpan = document.createElement('span');
    textSpan.className = 'lobby-chat-text';
    textSpan.textContent = msg.text || '';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'lobby-chat-time';
    timeSpan.textContent = msg.timestamp || '';

    item.appendChild(senderSpan);
    item.appendChild(textSpan);
    item.appendChild(timeSpan);

    listEl.appendChild(item);
    listEl.scrollTop = listEl.scrollHeight;
  }

  function handleStageChatMessage(msg) {
    if (!msg || !msg.stage) return;
    // Strict room isolation on client as well as server
    const currentRoom = (typeof OnlineClient !== 'undefined' && OnlineClient.getRoomCode) ? OnlineClient.getRoomCode() : null;
    if (currentRoom && msg.room_code && msg.room_code !== currentRoom) return;

    const mySenderId = (typeof OnlineClient !== 'undefined' && OnlineClient.getCurrentSenderId)
      ? OnlineClient.getCurrentSenderId()
      : null;

    if (msg.stage === 'pre_match') {
      if (typeof MenuUI !== 'undefined' && MenuUI.addLobbyChatMessage) {
        MenuUI.addLobbyChatMessage(msg, mySenderId);
      }
      return;
    }

    if (msg.stage === 'in_match') {
      if (msg.id && _seenInMatchMsgIds.has(msg.id)) return;
      if (msg.id) _seenInMatchMsgIds.add(msg.id);
      const listEl = document.getElementById('ingame-chat-messages');
      _appendChatItem(listEl, msg, mySenderId);
      const drawer = document.getElementById('ingame-chat-drawer');
      if (drawer && drawer.classList.contains('hidden')) {
        _unreadInMatchChatCount++;
        _updateInMatchChatBadge();
      }
      return;
    }

    if (msg.stage === 'post_match') {
      if (msg.id && _seenPostMatchMsgIds.has(msg.id)) return;
      if (msg.id) _seenPostMatchMsgIds.add(msg.id);
      const listEl = document.getElementById('post-match-chat-messages');
      _appendChatItem(listEl, msg, mySenderId);
    }
  }

  function _bindStageChatAndPostMatchControls() {
    const closeIngameChatBtn = document.getElementById('btn-close-ingame-chat');
    if (closeIngameChatBtn) {
      closeIngameChatBtn.addEventListener('click', () => closeInMatchChat());
    }

    const ingameForm = document.getElementById('ingame-chat-form');
    const ingameInput = document.getElementById('ingame-chat-input');
    if (ingameForm && ingameInput) {
      ingameForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = ingameInput.value.trim();
        if (!text) return;
        OnlineClient.sendStageChatMessage('in_match', text, (res) => {
          if (res && !res.success) {
            showToast(res.message || 'Failed to send message', 'error', 2000);
          }
        });
        ingameInput.value = '';
      });
    }

    const postForm = document.getElementById('post-match-chat-form');
    const postInput = document.getElementById('post-match-chat-input');
    if (postForm && postInput) {
      postForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = postInput.value.trim();
        if (!text) return;
        OnlineClient.sendStageChatMessage('post_match', text, (res) => {
          if (res && !res.success) {
            showToast(res.message || 'Failed to send message', 'error', 2000);
          }
        });
        postInput.value = '';
      });
    }

    const toggleReadyBtn = document.getElementById('btn-toggle-ready');
    if (toggleReadyBtn) {
      toggleReadyBtn.addEventListener('click', () => {
        if (_isOffline || OnlineClient.isSpectator()) return;
        Sound.click();
        const nextReady = !_localPostMatchReady;
        toggleReadyBtn.disabled = true;
        OnlineClient.setPostMatchReady(nextReady, (res) => {
          toggleReadyBtn.disabled = false;
          if (res && res.success && res.post_match_status) {
            handlePostMatchStatus(res.post_match_status);
          } else if (res && !res.success) {
            showToast(res.message || 'Could not update Ready status', 'error', 2500);
          }
        });
      });
    }

    const createNewRoomBtn = document.getElementById('btn-create-new-room');
    if (createNewRoomBtn) {
      createNewRoomBtn.addEventListener('click', () => {
        Sound.click();
        handleCreateNewRoom();
      });
    }
  }

  function init() {
    Screens.go('screen-menu');
    MenuUI.init();
    _bindStageChatAndPostMatchControls();
    if (!_backNavBound && typeof window !== 'undefined') {
      window.addEventListener('popstate', _handlePopState);
      _backNavBound = true;
    }
    console.log('[KAZHUDHAI CLUB] Integrated Stages 1–5 Active.');

    // Check saved active session during startup for seamless Android APK / browser reload recovery
    _checkActiveSessionOnStartup();
  }

  function _checkActiveSessionOnStartup() {
    if (typeof Storage === 'undefined' || !Storage.getActiveSession) return;
    const session = Storage.getActiveSession();
    if (!session || !session.token || !session.roomCode) return;

    console.log('[App] Persistent active session detected on startup for room:', session.roomCode);

    // Initialize Socket.IO connection only when a valid saved session exists
    if (typeof OnlineClient !== 'undefined' && OnlineClient.initConnection) {
      showToast(`Reconnecting to room ${session.roomCode}…`, 'info', 3000);
      OnlineClient.initConnection();
    }
  }

  // Safe stubs for activity drawer (removed from game UI per user request)
  function _bindActivityDrawer() {}
  function toggleActivityDrawer() {}
  function openActivityDrawer() {}
  function closeActivityDrawer() {}
  function _updateActivityBadge() {}

  function _renderSingleActivity(act, prepend = true) {
    const list = document.getElementById('activity-log-list');
    if (!list) return;

    list.querySelector('.empty-activity-hint')?.remove();

    const item = document.createElement('div');
    item.className = 'activity-item';
    item.innerHTML = `
      <span class="activity-item-icon">${act.icon || 'ℹ️'}</span>
      <div class="activity-item-content">
        <span class="activity-item-msg">${act.message}</span>
        <span class="activity-item-time">${act.timestamp || ''}</span>
      </div>
    `;

    if (prepend) {
      list.insertBefore(item, list.firstChild);
    } else {
      list.appendChild(item);
    }

    // Also update waiting room lobby activity feed if present
    const waitingList = document.getElementById('waiting-activity-list');
    if (waitingList) {
      waitingList.querySelector('.empty-activity-hint')?.remove();
      const waitingItem = document.createElement('div');
      waitingItem.className = 'waiting-activity-item';
      waitingItem.innerHTML = `
        <span>${act.icon || 'ℹ️'}</span>
        <span>${act.message}</span>
        <span class="activity-time">${act.timestamp || ''}</span>
      `;
      waitingList.insertBefore(waitingItem, waitingList.firstChild);
    }

    const drawer = document.getElementById('activity-drawer');
    if (drawer && drawer.classList.contains('hidden')) {
      _unreadActivityCount++;
      _updateActivityBadge();
    }
  }

  function _renderActivityLog(logList) {
    const list = document.getElementById('activity-log-list');
    if (!list) return;
    list.innerHTML = '';
    if (!logList || logList.length === 0) {
      list.innerHTML = '<div class="empty-activity-hint">No activity recorded yet</div>';
      return;
    }
    logList.forEach(act => {
      _renderSingleActivity(act, false);
    });
  }

  function _clearAiTimeout() {
    if (_aiStepTimeout) {
      clearTimeout(_aiStepTimeout);
      _aiStepTimeout = null;
    }
    _isStepping = false;
  }

  // ─── Offline Game Flow ───

  async function startOfflineGame(config) {
    _clearAiTimeout();
    _currentConfig = config;
    _isOffline     = true;
    _isRoundPaused = false;

    showToast('Shuffling and dealing cards…', 'info', 2000);

    try {
      const state = await OfflineClient.startGame(config);
      GameClient.setState(state);

      Screens.go('screen-game');
      activateGameBackGuard();

      TableUI.init({
        roomCode:   'OFFLINE',
        deckCount:  config.deckCount,
        playerName: config.playerName,
      });
      if (typeof TableUI.setSpectatorMode === 'function') {
        TableUI.setSpectatorMode(false);
      }
      if (typeof TableUI.setOnlineControlsVisible === 'function') {
        TableUI.setOnlineControlsVisible(false, false);
      }
      closeInMatchChat();

      _renderActivityLog([
        {
          id: 'init_start',
          type: 'start',
          message: `Offline game started (${config.playerCount} players, ${config.deckCount} deck).`,
          icon: '🚀',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        }
      ]);

      _renderState(state);

      // If Round 1 starter is an AI (holds A♠), trigger the first AI move
      if (!state.is_my_turn && state.status === 'playing') {
        _scheduleNextAiStep(1000);
      }

    } catch (err) {
      console.error('[App] startOfflineGame error:', err);
      showToast('Failed to start game: ' + err.message, 'error');
    }
  }

  async function playCard(cardId) {
    if (!_isOffline && typeof OnlineClient !== 'undefined' && OnlineClient.isSpectator && OnlineClient.isSpectator()) {
      return;
    }
    if (!cardId || !GameClient.isActive()) {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      return;
    }

    const isMyTurn = isCurrentPlayerTurn();
    if (!isMyTurn) {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      return;
    }

    if (!_isOffline) {
      // Online mode: clean up any stale resolution pause and emit to authoritative server
      _isRoundPaused = false;
      _clearRoundTimer();
      OnlineClient.playCard(cardId);
      return;
    }

    if (_isRoundPaused) {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      return;
    }

    // Offline mode
    try {
      const response = await OfflineClient.playCard(cardId);
      if (!response || !response.state) return;

      const newState = response.state;
      GameClient.setState(newState);

      // Render the card human just played
      if (response.action && response.action.card) {
        TableUI.addPlayedCard(response.action.card, response.action.player_name || 'You', response.action.is_attack);
      }

      // Check if round finished
      if (response.round_completed && response.last_round_result) {
        _handleRoundResolution(response.last_round_result, newState);
      } else {
        _renderState(newState);
        if (!newState.is_my_turn && newState.status === 'playing') {
          _scheduleNextAiStep(900);
        }
      }

    } catch (err) {
      console.error('[App] playCard error:', err);
      showToast(err.message || 'Illegal card play', 'error');
    }
  }

  function _scheduleNextAiStep(delayMs = 850) {
    _clearAiTimeout();
    if (_isRoundPaused) return;

    const state = GameClient.getState();
    if (!state || state.status !== 'playing' || state.is_my_turn) return;

    _isStepping = true;
    _aiStepTimeout = setTimeout(async () => {
      _isStepping = false;
      await _executeAiStep();
    }, delayMs);
  }

  async function _executeAiStep() {
    if (!GameClient.isActive() || _isRoundPaused) return;
    const state = GameClient.getState();
    if (!state || state.status !== 'playing' || state.is_my_turn) return;

    try {
      const response = await OfflineClient.step();
      if (!response) return;

      if (response.status === 'finished') {
        GameClient.setState(response.state);
        _renderState(response.state);
        return;
      }

      if (response.action_type === 'waiting_human') {
        _renderState(response.state);
        return;
      }

      const newState = response.state;
      GameClient.setState(newState);

      // Render the card played by the AI
      if (response.action && response.action.card) {
        TableUI.addPlayedCard(response.action.card, response.action.player_name, response.action.is_attack);
        if (response.action.is_attack) {
          TableUI.showAttackBanner(response.action.player_name);
        }
      }

      // Check if round completed
      if (response.round_completed && response.last_round_result) {
        _handleRoundResolution(response.last_round_result, newState);
      } else {
        _renderState(newState);
        if (!newState.is_my_turn && newState.status === 'playing') {
          _scheduleNextAiStep(850);
        }
      }

    } catch (err) {
      console.error('[App] AI step error:', err);
    }
  }

  function _handleRoundResolution(roundResult, nextState) {
    _isRoundPaused = true;
    _clearAiTimeout();

    // Show attack banner if attack
    if (roundResult.is_attack) {
      TableUI.showAttackBanner(roundResult.attacker_name || 'Player');
      Sound.attack();
      Animations.screenShake();
      Animations.flashAttack();
      showToast(`ATTACK by ${roundResult.attacker_name}! ${roundResult.winner_name} takes all cards!`, 'attack', 3000);
    } else {
      TableUI.hideAttackBanner();
      showToast(`${roundResult.winner_name} won the round with ${CardRenderer.cardLabel(roundResult.winning_card)}`, 'success', 2500);
    }

    // Flash winner avatar
    if (roundResult.winner_id === 'human') {
      TableUI.flashSelfAvatar(roundResult.is_attack ? 'rgba(255,80,80,0.8)' : 'rgba(80,255,80,0.8)');
    } else {
      TableUI.flashOpponentAvatar(roundResult.winner_id, roundResult.is_attack ? 'rgba(255,80,80,0.8)' : 'rgba(80,255,80,0.8)');
    }

    // Notify if any players finished and became safe
    if (roundResult.eliminated_players && roundResult.eliminated_players.length > 0) {
      roundResult.eliminated_players.forEach(name => {
        Sound.playerFinish();
        showToast(`🎉 ${name} played their last card and is SAFE!`, 'success', 3500);
      });
    }

    // Pause briefly so the player sees the winning card and attack outcome
    _clearRoundTimer();
    _roundResolutionTimer = setTimeout(() => {
      _roundResolutionTimer = null;
      if (!GameClient.isActive()) return;

      // Collect played cards
      TableUI.clearPlayedCards(true);
      TableUI.hideAttackBanner();

      _isRoundPaused = false;
      _renderState(nextState);

      if (nextState.status === 'finished') {
        setTimeout(() => {
          if (GameClient.isActive()) _showResults(nextState);
        }, 1200);
      } else if (!nextState.is_my_turn) {
        _scheduleNextAiStep(1000);
      }
    }, 1800);
  }

  function _renderState(state) {
    if (!state) return;

    // Use authoritative player list from server (strictly room joining order)
    const myId = _isOffline ? 'human' : OnlineClient.getPlayerId();
    if (state.players) {
      const me = state.players.find(p => p.id === myId);
      if (me) {
        state.player_name = me.name;
        TableUI.updatePlayerStatus(myId, me.connection_status || 'connected');
      }
    }

    // Always render players in strictly consistent server-authoritative order:
    TableUI.renderPlayers(state.players || [], myId);

    // Authoritative turn calculation comparing current_player_id to local player ID
    const isMyTurn = (state.current_player_id && myId)
      ? (state.current_player_id === myId)
      : !!state.is_my_turn;
    state.is_my_turn = isMyTurn;

    const currentOpp = (state.players || []).find(o => o.id === state.current_player_id);
    const currentName = isMyTurn ? (state.player_name || 'You') : (currentOpp ? currentOpp.name : 'Opponent');

    TableUI.setTurn(isMyTurn ? 'Your' : `${currentName}'s`, isMyTurn);

    // Update synchronized turn countdown timer (30s)
    if (typeof TableUI.updateTurnTimer === 'function') {
      TableUI.updateTurnTimer(state.turn_deadline, state.turn_duration || 30);
    }

    if (isMyTurn) {
      if (state.legal_suit) {
        TableUI.setStatus(`Your turn! Follow ${CardRenderer.suitSymbol(state.legal_suit)} or Attack!`);
      } else {
        TableUI.setStatus('Your turn! Lead the round with any card.');
      }
    } else {
      TableUI.setStatus(`Waiting for ${currentName} to play…`);
    }

    // Common pile & deck count HUD
    TableUI.updateCommonPile(state.common_pile_count || 0);
    if (state.deck_count && typeof TableUI.updateDeckCount === 'function') {
      TableUI.updateDeckCount(state.deck_count);
    }

    // Synchronize played cards on the table
    // When not in mid-resolution pause, strictly show cards for the active round:
    if (!_isRoundPaused && typeof TableUI.syncPlayedCards === 'function') {
      TableUI.syncPlayedCards(state.played_cards || []);
    }

    // Preserve attack banner if active round has attack
    if (state.is_attack && state.attacker_name) {
      TableUI.showAttackBanner(state.attacker_name);
    } else if (!state.is_attack && !_isRoundPaused) {
      TableUI.hideAttackBanner();
    }

    // Human hand - always pass the authoritative isMyTurn
    TableUI.renderHand(
      state.my_hand || [],
      state.legal_suit || null,
      isMyTurn
    );

    // Check for game end
    if (state.status === 'finished') {
      setTimeout(() => {
        if (GameClient.isActive()) _showResults(state);
      }, 1400);
    }
  }

  function _showResults(state) {
    _clearAiTimeout();
    _clearRoundTimer();
    if (typeof TableUI !== 'undefined' && TableUI.updateTurnTimer) {
      TableUI.updateTurnTimer(null);
    }
    if (typeof VoiceClient !== 'undefined' && VoiceClient.leaveVoice) {
      VoiceClient.leaveVoice();
    }
    if (typeof MenuUI !== 'undefined' && typeof MenuUI.hideModal === 'function') {
      MAIN_MENU_MODALS.forEach(id => MenuUI.hideModal(id, { fromPopState: true }));
    }
    if (typeof TableUI !== 'undefined' && TableUI.hideExitConfirm) {
      TableUI.hideExitConfirm();
    }
    // Stage 3: Independent post-match chat starts completely fresh
    closeInMatchChat();
    _clearStageChatUI('in_match');
    _clearStageChatUI('post_match');
    _localPostMatchReady = false;

    Screens.go('screen-results');
    _releaseGameBackGuard();

    const kazhudhaiName = document.getElementById('kazhudhai-name');
    const rankings      = document.getElementById('results-rankings');

    kazhudhaiName.textContent = state.kazhudhai_name || 'Unknown';
    rankings.innerHTML = '';

    (state.rankings || []).forEach((player, i) => {
      const row = document.createElement('div');
      row.className = 'rank-row-item';
      const isKazhudhai = player.is_kazhudhai;

      const posSpan = document.createElement('span');
      posSpan.className = 'rank-position';
      posSpan.textContent = String(i + 1);

      const nameSpan = document.createElement('span');
      nameSpan.className = 'rank-name';
      nameSpan.textContent = player.name || 'Player';

      const badgeSpan = document.createElement('span');
      badgeSpan.className = `rank-badge ${isKazhudhai ? 'kazhudhai' : 'safe'}`;
      badgeSpan.textContent = isKazhudhai ? '👑 KAZHUDHAI' : '✅ Safe';

      row.appendChild(posSpan);
      row.appendChild(nameSpan);
      row.appendChild(badgeSpan);
      rankings.appendChild(row);
    });

    Sound.kazhudhai();
    Animations.confettiCelebration();

    const postPanel       = document.getElementById('post-match-online-panel');
    const postChatBox     = document.getElementById('post-match-chat-box');
    const playAgainBtn    = document.getElementById('btn-play-again');
    const createNewBtn    = document.getElementById('btn-create-new-room');
    const toggleReadyBtn  = document.getElementById('btn-toggle-ready');
    const mainMenuBtn     = document.getElementById('btn-main-menu');

    if (_isOffline) {
      if (postPanel) postPanel.classList.add('hidden');
      if (postChatBox) postChatBox.classList.add('hidden');
      if (createNewBtn) createNewBtn.classList.add('hidden');
      if (playAgainBtn) {
        playAgainBtn.classList.remove('hidden');
        playAgainBtn.disabled = false;
        playAgainBtn.onclick = () => startOfflineGame(_currentConfig);
      }
    } else {
      const isSpec = !!(typeof OnlineClient !== 'undefined' && OnlineClient.isSpectator && OnlineClient.isSpectator());
      if (postPanel) postPanel.classList.remove('hidden');
      if (postChatBox) postChatBox.classList.remove('hidden');
      if (createNewBtn) {
        // Stage 2.3: Create New Room is ALWAYS available and enabled
        createNewBtn.classList.remove('hidden');
        createNewBtn.disabled = false;
      }
      if (toggleReadyBtn) {
        toggleReadyBtn.classList.toggle('hidden', isSpec);
        toggleReadyBtn.dataset.ready = 'false';
        toggleReadyBtn.textContent = '⏳ Not Ready — Click to Ready Up';
        toggleReadyBtn.classList.remove('is-ready');
      }
      if (playAgainBtn) {
        if (isSpec) {
          playAgainBtn.classList.add('hidden');
          playAgainBtn.disabled = true;
          playAgainBtn.onclick = null;
        } else {
          playAgainBtn.classList.remove('hidden');
          playAgainBtn.disabled = true;
          playAgainBtn.onclick = () => {
            if (playAgainBtn.disabled) return;
            Sound.click();
            OnlineClient.playAgain();
          };
        }
      }

      const initialStatus = state.post_match_status || (typeof OnlineClient !== 'undefined' && OnlineClient.getPostMatchStatus ? OnlineClient.getPostMatchStatus() : null);
      if (initialStatus) {
        handlePostMatchStatus(initialStatus);
      }
    }

    if (mainMenuBtn) {
      mainMenuBtn.onclick = exitToMenu;
    }
  }

  /**
   * Stage 2: Live update post-match Ready / Not Ready status and Play Again button state.
   */
  function handlePostMatchStatus(status) {
    if (!status) return;
    const isSpec = !!(typeof OnlineClient !== 'undefined' && OnlineClient.isSpectator && OnlineClient.isSpectator());
    const myId = (typeof OnlineClient !== 'undefined' && OnlineClient.getPlayerId) ? OnlineClient.getPlayerId() : null;

    const summaryEl = document.getElementById('post-match-ready-summary');
    if (summaryEl) {
      summaryEl.textContent = `${status.ready_count || 0} / ${status.total_players || 0} Ready`;
    }

    const listEl = document.getElementById('post-match-ready-list');
    if (listEl && Array.isArray(status.players)) {
      listEl.innerHTML = '';
      status.players.forEach(p => {
        const row = document.createElement('div');
        row.className = `post-match-ready-row${p.ready ? ' is-ready' : ''}${!p.present ? ' is-left' : ''}`;

        const nameWrap = document.createElement('span');
        nameWrap.className = 'post-match-player-name';
        const dot = document.createElement('span');
        dot.className = `player-status-dot status-${p.connected ? 'connected' : (p.present ? 'disconnected' : 'left')}`;
        const nameText = document.createElement('span');
        nameText.textContent = (myId && p.id === myId) ? `${p.name} (You)` : p.name;
        nameWrap.appendChild(dot);
        nameWrap.appendChild(nameText);

        const stateBadge = document.createElement('span');
        stateBadge.className = `ready-status-badge ${p.ready ? 'badge-ready' : (!p.present ? 'badge-left' : (!p.connected ? 'badge-disconnected' : 'badge-not-ready'))}`;
        stateBadge.textContent = p.ready ? '✅ Ready' : (!p.present ? '🚪 Left' : (!p.connected ? '🔴 Disconnected' : '⏳ Not Ready'));

        row.appendChild(nameWrap);
        row.appendChild(stateBadge);
        listEl.appendChild(row);

        if (!isSpec && myId && p.id === myId) {
          _localPostMatchReady = !!p.ready;
        }
      });
    }

    const toggleBtn = document.getElementById('btn-toggle-ready');
    if (toggleBtn && !isSpec) {
      toggleBtn.dataset.ready = _localPostMatchReady ? 'true' : 'false';
      toggleBtn.classList.toggle('is-ready', _localPostMatchReady);
      toggleBtn.textContent = _localPostMatchReady
        ? '✅ Ready — Click to Switch to Not Ready'
        : '⏳ Not Ready — Click to Ready Up';
    }

    const reasonEl = document.getElementById('post-match-reason');
    if (reasonEl) {
      reasonEl.textContent = isSpec
        ? '👁️ Spectating post-match lobby. You can chat or create a new room.'
        : (status.reason || '');
    }

    const playAgainBtn = document.getElementById('btn-play-again');
    if (playAgainBtn && !_isOffline && !isSpec) {
      playAgainBtn.disabled = !status.can_play_again;
    }

    // Create New Room is ALWAYS enabled regardless of readiness or departures
    const createNewBtn = document.getElementById('btn-create-new-room');
    if (createNewBtn && !_isOffline) {
      createNewBtn.disabled = false;
    }
  }

  /**
   * Stage 2.3: Cleanly leave old room, clear old session references,
   * and open the exact existing Main Menu -> Play Online -> Create Private Room workflow.
   */
  function handleCreateNewRoom() {
    _clearAiTimeout();
    _clearRoundTimer();
    _isRoundPaused = false;
    _pendingNextState = null;
    _localPostMatchReady = false;
    closeInMatchChat();
    _clearStageChatUI('in_match');
    _clearStageChatUI('post_match');

    if (typeof TableUI !== 'undefined' && TableUI.updateTurnTimer) {
      TableUI.updateTurnTimer(null);
    }
    if (typeof TableUI !== 'undefined' && TableUI.setSpectatorMode) {
      TableUI.setSpectatorMode(false);
    }
    if (typeof VoiceClient !== 'undefined' && VoiceClient.leaveVoice) {
      VoiceClient.leaveVoice();
    }

    // Cleanly leave the old room without requiring permission from other players
    OnlineClient.leaveRoom('left');
    OfflineClient.reset();
    GameClient.reset();
    _releaseGameBackGuard();

    Screens.go('screen-menu');
    if (typeof MenuUI !== 'undefined' && MenuUI.openCreatePrivateRoomWorkflow) {
      MenuUI.openCreatePrivateRoomWorkflow();
    }
  }

  // ─── Online Game & Spectator Flow ───

  function createOnlineRoom(config, callback) {
    _isOffline = false;
    OnlineClient.createRoom(config, callback);
  }

  function joinOnlineRoom(config, callback) {
    _isOffline = false;
    OnlineClient.joinRoom(config, callback);
  }

  function joinAsSpectator(config, callback) {
    _isOffline = false;
    OnlineClient.joinAsSpectator(config, callback);
  }

  function handleSpectatorsUpdated(summary) {
    if (!summary) return;
    if (typeof TableUI !== 'undefined' && TableUI.updateSpectatorList) {
      TableUI.updateSpectatorList(summary.spectators || [], summary.spectator_count || 0);
    }
  }

  /**
   * Stage 4: Render server-sanitized live spectator table state.
   */
  function renderSpectatorState(state) {
    if (!state) return;
    _isOffline = false;
    GameClient.setState(state);

    if (typeof TableUI.setSpectatorMode === 'function') {
      TableUI.setSpectatorMode(true);
    }
    if (typeof TableUI.setOnlineControlsVisible === 'function') {
      TableUI.setOnlineControlsVisible(true, true);
    }
    if (state.deck_count && typeof TableUI.updateDeckCount === 'function') {
      TableUI.updateDeckCount(state.deck_count);
    }
    if (typeof state.spectator_count === 'number' && typeof TableUI.updateSpectatorList === 'function') {
      TableUI.updateSpectatorList(state.spectators || [], state.spectator_count);
    }

    if (typeof TableUI.renderSpectatorPlayers === 'function') {
      TableUI.renderSpectatorPlayers(state.players || []);
    }

    const currentPlayer = (state.players || []).find(p => p.id === state.current_player_id);
    const currentName = currentPlayer ? currentPlayer.name : 'Player';
    TableUI.setTurn(`${currentName}'s`, false);
    TableUI.setStatus(`👁️ Spectating · ${currentName}'s turn`);

    if (typeof TableUI.updateTurnTimer === 'function') {
      TableUI.updateTurnTimer(state.turn_deadline, state.turn_duration || 30);
    }

    TableUI.updateCommonPile(state.common_pile_count || 0);

    if (!_isRoundPaused && typeof TableUI.syncPlayedCards === 'function') {
      TableUI.syncPlayedCards(state.played_cards || []);
    }

    if (state.is_attack && state.attacker_name) {
      TableUI.showAttackBanner(state.attacker_name);
    } else if (!state.is_attack && !_isRoundPaused) {
      TableUI.hideAttackBanner();
    }
  }

  function renderOnlineState(state) {
    _isOffline = false;
    GameClient.setState(state);
    if (state.activity_log) {
      _renderActivityLog(state.activity_log);
    }
    if (typeof state.spectator_count === 'number' && typeof TableUI.updateSpectatorList === 'function') {
      TableUI.updateSpectatorList(state.spectators || [], state.spectator_count);
    }
    if (typeof TableUI.setOnlineControlsVisible === 'function') {
      TableUI.setOnlineControlsVisible(true, false);
    }

    // If currently paused in round resolution animation, do NOT destroy the timer!
    // Store the state so it is cleanly rendered once the resolution finishes.
    if (_isRoundPaused) {
      _pendingNextState = state;
      return;
    }

    const myTurn = isCurrentPlayerTurn();
    if (myTurn) {
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
    }
    _renderState(state);
    if (state.status === 'playing' && Screens.current() === 'screen-game') {
      activateGameBackGuard();
    }
    if (OnlineClient.getPlayerId()) {
      TableUI.updatePlayerStatus(OnlineClient.getPlayerId(), 'connected');
    }
  }

  function handlePlayerDeparture(data) {
    showToast(data.message, 'departure', data.duration || 5000);
    TableUI.updatePlayerStatus(data.player_id, data.status);
  }

  function handlePlayerStatusChange(data) {
    TableUI.updatePlayerStatus(data.player_id, data.status);
    const waitingCard = document.querySelector(`.waiting-player-card[data-player-id="${data.player_id}"]`);
    if (waitingCard) {
      const dot = waitingCard.querySelector('.player-status-dot');
      if (dot) dot.className = `player-status-dot status-${data.status}`;
      const badge = waitingCard.querySelector('.waiting-player-badge');
      if (badge && !badge.textContent.includes('Host')) {
        badge.className = `waiting-player-badge status-${data.status}`;
        badge.textContent = data.status === 'connected' ? 'Ready' :
                            data.status === 'reconnecting' ? 'Reconnecting' : 'Left';
      }
    }
  }

  function handleActivityLogged(act) {
    _renderSingleActivity(act, true);
  }

  function getHumanPlayerId() {
    return _isOffline ? 'human' : OnlineClient.getPlayerId();
  }

  function handleOnlineCardPlayed(action) {
    if (!action || !action.card) return;
    const myId = OnlineClient.getPlayerId();

    // If played by an opponent, display their card onto the table
    if (action.player_id !== myId) {
      TableUI.addPlayedCard(action.card, action.player_name, action.is_attack);
      if (action.is_attack) {
        TableUI.showAttackBanner(action.player_name);
      }
    } else {
      // Local card play was already selected, make sure sound plays
      Sound.cardPlay();
    }
  }

  function handleOnlineRoundResolution(roundResult) {
    _clearRoundTimer();
    _isRoundPaused = true;

    try {
      if (roundResult.is_attack) {
        TableUI.showAttackBanner(roundResult.attacker_name || 'Player');
        Sound.attack();
        Animations.screenShake();
        Animations.flashAttack();
        showToast(`ATTACK by ${roundResult.attacker_name || 'Player'}! ${roundResult.winner_name || 'Player'} takes all cards!`, 'attack', 3000);
      } else {
        TableUI.hideAttackBanner();
        const winningCardLabel = roundResult.winning_card ? CardRenderer.cardLabel(roundResult.winning_card) : 'winning card';
        showToast(`${roundResult.winner_name || 'Player'} won the round with ${winningCardLabel}`, 'success', 2500);
      }

      const myId = OnlineClient.getPlayerId();
      if (roundResult.winner_id === myId) {
        TableUI.flashSelfAvatar(roundResult.is_attack ? 'rgba(255,80,80,0.8)' : 'rgba(80,255,80,0.8)');
      } else if (roundResult.winner_id) {
        TableUI.flashOpponentAvatar(roundResult.winner_id, roundResult.is_attack ? 'rgba(255,80,80,0.8)' : 'rgba(80,255,80,0.8)');
      }

      if (roundResult.eliminated_players && roundResult.eliminated_players.length > 0) {
        roundResult.eliminated_players.forEach(name => {
          Sound.playerFinish();
          showToast(`🎉 ${name} played their last card and is SAFE!`, 'success', 3500);
        });
      }
    } catch (err) {
      console.warn('[App] handleOnlineRoundResolution animation error:', err);
    }

    _roundResolutionTimer = setTimeout(() => {
      try {
        TableUI.clearPlayedCards(true);
        TableUI.hideAttackBanner();
      } catch (e) {
        console.warn('[App] clearPlayedCards error:', e);
      }
      _isRoundPaused = false;
      _roundResolutionTimer = null;
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
      const state = _pendingNextState || GameClient.getState();
      _pendingNextState = null;
      if (state) _renderState(state);
    }, 1800);
  }

  function showOnlineResults(data) {
    _showResults(data);
  }

  // ─── General Controls ───

  function exitToMenu() {
    _clearAiTimeout();
    _clearRoundTimer();
    _isRoundPaused = false;
    _pendingNextState = null;
    if (typeof TableUI !== 'undefined' && TableUI.updateTurnTimer) {
      TableUI.updateTurnTimer(null);
    }
    if (typeof VoiceClient !== 'undefined' && VoiceClient.leaveVoice) {
      VoiceClient.leaveVoice();
    }
    if (typeof MenuUI !== 'undefined' && typeof MenuUI.hideModal === 'function') {
      MAIN_MENU_MODALS.forEach(id => MenuUI.hideModal(id, { fromPopState: true }));
    }
    if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
      TableUI.resetPlayInFlight();
    }
    if (typeof TableUI !== 'undefined' && TableUI.hideExitConfirm) {
      TableUI.hideExitConfirm();
    }
    if (typeof TableUI !== 'undefined' && TableUI.closeInGameMenu) {
      TableUI.closeInGameMenu();
    }
    if (typeof TableUI !== 'undefined' && TableUI.setSpectatorMode) {
      TableUI.setSpectatorMode(false);
    }
    if (typeof TableUI !== 'undefined' && TableUI.setOnlineControlsVisible) {
      TableUI.setOnlineControlsVisible(false, false);
    }
    closeInMatchChat();
    _clearStageChatUI('in_match');
    _clearStageChatUI('post_match');
    _localPostMatchReady = false;
    closeActivityDrawer();
    _unreadActivityCount = 0;
    _updateActivityBadge();
    OfflineClient.reset();
    OnlineClient.disconnect();
    GameClient.reset();
    Screens.go('screen-menu');
    _releaseGameBackGuard();
  }

  function restartGame() {
    if (_isOffline && _currentConfig) {
      startOfflineGame(_currentConfig);
    } else if (!_isOffline) {
      OnlineClient.restartGame();
    }
  }

  function sendReaction(emoji) {
    if (!emoji) return;
    if (!_isOffline) {
      if (typeof OnlineClient !== 'undefined' && OnlineClient.isSpectator && OnlineClient.isSpectator()) return;
      OnlineClient.sendReaction(emoji);
    } else {
      TableUI.showPlayerReaction('human', emoji);
    }
  }

  function handlePlayerReaction(data) {
    if (data && data.player_id && data.emoji) {
      TableUI.showPlayerReaction(data.player_id, data.emoji);
    }
  }

  return {
    init,
    startOfflineGame,
    playCard,
    isCurrentPlayerTurn,
    createOnlineRoom,
    joinOnlineRoom,
    joinAsSpectator,
    renderOnlineState,
    renderSpectatorState,
    handleSpectatorsUpdated,
    handlePostMatchStatus,
    handleCreateNewRoom,
    handleStageChatMessage,
    clearStageChatsOnMatchStart,
    toggleInMatchChat,
    closeInMatchChat,
    handleOnlineCardPlayed,
    handleOnlineRoundResolution,
    handlePlayerDeparture,
    handlePlayerStatusChange,
    handleActivityLogged,
    sendReaction,
    handlePlayerReaction,
    getHumanPlayerId,
    toggleActivityDrawer,
    openActivityDrawer,
    closeActivityDrawer,
    showOnlineResults,
    isActivelyPlayingGame,
    activateGameBackGuard,
    onModalOpened,
    onModalClosed,
    exitToMenu,
    restartGame,
  };
})();

// ── Bootstrap ──
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
