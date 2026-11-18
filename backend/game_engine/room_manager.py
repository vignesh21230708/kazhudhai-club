"""
KAZHUDHAI CLUB — game_engine/room_manager.py
Authoritative room and multiplayer session manager.
Supports private rooms with 6-char codes, public lobbies, 2–10 players, 1–6 decks,
reconnection tokens, activity history logging, real-time connection status tracking,
and zero-leak state serialisation.
"""
from __future__ import annotations
import html
import random
import secrets
import string
import threading
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from game_engine.game_state import GameState

GRACE_PERIOD_SECONDS = 120.0
MAX_CHAT_MESSAGE_LENGTH = 200
MAX_LOBBY_CHAT_LENGTH = 150
VALID_CHAT_STAGES = ('pre_match', 'in_match', 'post_match')
STATUS_TO_CHAT_STAGE = {
    'waiting':  'pre_match',
    'playing':  'in_match',
    'finished': 'post_match',
}


@dataclass
class RoomSpectator:
    id: str
    name: str
    sid: str | None
    connected: bool = True
    joined_at: float = field(default_factory=time.time)

    def to_summary(self) -> dict:
        return {
            'id':        self.id,
            'name':      self.name,
            'connected': self.connected,
        }


@dataclass
class RoomPlayer:
    id: str
    name: str
    sid: str | None
    is_host: bool = False
    connected: bool = True
    status: str = 'connected'  # 'connected', 'reconnecting', 'disconnected', 'left'
    departure_reason: str | None = None
    reconnect_token: str = field(default_factory=lambda: secrets.token_hex(24))
    disconnected_at: float | None = None

    def to_summary(self) -> dict:
        return {
            'id':               self.id,
            'name':             self.name,
            'is_host':          self.is_host,
            'connected':        self.connected,
            'status':           self.status,
            'departure_reason': self.departure_reason,
        }


