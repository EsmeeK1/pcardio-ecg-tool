"""Gecombineerde export: ECG (+ 6 leads), beweging, overige kanalen en annotaties per sample. En terug inlezen."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .opslag import WEERGAVE_TZ, Opname
from .pcardio import _NAAM_OP_KANAAL, Signaal
from .verwerking import ZES_LEADS, knip, magnitude, zes_leads


def gecombineerd(
    opname: Opname,
    signalen: dict[str, Signaal],
    t0: pd.Timestamp | None = None,
    t1: pd.Timestamp | None = None,
    met_zes_leads: bool = True,
) -> pd.DataFrame:
    """Eén rij per ECG-sample. Andere signalen worden gekoppeld aan de dichtstbijzijnde sample.

    Kolommen ``activiteit`` en ``moment`` komen uit de annotaties (omgerekend naar P-Cardio-tijd).
    """
    if not signalen:
        raise ValueError("Geen signalen om te exporteren. Koppel eerst P-Cardio-data aan deze opname.")
    basis_naam = "ecg" if "ecg" in signalen else max(signalen, key=lambda n: signalen[n].fs)
    basis_signaal = signalen[basis_naam]
    basis = basis_signaal.data
    if t0 is not None and t1 is not None:
        basis = knip(basis, t0, t1)
    basis = basis.reset_index(drop=True)

    if basis_naam == "ecg" and met_zes_leads and {"Ecg1", "Ecg2"} <= set(basis_signaal.kanalen):
        leads = zes_leads(basis)
        basis = pd.concat([basis, leads[[k for k in ZES_LEADS if k not in ("I", "II")]]], axis=1)

    for naam, signaal in signalen.items():
        if naam == basis_naam:
            continue
        extra = signaal.data.copy()
        if naam in ("acc", "gyro") and len(signaal.kanalen) >= 3:
            extra[f"{naam}_magnitude"] = magnitude(extra, signaal.kanalen[:3])
        dubbel = [k for k in extra.columns if k != "tijd" and k in basis.columns]
        extra = extra.rename(columns={k: f"{naam}_{k}" for k in dubbel})
        tolerantie = pd.Timedelta(seconds=1.5 / signaal.fs) if np.isfinite(signaal.fs) else None
        basis = pd.merge_asof(basis, extra, on="tijd", direction="nearest", tolerance=tolerantie)

    basis["activiteit"], basis["moment"] = _annotatiekolommen(opname, basis["tijd"])
    basis.insert(1, "t_s", (basis["tijd"] - basis["tijd"].iloc[0]).dt.total_seconds() if len(basis) else [])
    basis["tijd"] = basis["tijd"].dt.tz_convert(WEERGAVE_TZ)
    return basis


def _annotatiekolommen(opname: Opname, tijd: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    activiteit = np.full(len(tijd), "", dtype=object)
    moment = np.full(len(tijd), "", dtype=object)
    if not len(tijd):
        return activiteit, moment
    for annotatie in opname.chronologisch():
        start, eind = opname.in_datatijd(annotatie)
        if annotatie.soort == "periode" and eind is not None:
            i0 = tijd.searchsorted(start, side="left")
            i1 = tijd.searchsorted(eind, side="right")
            if i1 > i0:
                bestaand = activiteit[i0:i1]
                activiteit[i0:i1] = np.where(bestaand == "", annotatie.label, bestaand + " + " + annotatie.label)
        else:
            if start < tijd.iloc[0] or start > tijd.iloc[-1]:
                continue
            i = int(np.argmin(np.abs((tijd - start).dt.total_seconds().to_numpy())))
            moment[i] = annotatie.label if not moment[i] else f"{moment[i]} + {annotatie.label}"
    return activiteit, moment


# --- terug inlezen -----------------------------------------------------------------------------------

# Kolommen die de app zelf (opnieuw) berekent.
_AFGELEID = {"t_s", "III", "aVR", "aVL", "aVF", "acc_magnitude", "gyro_magnitude", "activiteit", "moment"}
# De export bewaart geen eenheden; dit zijn die van de P-Cardio.
_EENHEID = {"ecg": "mV", "emg": "mV", "acc": "g", "gyro": "deg/s", "mag": "", "batterij": "%", "bioz": "Ohm"}


def bestandssoort(pad: str | Path) -> str:
    """'zip', 'annotaties', 'export' of 'pcardio', op basis van extensie en kopregel (niet de bestandsnaam)."""
    pad = Path(pad)
    if pad.suffix.lower() == ".zip":
        return "zip"
    if pad.suffix.lower() == ".csv":
        with pad.open(encoding="utf-8-sig", errors="replace") as bestand:
            kop = bestand.readline()
        if kop.startswith("id,soort,label,"):
            return "annotaties"
        if kop.startswith("tijd,t_s,"):
            return "export"
    return "pcardio"


def lees_export(pad: str | Path) -> list[Signaal]:
    """Signalen uit een ``*_volledig.csv``. Beweging e.d. staat daarin op het ECG-raster (herhaalde waarden)."""
    pad = Path(pad)
    df = pd.read_csv(pad, usecols=lambda k: k not in _AFGELEID)
    df["tijd"] = pd.to_datetime(df["tijd"], format="ISO8601", utc=True)
    groepen: dict[str, list[str]] = {}
    for kolom in df.columns.drop("tijd"):
        naam = next((n for prefix, n in _NAAM_OP_KANAAL if kolom.lower().startswith(prefix)), kolom.lower())
        groepen.setdefault(naam, []).append(kolom)
    return [
        Signaal(
            naam,
            df[["tijd", *kolommen]].dropna(subset=kolommen, how="all").reset_index(drop=True),
            {k: _EENHEID.get(naam, "") for k in kolommen},
            pad.name,
        )
        for naam, kolommen in groepen.items()
    ]
