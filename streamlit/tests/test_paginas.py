"""Rooktest van de pagina's met Streamlit's AppTest, per pagina."""

from __future__ import annotations

import zipfile
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from kern.export import gecombineerd
from kern.opslag import DATA_ROOT, Deelnemers, Opname
from test_opslag_en_export import _signalen

APP = Path(__file__).resolve().parents[1]


def _app(pagina: str) -> AppTest:
    return AppTest.from_file(str(APP / "paginas" / pagina), default_timeout=60)


def _knop(at: AppTest, begin: str):
    return next(b for b in at.button if b.label.startswith(begin))


@pytest.fixture(scope="module")
def opname() -> Opname:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    deelnemer = Deelnemers(DATA_ROOT).toevoegen("Test", 40, "man", False)
    opname = Opname.nieuw(deelnemer, t0, root=DATA_ROOT)
    opname.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))
    opname.voeg_toe("periode", "Springen", t0 + pd.Timedelta(seconds=12), t0 + pd.Timedelta(seconds=14))
    opname.bewaar_signalen(_signalen(t0), [])
    return opname


def test_deelnemers(opname: Opname) -> None:
    at = _app("deelnemers.py").run()
    assert not at.exception, at.exception


def test_deelnemer_verwijderen_via_pagina() -> None:
    weg = Deelnemers(DATA_ROOT).toevoegen("Weg", None, "onbekend", False)
    at = _app("deelnemers.py").run()
    next(s for s in at.selectbox if s.label == "Deelnemer").set_value(weg.id).run()
    _knop(at, "Ja, verwijderen").click().run()
    assert not at.exception, at.exception
    assert weg.id not in {d.id for d in Deelnemers(DATA_ROOT).alle()}
    assert any("verwijderd" in s.value for s in at.success)


def test_live_startscherm_elektroden(opname: Opname) -> None:
    eigen = Deelnemers(DATA_ROOT).toevoegen("Elektroden", None, "onbekend", False)
    at = _app("live.py").run()
    assert not at.exception, at.exception
    next(s for s in at.selectbox if s.label == "Deelnemer").set_value(eigen.id)
    plaatsing = next(s for s in at.selectbox if s.label.startswith("Plaatsing"))
    assert plaatsing.options == ["Optie 1: met sticker", "Optie 2: met lanyard"]
    assert plaatsing.value == "Optie 2: met lanyard"  # standaard
    plaatsing.set_value("Optie 2: met lanyard")
    at.text_input[0].input("Huid met alcohol schoongemaakt")
    _knop(at, "Start opname").click().run()
    assert not at.exception, at.exception
    info = Opname.laad(at.session_state["live_map"]).info
    assert (info.elektroden, info.huidvoorbereiding) == ("Optie 2: met lanyard", "Huid met alcohol schoongemaakt")


def test_live(opname: Opname) -> None:
    live = Opname.nieuw(Deelnemers(DATA_ROOT).alle()[0], pd.Timestamp.now(tz="UTC"), root=DATA_ROOT)
    at = _app("live.py")
    at.session_state["live_map"] = str(live.map)
    at.run()
    for knop in ("Sync-sprong", "Zitten", "Lopen (rustig)", "Stop periode", "Ja, afsluiten"):
        _knop(at, knop).click().run()
        assert not at.exception, (knop, at.exception)
    perioden = [a.label for a in Opname.laad(live.map).chronologisch() if a.soort == "periode"]
    assert perioden == ["Zitten", "Lopen (rustig)"]


def test_live_plaatsing_blijft_staan_en_experiment(opname: Opname) -> None:
    eigen = Deelnemers(DATA_ROOT).toevoegen("Plaatsing", None, "onbekend", False)
    live = Opname.nieuw(eigen, pd.Timestamp.now(tz="UTC"), root=DATA_ROOT)
    at = _app("live.py")
    at.session_state["live_map"] = str(live.map)
    at.run()
    next(t for t in at.text_input if t.label.startswith("Plaatsing")).input("R2-Y2-G4").run()
    for knop in ("Zitten", "Armen bewegen"):  # tweede periode: niets opnieuw typen
        _knop(at, knop).click().run()
    next(t for t in at.text_input if t.label.startswith("Plaatsing")).input("R1-Y1").run()
    _knop(at, "Lopen (rustig)").click().run()
    next(t for t in at.text_input if t.label == "Experiment").input("Elektrodeplaatsing 21-10").run()
    assert not at.exception, at.exception

    geladen = Opname.laad(live.map)
    assert [(a.label, a.plaatsing) for a in geladen.chronologisch()] == [
        ("Zitten", "R2-Y2-G4"), ("Armen bewegen", "R2-Y2-G4"), ("Lopen (rustig)", "R1-Y1"),
    ]
    assert geladen.info.experiment == "Elektrodeplaatsing 21-10"

    # Na hervatten (nieuwe sessie) staat de laatste plaatsing weer in het veld.
    opnieuw = _app("live.py")
    opnieuw.session_state["live_map"] = str(live.map)
    opnieuw.run()
    assert next(t for t in opnieuw.text_input if t.label.startswith("Plaatsing")).value == "R1-Y1"


