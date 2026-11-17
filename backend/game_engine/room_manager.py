"""
KAZHUDHAI CLUB — game_engine/room_manager.py
Authoritative room and multiplayer session manager.
Supports private rooms with 6-char codes, public lobbies, 2–7 players, 1–5 decks,
reconnection tokens, activity history logging, real-time connection status tracking,
and zero-leak state serialisation.
"""
from __future__ import annotations
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
        self.max_players = max(2, min(7, max_players))
        self.deck_count = max(1, min(5, deck_count))
        self.status = 'waiting'  # 'waiting', 'playing', 'finished'
        self.players: dict[str, RoomPlayer] = {}  # player_id -> RoomPlayer
        self.host_id: str | None = None
        self.game_state: GameState | None = None
        self.activity_log: list[dict] = []  # Chronological game activity entries
        self.chat_messages: list[dict] = []  # Lobby-only real-time chat messages
        self.play_lock = threading.Lock()    # Atomic lock for turn moves and timeout handling
        self.turn_sequence: int = 0          # Monotonically increasing counter per turn
        self.turn_timer: threading.Timer | None = None
        self.turn_deadline: float | None = None

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

    def add_chat_message(self, sender_id: str, sender_name: str, text: str) -> dict:
        """Record a chat message while in lobby."""
        if self.status != 'waiting':
            raise ValueError("Chat is available only in the lobby")
        if sender_id not in self.players:
            raise ValueError("Sender is not a member of this room")
        player = self.players[sender_id]
        if not player.connected or player.status != 'connected':
            raise ValueError("Player is not active in the room")
        now = datetime.now()
        msg = {
            'id':          uuid.uuid4().hex[:8],
            'sender_id':   sender_id,
            'sender_name': sender_name,
            'text':        text.strip(),
            'timestamp':   now.strftime("%I:%M %p"),
            'iso_time':    now.isoformat(),
        }
        self.chat_messages.append(msg)
        if len(self.chat_messages) > 100:
            self.chat_messages.pop(0)
        return msg

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
            # During active game: keep player record marked as left
            player.connected = False
            player.status = reason
            player.departure_reason = reason
            player.disconnected_at = time.time()
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
        return {
            'code':         self.code,
            'is_private':   self.is_private,
            'status':       self.status,
            'max_players':  self.max_players,
            'deck_count':   self.deck_count,
            'player_count': len(self.players),
            'host_id':      self.host_id,
            'host_name':    self.host.name if self.host else 'Unknown',
            'players':      [p.to_summary() for p in self.players.values()],
            'activity_log': self.activity_log[::-1],  # Newest first
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
                    now = time.time()
                    if p.disconnected_at is not None and (now - p.disconnected_at) > GRACE_PERIOD_SECONDS:
                        raise ValueError("Reconnection grace period (2 minutes) has expired")
                    p.sid = sid
                    p.connected = True
                    p.status = 'connected'
                    p.departure_reason = None
                    p.disconnected_at = None
                    if room.game_state:
                        p_game = room.game_state._get_player(p.id)
                        if p_game:
                            p_game.connection_status = 'connected'
                    return room, p

        # If token is missing, invalid, or does not match:
        # If match is already playing, reject immediately (cannot take over any slot without valid token)
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

                # Enforce 2-minute grace period if player was disconnected
                if player.disconnected_at is not None and (now - player.disconnected_at) > GRACE_PERIOD_SECONDS:
                    return None, None

                player.sid = new_sid
                player.connected = True
                player.status = 'connected'
                player.departure_reason = None
                player.disconnected_at = None
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
        return room

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

        # Clear lobby chat history when match starts (chat is disabled during gameplay)
        room.chat_messages.clear()
        room.cancel_turn_timer()

        room.game_state = game_state
        room.status = 'playing'
        return room

    def restart_game(self, room_code: str, requester_id: str) -> Room:
        """
        Restart the game in an existing room for a rematch.
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
