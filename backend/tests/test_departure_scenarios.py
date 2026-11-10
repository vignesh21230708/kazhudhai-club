"""
KAZHUDHAI CLUB — test_departure_scenarios.py
Automated end-to-end integration test for the 10 Departure & Activity Scenarios:
1. Player intentionally leaves using the Exit button.
2. Player closes browser unexpectedly.
3. Player loses internet connection.
4. Player reconnects to the same room.
5. Verify that all remaining players receive correct notifications.
6. Verify player status indicators update correctly.
7. Click the small 🕘 history icon and check activity records.
8. Verify that new events appear automatically (newest first).
9. Check that history popup works correctly on laptop and mobile.
10. Ensure existing card gameplay and multiplayer synchronization still work.
"""
import sys
import os
import unittest
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask
from flask_socketio import SocketIO
from game_engine.room_manager import RoomManager
from sockets.game_events import register_socket_events


class TestDepartureScenarios(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'kazhudhai_scenario_secret'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_socket_events(self.socketio)

    def test_scenario_1_and_5_intentional_leave(self):
        """Scenario 1 & 5: Player intentionally leaves with Exit button; remaining player gets 5s notification."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        # 1. Laptop creates private room
        res_create = laptop.emit('create_room', {
            'playerName': 'LaptopPlayer',
            'isPrivate': True,
            'maxPlayers': 2,
            'deckCount': 1
        }, callback=True)
        self.assertTrue(res_create['success'])
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        # 2. Mobile joins the room
        res_join = mobile.emit('join_room', {
            'playerName': 'MobilePlayer',
            'roomCode': room_code
        }, callback=True)
        self.assertTrue(res_join['success'])
        mobile_id = res_join['player_id']

        # 3. Laptop starts game
        res_start = laptop.emit('start_game', {
            'roomCode': room_code,
            'playerId': laptop_id
        }, callback=True)
        self.assertTrue(res_start['success'])

        # Clear event queues
        laptop.get_received()
        mobile.get_received()

        # 4. Mobile clicks Exit -> calls leave_room with reason: 'left'
        res_leave = mobile.emit('leave_room', {
            'roomCode': room_code,
            'playerId': mobile_id,
            'reason': 'left'
        }, callback=True)
        self.assertTrue(res_leave['success'])

        # 5. Verify Laptop received intentional leave notification
        events = laptop.get_received()
        departure_msgs = [e for e in events if e['name'] == 'player_departure']
        status_msgs = [e for e in events if e['name'] == 'player_status_change']
        act_msgs = [e for e in events if e['name'] == 'activity_logged']

        self.assertEqual(len(departure_msgs), 1, "Must receive exactly 1 departure notification")
        dep = departure_msgs[0]['args'][0]
        self.assertEqual(dep['reason'], 'left')
        self.assertEqual(dep['duration'], 5000, "Duration must be approximately 5000ms")
        self.assertEqual(dep['message'], "🔴 MobilePlayer left the game.")
        self.assertEqual(dep['status'], 'left')

        # 6. Verify status indicator updated to 'left'
        self.assertEqual(len(status_msgs), 1)
        self.assertEqual(status_msgs[0]['args'][0]['status'], 'left')
        self.assertFalse(status_msgs[0]['args'][0]['connected'])

        # Disconnecting mobile socket must NOT emit a duplicate notification
        mobile.disconnect()
        dup_events = [e for e in laptop.get_received() if e['name'] == 'player_departure']
        self.assertEqual(len(dup_events), 0, "No duplicate notification on subsequent disconnect")

        laptop.disconnect()

    def test_scenario_2_unexpected_browser_close(self):
        """Scenario 2 & 5: Player closes browser unexpectedly; remaining player gets 'disconnected' message."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        res_create = laptop.emit('create_room', {'playerName': 'LaptopPlayer', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        res_join = mobile.emit('join_room', {'playerName': 'MobilePlayer', 'roomCode': room_code}, callback=True)
        laptop.emit('start_game', {'roomCode': room_code, 'playerId': laptop_id}, callback=True)

        laptop.get_received()
        mobile.get_received()

        # Mobile browser abruptly closes
        mobile.disconnect()

        events = laptop.get_received()
        departure_msgs = [e for e in events if e['name'] == 'player_departure']
        status_msgs = [e for e in events if e['name'] == 'player_status_change']
        act_msgs = [e for e in events if e['name'] == 'activity_logged']

        self.assertEqual(len(departure_msgs), 1)
        dep = departure_msgs[0]['args'][0]
        self.assertEqual(dep['reason'], 'disconnected')
        self.assertEqual(dep['duration'], 5000)
        self.assertEqual(dep['message'], "🔴 MobilePlayer disconnected.")
        self.assertEqual(dep['status'], 'disconnected')

        self.assertEqual(status_msgs[0]['args'][0]['status'], 'disconnected')
        self.assertEqual(act_msgs[0]['args'][0]['message'], "MobilePlayer disconnected.")

        laptop.disconnect()

    def test_scenario_3_connection_lost(self):
        """Scenario 3 & 6: Player loses network; remaining player gets 'lost connection' with 🟡 reconnecting status."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        res_create = laptop.emit('create_room', {'playerName': 'LaptopPlayer', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        res_join = mobile.emit('join_room', {'playerName': 'MobilePlayer', 'roomCode': room_code}, callback=True)
        mobile_id = res_join['player_id']
        laptop.emit('start_game', {'roomCode': room_code, 'playerId': laptop_id}, callback=True)

        laptop.get_received()
        mobile.get_received()

        # Mobile detects network drop
        mobile.emit('client_connection_lost', {'roomCode': room_code, 'playerId': mobile_id})

        events = laptop.get_received()
        departure_msgs = [e for e in events if e['name'] == 'player_departure']
        status_msgs = [e for e in events if e['name'] == 'player_status_change']

        self.assertEqual(len(departure_msgs), 1)
        dep = departure_msgs[0]['args'][0]
        self.assertEqual(dep['reason'], 'connection_lost')
        self.assertEqual(dep['duration'], 5000)
        self.assertEqual(dep['message'], "🟡 MobilePlayer lost connection.")
        self.assertEqual(dep['status'], 'reconnecting')

        self.assertEqual(status_msgs[0]['args'][0]['status'], 'reconnecting')

        laptop.disconnect()
        mobile.disconnect()

    def test_scenario_4_player_reconnects(self):
        """Scenario 4: Player reconnects to the same room; status becomes 🟢 connected, game state restored."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        res_create = laptop.emit('create_room', {'playerName': 'LaptopPlayer', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        res_join = mobile.emit('join_room', {'playerName': 'MobilePlayer', 'roomCode': room_code}, callback=True)
        mobile_id = res_join['player_id']
        mobile_token = res_join['reconnect_token']

        laptop.emit('start_game', {'roomCode': room_code, 'playerId': laptop_id}, callback=True)

        # Mobile loses connection
        mobile.disconnect()
        laptop.get_received()

        # Mobile reconnects using token
        new_mobile = self.socketio.test_client(self.app)
        res_recon = new_mobile.emit('reconnect_session', {'reconnectToken': mobile_token}, callback=True)
        self.assertTrue(res_recon['success'])
        self.assertEqual(res_recon['player_id'], mobile_id)
        self.assertEqual(res_recon['room_code'], room_code)
        self.assertEqual(res_recon['room_status'], 'playing')

        # Laptop receives reconnection alert
        laptop_events = laptop.get_received()
        dep_msgs = [e for e in laptop_events if e['name'] == 'player_departure']
        status_msgs = [e for e in laptop_events if e['name'] == 'player_status_change']
        act_msgs = [e for e in laptop_events if e['name'] == 'activity_logged']

        self.assertTrue(len(dep_msgs) >= 1)
        self.assertEqual(dep_msgs[-1]['args'][0]['reason'], 'reconnected')
        self.assertEqual(dep_msgs[-1]['args'][0]['message'], "🟢 MobilePlayer reconnected.")
        self.assertEqual(dep_msgs[-1]['args'][0]['duration'], 5000)

        self.assertEqual(status_msgs[-1]['args'][0]['status'], 'connected')
        self.assertTrue(status_msgs[-1]['args'][0]['connected'])

        self.assertIn("MobilePlayer reconnected.", act_msgs[-1]['args'][0]['message'])

        # New mobile client received restored personalized game_state
        mobile_events = new_mobile.get_received()
        state_msgs = [e for e in mobile_events if e['name'] == 'game_state']
        self.assertTrue(len(state_msgs) >= 1)
        self.assertIn('my_hand', state_msgs[-1]['args'][0])

        laptop.disconnect()
        new_mobile.disconnect()

    def test_scenario_7_and_8_history_records_and_automatic_updates(self):
        """Scenario 7 & 8: 🕘 History icon displays chronological activities, newest first, real-time sync."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        res_create = laptop.emit('create_room', {'playerName': 'LaptopPlayer', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        res_join = mobile.emit('join_room', {'playerName': 'MobilePlayer', 'roomCode': room_code}, callback=True)
        mobile_id = res_join['player_id']

        # Start game
        laptop.emit('start_game', {'roomCode': room_code, 'playerId': laptop_id}, callback=True)

        laptop_events = laptop.get_received()
        # Find personalized state sent to laptop
        state_events = [e for e in laptop_events if e['name'] == 'game_state']
        self.assertTrue(len(state_events) >= 1)
        state = state_events[-1]['args'][0]

        # Activity log in state is newest first
        acts = state.get('activity_log', [])
        self.assertTrue(len(acts) >= 3, "Activity log should contain joins and game started")

        # Top item is newest: "Game started."
        self.assertEqual(acts[0]['message'], "Game started.")
        self.assertEqual(acts[0]['icon'], '🚀')
        self.assertIn('timestamp', acts[0])

        # Laptop plays a card
        starter_id = state['current_player_id']
        active_client = laptop if starter_id == laptop_id else mobile
        starter_hand = state['my_hand'] if starter_id == laptop_id else mobile.get_received()[-1]['args'][0]['my_hand']
        starter_card = starter_hand[0]

        laptop.get_received()
        mobile.get_received()

        res_play = active_client.emit('play_card', {
            'roomCode': room_code,
            'playerId': starter_id,
            'cardId': starter_card['id']
        }, callback=True)
        self.assertTrue(res_play['success'])

        # Check real-time activity_logged was pushed automatically
        laptop_after_play = laptop.get_received()
        play_acts = [e for e in laptop_after_play if e['name'] == 'activity_logged']
        self.assertTrue(len(play_acts) >= 1, "New card play event must appear automatically")
        card_msg = play_acts[-1]['args'][0]['message']
        self.assertTrue("played" in card_msg or "Attack" in card_msg)

        laptop.disconnect()
        mobile.disconnect()

    def test_scenario_9_ui_markup_and_responsive_css(self):
        """Scenario 9: Verify Game Activity UI removed and Multiplayer Emoji Reactions UI integrated."""
        # 1. Read index.html
        with open('frontend/index.html', 'r', encoding='utf-8') as f:
            html = f.read()

        # In-game table history button and drawer removed
        self.assertNotIn('id="btn-table-history"', html, "Table felt history button must be removed")
        self.assertNotIn('id="activity-drawer"', html, "Activity popup panel must be removed")
        self.assertNotIn('id="activity-backdrop"', html, "Activity backdrop must be removed")

        # Emoji reaction button and picker panel present
        self.assertIn('id="btn-table-emoji"', html, "Table felt must have emoji reaction button")
        self.assertIn('id="emoji-picker-panel"', html, "Emoji picker panel must exist")
        self.assertIn('class="emoji-choice-btn"', html)

        # 2. Read table.css
        with open('frontend/css/table.css', 'r', encoding='utf-8') as f:
            table_css = f.read()

        self.assertIn('.table-emoji-btn', table_css)
        self.assertIn('.emoji-picker-panel', table_css)
        self.assertIn('.player-reaction-bubble', table_css)
        self.assertIn('top: 10px', table_css)
        self.assertIn('right: 12px', table_css)

        # 3. Read responsive.css
        with open('frontend/css/responsive.css', 'r', encoding='utf-8') as f:
            resp_css = f.read()

        self.assertIn('.table-emoji-btn', resp_css)
        self.assertIn('.emoji-picker-panel', resp_css)

        # 4. Read main.js
        with open('frontend/js/main.js', 'r', encoding='utf-8') as f:
            main_js = f.read()

        self.assertIn('sendReaction', main_js)
        self.assertIn('handlePlayerReaction', main_js)

    def test_scenario_10_gameplay_synchronization_and_privacy(self):
        """Scenario 10: Gameplay synchronization & zero card leakage."""
        laptop = self.socketio.test_client(self.app)
        mobile = self.socketio.test_client(self.app)

        res_create = laptop.emit('create_room', {'playerName': 'LaptopPlayer', 'maxPlayers': 2, 'deckCount': 1}, callback=True)
        room_code = res_create['room_code']
        laptop_id = res_create['player_id']

        res_join = mobile.emit('join_room', {'playerName': 'MobilePlayer', 'roomCode': room_code}, callback=True)
        mobile_id = res_join['player_id']

        laptop.emit('start_game', {'roomCode': room_code, 'playerId': laptop_id}, callback=True)

        # Check laptop's personalized state
        laptop_state = [e for e in laptop.get_received() if e['name'] == 'game_state'][-1]['args'][0]
        # Check mobile's personalized state
        mobile_state = [e for e in mobile.get_received() if e['name'] == 'game_state'][-1]['args'][0]

        # Privacy check: Laptop receives Laptop hand, NEVER Mobile hand
        self.assertIn('my_hand', laptop_state)
        self.assertIn('players', laptop_state)
        laptop_opponents = [p for p in laptop_state['players'] if p['id'] != laptop_id]
        self.assertEqual(len(laptop_opponents), 1)
        for opp in laptop_opponents:
            self.assertNotIn('hand', opp, "Opponents in laptop state must NOT expose hidden cards")
            self.assertIn('card_count', opp)
            self.assertIn('connection_status', opp)
            self.assertEqual(opp['connection_status'], 'connected')

        # Privacy check: Mobile receives Mobile hand, NEVER Laptop hand
        self.assertIn('my_hand', mobile_state)
        mobile_opponents = [p for p in mobile_state['players'] if p['id'] != mobile_id]
        self.assertEqual(len(mobile_opponents), 1)
        for opp in mobile_opponents:
            self.assertNotIn('hand', opp, "Opponents in mobile state must NOT expose hidden cards")
            self.assertIn('card_count', opp)
            self.assertIn('connection_status', opp)
            self.assertEqual(opp['connection_status'], 'connected')

        laptop.disconnect()
        mobile.disconnect()


if __name__ == '__main__':
    unittest.main()
