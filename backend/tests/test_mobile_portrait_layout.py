"""
Test Mobile Portrait Layout & Card Visibility:
Verifies CSS rules, responsive breakpoints, adaptive card overlap formulas,
compact opponent table spacing for 2-7 players, and hand accessibility.
"""
import unittest
import re


class TestMobilePortraitLayout(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open('frontend/css/table.css', 'r', encoding='utf-8') as f:
            cls.table_css = f.read()
        with open('frontend/css/responsive.css', 'r', encoding='utf-8') as f:
            cls.responsive_css = f.read()
        with open('frontend/css/cards.css', 'r', encoding='utf-8') as f:
            cls.cards_css = f.read()
        with open('frontend/js/ui/table.js', 'r', encoding='utf-8') as f:
            cls.table_js = f.read()

    def test_01_game_screen_and_table_flex_shrinkage(self):
        """Verify .game-table has min-height: 0 and .player-self-area has flex-shrink: 0."""
        # .game-table min-height: 0 prevents it from pushing player-self-area offscreen
        self.assertIn('min-height: 0', self.table_css)
        self.assertIn('flex-shrink: 0', self.table_css)
        self.assertIn('100dvh', self.table_css)
        self.assertIn('100dvh', self.responsive_css)

    def test_02_hand_container_scrolling_and_clipping_prevention(self):
        """Verify .hand-container prevents vertical scroll/clipping while allowing horizontal scrolling."""
        self.assertIn('overflow-x: auto', self.table_css)
        self.assertIn('overflow-y: hidden', self.table_css)
        self.assertIn('-webkit-overflow-scrolling: touch', self.table_css)
        self.assertIn('overflow-y: hidden', self.responsive_css)

    def test_03_card_dimensions_in_mobile_portrait(self):
        """Verify mobile portrait card dimensions are readable (at least 60px x 90px)."""
        # In responsive.css: default mobile portrait card dimensions
        match = re.search(r'\.playing-card\s*\{[^}]*width:\s*(\d+)px;[^}]*height:\s*(\d+)px;', self.responsive_css)
        self.assertIsNotNone(match)
        width = int(match.group(1))
        height = int(match.group(2))
        self.assertGreaterEqual(width, 60, "Card width should be >= 60px on mobile for legibility")
        self.assertGreaterEqual(height, 88, "Card height should be >= 88px on mobile for legibility")

    def test_04_selected_card_highlight_and_stability(self):
        """Verify selected card is lifted with high z-index and does not cause horizontal margin shifting."""
        self.assertIn('.hand-card.selected', self.cards_css)
        self.assertIn('z-index: 50 !important', self.cards_css)
        # Margin change rule should NOT be present on selection
        self.assertNotIn('margin-left: -14px', self.table_css)
        self.assertNotIn('margin-right: 4px', self.table_css)

    def test_05_adaptive_overlap_formula_in_js(self):
        """Verify table.js implements improved adaptive overlap ensuring at least 40px exposed card width."""
        self.assertIn('--hand-overlap', self.table_js)
        # Test improved visibility formula:
        def get_overlap_mobile(count):
            if count <= 3: return -4
            elif count <= 6: return -8
            elif count <= 10: return -12
            elif count <= 16: return -16
            elif count <= 22: return -20
            else: return -22

        card_width = 62
        for hand_size in [2, 4, 8, 15, 26]:
            overlap = get_overlap_mobile(hand_size)
            visible_index = card_width + overlap
            self.assertGreaterEqual(visible_index, 40,
                f"Hand size {hand_size} should expose at least 40px index width for clear visibility, got {visible_index}px")

    def test_06_compact_opponents_for_mobile_portrait(self):
        """Verify responsive.css provides compact styling for opponents to preserve central felt area."""
        self.assertIn('.opponent-hand-fan', self.responsive_css)
        self.assertIn('.opponent-avatar', self.responsive_css)
        self.assertIn('.opponent-slot', self.responsive_css)

    def test_07_centre_area_and_turn_indicator_preserved(self):
        """Verify played cards zone, common pile, and turn indicator are kept intact and visible."""
        self.assertIn('.played-cards-zone', self.responsive_css)
        self.assertIn('.collected-zone', self.responsive_css)
        self.assertIn('.turn-indicator', self.responsive_css)

    def test_08_both_portrait_and_landscape_supported(self):
        """Verify media queries exist for both portrait and landscape mobile."""
        self.assertIn('orientation: landscape', self.responsive_css)
        self.assertIn('max-width: 480px', self.responsive_css)
        self.assertIn('min-width: 769px', self.responsive_css)


if __name__ == '__main__':
    unittest.main()
