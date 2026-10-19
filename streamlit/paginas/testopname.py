"""Eerste test-opname stap voor stap, met afvinkbare stappen en een oefenmodus zonder P-Cardio."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from kern.opslag import DATA_ROOT, Deelnemers, Opname
from kern.pcardio import combineer, lees_bestand
from ui import link

VOORTGANG = DATA_ROOT / "testopname_voortgang.json"
# Vaste map, ook als ECG_TOOL_DATA een andere datamap aanwijst (tests).
OEFENDATA = Path(__file__).resolve().parents[1] / "data" / "test"


@dataclass(frozen=True)
class Stap:
    id: str
    titel: str
    uitleg: str
    pagina: str | None = None
    pagina_label: str = ""


FASES: list[tuple[str, str, list[Stap]]] = [
    (
        "1. Voorbereiden",
        "± 10 minuten. Doe dit met z'n tweeën: één deelnemer (draagt de P-Cardio) en één operator (bedient de app).",
        [
            Stap(
                "app",
                "Start de ECG-tool op de pc die je tijdens de opname gebruikt",
                "Vanuit de projectroot: `streamlit run streamlit\\app.py`. Gebruik tijdens de opname steeds **deze** "
                "pc: de tijdstempels komen van de klok van deze pc.",
            ),
            Stap(
                "deelnemer",
                "Leg de deelnemer vast",
                "Voornaam of patiënt-ID, leeftijd, geslacht. Onthoud het ID (`D001`, …): dat komt zo in de P-Cardio.",
                "paginas/deelnemers.py",
                "Naar Deelnemers",
            ),
            Stap(
                "docking",
                "Zet de P-Cardio in de docking-station",
                "Controleer de batterij (> 50%) en haal oude databestanden van het apparaat. Laat `config.txt` staan.",
            ),
            Stap(
                "klok",
                "Zet de tijd van de P-Cardio gelijk met deze pc",
                "Het `Time`-register (opnameprotocol, sectie 3). Dat kan **niet** vanuit de ECG-tool en **niet** "
                "via `config.txt`: gebruik de PCardio-software van 2M (via de USB-verbinding van de docking). "
                "Dan lopen de klokken vanaf het begin zo goed mogelijk gelijk (op de seconde); de sync-sprong "
                "corrigeert de rest.",
            ),
            Stap(
                "config",
                "Stel de meetconfiguratie in en vul het User Id in",
                "ECG 2-kanaals 250 Hz x6, accelerometer en gyroscoop 100 Hz x2, lead-off, button marker en battery 5 Hz (protocol, sectie 4). "
                "**User Id** = het deelnemer-ID, nooit de naam.",
            ),
            Stap(
                "elektroden",
                "Haal de P-Cardio uit de docking en plak de elektroden",
                "Uit de docking gaat de nieuwe configuratie in en begint het loggen. Noteer waar de elektroden zitten. "
                "**Wacht 2-3 minuten** zodat het signaal stabiel wordt.",
            ),
        ],
    ),
    (
        "2. Opnemen",
        "± 8 minuten. De operator klikt; de deelnemer doet de activiteiten. Elke klik wordt direct opgeslagen.",
        [
            Stap(
                "start",
                "Start een nieuwe live opname",
                "Kies de deelnemer, vul de plek van de elektroden in en vink aan dat de P-Cardio-tijd is gelijkgezet.",
                "paginas/live.py",
                "Naar Live opname",
            ),
            Stap(
                "sync_begin",
                "Sync-sprong",
                "Tel samen af (3-2-1-spring). De deelnemer maakt één sprongetje; klik op **Sync-sprong** precies op "
                "het moment van **landen**.",
            ),
            Stap(
                "zitten",
                "Zitten — 60 s, met 2× een hoest",
                "Klik **Zitten**. Laat de deelnemer na ±20 s en na ±40 s één keer hoesten en klik meteen op het "
                "moment **Hoest**. Na 60 s: **Stop periode**. Rust ±20 s.",
            ),
            Stap(
                "staan",
                "Staan — 60 s",
                "Klik **Staan**, na 60 s **Stop periode**. Rust ±20 s.",
            ),
            Stap(
                "lopen",
                "Lopen (rustig) — 60 s",
                "Klik **Lopen (rustig)**, na 60 s **Stop periode**. Rust ±20 s.",
            ),
            Stap(
                "armen",
                "Armen bewegen — 30 s",
                "Klik **Armen bewegen**, na 30 s **Stop periode**. Rust ±20 s.",
            ),
            Stap(
                "springen",
                "Springen — 30 s",
                "Klik **Springen**, na 30 s **Stop periode**.",
            ),
            Stap(
                "herstel",
                "Herstel — 60 s rustig zitten",
                "Klik **Herstel (rustig zitten)**. Hier zie je de hartslag weer dalen.",
            ),
            Stap(
                "sync_eind",
                "Nog een sync-sprong, en afsluiten",
                "Weer aftellen, springen, klikken bij het landen. Klik daarna **Opname afsluiten**. Hiermee kan de app "
                "zien of de klokken tijdens de opname uit elkaar zijn gaan lopen.",
            ),
        ],
    ),
    (
        "3. Data koppelen",
        "± 5 minuten.",
        [
            Stap(
                "download",
                "Zet de P-Cardio terug in de docking en kopieer de bestanden",
                "Kopieer `data_*.txt` (en eventueel de CSV-export) naar een map op de pc. Laat `config.txt` op het "
                "apparaat staan.",
            ),
            Stap(
                "inlezen",
                "Lees de bestanden in",
                "Tabblad **Bestand of map op deze pc** → pad naar de map → **Inlezen**. Controleer in de tabel of de "
                "sample rates en de start- en eindtijd kloppen.",
                "paginas/koppelen.py",
                "Naar Data koppelen",
            ),
            Stap(
                "koppel",
                "Koppel aan de test-opname",
                "De app stelt de juiste opname voor (op basis van de tijd). Klopt het? Klik **Koppel**.",
            ),
            Stap(
                "klokcorrectie",
                "Controleer de klokcorrectie",
                "Bij stap 3 zie je per sync-sprong een plot: valt de rode lijn op de piek? Dan **Gebruik voorstel**. "
                "Noteer het verschil tussen de eerste en de tweede sprong.",
            ),
        ],
    ),
    (
        "4. Bekijken",
        "Zo lang als je wilt — dit is waar het om gaat.",
        [
            Stap(
                "doorlopen",
                "Loop de perioden door",
                "Kies de opname en klik op **Volgende**. Begin met **Zitten**: zie je de hartslagen? Staat het "
                "**ECG-filter** in de zijbalk aan? Zet het ook eens uit om het ruwe signaal te zien.",
                "paginas/bekijken.py",
                "Naar Bekijken & annoteren",
            ),
            Stap(
                "hoest",
                "Bekijk de twee hoestmomenten",
                "Valt de oranje lijn samen met een verstoring in de ECG of de accelerometer? Zo niet: klopt de "
                "klokcorrectie, of klikte je te laat?",
            ),
            Stap(
                "vergelijken",
                "Vergelijk zitten, lopen en springen",
                "Wat zie je in de ECG, en zie je het ook in de accelerometer en de gyroscoop? Is één kanaal gevoeliger?",
            ),
            Stap(
                "beoordelen",
                "Beoordeel elke periode",
                "Kies per periode **schoon**, **ruis, QRS herkenbaar** of **onbruikbaar**, en schrijf kort op wat je "
                "ziet. Klik **Opslaan**.",
            ),
            Stap(
                "export",
                "Maak (optioneel) een export",
                "Eén CSV met alles per sample, voor verdere analyse in een notebook.",
                "paginas/export.py",
                "Naar Export",
            ),
        ],
    ),
]


def lees_voortgang() -> dict[str, bool]:
    if not VOORTGANG.exists():
        return {}
    return json.loads(VOORTGANG.read_text(encoding="utf-8"))


def _bewaar(stap_id: str) -> None:
    voortgang = lees_voortgang()
    voortgang[stap_id] = st.session_state[f"stap_{stap_id}"]
    VOORTGANG.parent.mkdir(parents=True, exist_ok=True)
    VOORTGANG.write_text(json.dumps(voortgang, indent=2), encoding="utf-8")


def _reset() -> None:
    VOORTGANG.unlink(missing_ok=True)
    for fase in FASES:
        for stap in fase[2]:
            st.session_state.pop(f"stap_{stap.id}", None)


def maak_oefenopname() -> Opname:
    """Opname met de P-Cardio-data van januari 2026, zonder annotaties, om mee te oefenen."""
    register = Deelnemers(DATA_ROOT)
    deelnemer = next((d for d in register.alle() if d.naam == "Oefen"), None)
    if deelnemer is None:
        deelnemer = register.toevoegen("Oefen", None, "man", False, "hartaandoening (oefendata, volwassene)")
    bestaand = [o for o in Opname.alle(DATA_ROOT) if o.info.deelnemer_id == deelnemer.id and o.heeft_signalen]
    if bestaand:
        return bestaand[0]
    bestanden = sorted(OEFENDATA.glob("*.csv"))
    signalen = combineer([s for pad in bestanden for s in lees_bestand(pad)[0]])
    start = min(s.start for s in signalen.values())
    opname = Opname.nieuw(
        deelnemer,
        start,
        root=DATA_ROOT,
        live_afgesloten=True,
        notities="Oefenopname met de P-Cardio-data van 19-01-2026. Er is niet live geannoteerd.",
    )
    opname.bewaar_signalen(signalen, bestanden)
    return opname


# --- pagina ---

st.title(
    "Test-opname stap voor stap",
    help="Een korte eerste opname (± 25 minuten in totaal) om de P-Cardio en de ECG-tool te leren kennen. Vink de "
    "stappen af; je voortgang wordt bewaard.",
)
st.markdown(
    "Een korte opname van ± 8 minuten met een paar activiteiten, om de hele werkwijze één keer te doorlopen: "
    "voorbereiden → opnemen → koppelen → bekijken. Het volledige programma staat in het **opnameprotocol** "
    "(`docs/opnameprotocol-p-cardio.md`). Uitleg over de begrippen staat in de **Handleiding**.",
)
link("paginas/handleiding.py", "Naar de handleiding")

with st.expander("Eerst oefenen zonder P-Cardio?"):
    st.markdown(
        "- **Live opname oefenen:** start gewoon een opname en klik wat rond. Er komt dan geen data bij, maar je "
        "leert de knoppen kennen. Een oefenopname kun je later laten staan; hij stoort niets.\n"
        "- **Bekijken oefenen:** maak een oefenopname met de P-Cardio-data van januari 2026 "
        "van een volwassen man met een hartaandoening (`streamlit/data/test/`). Daar zijn geen live annotaties bij; probeer zelf perioden toe te voegen op "
        "**Bekijken & annoteren** (uitklapvak *Nieuwe annotatie in dit venster*).",
    )
    if not OEFENDATA.exists() or not list(OEFENDATA.glob("*.csv")):
        st.warning(f"Oefendata niet gevonden in `{OEFENDATA}`.")
    elif st.button("Maak oefenopname met de data van januari", type="primary"):
        with st.spinner("Inlezen en opslaan…"):
            opname = maak_oefenopname()
        st.session_state.bekijk_opname = opname.info.id
        st.success(f"Oefenopname `{opname.info.id}` staat klaar.")
        link("paginas/bekijken.py", "Bekijk de oefenopname")

voortgang = lees_voortgang()
totaal = sum(len(stappen) for _, _, stappen in FASES)
gedaan = sum(1 for _, _, stappen in FASES for s in stappen if voortgang.get(s.id))
st.progress(gedaan / totaal, text=f"{gedaan} van {totaal} stappen gedaan")

for titel, inleiding, stappen in FASES:
    klaar = all(voortgang.get(s.id) for s in stappen)
    st.subheader(titel + (" (klaar)" if klaar else ""))
    st.caption(inleiding)
    for stap in stappen:
        links, rechts = st.columns([5, 2])
        with links:
            st.checkbox(
                f"**{stap.titel}**",
                value=voortgang.get(stap.id, False),
                key=f"stap_{stap.id}",
                on_change=_bewaar,
                args=(stap.id,),
            )
            st.markdown(stap.uitleg)
        if stap.pagina:
            with rechts:
                link(stap.pagina, stap.pagina_label)

st.divider()
if gedaan == totaal:
    st.success(
        "Klaar! Schrijf kort op wat je opviel (protocol, sectie 11): werkte de sync-sprong, welke activiteiten gaven "
        "artefacten, wat was onhandig in de app?",
    )
st.button("Opnieuw beginnen (alle vinkjes weg)", on_click=_reset)
