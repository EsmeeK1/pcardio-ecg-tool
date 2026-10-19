from __future__ import annotations

import binascii
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kern.pcardio import DATATYPES, GAINS, SAMPLE_RATES, combineer, lees_bestand, lees_csv

# Map met een echte P-Cardio-export (Ecg_2Ch.csv); in te stellen via ECG_TOOL_TESTDATA.
ECHTE_CSV = Path(os.environ.get("ECG_TOOL_TESTDATA", "")) / "Ecg_2Ch.csv"


# --- CSV ---


def test_csv_tijdzone_uit_kolomnaam(tmp_path: Path) -> None:
    pad = tmp_path / "Ecg_2Ch.csv"
    pad.write_text(
        "Date,Time  (UTC+01:00),Ecg1 (mV),Ecg2 (mV)\n"
        "2026/01/19,11:18:11.919936,-75.39305,-54.63327\n"
        "2026/01/19,11:18:11.923936,-75.0,-54.0\n",
        encoding="utf-8",
    )
    signaal = lees_csv(pad)
    assert signaal.naam == "ecg"
    assert signaal.kanalen == ["Ecg1", "Ecg2"]
    assert signaal.eenheden == {"Ecg1": "mV", "Ecg2": "mV"}
    assert signaal.start == pd.Timestamp("2026-01-19 10:18:11.919936", tz="UTC")


def test_csv_excel_notatie_mm_ss(tmp_path: Path) -> None:
    pad = tmp_path / "Acc.csv"
    pad.write_text("Date,Time (UTC+01:00),AccX (g),AccY (g),AccZ (g)\n2026-01-19,16:58.4,1,0,0\n", encoding="utf-8")
    signaal = lees_csv(pad)
    assert signaal.naam == "acc"
    assert signaal.start == pd.Timestamp("2026-01-19 00:16:58.4", tz="Europe/Amsterdam").tz_convert("UTC")


@pytest.mark.skipif(not ECHTE_CSV.exists(), reason="echte P-Cardio-export niet aanwezig")
def test_echte_export() -> None:
    signalen, meldingen = lees_bestand(ECHTE_CSV)
    ecg = signalen[0]
    assert meldingen == []
    assert ecg.naam == "ecg" and ecg.kanalen == ["Ecg1", "Ecg2"]
    assert 245 < ecg.fs < 255
    assert ecg.data["tijd"].is_monotonic_increasing


