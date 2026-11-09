"""UC-1 Beweging bepalen: activiteit (rust / beweging) en houding (rechtop / liggend) uit de accelerometer.

Kopie van de regels uit ``secu-sense-wp4/src/wp4/beweging.py`` (die is hier niet geïnstalleerd), met de uitkomsten
van wp4 notebook 03 (9-11-2026). Het ECG speelt geen rol. Zitten en staan worden bewust niet onderscheiden: met de
recorder op de borst zijn beide rechtop (UC-1, "Geen zitten of staan").

- **Activiteit** per 20 s (AI-01, ook de segmenten van UC-2): spreiding van |acc| boven 0,029 g is beweging. Een
  korter venster vraagt een andere drempel (notebook 03), dus activiteit blijft op 20 s. **Lopen** is beweging met
  een duidelijk stapritme: het maakt de oorzaak in UC-2 en de melding in UC-3 specifiek (UC-1, "Waarom deze
  categorieën"; op 9-11-2026 even geschrapt en dezelfde dag teruggezet).
- **Houding**: hoek tussen de gemiddelde acc-richting (de zwaartekracht) en rechtop. Per 20 s voor het contract en
  Bekijken; live over de laatste 5 s (zelfde score, ± 1 s vertraging in plaats van 12–18 s), met een marge zodat hij
  rond 45° niet heen en weer springt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import welch

from .verwerking import knip, magnitude

SEGMENT_S = 20  # AI-01: segmenten voor activiteit en het contract met de app
LIVE_STAP_S = 5  # live: activiteit elke 5 s opnieuw over de laatste 20 s (AI-01, glijdend venster)
HOUDING_LIVE_S = 5  # live: houding over de laatste 5 s (notebook 03: 99–100% bij elk venster van 2–20 s)
HOUDING_STAP_S = 1  # live: houding elke seconde opnieuw
MIN_DEKKING = 0.9  # minder samples dan dit deel van een venster: onbekend
RECHTOP = np.array([-1.0, 0.0, 0.0])  # zwaartekracht bij rechtop met sticker: x-as van de recorder omlaag
OMGEKEERD_GRADEN = 135  # verder dan dit van rechtop: recorder zit omgekeerd, houding onbekend
BEWEGING_G = 0.029  # sd van |acc| over 20 s boven deze waarde: beweging (notebook 03: beste drempel 0,028 g)
LIGGEND_GRADEN = 45.0  # kanteling boven deze waarde: liggend (B4)
MARGE_GRADEN = 5.0  # live: liggend pas boven 50°, terug naar rechtop pas onder 40° (bukken tot 54° gemeten)
STAP_HZ = (1.2, 2.8)  # stapfrequentie bij lopen
# ponytail: 0,33 voor sticker komt uit notebook 01 v0.2 (wp4 heeft nog 0,41, mist bijna al het lopen);
# gelijktrekken met wp4.beweging zodra 02 de drempel leave-one-out heeft getoetst.
STAP_AANDEEL = {"sticker": 0.33, "lanyard": 0.41}
ACC = ["AccX", "AccY", "AccZ"]
GYRO = ["GyrX", "GyrY", "GyrZ"]
KOLOMMEN = ["start", "eind", "acc_sd", "gyro_sd", "stap_hz", "stap_aandeel", "kanteling"]


def kanteling(acc_xyz: np.ndarray) -> float:
    """Hoek (°) tussen de gemiddelde acc-richting en rechtop; NaN zonder bruikbare data."""
    zw = np.nanmean(np.asarray(acc_xyz, dtype=float), axis=0)
    norm = np.linalg.norm(zw)
    if not np.isfinite(norm) or norm == 0:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(zw / norm @ RECHTOP, -1, 1))))


def houding(graden: float, bevestiging: str, vorige: str | None = None) -> str:
    """rechtop / liggend / onbekend. Met ``vorige`` (live) geldt de marge: van rechtop naar liggend pas boven 50°,
    terug pas onder 40°. Aan een lanyard is de stand niet vast: altijd onbekend."""
    if bevestiging != "sticker" or not np.isfinite(graden) or graden > OMGEKEERD_GRADEN:
        return "onbekend"
    grens = LIGGEND_GRADEN + {"rechtop": MARGE_GRADEN, "liggend": -MARGE_GRADEN}.get(vorige, 0.0)
    return "liggend" if graden > grens else "rechtop"


def kenmerken(acc: pd.DataFrame, gyro: pd.DataFrame | None, fs: float) -> dict[str, float]:
    """Kenmerken van één segment. ``acc`` in g, ``gyro`` in °/s (alleen ter informatie, AI-14)."""
    am = pd.Series(magnitude(acc, ACC)).interpolate(limit_direction="both").to_numpy()
    # Stapritme: hoogste piek in het spectrum van |acc| (0,5–4 Hz) en welk deel van het vermogen daarin zit.
    f, p = welch(am - am.mean(), fs=fs, nperseg=min(len(am), int(4 * fs)))
    band = (f >= 0.5) & (f <= 4.0)
    piek = f[band][np.argmax(p[band])]
    totaal = p[band].sum()
    return {
        "acc_sd": float(np.std(am)),
        "gyro_sd": float(np.nanstd(magnitude(gyro, GYRO))) if gyro is not None and len(gyro) else np.nan,
        "stap_hz": float(piek),
        "stap_aandeel": float(p[band & (np.abs(f - piek) <= 0.25)].sum() / totaal) if totaal > 0 else 0.0,
        "kanteling": kanteling(acc[ACC].to_numpy(dtype=float)),
    }


def beweging_per_segment(acc: pd.DataFrame, gyro: pd.DataFrame | None, fs: float, bevestiging: str) -> pd.DataFrame:
    """Vaste segmenten van 20 s met kenmerken, ``activiteit`` (rust / beweging / lopen) en ``houding``.

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
    """Live: activiteit (en houding) van de laatste ``SEGMENT_S`` uit een ringbuffer (tijden, samples × xyz).

    Te weinig data (net gestart, gaten): onbekend.
    """
    ok = ~np.isnan(tijd)
    rij = {}
    if ok.sum() >= MIN_DEKKING * SEGMENT_S * fs:
        rij = kenmerken(pd.DataFrame(acc[ok], columns=ACC), None, fs)
    return _classificeer(pd.DataFrame([rij], columns=KOLOMMEN), bevestiging).iloc[0]


