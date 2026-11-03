"""
KAZHUDHAI CLUB — api/offline_routes.py
REST API endpoints for offline game sessions.
Supports step-by-step turn execution for realistic animation timing,
card play validation, normal & attack round resolution, and game completion.
"""
from flask import Blueprint, request, jsonify
import uuid
from game_engine.game_state import GameState

offline_bp = Blueprint('offline', __name__, url_prefix='/api/offline')

# In-memory game sessions (key: game_id -> GameState)
_games: dict[str, GameState] = {}

HUMAN_PLAYER_ID = 'human'


@offline_bp.route('/start', methods=['POST'])
def start():
    """Start a new offline game session."""
    data = request.get_json() or {}
    player_name  = (data.get('playerName') or 'Player').strip()[:16]
    player_count = max(2, min(7, int(data.get('playerCount', 4))))
    num_decks    = max(1, min(5, int(data.get('deckCount', 1))))
    difficulty   = data.get('difficulty', 'medium')

    ai_names = ['Bot Ravi', 'Bot Priya', 'Bot Kumar', 'Bot Leela', 'Bot Arjun', 'Bot Deepa']

    player_configs = [{'id': HUMAN_PLAYER_ID, 'name': player_name, 'is_ai': False}]
    for i in range(player_count - 1):
        player_configs.append({
            'id':    f'ai_{i+1}',
            'name':  ai_names[i % len(ai_names)],
            'is_ai': True,
        })

    game_id = str(uuid.uuid4())
    gs = GameState(game_id, player_configs, num_decks=num_decks, difficulty=difficulty)
    gs.setup()
    _games[game_id] = gs

    state = _format_player_state(gs)
    return jsonify(state)


@offline_bp.route('/play', methods=['POST'])
def play():
    """
    Play a card in an offline game.
    Body: { 'game_id': str, 'card_id': str, 'auto_step': bool (optional) }
    """
    data      = request.get_json() or {}
    game_id   = data.get('game_id')
    card_id   = data.get('card_id')
    auto_step = data.get('auto_step', False)

    gs = _games.get(game_id)
    if not gs:
        return jsonify({'error': 'Game not found'}), 404

    try:
        play_result = gs.play_card(HUMAN_PLAYER_ID, card_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    if auto_step:
        # Fast-forward until human's turn or game end
        while gs.status == GameState.STATUS_PLAYING:
            cp = gs.current_player
            if cp is None or not cp.is_ai:
                break
            gs.step_ai_turn()

    state = _format_player_state(gs)
    return jsonify({
        'status':            'ok',
        'action':            play_result['action'],
        'round_completed':   play_result['round_completed'],
        'last_round_result': play_result['last_round_result'],
        'state':             state,
    })


@offline_bp.route('/step', methods=['POST'])
def step():
    """
    Execute ONE AI player's turn in sequence.
    Allows the frontend to animate cards one-by-one with realistic pacing.
    Body: { 'game_id': str }
    """
    data    = request.get_json() or {}
    game_id = data.get('game_id')

    gs = _games.get(game_id)
    if not gs:
        return jsonify({'error': 'Game not found'}), 404

    if gs.status != GameState.STATUS_PLAYING:
        state = _format_player_state(gs)
        return jsonify({
            'status':      'finished',
            'action_type': 'game_finished',
            'state':       state,
        })

    cp = gs.current_player
    if cp is None or not cp.is_ai:
        state = _format_player_state(gs)
        return jsonify({
            'status':      'ok',
            'action_type': 'waiting_human',
            'state':       state,
        })

    step_result = gs.step_ai_turn()
    state = _format_player_state(gs)

    return jsonify({
        'status':            'ok',
        'action_type':       step_result.get('action_type'),
        'action':            step_result.get('action'),
        'round_completed':   step_result.get('round_completed', False),
        'last_round_result': step_result.get('last_round_result'),
        'state':             state,
    })


@offline_bp.route('/fast_forward', methods=['POST'])
def fast_forward():
    """
    Fast-forward remaining AI turns until the game reaches completion.
    Called when the human is safe and wants to immediately see the final KAZHUDHAI.
    """
    data    = request.get_json() or {}
    game_id = data.get('game_id')

    gs = _games.get(game_id)
    if not gs:
        return jsonify({'error': 'Game not found'}), 404

    max_turns = 1000
    turns = 0
    while gs.status == GameState.STATUS_PLAYING and turns < max_turns:
        cp = gs.current_player
        if cp is None or not cp.is_ai:
            break
        gs.step_ai_turn()
        turns += 1

    state = _format_player_state(gs)
    return jsonify({
        'status':        'ok',
        'game_finished': gs.status == GameState.STATUS_FINISHED,
        'turns_played':  turns,
        'state':         state,
    })


@offline_bp.route('/state', methods=['GET'])
def get_state():
    """Get current game state."""
    game_id = request.args.get('game_id')
    gs = _games.get(game_id)
    if not gs:
        return jsonify({'error': 'Game not found'}), 404

    state = _format_player_state(gs)
    return jsonify(state)


def _format_player_state(gs: GameState) -> dict:
    """Helper to build safe state with opponent cards hidden."""
    state = gs.get_state_for_player(HUMAN_PLAYER_ID)
    state['player_name'] = _get_human_name(gs)
    state['room_code']   = 'OFFLINE'
    state['opponents']   = _build_opponents(gs, HUMAN_PLAYER_ID)
    state['is_demo']     = False
    return state


def _get_human_name(gs: GameState) -> str:
    p = next((p for p in gs.players if p.id == HUMAN_PLAYER_ID), None)
    return p.name if p else 'Player'


def _build_opponents(gs: GameState, exclude_id: str) -> list[dict]:
    """
    Build frontend-safe opponent list (NEVER reveals hidden cards).
    Includes only id, name, cardCount, isAI, isActive, and isSafe.
    """
    cp = gs.current_player
    result = []
    for p in gs.players:
        if p.id == exclude_id:
            continue
        result.append({
            'id':        p.id,
            'name':      p.name,
            'cardCount': p.card_count,
            'isAI':      p.is_ai,
            'isActive':  cp is not None and cp.id == p.id,
            'isSafe':    p.is_safe,
        })
    return result
