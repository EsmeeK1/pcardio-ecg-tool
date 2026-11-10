"""Rooktest van de desktop-app (offscreen): schermen openen, annoteren in Bekijken, live streamen met de simulator."""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kern.opslag import DATA_ROOT, Deelnemers, Opname  # noqa: E402
from test_opslag_en_export import _signalen  # noqa: E402

DESKTOP = Path(__file__).resolve().parents[2] / "desktop"


@pytest.fixture(scope="module")
def venster():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    sys.path.insert(0, str(DESKTOP))
    spec = importlib.util.spec_from_file_location("desktop_app", DESKTOP / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    v = module.Hoofdvenster()
    v.show()
    yield app, v
    v.close()


def _wacht(app, voorwaarde, timeout: float = 5.0) -> None:
    einde = time.monotonic() + timeout
    while not voorwaarde():
        assert time.monotonic() < einde, "timeout"
        app.processEvents()
        time.sleep(0.02)


def test_bekijken_en_annoteren(venster) -> None:
    app, v = venster
    t0 = pd.Timestamp("2026-10-06 09:00:00", tz="UTC")
    opname = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Desktop", 1996, "vrouw", False), t0, root=DATA_ROOT)
    opname.bewaar_signalen(_signalen(t0, seconden=60), [])
    for rij in range(5):
        v.menu.setCurrentRow(rij)
        app.processEvents()

    v._open("bekijken", str(opname.map))
    b = v.bekijken
    assert b._ecg is not None and b.lijst.rowCount() == 0
    b.selectie.setRegion((t0.timestamp() + 2, t0.timestamp() + 7))
    b._nieuw("periode", "Zitten")
    a = Opname.laad(opname.map).annotaties[0]
    assert (a.label, a.tijdbasis) == ("Zitten", "data") and a.duur_s == pytest.approx(5.0, abs=0.01)

    b.lijst.selectRow(0)
    app.processEvents()
    b.selectie.setRegion((t0.timestamp() + 3, t0.timestamp() + 10))
    b.beoordeling.setCurrentIndex(1)
    b._opslaan()
    a = Opname.laad(opname.map).annotaties[0]
    assert a.duur_s == pytest.approx(7.0, abs=0.01) and a.beoordeling == "schoon"


def test_live_met_simulator(venster) -> None:
    app, v = venster
    live = v.live
    live.modus.setCurrentText("Gesimuleerd")
    live._verbind()
    _wacht(app, lambda: live.sessie.toestand == "verbonden")
    live._start()
    _wacht(app, lambda: live.lijnen_ecg[0].xData is not None and len(live.lijnen_ecg[0].xData) > 250)
    live._ontkoppel()
    assert live.sessie is None


def test_koppelen_export_terug_en_sync(venster, tmp_path: Path, monkeypatch) -> None:
    import analyse
    from kern.export import gecombineerd

    app, v = venster
    monkeypatch.setattr(analyse, "fout", lambda _, tekst: pytest.fail(tekst))  # geen dialoogvenster in de test
    t0 = pd.Timestamp("2026-10-07 09:00:00", tz="UTC")
    bron = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Koppel", 1996, "man", False), t0, root=DATA_ROOT)
    signalen = _signalen(t0)
    bron.bewaar_signalen(signalen, [])
    bron.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))  # landing in de data op t0 + 10 s
    data, annotaties = tmp_path / "x_volledig.csv", tmp_path / "x_annotaties.csv"
    gecombineerd(bron, signalen).to_csv(data, index=False)
    bron.annotaties_df().to_csv(annotaties, index=False)
    deelnemer = bron.info.deelnemer_id
    bron.verwijder_opname()  # de nieuwe opname krijgt hetzelfde ID (zelfde start en deelnemer)

    k = v.koppelen
    k._lees([data, annotaties])
    assert not k.ingelezen.fouten and set(k.ingelezen.soorten.values()) == {"export", "annotaties"}
    k.doel.setCurrentIndex(k.doel.findData("__nieuw__"))
    k.deelnemer.setCurrentIndex(next(i for i in range(k.deelnemer.count()) if k.deelnemer.itemData(i).id == deelnemer))
    k._koppel()
    nieuw = Opname.laad(bron.map)
    assert nieuw.heeft_signalen and [a.soort for a in nieuw.annotaties] == ["sync"]

    k.klok_opname.setCurrentIndex(k.klok_opname.findData(str(nieuw.map)))
    k._zoek_sync()
    assert k._voorstel == pytest.approx(1.2, abs=0.02)
    k._zet_correctie(k._voorstel, "sync")
    assert Opname.laad(nieuw.map).info.klokcorrectie_s == pytest.approx(1.2, abs=0.02)


