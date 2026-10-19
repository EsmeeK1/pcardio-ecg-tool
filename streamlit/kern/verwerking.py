"""Signaalbewerking: 6 leads, weergavefilter, uitdunnen voor plots, sync-sprong zoeken."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt

# Aanname: kanaal Ecg1 van de P-Cardio = afleiding I, Ecg2 = afleiding II (elektroden volgens Einthoven /
# Mason-Likar). Alleen dan kloppen de vier afgeleide leads hieronder.
LEAD_I = "Ecg1"
LEAD_II = "Ecg2"
ZES_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF"]


def zes_leads(ecg: pd.DataFrame) -> pd.DataFrame:
    """Leid III, aVR, aVL en aVF af uit I en II via de wetten van Einthoven/Goldberger."""
    for kolom in (LEAD_I, LEAD_II):
        if kolom not in ecg.columns:
            raise ValueError(f"Kolom '{kolom}' ontbreekt voor 6-lead-afleiding. Kolommen: {list(ecg.columns)}")
    i = ecg[LEAD_I].to_numpy(dtype=float)
    ii = ecg[LEAD_II].to_numpy(dtype=float)
    return pd.DataFrame(
        {
            "tijd": ecg["tijd"].to_numpy(),
            "I": i,
            "II": ii,
            "III": ii - i,
            "aVR": -(i + ii) / 2,
            "aVL": i - ii / 2,
            "aVF": ii - i / 2,
        },
    )


# Weergavefilter: alleen voor de plots, nooit voor opgeslagen of geëxporteerde data.
FILTER_HZ = (0.5, 40.0)
# Extra data aan weerszijden van het venster, zodat het filter aan de vensterranden niet inzwaait.
FILTER_MARGE_S = 2.0


def ecg_filter(waarden: np.ndarray, fs: float) -> np.ndarray:
    """Zero-phase Butterworth-bandfilter (4e orde): weg met drift (< 0,5 Hz) en ruis/netbrom (> 40 Hz).

    Geeft een nieuwe array terug; ``waarden`` blijft onveranderd. Gaten (NaN) blijven gaten.
    """
    laag, hoog = FILTER_HZ[0], min(FILTER_HZ[1], 0.45 * fs) if np.isfinite(fs) else FILTER_HZ[1]
    gevuld = pd.Series(waarden).interpolate(limit_direction="both").to_numpy()
    try:
        sos = butter(4, [laag, hoog], btype="bandpass", fs=fs, output="sos")
        gefilterd = sosfiltfilt(sos, gevuld)
    except ValueError:  # te kort stuk of onbruikbare sample rate: dan alleen de offset eraf
        gefilterd = gevuld - np.nanmean(gevuld)
    gefilterd[np.isnan(waarden)] = np.nan
    return gefilterd


NETBROM_HZ = 50.0


def netbrom_filter(waarden: np.ndarray, fs: float) -> np.ndarray:
    """Zero-phase notchfilter op 50 Hz (netbrom). Alleen voor weergave; te korte stukken blijven onveranderd."""
    if not np.isfinite(fs) or fs <= 2 * NETBROM_HZ:
        return waarden
    b, a = iirnotch(NETBROM_HZ, 30.0, fs=fs)
    try:
        return filtfilt(b, a, waarden)
    except ValueError:
        return waarden


def magnitude(df: pd.DataFrame, kanalen: list[str]) -> np.ndarray:
    return np.sqrt(sum(df[k].to_numpy(dtype=float) ** 2 for k in kanalen))


def knip(df: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    """Rijen met ``t0 <= tijd <= t1``; ``df`` moet op ``tijd`` gesorteerd zijn."""
    tijden = df["tijd"]
    i0 = tijden.searchsorted(t0, side="left")
    i1 = tijden.searchsorted(t1, side="right")
    return df.iloc[i0:i1]


def dun_uit(tijd: pd.Series, waarden: np.ndarray, max_punten: int = 4000) -> tuple[pd.Series, np.ndarray]:
    """Min/max per bak, zodat pieken (artefacten!) zichtbaar blijven in een overzichtsplot."""
    n = len(waarden)
    if n <= max_punten:
        return tijd, waarden
    # Naar boven afronden en het laatste blok aanvullen met NaN, zodat het einde van het signaal niet wegvalt.
    grootte = -(-n // (max_punten // 2))
    bakken = -(-n // grootte)
    aanvulling = bakken * grootte - n
    blokken = np.concatenate([np.asarray(waarden, dtype=float), np.full(aanvulling, np.nan)]).reshape(bakken, grootte)
    i_min = np.nanargmin(np.where(np.isnan(blokken), np.inf, blokken), axis=1)
    i_max = np.nanargmax(np.where(np.isnan(blokken), -np.inf, blokken), axis=1)
    eerst = np.minimum(i_min, i_max)
    daarna = np.maximum(i_min, i_max)
    rijen = np.arange(bakken)
    idx_w = np.stack([blokken[rijen, eerst], blokken[rijen, daarna]], axis=1).reshape(-1)
    # Tijden via de posities ophalen: tijd.to_numpy() maakt van een tijdzone-kolom een Python-object per sample (traag).
    posities = np.minimum(np.stack([rijen * grootte + eerst, rijen * grootte + daarna], axis=1).reshape(-1), n - 1)
    return tijd.iloc[posities].reset_index(drop=True), idx_w


@dataclass
class SyncResultaat:
    t_gelogd: pd.Timestamp
    t_piek: pd.Timestamp
    piek_g: float
    ruis_g: float

    @property
    def correctie_s(self) -> float:
        """Op te tellen bij de pc-tijd om op de P-Cardio-tijd uit te komen."""
        return (self.t_piek - self.t_gelogd).total_seconds()

    @property
    def duidelijk(self) -> bool:
        """Piek steekt duidelijk boven de rest van het zoekvenster uit."""
        return self.piek_g > 5 * max(self.ruis_g, 1e-6)


def zoek_sync(acc: pd.DataFrame, t_gelogd: pd.Timestamp, zoek_s: float = 5.0) -> SyncResultaat | None:
    """Zoek de landing van de sync-sprong: de grootste afwijking van |acc| rond het gelogde moment."""
    kanalen = [k for k in ("AccX", "AccY", "AccZ") if k in acc.columns]
    if len(kanalen) != 3:
        raise ValueError(f"Accelerometer-kanalen AccX/AccY/AccZ niet compleet. Kolommen: {list(acc.columns)}")
    venster = knip(acc, t_gelogd - pd.Timedelta(seconds=zoek_s), t_gelogd + pd.Timedelta(seconds=zoek_s))
    if len(venster) < 3:
        return None
    grootte = magnitude(venster, kanalen)
    afwijking = np.abs(grootte - np.nanmedian(grootte))
    i = int(np.nanargmax(afwijking))
    return SyncResultaat(
        t_gelogd=t_gelogd,
        t_piek=venster["tijd"].iloc[i],
        piek_g=float(afwijking[i]),
        ruis_g=float(np.nanmedian(afwijking)),
    )


def overlap_fractie(a0: pd.Timestamp, a1: pd.Timestamp, b0: pd.Timestamp, b1: pd.Timestamp) -> float:
    """Deel van interval a dat binnen interval b valt (0-1)."""
    duur = (a1 - a0).total_seconds()
    gedeeld = (min(a1, b1) - max(a0, b0)).total_seconds()
    if duur <= 0:
        return 1.0 if b0 <= a0 <= b1 else 0.0
    return max(0.0, gedeeld) / duur
