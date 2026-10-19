"""Gecombineerde export: ECG, 6 leads, beweging en annotaties per sample in één CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import hulp
from kern.export import gecombineerd
from ui import kies_opname, klok, laad_signalen, relatief

MAX_DOWNLOAD_MB = 200

st.title("Export", help=hulp.EXPORT)
opname = kies_opname("export_opname", alleen_met_data=True)
if opname is None:
    st.stop()
signalen = laad_signalen(opname)

st.markdown(
    "Eén rij per ECG-sample, met de afgeleide leads, accelerometer, gyroscoop en overige kanalen (gekoppeld aan "
    "de dichtstbijzijnde sample) en de kolommen **activiteit** en **moment** uit de annotaties, omgerekend naar "
    "P-Cardio-tijd.",
)

perioden = [a for a in opname.chronologisch() if a.soort == "periode" and a.t_eind is not None]
bereik = st.radio("Bereik", ["Hele opname", "Eén periode"], horizontal=True, disabled=not perioden, help=hulp.BEREIK)
t0 = t1 = None
naam = "volledig"
if bereik == "Eén periode" and perioden:
    per_id = {a.id: a for a in perioden}
    gekozen = per_id[
        st.selectbox(
            "Periode",
            list(per_id),
            format_func=lambda i: f"{per_id[i].label} · {klok(opname.in_datatijd(per_id[i])[0])}",
        )
    ]
    marge = st.number_input("Marge (s)", 0.0, 120.0, 0.0, 1.0, help=hulp.MARGE_EXPORT)
    start, eind = opname.in_datatijd(gekozen)
    t0, t1 = start - pd.Timedelta(seconds=marge), eind + pd.Timedelta(seconds=marge)
    naam = f"{gekozen.id:03d}_{gekozen.label}".replace(" ", "_").replace("/", "-")
met_zes = st.checkbox("6 leads toevoegen (III, aVR, aVL, aVF)", value=True, help=hulp.ZES_LEADS_EXPORT)

if st.button("Maak export", type="primary", help=hulp.MAAK_EXPORT):
    with st.spinner("Exporteren…"):
        df = gecombineerd(opname, signalen, t0, t1, met_zes_leads=met_zes)
        map_ = opname.map / "export"
        map_.mkdir(exist_ok=True)
        pad = map_ / f"{opname.info.id}_{naam}.csv"
        df.to_csv(pad, index=False)
        annotaties_pad = map_ / f"{opname.info.id}_annotaties.csv"
        opname.annotaties_df().to_csv(annotaties_pad, index=False)
    st.session_state.export = {"pad": str(pad), "annotaties": str(annotaties_pad), "rijen": len(df),
                               "voorbeeld": df.head(20)}

export = st.session_state.get("export")
if export and export["pad"].startswith(str(opname.map)):
    pad = Path(export["pad"])
    grootte_mb = pad.stat().st_size / 1e6
    st.success(f"{export['rijen']:,} rijen geschreven naar `{relatief(pad)}` ({grootte_mb:.0f} MB).")
    st.dataframe(export["voorbeeld"], width="stretch")
    links, rechts = st.columns(2)
    if grootte_mb <= MAX_DOWNLOAD_MB:
        links.download_button("Download export", pad.read_bytes(), file_name=pad.name, mime="text/csv")
    else:
        links.caption("Te groot om via de browser te downloaden; open het bestand direct vanaf de schijf.")
    annotaties_pad = Path(export["annotaties"])
    rechts.download_button(
        "Download annotaties", annotaties_pad.read_bytes(), file_name=annotaties_pad.name, mime="text/csv",
        help=hulp.DOWNLOAD_ANNOTATIES,
    )
