"""Inlezen en koppelen in alle varianten, de sync-sprong, en het uur-voorstel bij zomer-/wintertijd."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kern.export import gecombineerd
from kern.koppelen import bestanden_in_map, binnen_data, lees_in, pak_uit, voorstellen
from kern.opslag import Deelnemers, Opname
from kern.verwerking import uur_verschoven, zoek_sync
from test_opslag_en_export import _signalen
from test_pcardio import _maak_binair

T0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")


@pytest.fixture
def bron(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Een ruw P-Cardio-bestand, een export en een annotatiebestand van dezelfde opname."""
    ruw = tmp_path / "data_20261005100000.txt"
    _maak_binair(ruw, int(T0.tz_convert("Europe/Amsterdam").tz_localize(None).timestamp()), seconden=2)
    opname = Opname.nieuw(Deelnemers(tmp_path / "db").toevoegen("Bron", 1996, "man", False), T0, root=tmp_path / "db")
    opname.voeg_toe("periode", "Zitten", T0 + pd.Timedelta(seconds=2), T0 + pd.Timedelta(seconds=8))
    export, annotaties = tmp_path / "x_volledig.csv", tmp_path / "x_annotaties.csv"
    gecombineerd(opname, _signalen(T0)).to_csv(export, index=False)
    opname.annotaties_df().to_csv(annotaties, index=False)
    return ruw, export, annotaties


def test_alleen_een_map(tmp_path: Path, bron) -> None:
    ruw, _, annotaties = bron
    map_ = tmp_path / "sessie"
    map_.mkdir()
    for p in (ruw, annotaties):
        (map_ / p.name).write_bytes(p.read_bytes())
    for overbodig in ("log.txt", "config.txt", "foto.jpg"):  # staan ook op de recorder of horen er niet bij
        (map_ / overbodig).write_text("x")
    paden = bestanden_in_map(map_)
    assert [p.name for p in paden] == sorted([ruw.name, annotaties.name])
    r = lees_in(paden, tmp_path / "uit")
    assert not r.fouten and "ecg" in r.signalen and len(r.annotaties["lijst"]) == 1


def test_zip_plat_uitgepakt_zonder_rommel(tmp_path: Path, bron) -> None:
    ruw, _, annotaties = bron
    zip_pad = tmp_path / "sessie.zip"
    with zipfile.ZipFile(zip_pad, "w") as zf:
        zf.write(ruw, f"map/diep/{ruw.name}")
        zf.write(annotaties, f"../{annotaties.name}")  # mag niet buiten de uitpakmap terechtkomen
        zf.writestr("__MACOSX/._x.csv", "rommel")
        zf.writestr("map/log.txt", "log")
    uit = tmp_path / "uit"
    assert sorted(p.name for p in pak_uit(zip_pad, uit)) == sorted([ruw.name, annotaties.name])
    assert sorted(p.name for p in uit.iterdir()) == sorted([ruw.name, annotaties.name])
    r = lees_in([zip_pad], tmp_path / "uit2")
    assert not r.fouten and "ecg" in r.signalen and r.annotaties is not None


def test_kapot_bestand_en_geen_zip(tmp_path: Path, bron) -> None:
    ruw = bron[0]
    kapot, nep_zip = tmp_path / "data_kapot.txt", tmp_path / "nep.zip"
    kapot.write_bytes(b"\x00\x01geen p-cardio")
    nep_zip.write_text("geen zip")
    r = lees_in([kapot, nep_zip, ruw], tmp_path / "uit")
    assert len(r.fouten) == 2 and "ecg" in r.signalen  # de rest wordt gewoon ingelezen


def test_twee_annotatiebestanden_en_export_met_ruw(tmp_path: Path, bron) -> None:
    ruw, export, annotaties = bron
    tweede = tmp_path / "y_annotaties.csv"
    tweede.write_bytes(annotaties.read_bytes())
    r = lees_in([annotaties, tweede], tmp_path / "uit")
    assert any("Meerdere annotatiebestanden" in f for f in r.fouten) and r.annotaties is not None
    r = lees_in([ruw, export], tmp_path / "uit")
    assert any("Kies één bron" in f for f in r.fouten) and r.signalen == {}


def test_alleen_annotaties_en_export_zonder_annotaties(tmp_path: Path, bron) -> None:
    _, export, annotaties = bron
    r = lees_in([annotaties], tmp_path / "uit")
    assert r.signalen == {} and len(r.annotaties["lijst"]) == 1 and not r.fouten
    r = lees_in([export], tmp_path / "uit")
    assert "ecg" in r.signalen and any("zonder annotatiebestand" in m for m in r.meldingen)


def test_voorstel_en_binnen_data(tmp_path: Path) -> None:
    signalen = _signalen(T0)
    register = Deelnemers(tmp_path)
    past = Opname.nieuw(register.toevoegen("A", 1996, "man", False), T0, root=tmp_path)
    past.voeg_toe("periode", "Zitten", T0 + pd.Timedelta(seconds=2), T0 + pd.Timedelta(seconds=6))
    later = Opname.nieuw(register.toevoegen("B", 1996, "man", False), T0 + pd.Timedelta(hours=3), root=tmp_path)
    later.voeg_toe("periode", "Zitten", T0 + pd.Timedelta(hours=3), T0 + pd.Timedelta(hours=3, seconds=5))
    assert [o.info.id for o, _ in voorstellen(signalen, Opname.alle(tmp_path))] == [past.info.id]
    assert binnen_data(past.annotaties, 0.0, signalen) == 1
    assert binnen_data(past.annotaties, 3600.0, signalen) == 0  # met een uur correctie buiten de data


