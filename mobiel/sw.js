// Offline in de sportschool: antwoord direct uit de cache en ververs die op de achtergrond.
// Een nieuwe versie is daardoor pas bij de tweede keer openen zichtbaar.
const CACHE = "pcardio-annotaties";
const BESTANDEN = ["./", "index.html", "annotaties.js", "live.html", "pcardio.js", "manifest.webmanifest", "icon.png"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(BESTANDEN))));

self.addEventListener("fetch", (e) => {
  const nieuw = caches.open(CACHE).then((c) =>
    fetch(e.request).then((antwoord) => {
      if (antwoord.ok) c.put(e.request, antwoord.clone());
      return antwoord;
    }),
  );
  e.waitUntil(nieuw.catch(() => {}));
  e.respondWith(caches.match(e.request).then((oud) => oud || nieuw));
});
