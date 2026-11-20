"""UC-2: signaalkwaliteit per segment van 20 s (goed / matig / onbruikbaar) met de meest waarschijnlijke oorzaak.

Over de bruikbaarheid van het signaal, niet over het hart: geen medische uitspraken.

Twee stappen, zodat live (fase 2) dezelfde code kan draaien op een buffer van 20 s:

- ``kenmerken_segment``: duur (filter, R-toppen, slagen, spectrum), alleen afhankelijk van het signaal;
- ``classificeer``: goedkoop, de beslisregels met ``DREMPELS`` en de activiteit uit UC-1.

Aanpak en richtwaarden: secu-sense-wp4, experiments/uc2_kwaliteit (notebooks 01 en 01b). Kort:

- lead-off ziet een losse draad, niet een (half) losse plakker; die zie je aan slechte slagen en drift;
- R-toppen alleen op lead II zoeken en voor alle leads gebruiken (per lead gaat mis als T groter is dan QRS);
- een storing op één elektrode zit in precies twee leads (III = II − I): RA → I+II, LA → I+III, LL → II+III;
- beweging verklaart, maar veroordeelt niet: het label komt uit het ECG, UC-1 geeft alleen de oorzaak.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")  # neurokit2 laadt matplotlib; naast PySide6 anders een Qt-backend (crash)
import neurokit2 as nk  # noqa: E402
import numpy as np
import pandas as pd
from scipy.signal import butter, resample_poly, sosfiltfilt, welch

from kern.beweging import MIN_DEKKING, SEGMENT_S

FS = 250  # Hz; alles wordt hiernaartoe omgezet
VOOR, NA = int(0.25 * FS), int(0.45 * FS)  # slag: 250 ms vóór tot 450 ms na de R-top
LEADS = ("I", "II", "III")
# Getoetst op proxy-labels van 38 opnames (D001, D002; docs/journal/2026-11-20-uc2-afronden.md), nog niet aan
# handmatige beoordelingen.
DREMPELS = {
    "goede_slag": 0.9,  # correlatie met de mediaan-slag waarboven een slag goed is (AI-03)
    "goed": 0.8,  # goed_min hierboven: goed (was 0,9: 23% vals alarm in rust aan de lanyard, door lead I)
    "matig": 0.5,  # goed_min hierboven: matig, anders onbruikbaar
    "drift_db": 15.0,  # drift boven dit in I of II, mét slechte slagen in die lead: onbruikbaar; per lead: "slecht"
    "rand_mv": 350.0,  # |ruw| hierboven: rand van het meetbereik (aanname)
}
PLAKKER = {frozenset({"I", "II"}): "rood", frozenset({"I", "III"}): "geel", frozenset({"II", "III"}): "groen"}
KWALITEIT_KLEUREN = {"goed": "#3FA34D", "matig": "#FF9806", "onbruikbaar": "#D64545"}
VERSIE = 1  # ophogen als kenmerken_segment verandert: de cache wordt dan opnieuw berekend
_SOS = butter(3, [0.5, 40], btype="band", fs=FS, output="sos")


def _band(f: np.ndarray, p: np.ndarray, laag: float, hoog: float) -> float:
    return p[(f >= laag) & (f < hoog)].sum()


def _r_toppen(ii: np.ndarray) -> np.ndarray:
    """R-toppen op gefilterd lead II (neurokit2 op ecg_clean), daarna naar het maximum binnen ± 25 ms."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # vlakke of verzadigde stukken
            _, info = nk.ecg_peaks(nk.ecg_clean(ii, sampling_rate=FS), sampling_rate=FS, method="neurokit")
    except Exception:  # neurokit2 faalt op vlakke of verzadigde stukken: geen toppen
        return np.empty(0, dtype=int)
    w = int(0.025 * FS)
    toppen = [max(t - w, 0) + int(np.argmax(ii[max(t - w, 0):t + w + 1])) for t in info["ECG_R_Peaks"]]
    return np.array([t for t in toppen if t - VOOR >= 0 and t + NA <= len(ii)], dtype=int)