def test_combineer_weigert_dubbele_signalen(tmp_path: Path) -> None:
    pad = tmp_path / "a.csv"
    pad.write_text("Date,Time (UTC+01:00),Ecg1 (mV)\n2026/01/19,11:18:11.9,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="meerdere bestanden"):
        combineer([lees_csv(pad), lees_csv(pad)])


# --- binair (synthetisch bestand volgens interface-handleiding v5) ---

SENSOREN = [
    (3, 4, 4, 3),  # ECG 2-kanaals, x6, 250 Hz, mV
    (5, 1, 6, 4),  # accelerometer, x2, 100 Hz, g
    (12, 0, 10, 8),  # lead-off, 5 Hz
]


def _digitaal(analoog: np.ndarray, type_id: int, gain_id: int) -> np.ndarray:
    dt = DATATYPES[type_id]
    schaal = (dt.analoog_max - dt.analoog_min) / (dt.digitaal_max - dt.digitaal_min)
    return np.round((analoog * GAINS[gain_id] - dt.analoog_max) / schaal + dt.digitaal_max).astype(np.int64)


def _maak_binair(pad: Path, t0: int, seconden: int) -> dict[str, np.ndarray]:
    config = bytearray(144)
    config[0:8] = bytes([0x50, 0x43, 0x41, 0x52, 0x44, 0x49, 0x4F, 0x00])
    # Sampling-configuratie op byte 72, zoals in echte bestanden van de P-Cardio.
    config[72:76] = len(SENSOREN).to_bytes(4, "little")
    for i, sensor in enumerate(SENSOREN):
        config[76 + 4 * i:80 + 4 * i] = bytes(sensor)
    kop = bytes(config) + t0.to_bytes(4, "little") + (t0 + seconden).to_bytes(4, "little")

    n_pakketten = seconden * 5
    ecg = np.sin(np.linspace(0, 20, n_pakketten * 50 * 2)).reshape(-1, 2)
    acc = np.tile([0.0, 0.0, 1.0], (n_pakketten * 20, 1))
    lead_off = (np.arange(n_pakketten) % 7 == 0).astype(np.int64)

    ecg_d = _digitaal(ecg, 3, 4)
    acc_d = _digitaal(acc, 4, 1)
    pakketten = bytearray()
    for k in range(n_pakketten):
        payload = bytearray()
        for waarde in ecg_d[k * 50:(k + 1) * 50].reshape(-1):
            payload += int(waarde).to_bytes(3, "little", signed=True)
        for waarde in acc_d[k * 20:(k + 1) * 20].reshape(-1):
            payload += int(waarde).to_bytes(2, "little", signed=True)
        payload += int(lead_off[k]).to_bytes(1, "little")
        seconde, rest = divmod(k, 5)
        ticks = int(rest * 32768 / 5)
        header = (
            (t0 + seconde).to_bytes(4, "little")
            + ticks.to_bytes(4, "little")
            + bytes([1])
            + len(payload).to_bytes(2, "little")
            + binascii.crc_hqx(bytes(payload), 0xFFFF).to_bytes(2, "little")
        )
        pakketten += header + payload
    pad.write_bytes(kop + bytes(pakketten))
    return {"ecg": ecg, "acc": acc, "lead_off": lead_off}


def test_binair_heen_en_terug(tmp_path: Path) -> None:
    pad = tmp_path / "data_20260119111800.txt"
    t0 = 1_768_817_880
    verwacht = _maak_binair(pad, t0, seconden=4)

    signalen, meldingen = lees_bestand(pad)
    per_naam = {s.naam: s for s in signalen}
    assert meldingen == []
    assert set(per_naam) == {"ecg", "acc", "lead_off"}

    ecg = per_naam["ecg"]
    assert ecg.kanalen == ["Ecg1", "Ecg2"]
    np.testing.assert_allclose(ecg.data[["Ecg1", "Ecg2"]].to_numpy(), verwacht["ecg"], atol=1e-3)
    assert ecg.fs == pytest.approx(250, rel=0.01)
    # pakkettijd = laatste sample van het pakket; het apparaat staat op Nederlandse kloktijd
    assert ecg.data["tijd"].iloc[49] == pd.to_datetime(t0, unit="s").tz_localize("Europe/Amsterdam").tz_convert("UTC")

    acc = per_naam["acc"]
    np.testing.assert_allclose(acc.data[["AccX", "AccY", "AccZ"]].to_numpy(), verwacht["acc"], atol=1e-3)
    assert acc.fs == pytest.approx(100, rel=0.01)
    np.testing.assert_array_equal(per_naam["lead_off"].data["LeadOff"].to_numpy(), verwacht["lead_off"])


def test_binair_verkeerde_prefix(tmp_path: Path) -> None:
    pad = tmp_path / "data_x.txt"
    pad.write_bytes(b"datum\ttijd\twaarde\n" * 20)
    with pytest.raises(ValueError, match="Geen P-Cardio-bestand"):
        lees_bestand(pad)


def test_tabellen() -> None:
    assert SAMPLE_RATES[4] == 250 and SAMPLE_RATES[10] == 5
    assert GAINS[4] == 6


def test_pakkettijden_secondeteller_loopt_achter() -> None:
    """Echt voorbeeld (data_20261006171437.txt): ticks springen naar 0 terwijl de seconde nog niet opgehoogd is."""
    from kern.pcardio import _pakkettijden

    seconden = [749, 749, 749, 750, 750]
    ticks = [19629, 26198, 1, 6570, 13139]  # derde pakket hoort bij seconde 750
    kop = np.zeros((5, 13), dtype=np.uint8)
    kop[:, 0:4] = np.array(seconden, dtype="<u4").view(np.uint8).reshape(5, 4)
    kop[:, 4:8] = np.array(ticks, dtype="<u4").view(np.uint8).reshape(5, 4)
    tijden, gecorrigeerd = _pakkettijden(kop, "little")
    assert gecorrigeerd == 1
    assert np.all(np.diff(tijden) > 0)
    np.testing.assert_allclose(np.diff(tijden), 0.2005, atol=0.001)
