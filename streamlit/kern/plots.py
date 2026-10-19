"""Plotly-figuren: overzicht van een hele opname, detail van een segment, controle van de sync-sprong."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .export import _annotatiekolommen
from .opslag import WEERGAVE_TZ, Annotatie, Opname
from .pcardio import Signaal
from .verwerking import FILTER_MARGE_S, ZES_LEADS, SyncResultaat, dun_uit, ecg_filter, knip, magnitude, netbrom_filter, zes_leads

# AppBakkers-huisstijl. Volgorde van het grafiekpalet uit de stijlgids; daarna de extra merktinten (voor de vele
# activiteitlabels). Oranje = wat de aandacht moet trekken (sync-sprong, gekozen venster, gevonden piek).
GRAFIEK = ["#1E6F80", "#FF9806", "#6EC6DA", "#14525F", "#9FDCEB", "#8A4B00"]
_PALET = GRAFIEK + ["#3DBDDC", "#39ADC6", "#399FB4"]
PRIMAIR, DONKER, ORANJE, SUBTIEL, TEKST = "#1E6F80", "#14525F", "#FF9806", "#4A6A72", "#1F2A30"
_RIJHOOGTE = 220
_MIN_HOOGTE = 520  # ook met één kanaal een flinke plot
# Signalen die niet in de plots komen (wel in de export).
NIET_PLOTTEN = {"batterij"}
_MAX_PUNTEN_DETAIL = 65000  # ruim 1 minuut op 1000 Hz zonder uitdunnen
# Bij selecteren stuurt Streamlit alle geselecteerde punten mee naar de server; minder punten houdt dat vlot.
# De gekozen tijden komen uit de randen van het kader en zijn dus even precies.
_MAX_PUNTEN_SELECTEREN = 8000


@dataclass
class DetailOpties:
    # Welke ECG-kanalen getoond worden: namen uit ZES_LEADS (als Ecg1 en Ecg2 er zijn) of de gemeten kanalen.
    # Standaard alleen afleiding I = Ecg1.
    ecg_kanalen: tuple[str, ...] = ("I", "Ecg1")
    filter: bool = True  # alleen weergave; de opgeslagen data blijft ruw
    acc: bool = False
    gyro: bool = False
    overig: bool = False


def ecg_kanaalkeuzes(ecg: Signaal) -> list[str]:
    """ECG-kanalen die getoond kunnen worden: de 6 afleidingen als Ecg1 en Ecg2 er zijn, anders de gemeten kanalen."""
    return list(ZES_LEADS) if {"Ecg1", "Ecg2"} <= set(ecg.kanalen) else list(ecg.kanalen)


def kleur_per_label(labels: list[str]) -> dict[str, str]:
    uniek = sorted(set(labels))
    return {label: _PALET[i % len(_PALET)] for i, label in enumerate(uniek)}


def overzicht(
    signalen: dict[str, Signaal],
    opname: Opname,
    venster: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> go.Figure:
    """Hele opname: ECG-kanaal 1 en |acc|, met de annotaties als gekleurde vlakken."""
    rijen: list[tuple[str, pd.Series, np.ndarray]] = []
    if "ecg" in signalen:
        ecg = signalen["ecg"]
        kanaal = ecg.kanalen[0]
        rijen.append((f"{kanaal} ({ecg.eenheden.get(kanaal, '')})", ecg.data["tijd"], ecg.data[kanaal].to_numpy()))
    if "acc" in signalen:
        acc = signalen["acc"]
        rijen.append(("|acc| (g)", acc.data["tijd"], magnitude(acc.data, acc.kanalen)))
    if not rijen:
        eerste = next(iter(signalen.values()))
        rijen.append((eerste.kanalen[0], eerste.data["tijd"], eerste.data[eerste.kanalen[0]].to_numpy()))

    fig = make_subplots(rows=len(rijen), cols=1, shared_xaxes=True, vertical_spacing=0.04)
    for i, (titel, tijd, waarden) in enumerate(rijen, start=1):
        t, w = dun_uit(tijd, waarden, max_punten=4000)
        fig.add_trace(
            go.Scattergl(x=_lokaal(t), y=w, mode="lines", line={"width": 1, "color": PRIMAIR}, name=titel),
            row=i,
            col=1,
        )
        fig.update_yaxes(title_text=titel, row=i, col=1)

    _teken_annotaties(fig, opname, len(rijen))
    if venster is not None:
        markeer_venster(fig, venster)
    # Slepen selecteert een stuk (voor lange perioden); zoomen kan nog via de knoppen rechtsboven.
    # Een verticale lijn en de kloktijd volgen de muis, zodat je precies weet waar je begint en eindigt.
    fig.update_xaxes(
        tickformat="%H:%M:%S", hoverformat="%H:%M:%S", showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikedash="solid", spikecolor=SUBTIEL,
    )
    fig.update_layout(
        height=120 + 110 * len(rijen),
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        showlegend=False,
        dragmode="select",
        selectdirection="h",
        hovermode="x unified",
        hoverlabel={"namelength": 0},
    )
    return fig


def markeer_venster(fig: go.Figure, venster: tuple[pd.Timestamp, pd.Timestamp]) -> None:
    """Rood kader in het overzicht rond het venster dat in de detailplot staat."""
    fig.add_vrect(
        x0=_lokaal_punt(venster[0]),
        x1=_lokaal_punt(venster[1]),
        fillcolor="rgba(0,0,0,0)",
        line={"color": ORANJE, "width": 2},
        row="all",
        col=1,
    )


def detail(
    signalen: dict[str, Signaal],
    opname: Opname,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    opties: DetailOpties,
    selecteren: bool = False,
) -> go.Figure:
    """Segment van t0 tot t1: ECG-leads, beweging en overige kanalen onder elkaar op één tijdas.

    Met ``selecteren`` maakt slepen een selectiekader (voor een nieuwe annotatie) in plaats van in te zoomen.
    """
    rijen = _detail_rijen(signalen, t0, t1, opties)
    if not rijen:
        fig = go.Figure()
        fig.add_annotation(text="Geen data in dit venster", showarrow=False)
        return fig

    fig = make_subplots(rows=len(rijen), cols=1, shared_xaxes=True, vertical_spacing=0.012)
    for i, (titel, sporen) in enumerate(rijen, start=1):
        for j, (naam, tijd, waarden, kleur) in enumerate(sporen):
            max_punten = _MAX_PUNTEN_SELECTEREN if selecteren else _MAX_PUNTEN_DETAIL
            t, w = dun_uit(tijd.reset_index(drop=True), waarden, max_punten=max_punten)
            fig.add_trace(
                go.Scattergl(x=_lokaal(t), y=w, mode="lines", line={"width": 1, "color": kleur}, name=naam),
                row=i,
                col=1,
            )
            if j == 0:
                _label_spoor(fig, opname, t, w, i)
        fig.update_yaxes(title_text=titel, row=i, col=1, title_font={"size": 11})

    _teken_annotaties(fig, opname, len(rijen), bereik=(t0, t1))
    fig.update_xaxes(range=[_lokaal_punt(t0), _lokaal_punt(t1)])
    fig.update_layout(
        height=max(_MIN_HOOGTE, 60 + _RIJHOOGTE * len(rijen)),
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        showlegend=False,
        hovermode="x unified",
        dragmode="select" if selecteren else "zoom",
        selectdirection="h",
    )
    return fig


def selectie_tijden(selectie: dict | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Laatste selectiekader uit ``st.plotly_chart(on_select=...)`` als (begin, eind) in UTC, of None."""
    boxen = (selectie or {}).get("box") or []
    x = boxen[-1].get("x") if boxen else None
    if not x or len(x) < 2:
        return None
    begin, eind = sorted(_uit_plot(v) for v in x[:2])
    return begin, eind


