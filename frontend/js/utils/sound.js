/**
 * KAZHUDHAI CLUB — sound.js
 * Complete Web Audio API Sound & Procedural Music Engine for Stage 7.
 * Provides rich synthesized sound effects, authentic card flips, dramatic attacks,
 * signature "HEE-HAW" KAZHUDHAI bray, and ambient relaxing casino background music.
 * Zero external audio files required — 100% reliable across all browsers & devices.
 */
const Sound = (() => {

  let ctx            = null;
  let sfxEnabled     = true;
  let musicEnabled   = false;
  let bgmGain        = null;
  let bgmInterval    = null;
  let currentChordIdx = 0;

  function getCtx() {
    if (!ctx) {
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        ctx = new AudioContext();
      } catch (e) {
        return null;
      }
    }
    if (ctx.state === 'suspended') {
      ctx.resume();
    }
    return ctx;
  }

  // ── Tone Generator Helper ──
  function tone({
    freq = 440,
    type = 'sine',
    duration = 0.2,
    volume = 0.25,
    attack = 0.01,
    decay = 0.1,
    detune = 0,
    destination = null,
  } = {}) {
    if (!sfxEnabled) return;
    const c = getCtx();
    if (!c) return;

    try {
      const osc = c.createOscillator();
      const gain = c.createGain();

      osc.type = type;
      osc.frequency.setValueAtTime(freq, c.currentTime);
      if (detune) osc.detune.setValueAtTime(detune, c.currentTime);

      const targetDest = destination || c.destination;
      osc.connect(gain);
      gain.connect(targetDest);

      const now = c.currentTime;
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(volume, now + attack);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(attack + 0.01, duration));

      osc.start(now);
      osc.stop(now + duration + 0.05);
    } catch (e) {
      // Audio node cleanup
    }
  }

  // ── Procedural Sound Effects (SFX) ──
  const SFX = {

    /**
     * Crisp playing card flick on felt.
     */
    cardPlay() {
      if (!sfxEnabled) return;
      const c = getCtx();
      if (!c) return;

      // Filtered noise snap + soft low pop
      tone({ freq: 850, type: 'triangle', duration: 0.08, volume: 0.25, attack: 0.005 });
      tone({ freq: 220, type: 'sine', duration: 0.1, volume: 0.2, attack: 0.01 });
    },

    /**
     * Card dealt from deck.
     */
    cardDeal() {
      if (!sfxEnabled) return;
      tone({ freq: 1100, type: 'triangle', duration: 0.06, volume: 0.18, attack: 0.003 });
    },

    /**
     * Multi-card deal flutter.
     */
    dealSequence(count = 5) {
      if (!sfxEnabled) return;
      for (let i = 0; i < Math.min(count, 8); i++) {
        setTimeout(() => SFX.cardDeal(), i * 65);
      }
    },

    /**
     * Dramatic attack alarm chord with brass rumble.
     */
    attack() {
      if (!sfxEnabled) return;
      const c = getCtx();
      if (!c) return;

      // Heavy dissonance
      tone({ freq: 140, type: 'sawtooth', duration: 0.5, volume: 0.35, attack: 0.02 });
      tone({ freq: 196, type: 'sawtooth', duration: 0.45, volume: 0.3, attack: 0.03 });
      tone({ freq: 294, type: 'square', duration: 0.35, volume: 0.25, attack: 0.05 });

      setTimeout(() => {
        tone({ freq: 95, type: 'sawtooth', duration: 0.6, volume: 0.4, attack: 0.02 });
      }, 120);
    },

    /**
     * Section 8 Safe / Round Win celebration chime.
     */
    playerFinish() {
      if (!sfxEnabled) return;
      const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
      notes.forEach((freq, idx) => {
        setTimeout(() => {
          tone({ freq, type: 'sine', duration: 0.35, volume: 0.25, attack: 0.01 });
        }, idx * 90);
      });
    },

    /**
     * Full game winner / safe ranking fanfare.
     */
    win() {
      if (!sfxEnabled) return;
      const chords = [
        [440, 554.37, 659.25],         // A major
        [493.88, 622.25, 739.99],     // B major
        [554.37, 659.25, 830.61],     // C#m
        [659.25, 830.61, 987.77, 1318.51] // E major peak
      ];
      chords.forEach((chord, step) => {
        setTimeout(() => {
          chord.forEach(f => tone({ freq: f, type: 'triangle', duration: 0.4, volume: 0.25 }));
        }, step * 160);
      });
    },

    /**
     * Procedural "HEE-HAW" comedic donkey sound for KAZHUDHAI declaration!
     */
    kazhudhai() {
      if (!sfxEnabled) return;
      const c = getCtx();
      if (!c) return;

      // Part 1: High bray "HEEE"
      const now = c.currentTime;
      try {
        const osc1 = c.createOscillator();
        const gain1 = c.createGain();
        osc1.type = 'sawtooth';
        osc1.frequency.setValueAtTime(600, now);
        osc1.frequency.exponentialRampToValueAtTime(1050, now + 0.25);
        osc1.frequency.exponentialRampToValueAtTime(800, now + 0.45);

        gain1.gain.setValueAtTime(0.001, now);
        gain1.gain.linearRampToValueAtTime(0.35, now + 0.05);
        gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.45);

        osc1.connect(gain1);
        gain1.connect(c.destination);
        osc1.start(now);
        osc1.stop(now + 0.5);

        // Part 2: Low guttural "HAWW"
        const hawTime = now + 0.45;
        const osc2 = c.createOscillator();
        const gain2 = c.createGain();
        osc2.type = 'sawtooth';
        osc2.frequency.setValueAtTime(320, hawTime);
        osc2.frequency.exponentialRampToValueAtTime(140, hawTime + 0.4);

        gain2.gain.setValueAtTime(0.001, hawTime);
        gain2.gain.linearRampToValueAtTime(0.4, hawTime + 0.05);
        gain2.gain.exponentialRampToValueAtTime(0.001, hawTime + 0.5);

        osc2.connect(gain2);
        gain2.connect(c.destination);
        osc2.start(hawTime);
        osc2.stop(hawTime + 0.55);

        // Second bray repetition after 600ms
        setTimeout(() => {
          tone({ freq: 850, type: 'sawtooth', duration: 0.35, volume: 0.3 });
          setTimeout(() => tone({ freq: 160, type: 'sawtooth', duration: 0.4, volume: 0.35 }), 200);
        }, 650);

      } catch (e) {}
    },

    /**
     * Card collection sweep sound.
     */
    collect() {
      if (!sfxEnabled) return;
      tone({ freq: 380, type: 'triangle', duration: 0.25, volume: 0.22, attack: 0.02, decay: 0.1 });
    },

    /**
     * Button click / selector tick.
     */
    click() {
      if (!sfxEnabled) return;
      tone({ freq: 880, type: 'sine', duration: 0.04, volume: 0.15, attack: 0.002 });
    },

    /**
     * Error buzz (illegal card or invalid move).
     */
    error() {
      if (!sfxEnabled) return;
      tone({ freq: 180, type: 'sawtooth', duration: 0.2, volume: 0.25, attack: 0.01 });
      setTimeout(() => tone({ freq: 140, type: 'sawtooth', duration: 0.2, volume: 0.25, attack: 0.01 }), 80);
    },

    /**
     * Shuffle sound.
     */
    shuffle() {
      if (!sfxEnabled) return;
      for (let i = 0; i < 6; i++) {
        setTimeout(() => tone({ freq: 500 + Math.random() * 400, type: 'triangle', duration: 0.05, volume: 0.15 }), i * 40);
      }
    }
  };

  // ── Procedural Ambient Casino Background Music (BGM) ──
  const BGM_CHORDS = [
    // Cmaj9: C3, G3, B3, E4, D5
    [130.81, 196.00, 246.94, 329.63, 587.33],
    // Am9: A2, E3, G3, C4, B4
    [110.00, 164.81, 196.00, 261.63, 493.88],
    // Fmaj7: F2, C3, E3, A3, G4
    [87.31, 130.81, 164.81, 220.00, 392.00],
    // G13sus: G2, D3, F3, B3, E4
    [98.00, 146.83, 174.61, 246.94, 329.63],
  ];

  function _playBgmChord(chordNotes) {
    if (!musicEnabled) return;
    const c = getCtx();
    if (!c) return;

    try {
      const filter = c.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(750, c.currentTime);

      if (!bgmGain) {
        bgmGain = c.createGain();
        bgmGain.gain.setValueAtTime(0.08, c.currentTime);
        bgmGain.connect(c.destination);
      }

      filter.connect(bgmGain);

      // Play soft arpeggio
      chordNotes.forEach((freq, idx) => {
        const osc = c.createOscillator();
        const noteGain = c.createGain();

        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, c.currentTime);

        const now = c.currentTime + idx * 0.12;
        noteGain.gain.setValueAtTime(0.001, now);
        noteGain.gain.linearRampToValueAtTime(0.07, now + 0.4);
        noteGain.gain.exponentialRampToValueAtTime(0.001, now + 2.7);

        osc.connect(noteGain);
        noteGain.connect(filter);

        osc.start(now);
        osc.stop(now + 2.8);
      });
    } catch (e) {}
  }

  function startBGM() {
    if (bgmInterval) return;
    const c = getCtx();
    if (!c) return;

    _playBgmChord(BGM_CHORDS[currentChordIdx]);
    bgmInterval = setInterval(() => {
      if (!musicEnabled) {
        stopBGM();
        return;
      }
      currentChordIdx = (currentChordIdx + 1) % BGM_CHORDS.length;
      _playBgmChord(BGM_CHORDS[currentChordIdx]);
    }, 3200);
  }

  function stopBGM() {
    if (bgmInterval) {
      clearInterval(bgmInterval);
      bgmInterval = null;
    }
  }

  function setMusicEnabled(val) {
    musicEnabled = val;
    if (musicEnabled) {
      startBGM();
    } else {
      stopBGM();
    }
  }

  function setEnabled(val) {
    sfxEnabled = val;
  }

  function isEnabled() {
    return sfxEnabled;
  }

  function isMusicEnabled() {
    return musicEnabled;
  }

  function unlock() {
    getCtx();
  }

  return {
    ...SFX,
    setEnabled,
    isEnabled,
    setMusicEnabled,
    isMusicEnabled,
    startBGM,
    stopBGM,
    unlock,
  };
})();
