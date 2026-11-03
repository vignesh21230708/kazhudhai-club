"""
Test suite to verify fixes for the 4 reported multiplayer gameplay bugs:
1. Card not in player's hand (turn check ordering, duplicate play handling, authoritative state resync)
2. Three-line menu event binding guard and backdrop overlay
3. Player card count property compatibility (card_count and cardCount)
4. Card responsiveness, in-flight play locking, round resolution timer cleanup
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from game_engine.game_state import GameState
from game_engine.player import Player
from app import app, socketio


class TestMultiplayerBugFixes(unittest.TestCase):

    def test_bug3_card_count_public_dict(self):
        """Verify Player.to_public_dict() provides BOTH snake_case and camelCase fields."""
        p = Player(id="p1", name="TestPlayer", is_ai=False)
        p.hand = [
            {'id': 'c1', 'suit': 'S', 'rank': 'A'},
            {'id': 'c2', 'suit': 'H', 'rank': 'K'},
        ]
        d = p.to_public_dict()

        # Bug 3: Ensure cardCount is a valid integer, not undefined
        self.assertIn("cardCount", d)
        self.assertIn("card_count", d)
        self.assertEqual(d["cardCount"], 2)
        self.assertEqual(d["card_count"], 2)

        # Also verify other camelCase aliases
        self.assertIn("isAI", d)
        self.assertEqual(d["isAI"], False)
        self.assertIn("isSafe", d)
        self.assertEqual(d["isSafe"], False)
        self.assertIn("isActive", d)

    def test_bug1_turn_validation_before_card_presence(self):
        """Verify that playing out-of-turn returns turn error rather than card not in hand."""
        game = GameState(
            game_id="test_game",
            player_configs=[
                {'id': 'p1', 'name': 'Player 1', 'is_ai': False},
                {'id': 'p2', 'name': 'Player 2', 'is_ai': False}
            ],
            num_decks=1
        )
        game.setup()
        # Determine who has the turn
        cp = game.current_player
        other_player = [p for p in game.players if p.id != cp.id][0]

        # If other player tries to play a card (even a card that exists or doesn't exist)
        with self.assertRaises(ValueError) as ctx:
            game.play_card(other_player.id, "non-existent-card-id")
        self.assertEqual(str(ctx.exception), "It is not this player's turn")

    def test_bug1_authoritative_state_emitted_on_error(self):
        """Verify SocketIO handles get_room_state and emits authoritative game_state on error."""
        app.config['TESTING'] = True
        client1 = socketio.test_client(app)
        client2 = socketio.test_client(app)

        # Create room
        res1 = client1.emit('create_room', {
            'playerName': 'Host',
            'isPrivate': True,
            'maxPlayers': 2,
            'deckCount': 1
        }, callback=True)
        self.assertTrue(res1['success'])
        room_code = res1['room_code']
        host_id = res1['player_id']

        # Join room
        res2 = client2.emit('join_room', {
            'playerName': 'Guest',
            'roomCode': room_code
        }, callback=True)
        self.assertTrue(res2['success'])
        guest_id = res2['player_id']

        # Start game
        res_start = client1.emit('start_game', {
            'roomCode': room_code,
            'playerId': host_id
        }, callback=True)
        self.assertTrue(res_start['success'])

        # Clear event queues
        client1.get_received()
        client2.get_received()

        # Test on-demand state resync
        client1.emit('get_room_state', {
            'roomCode': room_code,
            'playerId': host_id
        })
        resync_events = [m for m in client1.get_received() if m['name'] == 'game_state']
        self.assertEqual(len(resync_events), 1)
        state_payload = resync_events[0]['args'][0]
        self.assertIn('players', state_payload)
        for p in state_payload['players']:
            self.assertIn('cardCount', p)
            self.assertIn('card_count', p)
            self.assertIsInstance(p['cardCount'], int)

        # Try to play an invalid card (simulate duplicate emit or desync)
        client1.emit('play_card', {
            'roomCode': room_code,
            'playerId': host_id,
            'cardId': 'invalid-uuid-card'
        })
        err_events = client1.get_received()
        # Should re-emit authoritative game_state to client1 to restore sync
        state_after_err = [m for m in err_events if m['name'] == 'game_state']
        self.assertEqual(len(state_after_err), 1)

        client1.disconnect()
        client2.disconnect()

    def test_bug2_and_4_frontend_integrity(self):
        """Verify frontend source files contain the required bugfix implementations."""
        # Check table.js
        with open("frontend/js/ui/table.js", "r", encoding="utf-8") as f:
            table_js = f.read()

        self.assertIn("_eventsBound", table_js, "table.js must have _eventsBound guard")
        self.assertIn("_isPlayInFlight", table_js, "table.js must have _isPlayInFlight guard")
        self.assertIn("_formatCardCountText", table_js, "table.js must have _formatCardCountText")
        self.assertIn("openInGameMenu", table_js, "table.js must export openInGameMenu")
        self.assertIn("closeInGameMenu", table_js, "table.js must export closeInGameMenu")
        self.assertIn("resetPlayInFlight", table_js, "table.js must export resetPlayInFlight")
        self.assertIn("_isFirstDeal", table_js, "table.js must only animate dealHand on first deal")

        # Check online-client.js
        with open("frontend/js/game/online-client.js", "r", encoding="utf-8") as f:
            online_js = f.read()

        self.assertIn("get_room_state", online_js, "online-client.js must request get_room_state on play rejection")
        self.assertIn("resetPlayInFlight", online_js, "online-client.js must reset play in flight")
        self.assertIn("restartGame", online_js, "online-client.js must support restarting online games")

        # Check main.js
        with open("frontend/js/main.js", "r", encoding="utf-8") as f:
            main_js = f.read()

        self.assertIn("_roundResolutionTimer", main_js, "main.js must track _roundResolutionTimer")
        self.assertIn("_clearRoundTimer", main_js, "main.js must clear round resolution timer")

        # Check index.html
        with open("frontend/index.html", "r", encoding="utf-8") as f:
            index_html = f.read()

        self.assertIn("ingame-menu-backdrop", index_html, "index.html must have ingame-menu-backdrop overlay")

        # Check table.css
        with open("frontend/css/table.css", "r", encoding="utf-8") as f:
            table_css = f.read()

        self.assertIn(".ingame-menu-backdrop", table_css, "table.css must have .ingame-menu-backdrop styles")


if __name__ == '__main__':
    unittest.main()
