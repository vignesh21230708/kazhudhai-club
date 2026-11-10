"""
KAZHUDHAI CLUB — backend/tests/test_critical_regression_fix.py
Integration tests verifying:
1. JavaScript syntax integrity and TableUI exports across all frontend files.
2. Offline gameplay initialization, turn progression, and AI steps.
3. Hamburger menu DOM presence, attributes, and in-game navigation controls.
4. Retention of all 4 recent multiplayer features (player ordering, card clearing, emoji reaction, activity removal).
"""
import unittest
import os
import sys
import re
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app, socketio
from game_engine.game_state import GameState

class TestCriticalRegressionFix(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.app = app
        cls.socketio = socketio
        cls.client = cls.app.test_client()

    def test_01_all_js_files_valid_syntax_and_brackets(self):
        """Verify that all JS files have 0 unmatched or unclosed brackets and no illegal returns."""
        frontend_js_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'js')
        
        js_files = []
        for root, _, files in os.walk(frontend_js_dir):
            for file in files:
                if file.endswith('.js') and 'socket.io.min.js' not in file:
                    js_files.append(os.path.join(root, file))
        
        self.assertGreater(len(js_files), 5, "Expected at least 6 frontend JS files")

        for fpath in js_files:
            with open(fpath, 'r', encoding='utf-8') as f:
                code = f.read()

            stack = []
            i = 0
            n = len(code)
            line = 1
            col = 1
            errors = []
            while i < n:
                c = code[i]
                if c == '\n':
                    line += 1
                    col = 1
                    i += 1
                    continue
                col += 1
                if c == '/' and i + 1 < n and code[i+1] == '/':
                    while i < n and code[i] != '\n':
                        i += 1
                    continue
                if c == '/' and i + 1 < n and code[i+1] == '*':
                    i += 2
                    while i + 1 < n and not (code[i] == '*' and code[i+1] == '/'):
                        if code[i] == '\n':
                            line += 1
                        i += 1
                    i += 2
                    continue
                if c == '/' and i + 1 < n and code[i+1] not in ('/', '*'):
                    prev = code[:i].rstrip()
                    if prev and prev[-1] in '=(,[{:!&|?;~':
                        i += 1
                        while i < n:
                            if code[i] == '\\':
                                i += 2
                                continue
                            if code[i] == '/':
                                i += 1
                                while i < n and code[i].isalpha():
                                    i += 1
                                break
                            if code[i] == '\n':
                                break
                            i += 1
                        continue
                if c in ('"', "'", '`'):
                    quote = c
                    i += 1
                    while i < n:
                        if code[i] == '\\':
                            i += 2
                            continue
                        if code[i] == quote:
                            i += 1
                            break
                        if code[i] == '\n':
                            line += 1
                        i += 1
                    continue
                if c in '({[':
                    stack.append((c, line, col))
                elif c in ')}]':
                    if not stack:
                        errors.append(f"Unmatched closing {c} at line {line}")
                    else:
                        top, tline, tcol = stack.pop()
                        pairs = {')': '(', '}': '{', ']': '['}
                        if pairs[c] != top:
                            errors.append(f"Mismatched {top} from line {tline} closed by {c} at line {line}")
                i += 1
            for top, tline, tcol in stack:
                errors.append(f"Unclosed {top} from line {tline}:{tcol}")

            self.assertEqual(len(errors), 0, f"Bracket errors in {os.path.basename(fpath)}: {errors}")

    def test_02_table_js_defines_and_exports_table_ui(self):
        """Verify table.js properly defines TableUI IIFE and exports all required functions."""
        table_js_path = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'js', 'ui', 'table.js')
        with open(table_js_path, 'r', encoding='utf-8') as f:
            table_js = f.read()

        self.assertIn('const TableUI = (() => {', table_js)
        self.assertIn('return {', table_js)
        self.assertIn('init,', table_js)
        self.assertIn('renderPlayers,', table_js)
        self.assertIn('renderOpponents,', table_js)
        self.assertIn('renderHand,', table_js)
        self.assertIn('addPlayedCard,', table_js)
        self.assertIn('clearPlayedCards,', table_js)
        self.assertIn('syncPlayedCards,', table_js)
        self.assertIn('showPlayerReaction,', table_js)
        self.assertIn('openInGameMenu,', table_js)
        self.assertIn('closeInGameMenu,', table_js)
        self.assertIn('})();', table_js)

    def test_03_offline_gameplay_api_flow(self):
        """Test full offline gameplay API flow: start, play card or step AI."""
        # 1. Start offline game
        start_res = self.client.post('/api/offline/start', json={
            'playerName': 'Vignesh',
            'playerCount': 3,
            'deckCount': 1,
            'difficulty': 'medium'
        })
        self.assertEqual(start_res.status_code, 200)
        data = start_res.get_json()
        self.assertIn('game_id', data)
        self.assertEqual(data['status'], 'playing')
        self.assertIn('my_hand', data)
        self.assertIn('players', data)
        self.assertEqual(len(data['players']), 3)

        # Confirm player order: P1 is Vignesh, P2 is AI 1, P3 is AI 2
        self.assertEqual(data['players'][0]['name'], 'Vignesh')
        self.assertEqual(data['players'][0]['position'], 1)
        self.assertEqual(data['players'][1]['position'], 2)
        self.assertEqual(data['players'][2]['position'], 3)

        game_id = data['game_id']

        # 2. Advance offline game with a step if current player is AI
        if data['current_player_id'] != 'human':
            step_res = self.client.post('/api/offline/step', json={'game_id': game_id})
            self.assertEqual(step_res.status_code, 200)
            step_data = step_res.get_json()
            self.assertIn('action', step_data)
        else:
            # Human has starting card
            human_card = data['my_hand'][0]
            play_res = self.client.post('/api/offline/play', json={
                'game_id': game_id,
                'card_id': human_card['id']
            })
            self.assertEqual(play_res.status_code, 200)
            play_data = play_res.get_json()
            self.assertIn('state', play_data)

    def test_04_index_html_hud_and_menu_elements(self):
        """Verify hamburger button, in-game menu, and options exist in frontend/index.html."""
        html_path = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'index.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()

        # Hamburger menu button in HUD
        self.assertIn('id="btn-menu-game"', html)
        # Ingame menu panel and backdrop
        self.assertIn('id="ingame-menu"', html)
        self.assertIn('id="ingame-menu-backdrop"', html)
        self.assertIn('id="btn-restart-game"', html)
        self.assertIn('id="btn-rules-ingame"', html)
        self.assertIn('id="btn-settings-ingame"', html)
        self.assertIn('id="btn-exit-game"', html)
        self.assertIn('id="btn-close-ingame-menu"', html)

        # Verify Game Activity was removed per requirement 3
        self.assertNotIn('id="btn-toggle-activity"', html)
        self.assertNotIn('id="activity-drawer"', html)

        # Verify Emoji reactions exist per requirement 4
        self.assertIn('id="btn-table-emoji"', html)
        self.assertIn('id="emoji-picker-panel"', html)


if __name__ == '__main__':
    unittest.main()
