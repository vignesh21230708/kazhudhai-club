/**
 * KAZHUDHAI CLUB — storage.js
 * LocalStorage helpers for settings and game history
 */
const Storage = (() => {
  const PREFIX = 'kazhudhai_';

  function get(key, fallback = null) {
    try {
      const val = localStorage.getItem(PREFIX + key);
      return val !== null ? JSON.parse(val) : fallback;
    } catch { return fallback; }
  }

  function set(key, value) {
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch { /* storage full or denied */ }
  }

  function remove(key) {
    try { localStorage.removeItem(PREFIX + key); } catch {}
  }

  // Default settings
  const DEFAULTS = {
    sfx: true,
    music: false,
    animations: true,
    theme: 'green',
    playerName: 'Player',
    lastPlayerCount: 4,
    lastDeckCount: 1,
    lastDifficulty: 'medium',
  };

  function getSettings() {
    return {
      sfx:        get('sfx',        DEFAULTS.sfx),
      music:      get('music',      DEFAULTS.music),
      animations: get('animations', DEFAULTS.animations),
      theme:      get('theme',      DEFAULTS.theme),
    };
  }

  function saveSettings(settings) {
    Object.entries(settings).forEach(([k, v]) => set(k, v));
  }

  function getPlayerName()       { return get('playerName',       DEFAULTS.playerName); }
  function savePlayerName(name)  { set('playerName', name); }
  function getLastPlayerCount()  { return get('lastPlayerCount',  DEFAULTS.lastPlayerCount); }
  function saveLastPlayerCount(n){ set('lastPlayerCount', n); }
  function getLastDeckCount()    { return get('lastDeckCount',    DEFAULTS.lastDeckCount); }
  function saveLastDeckCount(n)  { set('lastDeckCount', n); }
  function getLastDifficulty()   { return get('lastDifficulty',   DEFAULTS.lastDifficulty); }
  function saveLastDifficulty(d) { set('lastDifficulty', d); }

  const SESSION_KEY     = 'active_session';
  const TAB_SESSION_KEY = PREFIX + 'tab_session';
  const TAB_ID_KEY      = PREFIX + 'tab_id';
  const HEARTBEATS_KEY  = 'tab_heartbeats';
  const LIVE_TAB_TTL_MS = 6000;

  // Unique per-tab identifier (persists across same-tab refreshes, distinct per new tab)
  let _tabId = null;
  let _heartbeatTimer = null;

  function _getTabId() {
    if (_tabId) return _tabId;
    try {
      let existing = sessionStorage.getItem(TAB_ID_KEY);
      if (!existing) {
        existing = 'tab_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
        sessionStorage.setItem(TAB_ID_KEY, existing);
      }
      _tabId = existing;
    } catch {
      _tabId = 'tab_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
    }
    return _tabId;
  }

  function _readHeartbeats() {
    const map = get(HEARTBEATS_KEY, {});
    return (map && typeof map === 'object') ? map : {};
  }

  function _touchTabHeartbeat() {
    const tid = _getTabId();
    const now = Date.now();
    const map = _readHeartbeats();
    // Prune expired entries older than 5 minutes
    Object.keys(map).forEach((k) => {
      if (now - map[k] > 300000) delete map[k];
    });
    map[tid] = now;
    set(HEARTBEATS_KEY, map);
  }

  function _clearTabHeartbeat() {
    const tid = _getTabId();
    const map = _readHeartbeats();
    if (tid in map) {
      delete map[tid];
      set(HEARTBEATS_KEY, map);
    }
  }

  function _isOtherTabAlive(ownerTabId) {
    if (!ownerTabId) return false;
    const tid = _getTabId();
    if (ownerTabId === tid) return false;
    const map = _readHeartbeats();
    const lastBeat = map[ownerTabId];
    return typeof lastBeat === 'number' && (Date.now() - lastBeat) < LIVE_TAB_TTL_MS;
  }

  function _startHeartbeat() {
    _touchTabHeartbeat();
    if (!_heartbeatTimer && typeof setInterval === 'function') {
      _heartbeatTimer = setInterval(() => {
        if (_getTabSessionRaw()) {
          _touchTabHeartbeat();
        } else {
          _stopHeartbeat();
        }
      }, 2000);
    }
  }

  function _stopHeartbeat() {
    if (_heartbeatTimer) {
      clearInterval(_heartbeatTimer);
      _heartbeatTimer = null;
    }
    _clearTabHeartbeat();
  }

  function _getTabSessionRaw() {
    try {
      const raw = sessionStorage.getItem(TAB_SESSION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || !parsed.roomCode || !parsed.token) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }

  // Clear this tab's live heartbeat when closing/navigating away so Android TWA / browser
  // restarts can recover the session immediately without waiting for TTL expiry.
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('pagehide', () => {
      _clearTabHeartbeat();
    });
    window.addEventListener('beforeunload', () => {
      _clearTabHeartbeat();
    });
  }

  /**
   * Save active multiplayer room session:
   * - Primarily stored in per-tab sessionStorage so multiple tabs in the same browser
   *   never hijack each other's player slot.
   * - Mirrored to localStorage tagged with ownerTabId + live heartbeat so full browser
   *   or Android TWA app restarts still recover seamlessly after the previous tab closes.
   */
  function saveActiveSession({ roomCode, playerId, playerName, token, isHost }) {
    if (!roomCode || !token) return;
    const tid = _getTabId();
    const record = {
      roomCode:   String(roomCode).trim().toUpperCase(),
      playerId:   String(playerId || ''),
      playerName: String(playerName || ''),
      token:      String(token).trim(),
      isHost:     Boolean(isHost),
      ownerTabId: tid,
      savedAt:    Date.now(),
    };
    try {
      sessionStorage.setItem(TAB_SESSION_KEY, JSON.stringify(record));
    } catch { /* sessionStorage denied */ }
    set(SESSION_KEY, record);
    _startHeartbeat();
  }

  /**
   * Retrieve strictly this tab's own session (never borrows another tab's session).
   */
  function getTabSession() {
    const tabSess = _getTabSessionRaw();
    if (tabSess) {
      _startHeartbeat();
      return tabSess;
    }
    return null;
  }

  /**
   * Retrieve active multiplayer session for THIS tab, or recover a closed tab's session
   * from localStorage (e.g. Android TWA / browser restart).
   * Never steals a session owned by another currently open tab!
   */
  function getActiveSession() {
    // 1. Prefer this tab's own session (handles same-tab reload cleanly)
    const tabSess = _getTabSessionRaw();
    if (tabSess) {
      _startHeartbeat();
      return tabSess;
    }

    // 2. Fallback to localStorage ONLY if no other live tab currently owns that session
    const session = get(SESSION_KEY, null);
    if (!session || typeof session !== 'object') return null;
    if (!session.roomCode || !session.token) {
      remove(SESSION_KEY);
      return null;
    }

    if (session.ownerTabId && _isOtherTabAlive(session.ownerTabId)) {
      return null;
    }

    // Owner tab is closed (app/browser restart): promote recovered session into this tab
    const promoted = Object.assign({}, session, { ownerTabId: _getTabId() });
    try {
      sessionStorage.setItem(TAB_SESSION_KEY, JSON.stringify(promoted));
    } catch {}
    set(SESSION_KEY, promoted);
    _startHeartbeat();
    return promoted;
  }

  /**
   * Clear active multiplayer session for THIS tab without clobbering another live tab's session.
   */
  function clearActiveSession() {
    const tid = _getTabId();
    _stopHeartbeat();
    try {
      sessionStorage.removeItem(TAB_SESSION_KEY);
      sessionStorage.removeItem('kz_reconnect_token');
      sessionStorage.removeItem('kz_room_code');
    } catch {}

    const shared = get(SESSION_KEY, null);
    if (!shared || !shared.ownerTabId || shared.ownerTabId === tid || !_isOtherTabAlive(shared.ownerTabId)) {
      remove(SESSION_KEY);
    }
  }

  return {
    get, set, remove,
    getSettings, saveSettings,
    getPlayerName, savePlayerName,
    getLastPlayerCount, saveLastPlayerCount,
    getLastDeckCount, saveLastDeckCount,
    getLastDifficulty, saveLastDifficulty,
    saveActiveSession, getActiveSession, getTabSession, clearActiveSession,
    getTabId: _getTabId,
  };
})();
