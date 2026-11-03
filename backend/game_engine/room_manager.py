"""
KAZHUDHAI CLUB — game_engine/room_manager.py
Authoritative room and multiplayer session manager.
Supports private rooms with 6-char codes, public lobbies, 2–7 players, 1–5 decks,
reconnection tokens, activity history logging, real-time connection status tracking,
and zero-leak state serialisation.
"""
from __future__ import annotations
import random
import string
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from game_engine.game_state import GameState


@dataclass
class RoomPlayer:
    id: str
    name: str
    sid: str | None
    is_host: bool = False
    connected: bool = True
    status: str = 'connected'  # 'connected', 'reconnecting', 'disconnected', 'left'
    departure_reason: str | None = None
    reconnect_token: str = field(default_factory=lambda: uuid.uuid4().hex)

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

    def join_room(self, room_code: str, player_name: str, sid: str | None = None) -> tuple[Room, RoomPlayer]:
        code = room_code.strip().upper()
        if code not in self.rooms:
            raise ValueError(f"Room '{code}' does not exist")
        room = self.rooms[code]
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

    def reconnect_player(self, reconnect_token: str, new_sid: str) -> tuple[Room | None, RoomPlayer | None]:
        for room in self.rooms.values():
            player = room.get_player_by_token(reconnect_token)
            if player:
                player.sid = new_sid
                player.connected = True
                player.status = 'connected'
                player.departure_reason = None
                if room.game_state:
                    p_game = room.game_state._get_player(player.id)
                    if p_game:
                        p_game.connection_status = 'connected'
                return room, player
        return None, None

    def handle_disconnect(self, sid: str, reason: str = 'disconnected') -> tuple[Room | None, RoomPlayer | None]:
        room, player = self.get_room_by_sid(sid)
        if room and player:
            # Only update if not already explicitly marked as 'left'
            if player.status != 'left':
                player.connected = False
                player.status = reason
                player.departure_reason = reason
                if room.game_state:
                    p_game = room.game_state._get_player(player.id)
                    if p_game:
                        p_game.connection_status = reason

            # If waiting and not in game, and all players disconnected or empty, clean up
            if room.status == 'waiting':
                all_disconnected = all(not p.connected for p in room.players.values())
                if all_disconnected:
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

        # Create player configurations preserving table order
        player_configs = [
            {'id': p.id, 'name': p.name, 'is_ai': False}
            for p in room.players.values()
        ]

        game_state = GameState(
            game_id=room.code,
            player_configs=player_configs,
            num_decks=room.deck_count,
        )
        game_state.setup()

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
