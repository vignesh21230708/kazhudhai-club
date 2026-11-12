/**
 * KAZHUDHAI CLUB — service-worker.js
 * Caches core frontend shell assets for offline loading and ensures deployed
 * frontend updates reach installed Android PWA / TWA users safely.
 */
const CACHE_NAME = 'kazhudhai-club-v2';
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/main.css',
  '/css/menu.css',
  '/css/table.css',
  '/css/cards.css',
  '/css/modals.css',
  '/css/responsive.css',
  '/js/main.js',
  '/js/utils/sound.js',
  '/js/utils/storage.js',
  '/js/ui/animations.js',
  '/js/ui/card-renderer.js',
  '/js/ui/menu.js',
  '/js/ui/table.js',
  '/js/lib/socket.io.min.js',
  '/js/game/game-client.js',
  '/js/game/offline-client.js',
  '/js/game/online-client.js',
  '/assets/images/icon-192.svg',
  '/assets/images/icon-512.svg',
  '/assets/images/icon-192.png',
  '/assets/images/icon-512.png',
  '/assets/images/icon-192-maskable.png',
  '/assets/images/icon-512-maskable.png',
  '/assets/images/apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        const requests = ASSETS_TO_CACHE.map((url) => new Request(url, { cache: 'reload' }));
        return cache.addAll(requests);
      })
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function _writeToCache(request, response) {
  if (!response || !response.ok || response.type !== 'basic') {
    return Promise.resolve();
  }
  const responseToCache = response.clone();
  return caches.open(CACHE_NAME)
    .then((cache) => cache.put(request, responseToCache))
    .catch(() => undefined);
}

function _cachedFallback(request, isNavigate, fallbackResponse) {
  return caches.match(request)
    .then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      if (isNavigate) {
        return caches.match('/index.html').then(
          (indexResponse) => indexResponse || fallbackResponse || Response.error()
        );
      }
      return fallbackResponse || Response.error();
    })
    .catch(() => fallbackResponse || Response.error());
}

function _networkFirst(event) {
  const { request } = event;
  const isNavigate = request.mode === 'navigate';
  let cacheWrite = Promise.resolve();

  const responsePromise = fetch(request)
    .then((networkResponse) => {
      if (!networkResponse || networkResponse.status >= 500) {
        return _cachedFallback(request, isNavigate, networkResponse);
      }
      cacheWrite = _writeToCache(request, networkResponse);
      return networkResponse;
    })
    .catch(() => _cachedFallback(request, isNavigate));

  event.waitUntil(responsePromise.then(() => cacheWrite));
  return responsePromise;
}

function _staleWhileRevalidate(event) {
  const { request } = event;
  let cacheWrite = Promise.resolve();

  const cachedMatch = caches.match(request).catch(() => undefined);
  const networkFetch = fetch(request)
    .then((networkResponse) => {
      if (!networkResponse || networkResponse.status >= 500) {
        return cachedMatch.then((cachedResponse) => cachedResponse || networkResponse || Response.error());
      }
      cacheWrite = _writeToCache(request, networkResponse);
      return networkResponse;
    })
    .catch(() => cachedMatch.then((cachedResponse) => cachedResponse || Response.error()));

  event.waitUntil(networkFetch.then(() => cacheWrite));
  return cachedMatch.then((cachedResponse) => cachedResponse || networkFetch);
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }
  if (event.request.cache === 'only-if-cached' && event.request.mode !== 'same-origin') {
    return;
  }

  const url = new URL(event.request.url);
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // Keep dynamic API, Socket.IO, and Digital Asset Links traffic strictly on the network
  if (
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/socket.io/') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/.well-known/')
  ) {
    return;
  }

  // Static icons/images use Stale-While-Revalidate for instant display with background refresh
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(_staleWhileRevalidate(event));
    return;
  }

  // Navigation requests and HTML/CSS/JS/manifest use Network-First with Cache Fallback
  // so deployed updates reach installed TWA/PWA users immediately while preserving offline shell support.
  event.respondWith(_networkFirst(event));
});