class Room:
    def __init__(self, code: str, is_private: bool, max_players: int = 4, deck_count: int = 1):
        self.code = code
        self.is_private = is_private
        self.max_players = max(2, min(10, max_players))
        self.deck_count = max(1, min(6, deck_count))
        self.status = 'waiting'  # 'waiting', 'playing', 'finished'
        self.match_id: str | None = None
        self.players: dict[str, RoomPlayer] = {}  # player_id -> RoomPlayer
        self.spectators: dict[str, RoomSpectator] = {}  # spectator_id -> RoomSpectator
        self.host_id: str | None = None
        self.game_state: GameState | None = None
        self.activity_log: list[dict] = []  # Chronological game activity entries
        self.chat_messages: list[dict] = []  # Pre-match lobby chat (aliased in chat_stages['pre_match'])
        self.chat_stages: dict[str, list[dict]] = {
            'pre_match':  self.chat_messages,
            'in_match':   [],
            'post_match': [],
        }
        self.play_lock = threading.Lock()    # Atomic lock for turn moves, ready state, play-again, and timers
        self.turn_sequence: int = 0          # Monotonically increasing counter per turn
        self.turn_timer: threading.Timer | None = None
        self.turn_deadline: float | None = None

        # Stage 2: Post-match Ready / Not Ready & Play Again state
        self.last_match_player_ids: list[str] = []
        self.last_match_deck_count: int = self.deck_count
        self.post_match_ready: dict[str, bool] = {}
        self.post_match_left_ids: set[str] = set()
        self.play_again_in_progress: bool = False

    def cancel_turn_timer(self):
        """Cancel any pending turn timeout timer."""
        if self.turn_timer:
            try:
                self.turn_timer.cancel()
            except Exception:
                pass
            self.turn_timer = None

    def start_turn_timer(self, timeout_callback, timeout_seconds: float = 30.0):
        """
        Start the server-authoritative 30s turn timer.
        Increments turn_sequence to invalidate prior timers and avoid races.
        """
        self.cancel_turn_timer()
        self.timeout_callback = timeout_callback
        self.turn_sequence += 1
        expected_seq = self.turn_sequence
        deadline = time.time() + timeout_seconds
        self.turn_deadline = deadline
        if self.game_state:
            self.game_state.turn_deadline = deadline
            self.game_state.turn_duration = timeout_seconds

        def _on_timeout():
            timeout_callback(self.code, expected_seq)

        self.turn_timer = threading.Timer(timeout_seconds, _on_timeout)
        self.turn_timer.daemon = True
        self.turn_timer.start()

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def host(self) -> RoomPlayer | None:
        if self.host_id and self.host_id in self.players:
            return self.players[self.host_id]
        return None

    def add_activity(self, event_type: str, message: str, player_name: str | None = None, icon: str = 'ℹ️') -> dict:
        """Record an activity in room history."""
        now = datetime.now()
        entry = {
            'id':          uuid.uuid4().hex[:8],
            'type':        event_type,
            'message':     message,
            'player_name': player_name,
            'icon':        icon,
            'timestamp':   now.strftime("%I:%M:%S %p"),
            'iso_time':    now.isoformat(),
        }
        self.activity_log.append(entry)
        if len(self.activity_log) > 200:
            self.activity_log.pop(0)
        return entry

    def clear_all_chat_stages(self):
        """Clear all three independent chat stage histories."""
        self.chat_messages.clear()
        self.chat_stages['in_match'].clear()
        self.chat_stages['post_match'].clear()

    def add_stage_chat_message(self, stage: str, sender_id: str, text: str,
                               max_length: int = MAX_CHAT_MESSAGE_LENGTH,
                               truncate: bool = False) -> dict:
        """
        Record an isolated chat message for one of the three independent stages:
        'pre_match' (waiting), 'in_match' (playing), 'post_match' (finished).
        Allows both active players and connected spectators; spectator messages
        receive the '[Spectator]' prefix.
        """
        if stage not in VALID_CHAT_STAGES:
            raise ValueError(f"Invalid chat stage: {stage}")

        expected_stage = STATUS_TO_CHAT_STAGE.get(self.status)
        if expected_stage != stage:
            if stage == 'pre_match':
                raise ValueError("Chat is available only in the lobby")
            raise ValueError(f"Chat stage '{stage}' is not active for room status '{self.status}'")

        if not isinstance(text, str):
            raise ValueError("Message must be text")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        if len(cleaned) > max_length:
            if truncate:
                cleaned = cleaned[:max_length]
            else:
                raise ValueError(f"Message exceeds maximum length of {max_length} characters")

        # Neutralize HTML/script injection while preserving normal readable punctuation
        safe_text = html.escape(cleaned, quote=False)

        is_spectator = False
        if sender_id in self.players:
            player = self.players[sender_id]
            if not player.connected or player.status != 'connected':
                raise ValueError("Player is not active in the room")
            sender_name = player.name
            display_name = player.name
        elif sender_id in self.spectators:
            spec = self.spectators[sender_id]
            if not spec.connected:
                raise ValueError("Spectator is not active in the room")
            is_spectator = True
            sender_name = spec.name
            display_name = f"[Spectator] {spec.name}"
        else:
            raise ValueError("Sender is not a member of this room")

        now = datetime.now()
        msg = {
            'id':           uuid.uuid4().hex[:8],
            'room_code':    self.code,
            'match_id':     self.match_id if stage != 'pre_match' else None,
            'stage':        stage,
            'sender_id':    sender_id,
            'sender_name':  sender_name,
            'display_name': display_name,
            'is_spectator': is_spectator,
            'text':         safe_text,
            'timestamp':    now.strftime("%I:%M %p"),
            'iso_time':     now.isoformat(),
        }
        stage_list = self.chat_stages[stage]
        stage_list.append(msg)
        if len(stage_list) > 100:
            stage_list.pop(0)
        return msg

    def add_chat_message(self, sender_id: str, sender_name: str, text: str) -> dict:
        """Backward-compatible helper for pre-match lobby chat."""
        return self.add_stage_chat_message(
            stage='pre_match',
            sender_id=sender_id,
            text=text,
            max_length=MAX_LOBBY_CHAT_LENGTH,
            truncate=True,
        )

    # ── Stage 2: Post-Match Ready / Play Again Helpers ──

    def enter_post_match(self):
        """
        Transition room into post-match finished state:
        - Captures exact previous-match players and deck count
        - Resets every previous-match player's Ready status to False (Not Ready)
        - Starts a fresh, empty post-match chat stage
        """
        self.status = 'finished'
        if self.game_state:
            self.last_match_player_ids = [p.id for p in self.game_state.players]
            self.last_match_deck_count = self.game_state.num_decks
        elif not self.last_match_player_ids:
            self.last_match_player_ids = list(self.players.keys())
            self.last_match_deck_count = self.deck_count

        self.post_match_ready = {pid: False for pid in self.last_match_player_ids}
        self.post_match_left_ids = {
            pid for pid in self.last_match_player_ids
            if pid not in self.players or self.players[pid].status == 'left'
        }
        self.play_again_in_progress = False

        # Independent post-match chat begins completely empty
        self.chat_stages['in_match'].clear()
        self.chat_stages['post_match'].clear()

    def set_player_ready(self, player_id: str, ready: bool) -> dict:
        """Toggle a previous-match player's Ready / Not Ready status (caller holds play_lock)."""
        if self.status != 'finished':
            raise ValueError("Ready status can only be changed after a match finishes")
        if player_id not in self.last_match_player_ids or player_id not in self.players:
            raise ValueError("Only previous-match players can change ready status")
        if player_id in self.post_match_left_ids:
            raise ValueError("Player has already left the room")
        player = self.players[player_id]
        if not player.connected or player.status != 'connected':
            raise ValueError("Player must be connected to set ready status")

        self.post_match_ready[player_id] = bool(ready)
        return self.get_post_match_status()

    def can_play_again(self) -> tuple[bool, str]:
        """
        Strictly validate ALL 4 Play Again conditions:
        1. Every player from the completed match is present in the original room.
        2. Every previous-match player is connected.
        3. Every previous-match player has selected Ready.
        4. No new or replacement player has taken the place of a missing previous-match player.
        """
        if self.status != 'finished':
            return False, "Match is not in finished state"
        if len(self.last_match_player_ids) < 2:
            return False, "At least 2 previous-match players are required"
        if self.play_again_in_progress:
            return False, "Rematch is already starting"

        expected_ids = set(self.last_match_player_ids)
        current_ids = set(self.players.keys())

        if current_ids != expected_ids:
            return False, "Room players do not match the completed match"
        if self.post_match_left_ids:
            return False, "A previous-match player has left the room"

        for pid in self.last_match_player_ids:
            p = self.players.get(pid)
            if not p or p.status == 'left':
                return False, "A previous-match player has left the room"
            if not p.connected or p.status != 'connected':
                return False, f"Waiting for {p.name} to reconnect"
            if not self.post_match_ready.get(pid, False):
                return False, f"Waiting for {p.name} to select Ready"

        return True, "All players are ready to Play Again"

    def get_post_match_status(self) -> dict:
        """Return live post-match readiness state for all previous-match players."""
        can_start, reason = self.can_play_again()
        players_status = []
        for pid in self.last_match_player_ids:
            p = self.players.get(pid)
            is_present = bool(p is not None and pid not in self.post_match_left_ids and p.status != 'left')
            is_connected = bool(is_present and p.connected and p.status == 'connected')
            is_ready = bool(is_connected and self.post_match_ready.get(pid, False))
            players_status.append({
                'id':        pid,
                'name':      p.name if p else 'Player',
                'present':   is_present,
                'connected': is_connected,
                'status':    p.status if p else 'left',
                'ready':     is_ready,
            })

        return {
            'room_code':      self.code,
            'match_id':       self.match_id,
            'deck_count':     self.last_match_deck_count,
            'players':        players_status,
            'can_play_again': can_start,
            'reason':         reason,
            'ready_count':    sum(1 for ps in players_status if ps['ready']),
            'total_players':  len(players_status),
        }

    # ── Stage 4: Spectator Helpers ──

    def add_spectator(self, name: str, sid: str | None = None) -> RoomSpectator:
        if self.status == 'finished':
            raise ValueError("This match has already finished and cannot accept new spectators")
        clean_name = (name or 'Spectator').strip()[:16] or 'Spectator'
        spec_id = f"spec_{uuid.uuid4().hex[:8]}"
        spec = RoomSpectator(id=spec_id, name=clean_name, sid=sid, connected=True)
        self.spectators[spec_id] = spec
        return spec

    def remove_spectator(self, spectator_id: str) -> RoomSpectator | None:
        return self.spectators.pop(spectator_id, None)

    def get_spectator_by_sid(self, sid: str) -> RoomSpectator | None:
        for s in self.spectators.values():
            if s.sid == sid:
                return s
        return None

    def get_spectators_summary(self) -> dict:
        active = [s.to_summary() for s in self.spectators.values() if s.connected]
        return {
            'room_code':       self.code,
            'spectator_count': len(active),
            'spectators':      active,
        }

    def add_player(self, name: str, sid: str | None = None, is_host: bool = False) -> RoomPlayer:
        if len(self.players) >= self.max_players:
            raise ValueError(f"Room {self.code} is full (max {self.max_players} players)")
        if self.status != 'waiting':
            raise ValueError(f"Game in room {self.code} is already in progress")

        pid = f"usr_{uuid.uuid4().hex[:8]}"
        player = RoomPlayer(id=pid, name=name, sid=sid, is_host=is_host, status='connected')
        self.players[pid] = player
        if is_host:
            self.host_id = pid
        return player

    def remove_player(self, player_id: str, reason: str = 'left') -> RoomPlayer | None:
        """
        Handle player removal/departure.
        If waiting, remove from list.
        If playing, retain slot marked as left/disconnected so table status displays accurately.
        """
        player = self.players.get(player_id)
        if not player:
            return None

        if self.status == 'waiting':
            self.players.pop(player_id, None)
            if player.is_host and self.players:
                new_host_id = next(iter(self.players))
                self.players[new_host_id].is_host = True
                self.host_id = new_host_id
            elif not self.players:
                self.host_id = None
        else:
            # During active or finished match: keep player record marked as left
            player.connected = False
            player.status = reason
            player.departure_reason = reason
            player.disconnected_at = time.time()
            if self.status == 'finished':
                self.post_match_ready[player_id] = False
                if reason == 'left':
                    self.post_match_left_ids.add(player_id)
            if self.game_state:
                p_game = self.game_state._get_player(player_id)
                if p_game:
                    p_game.connection_status = reason

        return player

    def get_player_by_sid(self, sid: str) -> RoomPlayer | None:
        for p in self.players.values():
            if p.sid == sid:
                return p
        return None

    def get_player_by_token(self, token: str) -> RoomPlayer | None:
        for p in self.players.values():
            if p.reconnect_token == token:
                return p
        return None

    def to_lobby_summary(self) -> dict:
        active_spectators = [s.to_summary() for s in self.spectators.values() if s.connected]
        return {
            'code':            self.code,
            'is_private':      self.is_private,
            'status':          self.status,
            'max_players':     self.max_players,
            'deck_count':      self.deck_count,
            'player_count':    len(self.players),
            'host_id':         self.host_id,
            'host_name':       self.host.name if self.host else 'Unknown',
            'players':         [p.to_summary() for p in self.players.values()],
            'spectator_count': len(active_spectators),
            'spectators':      active_spectators,
            'activity_log':    self.activity_log[::-1],  # Newest first
        }


