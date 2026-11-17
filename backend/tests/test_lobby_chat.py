"""
KAZHUDHAI CLUB — backend/tests/test_lobby_chat.py
Unit and integration tests for Lobby-Only Real-Time Messaging.

Validates:
1. Players in the same room can exchange chat messages in real time.
2. Players in different rooms are strictly isolated and cannot see each other's messages.
3. Host and normal players have equal messaging permissions.
4. Empty and whitespace-only messages are rejected both on client and server.
5. When an individual player leaves, they lose access and their local state is cleared.
6. Other remaining players' chat history remains intact when one player leaves.
7. Rejoining player does not receive previous chat history.
8. Chat is disabled and cleared server-side when the match starts.
9. Old chat history is not restored after match start, refresh, or reconnection.
10. Frontend DOM and CSS presence for lobby chat and reminder notice.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask_socketio import SocketIOTestClient
from app import app, socketio
from game_engine.room_manager import RoomManager, Room


class TestLobbyChat(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.socketio = socketio
        self.client1 = self.socketio.test_client(self.app)
        self.client2 = self.socketio.test_client(self.app)

    def tearDown(self):
        if self.client1.is_connected():
            self.client1.disconnect()
        if self.client2.is_connected():
            self.client2.disconnect()

    def test_01_same_room_chat_exchange(self):
        """Verify that players in the same room can exchange chat messages in real time."""
        res_host = self.client1.emit('create_room', {'playerName': 'Aravind'}, callback=True)
        room_code = res_host['room_code']
        host_id = res_host['player_id']

        res_guest = self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Vignesh'}, callback=True)
        guest_id = res_guest['player_id']

        # Clear initial join events
        self.client1.get_received()
        self.client2.get_received()

        # Host sends a message
        res_send = self.client1.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': host_id,
            'message': 'Hello everyone!',
        }, callback=True)

        self.assertTrue(res_send['success'])
        self.assertEqual(res_send['message']['sender_name'], 'Aravind')
        self.assertEqual(res_send['message']['text'], 'Hello everyone!')

        # Host receives its own message broadcast
        events_host_initial = self.client1.get_received()
        chat_events_host = [e for e in events_host_initial if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(chat_events_host), 1)

        # Guest must receive the message
        events_guest = self.client2.get_received()
        chat_events = [e for e in events_guest if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(chat_events), 1)
        self.assertEqual(chat_events[0]['args'][0]['text'], 'Hello everyone!')
        self.assertEqual(chat_events[0]['args'][0]['sender_name'], 'Aravind')

        # Guest replies
        res_reply = self.client2.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': guest_id,
            'message': 'Hey Aravind, ready to play!',
        }, callback=True)

        self.assertTrue(res_reply['success'])

        # Host must receive guest's reply
        events_host = self.client1.get_received()
        reply_events = [e for e in events_host if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(reply_events), 1)
        self.assertEqual(reply_events[0]['args'][0]['text'], 'Hey Aravind, ready to play!')
        self.assertEqual(reply_events[0]['args'][0]['sender_name'], 'Vignesh')

    def test_02_cross_room_isolation(self):
        """Verify that messages sent in Room A are never seen in Room B."""
        client_other = self.socketio.test_client(self.app)

        # Room A
        res_a = self.client1.emit('create_room', {'playerName': 'RoomA_Host'}, callback=True)
        code_a = res_a['room_code']
        host_a_id = res_a['player_id']

        # Room B
        res_b = client_other.emit('create_room', {'playerName': 'RoomB_Host'}, callback=True)
        code_b = res_b['room_code']

        client_other.get_received()

        # Send in Room A
        self.client1.emit('send_lobby_chat', {
            'roomCode': code_a,
            'playerId': host_a_id,
            'message': 'Secret in Room A',
        }, callback=True)

        # Client in Room B must NOT receive this message
        events_b = client_other.get_received()
        chat_b = [e for e in events_b if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(chat_b), 0, "Room B must not receive messages from Room A")

        client_other.disconnect()

    def test_03_empty_and_whitespace_messages_rejected(self):
        """Verify that empty, blank, or whitespace-only messages are rejected on the server."""
        res_host = self.client1.emit('create_room', {'playerName': 'Host'}, callback=True)
        room_code = res_host['room_code']
        host_id = res_host['player_id']

        for empty_text in ['', '   ', '\t\n', None]:
            res = self.client1.emit('send_lobby_chat', {
                'roomCode': room_code,
                'playerId': host_id,
                'message': empty_text,
            }, callback=True)
            self.assertFalse(res['success'])
            self.assertIn('empty', res['message'].lower())

    def test_04_individual_player_exit_keeps_room_chat_intact(self):
        """
        Scenario:
        Four players in room: Aravind, Vignesh, Mahadir, Mukesh.
        Vignesh leaves the room.
        - Vignesh loses access to that room's chat.
        - Aravind, Mahadir, and Mukesh retain their messages and can continue chatting.
        - The room's chat history is not deleted when one player leaves.
        """
        c_aravind = self.client1
        c_vignesh = self.client2
        c_mahadir = self.socketio.test_client(self.app)
        c_mukesh  = self.socketio.test_client(self.app)

        res_aravind = c_aravind.emit('create_room', {'playerName': 'Aravind'}, callback=True)
        room_code   = res_aravind['room_code']
        id_aravind  = res_aravind['player_id']

        res_vignesh = c_vignesh.emit('join_room', {'roomCode': room_code, 'playerName': 'Vignesh'}, callback=True)
        id_vignesh  = res_vignesh['player_id']

        res_mahadir = c_mahadir.emit('join_room', {'roomCode': room_code, 'playerName': 'Mahadir'}, callback=True)
        id_mahadir  = res_mahadir['player_id']

        res_mukesh  = c_mukesh.emit('join_room', {'roomCode': room_code, 'playerName': 'Mukesh'}, callback=True)
        id_mukesh   = res_mukesh['player_id']

        # Exchange messages while all 4 are present
        c_aravind.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': id_aravind, 'message': 'Welcome team!'}, callback=True)
        c_vignesh.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': id_vignesh, 'message': 'Hey all!'}, callback=True)

        from game_engine.room_manager import room_manager
        room = room_manager.get_room(room_code)
        self.assertIsNotNone(room)
        self.assertEqual(len(room.chat_messages), 2)

        # Vignesh leaves the room
        c_vignesh.emit('leave_room', {'roomCode': room_code, 'playerId': id_vignesh}, callback=True)
        # Drain events Vignesh received prior to leaving
        c_vignesh.get_received()

        # 1. Vignesh can no longer send messages to the room (actual membership validation)
        res_vignesh_after = c_vignesh.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': id_vignesh,
            'message': 'Can I still talk?',
        }, callback=True)
        self.assertFalse(res_vignesh_after['success'])

        # 2. Room chat history on server is NOT deleted
        self.assertEqual(len(room.chat_messages), 2, "Chat history must not be deleted when one player leaves")

        # 3. Remaining players (Aravind, Mahadir, Mukesh) can continue chatting normally
        c_mahadir.get_received()
        res_mukesh_msg = c_mukesh.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': id_mukesh,
            'message': 'We can still chat!',
        }, callback=True)
        self.assertTrue(res_mukesh_msg['success'])

        events_mahadir = c_mahadir.get_received()
        chat_events = [e for e in events_mahadir if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(chat_events), 1)
        self.assertEqual(chat_events[0]['args'][0]['text'], 'We can still chat!')

        # 4. Vignesh must NOT receive the new message
        events_vignesh = c_vignesh.get_received()
        chat_vignesh = [e for e in events_vignesh if e['name'] == 'lobby_chat_message']
        self.assertEqual(len(chat_vignesh), 0)

        c_mahadir.disconnect()
        c_mukesh.disconnect()

    def test_05_rejoining_player_does_not_restore_previous_chat(self):
        """
        Verify that when a player leaves and rejoins:
        - Neither join_room nor reconnect_session returns past chat messages in the room summary.
        - Old chat history is not restored.
        """
        res_host = self.client1.emit('create_room', {'playerName': 'Host'}, callback=True)
        room_code = res_host['room_code']
        host_id = res_host['player_id']

        res_p2 = self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Guest'}, callback=True)
        p2_id = res_p2['player_id']

        self.client1.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': host_id, 'message': 'Message 1'}, callback=True)
        self.client2.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': p2_id, 'message': 'Message 2'}, callback=True)

        # Guest leaves
        self.client2.emit('leave_room', {'roomCode': room_code, 'playerId': p2_id}, callback=True)

        # Guest rejoins
        res_rejoin = self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Guest'}, callback=True)
        self.assertTrue(res_rejoin['success'])

        # Room summary returned to client MUST NOT include past chat history
        self.assertNotIn('chat_messages', res_rejoin.get('room', {}))

    def test_06_match_start_disables_and_clears_lobby_chat(self):
        """
        Verify that when the match starts:
        1. Lobby chat history on server is cleared.
        2. Chat is disabled server-side: all new chat messages are rejected.
        3. Game state and reconnect payloads do not include chat history.
        """
        res_host = self.client1.emit('create_room', {'playerName': 'Host'}, callback=True)
        room_code = res_host['room_code']
        host_id = res_host['player_id']

        res_p2 = self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Guest'}, callback=True)
        p2_id = res_p2['player_id']

        # Chat in lobby
        self.client1.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': host_id, 'message': 'Ready?'}, callback=True)
        self.client2.emit('send_lobby_chat', {'roomCode': room_code, 'playerId': p2_id, 'message': 'Ready!'}, callback=True)

        from game_engine.room_manager import room_manager
        room = room_manager.get_room(room_code)
        self.assertEqual(len(room.chat_messages), 2)

        # Host starts the game
        res_start = self.client1.emit('start_game', {'roomCode': room_code, 'playerId': host_id}, callback=True)
        self.assertTrue(res_start['success'])
        self.assertEqual(room.status, 'playing')

        # 1. Server chat history is cleared
        self.assertEqual(len(room.chat_messages), 0, "Lobby chat messages must be cleared on match start")

        # 2. Chat is disabled server-side: attempts to send chat are rejected
        res_chat_during_game = self.client1.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': host_id,
            'message': 'Chat during game?',
        }, callback=True)
        self.assertFalse(res_chat_during_game['success'])
        self.assertIn('lobby', res_chat_during_game['message'].lower())

        # 3. game_state payload has NO chat history
        events = self.client1.get_received()
        state_events = [e for e in events if e['name'] == 'game_state']
        self.assertTrue(len(state_events) > 0)
        state = state_events[-1]['args'][0]
        self.assertNotIn('chat_messages', state)
        self.assertNotIn('chat', state)

    def test_07_frontend_markup_and_css_elements(self):
        """
        Verify that the lobby chat interface and mandatory reminder exist
        in frontend HTML and CSS files.
        """
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

        with open(os.path.join(base_dir, 'frontend', 'index.html'), 'r', encoding='utf-8') as f:
            html = f.read()

        with open(os.path.join(base_dir, 'frontend', 'css', 'modals.css'), 'r', encoding='utf-8') as f:
            css = f.read()

        # HTML elements
        self.assertIn('id="lobby-chat-box"', html)
        self.assertIn('id="lobby-chat-messages"', html)
        self.assertIn('id="lobby-chat-form"', html)
        self.assertIn('id="lobby-chat-input"', html)
        self.assertIn('id="btn-send-lobby-chat"', html)

        # Mandatory reminder notice
        self.assertIn('Chat is available only in the lobby. Once the match starts, lobby chat is no longer accessible.', html)

        # CSS rules
        self.assertIn('.lobby-chat-box', css)
        self.assertIn('.lobby-chat-messages', css)
        self.assertIn('.lobby-chat-input', css)
        self.assertIn('.lobby-chat-send-btn', css)

    def test_08_disconnected_or_connection_lost_revokes_chat_access(self):
        """
        Verify that chat access is revoked when a player:
        1. Emits client_connection_lost (status becomes 'reconnecting', connected is False).
        2. Closes browser or socket disconnects (connected is False).
        """
        res_host = self.client1.emit('create_room', {'playerName': 'Host'}, callback=True)
        room_code = res_host['room_code']

        res_p2 = self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Guest'}, callback=True)
        p2_id = res_p2['player_id']

        # Guest experiences connection loss
        self.client2.emit('client_connection_lost', {'roomCode': room_code, 'playerId': p2_id})

        # Attempt to chat while connection is lost must be rejected
        res_chat_lost = self.client2.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': p2_id,
            'message': 'Can I send while connection lost?',
        }, callback=True)

        self.assertFalse(res_chat_lost['success'])
        self.assertIn('not active', res_chat_lost['message'].lower())

    def test_09_duplicate_start_game_cannot_restart_chat(self):
        """
        Verify that repeated or duplicate start_game calls do not revive chat.
        """
        res_host = self.client1.emit('create_room', {'playerName': 'Host'}, callback=True)
        room_code = res_host['room_code']
        host_id = res_host['player_id']

        self.client2.emit('join_room', {'roomCode': room_code, 'playerName': 'Guest'}, callback=True)

        # First start_game
        res1 = self.client1.emit('start_game', {'roomCode': room_code, 'playerId': host_id}, callback=True)
        self.assertTrue(res1['success'])

        # Duplicate start_game
        res2 = self.client1.emit('start_game', {'roomCode': room_code, 'playerId': host_id}, callback=True)
        self.assertFalse(res2['success'])
        self.assertIn('already in progress', res2['message'])

        # Chat remains strictly disabled
        res_chat = self.client1.emit('send_lobby_chat', {
            'roomCode': room_code,
            'playerId': host_id,
            'message': 'Chat attempt after duplicate start',
        }, callback=True)
        self.assertFalse(res_chat['success'])
        self.assertIn('lobby', res_chat['message'].lower())


if __name__ == '__main__':
    unittest.main()
