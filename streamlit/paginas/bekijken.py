"""Opname bekijken per periode, moment of vrij venster, en annotaties nalopen, corrigeren of toevoegen."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import hulp
from kern.lijsten import lees_lijst
from kern.opslag import BEOORDELINGEN, WEERGAVE_TZ, Annotatie
from kern.plots import DetailOpties, detail, ecg_kanaalkeuzes, selectie_tijden
from ui import (
    annotatie_versie, kies_opname, klok, knoppenraster, laad_signalen, meld, overzicht_figuur, toon_meldingen,
)

ANDERS = "Anders…"
MIN_VENSTER_S, MAX_VENSTER_S = 1.0, 900.0
# Een annotatie openen toont het begin; lange perioden bekijk je in het overzicht of door verder te scrollen.
MAX_ANNOTATIE_VENSTER_S = 60.0

st.title("Bekijken & annoteren", help=hulp.BEKIJKEN)
toon_meldingen()

opname = kies_opname("bekijk_opname", alleen_met_data=True)
if opname is None:
    st.stop()
signalen = laad_signalen(opname)
if not signalen:
    st.error("De signalen van deze opname konden niet geladen worden. Koppel de data opnieuw.")
    st.stop()

referentie = signalen.get("ecg") or next(iter(signalen.values()))
d0, d1 = referentie.start, referentie.eind
duur_s = (d1 - d0).total_seconds()
# Kloktijd van het begin, voor de scrollbalk (ponytail: bij een zomertijdwissel in de opname loopt die een uur mis).
begin_klok: datetime = d0.tz_convert(WEERGAVE_TZ).tz_localize(None).to_pydatetime()

with st.sidebar:
    st.header("Weergave", help=hulp.WEERGAVE)
    keuzes = ecg_kanaalkeuzes(signalen["ecg"]) if "ecg" in signalen else []
    opties = DetailOpties(
        ecg_kanalen=tuple(
            st.multiselect(
                "ECG-kanalen",
                keuzes,
                default=keuzes[:1],
                format_func=lambda k: {"I": "I (= Ecg1)", "II": "II (= Ecg2)"}.get(k, k),
                help=hulp.ECG_KANALEN,
            ),
        ),
        filter=st.toggle("ECG-filter 0,5–40 Hz (alleen weergave)", value=True, help=hulp.FILTER),
        acc=st.toggle("Accelerometer", value=False, help=hulp.ACC),
        gyro=st.toggle("Gyroscoop", value=False, help=hulp.GYRO),
        overig=st.toggle("Overige kanalen (lead-off, markers, …)", value=False, help=hulp.OVERIG),
    )
    marge_s = st.number_input("Marge rond een annotatie (s)", 0.0, 120.0, 5.0, 1.0, help=hulp.MARGE)

# --- segment kiezen ---

annotaties = opname.chronologisch()
per_id = {a.id: a for a in annotaties}
opties_segment = ["vrij", *per_id]
sleutel = f"segment_{opname.info.id}"
# Na toevoegen/verwijderen: nieuwe keuze toepassen vóórdat het keuzeveld getekend wordt.
if "segment_naar" in st.session_state:
    st.session_state[sleutel] = st.session_state.pop("segment_naar")
if st.session_state.get(sleutel) not in opties_segment:
    st.session_state[sleutel] = "vrij"


def _beschrijf(keuze: object) -> str:
    if keuze == "vrij":
        return "Vrij venster"
    a = per_id[keuze]
    start, eind = opname.in_datatijd(a)
    tijd = f"{klok(start)}–{klok(eind)}" if eind is not None else klok(start)
    duur = f" ({a.duur_s:.0f} s)" if a.duur_s is not None else ""
    beoordeeld = f" · {a.beoordeling}" if a.beoordeling else ""
    return f"{a.soort} · {a.label} · {tijd}{duur}{beoordeeld}"


def _stap(richting: int) -> None:
    huidige = opties_segment.index(st.session_state[sleutel])
    st.session_state[sleutel] = opties_segment[(huidige + richting) % len(opties_segment)]


vorige, keuze_kol, volgende = st.columns([1, 6, 1])
vorige.button(
    "Vorige", on_click=_stap, args=(-1,), width="stretch", help=hulp.VORIGE_VOLGENDE, shortcut="Shift+Up",
)
keuze_kol.selectbox(
    "Segment", opties_segment, format_func=_beschrijf, key=sleutel, label_visibility="collapsed", help=hulp.SEGMENT,
)
volgende.button(
    "Volgende", on_click=_stap, args=(1,), width="stretch", help=hulp.VORIGE_VOLGENDE, shortcut="Shift+Down",
)

keuze = st.session_state[sleutel]
start_sleutel = f"start_{opname.info.id}"
venster_sleutel = f"venster_{opname.info.id}"
gekozen: Annotatie | None = None
if keuze == "vrij":
    venster_s = st.number_input(
        "Vensterlengte (s)", MIN_VENSTER_S, MAX_VENSTER_S, 10.0, 5.0, key=venster_sleutel, help=hulp.VENSTERLENGTE,
    )
    laatste_start = max(duur_s - venster_s, 0.0)
    huidig = st.session_state.get(start_sleutel)
    start_s = min((huidig - begin_klok).total_seconds() if isinstance(huidig, datetime) else 0.0, laatste_start)
    t0 = d0 + pd.Timedelta(seconds=start_s)
    t1 = t0 + pd.Timedelta(seconds=venster_s)
else:
    gekozen = per_id[keuze]
    start, eind = opname.in_datatijd(gekozen)
    if eind is None:
        eind = start
    t0 = start - pd.Timedelta(seconds=marge_s)
    t1 = min(eind + pd.Timedelta(seconds=marge_s), t0 + pd.Timedelta(seconds=MAX_ANNOTATIE_VENSTER_S))
    if t1 < eind:
        st.caption(
            f"Lange periode: je ziet de eerste {MAX_ANNOTATIE_VENSTER_S:.0f} s. Scroll verder, of bekijk het geheel "
            f"in het overzicht.",
        )
    venster_s = (t1 - t0).total_seconds()
    laatste_start = max(duur_s - venster_s, 0.0)
    start_s = min(max(round((t0 - d0).total_seconds()), 0.0), laatste_start)
    if not (d0 <= start <= d1):
        st.warning(
            "Deze annotatie valt buiten de data. Klopt de klokcorrectie? (Zie **Data koppelen**, stap 3.)",
        )
# De scrollbalk onder de plot toont altijd waar het venster begint.
st.session_state[start_sleutel] = begin_klok + timedelta(seconds=start_s)

if (t1 - t0).total_seconds() > 300:
    st.caption("Lang venster: de signalen worden uitgedund weergegeven (pieken blijven zichtbaar). Zoom in de plot in.")

# --- plots ---


def _reset_assen() -> None:
    """Nieuwe plot-sleutel: Streamlit tekent de plot opnieuw, zonder zoom en zonder selectie."""
    st.session_state.plot_versie = st.session_state.get("plot_versie", 0) + 1


def _scroll(venster_s: float) -> None:
    """Scrollen vanuit een annotatie gaat verder als vrij venster van dezelfde lengte."""
    if st.session_state[sleutel] != "vrij":
        st.session_state[venster_sleutel] = min(max(venster_s, MIN_VENSTER_S), MAX_VENSTER_S)
        st.session_state[sleutel] = "vrij"


def _verschuif(stap_s: float, venster_s: float) -> None:
    """Eén venster terug of verder, begrensd tot de opname."""
    _scroll(venster_s)
    nieuw = st.session_state[start_sleutel] + timedelta(seconds=stap_s)
    st.session_state[start_sleutel] = min(max(nieuw, begin_klok), begin_klok + timedelta(seconds=laatste_start))


def _voeg_toe(soort: str, label: str, begin: pd.Timestamp, eind: pd.Timestamp | None, opmerking: str = "") -> None:
    """Nieuwe annotatie in P-Cardio-tijd. Het venster blijft staan, zodat je meteen het volgende stuk kunt doen."""
    try:
        nieuw = opname.voeg_toe(soort, label, begin, eind, tijdbasis="data", opmerking=opmerking)
    except ValueError as fout:
        st.error(str(fout))
        return
    _reset_assen()  # wist ook de selecties
    meld("success", f"{nieuw.soort.capitalize()} '{nieuw.label}' toegevoegd.")
    st.rerun()


def _periode_label(s: str) -> str | None:
    """Labelknoppen plus een eigen label. Geeft het gekozen label terug, of None."""
    st.markdown("**Label**", help=hulp.LABEL_KNOPPEN)
    geklikt = knoppenraster(lees_lijst("activiteiten"), f"{s}_label")
    eigen_kol, knop_kol = st.columns([3, 1], vertical_alignment="bottom")
    eigen = eigen_kol.text_input(
        "Eigen label", key=f"{s}_eigen", placeholder="Eigen label voor deze situatie…",
    ).strip()
    if knop_kol.button("Toevoegen", type="primary", key=f"{s}_eigen_toevoegen", width="stretch"):
        if eigen:
            geklikt = eigen
        else:
            st.error("Typ eerst een eigen label, of klik op een van de labels hierboven.")
    return geklikt


def _kloktijd(tekst: str) -> pd.Timestamp:
    """'17:20:05' (of '17:20') -> tijdstip op de dag van de opname, in UTC. Na middernacht: de volgende dag."""
    tekst = tekst.strip()
    try:
        tijd = datetime.strptime(tekst, "%H:%M:%S" if tekst.count(":") == 2 else "%H:%M").time()
    except ValueError:
        raise ValueError(f"'{tekst}' is geen kloktijd. Typ bijvoorbeeld {klok(d0)}.") from None
    begin_dag = d0.tz_convert(WEERGAVE_TZ)
    tijdstip = pd.Timestamp.combine(begin_dag.date(), tijd).tz_localize(WEERGAVE_TZ)
    if tijdstip < begin_dag.floor("s"):
        tijdstip += pd.Timedelta(days=1)
    return tijdstip.tz_convert("UTC")


def _open_annotatie(tabel_sleutel: str, ids: list[int]) -> None:
    rijen = st.session_state[tabel_sleutel].selection.rows
    if rijen:
        st.session_state[sleutel] = ids[rijen[0]]


with st.expander("Overzicht hele opname", expanded=False):
    st.caption(hulp.OVERZICHT_PLOT)
    plot_versie = st.session_state.get("plot_versie", 0)
    gebeurtenis_overzicht = st.plotly_chart(
        overzicht_figuur(opname, (t0, t1)),
        width="stretch",
        key=f"overzicht_{opname.info.id}_{plot_versie}",
        on_select="rerun",
        selection_mode="box",
    )
    selectie_overzicht = selectie_tijden(gebeurtenis_overzicht.selection if gebeurtenis_overzicht else None)
    # Een selectie vult begin en eind in; typen kan ook. Nieuwe sleutels bij een nieuwe selectie.
    s = f"overzicht_{plot_versie}_" + ("_".join(str(t.value) for t in selectie_overzicht) if selectie_overzicht else "")
    links, rechts = st.columns(2)
    begin_tekst = links.text_input(
        "Begin periode (uu:mm:ss)", value=klok(max(selectie_overzicht[0], d0)) if selectie_overzicht else "",
        placeholder=klok(d0), key=f"{s}_begin", help=hulp.KLOKTIJD_INVOER,
    )
    eind_tekst = rechts.text_input(
        "Eind periode (uu:mm:ss)", value=klok(min(selectie_overzicht[1], d1)) if selectie_overzicht else "",
        placeholder=klok(d1), key=f"{s}_eind", help=hulp.KLOKTIJD_INVOER,
    )
    if begin_tekst.strip() and eind_tekst.strip():
        try:
            begin, eind = _kloktijd(begin_tekst), _kloktijd(eind_tekst)
            begin, eind = max(begin, d0), min(eind, d1)
            if eind <= begin:
                raise ValueError(
                    f"Het eind ligt niet na het begin, of de tijden vallen buiten de opname ({klok(d0)} – {klok(d1)}).",
                )
        except ValueError as fout:
            st.error(str(fout))
        else:
            st.info(
                f"Periode **{klok(begin)} – {klok(eind)}** ({(eind - begin).total_seconds() / 60:.1f} min). "
                f"Klik op een label om hem toe te voegen.",
            )
            label = _periode_label(s)
            if label:
                _voeg_toe("periode", label, begin, eind)
    if annotaties:
        st.markdown("**Annotaties** · klik op een regel om hem hieronder te bekijken")
        tabel_sleutel = f"annotatielijst_{opname.info.id}_{annotatie_versie(opname)}"
        ids = [a.id for a in annotaties]
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "soort": a.soort,
                        "label": a.label,
                        "begin": klok(opname.in_datatijd(a)[0]),
                        "eind": klok(opname.in_datatijd(a)[1]) if a.t_eind is not None else "",
                        "duur (s)": round(a.duur_s) if a.duur_s is not None else None,
                    }
                    for a in annotaties
                ],
            ),
            hide_index=True,
            width="stretch",
            key=tabel_sleutel,
            on_select=lambda: _open_annotatie(tabel_sleutel, ids),
            selection_mode="single-row",
        )

kop, modus, reset = st.columns([3, 2, 1], vertical_alignment="center")
kop.markdown(
    f"**{klok(t0)} – {klok(t1)}**" + (" · ECG gefilterd 0,5–40 Hz (alleen weergave)" if opties.filter else " · ECG ruw"),
    help=hulp.DETAIL_PLOT,
)
selecteren = modus.radio(
    "Slepen in de plot", ["Zoomen", "Selecteren"], horizontal=True, key="sleepmodus", help=hulp.SLEEPMODUS,
) == "Selecteren"
reset.button("Reset assen", on_click=_reset_assen, width="stretch", help=hulp.RESET_ASSEN)

figuur = detail(signalen, opname, t0, t1, opties, selecteren=selecteren)
# Zoom blijft staan bij het wisselen van sleepmodus; een nieuw venster begint weer zonder zoom.
figuur.update_layout(uirevision=f"{t0.value}_{t1.value}")
gebeurtenis = st.plotly_chart(
    figuur,
    width="stretch",
    key=f"detail_{opname.info.id}_{st.session_state.get('plot_versie', 0)}",
    on_select="rerun",
    selection_mode="box",
)
selectie = selectie_tijden(gebeurtenis.selection if gebeurtenis else None)
if selectie is not None:
    selectie = (max(selectie[0], t0), min(selectie[1], t1))
    if selectie[1] <= selectie[0]:
        selectie = None

if laatste_start > 0:
    terug, schuif, verder = st.columns([1, 8, 1], vertical_alignment="bottom")
    terug.button(
        "◀ Terug", on_click=_verschuif, args=(-venster_s, venster_s), width="stretch", help=hulp.TERUG_VERDER,
        shortcut="Shift+Left",
    )
    verder.button(
        "Verder ▶", on_click=_verschuif, args=(venster_s, venster_s), width="stretch", help=hulp.TERUG_VERDER,
        shortcut="Shift+Right",
    )
    schuif.slider(
        "Scrollen door de opname (kloktijd)",
        begin_klok,
        begin_klok + timedelta(seconds=laatste_start),
        step=timedelta(seconds=1),
        format="HH:mm:ss",
        key=start_sleutel,
        on_change=_scroll,
        args=(venster_s,),
        help=hulp.SCROLLBALK,
    )
    st.caption(
        f"Venster **{klok(t0)} – {klok(t1)}** (kloktijd) · {start_s:.0f} s van {duur_s:.0f} s "
        f"({start_s / duur_s:.0%} van de opname) · opname loopt van {klok(d0)} tot {klok(d1)}",
    )

# --- annotatie nalopen ---


def _label_kiezer(soort: str, huidig: str, sleutel_: str) -> str:
    lijst = lees_lijst("activiteiten" if soort == "periode" else "momenten")
    keuzes = [*([huidig] if huidig and huidig not in lijst else []), *lijst, ANDERS]
    index = keuzes.index(huidig) if huidig in keuzes else 0
    keuze_ = st.selectbox("Label", keuzes, index=index, key=f"{sleutel_}_keuze", help=hulp.LABEL)
    if keuze_ == ANDERS:
        return st.text_input("Eigen label", key=f"{sleutel_}_eigen").strip()
    return keuze_


if gekozen is not None:
    st.subheader(f"Annotatie: {gekozen.label}", help=hulp.ANNOTATIE)
    versie = annotatie_versie(opname)
    s = f"ann_{gekozen.id}_{versie}"
    links, rechts = st.columns(2)
    with links:
        if gekozen.soort == "sync":
            st.text_input("Label", value=gekozen.label, disabled=True)
            label = gekozen.label
        else:
            label = _label_kiezer(gekozen.soort, gekozen.label, s)
        opmerking = st.text_input("Opmerking", value=gekozen.opmerking, key=f"{s}_opm", help=hulp.OPMERKING)
        verschuif_start = st.number_input(
            "Begin verschuiven (s)", -600.0, 600.0, 0.0, 0.1, key=f"{s}_vs",
            help=hulp.VERSCHUIF_BEGIN,
        )
        verschuif_eind = (
            st.number_input(
                "Eind verschuiven (s)", -600.0, 600.0, 0.0, 0.1, key=f"{s}_ve", help=hulp.VERSCHUIF_EIND,
            )
            if gekozen.t_eind is not None
            else 0.0
        )
    with rechts:
        beoordeling = st.selectbox(
            "Beoordeling signaal",
            BEOORDELINGEN,
            index=BEOORDELINGEN.index(gekozen.beoordeling) if gekozen.beoordeling in BEOORDELINGEN else 0,
            format_func=lambda b: b or "—",
            key=f"{s}_beo",
            help=hulp.BEOORDELING,
        )
        toelichting = st.text_area(
            "Toelichting beoordeling", value=gekozen.beoordeling_opmerking, key=f"{s}_toel", help=hulp.TOELICHTING,
        )

    opslaan, verwijderen = st.columns([1, 1])
    if opslaan.button("Opslaan", type="primary", key=f"{s}_opslaan"):
        try:
            opname.wijzig(
                gekozen.id,
                label=label or gekozen.label,
                opmerking=opmerking,
                beoordeling=beoordeling,
                beoordeling_opmerking=toelichting,
                t_start=gekozen.t_start + pd.Timedelta(seconds=verschuif_start),
                t_eind=(gekozen.t_eind + pd.Timedelta(seconds=verschuif_eind)) if gekozen.t_eind is not None else None,
            )
            meld("success", "Annotatie opgeslagen.")
            st.rerun()
        except ValueError as fout:
            st.error(str(fout))
    with verwijderen.popover("Verwijderen"):
        st.write("Deze annotatie definitief verwijderen?")
        if st.button("Ja, verwijderen", key=f"{s}_weg"):
            opname.verwijder([gekozen.id])
            st.session_state.segment_naar = "vrij"
            meld("success", "Annotatie verwijderd.")
            st.rerun()

# --- nieuwe annotatie ---

with st.expander("Nieuwe annotatie in dit venster", expanded=gekozen is None or selectie is not None):
    st.caption(hulp.NIEUWE_ANNOTATIE)
    venster = (t1 - t0).total_seconds()
    if selectie is not None:
        st.info(
            f"Selectie: **{klok(selectie[0], tienden=True)} – {klok(selectie[1], tienden=True)}** "
            f"({(selectie[1] - selectie[0]).total_seconds():.1f} s). Kies hieronder een label.",
        )
        begin_standaard = round((selectie[0] - t0).total_seconds(), 2)
        eind_standaard = round((selectie[1] - t0).total_seconds(), 2)
    else:
        st.caption("Tip: zet *Slepen in de plot* op **Selecteren** en sleep over het stuk dat je wilt annoteren.")
        begin_standaard, eind_standaard = 0.0, venster
    # Nieuwe sleutels bij een nieuwe selectie of na opslaan, zodat de velden de nieuwe waarden overnemen.
    s = f"nieuw_{annotatie_versie(opname)}_{selectie[0].value if selectie else ''}_{selectie[1].value if selectie else ''}"
    soort = st.radio(
        "Soort", ["periode", "moment"], horizontal=True, key=f"nieuw_soort_{opname.info.id}", help=hulp.SOORT,
    )
    links, rechts = st.columns(2)
    begin_s = links.number_input(
        "Begin (s vanaf begin venster)" if soort == "periode" else "Tijdstip (s vanaf begin venster)",
        0.0, venster, begin_standaard, 0.1, key=f"{s}_begin", help=hulp.BEGIN_IN_VENSTER,
    )
    eind_s = (
        rechts.number_input(
            "Eind (s vanaf begin venster)", 0.0, venster, eind_standaard, 0.1, key=f"{s}_eind",
            help=hulp.BEGIN_IN_VENSTER,
        )
        if soort == "periode"
        else None
    )
    opmerking = st.text_input("Opmerking", key=f"{s}_opm", help=hulp.OPMERKING)

    if soort == "periode":
        geklikt = _periode_label(s)
        if geklikt:
            _voeg_toe("periode", geklikt, t0 + pd.Timedelta(seconds=begin_s), t0 + pd.Timedelta(seconds=eind_s), opmerking)
    else:
        label = _label_kiezer("moment", "", s)
        if st.button("Toevoegen", type="primary", key=f"{s}_toevoegen"):
            _voeg_toe("moment", label, t0 + pd.Timedelta(seconds=begin_s), None, opmerking)

# --- alle annotaties ---

st.subheader("Alle annotaties", help=hulp.ALLE_ANNOTATIES)
df = opname.annotaties_df()
if df.empty:
    st.caption("Nog geen annotaties.")
else:
    st.dataframe(
        df[["soort", "label", "t_start_data", "t_eind_data", "duur_s", "tijdbasis", "opmerking", "beoordeling",
            "beoordeling_opmerking"]].rename(columns={"t_start_data": "start (P-Cardio-tijd)",
                                                      "t_eind_data": "eind (P-Cardio-tijd)"}),
        hide_index=True,
        width="stretch",
    )