def _uit_plot(x: object) -> pd.Timestamp:
    """Tijd zoals Plotly die teruggeeft (lokale kloktijd zonder tz) -> UTC. Tegenhanger van ``_lokaal_punt``."""
    ts = pd.Timestamp(x, unit="ms") if isinstance(x, (int, float)) else pd.Timestamp(x)
    return ts.tz_localize(WEERGAVE_TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")


def sync_figuur(acc: Signaal, resultaat: SyncResultaat, zoek_s: float) -> go.Figure:
    venster = knip(
        acc.data,
        resultaat.t_gelogd - pd.Timedelta(seconds=zoek_s),
        resultaat.t_gelogd + pd.Timedelta(seconds=zoek_s),
    )
    fig = go.Figure(
        go.Scattergl(
            x=_lokaal(venster["tijd"]),
            y=magnitude(venster, acc.kanalen),
            mode="lines",
            line={"width": 1, "color": PRIMAIR},
        ),
    )
    fig.add_vline(x=_lokaal_punt(resultaat.t_gelogd), line={"color": SUBTIEL, "dash": "dash"})
    fig.add_vline(x=_lokaal_punt(resultaat.t_piek), line={"color": ORANJE})
    fig.add_annotation(
        x=_lokaal_punt(resultaat.t_gelogd), y=1, yref="paper", text="gelogd", showarrow=False, yanchor="bottom",
    )
    fig.add_annotation(
        x=_lokaal_punt(resultaat.t_piek), y=0.9, yref="paper", text="piek", showarrow=False, font={"color": ORANJE},
    )
    fig.update_layout(
        height=260,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        yaxis_title="|acc| (g)",
        showlegend=False,
    )
    return fig


def _detail_rijen(
    signalen: dict[str, Signaal],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    opties: DetailOpties,
) -> list[tuple[str, list[tuple[str, pd.Series, np.ndarray, str]]]]:
    rijen: list[tuple[str, list[tuple[str, pd.Series, np.ndarray, str]]]] = []

    if "ecg" in signalen:
        ecg = signalen["ecg"]
        # Met filter een stukje extra data meenemen en na het filteren weer afknippen (geen inzwaaien aan de randen).
        marge = pd.Timedelta(seconds=FILTER_MARGE_S if opties.filter else 0.0)
        stuk = knip(ecg.data, t0 - marge, t1 + marge)
        eenheid = ecg.eenheden.get(ecg.kanalen[0], "")
        if {"Ecg1", "Ecg2"} <= set(ecg.kanalen):
            stuk = zes_leads(stuk)
        kanalen = [k for k in ecg_kanaalkeuzes(ecg) if k in opties.ecg_kanalen]
        binnen = ((stuk["tijd"] >= t0) & (stuk["tijd"] <= t1)).to_numpy()
        for kanaal in kanalen:
            waarden = stuk[kanaal].to_numpy(dtype=float)
            if opties.filter:
                waarden = ecg_filter(waarden, ecg.fs)
            rijen.append((f"{kanaal} ({eenheid})", [(kanaal, stuk["tijd"][binnen], waarden[binnen], DONKER)]))

    if opties.acc and "acc" in signalen:
        rijen.append(_beweging(signalen["acc"], t0, t1, "acc", "g"))
    if opties.gyro and "gyro" in signalen:
        rijen.append(_beweging(signalen["gyro"], t0, t1, "gyro", "°/s"))

    if opties.overig:
        for naam, signaal in signalen.items():
            if naam in ("ecg", "acc", "gyro") or naam in NIET_PLOTTEN:
                continue
            stuk = knip(signaal.data, t0, t1)
            sporen = [
                (k, stuk["tijd"], stuk[k].to_numpy(dtype=float), _PALET[j % len(_PALET)])
                for j, k in enumerate(signaal.kanalen)
            ]
            rijen.append((naam, sporen))
    return rijen


def _beweging(
    signaal: Signaal,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    naam: str,
    eenheid: str,
) -> tuple[str, list[tuple[str, pd.Series, np.ndarray, str]]]:
    stuk = knip(signaal.data, t0, t1)
    kleuren = GRAFIEK[:3]
    sporen = [
        (k, stuk["tijd"], stuk[k].to_numpy(dtype=float), kleuren[j % 3])
        for j, k in enumerate(signaal.kanalen[:3])
    ]
    sporen.append((f"|{naam}|", stuk["tijd"], magnitude(stuk, signaal.kanalen[:3]), TEKST))
    return (f"{naam} ({eenheid})", sporen)


def _teken_annotaties(
    fig: go.Figure,
    opname: Opname,
    aantal_rijen: int,
    bereik: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> None:
    annotaties = opname.chronologisch()
    kleuren = kleur_per_label([a.label for a in annotaties if a.soort == "periode"])
    for annotatie in annotaties:
        start, eind = opname.in_datatijd(annotatie)
        if bereik is not None and not _zichtbaar(start, eind, bereik):
            continue
        if annotatie.soort == "periode" and eind is not None:
            fig.add_vrect(
                x0=_lokaal_punt(start),
                x1=_lokaal_punt(eind),
                fillcolor=kleuren[annotatie.label],
                opacity=0.25,
                line_width=0,
                layer="below",
                row="all",
                col=1,
            )
            _label(fig, start, annotatie)
        else:
            stijl = {"color": ORANJE, "dash": "dash"} if annotatie.soort == "sync" else {"color": "#8A4B00"}
            fig.add_vline(x=_lokaal_punt(start), line=stijl, row="all", col=1)
            if annotatie.soort == "periode":
                stijl_tekst = annotatie.label + " (loopt nog)"
                fig.add_annotation(x=_lokaal_punt(start), y=1.0, yref="paper", text=stijl_tekst, showarrow=False)
            else:
                _label(fig, start, annotatie)


def _label_spoor(fig: go.Figure, opname: Opname, t: pd.Series, w: np.ndarray, rij: int) -> None:
    """Onzichtbare punten op het signaal met het label als hovertekst: binnen een periode op elk punt, bij een
    moment op het dichtstbijzijnde punt (zoals de export). Zo staat het label in het hovervenster."""
    activiteit, moment = _annotatiekolommen(opname, t)
    tekst = np.where((activiteit != "") & (moment != ""), activiteit + ", " + moment, activiteit + moment)
    gelabeld = tekst != ""
    if not gelabeld.any():
        return
    fig.add_trace(
        go.Scattergl(
            x=_lokaal(t[gelabeld]),
            y=w[gelabeld],
            mode="markers",
            marker={"opacity": 0, "color": SUBTIEL},
            name="label",
            text=tekst[gelabeld],
            hovertemplate="label: <b>%{text}</b><extra></extra>",
        ),
        row=rij,
        col=1,
    )


def _label(fig: go.Figure, start: pd.Timestamp, annotatie: Annotatie) -> None:
    fig.add_annotation(
        x=_lokaal_punt(start),
        y=1.0,
        yref="paper",
        text=annotatie.label,
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font={"size": 10},
    )


def _zichtbaar(start: pd.Timestamp, eind: pd.Timestamp | None, bereik: tuple[pd.Timestamp, pd.Timestamp]) -> bool:
    eind = eind if eind is not None else start
    return eind >= bereik[0] and start <= bereik[1]


def _lokaal(tijd: pd.Series) -> pd.Series:
    """Plotly kent geen tijdzones: toon als lokale (Nederlandse) kloktijd zonder tz-info."""
    return pd.to_datetime(tijd, utc=True).dt.tz_convert(WEERGAVE_TZ).dt.tz_localize(None)


def _lokaal_punt(tijd: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(tijd).tz_convert(WEERGAVE_TZ).tz_localize(None)


_LIVE_KLEUREN = (PRIMAIR, ORANJE)
_LIVE_SCHAAL_S = 3.0


def live_ecg(
    t: np.ndarray,
    waarden: np.ndarray,
    kanalen: tuple[str, ...],
    fs: float,
    venster_s: float,
    filter: bool = True,
    netbrom: bool = False,
    y_bereik: float | None = None,
    hoogte: int = 420,
) -> go.Figure:
    """Scrollende live-ECG: tijd in seconden t.o.v. de laatste sample (dus van -venster tot 0), amplitude in mV.

    Er wordt gefilterd over de hele buffer en daarna pas geknipt, zodat het filter aan de linkerrand niet inzwaait.
    """
    if netbrom:
        waarden = np.column_stack([netbrom_filter(waarden[:, i], fs) for i in range(waarden.shape[1])])
    if filter:
        waarden = np.column_stack([ecg_filter(waarden[:, i], fs) for i in range(waarden.shape[1])])
    x = t - t[-1]
    binnen = x >= -venster_s
    if y_bereik is None:
        # Robuuste auto-schaal op de laatste seconden: het inzwaaien van de recorder bij de start van de stream
        # (eerste pakket nullen, daarna ± 1,5 s uitdempen) zou de schaal anders een heel venster lang platdrukken.
        recent = waarden[x >= -_LIVE_SCHAAL_S]
        laag, hoog = np.nanpercentile(recent, [0.5, 99.5]) if np.isfinite(recent).any() else (-1.0, 1.0)
        marge = 0.2 * (hoog - laag) + 0.05
        y_as = [laag - marge, hoog + marge]
    else:
        y_as = [-y_bereik, y_bereik]
    fig = go.Figure()
    for i, kanaal in enumerate(kanalen):
        fig.add_scatter(
            x=x[binnen], y=waarden[binnen, i], name=kanaal, mode="lines",
            line={"width": 1.2, "color": _LIVE_KLEUREN[i % len(_LIVE_KLEUREN)]},
        )
    fig.update_layout(
        height=hoogte,
        margin={"l": 50, "r": 10, "t": 10, "b": 40},
        xaxis={"range": [-venster_s, 0], "title": "tijd (s)"},
        yaxis={"title": "mV", "range": y_as},
        legend={"orientation": "h", "y": 1.08},
        uirevision="live",  # zoom en verborgen kanalen blijven staan bij elke verversing
    )
    return fig
