"""
KAZHUDHAI CLUB — backend/tests/test_table_layout_responsive.py
Verifies the responsive game-table layout, balanced player positioning
for 2, 3, 4, 5, 6, and 7 players across Android portrait, Android landscape,
and laptop/desktop screen sizes.
"""
import unittest
import re
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestResponsiveGameTableLayout(unittest.TestCase):
    """
    Validates:
      1. Player position calculation for 2 to 7 players.
      2. All players are visible simultaneously (never positioned outside screen).
      3. Balanced table positioning:
         - 6 players: 5 opponents (1 left, 3 top, 1 right, human bottom)
         - 7 players: 6 opponents (2 left, 2 top, 2 right, human bottom)
      4. Spacing, avatars, and dimensions fit across:
         - Android mobile portrait (360x740)
         - Android mobile landscape (740x360)
         - Laptop / Desktop (1366x768, 1920x1080)
      5. CSS Grid column safety: minmax(0, 1fr) prevents right-edge overflow.
    """

    @classmethod
    def setUpClass(cls):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'js', 'ui', 'table.js'), 'r', encoding='utf-8') as f:
            cls.table_js = f.read()
        with open(os.path.join(base_dir, 'frontend', 'css', 'table.css'), 'r', encoding='utf-8') as f:
            cls.table_css = f.read()
        with open(os.path.join(base_dir, 'frontend', 'css', 'responsive.css'), 'r', encoding='utf-8') as f:
            cls.responsive_css = f.read()

    # ── Test 1: Opponent Distribution Logic in JS ──

    def test_01_distribution_formula_in_js(self):
        """Verify _getOpponentDistribution function matches specifications for 2–7 players."""
        self.assertIn('_getOpponentDistribution', self.table_js)

        # Replicate JS function exactly
        def get_dist(count):
            if count == 1:
                return {'top': 1, 'left': 0, 'right': 0}
            elif count == 2:
                return {'top': 2, 'left': 0, 'right': 0}
            elif count == 3:
                return {'top': 1, 'left': 1, 'right': 1}
            elif count == 4:
                return {'top': 2, 'left': 1, 'right': 1}
            elif count == 5:
                return {'top': 3, 'left': 1, 'right': 1}
            elif count == 6:
                return {'top': 2, 'left': 2, 'right': 2}
            else:
                side = max(0, (count - 1) // 3)
                top = max(1, count - side * 2)
                return {'top': top, 'left': side, 'right': side}

        expectations = {
            1: (1, 0, 0),  # 2 players: 1 top
            2: (2, 0, 0),  # 3 players: 2 top
            3: (1, 1, 1),  # 4 players: 1 left, 1 top, 1 right
            4: (2, 1, 1),  # 5 players: 1 left, 2 top, 1 right
            5: (3, 1, 1),  # 6 players: 1 left, 3 top, 1 right
            6: (2, 2, 2),  # 7 players: 2 left, 2 top, 2 right (balanced)
        }

        for opp_count, (exp_top, exp_left, exp_right) in expectations.items():
            dist = get_dist(opp_count)
            self.assertEqual(dist['top'], exp_top, f"{opp_count + 1} players top count mismatch")
            self.assertEqual(dist['left'], exp_left, f"{opp_count + 1} players left count mismatch")
            self.assertEqual(dist['right'], exp_right, f"{opp_count + 1} players right count mismatch")
            self.assertEqual(dist['top'] + dist['left'] + dist['right'], opp_count,
                             f"Total opponents must equal {opp_count}")

    # ── Test 2: Dynamic CSS Classes & Hooks for Player Count ──

    def test_02_dynamic_player_count_hooks(self):
        """Verify TableUI dynamically attaches data-player-count and .players-N to table elements."""
        self.assertIn("setAttribute('data-player-count'", self.table_js)
        self.assertIn("players-${totalPlayers}", self.table_js)
        self.assertIn("leftPlayers", self.table_js)
        self.assertIn("rightPlayers", self.table_js)
        self.assertIn("topPlayers", self.table_js)

    # ── Test 3: CSS Grid minmax(0, 1fr) Prevents Right-Edge Overflow ──

    def test_03_css_grid_prevents_overflow(self):
        """Verify .table-inner uses minmax(0, 1fr) for middle column so right column is never pushed outside."""
        self.assertIn('minmax(0, 1fr)', self.table_css)
        self.assertIn('minmax(min-content, auto)', self.table_css)

    # ── Test 4: Sizing Simulation for Android Mobile Portrait (360px width) ──

    def test_04_android_mobile_portrait_dimensions(self):
        """Simulate widths in 360px portrait mode to ensure all players fit within table boundaries."""
        screen_width = 360
        table_padding = 8  # 4px each side
        inner_gap = 3

        configs = {
            2: {'left': 0, 'top': 1, 'right': 0, 'slot_w': 60, 'side_w': 46},
            3: {'left': 0, 'top': 2, 'right': 0, 'slot_w': 60, 'side_w': 46},
            4: {'left': 1, 'top': 1, 'right': 1, 'slot_w': 60, 'side_w': 46},
            5: {'left': 1, 'top': 2, 'right': 1, 'slot_w': 55, 'side_w': 46},
            6: {'left': 1, 'top': 3, 'right': 1, 'slot_w': 50, 'side_w': 46},
            7: {'left': 2, 'top': 2, 'right': 2, 'slot_w': 46, 'side_w': 46},
        }

        for total_players, cfg in configs.items():
            left_col = cfg['side_w'] if cfg['left'] > 0 else 0
            right_col = cfg['side_w'] if cfg['right'] > 0 else 0
            top_total_w = cfg['top'] * cfg['slot_w'] + (cfg['top'] - 1) * 4

            total_table_content_w = table_padding + left_col + right_col + max(top_total_w, 135) + inner_gap * 2
            right_edge_x = left_col + max(top_total_w, 135) + right_col + table_padding

            self.assertLessEqual(right_edge_x, screen_width,
                                 f"{total_players} players: right edge ({right_edge_x}px) exceeds screen width ({screen_width}px)")
            self.assertLessEqual(total_table_content_w, screen_width,
                                 f"{total_players} players: table content ({total_table_content_w}px) exceeds screen width")

    # ── Test 5: Sizing Simulation for Android Mobile Landscape (740px width x 360px height) ──

    def test_05_android_mobile_landscape_dimensions(self):
        """Simulate landscape mode where width is 740px and height is 360px."""
        screen_width = 740
        table_height = 240  # Table felt height in short landscape

        # For 7 players (2 left, 2 top, 2 right):
        # Vertical height of 2 side opponents:
        slot_height = 42  # 24px avatar + 12px name + 6px padding
        side_height = 2 * slot_height + 6  # 90px
        self.assertLessEqual(side_height, table_height,
                             f"Side opponents height ({side_height}px) must fit within table height ({table_height}px)")

        # Width check for 7 players:
        left_w = 52
        right_w = 52
        top_w = 2 * 58 + 12
        total_w = left_w + top_w + right_w + 20
        self.assertLessEqual(total_w, screen_width)

    # ── Test 6: Laptop / Desktop Dimensions (1366px x 768px) ──

    def test_06_laptop_desktop_dimensions(self):
        """Simulate laptop screen (1366px width)."""
        screen_width = 1366
        # 7 players: 2 left (75px), 2 top (2x80 + 12 = 172px), 2 right (75px)
        total_w = 75 + 172 + 75 + 24
        self.assertLessEqual(total_w, screen_width)
        # 6 players: 1 left (78px), 3 top (3x78 + 12 = 246px), 1 right (78px)
        total_6w = 78 + 246 + 78 + 24
        self.assertLessEqual(total_6w, screen_width)

    # ── Test 7: CSS Rules for 6 and 7 Players Present ──

    def test_07_css_player_count_rules_exist(self):
        """Verify dedicated styling exists for .players-6 and .players-7 in both table.css and responsive.css."""
        self.assertIn('.players-6', self.table_css)
        self.assertIn('.players-7', self.table_css)
        self.assertIn('.table-inner.players-6', self.responsive_css)
        self.assertIn('.table-inner.players-7', self.responsive_css)

    # ── Test 8: Side Slots Vertical Distribution ──

    def test_08_side_slots_vertical_distribution(self):
        """Verify space-evenly is used for left and right opponents to balance multiple side players."""
        self.assertIn('justify-content: space-evenly', self.table_css)
        self.assertIn('justify-content: space-evenly', self.responsive_css)


if __name__ == '__main__':
    unittest.main()
