"""Live ECG: het signaal van de P-Cardio live bekijken via de 2M BLE-dongle (of een gesimuleerde dongle)."""

from __future__ import annotations

import numpy as np
import streamlit as st

import hulp
from kern import pcardio_protocol as p
from kern.dongle import SerieleDongle, SimDongle, poorten, zoek_dongle
from kern.live_sessie import GEEN_DATA_S, LiveSessie
from ui import live_ecg_figuur, live_houder, live_sessie, meld, toon_meldingen

GESIMULEERD, ECHT = "Gesimuleerd", "Echte dongle"
TOESTANDEN = {
    "los": "niet verbonden",
    "verbinden": "verbinden…",
    "verbonden": "verbonden",
    "streamen": "streamt",
    "bezig": "bezig…",
}
LOG_TONEN = 60


# --- callbacks: draaien vóór de rerun; het echte werk loopt op de achtergrond ---


def _verbind() -> None:
    live_sessie()  # ruimt een sessie van vóór een code-wijziging op
    houder = live_houder()
    if houder.sessie is not None and houder.sessie.verbroken:
        houder.sessie.herverbind()  # zelfde recorder; start de stream weer als die liep
        return
    if houder.sessie is None:
        try:
            if st.session_state.live_modus == GESIMULEERD:
                dongle = SimDongle()
            elif st.session_state.get("live_poort"):
                dongle = SerieleDongle(st.session_state.live_poort)
            else:
                meld("error", "Geen COM-poort gekozen. Zit de dongle in een USB-poort?")
                return
        except ConnectionError as fout:
            meld("error", str(fout))
            return
        houder.sessie = LiveSessie(dongle)
    houder.sessie.op_achtergrond(
        houder.sessie.verbind,
        mac=st.session_state.live_mac.strip() or None,
        mac_omgekeerd=st.session_state.live_mac_omgekeerd,
    )


def _ontkoppel() -> None:
    """Synchroon (± 1 s), zodat de poort echt vrij is voordat er opnieuw verbonden kan worden."""
    houder = live_houder()
    sessie, houder.sessie = houder.sessie, None
    if sessie is not None:
        sessie.sluit()


def _schrijf_config() -> None:
    sessie = live_sessie()
    if sessie is not None:
        sessie.op_achtergrond(sessie.schrijf_config, p.STANDAARD_CONFIG, bevestigd=True)


# --- onderdelen ---


def instellingen() -> None:
    vast = live_sessie() is not None  # verbindingsinstellingen pas na Ontkoppelen te wijzigen
    st.sidebar.subheader("Verbinding")
    modus = st.sidebar.radio("Dongle", [GESIMULEERD, ECHT], index=1, key="live_modus", disabled=vast, help=hulp.LIVE_MODUS)
    if modus == ECHT:
        opties = dict(poorten())
        if not opties:
            st.sidebar.warning("Geen COM-poorten gevonden. Zit de dongle in een USB-poort?")
        if st.session_state.get("live_poort") not in opties:
            st.session_state.live_poort = zoek_dongle()
        st.sidebar.selectbox(
            "Poort", list(opties), format_func=lambda poort: opties[poort], key="live_poort", disabled=vast,
            help=hulp.LIVE_POORT,
        )
    st.sidebar.text_input("MAC-adres recorder (optioneel)", key="live_mac", disabled=vast, help=hulp.LIVE_MAC)
    st.sidebar.checkbox("MAC-bytes omgekeerd", key="live_mac_omgekeerd", disabled=vast, help=hulp.LIVE_MAC_OMGEKEERD)
    st.sidebar.checkbox("Automatisch opnieuw verbinden", value=True, key="live_auto", help=hulp.LIVE_AUTO)

    st.sidebar.subheader("Weergave")
    st.sidebar.radio("Venster", [5, 10], index=1, format_func=lambda s: f"{s} s", key="live_venster",
                     horizontal=True, help=hulp.LIVE_VENSTER)
    if st.sidebar.radio("Y-schaal", ["auto", "vast"], key="live_yschaal", horizontal=True, help=hulp.LIVE_YSCHAAL) == "vast":
        st.sidebar.number_input("± mV", min_value=0.1, max_value=500.0, value=2.0, step=0.5, key="live_ybereik")
    st.sidebar.checkbox("Filter 0,5–40 Hz", value=True, key="live_filter", help=hulp.LIVE_FILTER)
    st.sidebar.checkbox("50 Hz-notch", value=False, key="live_netbrom", help=hulp.LIVE_NETBROM)


