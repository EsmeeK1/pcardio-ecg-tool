"""UC-1-regels op synthetische acc: rechtop in rust, liggend in rust, lopen."""

import numpy as np
import pandas as pd

from kern.beweging import beweging_nu, beweging_per_segment

FS = 100


def _acc(zw: tuple[float, float, float], golf_g: float = 0.0, n_s: int = 20) -> np.ndarray:
    t = np.arange(n_s * FS) / FS
    rng = np.random.default_rng(0)
    a = np.tile(zw, (len(t), 1)) + rng.normal(0, 0.002, (len(t), 3))
    a[:, 0] -= golf_g * np.sin(2 * np.pi * 1.8 * t)  # stapritme langs de zwaartekracht
    return a


def test_rust_liggend_lopen() -> None:
    stukken = [_acc((-1, 0, 0)), _acc((0, 0, 1)), _acc((-1, 0, 0), golf_g=0.3), _acc((-1, 0, 0))]
    a = np.vstack(stukken)
    tijd = pd.Timestamp("2026-11-04 20:00", tz="UTC") + pd.to_timedelta(np.arange(len(a)) / FS, unit="s")
    acc = pd.DataFrame(a, columns=["AccX", "AccY", "AccZ"]).assign(tijd=tijd)

    s = beweging_per_segment(acc, None, FS, "sticker")
    assert list(s["activiteit"]) == ["rust", "rust", "lopen"], s
    assert list(s["houding"]) == ["rechtop", "liggend", "rechtop"], s
    assert set(beweging_per_segment(acc, None, FS, "lanyard")["houding"]) == {"onbekend"}


def test_live_laatste_20_s() -> None:
    a = _acc((0, 0, 1))
    tijd = np.arange(len(a)) / FS
    nu = beweging_nu(tijd, a, FS, "sticker")
    assert (nu["activiteit"], nu["houding"]) == ("rust", "liggend")
    kort = beweging_nu(tijd[:500], a[:500], FS, "sticker")  # net gestart: 5 s
    assert (kort["activiteit"], kort["houding"]) == ("onbekend", "onbekend")
