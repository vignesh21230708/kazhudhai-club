"""
KAZHUDHAI CLUB — backend/tests/test_pwa_twa_prep.py
Verification tests for Android PWA + TWA preparation:
- Valid PNG app icons (192x192, 512x512, maskable variants, apple-touch-icon)
- Web App Manifest fields (id, scope, icons with separate any/maskable purposes)
- index.html PNG apple-touch-icon & manifest/service-worker hooks
- service-worker.js update strategy, precache integrity, and /api/ + /socket.io/ exclusions
"""
import json
import os
import re
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import app


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend'))


def _read_png_info(path: str) -> tuple[int, int, tuple[int, int, int, int]]:
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'{path} has invalid PNG signature'
    pos = 8
    w = h = color_type = 0
    idat = bytearray()
    while pos < len(data):
        length, ctype = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b'IHDR':
            w, h, _bit_depth, color_type = struct.unpack('>IIBB', chunk[:10])
        elif ctype == b'IDAT':
            idat.extend(chunk)
        elif ctype == b'IEND':
            break
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    top_left = tuple(raw[1:5]) if color_type == 6 else tuple(raw[1:4]) + (255,)
    return w, h, top_left


class TestPwaTwaPreparation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def test_01_manifest_json_fields_and_png_icons(self):
        """Verify manifest.json includes id, scope, preserved fields, and separate any/maskable PNG icons."""
        with self.client.get('/manifest.json') as res:
            self.assertEqual(res.status_code, 200)
            self.assertIn('application/json', res.content_type)
            manifest = json.loads(res.data.decode('utf-8'))

        self.assertEqual(manifest.get('id'), '/')
        self.assertEqual(manifest.get('scope'), '/')
        self.assertEqual(manifest.get('name'), 'KAZHUDHAI CLUB')
        self.assertEqual(manifest.get('short_name'), 'KAZHUDHAI')
        self.assertEqual(manifest.get('start_url'), '/')
        self.assertEqual(manifest.get('display'), 'standalone')
        self.assertEqual(manifest.get('background_color'), '#061a0b')
        self.assertEqual(manifest.get('theme_color'), '#1a5c2a')

        icons = manifest.get('icons', [])
        self.assertGreaterEqual(len(icons), 4)

        required = {
            ('192x192', 'any'),
            ('512x512', 'any'),
            ('192x192', 'maskable'),
            ('512x512', 'maskable'),
        }
        seen = set()

        for icon in icons:
            self.assertEqual(icon.get('type'), 'image/png')
            purpose = icon.get('purpose')
            self.assertIn(purpose, ('any', 'maskable'))
            sizes = icon.get('sizes')
            src = icon.get('src')
            self.assertTrue(src.startswith('/'))
            seen.add((sizes, purpose))

            with self.client.get(src) as icon_res:
                self.assertEqual(icon_res.status_code, 200, f'Failed to serve {src}')
                self.assertIn('image/png', icon_res.content_type)

            disk_path = os.path.join(FRONTEND_DIR, src.lstrip('/').replace('/', os.sep))
            w, h, corner = _read_png_info(disk_path)
            expected_dim = int(sizes.split('x')[0])
            self.assertEqual((w, h), (expected_dim, expected_dim))
            if purpose == 'maskable':
                self.assertEqual(corner[3], 255, f'Maskable icon {src} must be full-bleed opaque')
            else:
                self.assertEqual(corner[3], 0, f'Standard rounded icon {src} should have transparent outer corner')

        self.assertEqual(required - seen, set())

    def test_02_index_html_png_apple_touch_icon_and_pwa_tags(self):
        """Verify index.html uses a PNG apple-touch-icon and serves properly."""
        with self.client.get('/') as res:
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')

        self.assertIn('<link rel="manifest" href="manifest.json" />', html)
        self.assertIn("navigator.serviceWorker.register('/service-worker.js')", html)

        match = re.search(r'<link[^>]+rel="apple-touch-icon"[^>]+href="([^"]+)"', html)
        self.assertIsNotNone(match, 'Missing apple-touch-icon link')
        apple_href = match.group(1)
        self.assertTrue(apple_href.endswith('.png'), f'apple-touch-icon must be PNG, got {apple_href}')

        with self.client.get('/' + apple_href.lstrip('/')) as apple_res:
            self.assertEqual(apple_res.status_code, 200)
            self.assertIn('image/png', apple_res.content_type)

        disk_path = os.path.join(FRONTEND_DIR, apple_href.lstrip('/').replace('/', os.sep))
        w, h, corner = _read_png_info(disk_path)
        self.assertEqual((w, h), (180, 180))
        self.assertEqual(corner[3], 255)

    def test_03_service_worker_assets_strategy_and_exclusions(self):
        """Verify service-worker.js serves cleanly, caches valid files, and excludes APIs/sockets."""
        with self.client.get('/service-worker.js') as res:
            self.assertEqual(res.status_code, 200)
            self.assertIn('javascript', res.content_type)
            sw_code = res.data.decode('utf-8')

        self.assertIn("const CACHE_NAME = 'kazhudhai-club-v2'", sw_code)
        self.assertIn('/api/', sw_code)
        self.assertIn('/socket.io/', sw_code)
        self.assertIn('/.well-known/', sw_code)
        self.assertIn('_networkFirst', sw_code)
        self.assertIn("caches.match('/index.html')", sw_code)

        arr_match = re.search(r'ASSETS_TO_CACHE\s*=\s*\[(.*?)\];', sw_code, re.DOTALL)
        self.assertIsNotNone(arr_match)
        assets = re.findall(r"'([^']+)'", arr_match.group(1))
        self.assertGreaterEqual(len(assets), 25)

        for asset_url in assets:
            with self.client.get(asset_url) as asset_res:
                self.assertEqual(asset_res.status_code, 200, f'Precache URL {asset_url} returned {asset_res.status_code}')

    def test_04_service_worker_network_first_waituntil_and_5xx_fallback(self):
        """Verify network-first uses event.waitUntil for cache writes and cached fallback on 5xx responses."""
        with self.client.get('/service-worker.js') as res:
            self.assertEqual(res.status_code, 200)
            sw_code = res.data.decode('utf-8')

        # Extract _writeToCache, _cachedFallback, _networkFirst, and fetch listener sections
        nf_match = re.search(
            r'function _networkFirst\(event\)\s*\{(?P<body>.*?)\n\}',
            sw_code,
            re.DOTALL,
        )
        self.assertIsNotNone(nf_match, '_networkFirst(event) definition missing')
        nf_body = nf_match.group('body')

        # Issue 1: network-first cache writes must be extended via event.waitUntil(...)
        self.assertIn('event.waitUntil(', nf_body)
        self.assertIn('_writeToCache(request, networkResponse)', nf_body)
        self.assertIn('cacheWrite', nf_body)

        # Issue 2: HTTP 5xx responses must trigger cached fallback rather than direct 5xx return
        self.assertIn('networkResponse.status >= 500', nf_body)
        self.assertIn('_cachedFallback(request, isNavigate, networkResponse)', nf_body)
        self.assertIn('event.respondWith(_networkFirst(event))', sw_code)

        # _writeToCache must return the cache.put promise and reject non-ok / non-basic responses
        wtc_match = re.search(
            r'function _writeToCache\(request, response\)\s*\{(?P<body>.*?)\n\}',
            sw_code,
            re.DOTALL,
        )
        self.assertIsNotNone(wtc_match, '_writeToCache definition missing')
        wtc_body = wtc_match.group('body')
        self.assertIn("response.type !== 'basic'", wtc_body)
        self.assertIn('return caches.open(CACHE_NAME)', wtc_body)
        self.assertIn('cache.put(request, responseToCache)', wtc_body)

        # _cachedFallback must safely fall back to cached /index.html on navigate and network fallback/Response.error
        fb_match = re.search(
            r'function _cachedFallback\(request, isNavigate, fallbackResponse\)\s*\{(?P<body>.*?)\n\}',
            sw_code,
            re.DOTALL,
        )
        self.assertIsNotNone(fb_match, '_cachedFallback definition missing')
        fb_body = fb_match.group('body')
        self.assertIn('caches.match(request)', fb_body)
        self.assertIn("caches.match('/index.html')", fb_body)
        self.assertIn('fallbackResponse || Response.error()', fb_body)

        # Verify balanced brackets/braces/parens in service-worker.js
        pairs = {'(': ')', '[': ']', '{': '}'}
        closing = {v: k for k, v in pairs.items()}
        stack = []
        i = 0
        n = len(sw_code)
        while i < n:
            ch = sw_code[i]
            if ch == '/' and i + 1 < n and sw_code[i + 1] == '/':
                while i < n and sw_code[i] != '\n':
                    i += 1
                continue
            if ch == '/' and i + 1 < n and sw_code[i + 1] == '*':
                i += 2
                while i + 1 < n and not (sw_code[i] == '*' and sw_code[i + 1] == '/'):
                    i += 1
                i += 2
                continue
            if ch in ("'", '"', '`'):
                q = ch
                i += 1
                while i < n:
                    if sw_code[i] == '\\':
                        i += 2
                        continue
                    if sw_code[i] == q:
                        i += 1
                        break
                    i += 1
                continue
            if ch in pairs:
                stack.append(ch)
            elif ch in closing:
                self.assertTrue(stack and stack[-1] == closing[ch], f'Unmatched {ch} in service-worker.js')
                stack.pop()
            i += 1
        self.assertEqual(stack, [], f'Unclosed delimiters in service-worker.js: {stack}')


if __name__ == '__main__':
    unittest.main()
