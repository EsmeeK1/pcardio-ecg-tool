from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kern.export import bestandssoort, gecombineerd, lees_export
from kern.opslag import Deelnemers, Opname, lees_annotaties, nu
from kern.pcardio import Signaal
from kern.plots import DetailOpties, detail, selectie_tijden
from kern.verwerking import dun_uit, ecg_filter, overlap_fractie, zes_leads, zoek_sync


def _deelnemer(root: Path):
    return Deelnemers(root).toevoegen("Esmee", 30, "vrouw", False, "")


def test_deelnemers(tmp_path: Path) -> None:
    register = Deelnemers(tmp_path)
    a = register.toevoegen("Esmee", 30, "vrouw", False)
    b = register.toevoegen("P-1234", None, "onbekend", True, "astma")
    assert (a.id, b.id) == ("D001", "D002")
    opgeslagen = {d.id: d for d in register.alle()}["D002"]
    assert opgeslagen.andere_aandoening == "astma" and opgeslagen.hartdecompensatie is True
    b.leeftijd = 61
    register.bijwerken(b)
    assert {d.id: d for d in register.alle()}["D002"].leeftijd == 61
    with pytest.raises(ValueError, match="voornaam"):
        register.toevoegen(" ", 1, "man", False)


def test_deelnemer_verwijderen(tmp_path: Path) -> None:
    register = Deelnemers(tmp_path)
    zonder = register.toevoegen("Zonder opname", None, "onbekend", False)
    met = register.toevoegen("Met opname", None, "onbekend", False)
    Opname.nieuw(met, nu(), root=tmp_path)

    with pytest.raises(ValueError, match="1 opname"):
        register.verwijder(met.id)
    with pytest.raises(ValueError, match="Onbekende deelnemer"):
        register.verwijder("D999")
    register.verwijder(zonder.id)
    assert [d.id for d in register.alle()] == [met.id]

    # De hoogste deelnemer weghalen mag zijn ID niet vrijgeven zolang er opnames met dat ID zijn.
    (tmp_path / "deelnemers.csv").unlink()
    assert register.toevoegen("Nieuw", None, "onbekend", False).id == "D003"


def test_live_annoteren_en_laden(tmp_path: Path) -> None:
    opname = Opname.nieuw(_deelnemer(tmp_path), nu(), root=tmp_path)
    opname.sync()
    opname.start_periode("Zitten")
    time.sleep(0.05)
    opname.moment("Hoest")
    opname.start_periode("Lopen (rustig)")
    opname.sluit_live_af()

    geladen = Opname.laad(opname.map)
    perioden = [a for a in geladen.chronologisch() if a.soort == "periode"]
    assert [p.label for p in perioden] == ["Zitten", "Lopen (rustig)"]
    assert all(p.t_eind is not None for p in perioden)
    assert perioden[0].t_eind == perioden[1].t_start
    assert geladen.info.live_afgesloten
    assert len(geladen.syncs) == 1


def test_klokcorrectie(tmp_path: Path) -> None:
    opname = Opname.nieuw(_deelnemer(tmp_path), nu(), root=tmp_path)
    a = opname.moment("Hoest")
    opname.zet_klokcorrectie(2.5, "handmatig")
    start, _ = opname.in_datatijd(a)
    assert (start - a.t_start).total_seconds() == pytest.approx(2.5)
    b = opname.voeg_toe("moment", "achteraf", start, tijdbasis="data")
    assert opname.in_datatijd(b)[0] == start


def _signalen(t0: pd.Timestamp, seconden: int = 20) -> dict[str, Signaal]:
    t_ecg = t0 + pd.to_timedelta(np.arange(seconden * 250) / 250, unit="s")
    t_acc = t0 + pd.to_timedelta(np.arange(seconden * 100) / 100, unit="s")
    rng = np.random.default_rng(0)
    acc = np.column_stack([rng.normal(0, 0.01, len(t_acc)), rng.normal(0, 0.01, len(t_acc)), np.ones(len(t_acc))])
    acc[1000, 2] = 4.0  # landing op t0 + 10 s
    return {
        "ecg": Signaal(
            "ecg",
            pd.DataFrame({"tijd": t_ecg, "Ecg1": np.sin(np.arange(len(t_ecg))), "Ecg2": np.cos(np.arange(len(t_ecg)))}),
            {"Ecg1": "mV", "Ecg2": "mV"},
            "test",
        ),
        "acc": Signaal(
            "acc",
            pd.DataFrame({"tijd": t_acc, "AccX": acc[:, 0], "AccY": acc[:, 1], "AccZ": acc[:, 2]}),
            {"AccX": "g", "AccY": "g", "AccZ": "g"},
            "test",
        ),
    }