def _twee_opnames() -> tuple[Opname, Opname]:
    register = Deelnemers(DATA_ROOT)
    a = Opname.nieuw(register.toevoegen("Sticker", 1996, "vrouw", False), pd.Timestamp("2026-10-08 09:00", tz="UTC"),
                     root=DATA_ROOT, elektroden="Optie 1: met sticker")
    b = Opname.nieuw(register.toevoegen("Lanyard", 1986, "man", False), pd.Timestamp("2026-10-09 09:00", tz="UTC"),
                     root=DATA_ROOT, elektroden="Optie 2: met lanyard")
    for o in (a, b):
        o.bewaar_signalen(_signalen(pd.Timestamp(o.info.gestart).tz_convert("UTC"), seconden=60), [])
    return a, b


def test_bekijken_wisselen_filters_sneltoetsen_hover(venster) -> None:
    from PySide6.QtGui import QShortcut

    app, v = venster
    a, b = _twee_opnames()
    v._open("bekijken", str(a.map))
    k = v.bekijken
    assert k._geladen == str(a.map) and k.bevestiging.currentText() == "sticker"
    k.keuze.setCurrentIndex(k.keuze.findData(str(b.map)))  # zoals de gebruiker: via het signaal (was de bug)
    app.processEvents()
    assert k._geladen == str(b.map) and k.bevestiging.currentText() == "lanyard"

    k.f_deelnemer.setCurrentIndex(k.f_deelnemer.findData(a.info.deelnemer_id))
    assert [k.keuze.itemData(i) for i in range(k.keuze.count())] == [str(a.map)] and k._geladen == str(a.map)
    k.f_deelnemer.setCurrentIndex(0)
    k.f_bevestiging.setCurrentText("lanyard")
    assert str(a.map) not in [k.keuze.itemData(i) for i in range(k.keuze.count())]
    k.f_bevestiging.setCurrentIndex(0)
    k.f_datum.setCurrentIndex(k.f_datum.findData("2026-10-08"))
    assert [k.keuze.itemData(i) for i in range(k.keuze.count())] == [str(a.map)]
    k.f_datum.setCurrentIndex(0)

    sneltoetsen = {s.key().toString(): s for s in k.findChildren(QShortcut)}
    assert {"Ctrl+R", "Shift+Left", "Shift+Right"} <= set(sneltoetsen)
    x0 = k._bereik[0]
    assert k.venster.getRegion() == pytest.approx((x0 + 5, x0 + 15), abs=0.01)  # beginweergave
    sneltoetsen["Shift+Right"].activated.emit()
    assert k.venster.getRegion()[0] == pytest.approx(x0 + 15, abs=0.01)
    k.venster.setRegion((x0 + 30, x0 + 31))
    sneltoetsen["Ctrl+R"].activated.emit()
    assert k.venster.getRegion() == pytest.approx((x0 + 5, x0 + 15), abs=0.01)

    k.toon_acc.setChecked(True)
    k.toon_gyro.setChecked(True)
    app.processEvents()
    assert k.acc_plot.isVisible() and len(k.acc_plot.listDataItems()) == 4  # X, Y, Z en |acc|
    assert len(k.gyro_plot.listDataItems()) == 0  # deze testopname heeft geen gyro
    from PySide6.QtCore import QPointF

    v.resize(1400, 1000)
    k.beweging_plot.setXRange(x0, x0 + 40, padding=0)
    app.processEvents()
    k._hover(k.beweging_plot.getViewBox().mapViewToScene(QPointF(x0 + 5, 1.5)))  # boven het eerste segment
    assert "activiteit:" in k.hover.text() and "houding:" in k.hover.text()


