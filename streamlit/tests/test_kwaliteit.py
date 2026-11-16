"""UC-2-regels op synthetische ECG's: schoon, losse draad, drift op één elektrode, grote T-golf in I."""

import numpy as np
import pandas as pd

from kern.kwaliteit import (
    FS, classificeer, kenmerken_per_segment, kenmerken_segment, kwaliteit_per_segment, per_label,
)

T = np.arange(20 * FS) / FS
SLAGEN = 0.4 + np.cumsum(np.r_[0, 0.8 + 0.05 * np.sin(np.arange(30))])  # ± 72 bpm, licht wisselend


def _ecg(qrs: float, t_golf: float) -> np.ndarray:
    """Eenvoudig ECG in mV: smalle QRS en brede T-golf per slag."""
    return sum(qrs * np.exp(-((T - s) / 0.012) ** 2) + t_golf * np.exp(-((T - s - 0.25) / 0.05) ** 2)
               for s in SLAGEN if s < 20)


I, II = _ecg(0.6, 0.15), _ecg(1.2, 0.3)
DRIFT = 8 * np.sin(2 * np.pi * 0.15 * T) + 5 * np.sin(2 * np.pi * 0.3 * T)  # mV, onder 0,5 Hz


def _label(i: np.ndarray, ii: np.ndarray, lead_off: bool = False, activiteit: str = "rust") -> dict:
    return classificeer(kenmerken_segment(i, ii, lead_off), activiteit)


def test_schoon_is_goed() -> None:
    assert _label(I, II) == {"kwaliteit": "goed", "oorzaak": "", "plakker": "geen"}


def test_losse_draad() -> None:
    vlak = np.full_like(T, -380.0)
    assert _label(vlak, II, lead_off=True) == {"kwaliteit": "onbruikbaar", "oorzaak": "losse draad", "plakker": "geen"}


def test_drift_wijst_plakker_aan() -> None:
    # Einthoven: I = LA − RA, II = LL − RA. Storing d op RA: I − d en II − d, III = II − I blijft schoon.
    k = kenmerken_segment(I - DRIFT, II - DRIFT, False)
    assert k["drift_db_III"] < 15 < min(k["drift_db_I"], k["drift_db_II"])
    assert classificeer(k, "rust")["plakker"] == "rood"
    assert _label(I + DRIFT, II)["plakker"] == "geel"  # LA: I + d, III − d
    assert _label(I, II + DRIFT)["plakker"] == "groen"  # LL: II + d, III + d
    assert _label(I - DRIFT, II - DRIFT, activiteit="beweging") == {
        "kwaliteit": "onbruikbaar", "oorzaak": "beweging", "plakker": "geen"}


def test_toppen_uit_ii_bij_grote_t_golf_in_i() -> None:
    k = kenmerken_segment(_ecg(0.2, 0.6), II, False)  # in I is T groter dan QRS
    assert k["goed_I"] >= 0.9


def test_per_segment_op_tijdstempel() -> None:
    n = 3 * len(T) - 100  # 59,8 s op 249,3 Hz
    tijd = pd.Timestamp("2026-11-10 09:00", tz="UTC") + pd.to_timedelta(np.arange(n) / 249.3, unit="s")
    ecg = pd.DataFrame({"tijd": tijd, "Ecg1": np.tile(I, 3)[:n], "Ecg2": np.tile(II, 3)[:n]})
    lead_off = pd.DataFrame({"tijd": tijd[::50], "LeadOff": 0.0})
    starts = pd.Series(tijd[0] + pd.to_timedelta([0, 20, 40], unit="s"))
    k = kenmerken_per_segment(ecg, lead_off, starts)
    assert len(k) == 2  # het derde segment is niet compleet (249,3 Hz)
    beweging = pd.DataFrame({"start": starts, "eind": starts + pd.Timedelta(seconds=20), "activiteit": "rust"})
    assert list(kwaliteit_per_segment(k, beweging)["kwaliteit"]) == ["goed", "goed"]


def test_per_label() -> None:
    t0 = pd.Timestamp("2026-11-10 09:00", tz="UTC")
    s = pd.to_timedelta([0, 20, 40], unit="s")
    kw = pd.DataFrame({"start": t0 + s, "eind": t0 + s + pd.Timedelta(seconds=20),
                       "kwaliteit": ["goed", "onbruikbaar", "onbruikbaar"], "plakker": ["geen", "rood", "rood"]})
    tabel = per_label(kw, [("Zitten", t0, t0 + pd.Timedelta(seconds=25)),
                           ("Plakker half los (RA)", t0 + pd.Timedelta(seconds=20), t0 + pd.Timedelta(seconds=60))])
    assert tabel.loc["Zitten", "goed"] == 1 and tabel.loc["Zitten", "onbruikbaar"] == 0
    assert tabel.loc["Plakker half los (RA)", "plakker rood"] == 2
