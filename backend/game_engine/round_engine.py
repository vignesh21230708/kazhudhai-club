"""
KAZHUDHAI CLUB — game_engine/round_engine.py
Implements normal and attack round logic.

This is a PURE Python module with no Flask dependency.
It can be unit-tested independently.
"""
from __future__ import annotations
from game_engine.deck import RANK_ORDER


class RoundEngine:
    """
    Manages a single round of KAZHUDHAI.

    A round consists of:
      - A sequence of played cards (one per active player until round ends)
      - Detection of ATTACK (when a player plays off-suit)
      - Determination of the winner
      - Collection of cards
    """

    def __init__(self, active_players: list, starting_player_index: int):
        """
        :param active_players: Ordered list of Player objects currently in game.
        :param starting_player_index: Index into active_players who plays first.
        """
        self.active_players    = active_players
        self.start_idx         = starting_player_index
        self.played_cards: list[dict] = []  # [{player, card, is_attack}]
        self.starting_suit: str | None = None
        self.is_attack: bool = False
        self.attacker_player = None
        self.is_complete: bool = False
        self._play_order: list = []
        self._next_idx: int = 0

        # Build play order starting from starting_player_index
        n = len(active_players)
        self._play_order = [
            active_players[(starting_player_index + i) % n]
            for i in range(n)
        ]
        self._next_idx = 0

    @property
    def current_player(self):
        """The player who should play next. None if round is complete."""
        if self.is_complete or self._next_idx >= len(self._play_order):
            return None
        return self._play_order[self._next_idx]

    @property
    def legal_suit(self) -> str | None:
        """
        The suit that the next player must follow (if they have it).
        None if the round hasn't started yet.
        """
        return self.starting_suit

    def can_play(self, player, card: dict) -> tuple[bool, str]:
        """
        Validate whether a player can play a given card.
        Returns (is_valid, reason_if_invalid).
        """
        if self.is_complete:
            return False, "Round is already complete"

        if player is not self.current_player:
            return False, "It is not this player's turn"

        # Validate that the player actually holds this card by physical ID
        card_id = card.get('id') if isinstance(card, dict) else None
        if card_id is not None:
            if not player.has_card(card_id):
                return False, "Player does not have this card"
        else:
            if card not in player.hand:
                return False, "Player does not have this card"

        # First card of round: any card is valid
        if self.starting_suit is None:
            return True, ""

        # Must follow starting suit if they have it
        if player.has_suit(self.starting_suit):
            if card['suit'] != self.starting_suit:
                return False, f"Must follow {self.starting_suit} suit"

        return True, ""

    def play_card(self, player, card: dict) -> dict:
        """
        Process a card play. Returns a result dict with round status.
        Raises ValueError if the play is invalid.
        """
        valid, reason = self.can_play(player, card)
        if not valid:
            raise ValueError(reason)

        # Remove card from player's hand immediately
        card_id = card.get('id') if isinstance(card, dict) else None
        removed = player.remove_card(card_id) if card_id is not None else None
        if removed is None:
            if card in player.hand:
                player.hand.remove(card)
                removed = card
            else:
                raise ValueError("Card not found in player's hand")

        is_attack = False

        # First card sets the starting suit
        if self.starting_suit is None:
            self.starting_suit = removed['suit']
        elif removed['suit'] != self.starting_suit:
            # ATTACK: player does not have starting suit
            is_attack = True
            self.is_attack = True
            self.attacker_player = player

        self.played_cards.append({
            'player':    player,
            'card':      removed,
            'is_attack': is_attack,
            'play_order': len(self.played_cards),  # 0-indexed order of play
        })

        self._next_idx += 1

        # If attack happened, round ends immediately
        if is_attack:
            self.is_complete = True

        # If all active players have played, round ends normally
        elif self._next_idx >= len(self._play_order):
            self.is_complete = True

        return {
            'is_attack':    is_attack,
            'is_complete':  self.is_complete,
            'played_card':  removed,
            'player_id':    player.id,
            'player_name':  player.name,
        }

    def resolve(self) -> dict:
        """
        Resolve the completed round.
        Returns a result dict with:
          - winner: Player who won
          - cards_collected: list of card dicts
          - collection_type: 'common' or 'winner_hand'
          - is_attack: bool

        Raises RuntimeError if round is not yet complete.
        """
        if not self.is_complete:
            raise RuntimeError("Cannot resolve: round is not complete")

        # Find highest starting-suit card
        starting_suit_plays = [
            p for p in self.played_cards
            if p['card']['suit'] == self.starting_suit
        ]

        # Sort by rank descending, then by play_order ascending (earliest wins tie)
        starting_suit_plays.sort(
            key=lambda p: (-RANK_ORDER[p['card']['rank']], p['play_order'])
        )

        winner_play = starting_suit_plays[0]
        winner      = winner_play['player']

        # Collect all played cards deduplicated by unique physical card ID
        seen_ids = set()
        all_cards = []
        for p in self.played_cards:
            c = p['card']
            cid = str(c.get('id')) if isinstance(c, dict) and 'id' in c else None
            if cid:
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_cards.append(c)
            else:
                all_cards.append(c)

        if self.is_attack:
            # All played cards go to winner's hand
            return {
                'winner':           winner,
                'cards_collected':  all_cards,
                'collection_type':  'winner_hand',
                'is_attack':        True,
                'attacker':         self.attacker_player,
                'winning_card':     winner_play['card'],
            }
        else:
            # All played cards go to common collected section (removed)
            return {
                'winner':           winner,
                'cards_collected':  all_cards,
                'collection_type':  'common',
                'is_attack':        False,
                'attacker':         None,
                'winning_card':     winner_play['card'],
            }
