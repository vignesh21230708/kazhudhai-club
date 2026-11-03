"""
KAZHUDHAI CLUB — tests/test_stage3.py
Comprehensive test suite for STAGE 3 (Normal Rounds & Attack Rounds):

Rules Verified:
  1. Starting suit determination (first card sets starting suit).
  2. Suit-following requirement (must follow starting suit if holding it).
  3. Attack triggering (off-suit card when void in starting suit triggers attack).
  4. Immediate round termination on attack (remaining players do not play).
  5. Winner evaluation (only starting suit considered; highest rank wins).
  6. Duplicate highest card tie-breaking (earliest played card wins).
  7. Normal round collection (cards permanently removed into common pile).
  8. Attack round collection (all played cards transfer into winner's hand).
  9. Next-round starter assignment (round winner starts the next round).
  10. Section 8 Special Rule: Player playing their last card:
      - Case A: Normal finish -> 0 cards -> marked safe.
      - Case B: Attack won -> receives cards back -> continues playing.
  11. Multi-round game loop with AI opponents reaching complete finish.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game_engine.deck import build_deck, RANK_ORDER
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.game_state import GameState


def test_starting_suit_and_following():
    """Verify first card sets starting suit and subsequent players must follow."""
    print("Testing Starting Suit & Suit Following Requirement...")
    p1 = Player('p1', 'Player 1')
    p2 = Player('p2', 'Player 2')
    p3 = Player('p3', 'Player 3')

    # p1 leads with Spades
    p1.hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]
    # p2 has both Spades and Hearts
    p2.hand = [
        {'id': 'c2', 'rank': '9', 'suit': 'S'},
        {'id': 'c3', 'rank': 'K', 'suit': 'H'}
    ]
    # p3 has only Hearts
    p3.hand = [{'id': 'c4', 'rank': 'A', 'suit': 'H'}]

    rnd = RoundEngine([p1, p2, p3], 0)
    assert rnd.starting_suit is None

    # p1 plays 5♠ -> sets starting suit to S
    res1 = rnd.play_card(p1, p1.hand[0])
    assert rnd.starting_suit == 'S'
    assert rnd.legal_suit == 'S'
    assert not res1['is_attack']
    print("  ✓ First card 5♠ correctly set starting suit to 'S'")

    # p2 tries to play K♥ while holding 9♠ -> MUST FAIL
    can_play_heart, reason = rnd.can_play(p2, p2.hand[1])
    assert not can_play_heart, "Playing off-suit while holding starting suit must be blocked!"
    print(f"  ✓ Off-suit play blocked correctly: '{reason}'")

    # p2 plays 9♠ -> valid
    can_play_spade, _ = rnd.can_play(p2, p2.hand[0])
    assert can_play_spade
    res2 = rnd.play_card(p2, p2.hand[0])
    assert not res2['is_attack']
    print("  ✓ Player 2 followed starting suit with 9♠")


def test_normal_round_resolution():
    """
    Test Rule 6.A: Normal round with no attack.
    Example from spec:
      Player 1: ♠5
      Player 2: ♠4
      Player 3: ♠7
      Player 4: ♠6
      Result:
      - No attack.
      - Player 3 wins with ♠7.
      - All four cards go into the common collected section.
      - Player 3 starts the next round.
    """
    print("\nTesting Normal Round (Specification Example)...")
    p1 = Player('p1', 'Player 1')
    p2 = Player('p2', 'Player 2')
    p3 = Player('p3', 'Player 3')
    p4 = Player('p4', 'Player 4')

    p1.hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]
    p2.hand = [{'id': 'c2', 'rank': '4', 'suit': 'S'}]
    p3.hand = [{'id': 'c3', 'rank': '7', 'suit': 'S'}]
    p4.hand = [{'id': 'c4', 'rank': '6', 'suit': 'S'}]

    rnd = RoundEngine([p1, p2, p3, p4], 0)
    rnd.play_card(p1, p1.hand[0])
    rnd.play_card(p2, p2.hand[0])
    rnd.play_card(p3, p3.hand[0])
    rnd.play_card(p4, p4.hand[0])

    assert rnd.is_complete, "Round must be complete after all 4 players played"
    assert not rnd.is_attack, "Round must NOT be an attack"

    res = rnd.resolve()
    assert res['winner'].name == 'Player 3', f"Expected Player 3 to win, got {res['winner'].name}"
    assert res['winning_card']['rank'] == '7' and res['winning_card']['suit'] == 'S'
    assert res['collection_type'] == 'common', "Normal round cards must go to common collection"
    assert len(res['cards_collected']) == 4
    print("  ✓ Normal round: Player 3 won with ♠7")
    print("  ✓ All 4 cards routed to 'common' collection")


def test_attack_round_resolution():
    """
    Test Rule 6.B: Attack round.
    Example from spec:
      Player 1: ♠5
      Player 2: ♠8
      Player 3: ♠4
      Player 4: ♥K
      Result:
      - Player 4 has no Spades and causes an attack.
      - The round ends immediately.
      - Player 2 wins with ♠8.
      - All four cards go to Player 2's hand.
      - Player 2 starts the next round.
    """
    print("\nTesting Attack Round (Specification Example)...")
    p1 = Player('p1', 'Player 1')
    p2 = Player('p2', 'Player 2')
    p3 = Player('p3', 'Player 3')
    p4 = Player('p4', 'Player 4')
    p5 = Player('p5', 'Player 5')  # To verify p5 does NOT play after attack!

    p1.hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}]
    p2.hand = [{'id': 'c2', 'rank': '8', 'suit': 'S'}]
    p3.hand = [{'id': 'c3', 'rank': '4', 'suit': 'S'}]
    p4.hand = [{'id': 'c4', 'rank': 'K', 'suit': 'H'}]  # Off-suit attack!
    p5.hand = [{'id': 'c5', 'rank': 'A', 'suit': 'S'}]

    rnd = RoundEngine([p1, p2, p3, p4, p5], 0)
    rnd.play_card(p1, p1.hand[0])
    rnd.play_card(p2, p2.hand[0])
    rnd.play_card(p3, p3.hand[0])
    play4 = rnd.play_card(p4, p4.hand[0])  # Attack!

    assert play4['is_attack'], "Player 4 move must be flagged as attack"
    assert rnd.is_attack, "Round must be flagged as attack"
    assert rnd.is_complete, "Round must terminate IMMEDIATELY on attack!"
    assert len(rnd.played_cards) == 4, "Player 5 must NOT have played!"

    res = rnd.resolve()
    assert res['winner'].name == 'Player 2', f"Expected Player 2 to win with ♠8, got {res['winner'].name}"
    assert res['winning_card']['rank'] == '8' and res['winning_card']['suit'] == 'S'
    assert res['collection_type'] == 'winner_hand', "Attack cards must route to winner hand"
    assert len(res['cards_collected']) == 4
    assert res['attacker'].name == 'Player 4'
    print("  ✓ Attack detected: Player 4 played ♥K (off-suit)")
    print("  ✓ Round ended immediately; Player 5 skipped")
    print("  ✓ Player 2 won with ♠8 (highest starting suit)")
    print("  ✓ All 4 cards routed to Player 2's hand")


def test_duplicate_highest_cards_tie():
    """
    Test Rule 6.B.10 & Section 7:
    Duplicate highest cards:
      Player 1: ♠4
      Player 2: ♠3
      Player 3: ♠6  (played first)
      Player 4: ♠5
      Player 5: ♠6  (played second)
      Result:
      - Player 3 and Player 5 have identical highest cards.
      - Player 3 wins because they played the card first.
      - All cards go into the common collected section.
      - Player 3 starts the next round.
    """
    print("\nTesting Duplicate Highest Cards Tie-Breaker...")
    p1 = Player('p1', 'Player 1')
    p2 = Player('p2', 'Player 2')
    p3 = Player('p3', 'Player 3')
    p4 = Player('p4', 'Player 4')
    p5 = Player('p5', 'Player 5')

    p1.hand = [{'id': 'c1', 'rank': '4', 'suit': 'S'}]
    p2.hand = [{'id': 'c2', 'rank': '3', 'suit': 'S'}]
    p3.hand = [{'id': 'c3', 'rank': '6', 'suit': 'S'}]  # First 6
    p4.hand = [{'id': 'c4', 'rank': '5', 'suit': 'S'}]
    p5.hand = [{'id': 'c5', 'rank': '6', 'suit': 'S'}]  # Second 6

    rnd = RoundEngine([p1, p2, p3, p4, p5], 0)
    for p in [p1, p2, p3, p4, p5]:
        rnd.play_card(p, p.hand[0])

    res = rnd.resolve()
    assert res['winner'].name == 'Player 3', (
        f"Tie break failed: expected Player 3 (earliest), got {res['winner'].name}"
    )
    print("  ✓ Duplicate highest cards: Player 3 won because they played ♠6 earlier than Player 5")


def test_last_card_pending_rule_case_a():
    """
    Section 8 Case A:
      Player plays last card.
      Round ends normally.
      Cards go to common collected section.
      Player has 0 cards after collection -> officially finishes & safe!
    """
    print("\nTesting Section 8: Last Card Pending — Case A (Normal finish)...")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
        {'id': 'p4', 'name': 'Player 4'},
    ]
    gs = GameState('test-case-a', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Give players specific cards
    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}, {'id': 'extra1', 'rank': '2', 'suit': 'D'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '4', 'suit': 'S'}, {'id': 'extra2', 'rank': '3', 'suit': 'D'}]
    # Player 3 has ONLY ONE card (their last card)
    gs.players[2].hand = [{'id': 'c3', 'rank': '7', 'suit': 'S'}]
    gs.players[3].hand = [{'id': 'c4', 'rank': '6', 'suit': 'S'}, {'id': 'extra3', 'rank': '4', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    # Play round: p1, p2, p3 (plays last card), p4
    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')

    # Verify Player 3 is NOT immediately marked safe after playing last card
    res_p3 = gs.play_card('p3', 'c3')
    p3 = gs.players[2]
    assert len(p3.hand) == 0
    # Must remain pending during the round!
    assert p3.is_safe is False, "Player 3 MUST NOT be eliminated mid-round!"
    print("  ✓ Player 3 played their last card — status remains pending while round is in progress")

    # Player 4 plays and completes normal round
    gs.play_card('p4', 'c4')

    # Round ended normally, cards went to common pile, collection finished.
    # NOW Player 3 should be officially safe!
    assert p3.is_safe is True, "Player 3 must be marked safe AFTER round collection"
    assert len(gs.common_pile) == 4, "Cards must be in common pile"
    assert p3.name in [r['name'] for r in gs.rankings]
    print("  ✓ Round finished normally -> cards collected to common pile -> Player 3 officially safe!")


def test_last_card_pending_rule_case_b():
    """
    Section 8 Case B:
      Player 3 plays last card (7♠).
      Player 4 has no spades and plays K♥ -> ATTACK!
      Player 3 had the highest starting suit card (7♠) and wins the round!
      All played cards go to Player 3's hand.
      Player 3 is NO LONGER OUT and continues playing!
    """
    print("\nTesting Section 8: Last Card Pending — Case B (Attack won, back in game)...")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
        {'id': 'p4', 'name': 'Player 4'},
    ]
    gs = GameState('test-case-b', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    gs.players[0].hand = [{'id': 'c1', 'rank': '5', 'suit': 'S'}, {'id': 'extra1', 'rank': '2', 'suit': 'D'}]
    gs.players[1].hand = [{'id': 'c2', 'rank': '4', 'suit': 'S'}, {'id': 'extra2', 'rank': '3', 'suit': 'D'}]
    # Player 3 has only ONE card (their last card)
    gs.players[2].hand = [{'id': 'c3', 'rank': '7', 'suit': 'S'}]
    # Player 4 has NO spades, has Heart K
    gs.players[3].hand = [{'id': 'c4', 'rank': 'K', 'suit': 'H'}, {'id': 'extra3', 'rank': '4', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'c1')
    gs.play_card('p2', 'c2')
    gs.play_card('p3', 'c3')  # p3 hand becomes 0

    p3 = gs.players[2]
    assert not p3.is_safe, "Player 3 must not be eliminated mid-round!"

    # Player 4 attacks!
    res_p4 = gs.play_card('p4', 'c4')
    assert res_p4['round_completed']
    assert res_p4['last_round_result']['is_attack']

    # Player 3 won with 7♠ and received all 4 played cards!
    assert p3.is_safe is False, "Player 3 received cards from attack and MUST NOT be safe!"
    assert p3.card_count == 4, f"Player 3 must have 4 cards, got {p3.card_count}"
    assert p3.name not in [r['name'] for r in gs.rankings], "Player 3 must not be in safe rankings!"
    print("  ✓ Attack occurred: Player 3 won with 7♠ and received all 4 cards into hand")
    print("  ✓ Player 3 is NOT safe and continues playing with 4 cards!")


def test_next_round_starter_after_winner_finishes():
    """Verify that when a round winner finishes and becomes safe, the next active player starts."""
    print("\nTesting Next Round Starter when Winner Finishes...")
    configs = [
        {'id': 'p1', 'name': 'Player 1'},
        {'id': 'p2', 'name': 'Player 2'},
        {'id': 'p3', 'name': 'Player 3'},
    ]
    gs = GameState('test-winner-finish', configs)
    gs.status = GameState.STATUS_PLAYING
    gs.round_number = 1

    # Player 2 has 1 card (A♠) and will win and finish
    gs.players[0].hand = [{'id': 'a1', 'rank': '5', 'suit': 'S'}, {'id': 'a2', 'rank': '2', 'suit': 'D'}]
    gs.players[1].hand = [{'id': 'b1', 'rank': 'A', 'suit': 'S'}]  # Will win and finish!
    gs.players[2].hand = [{'id': 'c1', 'rank': '4', 'suit': 'S'}, {'id': 'c2', 'rank': '3', 'suit': 'D'}]

    gs.current_player_idx = 0
    gs._start_new_round()

    gs.play_card('p1', 'a1')
    gs.play_card('p2', 'b1')
    gs.play_card('p3', 'c1')

    # Player 2 won with A♠ and finished
    assert gs.players[1].is_safe, "Player 2 must be safe"

    # Next round should be started by Player 3 (next active in table order after Player 2)
    next_starter = gs.current_player
    assert next_starter.name == 'Player 3', (
        f"Expected Player 3 to start after Player 2 finished, got {next_starter.name}"
    )
    print("  ✓ Winner Player 2 finished; turn correctly passed to Player 3 for the next round")


def test_full_offline_gameplay_simulation():
    """Simulate a complete 3-player offline game to verify full game termination and KAZHUDHAI declaration."""
    print("\nTesting Full Offline Game Simulation to Completion...")
    configs = [
        {'id': 'human', 'name': 'Human', 'is_ai': True},  # Auto-play as AI for simulation
        {'id': 'bot1',  'name': 'Bot 1', 'is_ai': True},
        {'id': 'bot2',  'name': 'Bot 2', 'is_ai': True},
    ]
    gs = GameState('sim-game', configs, num_decks=1, difficulty='easy')
    gs.setup()

    max_turns = 300
    turns = 0
    while gs.status == GameState.STATUS_PLAYING and turns < max_turns:
        step = gs.step_ai_turn()
        turns += 1

    assert gs.status == GameState.STATUS_FINISHED, (
        f"Game did not finish within {max_turns} turns! Status: {gs.status}"
    )
    assert len(gs.rankings) == 3, f"Expected 3 players in rankings, got {len(gs.rankings)}"

    kazhudhai = [r for r in gs.rankings if r.get('is_kazhudhai')]
    assert len(kazhudhai) == 1, "Exactly ONE player must be KAZHUDHAI!"
    safe_players = [r for r in gs.rankings if not r.get('is_kazhudhai')]
    assert len(safe_players) == 2, "2 players must be safe!"

    print(f"  ✓ Game finished cleanly in {turns} turns!")
    print(f"  ✓ Safe: {[p['name'] for p in safe_players]}")
    print(f"  ✓ KAZHUDHAI: {kazhudhai[0]['name']}")


if __name__ == '__main__':
    print("=" * 65)
    print("KAZHUDHAI CLUB — STAGE 3 (NORMAL & ATTACK ROUNDS) TEST SUITE")
    print("=" * 65)

    test_starting_suit_and_following()
    test_normal_round_resolution()
    test_attack_round_resolution()
    test_duplicate_highest_cards_tie()
    test_last_card_pending_rule_case_a()
    test_last_card_pending_rule_case_b()
    test_next_round_starter_after_winner_finishes()
    test_full_offline_gameplay_simulation()

    print("\n" + "=" * 65)
    print("ALL STAGE 3 TESTS PASSED SUCCESSFULLY! (100% COMPLIANT)")
    print("=" * 65)