def test_koppelen_klokcorrectie(opname: Opname) -> None:
    at = _app("koppelen.py")
    at.session_state["klok_opname"] = opname.info.id
    at.run()
    assert not at.exception, at.exception
    _knop(at, "Gebruik voorstel").click().run()
    assert Opname.laad(opname.map).info.klokcorrectie_s == pytest.approx(1.2, abs=0.02)


def test_koppelen_export_zip(tmp_path: Path) -> None:
    """Een eerdere export (zip met data + annotaties) terugzetten op dezelfde opname."""
    t0 = pd.Timestamp("2026-10-04 08:00:00", tz="UTC")
    opname = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Import", None, "onbekend", False), t0, root=DATA_ROOT)
    opname.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=2), t0 + pd.Timedelta(seconds=5))
    opname.zet_klokcorrectie(0.5, "sync")
    zip_pad = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_pad, "w") as zf:
        zf.writestr(f"map/{opname.info.id}_volledig.csv", gecombineerd(opname, _signalen(t0)).to_csv(index=False))
        zf.writestr(f"map/{opname.info.id}_annotaties.csv", opname.annotaties_df().to_csv(index=False))
    opname.verwijder([1])
    opname.zet_klokcorrectie(None, "")

    at = _app("koppelen.py").run()
    at.text_input[0].input(str(zip_pad)).run()
    next(b for b in at.button if b.key == "lees_lokaal").click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.selectbox[0].value == opname.info.id
    assert any("Alle 1 annotaties" in s.value for s in at.success)
    _knop(at, "Koppel").click().run()
    assert not at.exception, at.exception
    geladen = Opname.laad(opname.map)
    assert [a.label for a in geladen.annotaties] == ["Zitten"]
    assert geladen.info.klokcorrectie_s == pytest.approx(0.5)
    assert geladen.heeft_signalen and set(geladen.laad_signalen()) == {"ecg", "acc"}


def test_koppelen_zonder_live_annotaties_wordt_nieuwe_opname(opname: Opname, tmp_path: Path) -> None:
    """Data die bij geen enkele opname past (bijv. wandeling zonder live annoteren): standaard een nieuwe opname."""
    pad = tmp_path / "wandeling_volledig.csv"
    gecombineerd(opname, _signalen(pd.Timestamp("2026-10-01 12:00:00", tz="UTC"))).to_csv(pad, index=False)
    at = _app("koppelen.py").run()
    at.text_input[0].input(str(pad)).run()
    next(b for b in at.button if b.key == "lees_lokaal").click().run()
    assert not at.exception, at.exception
    assert at.selectbox[0].value == "__nieuw__"


def test_bekijken_periode_typen_in_overzicht(opname: Opname) -> None:
    at = _app("bekijken.py")
    at.session_state["bekijk_opname"] = opname.info.id
    at.run()
    # Opname loopt 10:00:00 – 10:00:20 (Amsterdam).
    next(t for t in at.text_input if t.label.startswith("Begin periode")).input("10:00:02")
    next(t for t in at.text_input if t.label.startswith("Eind periode")).input("10:00:07").run()
    assert not at.error, [e.value for e in at.error]
    _knop(at, "Lopen (rustig)").click().run()
    assert not at.exception, at.exception
    wandelen = [a for a in Opname.laad(opname.map).annotaties if a.label == "Lopen (rustig)" and a.tijdbasis == "data"]
    assert len(wandelen) == 1 and wandelen[0].duur_s == pytest.approx(5.0, abs=0.01)

    next(t for t in at.text_input if t.label.startswith("Begin periode")).input("kwart over")
    next(t for t in at.text_input if t.label.startswith("Eind periode")).input("10:00:07").run()
    assert any("geen kloktijd" in e.value for e in at.error)


def test_bekijken_en_export(opname: Opname) -> None:
    at = _app("bekijken.py")
    at.session_state["bekijk_opname"] = opname.info.id
    at.run()
    assert not at.exception, at.exception
    _knop(at, "Volgende").click().run()
    _knop(at, "Volgende").click().run()
    assert not at.exception, at.exception

    at = _app("export.py")
    at.session_state["export_opname"] = opname.info.id
    at.run()
    _knop(at, "Maak export").click().run()
    assert not at.exception, at.exception
    assert list((opname.map / "export").glob("*_volledig.csv"))


