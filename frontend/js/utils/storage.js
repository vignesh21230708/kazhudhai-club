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

  const SESSION_KEY = 'active_session';

  /**
   * Save active multiplayer room session for seamless reconnection across
   * page reloads, browser tab restarts, and Android TWA app restarts.
   */
  function saveActiveSession({ roomCode, playerId, playerName, token, isHost }) {
    if (!roomCode || !token) return;
    set(SESSION_KEY, {
      roomCode:   String(roomCode).trim().toUpperCase(),
      playerId:   String(playerId || ''),
      playerName: String(playerName || ''),
      token:      String(token).trim(),
      isHost:     Boolean(isHost),
      savedAt:    Date.now(),
    });
  }

  /**
   * Retrieve active multiplayer session. Returns null if missing or invalid.
   */
  function getActiveSession() {
    const session = get(SESSION_KEY, null);
    if (!session || typeof session !== 'object') return null;
    if (!session.roomCode || !session.token) {
      clearActiveSession();
      return null;
    }
    return session;
  }

  /**
   * Clear active multiplayer session from both localStorage and legacy sessionStorage.
   */
  function clearActiveSession() {
    remove(SESSION_KEY);
    try {
      sessionStorage.removeItem('kz_reconnect_token');
      sessionStorage.removeItem('kz_room_code');
    } catch {}
  }

  return {
    get, set, remove,
    getSettings, saveSettings,
    getPlayerName, savePlayerName,
    getLastPlayerCount, saveLastPlayerCount,
    getLastDeckCount, saveLastDeckCount,
    getLastDifficulty, saveLastDifficulty,
    saveActiveSession, getActiveSession, clearActiveSession,
  };
})();
