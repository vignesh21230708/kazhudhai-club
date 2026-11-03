/**
 * KAZHUDHAI CLUB — service-worker.js
 * Caches core frontend assets for offline play and instant loading on Android / Desktop PWA.
 */
const CACHE_NAME = 'kazhudhai-club-v1';
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
  '/assets/images/icon-512.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // Only handle GET requests and skip socket.io and dynamic API requests
  if (event.request.method !== 'GET' || event.request.url.includes('/socket.io/') || event.request.url.includes('/api/')) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseToCache);
        });
        return networkResponse;
      }).catch(() => {
        // Fallback for navigation requests
        if (event.request.mode === 'navigate') {
          return caches.match('/index.html');
        }
      });
    })
  );
});
