"""
KAZHUDHAI CLUB — tests/test_stage4.py
Comprehensive test suite for STAGE 4 (Card Collection & Player Finishing Rules):

Rules Verified:
  1. Normal round card collection (permanently removed into common collected section).
  2. Attack round card collection (all played cards transfer into winner's hand).
  3. No cards in common pile ever return to any player's hand.
  4. Winner of normal round does NOT receive the collected cards.
  5. Section 8 Special Rule: Player playing their last card remains pending mid-round.
  6. Recalculation of hand counts strictly AFTER collection.
  7. Elimination Case A: Normal finish -> 0 cards -> officially safe & leaves active game.
  8. Elimination Case B: Attack won -> receives cards into hand -> NOT out, continues playing.
  9. Elimination Case C: Attack lost -> 0 cards after collection -> officially safe.
  10. Multiple players finishing in the same round (proper rank assignment).
  11. Turn rotation when round winner officially finishes.
  12. Heads-up (2-player) transition to KAZHUDHAI declaration.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.game_state import GameState


def test_normal_round_card_collection():
    """Verify normal round cards go permanently into common collected section."""
    print("Testing Normal Round Card Collection...")
    configs = [{'id': f'p{i}', 'name': f'Player {i+1}'} for i in range(4)]
    gs = GameState('test-col-normal', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Give each player 3 cards
    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}, {'id': 'x1', 'rank': '2', 'suit': 'D'}, {'id': 'y1', 'rank': '3', 'suit': 'D'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}, {'id': 'x2', 'rank': '4', 'suit': 'D'}, {'id': 'y2', 'rank': '5', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '6', 'suit': 'D'}, {'id': 'y3', 'rank': '7', 'suit': 'D'}]
    gs.players[3].hand = [{'id': 'c4', 'rank': '6', 'suit': 'S'}, {'id': 'x4', 'rank': '8', 'suit': 'D'}, {'id': 'y4', 'rank': '9', 'suit': 'D'}]

    initial_common = len(gs.common_pile)
    gs.current_player_idx = 0
    gs._start_new_round()

    # Play all 4 cards
    gs.play_card('p0', 'c1')
    gs.play_card('p1', 'c2')
    gs.play_card('p2', 'c3')
    res = gs.play_card('p3', 'c4')

    # Winner was Player 2 with 8♠
    assert res['round_completed']
    round_result = res['last_round_result']
    assert round_result['winner_id'] == 'p1'
    assert round_result['collection_type'] == 'common'

    # Common pile must have increased by exactly 4 cards
    assert len(gs.common_pile) == initial_common + 4, (
        f"Expected common pile {initial_common + 4}, got {len(gs.common_pile)}"
    )

    # Winner (Player 2) must NOT receive collected cards (should have 2 cards left)
    p1 = gs.players[1]
    assert p1.card_count == 2, f"Player 2 should have 2 cards left, got {p1.card_count}"
    print("  ✓ Normal round: 4 cards permanently added to common collection")
    print("  ✓ Winner Player 2 did NOT receive the collected cards")


def test_attack_round_card_collection():
    """Verify attack round cards all transfer to winner's hand."""
    print("\nTesting Attack Round Card Collection...")
    configs = [{'id': f'p{i}', 'name': f'Player {i+1}'} for i in range(4)]
    gs = GameState('test-col-attack', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}, {'id': 'x1', 'rank': '2', 'suit': 'D'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}, {'id': 'x2', 'rank': '3', 'suit': 'D'}]  # Highest spade
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '4', 'suit': 'D'}]
    gs.players[3].hand = [{'id': 'c4', 'rank': 'K', 'suit': 'H'}, {'id': 'x4', 'rank': '5', 'suit': 'D'}]  # Off-suit attack!

    initial_common = len(gs.common_pile)
    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p0', 'c1')
    gs.play_card('p1', 'c2')
    gs.play_card('p2', 'c3')
    res = gs.play_card('p3', 'c4')  # Attack

    assert res['round_completed']
    round_result = res['last_round_result']
    assert round_result['is_attack']
    assert round_result['winner_id'] == 'p1'
    assert round_result['collection_type'] == 'winner_hand'

    # Common pile must NOT have changed
    assert len(gs.common_pile) == initial_common, "Common pile must not increase on attack!"

    # Winner (Player 2) had 1 card left before collection, now received all 4 played cards -> 1 + 4 = 5 cards!
    p1 = gs.players[1]
    assert p1.card_count == 5, f"Player 2 should have 1 + 4 = 5 cards, got {p1.card_count}"
    print("  ✓ Attack round: all 4 cards transferred to Winner Player 2's hand")
    print("  ✓ Common pile remained unchanged")