class RoomManager:
    """Manages active game rooms."""

    def __init__(self):
        self.rooms: dict[str, Room] = {}  # code -> Room

    def _generate_code(self) -> str:
        """Generate a random 6-character uppercase alphanumeric code (e.g. KZ7492)."""
        chars = string.ascii_uppercase + string.digits
        safe_chars = [c for c in chars if c not in ('0', 'O', '1', 'I')]
        for _ in range(100):
            code = "KZ" + "".join(random.choices(safe_chars, k=4))
            if code not in self.rooms:
                return code
        return "KZ" + uuid.uuid4().hex[:4].upper()

    def create_room(self, host_name: str, is_private: bool = True,
                    max_players: int = 4, deck_count: int = 1,
                    sid: str | None = None) -> tuple[Room, RoomPlayer]:
        code = self._generate_code()
        room = Room(code=code, is_private=is_private, max_players=max_players, deck_count=deck_count)
        host = room.add_player(name=host_name, sid=sid, is_host=True)
        self.rooms[code] = room
        return room, host

    def join_room(self, room_code: str, player_name: str, sid: str | None = None,
                  reconnect_token: str | None = None) -> tuple[Room, RoomPlayer]:
        code = room_code.strip().upper()
        if code not in self.rooms:
            raise ValueError(f"Room '{code}' does not exist")
        room = self.rooms[code]

        # Feature 2 & Security: Reconnect to original player slot ONLY if a valid,
        # securely generated reconnect_token matches an existing player in this room
        # AND is within the 2-minute grace period.
        # NEVER allow reclaiming an existing player slot using only the same player name.
        if reconnect_token and isinstance(reconnect_token, str) and reconnect_token.strip():
            clean_token = reconnect_token.strip()
            for p in room.players.values():
                if p.reconnect_token == clean_token:
                    if room.status == 'finished' and p.id in room.post_match_left_ids:
                        raise ValueError("Cannot rejoin after leaving a finished room")
                    now = time.time()
                    if p.disconnected_at is not None and (now - p.disconnected_at) > GRACE_PERIOD_SECONDS:
                        raise ValueError("Reconnection grace period (2 minutes) has expired")
                    p.sid = sid
                    p.connected = True
                    p.status = 'connected'
                    p.departure_reason = None
                    p.disconnected_at = None
                    if room.status == 'finished':
                        # Must select Ready again after reconnecting
                        room.post_match_ready[p.id] = False
                    if room.game_state:
                        p_game = room.game_state._get_player(p.id)
                        if p_game:
                            p_game.connection_status = 'connected'
                    return room, p

        # If token is missing, invalid, or does not match:
        # Reject joining active or finished rooms (prevents replacing a missing previous-match player)
        if room.status == 'finished':
            raise ValueError(f"Game in room '{code}' has already finished")
        if room.status != 'waiting':
            raise ValueError(f"Game in room '{code}' is already in progress")

        player = room.add_player(name=player_name, sid=sid, is_host=False)
        return room, player

    def get_room(self, room_code: str) -> Room | None:
        if not room_code:
            return None
        return self.rooms.get(room_code.strip().upper())

    def get_room_by_sid(self, sid: str) -> tuple[Room | None, RoomPlayer | None]:
        for room in self.rooms.values():
            player = room.get_player_by_sid(sid)
            if player:
                return room, player
        return None, None

    def reconnect_player(self, reconnect_token: str, new_sid: str,
                         room_code: str | None = None,
                         player_id: str | None = None) -> tuple[Room | None, RoomPlayer | None]:
        if not reconnect_token or not isinstance(reconnect_token, str) or not reconnect_token.strip():
            return None, None
        clean_token = reconnect_token.strip()
        clean_player_id = player_id.strip() if (player_id and isinstance(player_id, str)) else None
        now = time.time()

        if room_code:
            target_room = self.get_room(room_code)
            if not target_room:
                return None, None
            candidate_rooms = [target_room]
        else:
            candidate_rooms = list(self.rooms.values())

        for room in candidate_rooms:
            player = room.get_player_by_token(clean_token)
            if player:
                # If player_id was specified, strictly verify it matches the slot
                if clean_player_id and player.id != clean_player_id:
                    return None, None

                # Do not allow reconnecting to a finished room after explicitly leaving
                if room.status == 'finished' and player.id in room.post_match_left_ids:
                    return None, None

                # Enforce 2-minute grace period if player was disconnected
                if player.disconnected_at is not None and (now - player.disconnected_at) > GRACE_PERIOD_SECONDS:
                    return None, None

                player.sid = new_sid
                player.connected = True
                player.status = 'connected'
                player.departure_reason = None
                player.disconnected_at = None
                if room.status == 'finished':
                    # Reconnected previous-match player must select Ready again
                    room.post_match_ready[player.id] = False
                if room.game_state:
                    p_game = room.game_state._get_player(player.id)
                    if p_game:
                        p_game.connection_status = 'connected'
                return room, player
        return None, None

    def handle_disconnect(self, sid: str, reason: str = 'disconnected') -> tuple[Room | None, RoomPlayer | None]:
        room, player = self.get_room_by_sid(sid)
        if room and player:
            # Stale socket disconnect protection:
            # If the player already reconnected on a newer socket (player.sid != sid),
            # this old socket disconnect event must NOT override the newer active connection!
            if player.sid != sid:
                return None, None

            # Only update if not already explicitly marked as 'left'
            if player.status != 'left':
                player.connected = False
                player.status = reason
                player.departure_reason = reason
                player.disconnected_at = time.time()
                player.sid = None  # Clear old socket ID so stale events cannot match

                if room.status == 'finished':
                    room.post_match_ready[player.id] = False

                if room.game_state:
                    p_game = room.game_state._get_player(player.id)
                    if p_game:
                        p_game.connection_status = reason

            # If waiting and not in game, only clean up if all players explicitly left
            if room.status == 'waiting':
                all_left = all(p.status == 'left' for p in room.players.values())
                if all_left:
                    self.rooms.pop(room.code, None)
            return room, player
        return None, None

    def leave_room(self, room_code: str, player_id: str, reason: str = 'left') -> Room | None:
        room = self.get_room(room_code)
        if not room:
            return None
        room.remove_player(player_id, reason=reason)
        # If in waiting room and no players left, clean up
        if room.status == 'waiting' and len(room.players) == 0:
            self.rooms.pop(room.code, None)
            return None
        # If finished and all players left AND no connected spectators remain, clean up
        if room.status == 'finished':
            all_left = all(p.status == 'left' for p in room.players.values())
            any_spectators = any(s.connected for s in room.spectators.values())
            if all_left and not any_spectators:
                self.rooms.pop(room.code, None)
                return None
        return room

    # ── Stage 4: Spectator RoomManager Operations ──

    def join_as_spectator(self, room_code: str, spectator_name: str, sid: str | None = None) -> tuple[Room, RoomSpectator]:
        code = (room_code or '').strip().upper()
        if not code or code not in self.rooms:
            raise ValueError(f"Room '{code}' does not exist")
        room = self.rooms[code]
        if room.status == 'finished':
            raise ValueError("This match has already finished and cannot accept new spectators")
        spec = room.add_spectator(name=spectator_name, sid=sid)
        return room, spec

    def leave_spectator(self, room_code: str, spectator_id: str) -> tuple[Room | None, RoomSpectator | None]:
        room = self.get_room(room_code)
        if not room:
            return None, None
        spec = room.remove_spectator(spectator_id)
        if room.status == 'finished':
            all_left = all(p.status == 'left' for p in room.players.values())
            any_spectators = any(s.connected for s in room.spectators.values())
            if all_left and not any_spectators:
                self.rooms.pop(room.code, None)
        return room, spec

    def get_spectator_by_sid(self, sid: str) -> tuple[Room | None, RoomSpectator | None]:
        for room in self.rooms.values():
            spec = room.get_spectator_by_sid(sid)
            if spec:
                return room, spec
        return None, None

    def handle_spectator_disconnect(self, sid: str) -> tuple[Room | None, RoomSpectator | None]:
        room, spec = self.get_spectator_by_sid(sid)
        if room and spec:
            room.remove_spectator(spec.id)
            if room.status == 'finished':
                all_left = all(p.status == 'left' for p in room.players.values())
                any_spectators = any(s.connected for s in room.spectators.values())
                if all_left and not any_spectators:
                    self.rooms.pop(room.code, None)
            return room, spec
        return None, None

    def start_game(self, room_code: str, requester_id: str) -> Room:
        room = self.get_room(room_code)
        if not room:
            raise ValueError(f"Room '{room_code}' does not exist")
        if room.host_id != requester_id:
            raise ValueError("Only the room host can start the game")
        if len(room.players) < 2:
            raise ValueError("At least 2 players are required to start the game")
        if room.status == 'playing':
            raise ValueError("Game is already in progress")

        # Randomly shuffle player order exactly ONCE when match starts
        player_list = list(room.players.values())
        random.shuffle(player_list)

        # Create player configurations using the finalized shuffled order
        player_configs = [
            {'id': p.id, 'name': p.name, 'is_ai': False}
            for p in player_list
        ]

        game_state = GameState(
            game_id=room.code,
            player_configs=player_configs,
            num_decks=room.deck_count,
        )
        game_state.setup()

        # Generate fresh match identifier and clear all independent chat stages
        room.match_id = uuid.uuid4().hex[:12]
        room.clear_all_chat_stages()
        room.cancel_turn_timer()

        # Reset post-match readiness state for the new match
        room.last_match_player_ids = [p.id for p in player_list]
        room.last_match_deck_count = room.deck_count
        room.post_match_ready.clear()
        room.post_match_left_ids.clear()
        room.play_again_in_progress = False

        room.game_state = game_state
        room.status = 'playing'
        return room

    def restart_game(self, room_code: str, requester_id: str) -> Room:
        """
        Existing host-controlled Restart Game.
        Generates a completely new random shuffle and distributes cards.
        """
        room = self.get_room(room_code)
        if not room:
            raise ValueError(f"Room '{room_code}' does not exist")
        if room.host_id != requester_id:
            raise ValueError("Only the room host can start/restart the game")
        room.game_state = None
        room.status = 'waiting'
        return self.start_game(room_code, requester_id)

    def play_again(self, room_code: str, requester_id: str) -> Room:
        """
        Stage 2: Post-match Play Again.
        Atomically validates all 4 readiness conditions under room.play_lock,
        prevents concurrent restarts, keeps the exact previous-match players and
        deck configuration, shuffles a completely fresh deck with 1 A♠, and starts
        a new match with fresh isolated chat stages.
        """
        room = self.get_room(room_code)
        if not room:
            raise ValueError(f"Room '{room_code}' does not exist")

        with room.play_lock:
            if requester_id not in room.last_match_player_ids or requester_id not in room.players:
                raise ValueError("Only previous-match players can trigger Play Again")

            can_start, reason = room.can_play_again()
            if not can_start:
                raise ValueError(reason)

            room.play_again_in_progress = True
            try:
                # Preserve exact previous-match players and deck configuration
                room.deck_count = room.last_match_deck_count
                player_list = [room.players[pid] for pid in room.last_match_player_ids]
                random.shuffle(player_list)

                player_configs = [
                    {'id': p.id, 'name': p.name, 'is_ai': False}
                    for p in player_list
                ]

                game_state = GameState(
                    game_id=room.code,
                    player_configs=player_configs,
                    num_decks=room.deck_count,
                )
                game_state.setup()

                room.match_id = uuid.uuid4().hex[:12]
                room.clear_all_chat_stages()
                room.cancel_turn_timer()

                room.last_match_player_ids = [p.id for p in player_list]
                room.last_match_deck_count = room.deck_count
                room.post_match_ready.clear()
                room.post_match_left_ids.clear()

                room.game_state = game_state
                room.status = 'playing'
                return room
            finally:
                room.play_again_in_progress = False

    def get_public_rooms(self) -> list[dict]:
        """Returns list of active joinable public rooms."""
        public_list = []
        for room in self.rooms.values():
            if not room.is_private and room.status == 'waiting' and len(room.players) < room.max_players:
                public_list.append({
                    'code':        room.code,
                    'hostName':    room.host.name if room.host else 'Host',
                    'playerCount': len(room.players),
                    'maxPlayers':  room.max_players,
                    'deckCount':   room.deck_count,
                })
        return public_list


# Global singleton room manager instance
room_manager = RoomManager()
