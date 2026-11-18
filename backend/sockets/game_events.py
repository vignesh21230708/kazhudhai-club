"""
KAZHUDHAI CLUB — sockets/game_events.py
SocketIO event handlers for real-time multiplayer.
Handles private/public room creation, joins, card play broadcasts,
authoritative rule execution, zero-leak state delivery,
instant leave/disconnect notifications, connection status tracking,
and real-time game activity history synchronization.
"""
import os
from flask import request
from flask_socketio import emit, join_room, leave_room
from game_engine.room_manager import room_manager
from game_engine.deck import SUIT_SYMBOLS


def register_socket_events(socketio):

    def _get_authenticated_player(room, player_id):
        """
        Verify that player_id belongs to room.players (never room.spectators)
        and is bound to the current Socket.IO connection (request.sid).
        """
        if not room or not player_id or player_id in room.spectators:
            return None
        player = room.players.get(player_id)
        if not player or not player.sid or player.sid != request.sid:
            return None
        return player

    def _get_authenticated_spectator(room, spectator_id):
        """
        Verify that spectator_id belongs to room.spectators and is bound
        to the current Socket.IO connection (request.sid).
        """
        if not room or not spectator_id:
            return None
        spec = room.spectators.get(spectator_id)
        if not spec or not spec.sid or spec.sid != request.sid:
            return None
        return spec

    def _is_spectator_socket(room):
        """Return True if the current Socket.IO connection is a spectator in room."""
        return bool(room and room.get_spectator_by_sid(request.sid) is not None)

    def _ensure_voice_peers_locked(room):
        """Ensure room.voice_peers exists. Caller MUST hold room.play_lock."""
        if not hasattr(room, 'voice_peers') or room.voice_peers is None:
            room.voice_peers = set()
        return room.voice_peers

    def _clear_voice_peers(room):
        """Safely initialize/clear room.voice_peers under room.play_lock."""
        if not room:
            return
        with room.play_lock:
            _ensure_voice_peers_locked(room).clear()

    def _remove_voice_peer_and_notify(room, player_id):
        """
        Atomically remove player_id from room.voice_peers under room.play_lock.
        Notifies only remaining active voice peers via their Socket.IO sid,
        returning True only when the peer was actually removed (preventing
        duplicate voice_peer_left notifications).
        """
        if not room or not player_id:
            return False
        notify_sids = []
        with room.play_lock:
            voice_peers = _ensure_voice_peers_locked(room)
            if player_id not in voice_peers:
                return False
            voice_peers.discard(player_id)
            for pid in list(voice_peers):
                peer = room.players.get(pid)
                if peer and peer.connected and peer.sid:
                    notify_sids.append(peer.sid)

        for sid in notify_sids:
            emit('voice_peer_left', {'peerId': player_id}, to=sid)
        return True

    @socketio.on('connect')
    def handle_connect():
        pass

    @socketio.on('disconnect')
    def handle_disconnect():
        # Stage 4: Check if disconnecting socket belongs to a spectator first
        spec_room, spec = room_manager.handle_spectator_disconnect(request.sid)
        if spec_room and spec:
            emit('spectators_updated', spec_room.get_spectators_summary(), room=spec_room.code)
            if spec_room.status == 'waiting':
                emit('room_updated', spec_room.to_lobby_summary(), room=spec_room.code)
            return

        room, player = room_manager.handle_disconnect(request.sid, reason='disconnected')
        if room and player:
            # Always clean up voice participant state and notify active voice peers
            # even when departure_notified was already set (e.g. client_connection_lost).
            _remove_voice_peer_and_notify(room, player.id)

            # Stage 2: If match is finished, always broadcast updated post-match readiness
            # so Play Again immediately disables when a player disconnects.
            if room.status == 'finished':
                emit('post_match_status', room.get_post_match_status(), room=room.code)

            # Prevent duplicate departure notification if player already called leave_room
            if getattr(player, 'departure_notified', False):
                return
            player.departure_notified = True

            message = f"{player.name} disconnected."
            notice = f"🔴 {player.name} disconnected."

            # Log to activity history
            act = room.add_activity('disconnect', message, player_name=player.name, icon='🔴')

            # 1. Instant Leave/Disconnect notification to all remaining players (5s display)
            emit('player_departure', {
                'player_id': player.id,
                'name':      player.name,
                'reason':    'disconnected',
                'message':   notice,
                'status':    'disconnected',
                'duration':  5000,
            }, room=room.code)

            # 2. Player status update (🔴 Disconnected)
            emit('player_status_change', {
                'player_id': player.id,
                'name':      player.name,
                'connected': False,
                'status':    'disconnected',
            }, room=room.code)

            # 3. Synchronize activity feed across devices
            emit('activity_logged', act, room=room.code)

            if room.status == 'waiting':
                emit('room_updated', room.to_lobby_summary(), room=room.code)
            elif room.status == 'playing':
                _broadcast_personalized_state(room)

    @socketio.on('client_connection_lost')
    def handle_client_connection_lost(data):
        data = data or {}
        room_code = (data.get('roomCode') or '').strip().upper()
        player_id = data.get('playerId')
        room = room_manager.get_room(room_code)
        player = _get_authenticated_player(room, player_id)
        if not player:
            return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

        player.connected = False
        player.status = 'reconnecting'
        player.departure_notified = True
        if room.status == 'finished':
            room.post_match_ready[player.id] = False

        message = f"{player.name} lost connection."
        notice  = f"🟡 {player.name} lost connection."

        act = room.add_activity('connection_lost', message, player_name=player.name, icon='🟡')

        emit('player_departure', {
            'player_id': player.id,
            'name':      player.name,
            'reason':    'connection_lost',
            'message':   notice,
            'status':    'reconnecting',
            'duration':  5000,
        }, room=room.code)

        emit('player_status_change', {
            'player_id': player.id,
            'name':      player.name,
            'connected': False,
            'status':    'reconnecting',
        }, room=room.code)

        emit('activity_logged', act, room=room.code)
        if room.status == 'finished':
            emit('post_match_status', room.get_post_match_status(), room=room.code)
        return {'success': True}

    @socketio.on('create_room')
    def handle_create_room(data):
        try:
            player_name = (data.get('playerName') or 'Player').strip()
            is_private  = bool(data.get('isPrivate', True))
            max_players = int(data.get('maxPlayers', 4))
            deck_count  = int(data.get('deckCount', 1))

            room, host = room_manager.create_room(
                host_name=player_name,
                is_private=is_private,
                max_players=max_players,
                deck_count=deck_count,
                sid=request.sid,
            )
            _clear_voice_peers(room)
            join_room(room.code)

            print(f"[SocketIO] Room created: code={room.code}, host={host.name}, sid={request.sid}")

            # Log initial host join activity
            room.add_activity('join', f"{host.name} joined the room.", player_name=host.name, icon='🟢')

            return {
                'success':         True,
                'room_code':       room.code,
                'player_id':       host.id,
                'player_name':     host.name,
                'is_host':         True,
                'reconnect_token': host.reconnect_token,
                'room':            room.to_lobby_summary(),
            }
        except Exception as e:
            print(f"[SocketIO] create_room error: {e}")
            return {'success': False, 'message': str(e)}

    @socketio.on('join_room')
    def handle_join_room(data):
        try:
            player_name     = (data.get('playerName') or 'Player').strip()
            room_code       = (data.get('roomCode') or '').strip().upper()
            reconnect_token = data.get('reconnectToken')

            room, player = room_manager.join_room(
                room_code=room_code,
                player_name=player_name,
                sid=request.sid,
                reconnect_token=reconnect_token,
            )
            join_room(room.code)

            print(f"[SocketIO] Player joined: code={room.code}, player={player.name}, sid={request.sid}")

            # Log join activity
            act = room.add_activity('join', f"{player.name} joined the room.", player_name=player.name, icon='🟢')

            if room.status == 'waiting':
                # Broadcast updated lobby to all players in the room
                emit('room_updated', room.to_lobby_summary(), room=room.code)
                emit('activity_logged', act, room=room.code)
            elif room.status == 'playing' and room.game_state:
                # Reconnected to playing match via join_room
                emit('player_status_change', {
                    'player_id': player.id,
                    'name':      player.name,
                    'connected': True,
                    'status':    'connected',
                }, room=room.code)
                emit('activity_logged', act, room=room.code)
                personalized_state = room.game_state.get_state_for_player(player.id)
                personalized_state['activity_log'] = room.activity_log[::-1]
                emit('game_state', personalized_state, to=request.sid)
                _broadcast_personalized_state(room)
            elif room.status == 'finished':
                emit('player_status_change', {
                    'player_id': player.id,
                    'name':      player.name,
                    'connected': True,
                    'status':    'connected',
                }, room=room.code)
                emit('activity_logged', act, room=room.code)
                emit('post_match_status', room.get_post_match_status(), room=room.code)

            res_payload = {
                'success':         True,
                'room_code':       room.code,
                'player_id':       player.id,
                'player_name':     player.name,
                'is_host':         player.is_host,
                'reconnect_token': player.reconnect_token,
                'room_status':     room.status,
                'room':            room.to_lobby_summary(),
            }
            if room.status == 'finished':
                res_payload['post_match_status'] = room.get_post_match_status()
            return res_payload
        except Exception as e:
            print(f"[SocketIO] join_room error for code '{data.get('roomCode')}': {e}")
            return {'success': False, 'message': str(e)}

    @socketio.on('leave_room')
    def handle_leave_room(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            reason    = data.get('reason') or 'left'

            room = room_manager.get_room(room_code)
            if not room:
                leave_room(room_code)
                return {'success': True}

            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            leave_room(room_code)
            _remove_voice_peer_and_notify(room, player.id)
            player.departure_notified = True
            message = f"{player.name} left the game."
            notice  = f"🔴 {player.name} left the game."

            act = room.add_activity('leave', message, player_name=player.name, icon='🔴')

            # Immediate departure notification (~5 seconds display)
            emit('player_departure', {
                'player_id': player.id,
                'name':      player.name,
                'reason':    'left',
                'message':   notice,
                'status':    'left',
                'duration':  5000,
            }, room=room.code)

            emit('player_status_change', {
                'player_id': player.id,
                'name':      player.name,
                'connected': False,
                'status':    'left',
            }, room=room.code)

            emit('activity_logged', act, room=room.code)

            updated_room = room_manager.leave_room(room_code, player.id, reason=reason)
            if updated_room:
                if updated_room.status == 'waiting':
                    emit('room_updated', updated_room.to_lobby_summary(), room=room_code)
                elif updated_room.status == 'playing':
                    _broadcast_personalized_state(updated_room)
                elif updated_room.status == 'finished':
                    emit('post_match_status', updated_room.get_post_match_status(), room=room_code)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _execute_turn_timeout(room_code: str, expected_sequence: int):
        room = room_manager.get_room(room_code)
        if not room:
            return

        with room.play_lock:
            if room.status != 'playing' or not room.game_state:
                return
            if room.turn_sequence != expected_sequence:
                return

            current_player = room.game_state.current_player
            if not current_player:
                return

            try:
                res = room.game_state.auto_play_current_turn()
                card = res['action']['card']
                suit_sym = SUIT_SYMBOLS.get(card['suit'], card['suit'])
                card_label = f"{card['rank']}{suit_sym}"
                p_name = res['action']['player_name']

                # Activity log
                if res['action']['is_attack']:
                    act = room.add_activity('attack', f"⏰ Turn timeout: ⚔️ Attack by {p_name} with {card_label}!", player_name=p_name, icon='⚔️')
                else:
                    act = room.add_activity('play', f"⏰ Turn timeout: {p_name} auto-played {card_label}.", player_name=p_name, icon='⏳')

                # Broadcast card played to all players in the room
                socketio.emit('card_played', res['action'], room=room.code)
                socketio.emit('activity_logged', act, room=room.code)

                # Round completion handling
                if res['round_completed']:
                    round_res = res['last_round_result']
                    socketio.emit('round_resolved', round_res, room=room.code)
                    if round_res and round_res.get('eliminated_players'):
                        for safe_name in round_res['eliminated_players']:
                            act_safe = room.add_activity('safe', f"🎉 {safe_name} is Safe!", player_name=safe_name, icon='🎉')
                            socketio.emit('activity_logged', act_safe, room=room.code)

                # Game finished check
                if room.game_state.status == 'finished':
                    room.enter_post_match()
                    _ensure_voice_peers_locked(room).clear()
                    room.cancel_turn_timer()
                    kazhudhai = next((r for r in room.game_state.rankings if r.get('is_kazhudhai')), None)
                    k_name = kazhudhai['name'] if kazhudhai else 'Unknown'
                    post_status = room.get_post_match_status()
                    spec_summary = room.get_spectators_summary()
                    act_end = room.add_activity('game_over', f"👑 Game ended. {k_name} is KAZHUDHAI!", icon='👑')
                    socketio.emit('activity_logged', act_end, room=room.code)
                    socketio.emit('game_over', {
                        'rankings':          room.game_state.rankings,
                        'kazhudhai_name':    k_name,
                        'room_code':         room.code,
                        'match_id':          room.match_id,
                        'deck_count':        room.last_match_deck_count,
                        'post_match_status': post_status,
                        'spectator_count':   spec_summary['spectator_count'],
                        'spectators':        spec_summary['spectators'],
                    }, room=room.code)
                    socketio.emit('post_match_status', post_status, room=room.code)
                else:
                    # Restart 30s turn timer for next turn
                    room.start_turn_timer(_execute_turn_timeout, timeout_seconds=30.0)

                _broadcast_personalized_state(room)

            except Exception as e:
                print(f"[TurnTimer] Error during auto-play timeout: {e}")

    @socketio.on('start_game')
    def handle_start_game(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot start the game'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            if room.status == 'finished':
                room = room_manager.restart_game(room_code, player.id)
            else:
                room = room_manager.start_game(room_code, player.id)

            _clear_voice_peers(room)

            # Log game started activity
            act = room.add_activity('start', "Game started.", icon='🚀')

            # Notify room (players + spectators) game has started
            emit('game_started', {
                'room_code':  room.code,
                'match_id':   room.match_id,
                'deck_count': room.deck_count,
            }, room=room.code)
            emit('activity_logged', act, room=room.code)
            emit('spectators_updated', room.get_spectators_summary(), room=room.code)

            # Start authoritative 30s turn timer
            room.start_turn_timer(_execute_turn_timeout, timeout_seconds=30.0)

            # Send personalized states to players and sanitized state to spectators
            _broadcast_personalized_state(room)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('restart_game')
    def handle_restart_game(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot restart the game'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            room = room_manager.restart_game(room_code, player.id)
            _clear_voice_peers(room)

            act = room.add_activity('start', "Match restarted (fresh random deck shuffled).", icon='🔄')

            emit('game_started', {
                'room_code':  room.code,
                'match_id':   room.match_id,
                'deck_count': room.deck_count,
            }, room=room.code)
            emit('activity_logged', act, room=room.code)
            emit('spectators_updated', room.get_spectators_summary(), room=room.code)

            # Start authoritative 30s turn timer
            room.start_turn_timer(_execute_turn_timeout, timeout_seconds=30.0)

            _broadcast_personalized_state(room)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ── Stage 2: Post-Match Ready / Not Ready & Play Again ──

    @socketio.on('set_post_match_ready')
    def handle_set_post_match_ready(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            ready     = bool(data.get('ready', False))

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot set player ready status'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            with room.play_lock:
                post_status = room.set_player_ready(player.id, ready)

            emit('post_match_status', post_status, room=room.code)
            return {'success': True, 'post_match_status': post_status}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('play_again')
    def handle_play_again(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot start Play Again'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            room = room_manager.play_again(room_code, player.id)
            _clear_voice_peers(room)

            act = room.add_activity('start', "All players ready — new match started!", icon='🔄')

            emit('game_started', {
                'room_code':  room.code,
                'match_id':   room.match_id,
                'deck_count': room.deck_count,
            }, room=room.code)
            emit('activity_logged', act, room=room.code)
            emit('spectators_updated', room.get_spectators_summary(), room=room.code)

            room.start_turn_timer(_execute_turn_timeout, timeout_seconds=30.0)
            _broadcast_personalized_state(room)

            return {
                'success':    True,
                'room_code':  room.code,
                'match_id':   room.match_id,
                'deck_count': room.deck_count,
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('play_card')
    def handle_play_card(data):
        room = None
        verified_player_id = None
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            card_id   = data.get('cardId')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot play cards'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}
            verified_player_id = player.id
            if room.status != 'playing' or not room.game_state:
                return {'success': False, 'message': 'Game is not in progress'}

            with room.play_lock:
                # Authoritative game play
                res = room.game_state.play_card(verified_player_id, card_id)
                card = res['action']['card']
                suit_sym = SUIT_SYMBOLS.get(card['suit'], card['suit'])
                card_label = f"{card['rank']}{suit_sym}"
                p_name = res['action']['player_name']

                # Record play in activity history
                if res['action']['is_attack']:
                    act = room.add_activity('attack', f"⚔️ Attack triggered by {p_name} with {card_label}!", player_name=p_name, icon='⚔️')
                else:
                    act = room.add_activity('play', f"{p_name} played {card_label}.", player_name=p_name, icon='🃏')

                # Broadcast the action card played to all table participants
                emit('card_played', res['action'], room=room.code)
                emit('activity_logged', act, room=room.code)

                # If round resolved, broadcast round completion details
                if res['round_completed']:
                    round_res = res['last_round_result']
                    emit('round_resolved', round_res, room=room.code)

                    # Record eliminated safe players
                    if round_res and round_res.get('eliminated_players'):
                        for safe_name in round_res['eliminated_players']:
                            act_safe = room.add_activity('safe', f"🎉 {safe_name} is Safe!", player_name=safe_name, icon='🎉')
                            emit('activity_logged', act_safe, room=room.code)

                # If game is finished, transition to post-match and broadcast game over
                if room.game_state.status == 'finished':
                    room.enter_post_match()
                    _ensure_voice_peers_locked(room).clear()
                    room.cancel_turn_timer()
                    kazhudhai = next((r for r in room.game_state.rankings if r.get('is_kazhudhai')), None)
                    k_name = kazhudhai['name'] if kazhudhai else 'Unknown'
                    post_status = room.get_post_match_status()
                    spec_summary = room.get_spectators_summary()

                    act_end = room.add_activity('game_over', f"👑 Game ended. {k_name} is KAZHUDHAI!", icon='👑')
                    emit('activity_logged', act_end, room=room.code)

                    emit('game_over', {
                        'rankings':          room.game_state.rankings,
                        'kazhudhai_name':    k_name,
                        'room_code':         room.code,
                        'match_id':          room.match_id,
                        'deck_count':        room.last_match_deck_count,
                        'post_match_status': post_status,
                        'spectator_count':   spec_summary['spectator_count'],
                        'spectators':        spec_summary['spectators'],
                    }, room=room.code)
                    emit('post_match_status', post_status, room=room.code)
                else:
                    # Advance 30s turn timer for next turn
                    room.start_turn_timer(_execute_turn_timeout, timeout_seconds=30.0)

                # Sync personalized state to players and sanitized state to spectators
                _broadcast_personalized_state(room)

            return {'success': True}
        except Exception as e:
            # Re-emit authoritative personalized state ONLY to the verified owner socket (never spoofed/spectator)
            if (
                room
                and room.game_state
                and verified_player_id
                and _get_authenticated_player(room, verified_player_id) is not None
            ):
                try:
                    emit('game_state', room.game_state.get_state_for_player(verified_player_id), to=request.sid)
                except Exception:
                    pass
            return {'success': False, 'message': str(e)}

    @socketio.on('get_room_state')
    def handle_get_room_state(data):
        data = data or {}
        room_code    = (data.get('roomCode') or '').strip().upper()
        player_id    = data.get('playerId')
        spectator_id = data.get('spectatorId')
        room = room_manager.get_room(room_code)
        if not room or not room.game_state:
            return {'success': False, 'message': 'Room not found'}

        # Strict spectator privacy: spectator sockets may ONLY fetch sanitized spectator_state
        # for their own spectator identity, never a player's hidden game_state.
        caller_spec = room.get_spectator_by_sid(request.sid)
        if caller_spec is not None:
            requested_id = spectator_id or player_id
            if requested_id and requested_id != caller_spec.id:
                return {'success': False, 'message': 'Unauthorized: socket does not match spectator identity'}
            spec_state = room.game_state.get_spectator_state()
            spec_state['activity_log'] = room.activity_log[::-1]
            spec_summary = room.get_spectators_summary()
            spec_state['spectator_count'] = spec_summary['spectator_count']
            spec_state['spectators'] = spec_summary['spectators']
            emit('spectator_state', spec_state, to=request.sid)
            return {'success': True, 'is_spectator': True}

        # Strict player ownership: requesting socket must own player_id
        player = _get_authenticated_player(room, player_id)
        if not player:
            return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

        p_state = room.game_state.get_state_for_player(player.id)
        p_state['activity_log'] = room.activity_log[::-1]
        spec_summary = room.get_spectators_summary()
        p_state['spectator_count'] = spec_summary['spectator_count']
        p_state['spectators'] = spec_summary['spectators']
        emit('game_state', p_state, to=request.sid)
        return {'success': True}

    # ── Stage 3: Independent Pre-Match, In-Match, and Post-Match Chat ──

    @socketio.on('send_lobby_chat')
    def handle_send_lobby_chat(data):
        try:
            data = data or {}
            room_code    = (data.get('roomCode') or '').strip().upper()
            sender_id    = data.get('playerId') or data.get('spectatorId') or data.get('senderId')
            message_text = (data.get('message') or '').strip()

            if not message_text:
                return {'success': False, 'message': 'Message cannot be empty'}
            if len(message_text) > 150:
                message_text = message_text[:150]

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}

            # Strict server-side lobby enforcement: pre-match lobby chat disabled once match starts
            if room.status != 'waiting':
                return {'success': False, 'message': 'Chat is only available in the lobby'}

            auth_player = _get_authenticated_player(room, sender_id)
            auth_spec   = _get_authenticated_spectator(room, sender_id)
            if not auth_player and not auth_spec:
                return {'success': False, 'message': 'Unauthorized: socket does not match sender identity'}
            verified_sender_id = auth_player.id if auth_player else auth_spec.id

            chat_msg = room.add_stage_chat_message(
                stage='pre_match',
                sender_id=verified_sender_id,
                text=message_text,
                max_length=150,
                truncate=True,
            )

            emit('lobby_chat_message', chat_msg, room=room.code)
            emit('chat_message', chat_msg, room=room.code)
            return {'success': True, 'message': chat_msg}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('send_chat_message')
    def handle_send_chat_message(data):
        try:
            data = data or {}
            room_code    = (data.get('roomCode') or '').strip().upper()
            sender_id    = data.get('senderId') or data.get('playerId') or data.get('spectatorId')
            stage        = (data.get('stage') or '').strip()
            message_text = data.get('message')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}

            auth_player = _get_authenticated_player(room, sender_id)
            auth_spec   = _get_authenticated_spectator(room, sender_id)
            if not auth_player and not auth_spec:
                return {'success': False, 'message': 'Unauthorized: socket does not match sender identity'}
            verified_sender_id = auth_player.id if auth_player else auth_spec.id

            chat_msg = room.add_stage_chat_message(
                stage=stage,
                sender_id=verified_sender_id,
                text=message_text,
                max_length=200,
                truncate=False,
            )

            emit('chat_message', chat_msg, room=room.code)
            if stage == 'pre_match':
                emit('lobby_chat_message', chat_msg, room=room.code)
            return {'success': True, 'message': chat_msg}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ── Stage 4: Live Spectator Mode ──

    @socketio.on('join_as_spectator')
    def handle_join_as_spectator(data):
        try:
            room_code      = (data.get('roomCode') or '').strip().upper()
            spectator_name = (data.get('spectatorName') or data.get('playerName') or 'Spectator').strip()

            room, spec = room_manager.join_as_spectator(
                room_code=room_code,
                spectator_name=spectator_name,
                sid=request.sid,
            )
            join_room(room.code)

            spec_summary = room.get_spectators_summary()
            emit('spectators_updated', spec_summary, room=room.code)

            if room.status == 'waiting':
                emit('room_updated', room.to_lobby_summary(), room=room.code)

            spec_state = None
            if room.status == 'playing' and room.game_state:
                spec_state = room.game_state.get_spectator_state()
                spec_state['activity_log'] = room.activity_log[::-1]
                spec_state['spectator_count'] = spec_summary['spectator_count']
                spec_state['spectators'] = spec_summary['spectators']
                emit('spectator_state', spec_state, to=request.sid)

            return {
                'success':         True,
                'room_code':       room.code,
                'spectator_id':    spec.id,
                'spectator_name':  spec.name,
                'room_status':     room.status,
                'match_id':        room.match_id,
                'room':            room.to_lobby_summary(),
                'spectators':      spec_summary['spectators'],
                'spectator_count': spec_summary['spectator_count'],
                'spectator_state': spec_state,
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('leave_spectator')
    def handle_leave_spectator(data):
        try:
            data = data or {}
            room_code    = (data.get('roomCode') or '').strip().upper()
            spectator_id = data.get('spectatorId')

            room = room_manager.get_room(room_code)
            if not room:
                leave_room(room_code)
                return {'success': True}

            spec = _get_authenticated_spectator(room, spectator_id)
            if not spec:
                return {'success': False, 'message': 'Unauthorized: socket does not match spectator identity'}

            leave_room(room_code)
            room, spec = room_manager.leave_spectator(room_code, spec.id)
            if room and spec:
                emit('spectators_updated', room.get_spectators_summary(), room=room.code)
                if room.status == 'waiting':
                    emit('room_updated', room.to_lobby_summary(), room=room.code)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('get_spectator_list')
    def handle_get_spectator_list(data):
        data = data or {}
        room_code = (data.get('roomCode') or '').strip().upper()
        room = room_manager.get_room(room_code)
        if not room:
            return {'success': False, 'message': 'Room not found'}
        return {'success': True, **room.get_spectators_summary()}

    @socketio.on('send_reaction')
    def handle_send_reaction(data):
        try:
            data = data or {}
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            emoji     = (data.get('emoji') or '').strip()
            allowed_emojis = {'😂', '❤️', '👍', '😮', '😎', '👏', '🔥', '😢'}
            if not emoji or emoji not in allowed_emojis:
                return {'success': False, 'message': 'Invalid reaction emoji'}

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
                return {'success': False, 'message': 'Spectators cannot send player reactions'}
            player = _get_authenticated_player(room, player_id)
            if not player:
                return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

            # Broadcast reaction to all connected players in the room
            emit('player_reaction', {
                'player_id':   player.id,
                'player_name': player.name,
                'emoji':       emoji,
            }, room=room.code)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('get_public_rooms')
    def handle_get_public_rooms():
        return room_manager.get_public_rooms()

    @socketio.on('reconnect_session')
    def handle_reconnect(data):
        try:
            token = data.get('reconnectToken')
            room_code = data.get('roomCode')
            player_id = data.get('playerId')
            if not token:
                return {'success': False, 'message': 'Token missing'}

            room, player = room_manager.reconnect_player(
                token,
                request.sid,
                room_code=room_code,
                player_id=player_id
            )
            if not room or not player:
                return {'success': False, 'message': 'Invalid session or room closed'}

            print(f"[SocketIO] Reconnected: code={room.code}, player={player.name}, sid={request.sid}")

            player.departure_notified = False
            join_room(room.code)

            message = f"{player.name} reconnected."
            notice  = f"🟢 {player.name} reconnected."

            act = room.add_activity('reconnect', message, player_name=player.name, icon='🟢')

            # Instant reconnected notification (5s display)
            emit('player_departure', {
                'player_id': player.id,
                'name':      player.name,
                'reason':    'reconnected',
                'message':   notice,
                'status':    'connected',
                'duration':  5000,
            }, room=room.code)

            emit('player_status_change', {
                'player_id': player.id,
                'name':      player.name,
                'connected': True,
                'status':    'connected',
            }, room=room.code)

            emit('activity_logged', act, room=room.code)

            # Return room & game info
            if room.status == 'playing' and room.game_state:
                personalized_state = room.game_state.get_state_for_player(player.id)
                personalized_state['activity_log'] = room.activity_log[::-1]
                emit('game_state', personalized_state, to=request.sid)
                _broadcast_personalized_state(room)
            elif room.status == 'finished':
                emit('post_match_status', room.get_post_match_status(), room=room.code)

            res_data = {
                'success':     True,
                'room_code':   room.code,
                'player_id':   player.id,
                'player_name': player.name,
                'is_host':     player.is_host,
                'room_status': room.status,
                'room':        room.to_lobby_summary(),
            }
            if room.status == 'finished':
                kazhudhai = next((r for r in (room.game_state.rankings if room.game_state else []) if r.get('is_kazhudhai')), None)
                res_data['post_match_status'] = room.get_post_match_status()
                res_data['game_over'] = {
                    'rankings':          room.game_state.rankings if room.game_state else [],
                    'kazhudhai_name':    kazhudhai['name'] if kazhudhai else 'Unknown',
                    'room_code':         room.code,
                    'match_id':          room.match_id,
                    'deck_count':        room.last_match_deck_count,
                    'post_match_status': res_data['post_match_status'],
                }
            return res_data
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ── Match-Only WebRTC Voice Chat Signaling ──

    @socketio.on('get_ice_servers')
    def handle_get_ice_servers():
        ice_servers = [
            {'urls': [
                'stun:stun.l.google.com:19302',
                'stun:stun1.l.google.com:19302',
            ]}
        ]
        turn_url = os.environ.get('TURN_SERVER_URL')
        if turn_url:
            urls = [u.strip() for u in turn_url.split(',') if u.strip()]
            turn_cfg = {'urls': urls if len(urls) > 1 else (urls[0] if urls else turn_url.strip())}
            turn_user = os.environ.get('TURN_USERNAME')
            turn_cred = os.environ.get('TURN_CREDENTIAL')
            if turn_user:
                turn_cfg['username'] = turn_user
            if turn_cred:
                turn_cfg['credential'] = turn_cred
            ice_servers.append(turn_cfg)

        return {'success': True, 'iceServers': ice_servers}

    @socketio.on('voice_join')
    def handle_voice_join(data):
        data = data or {}
        room_code = (data.get('roomCode') or '').strip().upper()
        player_id = data.get('playerId')
        room = room_manager.get_room(room_code)
        if not room or room.status != 'playing':
            return {'success': False, 'message': 'Voice chat is only available during an active match'}
        if _is_spectator_socket(room) or (player_id and player_id in room.spectators):
            return {'success': False, 'message': 'Spectators cannot use voice chat'}
        player = _get_authenticated_player(room, player_id)
        if not player:
            return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

        active_peers = []
        notify_sids = []
        with room.play_lock:
            voice_peers = _ensure_voice_peers_locked(room)

            for pid in list(voice_peers):
                if pid == player.id:
                    continue
                p = room.players.get(pid)
                if p and p.connected and p.status == 'connected':
                    active_peers.append({'peerId': p.id, 'name': p.name})
                    if p.sid:
                        notify_sids.append(p.sid)

            voice_peers.add(player.id)

        for sid in notify_sids:
            emit('voice_peer_joined', {
                'peerId': player.id,
                'name':   player.name,
            }, to=sid)

        return {'success': True, 'peers': active_peers}

    @socketio.on('voice_signal')
    def handle_voice_signal(data):
        data = data or {}
        room_code      = (data.get('roomCode') or '').strip().upper()
        target_peer_id = data.get('targetPeerId')
        signal         = data.get('signal')
        from_peer_id   = data.get('playerId')

        room = room_manager.get_room(room_code)
        if not room or room.status != 'playing':
            return {'success': False, 'message': 'Voice chat available only during match'}
        if _is_spectator_socket(room) or (from_peer_id and from_peer_id in room.spectators):
            return {'success': False, 'message': 'Spectators cannot use voice chat'}
        sender_player = _get_authenticated_player(room, from_peer_id)
        if not sender_player:
            return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}

        target_player = room.players.get(target_peer_id)
        if not target_player or not target_player.sid:
            return {'success': False, 'message': 'Target peer not connected'}

        emit('voice_signal', {
            'fromPeerId': sender_player.id,
            'signal':     signal,
        }, to=target_player.sid)
        return {'success': True}

    @socketio.on('voice_leave')
    def handle_voice_leave(data):
        data = data or {}
        room_code = (data.get('roomCode') or '').strip().upper()
        player_id = data.get('playerId')
        room = room_manager.get_room(room_code)
        if not room:
            return {'success': True}
        player = _get_authenticated_player(room, player_id)
        if not player:
            return {'success': False, 'message': 'Unauthorized: socket does not match player identity'}
        _remove_voice_peer_and_notify(room, player.id)
        return {'success': True}

    def _broadcast_personalized_state(room):
        """
        Send strictly personalized state to each player and strictly sanitized
        public-only state to each connected spectator:
        - Players receive only their own cards in 'my_hand' (opponents' hands omitted).
        - Spectators receive 'spectator_state' with ZERO hidden hands, card IDs, or card faces.
        - Synchronize activity log (newest first) and live spectator count/list.
        """
        if not room.game_state:
            return

        activity_history = room.activity_log[::-1]
        spec_summary = room.get_spectators_summary()

        for p in room.players.values():
            if p.sid and p.connected:
                p_state = room.game_state.get_state_for_player(p.id)
                p_state['activity_log'] = activity_history
                p_state['spectator_count'] = spec_summary['spectator_count']
                p_state['spectators'] = spec_summary['spectators']
                socketio.emit('game_state', p_state, to=p.sid)

        if room.spectators:
            base_spec_state = room.game_state.get_spectator_state()
            base_spec_state['activity_log'] = activity_history
            base_spec_state['spectator_count'] = spec_summary['spectator_count']
            base_spec_state['spectators'] = spec_summary['spectators']
            for s in list(room.spectators.values()):
                if s.sid and s.connected:
                    socketio.emit('spectator_state', base_spec_state, to=s.sid)
