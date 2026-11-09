"""Gedeelde Streamlit-onderdelen voor de pagina's."""

from __future__ import annotations

import atexit
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

import hulp
from kern.live_sessie import LiveSessie
from kern.opslag import DATA_ROOT, WEERGAVE_TZ, Deelnemers, Opname, versie
from kern.pcardio import Signaal
from kern.beweging import HOUDING_LIVE_S, LIVE_STAP_S, SEGMENT_S, beweging_nu, houding_nu
from kern.plots import live_beweging, live_ecg, markeer_venster, overzicht


STANDAARD_CONFIGURATIE = (
    "ECG 2-kanaals 250 Hz gain x6; Acc 100 Hz x2; Gyro 100 Hz x2; Lead-off 5 Hz; Button Marker 5 Hz; Battery 5 Hz"
)
ELEKTRODE_PLAATSINGEN = ["Optie 1: met sticker", "Optie 2: met lanyard"]
ELEKTRODE_FOTO = Path(__file__).resolve().parent / "assets" / "elektroden_plaatsing.png"


def opname_velden(apparaat: str = "déze pc") -> dict[str, object]:
    """Gegevens van een nieuwe opname, met dezelfde standaardwaarden op Live opname en Data koppelen. Geeft de
    velden voor ``Opname.nieuw``. ``apparaat`` is waarmee geannoteerd is (pc of telefoon)."""
    plaatsing, foto = st.columns([4, 1], vertical_alignment="bottom")
    elektroden = plaatsing.selectbox(
        "Plaatsing van de elektroden", ELEKTRODE_PLAATSINGEN, index=1, help=hulp.ELEKTRODEN,  # lanyard
    )
    with foto.popover("📷 Foto's", width="stretch"):
        st.image(str(ELEKTRODE_FOTO), caption="Bron: handleiding P-Cardio (2M Engineering)")
    huidvoorbereiding = st.text_input("Huidvoorbereiding / bijzonderheden (optioneel)", help=hulp.HUIDVOORBEREIDING)
    configuratie = st.text_input("Meetconfiguratie P-Cardio", value=STANDAARD_CONFIGURATIE, help=hulp.CONFIGURATIE)
    gelijkgezet = st.checkbox(
        f"Tijd van de P-Cardio is vlak voor de opname gelijkgezet met {apparaat}", help=hulp.GELIJKGEZET,
    )
    experiment = st.text_input(
        "Experiment (optioneel)", placeholder="bijv. Elektrodeplaatsing 21-10", help=hulp.EXPERIMENT,
    )
    notities = st.text_area("Notities", help=hulp.NOTITIES)
    return {
        "elektroden": elektroden,
        "huidvoorbereiding": huidvoorbereiding.strip(),
        "configuratie": configuratie.strip(),
        "pcardio_tijd_gelijkgezet": gelijkgezet,
        "notities": notities.strip(),
        "experiment": experiment.strip(),
    }


@st.cache_data(show_spinner=False, max_entries=1)
def _namen(versie: int) -> dict[str, str]:
    return {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}


def deelnemer_naam(deelnemer_id: str) -> str:
    """Gecachet op de versie van de database: wordt per rerun vaak aangeroepen (keuzelijst met opnames)."""
    return _namen(versie(DATA_ROOT)).get(deelnemer_id, deelnemer_id)


def opname_label(opname: Opname) -> str:
    gestart = pd.Timestamp(opname.info.gestart).strftime("%d-%m-%Y %H:%M")
    delen = [gestart, deelnemer_naam(opname.info.deelnemer_id)]
    delen.append(f"{len(opname.annotaties)} annotaties")
    if opname.heeft_signalen:
        delen.append("data gekoppeld")
    return " · ".join(delen)


def kies_opname(key: str, alleen_met_data: bool = False) -> Opname | None:
    opnames = Opname.alle(DATA_ROOT)
    if alleen_met_data:
        opnames = [o for o in opnames if o.heeft_signalen]
    if not opnames:
        st.info(
            "Nog geen opnames met gekoppelde P-Cardio-data. Koppel eerst data op de pagina **Data koppelen**."
            if alleen_met_data
            else "Nog geen opnames. Start er een op de pagina **Live opname** of **Data koppelen**.",
        )
        return None
    # Opties zijn de (stabiele) id's, zodat de keuze blijft staan als het label verandert.
    per_id = {o.info.id: o for o in opnames}
    ids = list(per_id)
    if st.session_state.get(key) not in ids:
        st.session_state.pop(key, None)
    gekozen = st.selectbox("Opname", ids, format_func=lambda i: opname_label(per_id[i]), key=key)
    return per_id[gekozen]


@st.cache_resource(show_spinner="Signalen laden…", max_entries=4)
def _laad_signalen(map: str, versie: int) -> dict[str, Signaal]:
    return Opname.laad(map).laad_signalen()


def _signalen_versie(opname: Opname) -> int:
    meta = opname.signalen_map / "signalen.json"
    return meta.stat().st_mtime_ns if meta.exists() else 0


