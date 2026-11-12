"""
KAZHUDHAI CLUB — backend/tests/test_android_back_exit.py
Verification tests for Android TWA / Browser Back Button Exit Confirmation:
- Exact "Leave Game?" modal copy and "No" / "Yes, Leave" buttons in index.html
- Reuse of #confirm-exit and App.exitToMenu() in table.js and main.js
- Priority handling for open Rules / Settings / In-Game Menu modals before Leave Game prompt
- Duplicate confirmation prevention and history guard lifecycle
- Preservation of online leave_room + offline reset flows without reload/app close
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend'))


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
        self.assertIn('function _releaseGameBackGuard()', main_js)

        # Must never force reload or close window
        self.assertNotIn('location.reload', main_js)
        self.assertNotIn('window.close(', main_js)

        pop_match = re.search(r'function _handlePopState\(\)\s*\{(?P<body>.*?)\n  \}', main_js, re.DOTALL)
        self.assertIsNotNone(pop_match)
        pop_body = pop_match.group('body')

        # Retains normal navigation when no game is active
        self.assertIn('if (!isActivelyPlayingGame())', pop_body)

        # Closes Rules / Settings / In-game Menu before Leave Game confirmation, and prevents duplicate confirm dialogs
        idx_rules = pop_body.index("modal-rules")
        idx_settings = pop_body.index("modal-settings")
        idx_confirm_open = pop_body.index("TableUI.isExitConfirmOpen")
        idx_menu = pop_body.index("TableUI.isInGameMenuOpen")
        idx_show_confirm = pop_body.index("TableUI.showExitConfirm")
        self.assertLess(idx_rules, idx_confirm_open)
        self.assertLess(idx_settings, idx_confirm_open)
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

    def test_04_online_client_hooks_back_guard_and_leave_room(self):
        """Verify OnlineClient arms back guard on game start/reconnect and emits leave_room on exit."""
        online_js = self._read_frontend('js/game/online-client.js')

        self.assertGreaterEqual(online_js.count('App.activateGameBackGuard()'), 2)
        self.assertIn("_socket.emit('leave_room'", online_js)
        self.assertIn("leaveRoom('left'", online_js)


if __name__ == '__main__':
    unittest.main()