def _acc_met_sprongen(sprongen_s: list[float], ruis: float = 0.005) -> pd.DataFrame:
    t = np.arange(120 * 100) / 100
    rng = np.random.default_rng(1)
    acc = np.column_stack([rng.normal(0, ruis, len(t)), rng.normal(0, ruis, len(t)), np.ones(len(t))])
    for s in sprongen_s:
        acc[int(s * 100), 2] = 4.0
    return pd.DataFrame({"tijd": T0 + pd.to_timedelta(t, unit="s"), "AccX": acc[:, 0], "AccY": acc[:, 1],
                         "AccZ": acc[:, 2]})


def test_sync_negatieve_correctie_en_drift() -> None:
    acc = _acc_met_sprongen([10.0, 100.5])
    eerste = zoek_sync(acc, T0 + pd.Timedelta(seconds=11.0), zoek_s=5)  # pc-klok loopt 1 s vóór
    tweede = zoek_sync(acc, T0 + pd.Timedelta(seconds=101.0), zoek_s=5)
    assert eerste.duidelijk and eerste.correctie_s == pytest.approx(-1.0, abs=0.01)
    assert tweede.correctie_s - eerste.correctie_s == pytest.approx(0.5, abs=0.01)  # drift tussen de syncs


def test_sync_zonder_duidelijke_piek_en_buiten_de_data() -> None:
    acc = _acc_met_sprongen([], ruis=0.05)
    assert not zoek_sync(acc, T0 + pd.Timedelta(seconds=30), zoek_s=5).duidelijk
    assert zoek_sync(acc, T0 + pd.Timedelta(hours=2), zoek_s=5) is None


@pytest.mark.parametrize(("correctie", "uren"), [
    (3676.2, 1), (-3600 + 30, -1), (3600 - 250, 1), (3600 + 400, 0), (76, 0), (7200, 0), (-200, 0),
])
def test_uur_verschoven(correctie: float, uren: int) -> None:
    assert uur_verschoven(correctie) == uren


def test_data_een_uur_verschuiven(tmp_path: Path) -> None:
    opname = Opname.nieuw(Deelnemers(tmp_path).toevoegen("C", 1996, "man", False), T0, root=tmp_path)
    opname.bewaar_signalen(_signalen(T0), [])
    opname.voeg_toe("sync", "sync-sprong", T0 + pd.Timedelta(seconds=10))  # live: pc-tijd
    opname.voeg_toe("periode", "Zitten", T0, T0 + pd.Timedelta(seconds=5), tijdbasis="data")
    opname.zet_klokcorrectie(3601.0, "sync")
    opname.verschuif_signalen(-3600)
    o = Opname.laad(opname.map)
    assert o.laad_signalen()["ecg"].data["tijd"].iloc[0] == T0 - pd.Timedelta(hours=1)
    assert o.info.klokcorrectie_s == pytest.approx(1.0)
    periode = next(a for a in o.annotaties if a.tijdbasis == "data")
    assert periode.t_start == T0 - pd.Timedelta(hours=1)
    sync = next(a for a in o.annotaties if a.soort == "sync")
    assert sync.t_start == T0 + pd.Timedelta(seconds=10)  # pc-tijd blijft, de correctie schuift mee


def test_sync_een_uur_verschoven_gevonden() -> None:
    from kern.verwerking import zoek_sync_of_uur_verschoven

    acc = _acc_met_sprongen([60.0])
    gelogd = T0 + pd.Timedelta(seconds=60 - 3600 + 1.5)  # data loopt een uur (en 1,5 s) voor op de pc
    assert zoek_sync(acc, gelogd, zoek_s=120) is None  # gewoon zoeken vindt niets: buiten de data
    r = zoek_sync_of_uur_verschoven(acc, gelogd, zoek_s=120)
    assert r.duidelijk and r.correctie_s == pytest.approx(3598.5, abs=0.01) and uur_verschoven(r.correctie_s) == 1


def test_syncs_robuust_tegen_andere_beweging_en_een_verkeerde_klik() -> None:
    from kern.verwerking import zoek_syncs

    acc = _acc_met_sprongen([30.0, 40.0, 70.0, 100.0])  # sync-sprongen op 30, 70 en 100 s; op 40 s iets anders
    acc.loc[4000, "AccZ"] = 9.0  # die andere beweging is zelfs groter dan de sprongen
    gelogd = [T0 + pd.Timedelta(seconds=s - 1.0) for s in (30.0, 70.0, 100.0)]  # pc 1 s achter
    ruim = zoek_sync(acc, gelogd[0], zoek_s=120)
    assert ruim.correctie_s == pytest.approx(11.0, abs=0.01)  # alleen ruim zoeken pakt de verkeerde piek
    assert [round(r.correctie_s, 2) for r in zoek_syncs(acc, gelogd, 120)] == [1.0, 1.0, 1.0]

    gelogd[1] = T0 + pd.Timedelta(seconds=70 - 9.0)  # één sync 8 s te laat geklikt...
    correcties = [r.correctie_s for r in zoek_syncs(acc, gelogd, 120)]
    assert float(np.median(correcties)) == pytest.approx(1.0, abs=0.01)  # ...de mediaan blijft kloppen
