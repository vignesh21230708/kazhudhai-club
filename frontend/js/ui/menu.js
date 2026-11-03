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
      const code = (roomInput.value || '').trim().toUpperCase();

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
      // Normalize to uppercase on blur without disturbing mobile IME typing
      roomInput.addEventListener('blur', () => {
        roomInput.value = roomInput.value.trim().toUpperCase();
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
    if (rulesIngame)    rulesIngame.addEventListener('click', () => { showModal('modal-rules'); });
    if (settingsIngame) settingsIngame.addEventListener('click', () => { showModal('modal-settings'); });
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

  // ── Waiting Room / Lobby Modal ──
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
  }

  function showWaitingRoom(roomSummary, myPlayerId) {
    showModal('modal-room-waiting');
    updateWaitingRoom(roomSummary, myPlayerId);
  }

  function hideWaitingRoom() {
    hideModal('modal-room-waiting');
  }

  function updateWaitingRoom(roomSummary, myPlayerId) {
    if (!roomSummary) return;

    // Room code
    const codeEl = document.getElementById('waiting-room-code');
    if (codeEl) codeEl.textContent = roomSummary.code;

    // Badge
    const badgeEl = document.getElementById('waiting-room-badge');
    if (badgeEl) {
      badgeEl.textContent = roomSummary.is_private ? '🔒 Private Room' : '🌍 Public Room';
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

    // Render players
    const gridEl = document.getElementById('waiting-players-grid');
    if (gridEl && roomSummary.players) {
      gridEl.innerHTML = '';
      roomSummary.players.forEach((p, idx) => {
        const card = document.createElement('div');
        const isSelf = p.id === myPlayerId;
        const status = p.status || (p.connected ? 'connected' : 'disconnected');
        const badgeText = p.is_host ? 'Host' : (status === 'connected' ? 'Ready' : (status === 'reconnecting' ? 'Reconnecting' : 'Left'));
        card.className = `waiting-player-card ${isSelf ? 'is-self' : ''}`;
        card.dataset.playerId = p.id;
        card.innerHTML = `
          <div class="waiting-player-avatar">${p.is_host ? '👑' : '👤'}</div>
          <div class="waiting-player-name">
            <span class="player-status-dot status-${status}"></span>
            <span>${p.name} ${isSelf ? '(You)' : ''}</span>
          </div>
          <div class="waiting-player-badge status-${status}">${badgeText}</div>
        `;
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
          item.innerHTML = `
            <span>${act.icon || 'ℹ️'}</span>
            <span>${act.message}</span>
            <span class="activity-time">${act.timestamp || ''}</span>
          `;
          activityListEl.appendChild(item);
        });
      }
    }

    // Host controls
    const isMeHost = (roomSummary.host_id === myPlayerId);
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
      if (isMeHost) {
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
    if (el) el.classList.remove('hidden');
  }

  function hideModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  }

  return {
    init,
    showModal,
    hideModal,
    showWaitingRoom,
    updateWaitingRoom,
    hideWaitingRoom,
  };
})();
