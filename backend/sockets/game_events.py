"""
KAZHUDHAI CLUB — sockets/game_events.py
SocketIO event handlers for real-time multiplayer.
Handles private/public room creation, joins, card play broadcasts,
authoritative rule execution, zero-leak state delivery,
instant leave/disconnect notifications, connection status tracking,
and real-time game activity history synchronization.
"""
from flask import request
from flask_socketio import emit, join_room, leave_room
from game_engine.room_manager import room_manager
from game_engine.deck import SUIT_SYMBOLS


def register_socket_events(socketio):

    @socketio.on('connect')
    def handle_connect():
        pass

    @socketio.on('disconnect')
    def handle_disconnect():
        room, player = room_manager.handle_disconnect(request.sid, reason='disconnected')
        if room and player:
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
        room_code = (data.get('roomCode') or '').strip().upper()
        player_id = data.get('playerId')
        room = room_manager.get_room(room_code)
        if room and player_id in room.players:
            player = room.players[player_id]
            player.status = 'reconnecting'
            player.departure_notified = True

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
            player_name = (data.get('playerName') or 'Player').strip()
            room_code   = (data.get('roomCode') or '').strip().upper()

            room, player = room_manager.join_room(
                room_code=room_code,
                player_name=player_name,
                sid=request.sid,
            )
            join_room(room.code)

            print(f"[SocketIO] Player joined: code={room.code}, player={player.name}, sid={request.sid}")

            # Log join activity
            act = room.add_activity('join', f"{player.name} joined the room.", player_name=player.name, icon='🟢')

            # Broadcast updated lobby to all players in the room
            emit('room_updated', room.to_lobby_summary(), room=room.code)
            emit('activity_logged', act, room=room.code)

            return {
                'success':         True,
                'room_code':       room.code,
                'player_id':       player.id,
                'player_name':     player.name,
                'is_host':         player.is_host,
                'reconnect_token': player.reconnect_token,
                'room':            room.to_lobby_summary(),
            }
        except Exception as e:
            print(f"[SocketIO] join_room error for code '{data.get('roomCode')}': {e}")
            return {'success': False, 'message': str(e)}

    @socketio.on('leave_room')
    def handle_leave_room(data):
        try:
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            reason    = data.get('reason') or 'left'

            leave_room(room_code)
            room = room_manager.get_room(room_code)
            player = room.players.get(player_id) if room else None

            if room and player:
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

            updated_room = room_manager.leave_room(room_code, player_id, reason=reason)
            if updated_room:
                if updated_room.status == 'waiting':
                    emit('room_updated', updated_room.to_lobby_summary(), room=room_code)
                elif updated_room.status == 'playing':
                    _broadcast_personalized_state(updated_room)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('start_game')
    def handle_start_game(data):
        try:
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')

            room = room_manager.get_room(room_code)
            if room and room.status == 'finished':
                room = room_manager.restart_game(room_code, player_id)
            else:
                room = room_manager.start_game(room_code, player_id)

            # Log game started activity
            act = room.add_activity('start', "Game started.", icon='🚀')

            # Notify room game has started
            emit('game_started', {'room_code': room.code}, room=room.code)
            emit('activity_logged', act, room=room.code)

            # Send personalized states with strict card isolation
            _broadcast_personalized_state(room)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('restart_game')
    def handle_restart_game(data):
        try:
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')

            room = room_manager.restart_game(room_code, player_id)

            act = room.add_activity('start', "Match restarted (fresh random deck shuffled).", icon='🔄')

            emit('game_started', {'room_code': room.code}, room=room.code)
            emit('activity_logged', act, room=room.code)

            _broadcast_personalized_state(room)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @socketio.on('play_card')
    def handle_play_card(data):
        try:
            room_code = (data.get('roomCode') or '').strip().upper()
            player_id = data.get('playerId')
            card_id   = data.get('cardId')

            room = room_manager.get_room(room_code)
            if not room:
                return {'success': False, 'message': 'Room not found'}
            if room.status != 'playing' or not room.game_state:
                return {'success': False, 'message': 'Game is not in progress'}

            # Authoritative game play
            res = room.game_state.play_card(player_id, card_id)
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

            # Sync personalized state to all players
            _broadcast_personalized_state(room)

            # If game is finished, broadcast game over
            if room.game_state.status == 'finished':
                room.status = 'finished'
                kazhudhai = next((r for r in room.game_state.rankings if r.get('is_kazhudhai')), None)
                k_name = kazhudhai['name'] if kazhudhai else 'Unknown'

                act_end = room.add_activity('game_over', f"👑 Game ended. {k_name} is KAZHUDHAI!", icon='👑')
                emit('activity_logged', act_end, room=room.code)

                emit('game_over', {
                    'rankings':       room.game_state.rankings,
                    'kazhudhai_name': k_name,
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
            if not token:
                return {'success': False, 'message': 'Token missing'}

            room, player = room_manager.reconnect_player(token, request.sid)
            if not room or not player:
                return {'success': False, 'message': 'Invalid session or room closed'}

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

            return {
                'success':     True,
                'room_code':   room.code,
                'player_id':   player.id,
                'player_name': player.name,
                'is_host':     player.is_host,
                'room_status': room.status,
                'room':        room.to_lobby_summary(),
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _broadcast_personalized_state(room):
        """
        Send strictly personalized state to each player:
        - Only their own cards in 'my_hand'
        - All other opponents' hands are completely omitted (only count visible)
        - Synchronize activity log (newest first)
        """
        if not room.game_state:
            return

        activity_history = room.activity_log[::-1]

        for p in room.players.values():
            if p.sid and p.connected:
                p_state = room.game_state.get_state_for_player(p.id)
                p_state['activity_log'] = activity_history
                emit('game_state', p_state, to=p.sid)
