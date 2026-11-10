/**
 * KAZHUDHAI CLUB — table.js
 * Game table rendering: opponents, hand, played cards, HUD updates
 */
const TableUI = (() => {

  // ── DOM refs ──
  const DOM = {};

  function _cache() {
    DOM.opponentsTop   = document.getElementById('opponents-top');
    DOM.opponentsLeft  = document.getElementById('opponents-left');
    DOM.opponentsRight = document.getElementById('opponents-right');
    DOM.handRow        = document.getElementById('hand-row');
    DOM.handContainer  = document.getElementById('hand-container');
    DOM.playedCardsRow = document.getElementById('played-cards-row');
    DOM.commonPileCount= document.getElementById('common-pile-count');
    DOM.hudRoomCode    = document.getElementById('hud-room-code');
    DOM.hudDeckCount   = document.getElementById('hud-deck-count');
    DOM.hudCommonCount = document.getElementById('hud-common-count');
    DOM.hudStatus      = document.getElementById('hud-status');
    DOM.turnText       = document.getElementById('turn-text');
    DOM.attackBanner   = document.getElementById('attack-banner');
    DOM.attackSub      = document.getElementById('attack-sub');
    DOM.selfName       = document.getElementById('self-name');
    DOM.selfCardCount  = document.getElementById('self-card-count');
    DOM.selfAvatar     = document.getElementById('self-avatar');
    DOM.selfAttackZone = document.getElementById('self-collected-zone');
    DOM.selfAttackCount= document.getElementById('self-attack-count');
    DOM.selfStatusBadge= document.getElementById('self-status-badge');
    DOM.playBtn        = document.getElementById('btn-play-card');
    DOM.actionHint     = document.getElementById('action-hint');
    DOM.ingameMenu     = document.getElementById('ingame-menu');
    DOM.menuBackdrop   = document.getElementById('ingame-menu-backdrop');
    DOM.confirmExit    = document.getElementById('confirm-exit');
    DOM.btnEmoji       = document.getElementById('btn-table-emoji');
    DOM.emojiPanel     = document.getElementById('emoji-picker-panel');
  }

  let _eventsBound = false;
  let _isPlayInFlight = false;
  let _isFirstDeal = true;
  let _selectedCardId = null;
  let _myHand = [];     // Array of card objects { id, rank, suit }
  let _legalSuit = null; // null = any card OK; 'S'/'H'/etc = must follow suit
  let _isMyTurn  = false;

  // ── Authoritative helper to determine whether it is the local player's turn ──
  function _getIsMyTurn() {
    if (typeof App !== 'undefined' && typeof App.isCurrentPlayerTurn === 'function') {
      const activeTurn = App.isCurrentPlayerTurn();
      if (activeTurn) _isMyTurn = true;
      return activeTurn;
    }
    return !!_isMyTurn;
  }

  // ── Defensive helper to get safe numeric card count ──
  function _getCardCount(player) {
    if (!player) return 0;
    if (typeof player.cardCount === 'number') return player.cardCount;
    if (typeof player.card_count === 'number') return player.card_count;
    if (Array.isArray(player.hand)) return player.hand.length;
    return 0;
  }

  function _formatCardCountText(player) {
    const count = _getCardCount(player);
    return `${count} ${count === 1 ? 'card' : 'cards'}`;
  }

  // ── In-game slide-out menu controls ──
  function openInGameMenu() {
    if (!DOM.ingameMenu) _cache();
    if (DOM.ingameMenu) DOM.ingameMenu.classList.remove('hidden');
    if (DOM.menuBackdrop) DOM.menuBackdrop.classList.remove('hidden');
  }

  function closeInGameMenu() {
    if (!DOM.ingameMenu) _cache();
    if (DOM.ingameMenu) DOM.ingameMenu.classList.add('hidden');
    if (DOM.menuBackdrop) DOM.menuBackdrop.classList.add('hidden');
  }

  // ── Initialise the table for a new game ──
  function init(gameConfig) {
    _cache();
    _selectedCardId = null;
    _myHand = [];
    _legalSuit = null;
    _isMyTurn = false;
    _isPlayInFlight = false;
    _isFirstDeal = true;
    closeInGameMenu();

    DOM.hudRoomCode.textContent  = gameConfig.roomCode  || 'OFFLINE';
    DOM.hudDeckCount.textContent = gameConfig.deckCount || '?';
    DOM.selfName.textContent     = gameConfig.playerName || 'You';

    DOM.playedCardsRow.innerHTML = '<div class="empty-zone-hint">Waiting for first card…</div>';
    DOM.attackBanner.classList.add('hidden');
    updateCommonPile(0);

    _bindTableEvents();
  }

  function _bindTableEvents() {
    if (_eventsBound) return;
    _cache();
    _eventsBound = true;

    // Helper to safely bind both click and touch without double firing
    function bindTap(el, handler) {
      if (!el) return;
      let lastTrigger = 0;
      const onEvent = (e) => {
        const now = Date.now();
        if (now - lastTrigger < 350) return;
        lastTrigger = now;
        handler(e);
      };
      el.addEventListener('click', onEvent);
      el.addEventListener('touchend', onEvent);
    }

    // HUD menu button (hamburger ☰)
    const menuBtn = document.getElementById('btn-menu-game');
    if (menuBtn) {
      bindTap(menuBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        Sound.click();
        if (DOM.ingameMenu && DOM.ingameMenu.classList.contains('hidden')) {
          openInGameMenu();
        } else {
          closeInGameMenu();
        }
      });
    }

    // In-game menu close button (✕)
    const closeBtn = document.getElementById('btn-close-ingame-menu');
    if (closeBtn) {
      bindTap(closeBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        Sound.click();
        closeInGameMenu();
      });
    }

    // Backdrop overlay click/touch
    if (DOM.menuBackdrop) {
      bindTap(DOM.menuBackdrop, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        closeInGameMenu();
      });
    }

    // Rules & Settings buttons in menu
    const rulesBtn = document.getElementById('btn-rules-ingame');
    if (rulesBtn) {
      bindTap(rulesBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        closeInGameMenu();
        if (typeof MenuUI !== 'undefined' && MenuUI.showModal) {
          MenuUI.showModal('modal-rules');
        }
      });
    }
    const settingsBtn = document.getElementById('btn-settings-ingame');
    if (settingsBtn) {
      bindTap(settingsBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        closeInGameMenu();
        if (typeof MenuUI !== 'undefined' && MenuUI.showModal) {
          MenuUI.showModal('modal-settings');
        }
      });
    }

    // Exit confirmation
    const exitBtn = document.getElementById('btn-exit-game');
    if (exitBtn) {
      bindTap(exitBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        closeInGameMenu();
        if (DOM.confirmExit) DOM.confirmExit.classList.remove('hidden');
      });
    }

    const cancelExitBtn = document.getElementById('btn-cancel-exit');
    if (cancelExitBtn) {
      bindTap(cancelExitBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (DOM.confirmExit) DOM.confirmExit.classList.add('hidden');
      });
    }

    const confirmExitBtn = document.getElementById('btn-confirm-exit');
    if (confirmExitBtn) {
      bindTap(confirmExitBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (DOM.confirmExit) DOM.confirmExit.classList.add('hidden');
        Sound.click();
        if (typeof App !== 'undefined' && App.exitToMenu) {
          App.exitToMenu();
        }
      });
    }

    // Restart
    const restartBtn = document.getElementById('btn-restart-game');
    if (restartBtn) {
      bindTap(restartBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        closeInGameMenu();
        Sound.click();
        if (typeof App !== 'undefined' && App.restartGame) {
          App.restartGame();
        }
      });
    }

    // Play button - support both click and touch on mobile devices
    if (DOM.playBtn) {
      bindTap(DOM.playBtn, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        _playSelectedCard();
      });
    }

    // Emoji reaction button (toggle panel)
    if (DOM.btnEmoji) {
      bindTap(DOM.btnEmoji, (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        if (DOM.emojiPanel) {
          DOM.emojiPanel.classList.toggle('hidden');
        }
      });
    }

    // Emoji choice buttons
    if (DOM.emojiPanel) {
      DOM.emojiPanel.querySelectorAll('.emoji-choice-btn').forEach(btn => {
        bindTap(btn, (e) => {
          if (e && typeof e.preventDefault === 'function') e.preventDefault();
          if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
          const emoji = btn.dataset.emoji;
          if (DOM.emojiPanel) DOM.emojiPanel.classList.add('hidden');
          if (emoji && typeof App !== 'undefined' && App.sendReaction) {
            App.sendReaction(emoji);
          }
        });
      });
    }

    // Close emoji picker when tapping outside
    document.addEventListener('click', (e) => {
      if (DOM.emojiPanel && !DOM.emojiPanel.classList.contains('hidden')) {
        if (!DOM.emojiPanel.contains(e.target) && e.target !== DOM.btnEmoji && !DOM.btnEmoji?.contains(e.target)) {
          DOM.emojiPanel.classList.add('hidden');
        }
      }
    });
  }

  function _playSelectedCard() {
    if (_isPlayInFlight) return;
    const myTurn = _getIsMyTurn();
    if (!myTurn || !_selectedCardId) {
      _updateActionBar(myTurn, _legalSuit);
      return;
    }

    const cardToPlay = _selectedCardId;
    _isPlayInFlight = true;
    if (DOM.playBtn) DOM.playBtn.disabled = true;
    _selectedCardId = null;

    // Clear selection visual state
    if (DOM.handRow) {
      DOM.handRow.querySelectorAll('.hand-card.selected').forEach(el => el.classList.remove('selected'));
    }

    Sound.click();
    App.playCard(cardToPlay);

    // Timeout safety fallback: prevent in-flight lock from getting stuck if network stalls
    setTimeout(() => {
      if (_isPlayInFlight) {
        resetPlayInFlight();
      }
    }, 3500);
  }

  function resetPlayInFlight() {
    _isPlayInFlight = false;
    _updateActionBar(_getIsMyTurn(), _legalSuit);
  }

  // ── Render players around the table ──
  /**
   * Distribute players strictly according to their room joining order:
   * First joined player = Position 1
   * Second joined player = Position 2
   * Third joined player = Position 3
   * Fourth joined player = Position 4
   * Every connected device receives and displays the exact same player sequence.
   *
   * Balanced layouts:
   * 2 players: Top: 2 (P1, P2), Left: 0, Right: 0
   * 3 players: Left: 1 (P1), Top: 1 (P2), Right: 1 (P3)
   * 4 players: Left: 1 (P1), Top: 2 (P2, P3), Right: 1 (P4)
   * 5 players: Left: 1 (P1), Top: 3 (P2, P3, P4), Right: 1 (P5)
   * 6 players: Left: 2 (P1, P2), Top: 2 (P3, P4), Right: 2 (P5, P6)
   * 7 players: Left: 2 (P1, P2), Top: 3 (P3, P4, P5), Right: 2 (P6, P7)
   */
  function _getTableDistribution(totalPlayers) {
    switch (totalPlayers) {
      case 2:
        return { top: 2, left: 0, right: 0 };
      case 3:
        return { top: 1, left: 1, right: 1 };
      case 4:
        return { top: 2, left: 1, right: 1 };
      case 5:
        return { top: 3, left: 1, right: 1 };
      case 6:
        return { top: 2, left: 2, right: 2 };
      case 7:
        return { top: 3, left: 2, right: 2 };
      default: {
        const side = Math.max(0, Math.floor((totalPlayers - 1) / 3));
        const top = Math.max(1, totalPlayers - side * 2);
        return { top, left: side, right: side };
      }
    }
  }

  // Backward compatibility distribution function
  function _getOpponentDistribution(count) {
    switch (count) {
      case 1:
        return { top: 1, left: 0, right: 0 };
      case 2:
        return { top: 2, left: 0, right: 0 };
      case 3:
        return { top: 1, left: 1, right: 1 };
      case 4:
        return { top: 2, left: 1, right: 1 };
      case 5:
        return { top: 3, left: 1, right: 1 };
      case 6:
        return { top: 2, left: 2, right: 2 };
      default: {
        const side = Math.max(0, Math.floor((count - 1) / 3));
        const top = Math.max(1, count - side * 2);
        return { top, left: side, right: side };
      }
    }
  }

  /**
   * Render all players around the table in consistent server-authoritative order.
   *
   * @param {Array} players - Array of {id, name, cardCount, isAI, isActive, isSafe, position}
   * @param {string} myId   - Local player ID
   */
  function renderPlayers(players, myId) {
    if (!DOM.opponentsTop) _cache();

    // Clear zones
    DOM.opponentsTop.innerHTML   = '';
    DOM.opponentsLeft.innerHTML  = '';
    DOM.opponentsRight.innerHTML = '';

    const totalPlayers = players.length;
    if (totalPlayers === 0) return;

    // Apply layout hooks to table elements
    const tableEl = document.querySelector('.game-table');
    const tableInner = document.querySelector('.table-inner');
    if (tableEl) {
      tableEl.setAttribute('data-player-count', totalPlayers);
    }
    if (tableInner) {
      tableInner.setAttribute('data-player-count', totalPlayers);
      tableInner.className = `table-inner players-${totalPlayers}`;
    }

    const dist = _getTableDistribution(totalPlayers);

    const leftPlayers  = players.slice(0, dist.left);
    const topPlayers   = players.slice(dist.left, dist.left + dist.top);
    const rightPlayers = players.slice(dist.left + dist.top, dist.left + dist.top + dist.right);

    // Append to respective table zones in strictly consistent order
    leftPlayers.forEach((p, idx) => {
      const posNum = idx + 1;
      DOM.opponentsLeft.appendChild(_createPlayerSlot(p, 'left', posNum, p.id === myId));
    });
    topPlayers.forEach((p, idx) => {
      const posNum = dist.left + idx + 1;
      DOM.opponentsTop.appendChild(_createPlayerSlot(p, 'top', posNum, p.id === myId));
    });
    rightPlayers.forEach((p, idx) => {
      const posNum = dist.left + dist.top + idx + 1;
      DOM.opponentsRight.appendChild(_createPlayerSlot(p, 'right', posNum, p.id === myId));
    });
  }

  function renderOpponents(opponents, myId) {
    renderPlayers(opponents, myId);
  }

  function _createPlayerSlot(opp, position, posNum, isSelf) {
    const slot = document.createElement('div');
    const isSide = position === 'side' || position === 'left' || position === 'right';
    slot.className = `opponent-slot ${position}${isSide ? ' side' : ''}${isSelf ? ' is-self' : ''}`;
    slot.id = `opp-slot-${opp.id}`;

    // Position indicator badge: P1, P2, P3, etc.
    const posBadge = document.createElement('div');
    posBadge.className = 'player-pos-badge';
    posBadge.textContent = `P${posNum || opp.position || 1}`;
    slot.appendChild(posBadge);

    const avatar = document.createElement('div');
    avatar.className = `opponent-avatar${opp.isActive ? ' active-turn' : ''}${opp.isSafe ? ' safe' : ''}`;
    avatar.id = `opp-avatar-${opp.id}`;
    avatar.innerHTML = `<span class="avatar-emoji">${opp.isAI ? '🤖' : (isSelf ? '👤' : '👤')}</span>`;

    if (opp.isSafe) {
      const badge = document.createElement('div');
      badge.className = 'opponent-safe-badge';
      badge.textContent = 'SAFE';
      avatar.appendChild(badge);
    }

    if (opp.isAI) {
      const chip = document.createElement('div');
      chip.className = 'ai-chip';
      chip.textContent = 'AI';
      avatar.appendChild(chip);
    }

    const nameEl = document.createElement('div');
    nameEl.className = 'opponent-name';
    nameEl.id = `opp-name-${opp.id}`;

    // Connection status indicator dot
    const status = opp.connection_status || 'connected';
    const statusDot = document.createElement('span');
    statusDot.className = `player-status-dot status-${status}`;
    statusDot.id = `opp-status-${opp.id}`;
    statusDot.title = status.charAt(0).toUpperCase() + status.slice(1);

    const nameText = document.createElement('span');
    nameText.textContent = isSelf ? `${opp.name} (You)` : opp.name;

    nameEl.appendChild(statusDot);
    nameEl.appendChild(nameText);

    const cardCount = _getCardCount(opp);
    const countEl = document.createElement('div');
    countEl.className = 'opponent-card-count';
    countEl.id = `opp-count-${opp.id}`;
    countEl.textContent = _formatCardCountText(opp);

    slot.appendChild(avatar);
    slot.appendChild(nameEl);
    slot.appendChild(countEl);

    // Fan of card backs (omit for self who has real cards displayed in hand below)
    if (!isSelf && cardCount > 0) {
      const fan = CardRenderer.createOpponentFan(cardCount);
      fan.id = `opp-fan-${opp.id}`;
      slot.appendChild(fan);
    }

    return slot;
  }

  function _createOpponentSlot(opp, position) {
    return _createPlayerSlot(opp, position, opp.position || 1, false);
  }

  // ── Update one opponent's card count and turn state ──
  function updateOpponent(opp) {
    const cardCount = _getCardCount(opp);
    const countEl = document.getElementById(`opp-count-${opp.id}`);
    if (countEl) countEl.textContent = _formatCardCountText(opp);

    const avatarEl = document.getElementById(`opp-avatar-${opp.id}`);
    if (avatarEl) {
      avatarEl.classList.toggle('active-turn', !!opp.isActive);
      avatarEl.classList.toggle('safe', !!opp.isSafe);

      if (opp.isSafe && !avatarEl.querySelector('.opponent-safe-badge')) {
        const badge = document.createElement('div');
        badge.className = 'opponent-safe-badge';
        badge.textContent = 'SAFE';
        avatarEl.appendChild(badge);
      }
    }

    const fan = document.getElementById(`opp-fan-${opp.id}`);
    if (fan) {
      const newFan = CardRenderer.createOpponentFan(cardCount);
      newFan.id = fan.id;
      fan.replaceWith(newFan);
    }

    if (opp.connection_status) {
      updatePlayerStatus(opp.id, opp.connection_status);
    }
  }

  // ── Update player connection status indicator ──
  function updatePlayerStatus(playerId, status) {
    const normStatus = (status || 'connected').toLowerCase();

    // Check opponent slot
    const dot = document.getElementById(`opp-status-${playerId}`);
    if (dot) {
      dot.className = `player-status-dot status-${normStatus}`;
      dot.title = normStatus.charAt(0).toUpperCase() + normStatus.slice(1);
    }

    // Check self area if it's the current player
    const myId = (typeof OnlineClient !== 'undefined' && OnlineClient.getPlayerId)
      ? OnlineClient.getPlayerId()
      : 'human';

    if (playerId === myId || playerId === 'human') {
      const badge = document.getElementById('self-status-badge');
      if (badge) {
        badge.className = `self-status-badge status-${normStatus}`;
        const dotSelf = badge.querySelector('.player-status-dot');
        if (dotSelf) dotSelf.className = `player-status-dot status-${normStatus}`;
        const txtSelf = badge.querySelector('.status-text');
        if (txtSelf) {
          txtSelf.textContent = normStatus === 'connected' ? 'Connected' :
                                normStatus === 'reconnecting' ? 'Reconnecting' :
                                normStatus === 'left' ? 'Left' : 'Disconnected';
        }
      }
    }
  }

  // ── Render the human player's hand ──
  /**
   * @param {Array}  hand          - Array of card objects {id, rank, suit}
   * @param {string} legalSuit     - null or suit letter that must be followed
   * @param {boolean} isMyTurn     - Whether it is this player's turn
   */
  function renderHand(hand, legalSuit, isMyTurn) {
    const prevSelectedId = _selectedCardId;
    _myHand    = hand || [];
    _legalSuit = legalSuit;
    _isMyTurn  = (typeof isMyTurn === 'boolean') ? isMyTurn : _getIsMyTurn();
    _isPlayInFlight = false;

    DOM.handRow.innerHTML = '';
    DOM.selfCardCount.textContent = _formatCardCountText({ cardCount: _myHand.length });

    if (_myHand.length === 0) {
      _selectedCardId = null;
      DOM.handRow.innerHTML = '<div class="empty-zone-hint" style="color:#55dd88; font-weight:700; font-size:0.9rem; padding: 20px 0;">🎉 You emptied your hand and are SAFE! Watching remaining players…</div>';
      DOM.selfAvatar.classList.add('safe');
      if (!DOM.selfAvatar.querySelector('.opponent-safe-badge')) {
        const badge = document.createElement('div');
        badge.className = 'opponent-safe-badge';
        badge.textContent = 'SAFE';
        DOM.selfAvatar.appendChild(badge);
      }
      _updateActionBar(false, null);

      const actionBar = document.getElementById('action-bar');
      if (actionBar && !document.getElementById('btn-fast-forward')) {
        const ffBtn = document.createElement('button');
        ffBtn.id = 'btn-fast-forward';
        ffBtn.className = 'play-btn';
        ffBtn.style.cssText = 'background: linear-gradient(135deg, #c9a84c, #7a5f20); color: #000; font-weight:900; margin-left: auto;';
        ffBtn.textContent = '⚡ Fast-Forward to Results';
        ffBtn.addEventListener('click', () => {
          App.fastForwardGame();
        });
        actionBar.appendChild(ffBtn);
      }
      return;
    }

    // Clean up fast-forward button if hand is replenished (e.g. attack won)
    document.getElementById('btn-fast-forward')?.remove();

    // Automatically sort human player's visible hand:
    // Group by suit (♠, ♥, ♦, ♣) and descending rank (A down to 2)
    const sortedHand = CardRenderer.sortHand(_myHand);
    _myHand = sortedHand;

    // Responsive horizontal spacing:
    // Slightly increased spacing so every card's rank, suit, and face are clearly visible
    const winWidth = window.innerWidth;
    const isMobilePortrait = winWidth <= 480;
    const isLandscapeShort = window.innerHeight <= 500 && window.innerWidth > window.innerHeight;
    const isTablet = winWidth > 480 && winWidth <= 768;

    let overlap = '-14px';
    if (isLandscapeShort) {
      if (sortedHand.length <= 4) overlap = '-4px';
      else if (sortedHand.length <= 8) overlap = '-8px';
      else if (sortedHand.length <= 14) overlap = '-12px';
      else overlap = '-16px';
    } else if (isMobilePortrait) {
      if (sortedHand.length <= 3) overlap = '-4px';
      else if (sortedHand.length <= 6) overlap = '-8px';
      else if (sortedHand.length <= 10) overlap = '-12px';
      else if (sortedHand.length <= 16) overlap = '-16px';
      else if (sortedHand.length <= 22) overlap = '-20px';
      else overlap = '-22px';
    } else if (isTablet) {
      if (sortedHand.length <= 4) overlap = '-6px';
      else if (sortedHand.length <= 8) overlap = '-10px';
      else if (sortedHand.length <= 14) overlap = '-14px';
      else if (sortedHand.length <= 20) overlap = '-18px';
      else overlap = '-22px';
    } else {
      // Desktop / Laptop
      if (sortedHand.length <= 4) overlap = '-6px';
      else if (sortedHand.length <= 8) overlap = '-10px';
      else if (sortedHand.length <= 14) overlap = '-14px';
      else if (sortedHand.length <= 20) overlap = '-18px';
      else overlap = '-22px';
    }
    DOM.handRow.style.setProperty('--hand-overlap', overlap);

    // Center hand when few cards, left-align for smooth natural scrolling
    if (sortedHand.length <= 4) {
      DOM.handRow.style.justifyContent = 'center';
    } else {
      DOM.handRow.style.justifyContent = 'flex-start';
    }

    const cardEls = [];
    let preservedSelection = false;

    sortedHand.forEach(card => {
      const isLegal = _isMyTurn ? _isCardLegal(card, legalSuit, sortedHand) : true;
      const isSelected = prevSelectedId && String(card.id) === String(prevSelectedId);

      if (isSelected && isLegal) {
        preservedSelection = true;
        _selectedCardId = card.id;
      }

      const cardEl  = CardRenderer.createFaceUp(card, {
        selectable: true,
        selected: isSelected && isLegal,
        legal: isLegal,
      });
      cardEl.classList.toggle('hand-card', true);
      cardEl.classList.toggle('illegal', _isMyTurn && !isLegal);

      // Card tap listener
      cardEl.addEventListener('click', (e) => {
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        _onCardClick(card.id, cardEl);
      });

      DOM.handRow.appendChild(cardEl);
      cardEls.push(cardEl);
    });

    if (!preservedSelection) {
      _selectedCardId = null;
    }

    if (_isFirstDeal && Storage.getSettings().animations) {
      Animations.dealHand(cardEls, 30);
    }
    _isFirstDeal = false;

    _updateActionBar(_isMyTurn, legalSuit);
  }

  function _isCardLegal(card, legalSuit, hand) {
    if (!card) return false;
    if (!legalSuit) return true; // First card of round: any card is legal
    const cardSuit = String(card.suit || '').toUpperCase();
    const targetSuit = String(legalSuit || '').toUpperCase();
    if (!targetSuit) return true;
    if (!Array.isArray(hand) || hand.length === 0) return true;

    // Has the starting suit? Must follow it
    const hasSuit = hand.some(c => c && String(c.suit || '').toUpperCase() === targetSuit);
    if (hasSuit) return cardSuit === targetSuit;
    return true; // Doesn't have suit → any card is legal (attack)
  }

  function _onCardClick(cardId, cardEl) {
    if (_isPlayInFlight) return;

    const myTurn = _getIsMyTurn();
    _isMyTurn = myTurn;

    const cardIdStr = String(cardId || cardEl.dataset.cardId || '');
    let cardObj = _myHand.find(c => String(c.id) === cardIdStr);
    if (!cardObj && cardEl.dataset.suit) {
      cardObj = {
        id: cardIdStr,
        rank: cardEl.dataset.rank,
        suit: cardEl.dataset.suit,
      };
    }

    const isLegal = myTurn && cardObj ? _isCardLegal(cardObj, _legalSuit, _myHand) : false;

    // Deselect or direct-play if clicking already-selected card
    if (_selectedCardId === cardIdStr) {
      if (myTurn && isLegal && !_isPlayInFlight) {
        // Direct play on double-tap: rapid and natural on Android touchscreens
        _playSelectedCard();
        return;
      }

      // If not legal or not player's turn, simply deselect
      _selectedCardId = null;
      cardEl.classList.remove('selected');
      if (DOM.playBtn) DOM.playBtn.disabled = true;
      return;
    }

    // Deselect previous
    DOM.handRow.querySelectorAll('.hand-card.selected').forEach(el => el.classList.remove('selected'));

    _selectedCardId = cardIdStr;
    cardEl.classList.add('selected');
    Sound.click();

    // Check legality: play button is only active when it is my turn AND card is legal AND not in flight
    const btnDisabled = !myTurn || !isLegal || _isPlayInFlight;
    if (DOM.playBtn) DOM.playBtn.disabled = btnDisabled;

    // Smoothly scroll the selected card into view if partially obscured on small screens
    if (typeof cardEl.scrollIntoView === 'function') {
      cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }
  }

  function _updateActionBar(isMyTurn, legalSuit) {
    const myTurn = (typeof isMyTurn === 'boolean') ? isMyTurn : _getIsMyTurn();
    const hasValidSelection = !!_selectedCardId;
    if (DOM.playBtn) {
      DOM.playBtn.disabled = !myTurn || !hasValidSelection || _isPlayInFlight;
    }

    if (!myTurn) {
      DOM.actionHint.textContent = 'Wait for your turn…';
      DOM.selfAvatar.classList.remove('active-turn');
    } else {
      DOM.selfAvatar.classList.add('active-turn');
      if (legalSuit) {
        DOM.actionHint.textContent = `Must follow ${CardRenderer.suitSymbol(legalSuit)} or attack!`;
      } else {
        DOM.actionHint.textContent = 'Select any card to start the round';
      }
    }
  }

  // ── Render a card being played to the centre zone ──
  function addPlayedCard(card, playerName, isAttack) {
    // Remove empty hint
    DOM.playedCardsRow.querySelector('.empty-zone-hint')?.remove();

    const cardEl = CardRenderer.createFaceUp(card, { played: true });

    // Add player label
    const wrap = document.createElement('div');
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.alignItems = 'center';
    wrap.style.gap = '3px';

    const label = document.createElement('div');
    label.style.cssText = `
      font-size:0.6rem; color:${isAttack ? '#ff8888' : 'var(--text-muted)'};
      font-family:var(--font-body); font-weight:600;
      white-space:nowrap;
    `;
    label.textContent = playerName;

    wrap.appendChild(cardEl);
    wrap.appendChild(label);
    DOM.playedCardsRow.appendChild(wrap);

    Sound.cardPlay();
  }

  // ── Clear played cards zone ──
  function clearPlayedCards(animate) {
    const cards = Array.from(DOM.playedCardsRow.children);
    if (animate && Storage.getSettings().animations && cards.length) {
      Animations.collectPlayedCards(cards, () => {
        DOM.playedCardsRow.innerHTML = '<div class="empty-zone-hint">Waiting for first card…</div>';
      });
    } else {
      DOM.playedCardsRow.innerHTML = '<div class="empty-zone-hint">Waiting for first card…</div>';
    }
  }

  // ── Authoritative sync for played cards ──
  function syncPlayedCards(playedCards) {
    if (!DOM.playedCardsRow) _cache();
    if (!Array.isArray(playedCards) || playedCards.length === 0) {
      if (!DOM.playedCardsRow.querySelector('.empty-zone-hint') || DOM.playedCardsRow.children.length > 1) {
        clearPlayedCards(false);
      }
      return;
    }

    const currentCardEls = DOM.playedCardsRow.querySelectorAll('.card');
    let isMatch = (currentCardEls.length === playedCards.length);
    if (isMatch) {
      for (let i = 0; i < playedCards.length; i++) {
        const pc = playedCards[i];
        const cardId = pc.card ? pc.card.id : null;
        if (currentCardEls[i].dataset.cardId !== String(cardId)) {
          isMatch = false;
          break;
        }
      }
    }

    if (!isMatch) {
      DOM.playedCardsRow.innerHTML = '';
      playedCards.forEach(pc => {
        addPlayedCard(pc.card, pc.player_name, pc.is_attack);
      });
    }
  }

  // ── Show floating emoji reaction bubble near player's avatar ──
  function showPlayerReaction(playerId, emoji) {
    if (!emoji) return;

    let targetEl = null;
    const isSelf = (playerId === 'human' || (typeof OnlineClient !== 'undefined' && typeof OnlineClient.getPlayerId === 'function' && playerId === OnlineClient.getPlayerId()));
    if (isSelf) {
      targetEl = DOM.selfAvatar || document.getElementById('self-avatar');
    } else {
      targetEl = document.getElementById(`opp-avatar-${playerId}`) ||
                 document.getElementById(`opp-slot-${playerId}`);
    }
    if (!targetEl) return;

    // Remove any previous active reaction bubble in this slot
    targetEl.querySelectorAll('.player-reaction-bubble').forEach(b => b.remove());

    const bubble = document.createElement('div');
    bubble.className = 'player-reaction-bubble';
    bubble.textContent = emoji;

    targetEl.style.position = 'relative';
    targetEl.appendChild(bubble);

    Sound.click();

    setTimeout(() => {
      bubble.remove();
    }, 3000);
  }

  // ── Show / hide attack banner ──
  function showAttackBanner(attackerName) {
    DOM.attackSub.textContent = `${attackerName} caused an ATTACK!`;
    DOM.attackBanner.classList.remove('hidden');
    Animations.flashAttack();
    Sound.attack();
  }

  function hideAttackBanner() {
    DOM.attackBanner.classList.add('hidden');
  }

  // ── Update common pile count ──
  function updateCommonPile(count) {
    DOM.commonPileCount.textContent = count;
    DOM.hudCommonCount.textContent = `${count} cards`;
  }

  // ── Update HUD status text ──
  function setStatus(text) {
    DOM.hudStatus.textContent = text;
  }

  // ── Update turn indicator ──
  function setTurn(playerName, isMyTurn) {
    if (playerName === 'Your' || playerName === 'You') {
      DOM.turnText.textContent = 'Your Turn';
    } else {
      const cleanName = String(playerName || '').replace(/'s$/, '');
      DOM.turnText.textContent = `${cleanName}'s Turn`;
    }
    if (typeof isMyTurn === 'boolean') {
      _isMyTurn = isMyTurn;
      _updateActionBar(_isMyTurn, _legalSuit);
    }
  }

  // ── Self attack pile (cards won in attack) ──
  function updateSelfAttackPile(count) {
    if (count > 0) {
      DOM.selfAttackZone.style.display = 'flex';
      DOM.selfAttackCount.textContent = count;
    } else {
      DOM.selfAttackZone.style.display = 'none';
    }
  }

  // ── Flash a player's avatar (got cards / won round) ──
  function flashOpponentAvatar(playerId, color) {
    const el = document.getElementById(`opp-avatar-${playerId}`);
    if (el) Animations.flash(el, color || 'rgba(201,168,76,0.6)');
  }

  function flashSelfAvatar(color) {
    Animations.flash(DOM.selfAvatar, color || 'rgba(201,168,76,0.6)');
  }

  return {
    init,
    renderPlayers,
    renderOpponents,
    updateOpponent,
    renderHand,
    addPlayedCard,
    clearPlayedCards,
    syncPlayedCards,
    showPlayerReaction,
    showAttackBanner,
    hideAttackBanner,
    updateCommonPile,
    setStatus,
    setTurn,
    updateSelfAttackPile,
    flashOpponentAvatar,
    flashSelfAvatar,
    updatePlayerStatus,
    openInGameMenu,
    closeInGameMenu,
    resetPlayInFlight,
    bindEvents: _bindTableEvents,
  };
})();

// Auto-bind table and menu events on DOM ready
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (typeof TableUI !== 'undefined' && TableUI.bindEvents) TableUI.bindEvents();
    });
  } else {
    if (typeof TableUI !== 'undefined' && TableUI.bindEvents) TableUI.bindEvents();
  }
}
