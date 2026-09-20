const CACHE_NAME = "maintenance-silo-static-v2";
const APP_SHELL = [
  "/static/css/app.css",
  "/static/js/realtime.js",
  "/static/js/pwa.js",
  "/static/manifest.webmanifest",
  "/static/logo.jpg",
  "/static/offline.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  const isStaticAsset = url.origin === self.location.origin
    && url.pathname.startsWith("/static/");

  if (!isStaticAsset) {
    event.respondWith(
      fetch(event.request).catch(() => {
        if (event.request.mode === "navigate") {
          return caches.match("/static/offline.html");
        }
        return Response.error();
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then(
        (cached) => cached || caches.match("/static/offline.html")
      ))
  );
});