@st.fragment(run_every=0.5)
def bediening() -> None:
    toon_meldingen()  # hier, want een klik in een fragment ververst alleen het fragment
    sessie = live_sessie()
    toestand = sessie.toestand if sessie else "los"
    bezig = sessie is not None and sessie.bezig
    if sessie is not None:
        sessie.automatisch_herverbinden = st.session_state.get("live_auto", True)
    verbroken = sessie is not None and sessie.verbroken

    verbind, start, stop, ontkoppel = st.columns(4)
    verbind.button("Opnieuw verbinden" if verbroken else "Verbinden", on_click=_verbind,
                   disabled=toestand != "los" or bezig, type="primary", width="stretch",
                   help=hulp.LIVE_OPNIEUW if verbroken else hulp.LIVE_VERBINDEN)
    start.button("Start", on_click=lambda: sessie.op_achtergrond(sessie.start), width="stretch", help=hulp.LIVE_START,
                 disabled=toestand != "verbonden" or bezig or sessie.ecg is None)
    stop.button("Stop", on_click=lambda: sessie.op_achtergrond(sessie.stop), width="stretch",
                disabled=toestand != "streamen" or bezig)
    ontkoppel.button("Ontkoppelen", on_click=_ontkoppel, disabled=sessie is None, width="stretch",
                     help=hulp.LIVE_ONTKOPPELEN)

    if sessie is None:
        st.caption("Niet verbonden.")
        return
    if sessie.herverbindt:
        st.button("Stop met opnieuw verbinden", on_click=sessie.stop_herverbinden)
    if sessie.dongle.fout:
        st.error(sessie.dongle.fout + " Klik op **Ontkoppelen** en verbind opnieuw.")
    if sessie.melding:
        getattr(st, sessie.melding[0])(sessie.melding[1])
    status(sessie)
    if toestand == "verbonden" and sessie.ecg is None and not bezig:
        with st.popover("ECG-configuratie schrijven…", help=hulp.LIVE_CONFIG):
            st.write(f"Schrijft naar de recorder: {p.config_tekst(p.STANDAARD_CONFIG)}.")
            st.write("De recorder gebruikt deze configuratie daarna ook als hij zelf logt.")
            st.button("Ja, schrijven", on_click=_schrijf_config, type="primary")


def status(sessie: LiveSessie) -> None:
    info = sessie.info
    dongle = sessie.dongle.status.omschrijving if sessie.dongle.status else "?"
    batterij = sessie.batterij if sessie.batterij is not None else (info.batterij if info else None)
    kolommen = st.columns(6)
    toestand = ("opnieuw verbinden…" if sessie.herverbindt else "verbinding kwijt" if sessie.verbroken
                else TOESTANDEN.get(sessie.toestand, sessie.toestand))
    kolommen[0].metric("Toestand", toestand, help=f"Dongle: {dongle}")
    kolommen[1].metric("Batterij", f"{batterij} %" if batterij is not None else "–")
    kolommen[2].metric("Firmware", info.firmware if info else "–")
    kolommen[3].metric("Hardware", info.hw_tekst if info else "–")
    kolommen[4].metric(
        "Recorder", {True: "neemt op", False: "neemt NIET op"}.get(sessie.logt, "–"), help=hulp.LIVE_LOGT,
    )
    t = sessie.tellers
    kolommen[5].metric(
        "Pakketten", t["pakketten"], help=hulp.LIVE_TELLERS,
        delta=f"{t['crc_fout']} CRC · {t['onvolledig']} onvolledig · {t['tijdgaten']} gaten",
        delta_color="off" if not (t["crc_fout"] or t["onvolledig"] or t["tijdgaten"]) else "inverse",
    )
    if info:
        st.caption(f"Configuratie: {p.config_tekst(sessie.configs) or 'leeg'}")

    lead_off = sessie.lead_off if sessie.toestand == "streamen" else (info.lead_off if info else None)
    if lead_off:
        st.warning("Lead-off: een elektrode zit los of maakt slecht contact.")
    elif sessie.toestand == "streamen" and _verzadigd(sessie):
        st.warning("Het ECG zit tegen de rand van het meetbereik: zitten de elektroden goed op de huid?")
    stil = sessie.seconden_zonder_data
    if stil is not None and stil > GEEN_DATA_S:
        st.warning(f"Al {stil:.0f} s geen data van de recorder. Buiten bereik? Probeer **Stop** en **Start**.")


def _verzadigd(sessie: LiveSessie) -> bool:
    """Meer dan de helft van de laatste seconde tegen de rand van het meetbereik (alleen tijdens streamen)."""
    laatste = sessie.buffer.lees()[1][-sessie.ecg.rate:]
    grens = 0.999 * sessie.ecg.datatype.analoog_max / sessie.ecg.gain
    return len(laatste) > 0 and float(np.mean(np.abs(laatste) >= grens)) > 0.5


@st.fragment(run_every=0.25)
def grafiek() -> None:
    sessie = live_sessie()
    if sessie is None or sessie.toestand != "streamen":
        st.info("Verbind met de recorder en klik op **Start** om het ECG te zien.")
        return
    fig = live_ecg_figuur(
        sessie,
        st.session_state.get("live_venster", 10),
        st.session_state.get("live_filter", True),
        st.session_state.get("live_netbrom", False),
        st.session_state.get("live_ybereik") if st.session_state.get("live_yschaal") == "vast" else None,
    )
    if fig is None:
        st.caption("Wachten op data…")
    else:
        st.plotly_chart(fig, width="stretch", key="live_ecg", config={"displayModeBar": False})


@st.fragment(run_every=1)
def seriele_log() -> None:
    sessie = live_sessie()
    if sessie is None:
        st.caption("Nog geen verbinding.")
        return
    regels = list(sessie.dongle.log)[-LOG_TONEN:]
    st.code("\n".join(f"{richting} {regel[:120]}" for _, richting, regel in regels) or "(leeg)", language=None)
    if sessie.dongle.ongeldige_regels:
        st.caption(f"{sessie.dongle.ongeldige_regels} onleesbare regels genegeerd.")


st.title("Live ECG", help=hulp.LIVE_ECG)
instellingen()
bediening()
grafiek()
with st.expander("Seriële log", icon=":material/terminal:"):
    st.caption(hulp.LIVE_LOG)
    seriele_log()