def test_bekijken_filter_scrollen_en_labelknoppen(opname: Opname) -> None:
    at = _app("bekijken.py")
    at.session_state["bekijk_opname"] = opname.info.id
    at.run()
    assert not at.exception, at.exception
    assert any("gefilterd" in m.value for m in at.markdown)

    next(t for t in at.toggle if t.label.startswith("ECG-filter")).set_value(False).run()
    assert not at.exception, at.exception
    assert any("ECG ruw" in m.value for m in at.markdown)

    # Vanuit een annotatie scrollen: verder als vrij venster.
    _knop(at, "Volgende").click().run()
    assert at.session_state[f"segment_{opname.info.id}"] != "vrij"
    scroll = at.slider(key=f"start_{opname.info.id}")
    assert scroll.value.strftime("%H:%M") == "10:00"  # kloktijd: opname start 08:00 UTC = 10:00 Amsterdam
    scroll.set_value(scroll.value + timedelta(seconds=3)).run()
    assert not at.exception, at.exception
    assert at.session_state[f"segment_{opname.info.id}"] == "vrij"

    # Terug/Verder schuift een venster op, maar niet voorbij het begin of eind van de opname.
    voor = at.slider(key=f"start_{opname.info.id}").value
    _knop(at, "Verder").click().run()
    assert at.slider(key=f"start_{opname.info.id}").value > voor
    _knop(at, "◀ Terug").click().run()
    _knop(at, "◀ Terug").click().run()
    assert at.slider(key=f"start_{opname.info.id}").value.strftime("%H:%M:%S") == "10:00:00"

    # Periode toevoegen met een label-knop (begin/eind ingevuld zoals een selectie dat zou doen).
    next(n for n in at.number_input if n.label.startswith("Begin (s vanaf")).set_value(1.0)
    next(n for n in at.number_input if n.label.startswith("Eind (s vanaf")).set_value(2.5)
    _knop(at, "Staan").click().run()
    assert not at.exception, at.exception
    staan = [a for a in Opname.laad(opname.map).annotaties if a.label == "Staan"]
    assert len(staan) == 1 and staan[0].tijdbasis == "data" and staan[0].duur_s == pytest.approx(1.5)


def test_handleiding() -> None:
    at = _app("handleiding.py").run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 5


def test_testopname_voortgang_en_oefenopname() -> None:
    at = _app("testopname.py").run()
    assert not at.exception, at.exception
    at.checkbox(key="stap_app").check().run()
    assert not at.exception, at.exception

    opnieuw = _app("testopname.py").run()
    assert opnieuw.checkbox(key="stap_app").value is True

    oefen = [b for b in opnieuw.button if b.label.startswith("Maak oefenopname")]
    if oefen:  # alleen als streamlit/data/test aanwezig is
        oefen[0].click().run()
        assert not opnieuw.exception, opnieuw.exception
        assert any(o.heeft_signalen and "Oefenopname" in o.info.notities for o in Opname.alle(DATA_ROOT))

    _knop(opnieuw, "Opnieuw beginnen").click().run()
    assert opnieuw.checkbox(key="stap_app").value is False


def _wacht_tot(voorwaarde, timeout: float = 5.0) -> None:
    import time

    einde = time.monotonic() + timeout
    while not voorwaarde():
        assert time.monotonic() < einde, "timeout"
        time.sleep(0.05)


def test_live_ecg_gesimuleerd() -> None:
    from ui import live_sessie

    at = _app("live_ecg.py").run()
    assert not at.exception, at.exception
    at.sidebar.radio(key="live_modus").set_value("Gesimuleerd").run()
    _knop(at, "Verbinden").click().run()
    assert not at.exception, at.exception
    try:
        _wacht_tot(lambda: live_sessie() is not None and live_sessie().toestand == "verbonden")
        at.run()
        _knop(at, "Start").click().run()
        _wacht_tot(lambda: live_sessie().tellers["pakketten"] >= 2)
        at.run()
        assert not at.exception, at.exception
        assert at.get("plotly_chart"), "geen live plot"
        assert any(m.label == "Firmware" and m.value == "3.3.1.1" for m in at.metric)
        assert any(m.label == "Recorder" and m.value == "neemt NIET op" for m in at.metric)
    finally:
        _knop(at, "Ontkoppelen").click().run()
    assert live_sessie() is None
    assert not at.exception, at.exception
