"""UC-1 Beweging bepalen: per segment van 20 s activiteit (rust / beweging, lopen) en houding (rechtop / liggend).

Kopie van de regels uit ``secu-sense-wp4/src/wp4/beweging.py`` (die is hier niet geïnstalleerd). Alleen accelerometer
en gyroscoop; het ECG speelt geen rol. Zitten en staan worden bewust niet onderscheiden: met de recorder op de borst
zijn beide rechtop (UC-1, "Geen zitten of staan").
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import welch

from .verwerking import knip, magnitude

SEGMENT_S = 20  # AI-01
LIVE_STAP_S = 5  # AI-01: live schuift het venster van 20 s elke x s op (richtwaarde)
MIN_DEKKING = 0.9  # minder samples dan dit deel van een segment: activiteit onbekend
STAP_HZ = (1.2, 2.8)  # stapfrequentie bij lopen
RECHTOP = np.array([-1.0, 0.0, 0.0])  # zwaartekracht bij rechtop met sticker: x-as van de recorder omlaag
OMGEKEERD_GRADEN = 135  # verder dan dit van rechtop: recorder zit omgekeerd, houding onbekend
BEWEGING_G = 0.029  # sd van |acc| boven deze waarde: beweging (notebook 01: beste drempel sticker 0,028 g)
LIGGEND_GRADEN = 45.0  # kanteling boven deze waarde: liggend (B4)
# ponytail: 0,33 voor sticker komt uit notebook 01 v0.2 (wp4 heeft nog 0,41, mist bijna al het lopen);
# gelijktrekken met wp4.beweging zodra 02 de drempel leave-one-out heeft getoetst.
STAP_AANDEEL = {"sticker": 0.33, "lanyard": 0.41}
ACC = ["AccX", "AccY", "AccZ"]
GYRO = ["GyrX", "GyrY", "GyrZ"]
KOLOMMEN = ["start", "eind", "acc_sd", "gyro_sd", "stap_hz", "stap_aandeel", "kanteling"]


def kenmerken(acc: pd.DataFrame, gyro: pd.DataFrame | None, fs: float) -> dict[str, float]:
    """Kenmerken van één segment. ``acc`` in g, ``gyro`` in °/s."""
    am = pd.Series(magnitude(acc, ACC)).interpolate(limit_direction="both").to_numpy()
    zw = np.nanmean(acc[ACC].to_numpy(dtype=float), axis=0)
    zw = zw / np.linalg.norm(zw)
    f, p = welch(am - am.mean(), fs=fs, nperseg=min(len(am), int(4 * fs)))
    band = (f >= 0.5) & (f <= 4.0)
    piek = f[band][np.argmax(p[band])]
    totaal = p[band].sum()
    return {
        "acc_sd": float(np.std(am)),
        "gyro_sd": float(np.nanstd(magnitude(gyro, GYRO))) if gyro is not None and len(gyro) else np.nan,
        "stap_hz": float(piek),
        "stap_aandeel": float(p[band & (np.abs(f - piek) <= 0.25)].sum() / totaal) if totaal > 0 else 0.0,
        "kanteling": float(np.degrees(np.arccos(np.clip(zw @ RECHTOP, -1, 1)))),
    }


def beweging_per_segment(acc: pd.DataFrame, gyro: pd.DataFrame | None, fs: float, bevestiging: str) -> pd.DataFrame:
    """Vaste segmenten van 20 s met kenmerken, ``activiteit``, ``lopen`` en ``houding``.

    ``bevestiging``: "sticker" of "lanyard". Aan een lanyard is de stand niet vast: houding dan altijd onbekend.
    """
    stap = pd.Timedelta(seconds=SEGMENT_S)
    t0 = acc["tijd"].iloc[0]
    rijen = []
    for k in range(int((acc["tijd"].iloc[-1] - t0) / stap)):
        start = t0 + k * stap
        a = knip(acc, start, start + stap).dropna(subset=ACC)
        rij = {"start": start, "eind": start + stap}
        if len(a) >= MIN_DEKKING * SEGMENT_S * fs:
            rij |= kenmerken(a, knip(gyro, start, start + stap) if gyro is not None else None, fs)
        rijen.append(rij)
    return _classificeer(pd.DataFrame(rijen, columns=KOLOMMEN), bevestiging)


def beweging_nu(tijd: np.ndarray, acc: np.ndarray, fs: float, bevestiging: str) -> pd.Series:
    """Live (UC-3): activiteit en houding van de laatste ``SEGMENT_S`` uit een ringbuffer (tijden, samples × xyz).

    Te weinig data (net gestart, gaten): activiteit en houding onbekend.
    """
    ok = ~np.isnan(tijd)
    rij = {}
    if ok.sum() >= MIN_DEKKING * SEGMENT_S * fs:
        rij = kenmerken(pd.DataFrame(acc[ok], columns=ACC), None, fs)
    return _classificeer(pd.DataFrame([rij], columns=KOLOMMEN), bevestiging).iloc[0]


def _classificeer(s: pd.DataFrame, bevestiging: str) -> pd.DataFrame:
    bekend = s["acc_sd"].notna()
    beweegt = bekend & (s["acc_sd"] > BEWEGING_G)
    s["activiteit"] = np.where(~bekend, "onbekend", np.where(beweegt, "beweging", "rust"))
    s["lopen"] = beweegt & s["stap_hz"].between(*STAP_HZ) & (s["stap_aandeel"] > STAP_AANDEEL[bevestiging])
    s.loc[s["lopen"], "activiteit"] = "lopen"
    s["houding"] = "onbekend"
    if bevestiging == "sticker":
        s["houding"] = np.select(
            [s["kanteling"] <= LIGGEND_GRADEN, s["kanteling"] <= OMGEKEERD_GRADEN], ["rechtop", "liggend"], "onbekend",
        )
    return s
