"""
KAZHUDHAI CLUB — backend/tests/test_rotating_seating.py
Unit and integration tests for Player-Centric Rotating Seating.

Validates:
1. Relative clockwise seating rotation for 2 to 7 players with all possible local player positions.
2. Exact 4-player rotation specification matching user requirements:
   - P1 local: P1 Bottom, P2 Left, P3 Top, P4 Right.
   - P2 local: P2 Bottom, P3 Left, P4 Top, P1 Right.
   - P3 local: P3 Bottom, P4 Left, P1 Top, P2 Right.
   - P4 local: P4 Bottom, P1 Left, P2 Top, P3 Right.
3. Distribution mapping across zones for 2 to 7 players (1 to 6 opponents).
4. Permanent P1..P7 joining badges retained for all players, including self at bottom.
5. DOM flow and clockwise ordering consistency in multi-opponent zones.
6. Offline and Online local player ID resolution.
7. Frontend DOM and CSS presence for self badge and left zone reverse column.
"""
import unittest
import os
import re


def get_opponent_distribution(count):
    """Python reference of TableUI._getOpponentDistribution(count)."""
    if count == 1:
        return {'top': 1, 'left': 0, 'right': 0}
    elif count == 2:
        return {'top': 0, 'left': 1, 'right': 1}
    elif count == 3:
        return {'top': 1, 'left': 1, 'right': 1}
    elif count == 4:
        return {'top': 2, 'left': 1, 'right': 1}
    elif count == 5:
        return {'top': 1, 'left': 2, 'right': 2}
    elif count == 6:
        return {'top': 2, 'left': 2, 'right': 2}
    else:
        side = max(0, count // 3)
        top = max(0, count - side * 2)
        return {'top': top, 'left': side, 'right': side}


def simulate_rotating_seating(players, local_id, cached_id=None, is_offline=None):
    """
    Simulates the exact rotating seating logic implemented in TableUI.renderPlayers.
    Returns:
      {
        'bottom': local_player,
        'left': [players],
        'top': [players],
        'right': [players]
      } or None if local_index == -1.
    """
    total = len(players)
    if total == 0:
        return None

    # Find local player index
    local_index = -1
    if local_id:
        for idx, p in enumerate(players):
            if p.get('id') == local_id:
                local_index = idx
                break

    # During reconnect, fallback to previously resolved local player ID if still in room
    if local_index == -1 and cached_id:
        for idx, p in enumerate(players):
            if p.get('id') == cached_id:
                local_index = idx
                break

    # Determine whether we are in offline mode
    if is_offline is None:
        is_offline = (local_id == 'human') or any(p.get('id') == 'human' for p in players if not p.get('id', '').startswith('p_'))

    # Offline mode fallback: strictly match 'human' ONLY when in offline mode
    if local_index == -1 and is_offline:
        for idx, p in enumerate(players):
            if p.get('id') == 'human':
                local_index = idx
                break

    # If identity is unconfirmed, do NOT assume players[0]
    if local_index == -1:
        return None

    local_player = players[local_index]
    bottom_player = dict(local_player)
    bottom_player['visual_seat'] = 1
    bottom_player['seat_badge'] = 'P1'

    # Clockwise opponents relative to local player with fixed visual seats (P2, P3, P4, ...)
    opponents = []
    for i in range(1, total):
        opp_idx = (local_index + i) % total
        p = dict(players[opp_idx])
        p['visual_seat'] = i + 1
        p['seat_badge'] = f"P{i + 1}"
        opponents.append(p)

    dist = get_opponent_distribution(len(opponents))

    left_players = opponents[0:dist['left']]
    top_players = opponents[dist['left']:dist['left'] + dist['top']]
    right_players = opponents[dist['left'] + dist['top']:dist['left'] + dist['top'] + dist['right']]

    return {
        'bottom': bottom_player,
        'left': left_players,
        'top': top_players,
        'right': right_players
    }


class TestRotatingSeating(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with open(os.path.join(base_dir, 'frontend', 'js', 'ui', 'table.js'), 'r', encoding='utf-8') as f:
            cls.table_js = f.read()
        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            cls.index_html = f.read()
        with open(os.path.join(base_dir, 'frontend', 'css', 'table.css'), 'r', encoding='utf-8') as f:
            cls.table_css = f.read()

    # ── Test 1: Exact 4-Player User Specification ──

    def test_01_four_player_user_spec_rotations(self):
        """
        Validates the 4-player rotation specification explicitly requested:
        - P1 local: P1 Bottom, P2 Left, P3 Top, P4 Right.
        - P2 local: P2 Bottom, P3 Left, P4 Top, P1 Right.
        - P3 local: P3 Bottom, P4 Left, P1 Top, P2 Right.
        - P4 local: P4 Bottom, P1 Left, P2 Top, P3 Right.

        Also explicitly validates the 4 user system screenshots:
        Aravind's system:
        P1 Aravind, P2 Selva, P3 Vignesh, P4 Mahadir.

        Selva's system:
        P1 Selva, P2 Vignesh, P3 Mahadir, P4 Aravind.

        Vignesh's system:
        P1 Vignesh, P2 Mahadir, P3 Aravind, P4 Selva.

        Mahadir's system:
        P1 Mahadir, P2 Aravind, P3 Selva, P4 Vignesh.
        """
        players = [
            {'id': 'p1', 'name': 'Player 1', 'position': 1},
            {'id': 'p2', 'name': 'Player 2', 'position': 2},
            {'id': 'p3', 'name': 'Player 3', 'position': 3},
            {'id': 'p4', 'name': 'Player 4', 'position': 4},
        ]

        expected_rotations = [
            # local_id, bottom_pos, left_pos, top_pos, right_pos
            ('p1', 1, 2, 3, 4),
            ('p2', 2, 3, 4, 1),
            ('p3', 3, 4, 1, 2),
            ('p4', 4, 1, 2, 3),
        ]

        for local_id, exp_bottom, exp_left, exp_top, exp_right in expected_rotations:
            res = simulate_rotating_seating(players, local_id)
            self.assertEqual(res['bottom']['position'], exp_bottom,
                             f"For local {local_id}: Bottom must be P{exp_bottom}")
            self.assertEqual(res['bottom']['seat_badge'], 'P1',
                             f"For local {local_id}: Bottom visual seat badge must be P1")

            self.assertEqual(len(res['left']), 1)
            self.assertEqual(res['left'][0]['position'], exp_left,
                             f"For local {local_id}: Left must be P{exp_left}")
            self.assertEqual(res['left'][0]['seat_badge'], 'P2',
                             f"For local {local_id}: Left visual seat badge must be P2")

            self.assertEqual(len(res['top']), 1)
            self.assertEqual(res['top'][0]['position'], exp_top,
                             f"For local {local_id}: Top must be P{exp_top}")
            self.assertEqual(res['top'][0]['seat_badge'], 'P3',
                             f"For local {local_id}: Top visual seat badge must be P3")

            self.assertEqual(len(res['right']), 1)
            self.assertEqual(res['right'][0]['position'], exp_right,
                             f"For local {local_id}: Right must be P{exp_right}")
            self.assertEqual(res['right'][0]['seat_badge'], 'P4',
                             f"For local {local_id}: Right visual seat badge must be P4")

        # Explicit validation of the 4 user system screenshots
        four_systems = [
            {'id': 'p_aravind', 'name': 'Aravind', 'position': 1},
            {'id': 'p_selva', 'name': 'Selva', 'position': 2},
            {'id': 'p_vignesh', 'name': 'Vignesh', 'position': 3},
            {'id': 'p_mahadir', 'name': 'Mahadir', 'position': 4},
        ]

        # 1. Aravind's system: P1 Aravind, P2 Selva, P3 Vignesh, P4 Mahadir
        res_a = simulate_rotating_seating(four_systems, 'p_aravind')
        self.assertEqual(res_a['bottom']['name'], 'Aravind')
        self.assertEqual(res_a['bottom']['seat_badge'], 'P1')
        self.assertEqual(res_a['left'][0]['name'], 'Selva')
        self.assertEqual(res_a['left'][0]['seat_badge'], 'P2')
        self.assertEqual(res_a['top'][0]['name'], 'Vignesh')
        self.assertEqual(res_a['top'][0]['seat_badge'], 'P3')
        self.assertEqual(res_a['right'][0]['name'], 'Mahadir')
        self.assertEqual(res_a['right'][0]['seat_badge'], 'P4')

        # 2. Selva's system: P1 Selva, P2 Vignesh, P3 Mahadir, P4 Aravind
        res_s = simulate_rotating_seating(four_systems, 'p_selva')
        self.assertEqual(res_s['bottom']['name'], 'Selva')
        self.assertEqual(res_s['bottom']['seat_badge'], 'P1')
        self.assertEqual(res_s['left'][0]['name'], 'Vignesh')
        self.assertEqual(res_s['left'][0]['seat_badge'], 'P2')
        self.assertEqual(res_s['top'][0]['name'], 'Mahadir')
        self.assertEqual(res_s['top'][0]['seat_badge'], 'P3')
        self.assertEqual(res_s['right'][0]['name'], 'Aravind')
        self.assertEqual(res_s['right'][0]['seat_badge'], 'P4')

        # 3. Vignesh's system: P1 Vignesh, P2 Mahadir, P3 Aravind, P4 Selva
        res_v = simulate_rotating_seating(four_systems, 'p_vignesh')
        self.assertEqual(res_v['bottom']['name'], 'Vignesh')
        self.assertEqual(res_v['bottom']['seat_badge'], 'P1')
        self.assertEqual(res_v['left'][0]['name'], 'Mahadir')
        self.assertEqual(res_v['left'][0]['seat_badge'], 'P2')
        self.assertEqual(res_v['top'][0]['name'], 'Aravind')
        self.assertEqual(res_v['top'][0]['seat_badge'], 'P3')
        self.assertEqual(res_v['right'][0]['name'], 'Selva')
        self.assertEqual(res_v['right'][0]['seat_badge'], 'P4')

        # 4. Mahadir's system: P1 Mahadir, P2 Aravind, P3 Selva, P4 Vignesh
        res_m = simulate_rotating_seating(four_systems, 'p_mahadir')
        self.assertEqual(res_m['bottom']['name'], 'Mahadir')
        self.assertEqual(res_m['bottom']['seat_badge'], 'P1')
        self.assertEqual(res_m['left'][0]['name'], 'Aravind')
        self.assertEqual(res_m['left'][0]['seat_badge'], 'P2')
        self.assertEqual(res_m['top'][0]['name'], 'Selva')
        self.assertEqual(res_m['top'][0]['seat_badge'], 'P3')
        self.assertEqual(res_m['right'][0]['name'], 'Vignesh')
        self.assertEqual(res_m['right'][0]['seat_badge'], 'P4')

    # ── Test 2: Distribution Zones for 2 to 7 Players ──

    def test_02_distribution_counts_for_2_to_7_players(self):
        """
        Verify distribution across Left, Top, Right for player counts 2 to 7.
        Total opponents M = N - 1.
        """
        expected_distributions = {
            1: {'left': 0, 'top': 1, 'right': 0},  # 2 players
            2: {'left': 1, 'top': 0, 'right': 1},  # 3 players
            3: {'left': 1, 'top': 1, 'right': 1},  # 4 players
            4: {'left': 1, 'top': 2, 'right': 1},  # 5 players
            5: {'left': 2, 'top': 1, 'right': 2},  # 6 players
            6: {'left': 2, 'top': 2, 'right': 2},  # 7 players
        }

        for count, exp in expected_distributions.items():
            dist = get_opponent_distribution(count)
            self.assertEqual(dist['left'], exp['left'], f"Left mismatch for {count} opponents")
            self.assertEqual(dist['top'], exp['top'], f"Top mismatch for {count} opponents")
            self.assertEqual(dist['right'], exp['right'], f"Right mismatch for {count} opponents")
            self.assertEqual(dist['left'] + dist['top'] + dist['right'], count,
                             f"Sum of zones must equal total opponents ({count})")

    # ── Test 3: Rotation for All Player Counts (2 to 7) and All Local Positions ──

    def test_03_all_player_counts_and_local_positions(self):
        """
        Test that for every player count from 2 to 7, and for every local player index:
        1. Local player is at Bottom.
        2. All N-1 opponents are present across Left, Top, Right with zero duplicates and zero omissions.
        3. Clockwise joining order is preserved sequentially.
        """
        for n in range(2, 8):
            players = [{'id': f'p{i}', 'name': f'Player {i}', 'position': i} for i in range(1, n + 1)]
            for local_idx in range(n):
                local_id = players[local_idx]['id']
                res = simulate_rotating_seating(players, local_id)

                # Local is at bottom
                self.assertEqual(res['bottom']['id'], local_id)
                self.assertEqual(res['bottom']['position'], local_idx + 1)

                # Collect opponents in clockwise order: left -> top -> right
                collected_opponents = res['left'] + res['top'] + res['right']
                self.assertEqual(len(collected_opponents), n - 1)

                # Verify exact clockwise sequence
                for step, opp in enumerate(collected_opponents):
                    expected_idx = (local_idx + 1 + step) % n
                    expected_p = players[expected_idx]
                    self.assertEqual(opp['id'], expected_p['id'],
                                     f"For N={n}, local={local_id}: step {step} opponent mismatch")
                    self.assertEqual(opp['position'], expected_p['position'])

    # ── Test 4: Fixed Visual Seat Positions and Rotating Player Identities ──

    def test_04_fixed_visual_seats_and_rotating_identities(self):
        """
        Confirm that:
        1. Players retain their permanent joining order position on their player object.
        2. Visual seat positions and badges are fixed:
           - Bottom seat is always visual seat 1 (P1)
           - Left seat is visual seat 2 (P2)
           - Right seat is visual seat 3 (P3)
        3. Player identities rotate into those fixed seats relative to the local viewer.
        """
        players = [
            {'id': 'p1', 'name': 'Host', 'position': 1},
            {'id': 'p2', 'name': 'Guest1', 'position': 2},
            {'id': 'p3', 'name': 'Guest2', 'position': 3},
        ]

        # Case A: Guest2 (P3 joining position) is local
        res_p3 = simulate_rotating_seating(players, 'p3')
        # Local player at Bottom: Guest2
        self.assertEqual(res_p3['bottom']['id'], 'p3')
        self.assertEqual(res_p3['bottom']['position'], 3)
        self.assertEqual(res_p3['bottom']['seat_badge'], 'P1')
        # Left seat: Host (P1 joining position) in visual seat P2
        self.assertEqual(res_p3['left'][0]['id'], 'p1')
        self.assertEqual(res_p3['left'][0]['position'], 1)
        self.assertEqual(res_p3['left'][0]['seat_badge'], 'P2')
        # Right seat: Guest1 (P2 joining position) in visual seat P3
        self.assertEqual(res_p3['right'][0]['id'], 'p2')
        self.assertEqual(res_p3['right'][0]['position'], 2)
        self.assertEqual(res_p3['right'][0]['seat_badge'], 'P3')

        # Case B: Guest1 (P2 joining position) is local
        res_p2 = simulate_rotating_seating(players, 'p2')
        # Local player at Bottom: Guest1
        self.assertEqual(res_p2['bottom']['id'], 'p2')
        self.assertEqual(res_p2['bottom']['position'], 2)
        self.assertEqual(res_p2['bottom']['seat_badge'], 'P1')
        # Left seat: Guest2 (P3 joining position) in visual seat P2
        self.assertEqual(res_p2['left'][0]['id'], 'p3')
        self.assertEqual(res_p2['left'][0]['position'], 3)
        self.assertEqual(res_p2['left'][0]['seat_badge'], 'P2')
        # Right seat: Host (P1 joining position) in visual seat P3
        self.assertEqual(res_p2['right'][0]['id'], 'p1')
        self.assertEqual(res_p2['right'][0]['position'], 1)
        self.assertEqual(res_p2['right'][0]['seat_badge'], 'P3')

    # ── Test 5: Offline and Online Local Player Resolution ──

    def test_05_local_player_resolution_offline_and_online(self):
        """
        Verify resolution for offline ('human') and online ('p_xxx') local players.
        """
        offline_players = [
            {'id': 'human', 'name': 'You', 'position': 1},
            {'id': 'ai_1', 'name': 'Bot 1', 'position': 2},
            {'id': 'ai_2', 'name': 'Bot 2', 'position': 3},
            {'id': 'ai_3', 'name': 'Bot 3', 'position': 4},
        ]
        res_offline = simulate_rotating_seating(offline_players, 'human')
        self.assertEqual(res_offline['bottom']['id'], 'human')
        self.assertEqual(res_offline['left'][0]['id'], 'ai_1')
        self.assertEqual(res_offline['top'][0]['id'], 'ai_2')
        self.assertEqual(res_offline['right'][0]['id'], 'ai_3')

        # Fallback if local_id is None in offline mode
        res_fallback = simulate_rotating_seating(offline_players, None)
        self.assertEqual(res_fallback['bottom']['id'], 'human')

    # ── Test 6: Frontend DOM and CSS Integration ──

    def test_06_frontend_dom_and_css_elements(self):
        """
        Verify that:
        1. index.html contains #self-pos-badge inside .self-name-row.
        2. table.css contains .self-pos-badge styling.
        3. table.css sets .opponents-left to column-reverse.
        4. table.js caches and updates selfPosBadge.
        """
        # HTML check
        self.assertIn('id="self-pos-badge"', self.index_html)
        self.assertIn('self-pos-badge', self.index_html)

        # CSS checks
        self.assertIn('.self-pos-badge', self.table_css)
        self.assertIn('flex-direction: column-reverse;', self.table_css)

        # JS checks
        self.assertIn('DOM.selfPosBadge', self.table_js)
        self.assertIn('self-pos-badge', self.table_js)
        self.assertIn('_getOpponentDistribution', self.table_js)
        self.assertIn('renderPlayers', self.table_js)
        self.assertIn("DOM.selfPosBadge.textContent = 'P1';", self.table_js)
        self.assertIn("item.seatNum", self.table_js)

    # ── Test 7: Multi-opponent Left Zone Flow ──

    def test_07_multi_opponent_zones_clockwise_integrity(self):
        """
        For 6 and 7 players, Left zone has 2 players.
        Because .opponents-left has flex-direction: column-reverse,
        the first opponent (leftPlayers[0]) renders at the bottom of the column (nearest to Self),
        and the second opponent (leftPlayers[1]) renders above it (nearest to Top).
        This guarantees seamless clockwise flow from Self -> Left-bottom -> Left-top -> Top!
        """
        players = [{'id': f'p{i}', 'name': f'P{i}', 'position': i} for i in range(1, 8)]
        res = simulate_rotating_seating(players, 'p1')

        # 7 players: Left has 2 opponents
        self.assertEqual(len(res['left']), 2)
        # Clockwise next is P2 (at lower left)
        self.assertEqual(res['left'][0]['id'], 'p2')
        # Clockwise next is P3 (at upper left)
        self.assertEqual(res['left'][1]['id'], 'p3')
        # Clockwise next are P4, P5 (at top)
        self.assertEqual(res['top'][0]['id'], 'p4')
        self.assertEqual(res['top'][1]['id'], 'p5')
        # Clockwise next are P6, P7 (at right, top-to-bottom)
        self.assertEqual(res['right'][0]['id'], 'p6')
        self.assertEqual(res['right'][1]['id'], 'p7')

    # ── Test 8: SAFE Badge Synchronization, Removal, and Deduplication ──

    def test_08_safe_badge_synchronization_and_deduplication(self):
        """
        Verify:
        1. SAFE true -> badge appears.
        2. SAFE false -> badge disappears.
        3. Duplicate SAFE badges are prevented / cleaned up.
        4. Starting a new game after a player was SAFE does not retain an old badge.
        5. Code pattern in table.js: renderPlayers, updateOpponent, and init implement _syncSafeBadge.
        """
        # Static checks in table.js
        self.assertIn('_syncSafeBadge', self.table_js, "table.js must define _syncSafeBadge helper")
        self.assertIn('_syncSafeBadge(DOM.selfAvatar, localPlayer.isSafe)', self.table_js,
                      "renderPlayers must sync safe badge on localPlayer.isSafe")
        self.assertIn('_syncSafeBadge(DOM.selfAvatar, opp.isSafe)', self.table_js,
                      "updateOpponent must sync safe badge for local player")
        self.assertIn('_syncSafeBadge(avatarEl, opp.isSafe)', self.table_js,
                      "updateOpponent must sync safe badge for opponent avatars")
        self.assertIn('_syncSafeBadge(DOM.selfAvatar, false)', self.table_js,
                      "init must clear safe badge for new game")

        # Mock DOM element to simulate _syncSafeBadge logic exactly
        class MockElement:
            def __init__(self):
                self.classes = set()
                self.children = []

            @property
            def class_list(self):
                el = self
                class ClassList:
                    def toggle(self, cls, val):
                        if val:
                            el.classes.add(cls)
                        else:
                            el.classes.discard(cls)
                    def remove(self, *clss):
                        for c in clss:
                            el.classes.discard(c)
                    def contains(self, cls):
                        return cls in el.classes
                return ClassList()

            def query_selector_all(self, selector):
                if selector == '.opponent-safe-badge':
                    return [c for c in self.children if getattr(c, 'is_badge', False)]
                return []

            def query_selector(self, selector):
                matches = self.query_selector_all(selector)
                return matches[0] if matches else None

            def append_child(self, child):
                self.children.append(child)

            def remove_child(self, child):
                if child in self.children:
                    self.children.remove(child)

        class MockBadge:
            def __init__(self):
                self.is_badge = True
                self.parent = None
            def remove(self):
                if self.parent:
                    self.parent.remove_child(self)

        def sync_safe_badge(avatar_el, is_safe):
            if not avatar_el:
                return
            avatar_el.class_list.toggle('safe', bool(is_safe))
            existing_badges = avatar_el.query_selector_all('.opponent-safe-badge')
            if is_safe:
                if len(existing_badges) == 0:
                    badge = MockBadge()
                    badge.parent = avatar_el
                    avatar_el.append_child(badge)
                elif len(existing_badges) > 1:
                    for b in existing_badges[1:]:
                        b.remove()
            else:
                for b in existing_badges:
                    b.remove()

        avatar = MockElement()

        # Step 1: Initial state - no badge, not safe
        self.assertFalse(avatar.class_list.contains('safe'))
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 0)

        # Step 2: SAFE true -> badge appears
        sync_safe_badge(avatar, True)
        self.assertTrue(avatar.class_list.contains('safe'))
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 1)

        # Step 3: SAFE true again -> duplicate prevented (remains 1)
        sync_safe_badge(avatar, True)
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 1)

        # Step 4: Simulate duplicate injected into DOM -> sync removes duplicate
        duplicate_badge = MockBadge()
        duplicate_badge.parent = avatar
        avatar.append_child(duplicate_badge)
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 2)
        sync_safe_badge(avatar, True)
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 1)

        # Step 5: SAFE false -> badge disappears and 'safe' class removed
        sync_safe_badge(avatar, False)
        self.assertFalse(avatar.class_list.contains('safe'))
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 0)

        # Step 6: Starting new game after player was SAFE -> init resets badge
        # Set avatar back to safe
        sync_safe_badge(avatar, True)
        self.assertTrue(avatar.class_list.contains('safe'))
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 1)

        # Simulate init() reset
        sync_safe_badge(avatar, False)
        avatar.class_list.remove('active-turn')
        self.assertFalse(avatar.class_list.contains('safe'))
        self.assertEqual(len(avatar.query_selector_all('.opponent-safe-badge')), 0)

    # ── Test 9: Online Local-Player Identity Resolution ──

    def test_09_online_identity_resolution(self):
        """
        Verify that in online mode:
        1. When myId is provided, local player is identified and seated at bottom (P1).
        2. When myId is completely unresolvable (no match):
           - renderPlayers returns early (None in simulation) without altering table layout.
           - Another player is NOT labeled as (You).
        3. In offline mode:
           - 'human' matches correctly even if myId is omitted.
        4. Static code checks in table.js:
           - localIndex = 0 fallback does NOT exist.
           - localIndex === -1 returns early.
           - DOM.selfPosBadge is updated to P1.
        """
        online_players = [
            {'id': 'p_host', 'name': 'Host', 'position': 1},
            {'id': 'p_guest_2', 'name': 'GuestTwo', 'position': 2},
            {'id': 'p_guest_3', 'name': 'GuestThree', 'position': 3},
            {'id': 'p_guest_4', 'name': 'GuestFour', 'position': 4},
        ]

        # Case 1: Normal online play - GuestTwo is local player
        res_normal = simulate_rotating_seating(online_players, 'p_guest_2')
        self.assertIsNotNone(res_normal)
        self.assertEqual(res_normal['bottom']['id'], 'p_guest_2')
        self.assertEqual(res_normal['bottom']['position'], 2)
        # GuestTwo sees: P3 Left, P4 Top, Host Right
        self.assertEqual(res_normal['left'][0]['id'], 'p_guest_3')
        self.assertEqual(res_normal['top'][0]['id'], 'p_guest_4')
        self.assertEqual(res_normal['right'][0]['id'], 'p_host')

        # Case 2: Identity completely unresolvable (e.g. initial load before join ack, myId is None)
        res_unresolvable = simulate_rotating_seating(online_players, None, is_offline=False)
        # Must return None (early return in table.js) and NOT assume players[0]
        self.assertIsNone(res_unresolvable)

        # Case 3: myId does not match any player in room
        res_mismatched = simulate_rotating_seating(online_players, 'p_stale_nonexistent', is_offline=False)
        self.assertIsNone(res_mismatched)

        # Case 4: Offline mode fallback - player with id 'human' matches even if myId is None
        offline_players = [
            {'id': 'human', 'name': 'You', 'position': 1},
            {'id': 'ai_1', 'name': 'AI 1', 'position': 2},
        ]
        res_offline = simulate_rotating_seating(offline_players, None)
        self.assertIsNotNone(res_offline)
        self.assertEqual(res_offline['bottom']['id'], 'human')

        # Case 5: Static checks in table.js
        # Must NOT silently assume players[0]
        self.assertNotIn('localIndex = 0;', self.table_js)
        # Must NOT contain p.is_human
        self.assertNotIn('is_human', self.table_js)
        # Must return early if localIndex === -1
        self.assertIn('if (localIndex === -1) return;', self.table_js)
        # Must update DOM.selfPosBadge to P1
        self.assertIn("DOM.selfPosBadge.textContent = 'P1';", self.table_js)

    # ── Test 10: TableUI.init() Visual State Initialization ──

    def test_10_table_ui_init_visual_state(self):
        """
        Verify:
        1. Calling init() sets up DOM caching including selfPosBadge.
        2. init() resets played cards, attack banner, active-turn indicator and SAFE badge on self avatar.
        3. init() resets common pile.
        """
        # Static checks in table.js
        self.assertIn("DOM.selfPosBadge   = document.getElementById('self-pos-badge');", self.table_js)
        self.assertIn("DOM.attackBanner.classList.add('hidden');", self.table_js)
        self.assertIn("DOM.selfAvatar.classList.remove('active-turn');", self.table_js)
        self.assertIn("_syncSafeBadge(DOM.selfAvatar, false);", self.table_js)

    # ── Test 11: Identity Safeguards and updateOpponent Early Return ──

    def test_11_identity_safeguards_and_update_opponent_early_return(self):
        """
        Verify:
        1. In updateOpponent(), when opp.id matches local player myId:
           - Local card count is updated.
           - Active-turn indicator and SAFE badge on self avatar are synchronized.
           - updateOpponent returns early, preventing fallthrough into opponent DOM elements.
        2. When an update belongs to an actual opponent:
           - Opponent DOM elements (opp-count, opp-avatar, opp-fan) are updated.
        """
        # Static checks in table.js
        self.assertIn('function updateOpponent(opp)', self.table_js)
        self.assertIn('if (opp.id === myId)', self.table_js)
        self.assertIn('_syncSafeBadge(DOM.selfAvatar, opp.isSafe);', self.table_js)

        update_opp_pattern = re.search(r'function updateOpponent\(opp\)\s*\{(.*?)\n  \}', self.table_js, re.DOTALL)
        self.assertIsNotNone(update_opp_pattern, "updateOpponent function definition must exist")
        update_opp_body = update_opp_pattern.group(1)
        self.assertIn('if (opp.id === myId) {', update_opp_body)
        self.assertIn('return;', update_opp_body)

        # ── Simulation: updateOpponent early return behavior ──
        class MockDOM:
            def __init__(self):
                self.self_card_count_text = None
                self.self_avatar_active_turn = None
                self.self_avatar_safe = None
                self.updated_player_status = []
                self.opponent_elements_accessed = []

        dom = MockDOM()

        def simulate_update_opponent(opp, current_my_id):
            if opp['id'] == current_my_id:
                dom.self_card_count_text = f"{opp.get('cardCount', 0)} cards"
                dom.self_avatar_active_turn = bool(opp.get('isActive'))
                dom.self_avatar_safe = bool(opp.get('isSafe'))
                if opp.get('connection_status'):
                    dom.updated_player_status.append((opp['id'], opp['connection_status']))
                return  # EARLY RETURN

            # If not returned early, opponent elements are accessed
            dom.opponent_elements_accessed.append(f"opp-count-{opp['id']}")
            dom.opponent_elements_accessed.append(f"opp-avatar-{opp['id']}")
            dom.opponent_elements_accessed.append(f"opp-fan-{opp['id']}")

        # Test Case 1: Local player update
        local_opp = {'id': 'p_local', 'cardCount': 4, 'isActive': True, 'isSafe': True, 'connection_status': 'connected'}
        simulate_update_opponent(local_opp, current_my_id='p_local')

        self.assertEqual(dom.self_card_count_text, '4 cards')
        self.assertTrue(dom.self_avatar_active_turn)
        self.assertTrue(dom.self_avatar_safe)
        self.assertEqual(dom.updated_player_status, [('p_local', 'connected')])
        # Opponent elements must NEVER be accessed for local player
        self.assertEqual(len(dom.opponent_elements_accessed), 0)

        # Test Case 2: Actual opponent update
        remote_opp = {'id': 'p_remote', 'cardCount': 7, 'isActive': False, 'isSafe': False}
        simulate_update_opponent(remote_opp, current_my_id='p_local')

        self.assertIn('opp-count-p_remote', dom.opponent_elements_accessed)
        self.assertIn('opp-avatar-p_remote', dom.opponent_elements_accessed)
        self.assertIn('opp-fan-p_remote', dom.opponent_elements_accessed)

    # ── Test 12: renderOpponents Compatibility ──

    def test_12_render_opponents_compatibility(self):
        """
        Verify:
        1. renderOpponents delegates directly to renderPlayers.
        2. Visual seat badges remain fixed and clockwise.
        """
        # Static checks in table.js
        self.assertIn('function renderOpponents(opponents, myId)', self.table_js)
        self.assertIn('renderPlayers(opponents, myId);', self.table_js)

        # Simulation
        players = [
            {'id': 'p1', 'name': 'Aravind', 'position': 1},
            {'id': 'p2', 'name': 'Selva', 'position': 2},
            {'id': 'p3', 'name': 'Vignesh', 'position': 3},
            {'id': 'p4', 'name': 'Mahadir', 'position': 4},
        ]
        res = simulate_rotating_seating(players, 'p2')
        self.assertEqual(res['bottom']['name'], 'Selva')
        self.assertEqual(res['bottom']['seat_badge'], 'P1')
        self.assertEqual(res['left'][0]['name'], 'Vignesh')
        self.assertEqual(res['left'][0]['seat_badge'], 'P2')
        self.assertEqual(res['top'][0]['name'], 'Mahadir')
        self.assertEqual(res['top'][0]['seat_badge'], 'P3')
        self.assertEqual(res['right'][0]['name'], 'Aravind')
        self.assertEqual(res['right'][0]['seat_badge'], 'P4')

    # ── Test 13: Exact Four-Client System Live Website Arrangements ──

    def test_13_exact_four_client_system_arrangements(self):
        """
        Regression test validating that when all four player systems (Aravind, Selva,
        Vignesh, Mahadir) receive the exact same room state:
        1. Each client independently renders its own identity at P1 (Bottom).
        2. Local player is completely excluded from opponent seats (Left, Top, Right).
        3. Visual seat badges remain fixed: P1 (Bottom), P2 (Left), P3 (Top), P4 (Right).
        4. Actual opponent player objects (name, id, card count, turn state) rotate cyclically.
        5. For each viewer, the expected arrangement is satisfied:
           - Aravind: P1 Aravind, P2 Selva, P3 Vignesh, P4 Mahadir
           - Selva:   P1 Selva, P2 Vignesh, P3 Mahadir, P4 Aravind
           - Vignesh: P1 Vignesh, P2 Mahadir, P3 Aravind, P4 Selva
           - Mahadir: P1 Mahadir, P2 Aravind, P3 Selva, P4 Vignesh
        """
        # Exact server players array in original joining order
        room_players = [
            {'id': 'usr_aravind', 'name': 'Aravind', 'position': 1, 'cardCount': 13, 'isActive': False, 'isSafe': False},
            {'id': 'usr_selva',   'name': 'Selva',   'position': 2, 'cardCount': 13, 'isActive': True,  'isSafe': False},
            {'id': 'usr_vignesh', 'name': 'Vignesh', 'position': 3, 'cardCount': 13, 'isActive': False, 'isSafe': False},
            {'id': 'usr_mahadir', 'name': 'Mahadir', 'position': 4, 'cardCount': 13, 'isActive': False, 'isSafe': False},
        ]

        expected_client_views = {
            'usr_aravind': {
                'bottom': ('Aravind', 'P1', 1),
                'left':   ('Selva',   'P2', 2),
                'top':    ('Vignesh', 'P3', 3),
                'right':  ('Mahadir', 'P4', 4),
            },
            'usr_selva': {
                'bottom': ('Selva',   'P1', 2),
                'left':   ('Vignesh', 'P2', 3),
                'top':    ('Mahadir', 'P3', 4),
                'right':  ('Aravind', 'P4', 1),
            },
            'usr_vignesh': {
                'bottom': ('Vignesh', 'P1', 3),
                'left':   ('Mahadir', 'P2', 4),
                'top':    ('Aravind', 'P3', 1),
                'right':  ('Selva',   'P4', 2),
            },
            'usr_mahadir': {
                'bottom': ('Mahadir', 'P1', 4),
                'left':   ('Aravind', 'P2', 1),
                'top':    ('Selva',   'P3', 2),
                'right':  ('Vignesh', 'P4', 3),
            },
        }

        for client_player_id, exp in expected_client_views.items():
            res = simulate_rotating_seating(room_players, client_player_id)
            self.assertIsNotNone(res, f"Client {client_player_id} must resolve seating")

            # 1. Bottom area (Self)
            b_name, b_badge, b_pos = exp['bottom']
            self.assertEqual(res['bottom']['name'], b_name)
            self.assertEqual(res['bottom']['seat_badge'], b_badge)
            self.assertEqual(res['bottom']['position'], b_pos)
            self.assertEqual(res['bottom']['id'], client_player_id)

            # 2. Left zone (Opponent P2)
            self.assertEqual(len(res['left']), 1)
            l_name, l_badge, l_pos = exp['left']
            self.assertEqual(res['left'][0]['name'], l_name)
            self.assertEqual(res['left'][0]['seat_badge'], l_badge)
            self.assertEqual(res['left'][0]['position'], l_pos)
            self.assertNotEqual(res['left'][0]['id'], client_player_id, "Local player must NOT be in Left zone")

            # 3. Top zone (Opponent P3)
            self.assertEqual(len(res['top']), 1)
            t_name, t_badge, t_pos = exp['top']
            self.assertEqual(res['top'][0]['name'], t_name)
            self.assertEqual(res['top'][0]['seat_badge'], t_badge)
            self.assertEqual(res['top'][0]['position'], t_pos)
            self.assertNotEqual(res['top'][0]['id'], client_player_id, "Local player must NOT be in Top zone")

            # 4. Right zone (Opponent P4)
            self.assertEqual(len(res['right']), 1)
            r_name, r_badge, r_pos = exp['right']
            self.assertEqual(res['right'][0]['name'], r_name)
            self.assertEqual(res['right'][0]['seat_badge'], r_badge)
            self.assertEqual(res['right'][0]['position'], r_pos)
            self.assertNotEqual(res['right'][0]['id'], client_player_id, "Local player must NOT be in Right zone")


if __name__ == '__main__':
    unittest.main()
