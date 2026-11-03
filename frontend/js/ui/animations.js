/**
 * KAZHUDHAI CLUB — animations.js
 * Card and UI animation helpers
 */
const Animations = (() => {

  let animationsEnabled = true;

  function setEnabled(val) { animationsEnabled = val; }

  /**
   * Animate a card flying from source element to target element.
   * Falls back to instant transition if animations disabled.
   */
  function flyCard(sourceEl, targetEl, callback) {
    if (!animationsEnabled || !sourceEl || !targetEl) {
      if (callback) callback();
      return;
    }

    const clone = sourceEl.cloneNode(true);
    clone.style.position = 'fixed';
    clone.style.zIndex = '9999';
    clone.style.pointerEvents = 'none';
    clone.style.transition = 'none';

    const srcRect = sourceEl.getBoundingClientRect();
    const tgtRect = targetEl.getBoundingClientRect();

    clone.style.left  = `${srcRect.left}px`;
    clone.style.top   = `${srcRect.top}px`;
    clone.style.width = `${srcRect.width}px`;
    clone.style.height= `${srcRect.height}px`;

    document.body.appendChild(clone);

    requestAnimationFrame(() => {
      clone.style.transition = 'all 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
      clone.style.left  = `${tgtRect.left}px`;
      clone.style.top   = `${tgtRect.top}px`;
      clone.style.width = `${tgtRect.width}px`;
      clone.style.height= `${tgtRect.height}px`;
      clone.style.opacity = '0.7';
    });

    setTimeout(() => {
      clone.remove();
      if (callback) callback();
    }, 420);
  }

  /**
   * Flash a DOM element with a highlight colour.
   */
  function flash(el, color = 'rgba(201,168,76,0.6)', duration = 400) {
    if (!animationsEnabled || !el) return;
    const old = el.style.boxShadow;
    el.style.transition = `box-shadow ${duration/2}ms ease`;
    el.style.boxShadow = `0 0 20px ${color}`;
    setTimeout(() => {
      el.style.boxShadow = old;
    }, duration);
  }

  /**
   * Shake a DOM element (for illegal move errors).
   */
  function shake(el) {
    if (!animationsEnabled || !el) return;
    el.style.animation = 'none';
    el.offsetHeight; // reflow
    el.style.animation = 'shakeEl 0.35s ease';
    el.addEventListener('animationend', () => { el.style.animation = ''; }, { once: true });
  }

  // Inject keyframes
  const style = document.createElement('style');
  style.textContent = `
    @keyframes shakeEl {
      0%, 100% { transform: translateX(0); }
      20%       { transform: translateX(-8px); }
      40%       { transform: translateX(8px); }
      60%       { transform: translateX(-5px); }
      80%       { transform: translateX(5px); }
    }
    @keyframes dealCard {
      from { transform: translateY(-60px) scale(0.7) rotate(-5deg); opacity: 0; }
      to   { transform: translateY(0) scale(1) rotate(0deg); opacity: 1; }
    }
    @keyframes collectCards {
      from { transform: scale(1); opacity: 1; }
      to   { transform: scale(0.3) translateY(40px); opacity: 0; }
    }
    @keyframes attackFlash {
      0%   { background: rgba(140,0,0,0); }
      30%  { background: rgba(140,0,0,0.3); }
      100% { background: rgba(140,0,0,0); }
    }
  `;
  document.head.appendChild(style);

  /**
   * Deal animation: stagger-delay cards appearing.
   */
  function dealHand(cardEls, baseDelay = 50) {
    if (!animationsEnabled) return;
    cardEls.forEach((el, i) => {
      el.style.animation = 'none';
      el.style.opacity = '0';
      setTimeout(() => {
        el.style.animation = `dealCard 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards`;
      }, i * baseDelay);
    });
  }

  /**
   * Collect all played cards (shrink + fade).
   */
  function collectPlayedCards(cardEls, callback) {
    if (!animationsEnabled || !cardEls.length) {
      if (callback) callback();
      return;
    }

    cardEls.forEach(el => {
      el.style.animation = 'collectCards 0.35s ease forwards';
    });

    setTimeout(() => {
      if (callback) callback();
    }, 380);
  }

  /**
   * Flash the table felt red for an attack.
   */
  function flashAttack() {
    if (!animationsEnabled) return;
    document.querySelector('.table-felt').style.animation = 'attackFlash 0.6s ease';
    setTimeout(() => {
      const felt = document.querySelector('.table-felt');
      if (felt) felt.style.animation = '';
    }, 650);
  }

  /**
   * Bounce an element in.
   */
  function bounceIn(el) {
    if (!animationsEnabled || !el) return;
    el.style.animation = 'none';
    el.offsetHeight;
    el.style.animation = 'bounceIn 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
  }

  /**
   * Screen impact shake for attacks.
   */
  function screenShake() {
    if (!animationsEnabled) return;
    const table = document.getElementById('game-table') || document.body;
    table.style.animation = 'none';
    table.offsetHeight; // reflow
    table.style.animation = 'shakeEl 0.4s ease';
    setTimeout(() => { table.style.animation = ''; }, 420);
  }

  /**
   * Confetti celebration burst on results screen.
   */
  function confettiCelebration() {
    if (!animationsEnabled) return;
    const colors = ['#ffd700', '#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12'];
    const container = document.body;

    for (let i = 0; i < 40; i++) {
      const p = document.createElement('div');
      const color = colors[Math.floor(Math.random() * colors.length)];
      const startX = Math.random() * window.innerWidth;
      const size = Math.random() * 8 + 6;

      p.style.cssText = `
        position: fixed;
        top: -10px;
        left: ${startX}px;
        width: ${size}px;
        height: ${size * 1.4}px;
        background: ${color};
        opacity: 0.9;
        transform: rotate(${Math.random() * 360}deg);
        pointer-events: none;
        z-index: 10000;
        border-radius: 2px;
        transition: transform 2.2s ease-out, top 2.2s cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 2.2s ease-in;
      `;
      container.appendChild(p);

      requestAnimationFrame(() => {
        const fallX = startX + (Math.random() - 0.5) * 150;
        const fallY = window.innerHeight + 20;
        p.style.top = `${fallY}px`;
        p.style.left = `${fallX}px`;
        p.style.transform = `rotate(${Math.random() * 720}deg)`;
        p.style.opacity = '0';
      });

      setTimeout(() => p.remove(), 2400);
    }
  }

  return { flyCard, flash, shake, dealHand, collectPlayedCards, flashAttack, screenShake, confettiCelebration, bounceIn, setEnabled };
})();