def test_sync_en_export(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    signalen = _signalen(t0)
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    # pc-klok loopt 1,2 s achter op de P-Cardio
    opname.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))
    opname.voeg_toe("periode", "Springen", t0 + pd.Timedelta(seconds=12), t0 + pd.Timedelta(seconds=14))
    opname.voeg_toe("moment", "Hoest", t0 + pd.Timedelta(seconds=15))

    resultaat = zoek_sync(signalen["acc"].data, opname.syncs[0].t_start)
    assert resultaat is not None and resultaat.duidelijk
    assert resultaat.correctie_s == pytest.approx(1.2, abs=0.02)
    opname.zet_klokcorrectie(resultaat.correctie_s, "sync")

    opname.bewaar_signalen(signalen, [])
    geladen = Opname.laad(opname.map).laad_signalen()
    assert set(geladen) == {"ecg", "acc"}
    pd.testing.assert_frame_equal(geladen["acc"].data, signalen["acc"].data)

    df = gecombineerd(opname, geladen)
    assert {"Ecg1", "Ecg2", "III", "aVR", "AccZ", "acc_magnitude", "activiteit", "moment"} <= set(df.columns)
    springen = df.loc[df["activiteit"] == "Springen", "t_s"]
    assert springen.min() == pytest.approx(13.2, abs=0.01)
    assert springen.max() == pytest.approx(15.2, abs=0.01)
    assert df.loc[df["moment"] == "Hoest", "t_s"].iloc[0] == pytest.approx(16.2, abs=0.01)
    assert len(df) == 20 * 250


def test_export_terug_inlezen(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    bron = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    bron.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))
    bron.voeg_toe("periode", "Springen", t0 + pd.Timedelta(seconds=12), t0 + pd.Timedelta(seconds=14), opmerking="x")
    bron.zet_klokcorrectie(1.2, "sync")
    data_pad, annotaties_pad = tmp_path / "volledig.csv", tmp_path / "annotaties.csv"
    gecombineerd(bron, _signalen(t0)).to_csv(data_pad, index=False)
    bron.annotaties_df().to_csv(annotaties_pad, index=False)
    assert (bestandssoort(data_pad), bestandssoort(annotaties_pad)) == ("export", "annotaties")

    signalen = {s.naam: s for s in lees_export(data_pad)}
    assert set(signalen) == {"ecg", "acc"}
    assert signalen["ecg"].kanalen == ["Ecg1", "Ecg2"] and signalen["acc"].kanalen == ["AccX", "AccY", "AccZ"]
    assert signalen["ecg"].start == t0 and len(signalen["ecg"].data) == 20 * 250

    annotaties, correctie = lees_annotaties(annotaties_pad)
    assert correctie == pytest.approx(1.2)
    doel = Opname.nieuw(_deelnemer(tmp_path), t0 + pd.Timedelta(hours=1), root=tmp_path)
    doel.voeg_toe("moment", "weg", t0)
    doel.vervang_annotaties(annotaties, correctie)
    doel = Opname.laad(doel.map)
    assert [(a.label, a.opmerking) for a in doel.chronologisch()] == [("sync-sprong", ""), ("Springen", "x")]
    assert (doel.info.klokcorrectie_s, doel.info.klokcorrectie_bron) == (pytest.approx(1.2), "geïmporteerd")


def test_zes_leads_einthoven() -> None:
    ecg = pd.DataFrame({"tijd": [0, 1], "Ecg1": [1.0, 2.0], "Ecg2": [3.0, 5.0]})
    leads = zes_leads(ecg)
    np.testing.assert_allclose(leads["I"] + leads["III"] - leads["II"], 0)
    np.testing.assert_allclose(leads["aVR"] + leads["aVL"] + leads["aVF"], 0)


def test_dun_uit_bewaart_pieken() -> None:
    tijd = pd.Series(pd.date_range("2026-01-01", periods=100_000, freq="4ms", tz="UTC"))
    waarden = np.zeros(100_000)
    waarden[54_321] = 9.0
    t, w = dun_uit(tijd, waarden, max_punten=1000)
    assert len(w) <= 1000 and w.max() == 9.0
    assert t.iloc[w.argmax()] == tijd.iloc[54_321] and t.dtype == tijd.dtype