def houding_nu(tijd: np.ndarray, acc: np.ndarray, fs: float, bevestiging: str,
               vorige: str | None = None) -> tuple[str, float]:
    """Live: houding en kanteling over de laatste ``HOUDING_LIVE_S`` (met marge t.o.v. ``vorige``)."""
    ok = ~np.isnan(tijd)
    if not ok.any():
        return "onbekend", float("nan")
    recent = ok & (tijd >= np.nanmax(tijd) - HOUDING_LIVE_S)
    if recent.sum() < MIN_DEKKING * HOUDING_LIVE_S * fs:
        return "onbekend", float("nan")
    graden = kanteling(acc[recent])
    return houding(graden, bevestiging, vorige), graden


def _classificeer(s: pd.DataFrame, bevestiging: str) -> pd.DataFrame:
    bekend = s["acc_sd"].notna()
    beweegt = bekend & (s["acc_sd"] > BEWEGING_G)
    s["activiteit"] = np.where(~bekend, "onbekend", np.where(beweegt, "beweging", "rust"))
    s["lopen"] = beweegt & s["stap_hz"].between(*STAP_HZ) & (s["stap_aandeel"] > STAP_AANDEEL[bevestiging])
    s.loc[s["lopen"], "activiteit"] = "lopen"
    s["houding"] = [houding(float(k), bevestiging) for k in s["kanteling"]]
    return s
