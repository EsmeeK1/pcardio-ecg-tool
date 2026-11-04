// Annotatielogica zonder DOM: index.html gebruikt hem, streamlit/tests/test_mobiel.py test hem met node.
// De CSV heeft het formaat van annotaties.csv (kern/opslag.py), zodat de pagina Koppelen hem herkent.

const KOLOMMEN = [
  "id", "soort", "label", "t_start", "t_eind", "tijdbasis", "opmerking", "beoordeling", "beoordeling_opmerking",
  "plaatsing",
];

const nul = (n, breedte = 2) => String(n).padStart(breedte, "0");

/** Lokale tijd met offset, zoals iso() in kern/opslag.py: 2026-11-03T19:20:00.000+01:00 */
export function iso(datum) {
  const offset = -datum.getTimezoneOffset();
  const teken = offset < 0 ? "-" : "+";
  return (
    `${datum.getFullYear()}-${nul(datum.getMonth() + 1)}-${nul(datum.getDate())}` +
    `T${nul(datum.getHours())}:${nul(datum.getMinutes())}:${nul(datum.getSeconds())}.${nul(datum.getMilliseconds(), 3)}` +
    `${teken}${nul(Math.floor(Math.abs(offset) / 60))}:${nul(Math.abs(offset) % 60)}`
  );
}

export const actief = (lijst) => lijst.find((a) => a.soort === "periode" && a.t_eind == null);

function voegToe(lijst, soort, label, tijd) {
  const id = Math.max(0, ...lijst.map((a) => a.id)) + 1;
  lijst.push({ id, soort, label, t_start: tijd, t_eind: null });
}

/** Net als live in de Streamlit-app: een nieuwe periode stopt de lopende op hetzelfde moment. */
export function startPeriode(lijst, label, tijd = Date.now()) {
  stopPeriode(lijst, tijd);
  voegToe(lijst, "periode", label, tijd);
}

export function stopPeriode(lijst, tijd = Date.now()) {
  const a = actief(lijst);
  if (a) a.t_eind = tijd;
}

export const moment = (lijst, label, tijd = Date.now()) => voegToe(lijst, "moment", label, tijd);
export const sync = (lijst, tijd = Date.now()) => voegToe(lijst, "sync", "sync-sprong", tijd);

export function verwijder(lijst, id) {
  const i = lijst.findIndex((a) => a.id === id);
  if (i >= 0) lijst.splice(i, 1);
}

const veld = (waarde) => (/[",\r\n]/.test(waarde) ? `"${waarde.replaceAll('"', '""')}"` : waarde);

/** Tijden in de lokale tijd van de telefoon met tijdbasis "pc": Koppelen zet ze gelijk via de sync-sprong. */
export function naarCsv(lijst) {
  const rijen = lijst.map((a) =>
    [a.id, a.soort, a.label, iso(new Date(a.t_start)), a.t_eind == null ? "" : iso(new Date(a.t_eind)), "pc", "", "", "", ""]
      .map((w) => veld(String(w)))
      .join(","),
  );
  return [KOLOMMEN.join(","), ...rijen].join("\n") + "\n";
}
