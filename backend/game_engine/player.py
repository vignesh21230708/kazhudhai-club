"""
KAZHUDHAI CLUB — game_engine/player.py
Player model (human and AI).
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Player:
    id: str                         # Unique ID
    name: str                       # Display name
    is_ai: bool = False             # True for AI opponents
    hand: list[dict] = field(default_factory=list)   # Cards in hand
    is_safe: bool = False           # Has officially finished (0 cards after collection)
    attack_pile: list[dict] = field(default_factory=list)  # Won cards from attacks (added to hand)
    connection_status: str = 'connected'  # 'connected', 'reconnecting', 'disconnected', 'left'

    @property
    def card_count(self) -> int:
        return len(self.hand)

    @property
    def is_active(self) -> bool:
        """Player is still in the game (not yet safe)."""
        return not self.is_safe

    def has_suit(self, suit: str) -> bool:
        """Returns True if the player has at least one card of the given suit."""
        return any(c['suit'] == suit for c in self.hand)

    def get_cards_of_suit(self, suit: str) -> list[dict]:
        return [c for c in self.hand if c['suit'] == suit]

    def has_card(self, card_id: str) -> bool:
        """Check if the player legitimately holds a card with this physical ID."""
        if not card_id:
            return False
        target_id = str(card_id)
        return any(isinstance(c, dict) and str(c.get('id')) == target_id for c in self.hand)

    def count_card_id(self, card_id: str) -> int:
        """Return how many instances of a physical card ID exist in hand (must be 0 or 1)."""
        target_id = str(card_id)
        return sum(1 for c in self.hand if isinstance(c, dict) and str(c.get('id')) == target_id)

    def remove_card(self, card_id: str) -> dict | None:
        """
        Remove a physical card by ID from hand.
        Ensures strict removal and purges any accidental duplicate physical IDs.
        Returns the removed card dictionary or None.
        """
        if not card_id:
            return None
        target_id = str(card_id)
        removed = None
        for i, c in enumerate(self.hand):
            if isinstance(c, dict) and str(c.get('id')) == target_id:
                removed = self.hand.pop(i)
                break

        # Invariant: Prevent the same physical card ID from appearing twice
        if removed is not None:
            self.hand = [c for c in self.hand if not (isinstance(c, dict) and str(c.get('id')) == target_id)]

        return removed

    def add_cards(self, cards: list[dict]):
        """
        Add a list of cards to the player's hand.
        Enforces strict physical uniqueness: a card with an already existing ID
        is never added twice. Duplicate-looking cards from multiple decks with distinct
        IDs are preserved.
        """
        if not cards:
            return

        existing_ids = {str(c['id']) for c in self.hand if isinstance(c, dict) and 'id' in c}
        for card in cards:
            if isinstance(card, dict) and 'id' in card:
                cid = str(card['id'])
                if cid not in existing_ids:
                    self.hand.append(card)
                    existing_ids.add(cid)
            else:
                if card not in self.hand:
                    self.hand.append(card)

    def to_public_dict(self) -> dict:
        """Safe representation sent to ALL clients (no hidden card info)."""
        return {
            'id':                self.id,
            'name':              self.name,
            'is_ai':             self.is_ai,
            'isAI':              self.is_ai,
            'card_count':        self.card_count,
            'cardCount':         self.card_count,
            'is_safe':           self.is_safe,
            'isSafe':            self.is_safe,
            'is_active':         self.is_active,
            'isActive':          self.is_active,
            'connection_status': self.connection_status,
        }

    def to_private_dict(self) -> dict:
        """Full representation sent ONLY to this player's own client."""
        return {
            **self.to_public_dict(),
            'hand': self.hand,
        }
