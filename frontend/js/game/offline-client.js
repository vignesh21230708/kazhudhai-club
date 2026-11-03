/**
 * KAZHUDHAI CLUB — offline-client.js
 * Manages offline game session via REST API calls to Flask backend.
 * Full integration with the authoritative Python GameEngine.
 */
const OfflineClient = (() => {

  const BASE = '/api/offline';
  let _gameId = null;

  /**
   * Start a new offline game session.
   * @param {object} config { playerName, playerCount, deckCount, difficulty }
   * @returns Promise resolving to initial game state
   */
  async function startGame(config) {
    const res = await fetch(`${BASE}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const data = await res.json();
    _gameId = data.game_id;
    return data;
  }

  /**
   * Play a card.
   * @param {string} cardId
   * @returns Promise with action result and updated game state
   */
  async function playCard(cardId) {
    if (!_gameId) return null;
    const res = await fetch(`${BASE}/play`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: _gameId, card_id: cardId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Play error: ${res.status}`);
    }
    return res.json();
  }

  /**
   * Step the game by executing ONE AI turn.
   * Allows smooth visual animation of each bot move.
   * @returns Promise with step result and updated game state
   */
  async function step() {
    if (!_gameId) return null;
    const res = await fetch(`${BASE}/step`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: _gameId }),
    });
    if (!res.ok) throw new Error(`Step error: ${res.status}`);
    return res.json();
  }

  /**
   * Fast-forward remaining AI turns to immediate completion.
   */
  async function fastForward() {
    if (!_gameId) return null;
    const res = await fetch(`${BASE}/fast_forward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: _gameId }),
    });
    if (!res.ok) throw new Error(`Fast-forward error: ${res.status}`);
    return res.json();
  }

  /**
   * Poll for current game state.
   */
  async function getState() {
    if (!_gameId) return null;
    const res = await fetch(`${BASE}/state?game_id=${_gameId}`);
    if (!res.ok) throw new Error(`State error: ${res.status}`);
    return res.json();
  }

  function reset() {
    _gameId = null;
  }

  function getGameId() {
    return _gameId;
  }

  return { startGame, playCard, step, fastForward, getState, reset, getGameId };
})();
