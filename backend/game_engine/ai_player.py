"""
KAZHUDHAI CLUB — game_engine/ai_player.py
AI Opponent Strategies for Offline Mode.

Three Distinct AI Difficulties:
  - Easy:
      Plays randomly among legal cards. Attacks with random off-suit card.
  - Medium:
      Follows suit with the lowest legal card to conserve high cards.
      When attacking, discards highest rank card to shed high burdens.
      When leading, plays mid/low rank cards.
  - Hard:
      Intelligent trick-taking and shedding heuristics:
      - When following suit: Inspects cards currently in play.
        If last to play and can win the normal trick (dumping cards permanently),
        plays the minimum winning card. Otherwise plays lowest card to conserve rank.
      - When attacking: Identifies longest suit or highest rank (e.g. Aces/Kings)
        to dump maximum burden onto the trick winner.
      - When leading: Employs suit-voiding strategy (leads from shortest suit
        to become void and unlock attack capabilities on future rounds).
"""
from __future__ import annotations
import random
from collections import Counter
from game_engine.deck import RANK_ORDER


class AIPlayer:

    @staticmethod
    def choose_card(player, legal_suit: str | None, difficulty: str = 'medium',
                    current_round=None) -> dict | None:
        """
        Select a legal card for an AI player to play.

        :param player:        Player instance holding .hand
        :param legal_suit:    Suit that must be followed, or None if leading
        :param difficulty:    'easy', 'medium', or 'hard'
        :param current_round: RoundEngine instance (optional, for table context)
        :returns:             A legal card dict from player.hand, or None
        """
        if not player.hand:
            return None

        difficulty = (difficulty or 'medium').lower()

        # Leading the round (first card played)
        if legal_suit is None:
            return _choose_leading_card(player, difficulty)

        # Must follow suit if player holds any cards of legal_suit
        suit_cards = player.get_cards_of_suit(legal_suit)
        if suit_cards:
            return _choose_following_card(suit_cards, difficulty, current_round, legal_suit)

        # Void in starting suit -> MUST ATTACK with any card from hand
        return _choose_attack_card(player.hand, difficulty)

    @staticmethod
    def choose_starting_card(player, difficulty: str = 'medium') -> dict | None:
        """Convenience alias for leading a round."""
        return AIPlayer.choose_card(player, None, difficulty)


# ── Strategy Implementation ──

def _choose_leading_card(player, difficulty: str) -> dict:
    """Select which card to lead with at the start of a round."""
    hand = player.hand
    if not hand:
        return None

    if difficulty == 'easy':
        return random.choice(hand)

    if difficulty == 'medium':
        # Play lowest rank card to avoid losing a valuable card
        return min(hand, key=lambda c: RANK_ORDER[c['rank']])

    # Hard difficulty: Voiding strategy
    # Find the suit in hand with the fewest cards (short suit / singleton)
    # By leading with this card, the AI empties that suit and can attack later!
    suit_counts = Counter(c['suit'] for c in hand)
    shortest_suit = min(suit_counts, key=lambda s: suit_counts[s])
    short_suit_cards = [c for c in hand if c['suit'] == shortest_suit]

    # Lead with the lowest card of the shortest suit
    return min(short_suit_cards, key=lambda c: RANK_ORDER[c['rank']])


def _choose_following_card(suit_cards: list[dict], difficulty: str,
                           current_round, legal_suit: str) -> dict:
    """Select a card when player has one or more cards of the starting suit."""
    if difficulty == 'easy':
        return random.choice(suit_cards)

    if difficulty == 'medium':
        # Conserve high cards: play lowest legal card
        return min(suit_cards, key=lambda c: RANK_ORDER[c['rank']])

    # Hard difficulty: Tactical evaluation
    if current_round and current_round.played_cards:
        # Find current highest starting-suit card on the table
        table_suit_plays = [
            p['card'] for p in current_round.played_cards
            if p['card']['suit'] == legal_suit
        ]
        if table_suit_plays:
            table_highest_rank = max(RANK_ORDER[c['rank']] for c in table_suit_plays)

            # If AI is the LAST player in the round, and can win cleanly
            # (normal round = cards go permanently to common pile!),
            # play the lowest card that beats the table's highest!
            is_last_player = (len(current_round.played_cards) == len(current_round._play_order) - 1)
            if is_last_player and not current_round.is_attack:
                winning_cards = [c for c in suit_cards if RANK_ORDER[c['rank']] > table_highest_rank]
                if winning_cards:
                    # Pick lowest winning card to conserve higher cards
                    return min(winning_cards, key=lambda c: RANK_ORDER[c['rank']])

    # Default hard: Play lowest card to conserve power
    return min(suit_cards, key=lambda c: RANK_ORDER[c['rank']])


def _choose_attack_card(hand: list[dict], difficulty: str) -> dict:
    """Select a card to play when player has NO cards of the starting suit (ATTACK)."""
    if difficulty == 'easy':
        return random.choice(hand)

    if difficulty == 'medium':
        # Attack with highest rank card (discard heavy burdens)
        return max(hand, key=lambda c: RANK_ORDER[c['rank']])

    # Hard difficulty:
    # 1. Discard highest rank card from the suit with the MOST cards (reduce long suit)
    suit_counts = Counter(c['suit'] for c in hand)
    longest_suit = max(suit_counts, key=lambda s: suit_counts[s])
    long_suit_cards = [c for c in hand if c['suit'] == longest_suit]

    # Dump the highest card from the longest suit
    return max(long_suit_cards, key=lambda c: RANK_ORDER[c['rank']])