def laad_signalen(opname: Opname) -> dict[str, Signaal]:
    """Gecachet op de wijzigingstijd van de signalen, zodat opnieuw koppelen meteen zichtbaar is."""
    return _laad_signalen(str(opname.map), _signalen_versie(opname))


@st.cache_data(show_spinner=False, max_entries=4)
def _overzicht(map: str, signalen_versie: int, annotaties_versie: int, klokcorrectie_s: float | None) -> go.Figure:
    return overzicht(_laad_signalen(map, signalen_versie), Opname.laad(map))


def overzicht_figuur(opname: Opname, venster: tuple[pd.Timestamp, pd.Timestamp]) -> go.Figure:
    """Overzicht van de hele opname, gecachet: opbouwen kost ruim een seconde en gebeurt anders bij elke rerun.
    Opnieuw opgebouwd na nieuwe signalen, annotaties of klokcorrectie. Het rode vensterkader komt er elke keer bij."""
    fig = _overzicht(
        str(opname.map), _signalen_versie(opname), annotatie_versie(opname), opname.info.klokcorrectie_s,
    )
    markeer_venster(fig, venster)
    return fig


def annotatie_versie(opname: Opname) -> int:
    # ponytail: versie van de hele database, dus ook andere opnames maken de cache ongeldig; prima bij deze omvang
    return versie(opname.root)


def klok(tijd: pd.Timestamp, tienden: bool = False) -> str:
    tekst = tijd.tz_convert(WEERGAVE_TZ).strftime("%H:%M:%S.%f" if tienden else "%H:%M:%S")
    return tekst[:-5] if tienden else tekst


def knoppenraster(labels: list[str], sleutel: str, callback=None, actief: str | None = None, per_rij: int = 4) -> str | None:
    """Knoppen in een raster. Met ``callback`` wordt die bij een klik aangeroepen met het label (vóór de rerun);
    de functie geeft ook het label van de aangeklikte knop terug, of None."""
    geklikt = None
    for begin in range(0, len(labels), per_rij):
        for kolom, label in zip(st.columns(per_rij), labels[begin:begin + per_rij]):
            if kolom.button(
                label,
                key=f"{sleutel}_{label}",
                on_click=callback,
                args=(label,) if callback else None,
                type="primary" if label == actief else "secondary",
                width="stretch",
            ):
                geklikt = label
    return geklikt


def toon_meldingen() -> None:
    """Meldingen die een callback heeft klaargezet (callbacks kunnen zelf niets tonen)."""
    for soort, tekst in st.session_state.pop("meldingen", []):
        getattr(st, soort)(tekst)


def meld(soort: str, tekst: str) -> None:
    st.session_state.setdefault("meldingen", []).append((soort, tekst))


def relatief(pad: Path) -> str:
    try:
        return str(pad.relative_to(DATA_ROOT.parent))
    except ValueError:
        return str(pad)


def link(pagina: str, label: str) -> None:
    """Link naar een andere pagina (pad zoals in app.py, bijv. 'paginas/live.py').

    Valt terug op gewone tekst als de pagina niet in de navigatie staat, bijv. als een pagina los getest wordt.
    """
    try:
        st.page_link(pagina, label=label)
    except StreamlitPageNotFoundError:
        st.markdown(f"Ga naar: **{label}**")


@st.cache_resource
def live_houder() -> SimpleNamespace:
    """Eén live sessie voor de hele app (de dongle kan maar één verbinding aan), gedeeld door alle pagina's en
    tabbladen. Bij het afsluiten van de app wordt de verbinding netjes verbroken en de poort vrijgegeven."""
    houder = SimpleNamespace(sessie=None)
    atexit.register(lambda: houder.sessie and houder.sessie.sluit())
    return houder


def live_sessie() -> LiveSessie | None:
    houder = live_houder()
    # Na een code-wijziging laadt Streamlit de module opnieuw, maar de bewaarde sessie is nog van de oude klasse
    # (en mist dan bijv. nieuwe attributen). Die netjes sluiten; daarna verbind je opnieuw.
    if houder.sessie is not None and not isinstance(houder.sessie, LiveSessie):
        oud, houder.sessie = houder.sessie, None
        with suppress(Exception):  # de oude sessie mag de app niet laten vallen
            oud.sluit()
    return houder.sessie


def live_ecg_figuur(sessie: LiveSessie, venster_s: float, filter: bool = True, netbrom: bool = False,
                    y_bereik: float | None = None, hoogte: int = 420) -> go.Figure | None:
    t, waarden = sessie.buffer.lees()
    if len(t) < 2:
        return None
    return live_ecg(t, waarden, sessie.buffer.kanalen, sessie.buffer.fs, venster_s, filter, netbrom, y_bereik, hoogte)