def test_deelnemers_scherm(venster) -> None:
    app, v = venster
    d = v.deelnemers
    d._nieuw()
    d.naam.setText("Zoë 😀")
    d.geboortejaar.setValue(d.geboortejaar.minimum())  # onbekend
    d._opslaan()
    nieuw = Deelnemers(DATA_ROOT).alle()[-1]
    assert (nieuw.naam, nieuw.geboortejaar) == ("Zoë 😀", None) and d.kop.text().startswith(f"<b>{nieuw.id}")
    d.naam.setText("Zoë")
    d._opslaan()
    assert Deelnemers(DATA_ROOT).alle()[-1].naam == "Zoë"


def test_live_balk_en_buffer_van_20_s(venster, monkeypatch) -> None:
    app, v = venster
    live = v.live
    live.modus.setCurrentText("Gesimuleerd")
    live._verbind()
    _wacht(app, lambda: live.sessie.toestand == "verbonden")
    assert live.sessie.buffer.seconden == 20 and live.sessie.gyro_buffer.seconden == 20
    live._status()
    assert live.waarschuwing.isHidden()
    monkeypatch.setattr(live.sessie, "verbroken", True)
    live._status()
    assert not live.waarschuwing.isHidden() and "kwijt" in live.waarschuwing.text()
    monkeypatch.setattr(live.sessie, "verbroken", False)
    live._ontkoppel()


def test_koppelen_uur_voorstel_en_overschrijven(venster, monkeypatch) -> None:
    import analyse

    app, v = venster
    monkeypatch.setattr(analyse, "zeker", lambda *_: True)
    monkeypatch.setattr(analyse, "fout", lambda _, tekst: pytest.fail(tekst))
    t0 = pd.Timestamp("2026-10-10 09:00:00", tz="UTC")
    o = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Uur", 1996, "man", False), t0, root=DATA_ROOT)
    o.bewaar_signalen(_signalen(t0), [])  # landing op t0 + 10 s
    o.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=10 - 3600 - 1.2))  # data een uur voor
    k = v.koppelen
    k.open_opname(str(o.map))
    k._zoek_sync()
    assert k._voorstel == pytest.approx(3601.2, abs=0.05) and not k.uur.isHidden() and not k.k_uur.isHidden()
    k._verschuif_uur()
    assert k._voorstel == pytest.approx(1.2, abs=0.05) and k.uur.isHidden()

    gevraagd = []
    monkeypatch.setattr(analyse, "zeker", lambda _, vraag: gevraagd.append(vraag) or False)
    from kern.koppelen import Ingelezen
    k.ingelezen = Ingelezen(signalen=_signalen(t0), soorten={"x.txt": "pcardio"})
    k._vul_doel()
    k.doel.setCurrentIndex(k.doel.findData(str(o.map)))
    k._koppel()
    assert gevraagd and "Vervangen?" in gevraagd[0]  # geweigerd: niets vervangen


def test_bekijken_markeert_rijen_in_beeld(venster) -> None:
    app, v = venster
    t0 = pd.Timestamp("2026-10-11 09:00:00", tz="UTC")
    o = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Inbeeld", 1996, "man", False), t0, root=DATA_ROOT)
    o.bewaar_signalen(_signalen(t0, seconden=60), [])
    o.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=2), t0 + pd.Timedelta(seconds=20), tijdbasis="data")
    o.voeg_toe("periode", "Lopen (rustig)", t0 + pd.Timedelta(seconds=40), t0 + pd.Timedelta(seconds=55),
               tijdbasis="data")
    v._open("bekijken", str(o.map))
    k = v.bekijken
    oranje = lambda r: k.lijst.item(r, 1).background().color().name() == "#ffe6c7"  # noqa: E731
    assert [k.lijst.item(r, 1).text() for r in range(2)] == ["Zitten", "Lopen (rustig)"]
    assert oranje(0) and not oranje(1)  # beginweergave 5–15 s valt in Zitten
    k.venster.setRegion((t0.timestamp() + 42, t0.timestamp() + 50))
    app.processEvents()
    assert not oranje(0) and oranje(1)
    k.venster.setRegion((t0.timestamp() + 15, t0.timestamp() + 45))  # over beide heen
    app.processEvents()
    assert oranje(0) and oranje(1)


