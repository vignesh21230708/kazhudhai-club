"""
KAZHUDHAI CLUB — backend/tests/test_stage5_remove_fast_forward.py
Stage 5 automated test suite:
  - Fast-forward button completely absent in online and offline frontend code
  - Finished (SAFE) players still see the watch view and continue watching remaining rounds
  - Existing host-controlled Restart Game button and handler remain present and functional
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module


class TestStage5RemoveFastForward(unittest.TestCase):

    def test_01_fast_forward_button_removed_from_frontend(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        files_to_check = [
            os.path.join(base_dir, 'frontend', 'index.html'),
            os.path.join(base_dir, 'frontend', 'js', 'ui', 'table.js'),
            os.path.join(base_dir, 'frontend', 'js', 'main.js'),
            os.path.join(base_dir, 'frontend', 'js', 'game', 'offline-client.js'),
            os.path.join(base_dir, 'frontend', 'js', 'game', 'online-client.js'),
        ]
        for path in files_to_check:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertNotIn('btn-fast-forward', content, f"btn-fast-forward still present in {path}")
            self.assertNotIn('Fast-Forward to Results', content, f"Fast-Forward label still present in {path}")
            self.assertNotIn('fastForwardGame', content, f"fastForwardGame handler still present in {path}")
            self.assertNotIn('fastForward', content, f"fastForward still present in {path}")

    def test_02_finished_player_watch_view_and_restart_button_preserved(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()
        with open(os.path.join(base_dir, 'frontend', 'js', 'ui', 'table.js'), 'r', encoding='utf-8') as f:
            table_js = f.read()

        # Finished (SAFE) player watch view remains intact
        self.assertIn('You emptied your hand and are SAFE! Watching remaining players', table_js)
        self.assertIn('_syncSafeBadge(DOM.selfAvatar, true)', table_js)

        # Existing host-controlled Restart Game button remains intact
        self.assertIn('id="btn-restart-game"', html)
        self.assertIn("getElementById('btn-restart-game')", table_js)

    def test_03_offline_finished_player_can_watch_remaining_ai_rounds(self):
        """Verify an offline game continues stepping remaining AI players normally after human becomes SAFE."""
        client = app_module.app.test_client()
        resp = client.post('/api/offline/start', json={
            'playerName': 'WatcherHuman',
            'playerCount': 3,
            'deckCount': 1,
            'difficulty': 'medium',
        })
        self.assertEqual(resp.status_code, 200)
        game_id = resp.get_json()['game_id']

        from api.offline_routes import _games
        gs = _games[game_id]
        # Mark human player safe with 0 cards and let remaining 2 AI players finish watching normally
        gs.players[0].hand = []
        gs.players[0].is_safe = True
        gs.players[1].hand = [{'id': 'ai_1_a', 'rank': 'A', 'suit': 'S', 'deck_index': 0}]
        gs.players[2].hand = [
            {'id': 'ai_2_k', 'rank': 'K', 'suit': 'S', 'deck_index': 0},
            {'id': 'ai_2_2', 'rank': '2', 'suit': 'H', 'deck_index': 0},
        ]
        gs.current_player_idx = 0  # index 0 in active_players -> AI 1
        gs._start_new_round()

        # Step remaining AI turns cleanly to game completion
        for _ in range(5):
            r_step = client.post('/api/offline/step', json={'game_id': game_id})
            self.assertEqual(r_step.status_code, 200)
            st = r_step.get_json()['state']
            self.assertEqual(len(st['my_hand']), 0)
            if st['status'] == 'finished':
                break

        self.assertEqual(gs.status, 'finished')


if __name__ == '__main__':
    unittest.main()
