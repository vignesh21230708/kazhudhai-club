# 🃏 KAZHUDHAI CLUB

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://kazhudhai-club.onrender.com)
[![Status](https://img.shields.io/badge/Status-Online%20%E2%9C%94-brightgreen?style=for-the-badge)](https://kazhudhai-club.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

🎮 **Play Live Now:** **[https://kazhudhai-club.onrender.com](https://kazhudhai-club.onrender.com)**

> **"The Last Card Loses. The Last Player Holding Cards Becomes KAZHUDHAI."**

**KAZHUDHAI CLUB** is a realistic, authoritative full-stack multiplayer card game built with a modern web frontend (HTML5/CSS3/ES6+ JavaScript) and a Python backend (Flask & Flask-SocketIO). It supports both full **Offline play against AI opponents** and real-time **Online multiplayer with private rooms and public lobbies**.

---

## 🌟 Key Highlights & Feature Matrix

- **🎮 Dual Gameplay Modes**:
  - **Offline vs AI**: Play against 1 to 6 AI opponents with 3 selectable heuristics (**Easy**, **Medium**, **Hard**).
  - **Online Multiplayer**: Real-time SocketIO multiplayer with unique 6-character room codes (`KZ####`), public lobby discovery, and reconnection resilience.
- **🪑 Player Flexibility**: Minimum **2** and maximum **7** players. The host can start the game at any time with joined players ($\ge 2$) without waiting for all 7.
- **🃏 Multi-Deck Support**: Selection of **1 to 5 standard 52-card decks**.
- **✨ Authentic Single A♠ Rule**: Exactly **ONE** Ace of Spades ($A♠$) retained across all decks; extra $A♠$ cards removed; all other duplicates retained.
- **🔒 Zero Card Leakage**: Hidden card data of opponents is **never sent** over REST API responses or WebSocket payloads. Clients only receive their own hand.
- **🎵 Procedural Audio & Web Audio BGM**: 100% synthetic sound effects (card snaps, attack fanfare, Section 8 victory chimes, comical KAZHUDHAI donkey bray) and ambient lounge music.
- **📱 PWA & Android Ready**: Fully responsive for mobile phones and laptops, complete with Web App Manifest, Service Worker offline caching, and Capacitor configuration.

---

## 📐 Exact Game Mechanics & Formulas

### 1. Total Deck Formula
$$\text{Total Cards} = (52 \times N) - (N - 1)$$

| Decks ($N$) | Total Cards | Standard Cards | Deduplicated $A♠$ Removed |
| :---: | :---: | :---: | :---: |
| **1** | **52** | 52 | 0 |
| **2** | **103** | 104 | 1 |
| **3** | **154** | 156 | 2 |
| **4** | **205** | 208 | 3 |
| **5** | **256** | 260 | 4 |

### 2. Card Distribution
Cards are shuffled and distributed as follows:
1. Base share distributed equally among all joined players: $\lfloor \text{Total} / P \rfloor$.
2. Remainder cards distributed one-by-one sequentially starting from **Player 1 (index 0)**.
3. Every card is assigned a unique UUID4 internal ID.

### 3. Ranking Hierarchy & First Turn
$$A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2$$
- The player holding the unique **$A♠$** starts Round 1.

### 4. Normal Round (No Attack)
1. Lead player sets the **starting suit**.
2. Every active player must follow suit if they hold it.
3. If all follow suit, the round finishes normally.
4. Highest card of the starting suit wins.
5. All played cards move to the **common collected section** and are **permanently removed** from the game.
6. The round winner leads the next round.

### 5. Attack Round
1. If a player cannot follow the starting suit (void in that suit), they may play any off-suit card.
2. Playing off-suit triggers an immediate **ATTACK**.
3. The round terminates immediately; remaining players in the turn order are skipped.
4. Highest card of the starting suit wins the round.
5. **All played cards** (including the off-suit attack card) go directly into the **winner's hand**.
6. The winner leads the next round.

### 6. Earliest Played Duplicate Tiebreak
If duplicate highest cards of the starting suit are played (common in multi-deck games), the player who played their card **earliest in turn order** wins the trick.

### 7. Section 8: Last Card Pending Rule
A player who plays their last card is **NOT** immediately declared safe. Their status remains pending until round and collection completion:
- **Case A (Normal Round)**: The player wins or round finishes normally $\rightarrow$ cards go to common pile $\rightarrow$ player officially finishes and is **Safe**.
- **Case B (Attack Round)**: An attack occurs and this player wins with highest starting suit $\rightarrow$ trick cards return to their hand $\rightarrow$ player is **NOT safe** and continues playing.
- **Case C (Multiple Finishers)**: Hand counts are recalculated after collection. If the round winner also reached 0 cards, they receive priority finishing rank.
- **Clockwise Lead Transfer**: When the round winner officially finishes, lead passes clockwise to the next active player.
- **KAZHUDHAI**: When only 1 active player remains holding cards, that player is declared **KAZHUDHAI**!

---

## 🏛️ Project Architecture

```
d:\KAZHUDHAI Club\
├── backend/
│   ├── api/
│   │   └── offline_routes.py        # REST endpoints for offline AI gameplay
│   ├── game_engine/
│   │   ├── ai_player.py             # Easy, Medium, Hard AI heuristics
│   │   ├── deck.py                  # Deck builder, single A♠ deduplication, sorting
│   │   ├── distributor.py           # Equal + sequential remainder distribution
│   │   ├── game_state.py            # Authoritative game state machine & Section 8 rules
│   │   ├── player.py                # Player model with public/private serialisation
│   │   ├── room_manager.py          # Private/public rooms, codes, reconnect tokens
│   │   └── round_engine.py          # Turn order, attacks, trick resolution
│   ├── sockets/
│   │   └── game_events.py           # SocketIO events for real-time multiplayer
│   ├── tests/
│   │   ├── test_stage1.py           # Frontend & Backend server integration
│   │   ├── test_stage2.py           # Deck formula & distribution tests
│   │   ├── test_stage3.py           # Normal & attack round tests
│   │   ├── test_stage4.py           # Card collection & Section 8 tests
│   │   ├── test_stage4_checklist.py # 7-point handover verification checklist
│   │   ├── test_stage5.py           # AI bot match simulation & heuristics
│   │   ├── test_stage6.py           # SocketIO multiplayer & zero-leak tests
│   │   └── test_stage8_complete.py  # Master 20-point verification suite
│   ├── app.py                       # Development server entry point
│   ├── wsgi.py                      # Production WSGI server entry point
│   ├── config.py                    # SQLite & PostgreSQL configuration
│   └── requirements.txt             # Python dependencies
├── frontend/
│   ├── assets/
│   │   └── images/
│   │       ├── icon-192.svg         # PWA & Android app icon (192px)
│   │       └── icon-512.svg         # PWA & Android app icon (512px)
│   ├── css/
│   │   ├── cards.css                # Realistic playing cards styling & 3D hover
│   │   ├── main.css                 # Theme variables & global typography
│   │   ├── menu.css                 # Main menu & background felt patterns
│   │   ├── modals.css               # Setup modals, waiting lobby, settings
│   │   ├── responsive.css           # Mobile portrait & landscape viewports
│   │   └── table.css                # Green felt card table, opponents, HUD bar
│   ├── js/
│   │   ├── game/
│   │   │   ├── game-client.js       # Client state container
│   │   │   ├── offline-client.js    # REST communication for AI gameplay
│   │   │   └── online-client.js     # SocketIO communication for multiplayer
│   │   ├── ui/
│   │   │   ├── animations.js        # Card deal, fly, attack screenshake, confetti
│   │   │   ├── card-renderer.js     # Face-up and face-down SVG card elements
│   │   │   ├── menu.js              # Menu logic, selectors, waiting lobby UI
│   │   │   └── table.js             # Opponents, turn indicators, table actions
│   │   ├── utils/
│   │   │   ├── sound.js             # Web Audio API sound synthesis & ambient BGM
│   │   │   └── storage.js           # LocalStorage settings persistence
│   │   ├── main.js                  # App coordinator, screen router, event bridge
│   │   ├── index.html               # Main single-page application entry point
│   │   ├── manifest.json            # Progressive Web App manifest
│   │   └── service-worker.js        # Offline asset caching service worker
├── capacitor.config.json            # Android Studio Capacitor build configuration
└── README.md                        # Complete project documentation
```

---

## 🚀 Running the Game Locally

### 1. Requirements
- Python 3.10+
- Modern Web Browser (Chrome, Firefox, Safari, Edge)

### 2. Install Dependencies
```bash
cd "d:\KAZHUDHAI Club\backend"
pip install -r requirements.txt
```

### 3. Start the Server
```bash
python app.py
```
Open your browser and navigate to:
```
http://localhost:5000
```

---

## 🧪 Running the Automated Test Suites

All game stages are accompanied by dedicated automated test suites.

### Run All 20 Master Verification Tests (Stage 8)
```bash
python backend/tests/test_stage8_complete.py
```

### Run All Unit & Integration Tests Across All Stages
```bash
python backend/tests/test_stage1.py
python backend/tests/test_stage2.py
python backend/tests/test_stage3.py
python backend/tests/test_stage4.py
python backend/tests/test_stage4_checklist.py
python backend/tests/test_stage5.py
python backend/tests/test_stage6.py
python backend/tests/test_stage8_complete.py
```

---

## ☁️ Production Deployment

### 1. Waitress (Windows / Linux)
```bash
pip install waitress
waitress-serve --port=5000 wsgi:app
```

### 2. Gunicorn + Threaded Workers (Linux / Render / Cloud)
```bash
gunicorn --worker-class gthread --workers 1 --threads 100 --bind 0.0.0.0:$PORT --chdir backend wsgi:app
```

### 3. Production Deployment on Render
- **Public URL**: [https://kazhudhai-club.onrender.com](https://kazhudhai-club.onrender.com)
- **Engine**: Python 3.11 with Gunicorn (`gthread` + `simple-websocket`)
- **Database**: Managed PostgreSQL on Render
- **Health Check**: `https://kazhudhai-club.onrender.com/api/health`

### 4. Database Configuration
By default, SQLite is used locally. In production on Render, PostgreSQL connectivity is automatically configured:
```bash
DATABASE_URL="postgresql://user:password@host:port/dbname"
```

---

## 📱 Android APK Packaging (Capacitor)

To compile KAZHUDHAI CLUB into a native Android APK:

1. **Install Node.js & Capacitor CLI**:
   ```bash
   npm install -g @capacitor/cli @capacitor/core @capacitor/android
   ```

2. **Initialize & Add Android Platform**:
   ```bash
   npx cap add android
   ```

3. **Sync Frontend Assets**:
   ```bash
   npx cap copy
   ```

4. **Build APK in Android Studio**:
   ```bash
   npx cap open android
   ```
   In Android Studio, select **Build > Build Bundle(s) / APK(s) > Build APK(s)** to generate the production APK.

---

## 📄 License
© 2026 KAZHUDHAI CLUB. All rights reserved.
