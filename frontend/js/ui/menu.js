/**
 * KAZHUDHAI CLUB — menu.js
 * Main menu UI logic, modals, settings, setup selectors
 */
const MenuUI = (() => {

  // ── State ──
  let offlineSetup = { playerCount: 4, deckCount: 1, difficulty: 'medium' };

  // ── Init ──
  function init() {
    _bindMainMenu();
    _bindOfflineSetup();
    _bindOnlineLobby();
    _bindSpectateModal();
    _bindWaitingRoom();
    _bindRules();
    _bindSettings();
    _loadSavedPrefs();
    _applyTheme(Storage.getSettings().theme);
  }

  // ── Main Menu Buttons ──
  function _bindMainMenu() {
    document.getElementById('btn-play-offline').addEventListener('click', () => {
      Sound.unlock(); Sound.click();
      showModal('modal-offline-setup');
    });

    document.getElementById('btn-play-online').addEventListener('click', () => {
      Sound.unlock(); Sound.click();
      if (typeof OnlineClient !== 'undefined' && OnlineClient.initConnection) {
        OnlineClient.initConnection();
      }
      showModal('modal-online-lobby');
    });

    const spectateBtn = document.getElementById('btn-spectate-menu');
    if (spectateBtn) {
      spectateBtn.addEventListener('click', () => {
        Sound.unlock(); Sound.click();
        if (typeof OnlineClient !== 'undefined' && OnlineClient.initConnection) {
          OnlineClient.initConnection();
        }
        const errEl = document.getElementById('spectate-error-msg');
        if (errEl) {
          errEl.textContent = '';
          errEl.classList.add('hidden');
        }
        const nameEl = document.getElementById('spectate-name-input');
        if (nameEl && !nameEl.value.trim()) {
          nameEl.value = Storage.getPlayerName() || 'Spectator';
        }
        showModal('modal-spectate');
      });
    }

    document.getElementById('btn-rules').addEventListener('click', () => {
      Sound.click();
      showModal('modal-rules');
    });

    document.getElementById('btn-settings').addEventListener('click', () => {
      Sound.click();
      showModal('modal-settings');
    });
  }

  // ── Offline Setup Modal ──
  function _bindOfflineSetup() {
    document.getElementById('offline-setup-close').addEventListener('click', () => hideModal('modal-offline-setup'));
    document.getElementById('modal-offline-setup').addEventListener('click', e => {
      if (e.target === e.currentTarget) hideModal('modal-offline-setup');
    });

    // Player count selector
    _bindSelector('player-count-selector', val => {
      offlineSetup.playerCount = +val;
      Storage.saveLastPlayerCount(+val);
    });

    // Deck count selector
    _bindSelector('deck-count-selector', val => {
      offlineSetup.deckCount = +val;
      Storage.saveLastDeckCount(+val);
      _updateCardCountHint(+val);
    });

    // Difficulty selector
    _bindSelector('difficulty-selector', val => {
      offlineSetup.difficulty = val;
      Storage.saveLastDifficulty(val);
    });

    // Start game
    document.getElementById('btn-start-offline').addEventListener('click', () => {
      const name = document.getElementById('offline-player-name').value.trim() || 'Player';
      Storage.savePlayerName(name);
      Sound.click();
      hideModal('modal-offline-setup');
      // Notify main app
      App.startOfflineGame({
        playerName: name,
        playerCount: offlineSetup.playerCount,
        deckCount: offlineSetup.deckCount,
        difficulty: offlineSetup.difficulty,
      });
    });
  }

  function _bindSelector(containerId, onChange) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.addEventListener('click', e => {
      const btn = e.target.closest('.sel-btn');
      if (!btn) return;

      container.querySelectorAll('.sel-btn').forEach(b => delete b.dataset.selected);
      btn.dataset.selected = true;
      Sound.click();
      onChange(btn.dataset.value);
    });
  }

  function _updateCardCountHint(deckCount) {
    const totalCards = 52 * deckCount - (deckCount - 1);
    const hint = document.getElementById('deck-card-count');
    if (hint) hint.textContent = `${deckCount} deck${deckCount > 1 ? 's' : ''} = ${totalCards} cards`;
  }

  // ── Online Lobby Modal ──
  let onlinePrivateSetup = { playerCount: 4, deckCount: 1 };
  let onlinePublicSetup  = { playerCount: 4, deckCount: 1 };

  function _bindOnlineLobby() {
    document.getElementById('online-lobby-close').addEventListener('click', () => hideModal('modal-online-lobby'));
    document.getElementById('modal-online-lobby').addEventListener('click', e => {
      if (e.target === e.currentTarget) hideModal('modal-online-lobby');
    });

    // Tab switching: Create Private, Join Private, Public Rooms
    document.querySelectorAll('.online-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.online-tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.online-tab-pane').forEach(p => {
          p.classList.add('hidden');
          p.classList.remove('active');
        });

        btn.classList.add('active');
        const targetTab = document.getElementById(btn.dataset.tab);
        if (targetTab) {
          targetTab.classList.remove('hidden');
          targetTab.classList.add('active');
        }
        Sound.click();

        if (btn.dataset.tab === 'tab-public-rooms') {
          _fetchPublicRooms();
        }
      });
    });

    // Selectors for Private Room setup
    _bindSelector('online-private-players', val => {
      onlinePrivateSetup.playerCount = +val;
    });

    _bindSelector('online-private-decks', val => {
      onlinePrivateSetup.deckCount = +val;
      const totalCards = 52 * (+val) - ((+val) - 1);
      const hint = document.getElementById('online-deck-card-count');
      if (hint) hint.textContent = `${val} deck${val > 1 ? 's' : ''} = ${totalCards} cards (Single A♠)`;
    });

    // Selectors for Public Room creation
    _bindSelector('online-public-players', val => {
      onlinePublicSetup.playerCount = +val;
    });

    _bindSelector('online-public-decks', val => {
      onlinePublicSetup.deckCount = +val;
    });

    // Toggle Public Room Creation Form
    const togglePublicBtn = document.getElementById('btn-create-public-toggle');
    const publicPanel = document.getElementById('create-public-panel');
    if (togglePublicBtn && publicPanel) {
      togglePublicBtn.addEventListener('click', () => {
        publicPanel.classList.toggle('hidden');
        togglePublicBtn.textContent = publicPanel.classList.contains('hidden') ? '+ New Public Room' : '✕ Cancel';
        Sound.click();
      });
    }

    // Refresh Public Rooms List
    const refreshBtn = document.getElementById('btn-refresh-public');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        Sound.click();
        _fetchPublicRooms();
      });
    }

    // 1. Create Private Room
    const createPrivBtn = document.getElementById('btn-create-private-room');
    if (createPrivBtn) {
      createPrivBtn.addEventListener('click', () => {
        const name = document.getElementById('online-player-name').value.trim() || 'Player';
        Storage.savePlayerName(name);
        Sound.click();

        const origContent = createPrivBtn.innerHTML;
        createPrivBtn.disabled = true;
        createPrivBtn.innerHTML = '<span>⏳</span> Creating Room…';

        App.createOnlineRoom({
          playerName: name,
          isPrivate: true,
          maxPlayers: onlinePrivateSetup.playerCount,
          deckCount: onlinePrivateSetup.deckCount,
        }, () => {
          createPrivBtn.disabled = false;
          createPrivBtn.innerHTML = origContent;
        });
      });
    }

    // 2. Join Private Room
    const joinPrivBtn = document.getElementById('btn-join-private-room');
    const roomInput   = document.getElementById('private-room-code-input');

    function doJoinPrivateRoom() {
      const name = document.getElementById('online-player-name').value.trim() || 'Player';
      const code = (roomInput.value || '').replace(/\s+/g, '').toUpperCase();
      roomInput.value = code;

      if (code.length < 4) {
        showToast('Please enter a valid room code (e.g. KZ1234)', 'error');
        Animations.shake(roomInput);
        roomInput.focus();
        return;
      }

      Storage.savePlayerName(name);
      Sound.click();

      const origContent = joinPrivBtn.innerHTML;
      joinPrivBtn.disabled = true;
      joinPrivBtn.innerHTML = '<span>⏳</span> Joining…';

      App.joinOnlineRoom({ playerName: name, roomCode: code }, () => {
        joinPrivBtn.disabled = false;
        joinPrivBtn.innerHTML = origContent;
      });
    }

    if (joinPrivBtn) {
      joinPrivBtn.addEventListener('click', doJoinPrivateRoom);
    }

    if (roomInput) {
      roomInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          doJoinPrivateRoom();
        }
      });
      // Normalize pasted/typed code cleanly without breaking mobile IME typing
      roomInput.addEventListener('blur', () => {
        roomInput.value = roomInput.value.replace(/\s+/g, '').toUpperCase().slice(0, 6);
      });
    }

    // 3. Create Public Room
    const createPubBtn = document.getElementById('btn-create-public-room');
    if (createPubBtn) {
      createPubBtn.addEventListener('click', () => {
        const name = document.getElementById('online-player-name').value.trim() || 'Player';
        Storage.savePlayerName(name);
        Sound.click();

        const origContent = createPubBtn.innerHTML;
        createPubBtn.disabled = true;
        createPubBtn.innerHTML = '<span>⏳</span> Launching…';

        App.createOnlineRoom({
          playerName: name,
          isPrivate: false,
          maxPlayers: onlinePublicSetup.playerCount,
          deckCount: onlinePublicSetup.deckCount,
        }, () => {
          createPubBtn.disabled = false;
          createPubBtn.innerHTML = origContent;
        });
      });
    }
  }

  function _fetchPublicRooms() {
    const listEl = document.getElementById('public-room-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="empty-rooms-hint">Looking for open public rooms…</div>';

    fetch('/api/rooms/public')
      .then(res => res.json())
      .then(rooms => {
        if (!rooms || rooms.length === 0) {
          listEl.innerHTML = '<div class="empty-rooms-hint">No active public rooms right now. Create one above!</div>';
          return;
        }

        listEl.innerHTML = '';
        rooms.forEach(r => {
          const card = document.createElement('div');
          card.className = 'public-room-card';
          card.innerHTML = `
            <div class="room-card-info">
              <div class="room-card-title">
                <span>Room</span>
                <span class="room-code-tag">${r.code}</span>
              </div>
              <div class="room-card-meta">
                <span>👤 Host: ${r.hostName}</span>
                <span>🪑 ${r.playerCount}/${r.maxPlayers} Seats</span>
                <span>🃏 ${r.deckCount} Deck${r.deckCount > 1 ? 's' : ''}</span>
              </div>
            </div>
            <button class="action-btn-sm" ${r.playerCount >= r.maxPlayers ? 'disabled' : ''}>
              ${r.playerCount >= r.maxPlayers ? 'Full' : 'Join'}
            </button>
          `;

          const joinBtn = card.querySelector('button');
          if (joinBtn && r.playerCount < r.maxPlayers) {
            joinBtn.addEventListener('click', () => {
              const name = document.getElementById('online-player-name').value.trim() || 'Player';
              Storage.savePlayerName(name);
              Sound.click();
              const origText = joinBtn.textContent;
              joinBtn.disabled = true;
              joinBtn.textContent = '…';
              App.joinOnlineRoom({ playerName: name, roomCode: r.code }, () => {
                joinBtn.disabled = false;
                joinBtn.textContent = origText;
              });
            });
          }

          listEl.appendChild(card);
        });
      })
      .catch(() => {
        listEl.innerHTML = '<div class="empty-rooms-hint">No public rooms found. You can create the first room!</div>';
      });
  }

  // ── Rules Modal ──
  function _bindRules() {
    document.getElementById('rules-close').addEventListener('click', () => hideModal('modal-rules'));
    document.getElementById('modal-rules').addEventListener('click', e => {
      if (e.target === e.currentTarget) hideModal('modal-rules');
    });
  }

  // ── Settings Modal ──
  function _bindSettings() {
    document.getElementById('settings-close').addEventListener('click', () => hideModal('modal-settings'));
    document.getElementById('modal-settings').addEventListener('click', e => {
      if (e.target === e.currentTarget) hideModal('modal-settings');
    });

    // SFX toggle
    document.getElementById('setting-sfx').addEventListener('change', e => {
      Sound.setEnabled(e.target.checked);
      Storage.saveSettings({ sfx: e.target.checked });
      Sound.click();
    });

    // Animations toggle
    document.getElementById('setting-animations').addEventListener('change', e => {
      Animations.setEnabled(e.target.checked);
      Storage.saveSettings({ animations: e.target.checked });
    });

    // Music toggle
    document.getElementById('setting-music').addEventListener('change', e => {
      Storage.saveSettings({ music: e.target.checked });
      Sound.setMusicEnabled(e.target.checked);
    });

    // Theme picker
    document.querySelectorAll('.theme-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const theme = btn.dataset.theme;
        _applyTheme(theme);
        Storage.saveSettings({ theme });
        Sound.click();
      });
    });

    // In-game shortcuts
    const rulesIngame    = document.getElementById('btn-rules-ingame');
    const settingsIngame = document.getElementById('btn-settings-ingame');
    if (rulesIngame) {
      rulesIngame.addEventListener('click', () => {
        if (typeof TableUI !== 'undefined' && TableUI.closeInGameMenu) TableUI.closeInGameMenu();
        showModal('modal-rules');
      });
    }
    if (settingsIngame) {
      settingsIngame.addEventListener('click', () => {
        if (typeof TableUI !== 'undefined' && TableUI.closeInGameMenu) TableUI.closeInGameMenu();
        showModal('modal-settings');
      });
    }
  }

  function _applyTheme(theme) {
    document.body.dataset.theme = theme || 'green';
    document.querySelectorAll('.theme-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.theme === (theme || 'green'));
    });
  }

  function _loadSavedPrefs() {
    const s = Storage.getSettings();
    Sound.setEnabled(s.sfx);
    Sound.setMusicEnabled(s.music);
    Animations.setEnabled(s.animations);

    document.getElementById('setting-sfx').checked        = s.sfx;
    document.getElementById('setting-music').checked      = s.music;
    document.getElementById('setting-animations').checked = s.animations;

    // Restore player name
    const savedName = Storage.getPlayerName();
    document.getElementById('offline-player-name').value = savedName;
    document.getElementById('online-player-name').value  = savedName;
    const specNameEl = document.getElementById('spectate-name-input');
    if (specNameEl) specNameEl.value = savedName || 'Spectator';

    // Restore last selections
    offlineSetup.playerCount = Storage.getLastPlayerCount();
    offlineSetup.deckCount   = Storage.getLastDeckCount();
    offlineSetup.difficulty  = Storage.getLastDifficulty();

    _restoreSelector('player-count-selector', String(offlineSetup.playerCount));
    _restoreSelector('deck-count-selector',   String(offlineSetup.deckCount));
    _restoreSelector('difficulty-selector',   offlineSetup.difficulty);
    _updateCardCountHint(offlineSetup.deckCount);
  }

  function _restoreSelector(containerId, value) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.sel-btn').forEach(btn => {
      delete btn.dataset.selected;
      if (btn.dataset.value === value) btn.dataset.selected = true;
    });
  }

  // ── Stage 4: Spectate Modal ──
  function _bindSpectateModal() {
    const closeBtn = document.getElementById('spectate-modal-close');
    const overlay  = document.getElementById('modal-spectate');
    if (closeBtn) closeBtn.addEventListener('click', () => hideModal('modal-spectate'));
    if (overlay) {
      overlay.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) hideModal('modal-spectate');
      });
    }

    const joinBtn   = document.getElementById('btn-join-spectate');
    const codeInput = document.getElementById('spectate-room-code-input');
    const nameInput = document.getElementById('spectate-name-input');
    const errEl     = document.getElementById('spectate-error-msg');

    function showSpecError(msg) {
      if (errEl) {
        errEl.textContent = msg;
        errEl.classList.remove('hidden');
      }
      showToast(msg, 'error', 3000);
    }

    function clearSpecError() {
      if (errEl) {
        errEl.textContent = '';
        errEl.classList.add('hidden');
      }
    }

    function doJoinSpectate() {
      clearSpecError();
      const name = (nameInput ? nameInput.value : '').trim() || 'Spectator';
      const code = (codeInput ? codeInput.value : '').replace(/\s+/g, '').toUpperCase();
      if (codeInput) codeInput.value = code;

      if (code.length < 4) {
        showSpecError('Please enter a valid room code (e.g. KZ1234)');
        if (codeInput) {
          Animations.shake(codeInput);
          codeInput.focus();
        }
        return;
      }

      Storage.savePlayerName(name);
      Sound.click();

      const origHTML = joinBtn ? joinBtn.innerHTML : '';
      if (joinBtn) {
        joinBtn.disabled = true;
        joinBtn.innerHTML = '<span>⏳</span> Joining as Spectator…';
      }

      App.joinAsSpectator({ roomCode: code, spectatorName: name }, (res) => {
        if (joinBtn) {
          joinBtn.disabled = false;
          joinBtn.innerHTML = origHTML;
        }
        if (res && !res.success) {
          showSpecError(res.message || 'Room not found or unavailable for spectating');
        } else if (codeInput) {
          codeInput.value = '';
        }
      });
    }

    if (joinBtn) {
      joinBtn.addEventListener('click', doJoinSpectate);
    }
    if (codeInput) {
      codeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          doJoinSpectate();
        }
      });
      codeInput.addEventListener('blur', () => {
        codeInput.value = codeInput.value.replace(/\s+/g, '').toUpperCase().slice(0, 6);
      });
    }
  }

  /**
   * Stage 2: Open the exact existing Main Menu -> Play Online -> Create Private Room workflow
   * with fresh default settings (no previous match players or decks carried over).
   */
  function openCreatePrivateRoomWorkflow() {
    onlinePrivateSetup = { playerCount: 4, deckCount: 1 };
    _restoreSelector('online-private-players', '4');
    _restoreSelector('online-private-decks', '1');
    const hint = document.getElementById('online-deck-card-count');
    if (hint) hint.textContent = '1 deck = 52 cards (Single A♠)';

    // Activate "Create Private Room" tab
    document.querySelectorAll('.online-tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === 'tab-create-private');
    });
    document.querySelectorAll('.online-tab-pane').forEach(p => {
      const isCreatePriv = p.id === 'tab-create-private';
      p.classList.toggle('active', isCreatePriv);
      p.classList.toggle('hidden', !isCreatePriv);
    });

    if (typeof OnlineClient !== 'undefined' && OnlineClient.initConnection) {
      OnlineClient.initConnection();
    }
    showModal('modal-online-lobby');
  }

  // ── Waiting Room / Lobby Modal ──
  let _seenLobbyMsgIds = new Set();

  function _bindWaitingRoom() {
    const copyBtn = document.getElementById('btn-copy-room-code');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const code = document.getElementById('waiting-room-code').textContent.trim();
        if (code && code !== 'KZ----') {
          navigator.clipboard?.writeText(code).then(() => {
            showToast(`Room code ${code} copied to clipboard!`, 'success', 2000);
            Sound.click();
          }).catch(() => {
            showToast(`Code: ${code}`, 'info', 3000);
          });
        }
      });
    }

    const leaveBtn = document.getElementById('btn-leave-waiting-room');
    if (leaveBtn) {
      leaveBtn.addEventListener('click', () => {
        Sound.click();
        OnlineClient.leaveRoom();
        hideWaitingRoom();
        showToast('Left room lobby', 'info', 2000);
      });
    }

    const startBtn = document.getElementById('btn-host-start-game');
    if (startBtn) {
      startBtn.addEventListener('click', () => {
        Sound.click();
        OnlineClient.startGame();
      });
    }

    const chatForm = document.getElementById('lobby-chat-form');
    const chatInput = document.getElementById('lobby-chat-input');
    if (chatForm && chatInput) {
      chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;
        OnlineClient.sendLobbyChatMessage(text, (res) => {
          if (res && !res.success) {
            showToast(res.message || 'Failed to send message', 'error', 2000);
          }
        });
        chatInput.value = '';
      });
    }
  }

  function showWaitingRoom(roomSummary, myPlayerId, isSpectator = false) {
    showModal('modal-room-waiting');
    updateWaitingRoom(roomSummary, myPlayerId, isSpectator);
  }

  function hideWaitingRoom() {
    hideModal('modal-room-waiting');
  }

  function updateWaitingRoom(roomSummary, myPlayerId, isSpectator = false) {
    if (!roomSummary) return;

    // Room code
    const codeEl = document.getElementById('waiting-room-code');
    if (codeEl) codeEl.textContent = roomSummary.code;

    // Badge
    const badgeEl = document.getElementById('waiting-room-badge');
    if (badgeEl) {
      const roleTag = isSpectator ? ' · 👁️ Spectating' : '';
      badgeEl.textContent = (roomSummary.is_private ? '🔒 Private Room' : '🌍 Public Room') + roleTag;
      badgeEl.className = `room-badge ${roomSummary.is_private ? 'private' : 'public'}`;
    }

    // Counts
    const countEl = document.getElementById('waiting-player-count');
    if (countEl) countEl.textContent = roomSummary.players ? roomSummary.players.length : roomSummary.player_count;

    const maxEl = document.getElementById('waiting-max-players');
    if (maxEl) maxEl.textContent = roomSummary.max_players;

    const deckEl = document.getElementById('waiting-deck-info');
    if (deckEl) {
      const totalCards = 52 * roomSummary.deck_count - (roomSummary.deck_count - 1);
      deckEl.textContent = `${roomSummary.deck_count} Deck${roomSummary.deck_count > 1 ? 's' : ''} (${totalCards} cards)`;
    }

    // Stage 4: Live spectators list in waiting room
    const specCountEl = document.getElementById('waiting-spectator-count');
    const specNamesEl = document.getElementById('waiting-spectator-names');
    const specList = Array.isArray(roomSummary.spectators) ? roomSummary.spectators : [];
    const specCount = typeof roomSummary.spectator_count === 'number' ? roomSummary.spectator_count : specList.length;
    if (specCountEl) specCountEl.textContent = String(specCount);
    if (specNamesEl) {
      specNamesEl.innerHTML = '';
      if (specList.length === 0) {
        const hint = document.createElement('span');
        hint.className = 'empty-spectators-hint';
        hint.textContent = 'No spectators watching yet';
        specNamesEl.appendChild(hint);
      } else {
        specList.forEach(s => {
          const pill = document.createElement('span');
          pill.className = 'waiting-spectator-pill';
          pill.textContent = `👁️ ${s.name}`;
          specNamesEl.appendChild(pill);
        });
      }
    }

    // Render players
    const gridEl = document.getElementById('waiting-players-grid');
    if (gridEl && roomSummary.players) {
      gridEl.innerHTML = '';
      roomSummary.players.forEach((p) => {
        const card = document.createElement('div');
        const isSelf = !isSpectator && (p.id === myPlayerId);
        const status = p.status || (p.connected ? 'connected' : 'disconnected');
        const badgeText = p.is_host ? 'Host' : (status === 'connected' ? 'Ready' : (status === 'reconnecting' ? 'Reconnecting' : 'Left'));
        card.className = `waiting-player-card ${isSelf ? 'is-self' : ''}`;
        card.dataset.playerId = p.id;

        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'waiting-player-avatar';
        avatarDiv.textContent = p.is_host ? '👑' : '👤';

        const nameDiv = document.createElement('div');
        nameDiv.className = 'waiting-player-name';
        const dot = document.createElement('span');
        dot.className = `player-status-dot status-${status}`;
        const nameSpan = document.createElement('span');
        nameSpan.textContent = isSelf ? `${p.name} (You)` : p.name;
        nameDiv.appendChild(dot);
        nameDiv.appendChild(nameSpan);

        const badgeDiv = document.createElement('div');
        badgeDiv.className = `waiting-player-badge status-${status}`;
        badgeDiv.textContent = badgeText;

        card.appendChild(avatarDiv);
        card.appendChild(nameDiv);
        card.appendChild(badgeDiv);
        gridEl.appendChild(card);
      });
    }

    // Render lobby activity history
    const activityListEl = document.getElementById('waiting-activity-list');
    if (activityListEl && roomSummary.activity_log) {
      if (roomSummary.activity_log.length === 0) {
        activityListEl.innerHTML = '<div class="empty-activity-hint">Waiting for room events…</div>';
      } else {
        activityListEl.innerHTML = '';
        roomSummary.activity_log.forEach(act => {
          const item = document.createElement('div');
          item.className = 'waiting-activity-item';
          const iconSpan = document.createElement('span');
          iconSpan.textContent = act.icon || 'ℹ️';
          const msgSpan = document.createElement('span');
          msgSpan.textContent = act.message || '';
          const timeSpan = document.createElement('span');
          timeSpan.className = 'activity-time';
          timeSpan.textContent = act.timestamp || '';
          item.appendChild(iconSpan);
          item.appendChild(msgSpan);
          item.appendChild(timeSpan);
          activityListEl.appendChild(item);
        });
      }
    }

    // Host controls (never shown to spectators)
    const isMeHost = !isSpectator && (roomSummary.host_id === myPlayerId);
    const playerCount = roomSummary.players ? roomSummary.players.length : roomSummary.player_count;
    const canStart = isMeHost && playerCount >= 2;

    const startBtn = document.getElementById('btn-host-start-game');
    const noticeEl = document.getElementById('waiting-status-notice');

    if (startBtn) {
      if (!isMeHost) {
        startBtn.style.display = 'none';
      } else {
        startBtn.style.display = 'block';
        startBtn.disabled = !canStart;
        startBtn.textContent = canStart ? '🚀 Start Game' : `Waiting for players (${playerCount}/2 min)`;
      }
    }

    if (noticeEl) {
      if (isSpectator) {
        noticeEl.textContent = '👁️ Spectating lobby — you will automatically enter live view when the host starts the match.';
      } else if (isMeHost) {
        noticeEl.textContent = canStart
          ? 'Ready to start! Click the button below.'
          : 'Waiting for at least 1 more player to join…';
      } else {
        noticeEl.textContent = 'Waiting for host to start the game…';
      }
    }
  }

  // ── Modal Helpers ──
  function showModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const wasHidden = el.classList.contains('hidden');
    el.classList.remove('hidden');
    if (wasHidden && typeof App !== 'undefined' && typeof App.onModalOpened === 'function') {
      App.onModalOpened(id);
    }
  }

  function hideModal(id, options) {
    const el = document.getElementById(id);
    if (!el) return;
    const wasVisible = !el.classList.contains('hidden');
    el.classList.add('hidden');
    if (wasVisible && typeof App !== 'undefined' && typeof App.onModalClosed === 'function') {
      App.onModalClosed(id, options);
    }
  }

  function addLobbyChatMessage(msg, myPlayerId) {
    if (!msg) return;
    if (msg.id && _seenLobbyMsgIds.has(msg.id)) return;
    if (msg.id) _seenLobbyMsgIds.add(msg.id);

    const listEl = document.getElementById('lobby-chat-messages');
    if (!listEl) return;

    // Remove empty placeholder
    const hint = listEl.querySelector('.empty-chat-hint');
    if (hint) hint.remove();

    const isSelf = !!(myPlayerId && msg.sender_id === myPlayerId);
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

  function clearLobbyChat() {
    _seenLobbyMsgIds.clear();
    const listEl = document.getElementById('lobby-chat-messages');
    if (listEl) {
      listEl.innerHTML = '<div class="empty-chat-hint">No messages yet. Say hello to your opponents!</div>';
    }
    const inputEl = document.getElementById('lobby-chat-input');
    if (inputEl) {
      inputEl.value = '';
    }
  }

  return {
    init,
    showModal,
    hideModal,
    showWaitingRoom,
    updateWaitingRoom,
    hideWaitingRoom,
    addLobbyChatMessage,
    clearLobbyChat,
    openCreatePrivateRoomWorkflow,
  };
})();
