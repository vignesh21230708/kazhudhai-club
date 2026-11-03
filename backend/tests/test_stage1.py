import sys
sys.path.insert(0, 'd:/KAZHUDHAI Club/backend')
from app import app

client = app.test_client()

# 1. Test index
r = client.get('/')
assert r.status_code == 200, f'Index failed: {r.status_code}'
assert b'KAZHUDHAI CLUB' in r.data, 'Missing title in index'
print('Test 1: Index HTML served OK')

# 2. Test static files
for f in ['css/main.css', 'css/table.css', 'css/cards.css', 'css/menu.css', 'css/modals.css', 'css/responsive.css',
          'js/main.js', 'js/ui/table.js', 'js/ui/menu.js', 'js/ui/card-renderer.js', 'js/ui/animations.js',
          'js/utils/sound.js', 'js/utils/storage.js']:
    r = client.get(f'/{f}')
    assert r.status_code == 200, f'Static file {f} failed: {r.status_code}'
print('Test 2: All 13 CSS and JS static assets served OK')

# 3. Test Health API
r = client.get('/api/health')
assert r.status_code == 200
data = r.get_json()
assert data['status'] == 'ok'
print('Test 3: Health check OK')

# 4. Test Offline Game Start API
payload = {
    'playerName': 'Gamer1',
    'playerCount': 4,
    'deckCount': 2,
    'difficulty': 'medium'
}
r = client.post('/api/offline/start', json=payload)
assert r.status_code == 200
st = r.get_json()
print('Test 4: Offline start OK')
print('   Game ID:', st.get('game_id'))
print('   My hand count:', len(st.get('my_hand', [])))
print('   Opponents count:', len(st.get('opponents', [])))

# 5. Security check: Opponents MUST NOT leak their hands!
for opp in st.get('opponents', []):
    assert 'hand' not in opp, f'SECURITY VIOLATION: Opponent hand exposed: {opp}'
print('Test 5: Opponent hidden cards security check PASSED (Zero card leakage)')

print('\n=======================================')
print('STAGE 1 FRONTEND & BACKEND INTEGRATION PASSED!')
print('=======================================')
