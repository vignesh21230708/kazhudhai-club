"""
Tests verifying the Android Mobile Multiplayer Play Button bug fixes:
1. Authoritative Turn Identification (current_player_id vs player_id)
2. Frontend code integrity:
   - isCurrentPlayerTurn check in main.js
   - resetPlayInFlight calls on blocked paths & safety timeout
   - touchend & click event listeners on playBtn
   - Preserved card selection across socket state refreshes
   - CSS touch target sizing (>=44px) and touch-action: manipulation
3. Turn-state synchronization via authoritative game state
"""

import unittest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.game_state import GameState
from app import app, socketio


class TestMobilePlayButtonBugFix(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_frontend_authoritative_turn_and_lock_reset(self):
        """Verify frontend scripts implement authoritative turn checks and lock resets."""
        project_root = Path(__file__).resolve().parent.parent.parent
        main_js_path = project_root / "frontend" / "js" / "main.js"
        self.assertTrue(main_js_path.exists(), "main.js must exist")
        main_js_content = main_js_path.read_text(encoding="utf-8")

        self.assertIn("function isCurrentPlayerTurn()", main_js_content)
        self.assertIn("TableUI.resetPlayInFlight()", main_js_content)
        self.assertIn("isCurrentPlayerTurn,", main_js_content)

    def test_frontend_table_ui_touch_and_selection_retention(self):
        """Verify TableUI handles mobile touch, selection retention, and safe timeouts."""
        project_root = Path(__file__).resolve().parent.parent.parent
        table_js_path = project_root / "frontend" / "js" / "ui" / "table.js"
        self.assertTrue(table_js_path.exists(), "table.js must exist")
        table_js_content = table_js_path.read_text(encoding="utf-8")

        self.assertIn("addEventListener('touchend'", table_js_content)
        self.assertIn("resetPlayInFlight", table_js_content)
        self.assertIn("prevSelectedId", table_js_content)
        self.assertIn("_getIsMyTurn", table_js_content)

    def test_frontend_css_touch_targets_and_action_bar(self):
        """Verify CSS contains touch-action: manipulation, min-height 44px, and z-index."""
        project_root = Path(__file__).resolve().parent.parent.parent
        table_css_path = project_root / "frontend" / "css" / "table.css"
        responsive_css_path = project_root / "frontend" / "css" / "responsive.css"

        table_css = table_css_path.read_text(encoding="utf-8")
        responsive_css = responsive_css_path.read_text(encoding="utf-8")

        self.assertIn("touch-action: manipulation", table_css)
        self.assertIn("z-index: 65", table_css)
        self.assertIn("min-height: 44px", responsive_css)

    def test_multiplayer_turn_sync_payload(self):
        """Verify that game state payload sent to clients authoritatively identifies the current turn."""
        player_configs = [
            {'id': 'P1', 'name': 'LaptopHost', 'is_ai': False},
            {'id': 'P2', 'name': 'AndroidPlayer', 'is_ai': False}
        ]
        game = GameState(game_id="KZTEST", player_configs=player_configs, num_decks=1)
        game.setup()

        # Authoritative current player ID must be either P1 or P2
        curr_id = game.current_player.id
        self.assertIn(curr_id, ["P1", "P2"])

        # P1 state
        p1_state = game.get_state_for_player("P1")
        self.assertEqual(p1_state["current_player_id"], curr_id)
        self.assertEqual(p1_state["is_my_turn"], (curr_id == "P1"))

        # P2 state
        p2_state = game.get_state_for_player("P2")
        self.assertEqual(p2_state["current_player_id"], curr_id)
        self.assertEqual(p2_state["is_my_turn"], (curr_id == "P2"))

        # Find the player whose turn it is
        curr_player = game._get_player(curr_id)
        card_to_play = curr_player.hand[0]
        res = game.play_card(curr_player.id, card_to_play['id'])
        self.assertNotIn("error", res, f"Play card failed with error: {res.get('error')}")
        self.assertIn("action", res)

        # After play, current_player_id changes to the next player
        next_id = game.current_player.id
        self.assertNotEqual(next_id, curr_id)

        next_p1_state = game.get_state_for_player("P1")
        next_p2_state = game.get_state_for_player("P2")
        self.assertEqual(next_p1_state["is_my_turn"], (next_id == "P1"))
        self.assertEqual(next_p2_state["is_my_turn"], (next_id == "P2"))


if __name__ == '__main__':
    unittest.main()
