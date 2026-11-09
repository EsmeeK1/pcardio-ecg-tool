"""Gedeelde datamap (OneDrive) met een lokale werkkopie en een slot: twee computers, één tegelijk."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import kern.synchronisatie as sync


def _db(pad: Path, waarde: str) -> None:
    with sqlite3.connect(pad) as con:
        con.execute("CREATE TABLE IF NOT EXISTS t (w TEXT)")
        con.execute("INSERT INTO t VALUES (?)", (waarde,))
    con.close()


def _waarden(pad: Path) -> list[str]:
    con = sqlite3.connect(pad)
    try:
        return [r[0] for r in con.execute("SELECT w FROM t")]
    finally:
        con.close()


@pytest.fixture
def opzet(tmp_path: Path, monkeypatch):
    gedeeld, laptop, pc = tmp_path / "OneDrive", tmp_path / "laptop" / "ecg.db", tmp_path / "pc" / "ecg.db"
    gedeeld.mkdir()
    naam = {"nu": "LAPTOP"}
    monkeypatch.setattr(sync, "computernaam", lambda: naam["nu"])
    return gedeeld, laptop, pc, naam


def test_twee_computers_om_de_beurt(opzet) -> None:
    gedeeld, laptop, pc, naam = opzet
    assert sync.controleer(gedeeld).soort == "ok"  # nog niets gedeeld
    sync.open_gedeeld(gedeeld, laptop)
    _db(laptop, "laptop 1")
    sync.publiceer(gedeeld, laptop, vrijgeven=False)  # tussendoor: slot blijft
    naam["nu"] = "PC"
    status = sync.controleer(gedeeld)
    assert (status.soort, status.computer) == ("in_gebruik", "LAPTOP")

    naam["nu"] = "LAPTOP"
    sync.publiceer(gedeeld, laptop, vrijgeven=True)
    naam["nu"] = "PC"
    assert sync.controleer(gedeeld).soort == "ok"
    sync.open_gedeeld(gedeeld, pc)
    assert _waarden(pc) == ["laptop 1"]  # de pc werkt verder met wat de laptop deed
    _db(pc, "pc 1")
    sync.publiceer(gedeeld, pc, vrijgeven=True)

    naam["nu"] = "LAPTOP"
    sync.open_gedeeld(gedeeld, laptop)
    assert _waarden(laptop) == ["laptop 1", "pc 1"]


def test_wachten_tot_onedrive_de_laatste_versie_heeft(opzet) -> None:
    gedeeld, laptop, pc, naam = opzet
    sync.open_gedeeld(gedeeld, laptop)
    _db(laptop, "oud")
    sync.publiceer(gedeeld, laptop, vrijgeven=True)
    oud = gedeeld.parent / "oud.db"
    shutil.copy(gedeeld / sync.DATABASE, oud)
    sync.open_gedeeld(gedeeld, laptop)
    _db(laptop, "nieuw")
    sync.publiceer(gedeeld, laptop, vrijgeven=True)
    shutil.copy(oud, gedeeld / sync.DATABASE)  # de pc ziet het slot al, maar OneDrive heeft de database nog niet

    naam["nu"] = "PC"
    assert sync.controleer(gedeeld).soort == "wacht_op_sync"


def test_na_een_crash_is_de_eigen_werkkopie_het_nieuwst(opzet) -> None:
    gedeeld, laptop, _, naam = opzet
    sync.open_gedeeld(gedeeld, laptop)
    _db(laptop, "bewaard")
    sync.publiceer(gedeeld, laptop, vrijgeven=False)
    _db(laptop, "nog niet gepubliceerd")  # en dan crasht de app: slot blijft 'in gebruik'
    assert sync.controleer(gedeeld).soort == "ok"  # eigen slot
    sync.open_gedeeld(gedeeld, laptop)
    assert _waarden(laptop) == ["bewaard", "nog niet gepubliceerd"]
    assert _waarden(gedeeld / sync.DATABASE) == ["bewaard", "nog niet gepubliceerd"]  # meteen gepubliceerd


def test_kapot_slotbestand_telt_als_geen_slot(opzet) -> None:
    gedeeld, *_ = opzet
    (gedeeld / sync.SLOT).write_text("{half", encoding="utf-8")
    assert sync.controleer(gedeeld).soort == "ok"
