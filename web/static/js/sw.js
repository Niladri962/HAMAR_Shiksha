/* Service worker: caches the static app shell and the portal page shells
   (HTML without data). API responses are never cached here - offline data
   lives in the signed-in user's IndexedDB bundle and is cleared at logout. */
const CACHE = "hs-shell-v5";
const SHELL = [
  "/static/css/app.css", "/static/js/theme.js", "/static/js/i18n.js", "/static/js/core.js", "/static/js/charts.js",
  "/static/js/voice.js", "/static/js/video.js", "/static/data/cg-districts.geojson",
  "/static/js/login.js", "/static/js/admin.js", "/static/js/teacher.js", "/static/js/student.js",
];
const PAGES = ["/student/dashboard", "/teacher/dashboard", "/student/login", "/teacher/login", "/"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const isStatic = url.pathname.startsWith("/static/");
  const isPage = e.request.mode === "navigate" && PAGES.includes(url.pathname);
  if (!isStatic && !isPage) return;
  // Network first so updates arrive promptly; fall back to cache when offline.
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && !res.redirected) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
    }
    return res;
  }).catch(() => caches.match(e.request)));
});
