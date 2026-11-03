/**
 * KAZHUDHAI CLUB — game-client.js
 * Client-side game state representation and utility
 * (No actual game logic – that lives on the server/engine)
 */
const GameClient = (() => {

  let _state = null;

  /**
   * Returns true if there is an active game state.
   */
  function isActive() { return !!_state; }

  /**
   * Set a new game state snapshot (received from server or offline engine).
   */
  function setState(state) { _state = state; }

  /**
   * Get current state.
   */
  function getState() { return _state; }

  /**
   * Reset state (game ended or exited).
   */
  function reset() { _state = null; }

  /**
   * Utility: find a card in the hand by id.
   */
  function findCard(hand, cardId) {
    return hand.find(c => c.id === cardId) || null;
  }

  return { isActive, setState, getState, reset, findCard };
})();