def test_live_volgt_verplaatste_dongle(venster, monkeypatch) -> None:
    import live as live_module

    app, v = venster
    l = v.live
    aanwezig = [("COM3", "COM3: Serieel USB-apparaat (COM3) (dongle)")]
    monkeypatch.setattr(live_module, "poorten", lambda: list(aanwezig))
    monkeypatch.setattr(live_module, "zoek_dongle", lambda: next((p for p, t in aanwezig if "(dongle)" in t), None))
    l._volg_poorten()
    assert l.poort.currentData() == "COM3"
    aanwezig[:] = [("COM1", "COM1: Communicatiepoort"), ("COM4", "COM4: Serieel USB-apparaat (COM4) (dongle)")]
    l._volg_poorten()  # dongle in een andere USB-poort gestoken
    assert l.poort.currentData() == "COM4" and l.poort.count() == 2


def test_ctrl_z_en_ctrl_shift_z(venster) -> None:
    from PySide6.QtGui import QShortcut

    from kern.opslag import GESCHIEDENIS

    app, v = venster
    GESCHIEDENIS.wis()
    t0 = pd.Timestamp("2026-10-12 09:00:00", tz="UTC")
    o = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Ctrl", 1996, "man", False), t0, root=DATA_ROOT)
    v._open("live", str(o.map))
    v.live._start_periode("Zitten")
    assert v.live.log.rowCount() == 1
    sneltoetsen = {s.key().toString(): s for s in v.findChildren(QShortcut)}
    sneltoetsen["Ctrl+Z"].activated.emit()
    assert v.live.log.rowCount() == 0 and "Periode gestart" in v.statusBar().currentMessage()
    sneltoetsen["Ctrl+Shift+Z"].activated.emit()
    assert v.live.log.rowCount() == 1 and v.live.periode_knoppen["Zitten"].isChecked()


def test_live_waarschuwt_bij_ondersteboven_recorder(venster, monkeypatch) -> None:
    app, v = venster
    live = v.live
    live.modus.setCurrentText("Gesimuleerd")
    live.bevestiging.setCurrentText("sticker")
    live._verbind()
    _wacht(app, lambda: live.sessie.toestand == "verbonden")
    monkeypatch.setattr(live.sessie, "toestand", "streamen")  # zonder 20 s te wachten
    for kanteling, verwacht in ((178.0, True), (12.0, False)):
        live._houding = (0.0, "sticker", "onbekend" if kanteling > 135 else "rechtop", kanteling)
        live._waarschuwingen(live.sessie)
        assert ("ondersteboven" in live.waarschuwing.text() and not live.waarschuwing.isHidden()) == verwacht
    monkeypatch.setattr(live.sessie, "toestand", "verbonden")
    live._ontkoppel()


def test_koppelen_bestanden_uit_twee_mappen_toevoegen(venster, tmp_path: Path) -> None:
    from kern.export import gecombineerd

    app, v = venster
    t0 = pd.Timestamp("2026-10-13 09:00:00", tz="UTC")
    bron = Opname.nieuw(Deelnemers(DATA_ROOT).toevoegen("Twee mappen", 1996, "man", False), t0, root=DATA_ROOT)
    signalen = _signalen(t0)
    bron.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=2), t0 + pd.Timedelta(seconds=8))
    (tmp_path / "pcardio").mkdir()
    (tmp_path / "telefoon").mkdir()
    data, annotaties = tmp_path / "pcardio" / "x_volledig.csv", tmp_path / "telefoon" / "x_annotaties.csv"
    gecombineerd(bron, signalen).to_csv(data, index=False)
    bron.annotaties_df().to_csv(annotaties, index=False)

    k = v.koppelen
    k._leegmaken()
    k._lees([data])  # eerst de data van de recorder (andere map)...
    k._lees([annotaties])  # ...dan de CSV van de telefoon: komt erbij, vervangt niet
    k._lees([annotaties])  # dubbel kiezen telt één keer
    assert set(k.ingelezen.soorten.values()) == {"export", "annotaties"} and not k.ingelezen.fouten
    k._leegmaken()
    assert k.ingelezen is None and k._paden == []