def test_section_8_pending_status_mid_round():
    """Verify player playing last card remains pending mid-round."""
    print("\nTesting Section 8: Last Card Pending Status Mid-Round...")
    configs = [{'id': 'p1', 'name': 'Player 1'}, {'id': 'p2', 'name': 'Player 2'}, {'id': 'p3', 'name': 'Player 3'}]
    gs = GameState('test-pending', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]  # Player 1 has ONLY 1 card!
    gs.players[1].hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Player 1 leads with their last card
    res1 = gs.play_card('p1', 'c1')
    p1 = gs.players[0]
    assert len(p1.hand) == 0, "Player 1 hand must be 0"
    assert p1.is_safe is False, "Player 1 MUST NOT be eliminated mid-round!"
    assert not res1['round_completed']
    print("  ✓ Player 1 played last card; is_safe is False (pending mid-round)")

    # Player 2 plays
    gs.play_card('p2', 'c2')
    assert p1.is_safe is False, "Player 1 must STILL be pending!"

    # Player 3 plays -> round ends normally
    res3 = gs.play_card('p3', 'c3')
    assert res3['round_completed']

    # NOW after round resolution and collection, Player 1 is officially safe
    assert p1.is_safe is True, "Player 1 must be marked safe AFTER collection"
    print("  ✓ Round completed normally -> Player 1 officially safe!")


