// Minimal service worker: it exists so the browser lets you install Chimera as
// an app (a Dock icon on macOS). It doesn't cache anything — Chimera needs the
// live local server — so every request goes straight to the network.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  // No respondWith: the browser handles the request normally. Having a fetch
  // listener at all is what makes the app installable.
});