@st.fragment(run_every=0.5)
def live_ecg_compact() -> None:
    """Klein live-ECG (5 s) voor op andere pagina's. Verbinden en starten gebeurt op de pagina Live ECG."""
    sessie = live_sessie()
    if sessie is not None and sessie.verbroken:
        # Weggelopen van de laptop? Hier zie je dat, en kun je zonder van pagina te wisselen opnieuw verbinden.
        tekst, knop = st.columns([4, 1], vertical_alignment="center")
        tekst.warning(sessie.melding[1] if sessie.melding else "Verbinding met de recorder verbroken.")
        if sessie.herverbindt:
            knop.button("Stop met opnieuw verbinden", on_click=sessie.stop_herverbinden, width="stretch")
        else:
            knop.button("Opnieuw verbinden", on_click=sessie.herverbind, type="primary", width="stretch")
        return
    if sessie is not None and sessie.logt is not None:
        bijgewerkt = "" if sessie.toestand == "streamen" else " (gelezen bij het verbinden)"
        if sessie.logt:
            st.success(f"Recorder: **neemt op**{bijgewerkt}")
        else:
            st.warning(f"Recorder: **neemt NIET op**{bijgewerkt}. Houd de knop op de P-Cardio 1-3 s ingedrukt "
                       "om te starten (lampje groen).")
    if sessie is None or sessie.toestand != "streamen":
        link("paginas/live_ecg.py", "Live ECG bekijken (verbinden met de dongle)")
        return
    if sessie.lead_off:
        st.warning("Lead-off: een elektrode zit los of maakt slecht contact.")
    fig = live_ecg_figuur(sessie, 5.0, hoogte=220)
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key="live_ecg_compact", config={"displayModeBar": False})
        live_beweging_weergave(sessie, 5.0, hoogte=180)


def live_beweging_weergave(sessie: LiveSessie, venster_s: float, hoogte: int = 220) -> None:
    """Onder het live-ECG: activiteit en houding (UC-1, laatste 20 s) en, als aangezet, de acc- en gyro-plot.
    Leest de keuzes ``live_bevestiging``, ``live_acc`` en ``live_gyro`` uit de session state."""
    if sessie.acc is not None:
        tijd, acc = sessie.acc_buffer.lees()
        bevestiging = st.session_state.get("live_bevestiging", "sticker")
        # Elke LIVE_STAP_S opnieuw bepalen (glijdend venster, AI-01), niet bij elke verversing van de plot.
        vorige = st.session_state.get("live_beweging")
        if (vorige is None or vorige[1] != bevestiging or vorige[2]["activiteit"] == "onbekend"
                or len(tijd) == 0 or not 0 <= tijd[-1] - vorige[0] < LIVE_STAP_S):  # < 0: nieuwe stream
            st.session_state.live_beweging = (tijd[-1] if len(tijd) else 0.0, bevestiging,
                                              beweging_nu(tijd, acc, sessie.acc_buffer.fs, bevestiging))
        nu = st.session_state.live_beweging[2]
        vorige_houding = st.session_state.get("live_houding")
        houding, graden = houding_nu(tijd, acc, sessie.acc_buffer.fs, bevestiging, vorige_houding)
        st.session_state.live_houding = houding
        houding_tekst = (f"{houding} ({graden:.0f}°, laatste {HOUDING_LIVE_S} s)" if bevestiging == "sticker"
                         and pd.notna(graden) else "onbekend (lanyard)" if bevestiging != "sticker" else "nog even…")
        activiteit_tekst = (f"nog {SEGMENT_S - len(tijd) / sessie.acc_buffer.fs:.0f} s data verzamelen…"
                            if nu["activiteit"] == "onbekend"
                            else f"{nu['activiteit']} (laatste {SEGMENT_S} s, elke {LIVE_STAP_S} s)")
        st.markdown(f"**Houding:** {houding_tekst} · **Activiteit:** {activiteit_tekst}", help=hulp.BEWEGING)
    t_laatste = sessie.buffer.lees()[0][-1]
    for naam, eenheid, buffer in (("acc", "g", sessie.acc_buffer), ("gyro", "°/s", sessie.gyro_buffer)):
        if not st.session_state.get(f"live_{naam}"):
            continue
        t, w = buffer.lees()
        if len(t) < 2:
            st.caption(f"Geen {naam}-data: staat die in de configuratie van de recorder?")
            continue
        st.plotly_chart(
            live_beweging(t, w, buffer.kanalen, venster_s, naam, eenheid, t_laatste, hoogte),
            width="stretch", key=f"live_{naam}_plot", config={"displayModeBar": False},
        )


LOGO = Path(__file__).resolve().parent / "assets" / "appbakkers_logo.png"

# Wat config.toml ([theme]) niet kan: kerncijfers in het kopfont en kaarten met een zachte schaduw.
_HUISSTIJL = """
<style>
[data-testid="stMetricValue"] {
    font-family: "Bricolage Grotesque", sans-serif; font-weight: 800; color: #1E6F80;
}
[data-testid="stMetricLabel"] p {
    font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.8rem; color: #1E6F80;
}
[data-testid="stExpander"] details, [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stForm"] {
    background: #FBFEFF; border: none; box-shadow: 0 2px 12px rgba(20, 82, 95, 0.08);
}
</style>
"""


def huisstijl() -> None:
    """AppBakkers-huisstijl; één keer per pagina, vanuit app.py."""
    st.html(_HUISSTIJL)
    st.logo(str(LOGO), size="large")  # linksboven in de zijbalk
