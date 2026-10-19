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

from kern.live_sessie import LiveSessie
from kern.opslag import DATA_ROOT, WEERGAVE_TZ, Deelnemers, Opname
from kern.pcardio import Signaal
from kern.plots import live_ecg, markeer_venster, overzicht


@st.cache_data(show_spinner=False, max_entries=1)
def _namen(versie: int) -> dict[str, str]:
    return {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}


def deelnemer_naam(deelnemer_id: str) -> str:
    """Gecachet op de wijzigingstijd van deelnemers.csv: wordt per rerun vaak aangeroepen (keuzelijst met opnames)."""
    pad = Deelnemers(DATA_ROOT).pad
    return _namen(pad.stat().st_mtime_ns if pad.exists() else 0).get(deelnemer_id, deelnemer_id)


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
    pad = opname.map / "annotaties.csv"
    return pad.stat().st_mtime_ns if pad.exists() else 0


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
    if sessie is None or sessie.toestand != "streamen":
        link("paginas/live_ecg.py", "Live ECG bekijken (verbinden met de dongle)")
        return
    if sessie.lead_off:
        st.warning("Lead-off: een elektrode zit los of maakt slecht contact.")
    fig = live_ecg_figuur(sessie, 5.0, hoogte=220)
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key="live_ecg_compact", config={"displayModeBar": False})


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