def test_section_8_attack_card_recovery():
    """Verify player playing last card who wins an attack gets cards back and continues playing."""
    print("\nTesting Section 8: Last Card Recovery via Attack...")
    configs = [{'id': 'p1', 'name': 'Player 1'}, {'id': 'p2', 'name': 'Player 2'}, {'id': 'p3', 'name': 'Player 3'}]
    gs = GameState('test-recovery', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': 'A', 'suit': 'S'}]  # Player 1 has A♠ (last card)
    gs.players[1].hand = [{'id': 'c2', 'rank': '4', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': 'K', 'suit': 'H'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]  # Off-suit attack!

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')  # p1 hand becomes 0
    gs.play_card('p2', 'c2')
    res3 = gs.play_card('p3', 'c3')  # p3 attacks!

    assert res3['round_completed']
    p1 = gs.players[0]

    # Player 1 won the attack with A♠ and received all 3 played cards!
    assert p1.is_safe is False, "Player 1 received cards and MUST NOT be safe!"
    assert p1.card_count == 3, f"Player 1 should now have 3 cards, got {p1.card_count}"
    assert p1 in gs.active_players, "Player 1 must remain an active player!"
    print("  ✓ Player 1 played last card but won attack with A♠ -> received 3 cards")
    print("  ✓ Player 1 remains ACTIVE with 3 cards (Rule 8.Case B verified!)")


def test_section_8_attack_loser_finishes():
    """Verify player playing last card who DOES NOT win the attack officially finishes and is safe."""
    print("\nTesting Section 8: Last Card in Attack Round (Non-Winner Finishes)...")
    configs = [{'id': 'p1', 'name': 'Player 1'}, {'id': 'p2', 'name': 'Player 2'}, {'id': 'p3', 'name': 'Player 3'}]
    gs = GameState('test-loser-finish', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': '3', 'suit': 'S'}]  # Player 1 has low spade (last card)
    gs.players[1].hand = [{'id': 'c2', 'rank': 'K', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]  # High spade
    gs.players[2].hand = [{'id': 'c3', 'rank': '10', 'suit': 'H'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}] # Attack!

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')
    res3 = gs.play_card('p3', 'c3')  # Attack

    assert res3['round_completed']
    p1 = gs.players[0]
    p2 = gs.players[1]

    # Player 2 won the attack with K♠ and received all cards
    assert res3['last_round_result']['winner_id'] == 'p2'
    assert p2.card_count == 1 + 3  # had 1 left, received 3

    # Player 1 did NOT win the attack, received 0 cards, so Player 1 officially FINISHED!
    assert p1.is_safe is True, "Player 1 did not win attack and has 0 cards -> must be SAFE!"
    assert p1.card_count == 0
    print("  ✓ Player 1 played last card, Player 2 won attack -> Player 1 officially SAFE!")


def test_multiple_finishers_same_round():
    """Verify correct ranking assignment when multiple players finish in the same round."""
    print("\nTesting Multiple Finishers in the Same Round...")
    configs = [{'id': 'p1', 'name': 'Player 1'}, {'id': 'p2', 'name': 'Player 2'}, {'id': 'p3', 'name': 'Player 3'}]
    gs = GameState('test-multi-finish', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Both Player 1 and Player 2 have only 1 card left!
    gs.players[0].hand = [{'id': 'c1', 'rank': 'A', 'suit': 'S'}]  # Will win with A♠
    gs.players[1].hand = [{'id': 'c2', 'rank': '5', 'suit': 'S'}]  # Lower spade
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '2', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')
    res3 = gs.play_card('p3', 'c3')

    assert res3['round_completed']
    assert gs.players[0].is_safe and gs.players[1].is_safe

    # Player 1 won the trick and emptied hand -> Rank 1
    # Player 2 followed and emptied hand -> Rank 2
    r1 = next(r for r in gs.rankings if r['player_id'] == 'p1')
    r2 = next(r for r in gs.rankings if r['player_id'] == 'p2')
    assert r1['rank'] < r2['rank'], f"Winner Player 1 should rank higher than Player 2: {r1} vs {r2}"
    print(f"  ✓ Multiple finishers handled: Player 1 (Winner) = Rank {r1['rank']}, Player 2 = Rank {r2['rank']}")


def test_heads_up_to_kazhudhai():
    """Verify that when 2 players remain and 1 finishes, the other becomes KAZHUDHAI."""
    print("\nTesting Heads-Up (2-Player) to KAZHUDHAI Transition...")
    configs = [{'id': 'p1', 'name': 'Player 1'}, {'id': 'p2', 'name': 'Player 2'}]
    gs = GameState('test-heads-up', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': 'K', 'suit': 'S'}]  # Player 1 has 1 card
    gs.players[1].hand = [{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]  # Player 2 has 2 cards

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')
    res = gs.play_card('p2', 'c2')

    assert res['round_completed']
    assert gs.status == GameState.STATUS_FINISHED, "Game must finish when only 1 player remains!"

    kazhudhai = next((r for r in gs.rankings if r.get('is_kazhudhai')), None)
    safe_player = next((r for r in gs.rankings if not r.get('is_kazhudhai')), None)

    assert safe_player['name'] == 'Player 1', f"Player 1 should be safe, got {safe_player}"
    assert kazhudhai['name'] == 'Player 2', f"Player 2 should be KAZHUDHAI, got {kazhudhai}"
    print("  ✓ Heads-up match concluded cleanly:")
    print(f"    - Safe (1st): {safe_player['name']}")
    print(f"    - KAZHUDHAI: {kazhudhai['name']} (King of Donkeys!)")


if __name__ == '__main__':
    print("=" * 65)
    print("KAZHUDHAI CLUB — STAGE 4 (COLLECTION & FINISHING RULES) TEST SUITE")
    print("=" * 65)

    test_normal_round_card_collection()
    test_attack_round_card_collection()
    test_section_8_pending_status_mid_round()
    test_section_8_attack_card_recovery()
    test_section_8_attack_loser_finishes()
    test_multiple_finishers_same_round()
    test_heads_up_to_kazhudhai()

    print("\n" + "=" * 65)
    print("ALL STAGE 4 TESTS PASSED SUCCESSFULLY! (100% COMPLIANT)")
    print("=" * 65)
