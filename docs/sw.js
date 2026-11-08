// 한 번 받은 판을 통신 없이 그대로 쓴다. 새 판은 사용자가 '새 판 받기'를 눌렀을 때만 바뀐다.
const VERSION = "0.3.1";
const CACHE = `bf-gather-${VERSION}`;
const PIN = "bf-gather-pin";
const FILES = [
  "./", "./index.html", "./app.css", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png",
  "./js/app.js", "./js/calc.js", "./js/fields.js", "./js/map.js", "./js/store.js", "./js/sync.js", "./js/version.js",
];

async function pinned() {
  const c = await caches.open(PIN);
  const r = await c.match("pin");
  return r ? r.text() : null;
}

async function setPin(v) {
  const c = await caches.open(PIN);
  await c.put("pin", new Response(v));
}

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(FILES.map((f) => new Request(f, { cache: "reload" })));
    if (!(await pinned())) await setPin(CACHE);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  e.respondWith((async () => {
    const name = (await pinned()) || CACHE;
    const c = await caches.open(name);
    const hit = await c.match(e.request, { ignoreSearch: true });
    if (hit) return hit;
    return fetch(e.request);
  })());
});

self.addEventListener("message", (e) => {
  const reply = (m) => e.source && e.source.postMessage(m);
  if (e.data === "versions") {
    e.waitUntil(pinned().then((p) => reply({ type: "versions", running: p, latest: CACHE })));
  } else if (e.data === "use-latest") {
    e.waitUntil(setPin(CACHE).then(() => reply({ type: "pinned", running: CACHE })));
  }
});
