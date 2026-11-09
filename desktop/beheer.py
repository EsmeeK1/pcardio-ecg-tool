"""Beheer: deelnemers en opnames bekijken, toevoegen, bewerken, verwijderen en exporteren."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from gedeeld import OpnameVelden, bezig, fout, hulp, klok, opname_label, tips, zeker
from kern.export import gecombineerd
from kern.opslag import DATA_ROOT, EERSTE_JAAR, GESLACHTEN, Deelnemer, Deelnemers, Opname, nu


def tabel(koppen: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(koppen))
    t.setHorizontalHeaderLabels(koppen)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(True)
    return t


def vul(t: QTableWidget, rijen: list[list[object]], sleutels: list[str]) -> None:
    """Rijen in de tabel; ``sleutels`` komt als data in de eerste kolom (terug te lezen met ``gekozen``)."""
    t.setSortingEnabled(False)
    t.setRowCount(len(rijen))
    for r, (rij, sleutel) in enumerate(zip(rijen, sleutels)):
        for k, waarde in enumerate(rij):
            item = QTableWidgetItem("" if waarde is None else str(waarde))
            if k == 0:
                item.setData(256, sleutel)  # Qt.UserRole
            t.setItem(r, k, item)
    t.setSortingEnabled(True)


def gekozen(t: QTableWidget) -> str | None:
    rijen = t.selectionModel().selectedRows()
    return t.item(rijen[0].row(), 0).data(256) if rijen else None


class DeelnemersScherm(QWidget):
    gewijzigd = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.register = Deelnemers(DATA_ROOT)
        self.tabel = tabel(["ID", "Naam", "Geboortejaar", "Geslacht", "Hartdecompensatie", "Andere aandoening", "Opnames"])
        self.tabel.itemSelectionChanged.connect(self._laad_formulier)

        self.naam, self.geboortejaar = QLineEdit(), QSpinBox()
        self.geboortejaar.setRange(EERSTE_JAAR - 1, nu().year)
        self.geboortejaar.setSpecialValueText("onbekend")  # EERSTE_JAAR - 1 = onbekend
        self.geslacht = QComboBox()
        self.geslacht.addItems(GESLACHTEN)
        self.hart, self.aandoening = QCheckBox("Bekende hartdecompensatie"), QLineEdit()
        vorm = QFormLayout()
        vorm.addRow("Voornaam of patiënt-ID", self.naam)
        vorm.addRow("Geboortejaar", self.geboortejaar)
        vorm.addRow("Geslacht", self.geslacht)
        vorm.addRow("", self.hart)
        vorm.addRow("Andere aandoening", self.aandoening)
        nieuw, opslaan, weg = QPushButton("Nieuw"), QPushButton("Opslaan"), QPushButton("Verwijderen")
        opslaan.setDefault(True)
        nieuw.clicked.connect(self._nieuw)
        opslaan.clicked.connect(self._opslaan)
        weg.clicked.connect(self._verwijder)
        knoppen = QHBoxLayout()
        for k in (nieuw, opslaan, weg):
            knoppen.addWidget(k)
        self.kop = QLabel()
        groep = QGroupBox("Deelnemer")
        g = QVBoxLayout(groep)
        g.addWidget(self.kop)
        g.addLayout(vorm)
        g.addLayout(knoppen)
        g.addWidget(QLabel("Zet in het User Id-veld van de P-Cardio het ID, niet de naam: dat veld is niet versleuteld."))
        tips((self.naam, hulp.NAAM), (self.geboortejaar, hulp.GEBOORTEJAAR), (self.geslacht, hulp.GESLACHT),
             (self.hart, hulp.HARTDECOMPENSATIE), (self.aandoening, hulp.ANDERE_AANDOENING), (weg, hulp.VERWIJDER_DEELNEMER),
             (self.tabel, hulp.DEELNEMERS))
        g.addStretch()

        splitter = QSplitter()
        splitter.addWidget(self.tabel)
        splitter.addWidget(groep)
        splitter.setSizes([700, 350])
        QVBoxLayout(self).addWidget(splitter)
        self.ververs()
        self._nieuw()

    def ververs(self) -> None:
        opnames = pd.Series([o.info.deelnemer_id for o in Opname.alle(DATA_ROOT)]).value_counts()
        alle = self.register.alle()
        vul(self.tabel, [[d.id, d.naam, d.geboortejaar, d.geslacht, "ja" if d.hartdecompensatie else "nee",
                          d.andere_aandoening, int(opnames.get(d.id, 0))] for d in alle], [d.id for d in alle])

    def _deelnemer(self) -> Deelnemer | None:
        id = gekozen(self.tabel)
        return next((d for d in self.register.alle() if d.id == id), None)

    def _laad_formulier(self) -> None:
        d = self._deelnemer()
        if d is None:
            return
        self.kop.setText(f"<b>{d.id}</b> · aangemaakt {d.aangemaakt[:10]}")
        self.naam.setText(d.naam)
        self.geboortejaar.setValue(self.geboortejaar.minimum() if d.geboortejaar is None else d.geboortejaar)
        self.geslacht.setCurrentText(d.geslacht)
        self.hart.setChecked(d.hartdecompensatie)
        self.aandoening.setText(d.andere_aandoening)

    def _nieuw(self) -> None:
        self.tabel.clearSelection()
        self.kop.setText("<b>Nieuwe deelnemer</b> · krijgt het volgende vrije ID")
        self.naam.clear()
        self.geboortejaar.setValue(self.geboortejaar.minimum())
        self.geslacht.setCurrentText("onbekend")
        self.hart.setChecked(False)
        self.aandoening.clear()
        self.naam.setFocus()

    def _opslaan(self) -> None:
        jaar = self.geboortejaar.value()
        velden = (self.naam.text().strip(), None if jaar == self.geboortejaar.minimum() else jaar, self.geslacht.currentText(), self.hart.isChecked(),
                  self.aandoening.text().strip())
        try:
            d = self._deelnemer()
            if d is None:
                d = self.register.toevoegen(*velden)
            else:
                d.naam, d.geboortejaar, d.geslacht, d.hartdecompensatie, d.andere_aandoening = velden
                self.register.bijwerken(d)
        except ValueError as e:
            fout(self, str(e))
            return
        self.ververs()
        self._selecteer(d.id)
        self.gewijzigd.emit()

    def _selecteer(self, id: str) -> None:
        for r in range(self.tabel.rowCount()):
            if self.tabel.item(r, 0).data(256) == id:
                self.tabel.selectRow(r)

    def _verwijder(self) -> None:
        d = self._deelnemer()
        if d is None or not zeker(self, f"Deelnemer {d.weergave} verwijderen? Het ID wordt niet opnieuw uitgegeven."):
            return
        try:
            self.register.verwijder(d.id)
        except ValueError as e:
            fout(self, str(e))
            return
        self.ververs()
        self._nieuw()
        self.gewijzigd.emit()


class OpnamesScherm(QWidget):
    """Alle opnames met filter; per opname gegevens bewerken, openen in een ander scherm, exporteren, verwijderen."""

    openen = Signal(str, str)  # (scherm, map van de opname)

    def __init__(self) -> None:
        super().__init__()
        self.filter_deelnemer, self.zoek = QComboBox(), QLineEdit()
        self.zoek.setPlaceholderText("Zoeken op ID, experiment of notities…")
        self.filter_deelnemer.currentIndexChanged.connect(self.ververs)
        self.zoek.textChanged.connect(self.ververs)
        boven = QHBoxLayout()
        boven.addWidget(QLabel("Deelnemer"))
        boven.addWidget(self.filter_deelnemer)
        boven.addWidget(self.zoek, 1)

        self.tabel = tabel(["Opname", "Deelnemer", "Gestart", "Elektroden", "Experiment", "Annotaties", "Data",
                            "Klokcorrectie", "Live"])
        self.tabel.itemSelectionChanged.connect(self._laad_formulier)
        self.tabel.doubleClicked.connect(lambda: self._open("bekijken"))

        self.kop = QLabel("Kies een opname.")
        self.velden = OpnameVelden()
        opslaan = QPushButton("Gegevens opslaan")
        opslaan.clicked.connect(self._opslaan)
        knoppen = [("Bekijken && annoteren", lambda: self._open("bekijken")),
                   ("Data koppelen", lambda: self._open("koppelen")),
                   ("Live hervatten", lambda: self._open("live")),
                   ("Exporteren…", self._exporteer),
                   ("Map openen", self._map_openen),
                   ("Opname verwijderen…", self._verwijder)]
        groep = QGroupBox("Opname")
        g = QVBoxLayout(groep)
        g.addWidget(self.kop)
        g.addWidget(self.velden)
        g.addWidget(opslaan)
        self.knoppen = []
        for tekst, actie in knoppen:
            k = QPushButton(tekst)
            k.clicked.connect(actie)
            g.addWidget(k)
            self.knoppen.append(k)
        g.addStretch()

        splitter = QSplitter()
        links = QWidget()
        l = QVBoxLayout(links)
        l.setContentsMargins(0, 0, 0, 0)
        l.addLayout(boven)
        l.addWidget(self.tabel)
        splitter.addWidget(links)
        splitter.addWidget(groep)
        splitter.setSizes([800, 380])
        QVBoxLayout(self).addWidget(splitter)
        self.ververs_deelnemers()

    def ververs_deelnemers(self) -> None:
        huidig = self.filter_deelnemer.currentData()
        self.namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
        self.filter_deelnemer.blockSignals(True)
        self.filter_deelnemer.clear()
        self.filter_deelnemer.addItem("Alle", None)
        for id, naam in self.namen.items():
            self.filter_deelnemer.addItem(naam, id)
        self.filter_deelnemer.setCurrentIndex(max(self.filter_deelnemer.findData(huidig), 0))
        self.filter_deelnemer.blockSignals(False)
        self.ververs()

    def ververs(self) -> None:
        deelnemer, zoek = self.filter_deelnemer.currentData(), self.zoek.text().lower()
        self.opnames = {str(o.map): o for o in Opname.alle(DATA_ROOT)
                        if (deelnemer is None or o.info.deelnemer_id == deelnemer)
                        and zoek in f"{o.info.id} {o.info.experiment} {o.info.notities}".lower()}
        rijen = []
        for o in self.opnames.values():
            i = o.info
            rijen.append([i.id, self.namen.get(i.deelnemer_id, i.deelnemer_id), i.gestart[:16].replace("T", " "),
                          i.elektroden, i.experiment, len(o.annotaties), "ja" if o.heeft_signalen else "—",
                          "" if i.klokcorrectie_s is None else f"{i.klokcorrectie_s:+.2f} s",
                          "afgesloten" if i.live_afgesloten else "open"])
        vul(self.tabel, rijen, list(self.opnames))
        self._laad_formulier()

    def _opname(self) -> Opname | None:
        map = gekozen(self.tabel)
        return Opname.laad(map) if map else None

    def _laad_formulier(self) -> None:
        o = self._opname()
        for k in self.knoppen:
            k.setEnabled(o is not None)
        if o is None:
            self.kop.setText("Kies een opname.")
            return
        self.kop.setText(f"<b>{opname_label(o, self.namen)}</b><br>{o.info.id} · bronbestanden: "
                         f"{', '.join(o.info.bronbestanden) or '—'}")
        self.velden.zet(o)
        self.knoppen[0].setEnabled(o.heeft_signalen)
        self.knoppen[2].setEnabled(not o.info.live_afgesloten)
        self.knoppen[3].setEnabled(o.heeft_signalen)

    def _opslaan(self) -> None:
        o = self._opname()
        if o is None:
            return
        for naam, waarde in self.velden.waarden().items():
            setattr(o.info, naam, waarde)
        o._opslaan()
        self.ververs()

    def _open(self, scherm: str) -> None:
        o = self._opname()
        if o is not None:
            self.openen.emit(scherm, str(o.map))

    def _map_openen(self) -> None:
        o = self._opname()
        if o is not None:
            o.map.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(o.map)))

    def _verwijder(self) -> None:
        o = self._opname()
        if o is None or not zeker(
            self, f"Opname {o.info.id} definitief verwijderen?\n\nDit wist de gegevens, {len(o.annotaties)} "
                  f"annotaties én de map met ruwe P-Cardio-bestanden, signalen en exports. Dit kan niet ongedaan.",
        ):
            return
        o.verwijder_opname()
        self.ververs()

    def _exporteer(self) -> None:
        o = self._opname()
        if o is not None:
            ExportDialoog(o, self).exec()


class ExportDialoog(QDialog):
    """Gecombineerde export: één rij per ECG-sample, met beweging en annotaties. Schrijft naar ``<opname>/export``."""

    def __init__(self, opname: Opname, ouder: QWidget) -> None:
        super().__init__(ouder)
        self.setWindowTitle(f"Export · {opname.info.id}")
        self.opname = opname
        self.periode = QComboBox()
        self.periode.addItem("Hele opname", None)
        for a in opname.chronologisch():
            if a.soort == "periode" and a.t_eind is not None:
                self.periode.addItem(f"{a.label} · {klok(opname.in_datatijd(a)[0])}", a.id)
        self.marge = QDoubleSpinBox()
        self.marge.setRange(0, 120)
        self.marge.setSuffix(" s")
        self.zes = QCheckBox("6 leads toevoegen (III, aVR, aVL, aVF)")
        self.zes.setChecked(True)
        vorm = QFormLayout(self)
        vorm.addRow(QLabel("Eén rij per ECG-sample, met acc, gyro en overige kanalen (dichtstbijzijnde sample) en de "
                           "annotaties omgerekend naar P-Cardio-tijd. Daarnaast een los annotatiebestand."))
        vorm.addRow("Bereik", self.periode)
        vorm.addRow("Marge rond periode", self.marge)
        vorm.addRow("", self.zes)
        knoppen = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        knoppen.button(QDialogButtonBox.StandardButton.Ok).setText("Maak export")
        knoppen.accepted.connect(lambda: self._maak())
        tips((self.periode, hulp.BEREIK), (self.marge, hulp.MARGE_EXPORT), (self.zes, hulp.ZES_LEADS_EXPORT))
        knoppen.rejected.connect(self.reject)
        vorm.addRow(knoppen)

    @bezig
    def _maak(self) -> None:
        o, t0, t1, naam = self.opname, None, None, "volledig"
        if self.periode.currentData() is not None:
            a = o.zoek(self.periode.currentData())
            start, eind = o.in_datatijd(a)
            marge = pd.Timedelta(seconds=self.marge.value())
            t0, t1 = start - marge, eind + marge
            naam = f"{a.id:03d}_{a.label}".replace(" ", "_").replace("/", "-")
        df = gecombineerd(o, o.laad_signalen(), t0, t1, met_zes_leads=self.zes.isChecked())
        map = o.map / "export"
        map.mkdir(exist_ok=True)
        df.to_csv(map / f"{o.info.id}_{naam}.csv", index=False)
        o.annotaties_df().assign(experiment=o.info.experiment).to_csv(map / f"{o.info.id}_annotaties.csv", index=False)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(map)))
        self.accept()
