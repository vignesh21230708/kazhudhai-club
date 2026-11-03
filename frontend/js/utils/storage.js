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

  return {
    get, set, remove,
    getSettings, saveSettings,
    getPlayerName, savePlayerName,
    getLastPlayerCount, saveLastPlayerCount,
    getLastDeckCount, saveLastDeckCount,
    getLastDifficulty, saveLastDifficulty,
  };
})();
