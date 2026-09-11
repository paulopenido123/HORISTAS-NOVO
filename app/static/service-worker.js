// Service worker mínimo — só o necessário pra navegadores (principalmente
// Android/Chrome) considerarem o sistema "instalável" como app. Não faz
// cache agressivo de nada — o painel sempre busca dados frescos do
// servidor, então não tem risco de mostrar informação desatualizada
// (saldo, reservas, etc) por causa de cache.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

// Passa tudo direto pro servidor, sem interceptar/cachear — mantém o
// comportamento idêntico ao de abrir o site direto no navegador.
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
