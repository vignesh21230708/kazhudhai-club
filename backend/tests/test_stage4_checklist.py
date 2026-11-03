"""
KAZHUDHAI CLUB — tests/test_stage4_checklist.py
Verification of the exact Stage 4 Testing Checklist:

  Checklist 1: Player plays their last card (Status remains Pending mid-round)
  Checklist 2: Normal round finishing (0 cards after collection -> officially Finished/Safe)
  Checklist 3: Attack round finishing (Player wins attack, cards return to hand, NOT Finished)
  Checklist 4: Safe players leave active game (Removed from subsequent rounds, no more turns)
  Checklist 5: KAZHUDHAI determination (Only 1 player remains with cards -> KAZHUDHAI)
  Checklist 6: Multiple players finish (All marked Finished, game continues with remaining active)
  Checklist 7: Game results (Finished players, finishing order ranks, final KAZHUDHAI player)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.game_state import GameState


def test_checklist_1_last_card_pending():
    """
    Checklist 1:
      Give a player only one card.
      Let them play it.
      Check whether their status becomes Pending instead of immediately finishing.
    """
    print("\n--- Checklist 1: Player Plays Their Last Card (Pending Status) ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('chk-1', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Give Player 1 only ONE card (their last card)
    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Player 1 plays their last card
    res = gs.play_card('p1', 'c1')
    p1 = gs.players[0]

    # Verify hand is 0, but status is STILL PENDING (not finished/safe!)
    assert len(p1.hand) == 0, "Player 1 hand must be empty"
    assert p1.is_safe is False, "Player 1 MUST NOT be marked safe/finished immediately!"
    assert p1 in gs.active_players, "Player 1 must still be in active_players while round is in progress"
    assert not res['round_completed'], "Round is still in progress with other players pending"
    print("  [PASS] Player 1 played their last card.")
    print(f"         Hand count: {len(p1.hand)} cards")
    print(f"         is_safe: {p1.is_safe} (Status: PENDING)")
    print(f"         active_players: {[p.name for p in gs.active_players]}")


def test_checklist_2_normal_round_finishing():
    """
    Checklist 2:
      A player plays their last card.
      The round finishes normally.
      Their cards go to the common collected section.
      Check whether the player is officially marked as Finished.
    """
    print("\n--- Checklist 2: Normal Round Finishing ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('chk-2', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]  # Player 1's last card
    gs.players[1].hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]

    initial_common = len(gs.common_pile)
    gs.current_player_idx = 0
    gs._start_new_round()

    # Player 1 plays last card (pending)
    gs.play_card('p1', 'c1')
    p1 = gs.players[0]
    assert p1.is_safe is False

    # Player 2 and Player 3 follow suit (normal round)
    gs.play_card('p2', 'c2')
    res3 = gs.play_card('p3', 'c3')

    # Round ended normally
    assert res3['round_completed']
    assert not res3['last_round_result']['is_attack']
    assert len(gs.common_pile) == initial_common + 3, "All 3 cards must go to common collection"

    # Player 1 has 0 cards after collection -> officially marked as Finished/Safe!
    assert p1.is_safe is True, "Player 1 must be officially marked Finished/Safe after collection"
    assert p1.card_count == 0
    assert p1 not in gs.active_players, "Player 1 must leave active_players"
    assert p1.name in [r['name'] for r in gs.rankings]
    print("  [PASS] Round finished normally.")
    print(f"         Common pile: {len(gs.common_pile)} cards (increased by 3)")
    print(f"         Player 1 is_safe: {p1.is_safe} (Officially Finished & Safe)")
    print(f"         Remaining active players: {[p.name for p in gs.active_players]}")


def test_checklist_3_attack_round_finishing():
    """
    Checklist 3:
      A player plays their last card.
      Another player triggers an attack.
      The first player wins the round and collects all played cards.
      Check whether their cards return to their hand.
      They must NOT be marked as Finished if they now have cards.
    """
    print("\n--- Checklist 3: Attack Round Finishing (Cards Return to Hand) ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('chk-3', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Player 1 has Ace of Spades (their last card)
    gs.players[0].hand = [{'id': 'c1', 'rank': 'A', 'suit': 'S'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    # Player 3 has no Spades -> plays King of Hearts (attack!)
    gs.players[2].hand = [{'id': 'c3', 'rank': 'K', 'suit': 'H'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Player 1 plays A♠
    gs.play_card('p1', 'c1')
    p1 = gs.players[0]
    assert len(p1.hand) == 0

    # Player 2 follows with 5♠
    gs.play_card('p2', 'c2')

    # Player 3 attacks with K♥
    res3 = gs.play_card('p3', 'c3')

    assert res3['round_completed']
    assert res3['last_round_result']['is_attack']
    assert res3['last_round_result']['winner_id'] == 'p1'

    # All 3 played cards must return to Player 1's hand
    assert p1.card_count == 3, f"Player 1 must have 3 cards, got {p1.card_count}"
    assert p1.is_safe is False, "Player 1 MUST NOT be marked Finished/Safe because they now have cards!"
    assert p1 in gs.active_players, "Player 1 must remain an active player"
    assert p1.name not in [r['name'] for r in gs.rankings], "Player 1 must not be in safe rankings"
    print("  [PASS] Attack triggered by Player 3.")
    print("         Player 1 won attack with highest starting suit (A♠).")
    print(f"         Player 1 card count: {p1.card_count} cards returned to hand.")
    print(f"         Player 1 is_safe: {p1.is_safe} (NOT Finished, continues playing!)")


def test_checklist_4_safe_players_leave_active_game():
    """
    Checklist 4:
      Check whether officially finished players are removed from subsequent rounds.
      They must not receive another turn.
    """
    print("\n--- Checklist 4: Safe Players Leave Active Game ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('chk-4', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Player 1 has only 1 card (A♠), Player 2 and 3 have multiple cards
    gs.players[0].hand = [{'id': 'c1', 'rank': 'A', 'suit': 'S'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}, {'id': 'x3', 'rank': '3', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Round 1: Player 1 wins and finishes
    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')
    gs.play_card('p3', 'c3')

    p1 = gs.players[0]
    p2 = gs.players[1]
    p3 = gs.players[2]

    assert p1.is_safe is True, "Player 1 is officially finished"
    assert p1 not in gs.active_players, "Player 1 is removed from active players"

    # Now verify Round 2:
    print(f"         Round 2 started. Active players: {[p.name for p in gs.active_players]}")
    assert gs.round_number == 2
    assert len(gs.active_players) == 2, "Only Player 2 and Player 3 are active"

    # Check play order in Round 2
    round_play_order = [p.name for p in gs.current_round._play_order]
    print(f"         Round 2 play order: {round_play_order}")
    assert 'Player 1' not in round_play_order, "Player 1 must NOT receive a turn in Round 2!"
    assert round_play_order == ['Player 2', 'Player 3'] or round_play_order == ['Player 3', 'Player 2']

    # Verify Player 1 cannot be called to play
    can_p1_play, reason = gs.current_round.can_play(p1, {'id': 'dummy', 'rank': '2', 'suit': 'D'})
    assert not can_p1_play
    print("  [PASS] Safe Player 1 was completely removed from subsequent round.")
    print("         Player 1 did not receive a turn in Round 2.")


def test_checklist_5_kazhudhai_determination():
    """
    Checklist 5:
      Continue playing until only one player has cards.
      Check whether that player is declared KAZHUDHAI.
    """
    print("\n--- Checklist 5: KAZHUDHAI Determination ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
    ]
    gs = GameState('chk-5', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Player 1 has 1 card (wins and finishes), Player 2 has 2 cards
    gs.players[0].hand = [{'id': 'c1', 'rank': 'K', 'suit': 'S'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '5', 'suit': 'S'}, {'id': 'x2', 'rank': '2', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')

    # Player 1 finished, only Player 2 has cards
    assert gs.status == GameState.STATUS_FINISHED, "Game must finish when only 1 player holds cards"

    kazhudhai_entry = next((r for r in gs.rankings if r.get('is_kazhudhai')), None)
    safe_entry = next((r for r in gs.rankings if not r.get('is_kazhudhai')), None)

    assert kazhudhai_entry is not None, "KAZHUDHAI must be declared!"
    assert kazhudhai_entry['name'] == 'Player 2', f"Player 2 should be KAZHUDHAI, got {kazhudhai_entry['name']}"
    assert safe_entry['name'] == 'Player 1', f"Player 1 should be safe, got {safe_entry['name']}"
    print(f"  [PASS] Game finished.")
    print(f"         Safe Player: {safe_entry['name']}")
    print(f"         KAZHUDHAI: {kazhudhai_entry['name']} (Successfully Identified!)")


def test_checklist_6_multiple_players_finish():
    """
    Checklist 6:
      Let two or more players finish during the game.
      Check whether all are correctly marked as Finished.
      Ensure the game continues with the remaining active players.
    """
    print("\n--- Checklist 6: Multiple Players Finish ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
        {'id': 'p4', 'name': 'Player 4'},
    ]
    gs = GameState('chk-6', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Player 1 has 1 card, Player 2 has 1 card
    # Player 3 has 3 cards, Player 4 has 3 cards
    gs.players[0].hand = [{'id': 'c1', 'rank': 'A', 'suit': 'S'}]  # P1 last card
    gs.players[1].hand = [{'id': 'c2', 'rank': 'K', 'suit': 'S'}]  # P2 last card
    gs.players[2].hand = [{'id': 'c3', 'rank': '5', 'suit': 'S'}, {'id': 'x3', 'rank': '2', 'suit': 'D'}, {'id': 'y3', 'rank': '3', 'suit': 'D'}]
    gs.players[3].hand = [{'id': 'c4', 'rank': '4', 'suit': 'S'}, {'id': 'x4', 'rank': '4', 'suit': 'D'}, {'id': 'y4', 'rank': '5', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Play Round 1: All 4 follow suit
    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')
    gs.play_card('p3', 'c3')
    res = gs.play_card('p4', 'c4')

    assert res['round_completed']

    # Both Player 1 and Player 2 had 0 cards after collection -> BOTH marked Finished!
    p1 = gs.players[0]
    p2 = gs.players[1]
    assert p1.is_safe is True, "Player 1 must be marked Finished"
    assert p2.is_safe is True, "Player 2 must be marked Finished"

    # Game MUST NOT be finished because Player 3 and Player 4 are still active!
    assert gs.status == GameState.STATUS_PLAYING, "Game must continue with remaining active players"
    active_names = [p.name for p in gs.active_players]
    assert active_names == ['Player 3', 'Player 4'], f"Expected [P3, P4] active, got {active_names}"
    print("  [PASS] Both Player 1 and Player 2 finished in the same round.")
    print(f"         Player 1 is_safe: {p1.is_safe}, Player 2 is_safe: {p2.is_safe}")
    print(f"         Game status: {gs.status} (CONTINUING)")
    print(f"         Remaining active players: {active_names}")


def test_checklist_7_game_results_display():
    """
    Checklist 7:
      Check whether the results screen / state correctly displays:
      - Finished players.
      - Their finishing order (ranks 1, 2, ...).
      - Final KAZHUDHAI player.
    """
    print("\n--- Checklist 7: Game Results Screen & Rankings ---")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('chk-7', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Round 1: Player 1 finishes first (Rank 1)
    gs.players[0].hand = [{'id': 'a1', 'rank': 'A', 'suit': 'S'}]
    gs.players[1].hand = [{'id': 'b1', 'rank': 'K', 'suit': 'S'}, {'id': 'b2', 'rank': '2', 'suit': 'D'}]
    gs.players[2].hand = [{'id': 'c1', 'rank': 'Q', 'suit': 'S'}, {'id': 'c2', 'rank': '3', 'suit': 'D'}, {'id': 'c3', 'rank': '4', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()
    gs.play_card('p1', 'a1')
    gs.play_card('p2', 'b1')
    gs.play_card('p3', 'c1')
    assert gs.players[0].is_safe

    # Round 2: Player 2 finishes second (Rank 2)
    # Remaining active: Player 2 and Player 3
    gs.play_card('p2', 'b2')
    gs.play_card('p3', 'c2')
    assert gs.players[1].is_safe

    # Game is now finished! Only Player 3 has cards (Rank 3: KAZHUDHAI)
    assert gs.status == GameState.STATUS_FINISHED

    # Build client state
    state = gs._build_state(requesting_player_id='p1')

    # Verify state payload for results screen
    assert state['status'] == 'finished'
    assert state['kazhudhai_name'] == 'Player 3'
    assert len(state['rankings']) == 3

    ranks = state['rankings']
    print(f"         Rankings Output:")
    for r in ranks:
        tag = '👑 KAZHUDHAI' if r.get('is_kazhudhai') else '✅ SAFE'
        print(f"           Rank {r['rank']}: {r['name']} — {tag}")

    assert ranks[0]['name'] == 'Player 1' and not ranks[0]['is_kazhudhai'] and ranks[0]['rank'] == 1
    assert ranks[1]['name'] == 'Player 2' and not ranks[1]['is_kazhudhai'] and ranks[1]['rank'] == 2
    assert ranks[2]['name'] == 'Player 3' and ranks[2]['is_kazhudhai'] and ranks[2]['rank'] == 3

    print("  [PASS] Results state correctly contains:")
    print("         1. All finished players.")
    print("         2. Sequential finishing order (Rank 1, Rank 2).")
    print("         3. Final KAZHUDHAI player accurately identified (Player 3).")


if __name__ == '__main__':
    print("=" * 70)
    print("KAZHUDHAI CLUB — STAGE 4 TESTING CHECKLIST SUITE (7/7 CHECKS)")
    print("=" * 70)

    test_checklist_1_last_card_pending()
    test_checklist_2_normal_round_finishing()
    test_checklist_3_attack_round_finishing()
    test_checklist_4_safe_players_leave_active_game()
    test_checklist_5_kazhudhai_determination()
    test_checklist_6_multiple_players_finish()
    test_checklist_7_game_results_display()

    print("\n" + "=" * 70)
    print("ALL 7 STAGE 4 CHECKLIST TESTS PASSED SUCCESSFULLY! (100% VERIFIED)")
    print("=" * 70)
