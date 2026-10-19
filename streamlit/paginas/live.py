"""Live opname: perioden, momenten en sync-sprongen loggen met de pc-klok."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import hulp
from kern.lijsten import lees_lijst
from kern.opslag import DATA_ROOT, WEERGAVE_TZ, Deelnemers, Opname, nu
from ui import annotatie_versie, deelnemer_naam, klok, knoppenraster, live_ecg_compact, meld, opname_label, toon_meldingen

STANDAARD_CONFIGURATIE = (
    "ECG 2-kanaals 250 Hz gain x6; Acc 100 Hz x2; Gyro 100 Hz x2; Lead-off 5 Hz; Button Marker 5 Hz; Battery 5 Hz"
)
ELEKTRODE_PLAATSINGEN = ["Optie 1: met sticker", "Optie 2: met lanyard"]
ELEKTRODE_FOTO = Path(__file__).resolve().parents[1] / "assets" / "elektroden_plaatsing.png"


def _opname() -> Opname:
    """Altijd vers van schijf, zodat wijzigingen op andere pagina's niet overschreven worden."""
    return Opname.laad(st.session_state.live_map)


# --- callbacks: draaien vóór de rerun, dus het tijdstempel is het moment van klikken ---


def _start_vrije_periode() -> None:
    label = st.session_state.vrije_periode.strip()
    if not label:
        meld("error", "Vul eerst een omschrijving in voor de periode.")
        return
    _opname().start_periode(label)
    st.session_state.vrije_periode = ""


def _vrij_moment() -> None:
    _opname().moment(st.session_state.vrij_moment.strip() or "markering")
    st.session_state.vrij_moment = ""


def _sluit_scherm() -> None:
    del st.session_state.live_map


def _verwerk_bewerkingen() -> None:
    opname = _opname()
    for positie, wijziging in st.session_state[st.session_state.log_key]["edited_rows"].items():
        velden = {k: (v or "") for k, v in wijziging.items() if k in ("label", "opmerking")}
        if velden:
            opname.wijzig(st.session_state.log_ids[positie], **velden)


def _verwijder_aangevinkt() -> None:
    bewerkingen = st.session_state[st.session_state.log_key]["edited_rows"]
    ids = [st.session_state.log_ids[p] for p, w in bewerkingen.items() if w.get("verwijder")]
    if ids:
        _opname().verwijder(ids)


# --- schermen ---


def startscherm() -> None:
    st.title("Live opname", help=hulp.LIVE)
    deelnemers = Deelnemers(DATA_ROOT).alle()
    nieuw, hervatten = st.tabs(["Nieuwe opname", "Opname hervatten"])

    with nieuw:
        if not deelnemers:
            st.info("Voeg eerst een deelnemer toe op de pagina **Deelnemers**.")
        else:
            per_id = {d.id: d for d in deelnemers}
            with st.form("nieuwe_opname"):
                deelnemer_id = st.selectbox(
                    "Deelnemer", list(per_id), format_func=lambda i: per_id[i].weergave, help=hulp.LIVE_DEELNEMER,
                )
                plaatsing, foto = st.columns([4, 1], vertical_alignment="bottom")
                elektroden = plaatsing.selectbox(
                    "Plaatsing van de elektroden", ELEKTRODE_PLAATSINGEN, help=hulp.ELEKTRODEN,
                )
                with foto.popover("📷 Foto's", width="stretch"):
                    st.image(str(ELEKTRODE_FOTO), caption="Bron: handleiding P-Cardio (2M Engineering)")
                huidvoorbereiding = st.text_input(
                    "Huidvoorbereiding / bijzonderheden (optioneel)", help=hulp.HUIDVOORBEREIDING,
                )
                configuratie = st.text_input(
                    "Meetconfiguratie P-Cardio", value=STANDAARD_CONFIGURATIE, help=hulp.CONFIGURATIE,
                )
                gelijkgezet = st.checkbox(
                    "Tijd van de P-Cardio is vlak voor de opname gelijkgezet met déze pc",
                    help=hulp.GELIJKGEZET,
                )
                notities = st.text_area("Notities", help=hulp.NOTITIES)
                if st.form_submit_button("Start opname", type="primary"):
                    try:
                        opname = Opname.nieuw(
                            per_id[deelnemer_id],
                            nu(),
                            root=DATA_ROOT,
                            elektroden=elektroden,
                            huidvoorbereiding=huidvoorbereiding.strip(),
                            configuratie=configuratie.strip(),
                            pcardio_tijd_gelijkgezet=gelijkgezet,
                            notities=notities.strip(),
                        )
                        st.session_state.live_map = str(opname.map)
                        st.rerun()
                    except ValueError as fout:
                        st.error(str(fout))

    with hervatten:
        open_ = [o for o in Opname.alle(DATA_ROOT) if not o.info.live_afgesloten]
        if not open_:
            st.info("Geen opnames die nog niet afgesloten zijn.")
            return
        open_per_id = {o.info.id: o for o in open_}
        gekozen = st.selectbox(
            "Opname", list(open_per_id), format_func=lambda i: opname_label(open_per_id[i]), help=hulp.HERVATTEN,
        )
        if st.button("Hervat"):
            st.session_state.live_map = str(open_per_id[gekozen].map)
            st.rerun()