def _lead(ruw: np.ndarray, toppen: np.ndarray) -> dict[str, float]:
    f, p = welch(ruw - ruw.mean(), fs=FS, nperseg=min(len(ruw), 10 * FS))
    qrs = _band(f, p, 5, 15)
    with np.errstate(divide="ignore", invalid="ignore"):  # vlak kanaal: geen vermogen, NaN
        drift = 10 * np.log10(_band(f, p, 0, 0.5) / qrs)
        ruis = 10 * np.log10(_band(f, p, 40, 120) / qrs)
    if len(toppen) == 0:
        return {"goed": 0.0, "drift_db": float(drift), "ruis_db": float(ruis), "uitslag_mv": np.nan}
    gefilterd = sosfiltfilt(_SOS, ruw)
    slagen = np.stack([gefilterd[t - VOOR:t + NA] for t in toppen])
    mediaan = np.median(slagen, axis=0)
    a, b = slagen - slagen.mean(axis=1, keepdims=True), mediaan - mediaan.mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (a @ b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b))
    return {"goed": float(np.mean(r >= DREMPELS["goede_slag"])), "drift_db": float(drift), "ruis_db": float(ruis),
            "uitslag_mv": float(np.ptp(mediaan))}


def kenmerken_segment(ecg1: np.ndarray, ecg2: np.ndarray, lead_off: bool, fs: float = FS) -> dict[str, float]:
    """Kenmerken van één segment: ruwe Ecg1 (I) en Ecg2 (II) in mV, en of lead-off in het segment > 0 was.

    Puur: geen bestanden, geen UI. Live kan dit op een buffer van 20 s draaien.
    """
    i, ii = (np.asarray(x, dtype=float) for x in (ecg1, ecg2))
    if round(fs) != FS:
        deler = np.gcd(round(fs), FS)
        i, ii = (resample_poly(x, FS // deler, round(fs) // deler) for x in (i, ii))
    rand = float(np.mean((np.abs(i) >= DREMPELS["rand_mv"]) | (np.abs(ii) >= DREMPELS["rand_mv"])))
    toppen = _r_toppen(sosfiltfilt(_SOS, ii))
    uit = {"lead_off": bool(lead_off), "rand": rand, "slagen": len(toppen)}
    for naam, x in (("I", i), ("II", ii), ("III", ii - i)):
        uit |= {f"{k}_{naam}": v for k, v in _lead(x, toppen).items()}
    return uit


def classificeer(k: dict, activiteit: str) -> dict[str, str]:
    """Beslisregels op de kenmerken van één segment. ``activiteit`` uit UC-1: rust / beweging / lopen / onbekend."""
    d = DREMPELS
    if k["lead_off"] or k["rand"] > 0:
        return {"kwaliteit": "onbruikbaar", "oorzaak": "losse draad", "plakker": "geen"}
    goed_min = min(k["goed_I"], k["goed_II"])
    # Drift telt alleen als de slagen in die lead ook slecht zijn: lead I is klein (± 0,55 mV), daar komt drift in rust
    # vaak net boven 15 dB terwijl de slagen 0,93–1,00 goed zijn (vals alarm). Een half losse plakker geeft beide.
    drift = lambda lead: k[f"drift_db_{lead}"] > d["drift_db"] and k[f"goed_{lead}"] < d["goed"]  # noqa: E731
    if k["slagen"] == 0 or drift("I") or drift("II"):
        kwaliteit = "onbruikbaar"
    elif goed_min >= d["goed"]:
        return {"kwaliteit": "goed", "oorzaak": "", "plakker": "geen"}
    else:
        kwaliteit = "matig" if goed_min >= d["matig"] else "onbruikbaar"
    if activiteit in ("beweging", "lopen"):
        return {"kwaliteit": kwaliteit, "oorzaak": "beweging", "plakker": "geen"}
    if activiteit != "rust":
        return {"kwaliteit": kwaliteit, "oorzaak": "onbekend", "plakker": "onbekend"}
    slecht = frozenset(lead for lead in LEADS if k[f"goed_{lead}"] < d["goed"] or k[f"drift_db_{lead}"] > d["drift_db"])
    return {"kwaliteit": kwaliteit, "oorzaak": "mogelijk slecht elektrodecontact",
            "plakker": PLAKKER.get(slecht, "onbekend")}


def kwaliteit_nu(tijd: np.ndarray, ecg: np.ndarray, fs: float, lead_off: bool, activiteit: str) -> dict | None:
    """Live: kenmerken en label van de laatste ``SEGMENT_S`` uit de ECG-ringbuffer (tijden, samples × [Ecg1, Ecg2]).
    None zolang er minder dan ``MIN_DEKKING`` van een segment in zit (net gestart, gaten)."""
    ok = ~np.isnan(tijd) & ~np.isnan(ecg).any(axis=1)
    if ok.sum() < MIN_DEKKING * SEGMENT_S * fs:
        return None
    k = kenmerken_segment(ecg[ok, 0], ecg[ok, 1], lead_off, fs)
    return k | classificeer(k, activiteit)


def kenmerken_per_segment(ecg: pd.DataFrame, lead_off: pd.DataFrame | None, starts: pd.Series) -> pd.DataFrame:
    """Kenmerken voor elk segment dat bij ``starts`` begint (het UC-1-rooster). Het ECG wordt op tijdstempel geknipt:
    de P-Cardio meet ± 249,3 Hz, op samplenummer schuift het venster weg ten opzichte van acc en annotaties.
    Segmenten zonder volledige ECG-data vallen weg."""
    tijd = ecg["tijd"].to_numpy(dtype="datetime64[ns]")
    fs = 1 / np.median(np.diff(tijd[:10_000]).astype(float) / 1e9)
    n = SEGMENT_S * round(fs)
    i_all, ii_all = ecg["Ecg1"].to_numpy(dtype=float), ecg["Ecg2"].to_numpy(dtype=float)
    lo_tijd = lead_off["tijd"].to_numpy(dtype="datetime64[ns]") if lead_off is not None else None
    lo = lead_off.drop(columns="tijd").iloc[:, 0].to_numpy(dtype=float) if lead_off is not None else None
    rijen = []
    for start in starts:
        s = np.datetime64(pd.Timestamp(start).tz_convert("UTC").tz_localize(None), "ns")
        i0 = int(np.searchsorted(tijd, s))
        if s < tijd[0] or i0 + n > len(tijd):
            continue
        i, ii = i_all[i0:i0 + n], ii_all[i0:i0 + n]
        if np.isnan(i).any() or np.isnan(ii).any():
            continue
        uit = False
        if lo is not None:
            a, b = np.searchsorted(lo_tijd, [s, s + np.timedelta64(SEGMENT_S, "s")])
            uit = bool(np.nanmax(lo[a:b], initial=0) > 0)
        rijen.append({"start": start, **kenmerken_segment(i, ii, uit, fs)})
    return pd.DataFrame(rijen)


def kwaliteit_per_segment(kenmerken: pd.DataFrame, beweging: pd.DataFrame) -> pd.DataFrame:
    """Kenmerken + UC-1 (``beweging_per_segment``) → het contract: start, eind, kwaliteit, oorzaak, plakker en per
    lead goed / drift_db / ruis_db / uitslag_mv, plus lead_off en rand."""
    if kenmerken.empty:
        return pd.DataFrame(columns=["start", "eind", "kwaliteit", "oorzaak", "plakker"])
    s = kenmerken.merge(beweging[["start", "eind", "activiteit"]], on="start", how="left")
    s["activiteit"] = s["activiteit"].fillna("onbekend")
    labels = pd.DataFrame([classificeer(r, r["activiteit"]) for r in s.to_dict("records")], index=s.index)
    return pd.concat([s, labels], axis=1)


def kenmerken_opname(signalen_map: Path, signalen: dict, starts: pd.Series) -> pd.DataFrame:
    """``kenmerken_per_segment`` met een cache in de signalenmap van de opname (weg bij opnieuw koppelen)."""
    pad = Path(signalen_map) / f"kwaliteit-v{VERSIE}.parquet"
    if pad.exists():
        return pd.read_parquet(pad)
    lo = signalen.get("lead_off")
    k = kenmerken_per_segment(signalen["ecg"].data, lo.data if lo is not None else None, starts)
    k.to_parquet(pad, index=False)
    return k


def per_label(kwaliteit: pd.DataFrame, perioden: list[tuple[str, pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    """Overeenstemming zonder handmatige beoordeling: per periodelabel (bijv. "Plakker half los (RA)") hoeveel
    segmenten goed / matig / onbruikbaar zijn en welke plakker is aangewezen. Een segment telt mee als het helemaal
    binnen de periode valt."""
    d = pd.DataFrame([{"label": label, "kwaliteit": r.kwaliteit, "plakker": r.plakker}
                      for label, begin, eind in perioden for r in kwaliteit.itertuples()
                      if begin <= r.start and r.eind <= eind])
    if d.empty:
        return d
    kw = pd.crosstab(d["label"], d["kwaliteit"]).reindex(columns=list(KWALITEIT_KLEUREN), fill_value=0)
    return pd.concat([kw, pd.crosstab(d["label"], d["plakker"]).add_prefix("plakker ")], axis=1)
