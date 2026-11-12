/* RR FOODS PWA service worker v2. Private/customer data is never cached. */
"use strict";
var CACHE = "rr-foods-shell-v2";
var IMAGE_CACHE = "rr-foods-product-images-v2";
var STATIC_CACHE = "rr-foods-static-v2";
var PRECACHE = ["/offline", "/static/css/base.css", "/static/css/shop.css", "/static/css/rr-foods-overrides.css", "/static/js/shop.js", "/static/js/shell.js", "/static/img/rr-foods-icon-192.png"];
var PRIVATE_PATH = /^\/(?:account|cart|checkout|orders?|order(?:\/|$)|login|register|forgot|reset|owner|admin)(?:\/|$)/i;
function isStatic(url) { return url.pathname.indexOf("/static/") === 0 && /\.(?:css|js|woff2?|png|jpe?g|webp|svg|ico)$/i.test(url.pathname); }
function isProductImage(url) { return url.pathname.indexOf("/static/img/products/") === 0; }
function trimImageCache(cache) {
  return cache.keys().then(function (keys) {
    var excess = keys.length - 60;
    if (excess <= 0) return;
    return Promise.all(keys.slice(0, excess).map(function (key) { return cache.delete(key); }));
  });
}
self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(STATIC_CACHE).then(function (cache) { return cache.addAll(PRECACHE); }).catch(function () {}).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key !== CACHE && key !== IMAGE_CACHE && key !== STATIC_CACHE; }).map(function (key) { return caches.delete(key); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (PRIVATE_PATH.test(url.pathname)) { event.respondWith(fetch(request)); return; }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(function () { return caches.match("/offline"); }));
    return;
  }
  if (!isStatic(url)) return;
  if (isProductImage(url)) {
    event.respondWith(caches.open(IMAGE_CACHE).then(function (cache) {
      return cache.match(request).then(function (cached) {
        var network = fetch(request).then(function (response) {
          if (response && response.ok) {
            var headers = new Headers(response.headers); headers.set("x-rr-cached-at", String(Date.now()));
            var saved = response.clone().arrayBuffer().then(function (body) { return cache.put(request, new Response(body, { status: response.status, statusText: response.statusText, headers: headers })); }).then(function () { return trimImageCache(cache); });
            event.waitUntil(saved);
          }
          return response;
        });
        if (cached) {
          var saved = Number(cached.headers.get("x-rr-cached-at") || 0);
          if (saved && Date.now() - saved > 7 * 24 * 60 * 60 * 1000) { cache.delete(request); return network.catch(function () { return cached; }); }
          network.catch(function () {}); return cached;
        }
        return network;
      });
    }));
    return;
  }
  event.respondWith(caches.open(STATIC_CACHE).then(function (cache) {
    return cache.match(request).then(function (cached) {
      var network = fetch(request).then(function (response) { if (response && response.ok) cache.put(request, response.clone()); return response; });
      return cached || network;
    });
  }));
});