@st.fragment(run_every=1)
def status() -> None:
    opname = _opname()
    links, midden, rechts = st.columns([3, 1, 2])
    with links:
        actief = opname.actieve_periode
        if actief is None:
            st.markdown("### Geen periode actief")
            st.caption("Rust / pauze. Klik op een activiteit om een periode te starten.")
        else:
            verstreken = (pd.Timestamp(nu()) - actief.t_start).total_seconds()
            st.markdown(f"### Bezig: {actief.label}")
            st.markdown(f"**{int(verstreken // 60)}:{int(verstreken % 60):02d}** sinds {klok(actief.t_start)}")
    midden.metric("Klok", pd.Timestamp(nu()).tz_convert(WEERGAVE_TZ).strftime("%H:%M:%S"), help=hulp.KLOK)
    with rechts:
        if not opname.syncs:
            st.warning("Nog geen sync-sprong gelogd.")
        else:
            st.success(f"Laatste sync: {klok(opname.syncs[-1].t_start)} ({len(opname.syncs)}×)")
        if not opname.info.pcardio_tijd_gelijkgezet:
            st.caption("Let op: P-Cardio-tijd niet gelijkgezet volgens de opname-gegevens.")


def livescherm() -> None:
    opname = _opname()
    st.title(f"Live opname — {deelnemer_naam(opname.info.deelnemer_id)}")
    st.caption(f"Opname `{opname.info.id}` — elke klik wordt direct opgeslagen.")

    if opname.info.live_afgesloten:
        st.success("Opname afgesloten. Koppel de P-Cardio-data op de pagina **Data koppelen**.")
        st.button("Terug", on_click=_sluit_scherm, type="primary")
        logboek(opname)
        return

    toon_meldingen()
    status()
    live_ecg_compact()

    sync_kol, stop_kol, afsluit_kol = st.columns(3)
    sync_kol.button(
        "Sync-sprong",
        on_click=lambda: _opname().sync(),
        type="primary",
        width="stretch",
        help=hulp.SYNC,
    )
    stop_kol.button(
        "Stop periode",
        on_click=lambda: _opname().stop_periode(),
        disabled=opname.actieve_periode is None,
        width="stretch",
        help=hulp.STOP_PERIODE,
    )
    with afsluit_kol.popover("Opname afsluiten", width="stretch", help=hulp.AFSLUITEN):
        st.write("Stopt een lopende periode en sluit de live opname af.")
        st.button("Ja, afsluiten", on_click=lambda: _opname().sluit_live_af(), type="primary")

    st.subheader("Perioden", help=hulp.PERIODEN)
    actief = opname.actieve_periode.label if opname.actieve_periode is not None else None
    knoppenraster(lees_lijst("activiteiten"), "periode", lambda l: _opname().start_periode(l), actief)
    tekst, knop = st.columns([3, 1])
    tekst.text_input("Andere activiteit", key="vrije_periode", label_visibility="collapsed", placeholder="Andere activiteit…")
    knop.button(
        "Start periode", on_click=_start_vrije_periode, width="stretch", help=hulp.ANDERE_ACTIVITEIT,
    )

    st.subheader("Momenten", help=hulp.MOMENTEN)
    knoppenraster(
        ["Markeer nu", *lees_lijst("momenten")],
        "moment",
        lambda l: _opname().moment("markering" if l == "Markeer nu" else l),
    )
    tekst, knop = st.columns([3, 1])
    tekst.text_input("Ander moment", key="vrij_moment", label_visibility="collapsed", placeholder="Ander moment…")
    knop.button("Markeer", on_click=_vrij_moment, width="stretch", help=hulp.ANDER_MOMENT)

    st.divider()
    logboek(opname)


def logboek(opname: Opname) -> None:
    st.subheader("Logboek", help=hulp.LOGBOEK)
    df = opname.annotaties_df()
    if df.empty:
        st.caption("Nog niets gelogd.")
        return
    df = df.iloc[::-1].reset_index(drop=True)
    tabel = pd.DataFrame(
        {
            "id": df["id"],
            "soort": df["soort"],
            "label": df["label"],
            "start": df["t_start"].str[11:23],
            "eind": df["t_eind"].str[11:23],
            "duur_s": df["duur_s"],
            "opmerking": df["opmerking"],
            "verwijder": False,
        },
    )
    st.session_state.log_ids = tabel["id"].tolist()
    st.session_state.log_key = f"live_log_{annotatie_versie(opname)}"
    st.data_editor(
        tabel,
        key=st.session_state.log_key,
        on_change=_verwerk_bewerkingen,
        hide_index=True,
        width="stretch",
        disabled=["id", "soort", "start", "eind", "duur_s"],
        column_config={
            "id": None,
            "verwijder": st.column_config.CheckboxColumn("verwijder?"),
        },
    )
    st.button("Verwijder aangevinkte regels", on_click=_verwijder_aangevinkt, help=hulp.VERWIJDER_REGELS)


if "live_map" in st.session_state:
    livescherm()
else:
    startscherm()
