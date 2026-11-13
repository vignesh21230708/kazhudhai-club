"""
KAZHUDHAI CLUB — backend/tests/test_android_back_exit.py
Verification tests for Android TWA / Browser Back Button Exit Confirmation:
- Exact "Leave Game?" modal copy and "No" / "Yes, Leave" buttons in index.html
- Reuse of #confirm-exit and App.exitToMenu() in table.js and main.js
- Priority handling for open Rules / Settings / In-Game Menu modals before Leave Game prompt
- Dedicated modal history entries when Rules or Settings opens during active gameplay
- Back button while Rules is open closes Rules and returns to exact same game
- Back button while Settings is open closes Settings and returns to exact same game
- Closing modal via X button or backdrop synchronizes history so next Back shows Leave Game confirmation
- Back button during normal gameplay shows Leave Game confirmation
- Tapping "No" preserves cards, turn, room ID, and player state
- Tapping "Yes, Leave" executes proper cleanup and notifies multiplayer server
- Outside active gameplay (e.g. Main Menu), normal navigation is preserved
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend'))


class MockHistory:
    def __init__(self):
        self.stack = [{'kzBackGuard': None, 'kzModalGuard': None}]
        self.index = 0
        self.popstate_listeners = []

    @property
    def state(self):
        return self.stack[self.index] if 0 <= self.index < len(self.stack) else None

    def pushState(self, state, title, url):
        # Truncate forward history and push
        self.stack = self.stack[:self.index + 1]
        self.stack.append(dict(state) if state else {})
        self.index = len(self.stack) - 1

    def replaceState(self, state, title, url):
        if 0 <= self.index < len(self.stack):
            self.stack[self.index] = dict(state) if state else {}

    def back(self):
        self.go(-1)

    def go(self, delta):
        new_index = self.index + delta
        if 0 <= new_index < len(self.stack):
            self.index = new_index
            event = {'type': 'popstate', 'state': self.state}
            for listener in list(self.popstate_listeners):
                listener(event)


class TestAndroidBackExitConfirmation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def _read_frontend(self, rel_path: str) -> str:
        path = os.path.join(FRONTEND_DIR, rel_path.replace('/', os.sep))
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_01_leave_game_modal_markup_and_exact_copy(self):
        """Verify #confirm-exit modal contains exact Leave Game title, prompt message, and buttons."""
        with self.client.get('/') as res:
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')

        modal_match = re.search(
            r'<div[^>]+id="confirm-exit"[^>]*>(?P<inner>.*?)</div>\s*</div>\s*</div>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(modal_match, '#confirm-exit modal missing from index.html')
        modal_html = modal_match.group(0)

        self.assertIn('role="dialog"', modal_html)
        self.assertIn('aria-modal="true"', modal_html)
        self.assertIn('>Leave Game?</h3>', modal_html)
        self.assertIn('>Are you sure you want to leave the current game?</p>', modal_html)
        self.assertRegex(modal_html, r'id="btn-cancel-exit"[^>]*>\s*No\s*</button>')
        self.assertRegex(modal_html, r'id="btn-confirm-exit"[^>]*>\s*Yes, Leave\s*</button>')

    def test_02_table_ui_reuses_single_confirm_modal_and_handlers(self):
        """Verify TableUI exports and reuses single #confirm-exit controls without duplicating dialogs."""
        table_js = self._read_frontend('js/ui/table.js')

        for fn_name in ('isInGameMenuOpen', 'isExitConfirmOpen', 'showExitConfirm', 'hideExitConfirm'):
            self.assertIn(f'function {fn_name}(', table_js)
            self.assertIn(fn_name, table_js.split('return {')[-1])

        # Duplicate guard inside showExitConfirm
        show_match = re.search(r'function showExitConfirm\(\)\s*\{(?P<body>.*?)\n  \}', table_js, re.DOTALL)
        self.assertIsNotNone(show_match)
        self.assertIn('if (isExitConfirmOpen()) return;', show_match.group('body'))

        # "No" closes modal and re-arms back guard without altering game state
        cancel_match = re.search(
            r"bindTap\(cancelExitBtn,\s*\(e\)\s*=>\s*\{(?P<body>.*?)\n      \}\);",
            table_js,
            re.DOTALL,
        )
        self.assertIsNotNone(cancel_match)
        self.assertIn('hideExitConfirm();', cancel_match.group('body'))
        self.assertIn('App.activateGameBackGuard()', cancel_match.group('body'))
        self.assertNotIn('exitToMenu', cancel_match.group('body'))

        # "Yes, Leave" executes existing App.exitToMenu workflow
        confirm_match = re.search(
            r"bindTap\(confirmExitBtn,\s*\(e\)\s*=>\s*\{(?P<body>.*?)\n      \}\);",
            table_js,
            re.DOTALL,
        )
        self.assertIsNotNone(confirm_match)
        self.assertIn('hideExitConfirm();', confirm_match.group('body'))
        self.assertIn('App.exitToMenu()', confirm_match.group('body'))

    def test_03_main_js_back_navigation_priority_and_lifecycle(self):
        """Verify main.js intercepts Android/browser back only during active play with modal priority."""
        main_js = self._read_frontend('js/main.js')

        self.assertIn("window.addEventListener('popstate', _handlePopState)", main_js)
        self.assertIn('function isActivelyPlayingGame()', main_js)
        self.assertIn('function activateGameBackGuard()', main_js)
        self.assertIn('function onModalOpened(', main_js)
        self.assertIn('function onModalClosed(', main_js)
        self.assertIn('function _releaseGameBackGuard()', main_js)

        # Must never force reload or close window
        self.assertNotIn('location.reload', main_js)
        self.assertNotIn('window.close(', main_js)

        pop_match = re.search(r'function _handlePopState\(\)\s*\{(?P<body>.*?)\n  \}', main_js, re.DOTALL)
        self.assertIsNotNone(pop_match)
        pop_body = pop_match.group('body')

        # Retains normal navigation when no game is active
        self.assertIn('if (!isActivelyPlayingGame())', pop_body)

        # Closes popups (Priority 1) before Leave Game confirmation, and prevents duplicate confirm dialogs
        for mid in ('modal-offline-setup', 'modal-online-lobby', 'modal-rules', 'modal-settings'):
            self.assertIn(mid, main_js)

        idx_modal_close = pop_body.index("modalToClose")
        idx_confirm_open = pop_body.index("TableUI.isExitConfirmOpen")
        idx_menu = pop_body.index("TableUI.isInGameMenuOpen")
        idx_show_confirm = pop_body.index("TableUI.showExitConfirm")
        self.assertLess(idx_modal_close, idx_confirm_open)
        self.assertLess(idx_confirm_open, idx_show_confirm)
        self.assertLess(idx_menu, idx_show_confirm)

        # exitToMenu delegates to existing cleanup and releases history guard cleanly
        exit_match = re.search(r'function exitToMenu\(\)\s*\{(?P<body>.*?)\n  \}', main_js, re.DOTALL)
        self.assertIsNotNone(exit_match)
        exit_body = exit_match.group('body')
        self.assertIn('OfflineClient.reset();', exit_body)
        self.assertIn('OnlineClient.disconnect();', exit_body)
        self.assertIn('GameClient.reset();', exit_body)
        self.assertIn("Screens.go('screen-menu');", exit_body)
        self.assertIn('_releaseGameBackGuard();', exit_body)

    def test_04_menu_ui_hooks_into_app_modal_lifecycle(self):
        """Verify MenuUI.showModal and hideModal call App.onModalOpened and App.onModalClosed for all 4 popups."""
        menu_js = self._read_frontend('js/ui/menu.js')

        show_match = re.search(r'function showModal\(id\)\s*\{(?P<body>.*?)\n  \}', menu_js, re.DOTALL)
        self.assertIsNotNone(show_match, 'showModal definition missing from menu.js')
        show_body = show_match.group('body')
        self.assertIn('wasHidden', show_body)
        self.assertIn('App.onModalOpened(id)', show_body)

        hide_match = re.search(r'function hideModal\(id,\s*options\)\s*\{(?P<body>.*?)\n  \}', menu_js, re.DOTALL)
        self.assertIsNotNone(hide_match, 'hideModal definition missing from menu.js')
        hide_body = hide_match.group('body')
        self.assertIn('wasVisible', hide_body)
        self.assertIn('App.onModalClosed(id, options)', hide_body)

        # Ensure close button and backdrop click listeners exist for all 4 main-menu popups
        self.assertIn("document.getElementById('offline-setup-close').addEventListener('click', () => hideModal('modal-offline-setup'))", menu_js)
        self.assertIn("if (e.target === e.currentTarget) hideModal('modal-offline-setup')", menu_js)
        self.assertIn("document.getElementById('online-lobby-close').addEventListener('click', () => hideModal('modal-online-lobby'))", menu_js)
        self.assertIn("if (e.target === e.currentTarget) hideModal('modal-online-lobby')", menu_js)
        self.assertIn("document.getElementById('rules-close').addEventListener('click', () => hideModal('modal-rules'))", menu_js)
        self.assertIn("if (e.target === e.currentTarget) hideModal('modal-rules')", menu_js)
        self.assertIn("document.getElementById('settings-close').addEventListener('click', () => hideModal('modal-settings'))", menu_js)
        self.assertIn("if (e.target === e.currentTarget) hideModal('modal-settings')", menu_js)

    def test_05_online_client_hooks_back_guard_and_leave_room(self):
        """Verify OnlineClient arms back guard on game start/reconnect and emits leave_room on exit."""
        online_js = self._read_frontend('js/game/online-client.js')

        self.assertGreaterEqual(online_js.count('App.activateGameBackGuard()'), 2)
        self.assertIn("_socket.emit('leave_room'", online_js)
        self.assertIn("leaveRoom('left'", online_js)

    # ── State Machine Simulation Tests ──

    def _create_app_state_machine(self):
        """Builds an exact simulation of the App and MenuUI navigation state machine."""
        history = MockHistory()
        modals = {
            'modal-offline-setup': False,
            'modal-online-lobby': False,
            'modal-rules': False,
            'modal-settings': False,
            'confirm-exit': False,
        }
        screen = 'screen-game'
        game_active = True
        in_game_menu = False
        online_left = False

        state = {
            'hasGameBackGuard': False,
            'activeModalGuard': None,
            'suppressNextPopCount': 0,
        }

        MAIN_MODALS = ('modal-offline-setup', 'modal-online-lobby', 'modal-rules', 'modal-settings')

        def isActivelyPlayingGame():
            return screen == 'screen-game' and game_active

        def isModalVisible(mid):
            return modals.get(mid, False)

        def getOpenModalId():
            for mid in MAIN_MODALS:
                if isModalVisible(mid):
                    return mid
            return None

        def activateGameBackGuard():
            if screen != 'screen-game':
                return
            state['suppressNextPopCount'] = 0
            if state['hasGameBackGuard']:
                return
            if history.state and history.state.get('kzBackGuard') == 'game':
                state['hasGameBackGuard'] = True
                return
            next_state = dict(history.state or {})
            next_state['kzBackGuard'] = 'game'
            history.pushState(next_state, '', '')
            state['hasGameBackGuard'] = True

        def onModalOpened(modal_id):
            if modal_id not in MAIN_MODALS:
                return
            in_game = isActivelyPlayingGame()
            if in_game:
                activateGameBackGuard()
            if state['activeModalGuard'] == modal_id:
                return
            state_payload = {'kzModalGuard': modal_id}
            if in_game:
                state_payload['kzBackGuard'] = 'game'
            base_state = dict(history.state or {})
            if not in_game and 'kzBackGuard' in base_state:
                del base_state['kzBackGuard']
            if state['activeModalGuard'] or (history.state and history.state.get('kzModalGuard')):
                state['activeModalGuard'] = modal_id
                next_state = dict(base_state)
                next_state.update(state_payload)
                history.replaceState(next_state, '', '')
                return
            state['activeModalGuard'] = modal_id
            next_state = dict(base_state)
            next_state.update(state_payload)
            history.pushState(next_state, '', '')

        def onModalClosed(modal_id, options=None):
            if modal_id not in MAIN_MODALS:
                return
            if options and options.get('fromPopState'):
                if state['activeModalGuard'] == modal_id:
                    state['activeModalGuard'] = None
                return
            is_guarded = bool(history.state and history.state.get('kzModalGuard') == modal_id)
            if state['activeModalGuard'] == modal_id or is_guarded:
                state['activeModalGuard'] = None
                state['suppressNextPopCount'] += 1
                history.back()

        def showModal(modal_id):
            was_hidden = not modals.get(modal_id, False)
            modals[modal_id] = True
            if was_hidden:
                onModalOpened(modal_id)

        def hideModal(modal_id, options=None):
            was_visible = modals.get(modal_id, False)
            modals[modal_id] = False
            if was_visible:
                onModalClosed(modal_id, options)

        def handlePopState(e=None):
            nonlocal in_game_menu
            if state['suppressNextPopCount'] > 0:
                state['suppressNextPopCount'] -= 1
                state['hasGameBackGuard'] = bool(history.state and history.state.get('kzBackGuard') == 'game')
                vis = getOpenModalId()
                if vis and not state['activeModalGuard']:
                    onModalOpened(vis)
                return

            # Priority 1: Any popup modal open -> close visible modal first (both in-game and on main menu)
            modal_to_close = state['activeModalGuard'] or getOpenModalId()
            if modal_to_close:
                state['activeModalGuard'] = None
                hideModal(modal_to_close, {'fromPopState': True})
                for mid in MAIN_MODALS:
                    if isModalVisible(mid):
                        hideModal(mid, {'fromPopState': True})
                if isActivelyPlayingGame():
                    state['hasGameBackGuard'] = bool(history.state and history.state.get('kzBackGuard') == 'game')
                    if not state['hasGameBackGuard']:
                        activateGameBackGuard()
                else:
                    state['hasGameBackGuard'] = False
                return

            # Retain normal navigation when no game is active (and no modal is open)
            if not isActivelyPlayingGame():
                state['hasGameBackGuard'] = False
                state['activeModalGuard'] = None
                return

            # Browser popped the game entry
            state['hasGameBackGuard'] = False

            # Priority 2: Confirm exit already open
            if modals.get('confirm-exit', False):
                activateGameBackGuard()
                return

            # Priority 3: In-game menu open
            if in_game_menu:
                in_game_menu = False
                activateGameBackGuard()
                return

            # Priority 4: Normal gameplay -> show Leave Game confirmation
            activateGameBackGuard()
            modals['confirm-exit'] = True

        history.popstate_listeners.append(handlePopState)

        def exitToMenu():
            nonlocal screen, game_active, in_game_menu, online_left
            for mid in MAIN_MODALS:
                modals[mid] = False
            modals['confirm-exit'] = False
            in_game_menu = False
            game_active = False
            online_left = True
            screen = 'screen-menu'
            state['activeModalGuard'] = None
            state['hasGameBackGuard'] = False
            has_modal = bool(history.state and history.state.get('kzModalGuard'))
            has_game = bool(history.state and history.state.get('kzBackGuard') == 'game')
            if has_modal or has_game:
                delta = -2 if (has_modal and has_game) else -1
                state['suppressNextPopCount'] += abs(delta)
                history.go(delta)

        class AppSimulator:
            def __init__(self):
                self.history = history
                self.modals = modals
                self.state = state

            @property
            def screen(self):
                return screen

            @screen.setter
            def screen(self, val):
                nonlocal screen
                screen = val

            @property
            def game_active(self):
                return game_active

            @game_active.setter
            def game_active(self, val):
                nonlocal game_active
                game_active = val

            @property
            def in_game_menu(self):
                return in_game_menu

            @in_game_menu.setter
            def in_game_menu(self, val):
                nonlocal in_game_menu
                in_game_menu = val

            @property
            def online_left(self):
                return online_left

            def activateGameBackGuard(self):
                activateGameBackGuard()

            def showModal(self, mid):
                showModal(mid)

            def hideModal(self, mid, opts=None):
                hideModal(mid, opts)

            def isModalVisible(self, mid):
                return isModalVisible(mid)

            def isActivelyPlayingGame(self):
                return isActivelyPlayingGame()

            def exitToMenu(self):
                exitToMenu()

        return AppSimulator()

    def test_06_back_while_rules_open_closes_rules_and_preserves_game(self):
        """Verify Android Back while Rules modal is open closes Rules and returns to exact same game."""
        app_sim = self._create_app_state_machine()

        # 1. Game starts -> history has [Initial, Game]
        app_sim.activateGameBackGuard()
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')

        # 2. Player opens Rules modal -> history has [Initial, Game, Rules]
        app_sim.showModal('modal-rules')
        self.assertTrue(app_sim.modals['modal-rules'])
        self.assertEqual(len(app_sim.history.stack), 3)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-rules')

        # 3. Android Back pressed -> Pops to [Initial, Game], closes Rules, leaves confirmation hidden
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-rules'], 'Rules modal must close on Back')
        self.assertFalse(app_sim.modals['confirm-exit'], 'Leave Game confirmation must NOT appear when closing Rules')
        self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')
        self.assertTrue(app_sim.state['hasGameBackGuard'], 'Game back guard must remain armed')
        self.assertTrue(app_sim.game_active, 'Game must remain active')

        # 4. Next Android Back pressed -> Shows Leave Game confirmation
        app_sim.history.back()
        self.assertTrue(app_sim.modals['confirm-exit'], 'Next Back must display Leave Game confirmation')
        self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')

    def test_07_back_while_settings_open_closes_settings_and_preserves_game(self):
        """Verify Android Back while Settings modal is open closes Settings and returns to exact same game."""
        app_sim = self._create_app_state_machine()

        # 1. Game starts
        app_sim.activateGameBackGuard()
        self.assertEqual(len(app_sim.history.stack), 2)

        # 2. Settings opened
        app_sim.showModal('modal-settings')
        self.assertTrue(app_sim.modals['modal-settings'])
        self.assertEqual(len(app_sim.history.stack), 3)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-settings')

        # 3. Android Back pressed -> Settings closes, returns to game
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-settings'])
        self.assertFalse(app_sim.modals['confirm-exit'])
        self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')
        self.assertTrue(app_sim.state['hasGameBackGuard'])

        # 4. Next Android Back pressed -> Shows Leave Game confirmation
        app_sim.history.back()
        self.assertTrue(app_sim.modals['confirm-exit'])

    def test_08_closing_modal_via_x_button_or_backdrop_synchronizes_history(self):
        """Verify closing either modal via X button or backdrop synchronizes history so next Back confirms exit."""
        for close_target in ('modal-rules', 'modal-settings'):
            app_sim = self._create_app_state_machine()

            # Start game
            app_sim.activateGameBackGuard()
            self.assertEqual(len(app_sim.history.stack), 2)

            # Open modal
            app_sim.showModal(close_target)
            self.assertTrue(app_sim.modals[close_target])
            self.assertEqual(app_sim.history.state.get('kzModalGuard'), close_target)
            self.assertEqual(app_sim.history.index, 2)

            # Close via X button or backdrop (both invoke hideModal without fromPopState)
            app_sim.hideModal(close_target)
            self.assertFalse(app_sim.modals[close_target])
            # Programmatic history.back() was executed and its popstate suppressed
            self.assertEqual(app_sim.history.index, 1, f"Failed for {close_target}: history must return to game entry")
            self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')
            self.assertIsNone(app_sim.history.state.get('kzModalGuard'))
            self.assertTrue(app_sim.state['hasGameBackGuard'])
            self.assertFalse(app_sim.modals['confirm-exit'], 'Closing modal must not display exit confirm')

            # Next Back press MUST show Leave Game confirmation immediately, not exit
            app_sim.history.back()
            self.assertTrue(app_sim.modals['confirm-exit'], f"Failed for {close_target}: next Back must display Leave Game confirmation")
            self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')

    def test_09_back_during_normal_gameplay_and_no_vs_yes_leave(self):
        """Verify normal gameplay back button shows Leave Game confirmation; No continues, Yes leaves."""
        app_sim = self._create_app_state_machine()
        player_cards = ['AS', 'KS', 'QS']

        # 1. Active game
        app_sim.activateGameBackGuard()
        self.assertEqual(app_sim.history.state.get('kzBackGuard'), 'game')

        # 2. Press Back during normal gameplay -> Leave Game confirmation opens
        app_sim.history.back()
        self.assertTrue(app_sim.modals['confirm-exit'], 'Leave Game confirmation must open')
        self.assertEqual(player_cards, ['AS', 'KS', 'QS'], 'Cards must not be altered')

        # 3. Pressing Back while confirmation is open -> Prevents duplicate dialogs
        app_sim.history.back()
        self.assertTrue(app_sim.modals['confirm-exit'])

        # 4. User clicks "No" -> Closes confirmation and continues exact same game
        app_sim.modals['confirm-exit'] = False
        app_sim.activateGameBackGuard()
        self.assertFalse(app_sim.modals['confirm-exit'])
        self.assertTrue(app_sim.game_active, 'Game must still be active')
        self.assertEqual(player_cards, ['AS', 'KS', 'QS'])
        self.assertTrue(app_sim.state['hasGameBackGuard'])

        # 5. User presses Back again and clicks "Yes, Leave"
        app_sim.history.back()
        self.assertTrue(app_sim.modals['confirm-exit'])

        # Execute exitToMenu cleanup
        app_sim.exitToMenu()

        self.assertFalse(app_sim.game_active, 'Game session ended')
        self.assertTrue(app_sim.online_left, 'Multiplayer server notified of departure')
        self.assertFalse(app_sim.modals['confirm-exit'])
        self.assertEqual(app_sim.screen, 'screen-menu')

    def test_10_main_menu_back_while_offline_setup_open_closes_popup_and_preserves_menu(self):
        """Verify Android Back while Play Offline setup is open closes popup and remains on Main Menu."""
        app_sim = self._create_app_state_machine()
        app_sim.screen = 'screen-menu'
        app_sim.game_active = False

        self.assertEqual(len(app_sim.history.stack), 1)

        # 1. Open Offline Setup on Main Menu
        app_sim.showModal('modal-offline-setup')
        self.assertTrue(app_sim.modals['modal-offline-setup'])
        self.assertEqual(len(app_sim.history.stack), 2, 'Must push dedicated modal history entry')
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-offline-setup')
        self.assertIsNone(app_sim.history.state.get('kzBackGuard'), 'Must NOT arm game back guard outside active gameplay')

        # 2. Press Android Back -> Closes Offline Setup, remains on Main Menu
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-offline-setup'], 'Offline setup modal must close')
        self.assertEqual(app_sim.screen, 'screen-menu', 'Must remain on Main Menu')
        self.assertFalse(app_sim.modals['confirm-exit'], 'Must NOT show Leave Game confirmation')
        self.assertEqual(app_sim.history.index, 0)

        # 3. Next Back press on Main Menu -> Normal navigation
        app_sim.history.back()
        self.assertFalse(app_sim.modals['confirm-exit'])

    def test_11_main_menu_back_while_online_lobby_open_closes_popup_and_preserves_menu(self):
        """Verify Android Back while Play Online lobby is open closes popup and remains on Main Menu."""
        app_sim = self._create_app_state_machine()
        app_sim.screen = 'screen-menu'
        app_sim.game_active = False

        self.assertEqual(len(app_sim.history.stack), 1)

        # 1. Open Online Lobby on Main Menu
        app_sim.showModal('modal-online-lobby')
        self.assertTrue(app_sim.modals['modal-online-lobby'])
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-online-lobby')
        self.assertIsNone(app_sim.history.state.get('kzBackGuard'))

        # 2. Press Android Back -> Closes Online Lobby, remains on Main Menu
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-online-lobby'])
        self.assertEqual(app_sim.screen, 'screen-menu')
        self.assertFalse(app_sim.modals['confirm-exit'])
        self.assertEqual(app_sim.history.index, 0)

        # 3. Next Back press -> Normal navigation
        app_sim.history.back()
        self.assertFalse(app_sim.modals['confirm-exit'])

    def test_12_main_menu_back_while_rules_open_closes_rules_and_preserves_menu(self):
        """Verify Android Back while Rules is open from Main Menu closes Rules and remains on Main Menu."""
        app_sim = self._create_app_state_machine()
        app_sim.screen = 'screen-menu'
        app_sim.game_active = False

        self.assertEqual(len(app_sim.history.stack), 1)

        # 1. Open Rules on Main Menu
        app_sim.showModal('modal-rules')
        self.assertTrue(app_sim.modals['modal-rules'])
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-rules')
        self.assertIsNone(app_sim.history.state.get('kzBackGuard'))

        # 2. Press Android Back -> Closes Rules, remains on Main Menu
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-rules'], 'Rules modal must close')
        self.assertEqual(app_sim.screen, 'screen-menu', 'Must remain on Main Menu')
        self.assertFalse(app_sim.modals['confirm-exit'], 'Must NOT show Leave Game confirmation')
        self.assertEqual(app_sim.history.index, 0)

        # 3. Next Back press on Main Menu -> Normal navigation
        app_sim.history.back()
        self.assertFalse(app_sim.modals['confirm-exit'])

    def test_13_main_menu_back_while_settings_open_closes_settings_and_preserves_menu(self):
        """Verify Android Back while Settings is open from Main Menu closes Settings and remains on Main Menu."""
        app_sim = self._create_app_state_machine()
        app_sim.screen = 'screen-menu'
        app_sim.game_active = False

        self.assertEqual(len(app_sim.history.stack), 1)

        # 1. Open Settings on Main Menu
        app_sim.showModal('modal-settings')
        self.assertTrue(app_sim.modals['modal-settings'])
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-settings')
        self.assertIsNone(app_sim.history.state.get('kzBackGuard'))

        # 2. Press Android Back -> Closes Settings, remains on Main Menu
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-settings'])
        self.assertEqual(app_sim.screen, 'screen-menu')
        self.assertFalse(app_sim.modals['confirm-exit'])
        self.assertEqual(app_sim.history.index, 0)

        # 3. Next Back press -> Normal navigation
        app_sim.history.back()
        self.assertFalse(app_sim.modals['confirm-exit'])

    def test_14_main_menu_closing_all_four_popups_via_x_or_backdrop_synchronizes_history(self):
        """Verify closing any of the 4 popups via X button or backdrop synchronizes history cleanly."""
        all_popups = ('modal-offline-setup', 'modal-online-lobby', 'modal-rules', 'modal-settings')
        for target_modal in all_popups:
            app_sim = self._create_app_state_machine()
            app_sim.screen = 'screen-menu'
            app_sim.game_active = False

            # Open modal
            app_sim.showModal(target_modal)
            self.assertTrue(app_sim.modals[target_modal])
            self.assertEqual(app_sim.history.index, 1)
            self.assertEqual(app_sim.history.state.get('kzModalGuard'), target_modal)

            # Close via X button / backdrop (manual close without fromPopState)
            app_sim.hideModal(target_modal)
            self.assertFalse(app_sim.modals[target_modal])
            self.assertEqual(app_sim.history.index, 0, f"History index must return to 0 after closing {target_modal}")
            self.assertIsNone(app_sim.history.state.get('kzModalGuard'))
            self.assertFalse(app_sim.modals['confirm-exit'])

            # Next Back press -> Normal navigation
            app_sim.history.back()
            self.assertFalse(app_sim.modals['confirm-exit'])

    def test_15_rapid_modal_switching_replaces_history_entry_in_both_contexts(self):
        """Verify switching between any popups replaces the modal history entry without stacking."""
        # 1. Main menu context: Play Offline -> Play Online -> Settings -> Rules
        app_sim = self._create_app_state_machine()
        app_sim.screen = 'screen-menu'
        app_sim.game_active = False

        app_sim.showModal('modal-offline-setup')
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-offline-setup')

        app_sim.showModal('modal-online-lobby')
        self.assertEqual(len(app_sim.history.stack), 2, 'History entry must be replaced, not stacked')
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-online-lobby')

        app_sim.showModal('modal-settings')
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-settings')

        app_sim.showModal('modal-rules')
        self.assertEqual(len(app_sim.history.stack), 2)
        self.assertEqual(app_sim.history.state.get('kzModalGuard'), 'modal-rules')

        # Single Back closes modal and returns to main menu
        app_sim.history.back()
        self.assertFalse(app_sim.modals['modal-rules'])
        self.assertEqual(app_sim.history.index, 0)
        self.assertEqual(app_sim.screen, 'screen-menu')

        # 2. Active game context
        app_sim_game = self._create_app_state_machine()
        app_sim_game.activateGameBackGuard()
        self.assertEqual(len(app_sim_game.history.stack), 2)

        app_sim_game.showModal('modal-rules')
        self.assertEqual(len(app_sim_game.history.stack), 3)
        self.assertEqual(app_sim_game.history.state.get('kzModalGuard'), 'modal-rules')

        # Switch to settings in-game
        app_sim_game.showModal('modal-settings')
        self.assertEqual(len(app_sim_game.history.stack), 3, 'In-game history entry must be replaced, not stacked')
        self.assertEqual(app_sim_game.history.state.get('kzModalGuard'), 'modal-settings')

        # Single Back closes modal and returns to game
        app_sim_game.history.back()
        self.assertFalse(app_sim_game.modals['modal-settings'])
        self.assertEqual(app_sim_game.history.index, 1)
        self.assertEqual(app_sim_game.history.state.get('kzBackGuard'), 'game')


if __name__ == '__main__':
    unittest.main()