def test_dun_uit_houdt_het_einde() -> None:
    """10 s op 1000 Hz uitgedund naar 8000 punten liet eerder alleen de eerste 8 s zien."""
    tijd = pd.Series(pd.date_range("2026-01-01", periods=10_000, freq="1ms", tz="UTC"))
    t, w = dun_uit(tijd, np.arange(10_000, dtype=float), max_punten=8000)
    assert len(w) <= 8000
    assert t.iloc[0] == tijd.iloc[0] and t.iloc[-1] == tijd.iloc[-1]
    assert w.min() == 0 and w.max() == 9_999


def test_overlap() -> None:
    t = pd.Timestamp("2026-01-01", tz="UTC")
    s = pd.Timedelta(seconds=1)
    assert overlap_fractie(t, t + 10 * s, t + 5 * s, t + 100 * s) == pytest.approx(0.5)
    assert overlap_fractie(t, t + 10 * s, t + 20 * s, t + 30 * s) == 0


def test_ecg_filter_haalt_drift_en_ruis_weg() -> None:
    fs = 250.0
    t = np.arange(int(20 * fs)) / fs
    hart = np.sin(2 * np.pi * 5 * t)  # in de doorlaatband
    ruw = 3.0 + 0.8 * np.sin(2 * np.pi * 0.1 * t) + hart + 0.5 * np.sin(2 * np.pi * 50 * t)
    ruw[1000:1010] = np.nan
    kopie = ruw.copy()

    gefilterd = ecg_filter(ruw, fs)

    np.testing.assert_array_equal(ruw, kopie)  # invoer onveranderd
    assert len(gefilterd) == len(ruw) and np.isnan(gefilterd[1000:1010]).all()
    midden = slice(int(2 * fs), int(18 * fs))  # randen buiten beschouwing
    ok = ~np.isnan(gefilterd[midden])
    fout = gefilterd[midden][ok] - hart[midden][ok]
    assert np.sqrt(np.mean(fout**2)) < 0.05
    assert ecg_filter(np.array([1.0, 2.0, 3.0]), fs).tolist() == [-1.0, 0.0, 1.0]  # te kort: alleen offset eraf


def test_filter_alleen_in_de_plot(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    signalen = _signalen(t0)
    signalen["ecg"].data["Ecg1"] += 5.0  # offset die het filter in de plot weghaalt
    voor = {n: s.data.copy() for n, s in signalen.items()}
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)

    fig = detail(signalen, opname, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=15), DetailOpties(filter=True))
    getoond = np.concatenate([np.asarray(tr.y, dtype=float) for tr in fig.data if tr.name == "I"])
    assert abs(np.nanmean(getoond)) < 1.0  # in de plot is de offset weg

    for naam, data in voor.items():
        pd.testing.assert_frame_equal(signalen[naam].data, data)  # opgeslagen signalen onveranderd
    df = gecombineerd(opname, signalen)
    np.testing.assert_array_equal(df["Ecg1"].to_numpy(), voor["ecg"]["Ecg1"].to_numpy())  # export ruw


def test_label_in_hover(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    opname.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=6), t0 + pd.Timedelta(seconds=8), tijdbasis="data")
    opname.voeg_toe("moment", "Hoest", t0 + pd.Timedelta(seconds=7), tijdbasis="data")
    fig = detail(_signalen(t0), opname, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=15), DetailOpties())

    label = next(tr for tr in fig.data if tr.name == "label")
    assert set(label.text) == {"Zitten", "Zitten, Hoest"} and list(label.text).count("Zitten, Hoest") == 1
    assert len(label.x) == 2 * 250 + 1  # alleen punten binnen de periode (2 s op 250 Hz, randen inbegrepen)


def test_selectie_tijden() -> None:
    selectie = {"box": [{"xref": "x", "yref": "y", "x": ["2026-10-05 10:00:12.5", "2026-10-05 10:00:03.25"]}]}
    begin, eind = selectie_tijden(selectie)
    assert begin == pd.Timestamp("2026-10-05 08:00:03.25", tz="UTC")  # zomertijd: UTC+2
    assert eind == pd.Timestamp("2026-10-05 08:00:12.5", tz="UTC")
    assert selectie_tijden({"box": [], "points": []}) is None
    assert selectie_tijden(None) is None
