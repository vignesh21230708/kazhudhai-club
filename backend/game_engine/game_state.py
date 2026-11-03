"""
KAZHUDHAI CLUB — game_engine/game_state.py
Complete game state machine orchestrating rounds, attacks, card collections,
player finishes, and KAZHUDHAI identification.

Security: Never exposes other players' hands in state returned to client.
"""
from __future__ import annotations
import uuid
from game_engine.deck import build_deck, find_ace_of_spades, sort_hand
from game_engine.distributor import distribute
from game_engine.player import Player
from game_engine.round_engine import RoundEngine
from game_engine.ai_player import AIPlayer


class GameState:

    STATUS_WAITING   = 'waiting'
    STATUS_PLAYING   = 'playing'
    STATUS_FINISHED  = 'finished'

    def __init__(self, game_id: str, player_configs: list[dict],
                 num_decks: int = 1, difficulty: str = 'medium'):
        """
        :param game_id:        Unique game identifier
        :param player_configs: List of {'id': str, 'name': str, 'is_ai': bool}
        :param num_decks:      Number of card decks (1–5)
        :param difficulty:     AI difficulty ('easy', 'medium', 'hard')
        """
        self.game_id     = game_id
        self.num_decks   = num_decks
        self.difficulty  = difficulty
        self.status      = self.STATUS_WAITING

        # Players in table order (Player 1 is at index 0)
        self.players: list[Player] = [
            Player(id=pc['id'], name=pc['name'], is_ai=pc.get('is_ai', False))
            for pc in player_configs
        ]

        self.common_pile: list[dict] = []  # Permanently removed cards
        self.round_number: int = 0
        self.current_round: RoundEngine | None = None
        self.current_player_idx: int = 0  # Index into self.active_players
        self.rankings: list[dict] = []    # Finished players in rank order
        self.last_round_result: dict | None = None  # Info on most recently resolved round
        self.last_action: dict | None = None        # Info on most recent card play

    # ── Read-only properties ──

    @property
    def active_players(self) -> list[Player]:
        """Players who are still in the game (not yet safe)."""
        return [p for p in self.players if p.is_active]

    @property
    def current_player(self) -> Player | None:
        if self.current_round and not self.current_round.is_complete:
            return self.current_round.current_player
        ap = self.active_players
        if not ap:
            return None
        return ap[self.current_player_idx % len(ap)]

    # ── Game Setup ──

    def setup(self):
        """Build deck, shuffle thoroughly, distribute cards, and find A♠ starter for Round 1."""
        cards = build_deck(self.num_decks, shuffle=True)
        hands = distribute(cards, len(self.players), sort_hands=False)

        for i, player in enumerate(self.players):
            player.hand = hands[i]

        # Rule 5: The player holding A♠ starts the first round
        starter_found = False
        for i, player in enumerate(self.players):
            if find_ace_of_spades(player.hand):
                self.current_player_idx = i
                starter_found = True
                break

        if not starter_found:
            self.current_player_idx = 0

        # After card distribution is complete, automatically arrange each player's hand:
        # Group by suit (♠, ♥, ♦, ♣) and within each suit in descending rank order (A down to 2)
        for player in self.players:
            player.hand = sort_hand(player.hand)

        self.status = self.STATUS_PLAYING
        self.round_number = 1
        self.last_round_result = None
        self.last_action = None
        self._start_new_round()

    def restart(self):
        """
        Restart the match (rematch):
        Clears all player hands, resets statuses, builds a brand-new complete deck,
        freshly and randomly shuffles it using the secure random generator, and distributes
        cards to all players for a new match.
        """
        for p in self.players:
            p.hand = []
            p.is_safe = False
            p.safe_rank = None
            p.round_eliminated = None
            p.is_kazhudhai = False
        self.rankings = []
        self.eliminated_order = []
        self.common_collected = []
        self.current_round = None
        self.setup()

    def _start_new_round(self):
        ap = self.active_players
        if len(ap) <= 1:
            self._end_game()
            return

        self.current_round = RoundEngine(ap, self.current_player_idx % len(ap))

    # ── Card Play ──

    def play_card(self, player_id: str, card_id: str) -> dict:
        """
        Process a player's card play.
        Returns a dict with play action details and updated player state.
        Raises ValueError for illegal moves.
        """
        if self.status != self.STATUS_PLAYING:
            raise ValueError("Game is not in progress")

        player = self._get_player(player_id)
        if player is None:
            raise ValueError("Player not found")

        # Turn validation first: prevent stale or duplicate actions when not player's turn
        if self.current_player is None or self.current_player.id != player.id:
            raise ValueError("It is not this player's turn")

        card = self._get_card_from_hand(player, card_id)
        if card is None:
            raise ValueError("Card not in player's hand")

        if self.current_round is None:
            raise ValueError("No active round")

        # Execute play in RoundEngine
        play_res = self.current_round.play_card(player, card)

        self.last_action = {
            'player_id':    player.id,
            'player_name':  player.name,
            'card':         card,
            'is_attack':    play_res['is_attack'],
            'round_complete': play_res['is_complete'],
        }

        # If round finished, resolve it
        round_resolved_data = None
        if self.current_round.is_complete:
            round_resolved_data = self._resolve_round()

        return {
            'action':            self.last_action,
            'round_completed':   play_res['is_complete'],
            'last_round_result': round_resolved_data,
            'state':             self._build_state(requesting_player_id=player_id),
        }

    def _resolve_round(self) -> dict:
        """
        Resolve the completed round according to Section 6 and Section 8:
          1. Determine winner based on starting suit.
          2. Normal round: all cards permanently removed into common collected pile.
          3. Attack round: all cards go into winner's hand.
          4. Check player eliminations strictly AFTER collection.
          5. If winner finished, next active player in table rotation starts.
          6. If only 1 player remains, declare KAZHUDHAI.
        """
        resolution = self.current_round.resolve()
        winner: Player = resolution['winner']
        cards_collected = resolution['cards_collected']
        is_attack = resolution['is_attack']

        if resolution['collection_type'] == 'common':
            # Normal round: permanently removed into common collected pile
            for c in cards_collected:
                cid = str(c.get('id')) if isinstance(c, dict) and 'id' in c else None
                if not cid or not any(str(x.get('id')) == cid for x in self.common_pile if isinstance(x, dict)):
                    self.common_pile.append(c)
        else:
            # Attack round: all cards transfer to winner's hand in order
            winner.add_cards(cards_collected)
            # When a player collects cards after an attack round, arrange their updated hand again
            winner.hand = sort_hand(winner.hand)

        # ── Section 8: Only check player elimination AFTER collection ──
        newly_safe = self._check_eliminations(round_winner=winner)

        # Capture completed round result before starting next
        completed_played_cards = [
            {
                'player_id':   p['player'].id,
                'player_name': p['player'].name,
                'card':        p['card'],
                'is_attack':   p['is_attack'],
            }
            for p in self.current_round.played_cards
        ]

        result_summary = {
            'round_number':        self.round_number,
            'starting_suit':       self.current_round.starting_suit,
            'is_attack':           is_attack,
            'attacker_id':         resolution['attacker'].id if resolution['attacker'] else None,
            'attacker_name':       resolution['attacker'].name if resolution['attacker'] else None,
            'winner_id':           winner.id,
            'winner_name':         winner.name,
            'winning_card':        resolution['winning_card'],
            'collection_type':     resolution['collection_type'],
            'cards_collected':     cards_collected,
            'cards_count':         len(cards_collected),
            'played_cards':        completed_played_cards,
            'eliminated_players':  [p.name for p in newly_safe],
        }
        self.last_round_result = result_summary

        ap = self.active_players
        if len(ap) <= 1:
            self._end_game()
            result_summary['game_finished'] = True
            return result_summary

        result_summary['game_finished'] = False

        # Determine starter for the next round
        next_starter_idx = self._get_next_starter_after(winner)
        self.current_player_idx = next_starter_idx
        self.round_number += 1
        self._start_new_round()

        return result_summary

    def _get_next_starter_after(self, winner: Player) -> int:
        """
        If the round winner is still active, they start the next round.
        If the winner officially finished and is safe, the next active player
        in circular table order starts the next round.
        """
        ap = self.active_players
        if not ap:
            return 0

        # If winner is still active, they start next round
        if not winner.is_safe and winner in ap:
            return self._find_active_index(winner)

        # Winner is safe. Find their table position in self.players
        try:
            win_table_idx = self.players.index(winner)
        except ValueError:
            return 0

        n = len(self.players)
        for step in range(1, n):
            candidate = self.players[(win_table_idx + step) % n]
            if candidate.is_active:
                return self._find_active_index(candidate)

        return 0

    def _check_eliminations(self, round_winner: Player | None = None) -> list[Player]:
        """
        Recalculates every player's hand count and marks safe any player with 0 cards.
        Called STRICTLY after card collection is completed.
        If the round winner also reached 0 cards, they receive priority ranking.
        """
        newly_safe: list[Player] = []
        players_to_check: list[Player] = []

        if round_winner and not round_winner.is_safe and round_winner.card_count == 0:
            players_to_check.append(round_winner)

        for p in self.players:
            if p not in players_to_check and not p.is_safe and p.card_count == 0:
                players_to_check.append(p)

        for player in players_to_check:
            player.is_safe = True
            newly_safe.append(player)
            rank = len([p for p in self.players if p.is_safe])
            self.rankings.append({
                'player_id':    player.id,
                'name':         player.name,
                'rank':         rank,
                'is_kazhudhai': False,
            })
        return newly_safe

    def _end_game(self):
        """End the game and declare the last remaining player as KAZHUDHAI."""
        self.status = self.STATUS_FINISHED
        remaining = [p for p in self.players if not p.is_safe]
        for p in remaining:
            p.is_safe = True
            rank = len(self.rankings) + 1
            self.rankings.append({
                'player_id':    p.id,
                'name':         p.name,
                'rank':         rank,
                'is_kazhudhai': True,
            })

    # ── Turn Stepping (AI / Bot Execution) ──

    def step_ai_turn(self) -> dict:
        """
        Execute ONE AI player's turn if it is currently an AI's turn.
        Returns a dict with action details and updated state.
        """
        if self.status != self.STATUS_PLAYING:
            return {'action_type': 'game_finished', 'state': self._build_state(None)}

        player = self.current_player
        if player is None or not player.is_ai:
            return {'action_type': 'waiting_human', 'state': self._build_state(None)}

        legal_suit = self.current_round.legal_suit if self.current_round else None
        card = AIPlayer.choose_card(player, legal_suit, self.difficulty, current_round=self.current_round)

        if card is None:
            return {'action_type': 'no_card', 'state': self._build_state(None)}

        # Guard: Verify chosen card is actually present in the player's updated hand
        card_id = str(card.get('id')) if isinstance(card, dict) and 'id' in card else None
        if card_id and not player.has_card(card_id):
            if legal_suit and player.has_suit(legal_suit):
                valid_cards = player.get_cards_of_suit(legal_suit)
            else:
                valid_cards = player.hand
            if valid_cards:
                card = valid_cards[0]
            else:
                return {'action_type': 'no_card', 'state': self._build_state(None)}

        play_res = self.current_round.play_card(player, card)

        self.last_action = {
            'player_id':    player.id,
            'player_name':  player.name,
            'card':         card,
            'is_attack':    play_res['is_attack'],
            'round_complete': play_res['is_complete'],
        }

        round_resolved_data = None
        if self.current_round.is_complete:
            round_resolved_data = self._resolve_round()

        return {
            'action_type':       'ai_play',
            'action':            self.last_action,
            'round_completed':   play_res['is_complete'],
            'last_round_result': round_resolved_data,
            'state':             self._build_state(None),
        }

    # ── State Serialisation ──

    def _build_state(self, requesting_player_id: str | None) -> dict:
        """
        Build public game state dict.
        Only the requesting player's hand is attached.
        Opponent hands are NEVER included.
        """
        ap = self.active_players
        cp = self.current_player

        played_cards = []
        if self.current_round:
            for entry in self.current_round.played_cards:
                played_cards.append({
                    'player_id':   entry['player'].id,
                    'player_name': entry['player'].name,
                    'card':        entry['card'],
                    'is_attack':   entry['is_attack'],
                })

        players_data = []
        for p in self.players:
            pd = p.to_public_dict()
            pd['is_active'] = bool(cp is not None and cp.id == p.id)
            pd['isActive']  = pd['is_active']
            players_data.append(pd)

        state = {
            'game_id':           self.game_id,
            'status':            self.status,
            'round_number':      self.round_number,
            'current_player_id': cp.id if cp else None,
            'starting_suit':     self.current_round.starting_suit if self.current_round else None,
            'is_attack':         self.current_round.is_attack if self.current_round else False,
            'attacker_name':     self.current_round.attacker_player.name if (
                self.current_round and self.current_round.attacker_player) else None,
            'played_cards':      played_cards,
            'common_pile_count': len(self.common_pile),
            'players':           players_data,
            'rankings':          self.rankings,
            'deck_count':        self.num_decks,
            'last_round_result': self.last_round_result,
            'last_action':       self.last_action,
        }

        # Attach requesting player's hand (arranged by suit and descending rank)
        if requesting_player_id:
            req_player = self._get_player(requesting_player_id)
            if req_player:
                state['my_hand'] = sort_hand(req_player.hand)
                state['is_my_turn'] = (cp is not None and cp.id == requesting_player_id)
                state['legal_suit'] = (
                    self.current_round.legal_suit
                    if self.current_round and state['is_my_turn']
                    else None
                )

        if self.status == self.STATUS_FINISHED:
            kazhudhai = next((r for r in self.rankings if r.get('is_kazhudhai')), None)
            state['kazhudhai_name'] = kazhudhai['name'] if kazhudhai else '?'

        return state

    def get_state_for_player(self, player_id: str) -> dict:
        """Get state for a specific player (including their own hand)."""
        return self._build_state(requesting_player_id=player_id)

    # ── Helpers ──

    def _get_player(self, player_id: str) -> Player | None:
        return next((p for p in self.players if p.id == player_id), None)

    def _get_card_from_hand(self, player: Player, card_id: str) -> dict | None:
        target_id = str(card_id)
        return next((c for c in player.hand if isinstance(c, dict) and str(c.get('id')) == target_id), None)

    def _find_active_index(self, player: Player) -> int:
        ap = self.active_players
        for i, p in enumerate(ap):
            if p.id == player.id:
                return i
        return 0
