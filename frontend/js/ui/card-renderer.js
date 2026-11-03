/**
 * KAZHUDHAI CLUB — card-renderer.js
 * Generates realistic HTML playing card elements
 */
const CardRenderer = (() => {

  const SUIT_SYMBOLS = { S: '♠', H: '♥', D: '♦', C: '♣' };
  const SUIT_NAMES   = { S: 'spades', H: 'hearts', D: 'diamonds', C: 'clubs' };
  const SUIT_ORDER   = { S: 0, H: 1, D: 2, C: 3 };
  const RANK_ORDER   = {
    'A': 12, 'K': 11, 'Q': 10, 'J': 9, '10': 8, '9': 7,
    '8': 6, '7': 5, '6': 4, '5': 3, '4': 2, '3': 1, '2': 0
  };

  /**
   * Sort player hand:
   * 1. Group cards by suit (Spades, Hearts, Diamonds, Clubs).
   * 2. Within each suit, arrange in descending rank order (A, K, Q, J, 10, 9, 8, 7, 6, 5, 4, 3, 2).
   */
  function sortHand(cards) {
    if (!Array.isArray(cards)) return [];
    return [...cards].sort((a, b) => {
      const suitDiff = (SUIT_ORDER[a.suit] ?? 99) - (SUIT_ORDER[b.suit] ?? 99);
      if (suitDiff !== 0) return suitDiff;
      return (RANK_ORDER[b.rank] ?? 0) - (RANK_ORDER[a.rank] ?? 0);
    });
  }

  /**
   * Create a face-up playing card element.
   * @param {object} card  - { id, rank, suit }  (e.g. { rank:'A', suit:'S' })
   * @param {object} opts  - { selectable, selected, legal, played }
   * @returns HTMLElement
   */
  function createFaceUp(card, opts = {}) {
    const { selectable = false, selected = false, legal = true, played = false } = opts;

    const el = document.createElement('div');
    el.className = [
      'playing-card',
      'face-up',
      `suit-${SUIT_NAMES[card.suit]}`,
      card.rank === 'A' && card.suit === 'S' ? 'special-ace-spades' : '',
      selectable ? 'hand-card' : '',
      played ? 'played-card' : '',
      selected ? 'selected' : '',
      selectable && !legal ? 'illegal' : '',
    ].filter(Boolean).join(' ');

    el.dataset.cardId = card.id;
    el.dataset.rank   = card.rank;
    el.dataset.suit   = card.suit;

    const suitSym = SUIT_SYMBOLS[card.suit];

    el.innerHTML = `
      <div class="card-face">
        <div class="card-corner">
          <span class="card-rank">${card.rank}</span>
          <span class="card-suit-small">${suitSym}</span>
        </div>
        <div class="card-center">
          <span class="card-center-suit">${suitSym}</span>
        </div>
        <div class="card-corner bottom-right">
          <span class="card-rank">${card.rank}</span>
          <span class="card-suit-small">${suitSym}</span>
        </div>
      </div>
    `;

    return el;
  }

  /**
   * Create a face-down card (opponent's hidden card).
   * @returns HTMLElement
   */
  function createFaceDown() {
    const el = document.createElement('div');
    el.className = 'playing-card face-down';
    el.innerHTML = `<div class="card-back"></div>`;
    return el;
  }

  /**
   * Create a small opponent card-back for fan display.
   * @returns HTMLElement
   */
  function createSmallBack() {
    const el = document.createElement('div');
    el.className = 'opponent-card-back';
    return el;
  }

  /**
   * Render an opponent's hand as a fan of card backs.
   * @param {number} count  - Number of cards
   * @param {number} maxVisible - Max number of card backs to render (for performance)
   * @returns HTMLElement
   */
  function createOpponentFan(count, maxVisible = 10) {
    const fan = document.createElement('div');
    fan.className = 'opponent-hand-fan';

    const visible = Math.min(count, maxVisible);
    for (let i = 0; i < visible; i++) {
      fan.appendChild(createSmallBack());
    }
    return fan;
  }

  /**
   * Create a pile-of-cards visual (stacked backs).
   * @param {number} count
   * @returns HTMLElement
   */
  function createPileVisual(count) {
    const wrap = document.createElement('div');
    wrap.className = 'pile-stack';
    const badge = document.createElement('div');
    badge.className = 'pile-count-badge';
    badge.textContent = count;
    wrap.appendChild(badge);
    return wrap;
  }

  /**
   * Get suit symbol by letter.
   */
  function suitSymbol(suitLetter) {
    return SUIT_SYMBOLS[suitLetter] || suitLetter;
  }

  /**
   * Get CSS class name for a suit letter.
   */
  function suitClass(suitLetter) {
    return SUIT_NAMES[suitLetter] || '';
  }

  /**
   * Returns a string label like "A♠" for a card object.
   */
  function cardLabel(card) {
    return `${card.rank}${SUIT_SYMBOLS[card.suit]}`;
  }

  return { createFaceUp, createFaceDown, createSmallBack, createOpponentFan, createPileVisual, suitSymbol, suitClass, cardLabel, sortHand };
})();
