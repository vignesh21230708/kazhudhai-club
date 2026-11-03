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
  let _unreadActivityCount = 0;

  function _clearRoundTimer() {
    if (_roundResolutionTimer) {
      clearTimeout(_roundResolutionTimer);
      _roundResolutionTimer = null;
    }
  }

  function init() {
    Screens.go('screen-menu');
    MenuUI.init();
    _bindActivityDrawer();
    console.log('[KAZHUDHAI CLUB] Stage 3 Active: Core round gameplay online.');
  }

  function _bindActivityDrawer() {
    // 🕘 Table History Button (Top-Right corner of table)
    const tableHistoryBtn = document.getElementById('btn-table-history');
    if (tableHistoryBtn) {
      tableHistoryBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        Sound.click();
        toggleActivityDrawer();
      });
    }

    // HUD Bar History Button
    const toggleBtn = document.getElementById('btn-toggle-activity');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        Sound.click();
        toggleActivityDrawer();
      });
    }

    // Close button (×)
    const closeBtn = document.getElementById('btn-close-activity');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        Sound.click();
        closeActivityDrawer();
      });
    }

    // Backdrop click to close panel
    const backdrop = document.getElementById('activity-backdrop');
    if (backdrop) {
      backdrop.addEventListener('click', () => {
        closeActivityDrawer();
      });
    }

    // Global click outside to close panel
    document.addEventListener('click', (e) => {
      const drawer = document.getElementById('activity-drawer');
      if (!drawer || drawer.classList.contains('hidden')) return;

      const isInside = drawer.contains(e.target);
      const isTrigger = e.target.closest('#btn-table-history') || e.target.closest('#btn-toggle-activity');

      if (!isInside && !isTrigger) {
        closeActivityDrawer();
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeActivityDrawer();
      }
    });
  }

  function toggleActivityDrawer() {
    const drawer = document.getElementById('activity-drawer');
    if (!drawer) return;
    if (drawer.classList.contains('hidden')) {
      openActivityDrawer();
    } else {
      closeActivityDrawer();
    }
  }

  function openActivityDrawer() {
    const drawer = document.getElementById('activity-drawer');
    if (drawer) drawer.classList.remove('hidden');
    const backdrop = document.getElementById('activity-backdrop');
    if (backdrop) backdrop.classList.remove('hidden');
    _unreadActivityCount = 0;
    _updateActivityBadge();
  }

  function closeActivityDrawer() {
    const drawer = document.getElementById('activity-drawer');
    if (drawer) drawer.classList.add('hidden');
    const backdrop = document.getElementById('activity-backdrop');
    if (backdrop) backdrop.classList.add('hidden');
  }

  function _updateActivityBadge() {
    const badges = [
      document.getElementById('activity-badge'),
      document.getElementById('table-history-badge'),
    ];
    badges.forEach(badge => {
      if (!badge) return;
      if (_unreadActivityCount > 0) {
        badge.textContent = _unreadActivityCount > 99 ? '99+' : _unreadActivityCount;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    });
  }

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

      TableUI.init({
        roomCode:   'OFFLINE',
        deckCount:  config.deckCount,
        playerName: config.playerName,
      });

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
    if (!GameClient.isActive() || _isRoundPaused) return;
    const state = GameClient.getState();
    if (!state.is_my_turn) return;

    if (!_isOffline) {
      // Online mode: emit to server
      OnlineClient.playCard(cardId);
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
    setTimeout(() => {
      // Collect played cards
      TableUI.clearPlayedCards(true);
      TableUI.hideAttackBanner();

      _isRoundPaused = false;
      _renderState(nextState);

      if (nextState.status === 'finished') {
        setTimeout(() => _showResults(nextState), 1200);
      } else if (!nextState.is_my_turn) {
        _scheduleNextAiStep(1000);
      }
    }, 1800);
  }

  function _renderState(state) {
    if (!state) return;

    // Normalize opponents list for both offline and online modes
    if (!state.opponents && state.players) {
      const myId = _isOffline ? 'human' : OnlineClient.getPlayerId();
      state.opponents = state.players.filter(p => p.id !== myId);
      const me = state.players.find(p => p.id === myId);
      if (me) {
        state.player_name = me.name;
        TableUI.updatePlayerStatus(myId, me.connection_status || 'connected');
      }
    }

    // Opponents
    TableUI.renderOpponents(state.opponents || []);

    // Turn info
    const isMyTurn = !!state.is_my_turn;
    const currentOpp = (state.opponents || []).find(o => o.id === state.current_player_id);
    const currentName = isMyTurn ? (state.player_name || 'You') : (currentOpp ? currentOpp.name : 'Opponent');

    TableUI.setTurn(isMyTurn ? 'Your' : `${currentName}'s`);

    if (isMyTurn) {
      if (state.legal_suit) {
        TableUI.setStatus(`Your turn! Follow ${CardRenderer.suitSymbol(state.legal_suit)} or Attack!`);
      } else {
        TableUI.setStatus('Your turn! Lead the round with any card.');
      }
    } else {
      TableUI.setStatus(`Waiting for ${currentName} to play…`);
    }

    // Common pile
    TableUI.updateCommonPile(state.common_pile_count || 0);

    // Human hand
    TableUI.renderHand(
      state.my_hand || [],
      state.legal_suit || null,
      isMyTurn && !_isRoundPaused
    );

    // Check for game end
    if (state.status === 'finished' && !_isRoundPaused) {
      setTimeout(() => _showResults(state), 1400);
    }
  }

  function _showResults(state) {
    _clearAiTimeout();
    Screens.go('screen-results');

    const kazhudhaiName = document.getElementById('kazhudhai-name');
    const rankings      = document.getElementById('results-rankings');

    kazhudhaiName.textContent = state.kazhudhai_name || 'Unknown';
    rankings.innerHTML = '';

    (state.rankings || []).forEach((player, i) => {
      const row = document.createElement('div');
      row.className = 'rank-row-item';
      const isKazhudhai = player.is_kazhudhai;
      row.innerHTML = `
        <span class="rank-position">${i + 1}</span>
        <span class="rank-name">${player.name}</span>
        <span class="rank-badge ${isKazhudhai ? 'kazhudhai' : 'safe'}">
          ${isKazhudhai ? '👑 KAZHUDHAI' : '✅ Safe'}
        </span>
      `;
      rankings.appendChild(row);
    });

    Sound.kazhudhai();
    Animations.confettiCelebration();

    document.getElementById('btn-play-again').onclick = () => {
      if (_isOffline) {
        startOfflineGame(_currentConfig);
      } else {
        exitToMenu();
      }
    };
    document.getElementById('btn-main-menu').onclick  = exitToMenu;
  }

  // ─── Online Game Flow ───

  function createOnlineRoom(config, callback) {
    _isOffline = false;
    OnlineClient.createRoom(config, callback);
  }

  function joinOnlineRoom(config, callback) {
    _isOffline = false;
    OnlineClient.joinRoom(config, callback);
  }

  function renderOnlineState(state) {
    _isOffline = false;
    GameClient.setState(state);
    if (state.activity_log) {
      _renderActivityLog(state.activity_log);
    }
    // If it's my turn, ensure paused round state and play locks are cleanly released
    if (state.is_my_turn) {
      _clearRoundTimer();
      _isRoundPaused = false;
      if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
        TableUI.resetPlayInFlight();
      }
    }
    _renderState(state);
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
      const state = GameClient.getState();
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
    if (typeof TableUI !== 'undefined' && TableUI.resetPlayInFlight) {
      TableUI.resetPlayInFlight();
    }
    closeActivityDrawer();
    _unreadActivityCount = 0;
    _updateActivityBadge();
    OfflineClient.reset();
    OnlineClient.disconnect();
    GameClient.reset();
    Screens.go('screen-menu');
  }

  function restartGame() {
    if (_isOffline && _currentConfig) {
      startOfflineGame(_currentConfig);
    } else if (!_isOffline) {
      OnlineClient.restartGame();
    }
  }

  return {
    init,
    startOfflineGame,
    playCard,
    createOnlineRoom,
    joinOnlineRoom,
    renderOnlineState,
    handleOnlineCardPlayed,
    handleOnlineRoundResolution,
    handlePlayerDeparture,
    handlePlayerStatusChange,
    handleActivityLogged,
    getHumanPlayerId,
    toggleActivityDrawer,
    openActivityDrawer,
    closeActivityDrawer,
    showOnlineResults,
    exitToMenu,
    restartGame,
  };
})();

// ── Bootstrap ──
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
