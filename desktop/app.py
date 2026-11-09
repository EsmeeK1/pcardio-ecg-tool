"""ECG-tool P-Cardio als desktop-app (PySide6 + pyqtgraph). Zelfde kern en dezelfde data als de Streamlit-app.

Starten vanuit de projectroot:
    .venv\\Scripts\\python desktop\\app.py
of dubbelklik op ``ECG-tool.cmd``.
"""

from __future__ import annotations

import shutil
import sys
import traceback
from pathlib import Path

import pandas  # noqa: F401 - vóór PySide6 laden: anders struikelt shiboken 6.12 over `six` (via dateutil)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout,
    QWidget,
)

from gedeeld import GEDEELDE_MAP, HANDLEIDING, LOKALE_DB, PRIMAIR, bewaar_instellingen, bezig, \
    lees_instellingen, zeker  # zet ook kern/ op het pad
from analyse import BekijkenScherm, KoppelenScherm
from beheer import DeelnemersScherm, OpnamesScherm
from kern import synchronisatie
from kern.opslag import DATA_ROOT, GESCHIEDENIS, db_pad, leeg_prullenbak
from live import LiveScherm

LOGO = Path(__file__).resolve().parent / "assets" / "logo.png"
PUBLICEER_MS = 10 * 60 * 1000  # gedeelde datamap: elke 10 minuten de werkkopie naar OneDrive
STIJL = f"""
QListWidget {{ background: #F2FAFC; border: none; font-size: 11pt; padding-top: 8px; }}
QListWidget::item {{ padding: 10px 14px; }}
QListWidget::item:selected {{ background: {PRIMAIR}; color: white; }}
QGroupBox {{ font-weight: bold; color: {PRIMAIR}; }}
QPushButton:checked {{ background: #FF9806; color: white; font-weight: bold; }}
QTableView {{ selection-background-color: #CDEBF3; selection-color: #1F2A30; }}
QTableView::item:selected {{ background: #CDEBF3; color: #1F2A30; border-top: 1px solid #6EC6DA;
    border-bottom: 1px solid #6EC6DA; }}
QTableView::item:selected:!active {{ background: #CDEBF3; color: #1F2A30; }}
QTableView::item:hover {{ background: #EEF8FB; }}
"""


class Hoofdvenster(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ECG-tool P-Cardio · {'gedeeld: ' if GEDEELDE_MAP else ''}{DATA_ROOT}")
        self.setWindowIcon(QIcon(str(LOGO)))
        self.deelnemers, self.opnames, self.live = DeelnemersScherm(), OpnamesScherm(), LiveScherm()
        self.koppelen, self.bekijken = KoppelenScherm(), BekijkenScherm()
        self.schermen = {"Deelnemers": self.deelnemers, "Opnames": self.opnames, "Live": self.live,
                         "Data koppelen": self.koppelen, "Bekijken & annoteren": self.bekijken}
        self.menu, self.stapel = QListWidget(), QStackedWidget()
        self.menu.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for naam, scherm in self.schermen.items():
            self.menu.addItem(naam)
            self.stapel.addWidget(scherm)
        self.extra = {"Handleiding (pdf)": lambda: self._open_pdf(HANDLEIDING),
                      "Datamap…": self._kies_datamap}
        for naam in self.extra:
            self.menu.addItem(naam)
        self.menu.currentRowChanged.connect(self._kies)

        self.deelnemers.gewijzigd.connect(self.opnames.ververs_deelnemers)
        self.opnames.openen.connect(self._open)
        midden = QWidget()
        rij = QHBoxLayout(midden)
        rij.setContentsMargins(0, 0, 0, 0)
        links = QWidget()
        links.setFixedWidth(200)
        links.setStyleSheet("background: #F2FAFC;")
        kolom = QVBoxLayout(links)
        kolom.setContentsMargins(0, 14, 0, 0)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(LOGO)).scaledToWidth(72, Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        kolom.addWidget(logo)
        kolom.addWidget(self.menu, 1)
        rij.addWidget(links)
        rij.addWidget(self.stapel, 1)
        self.setCentralWidget(midden)
        self.menu.setCurrentRow(1)
        # Ongedaan maken / opnieuw doen voor de hele app. In een tekstveld wint het veld (tekst ongedaan maken).
        for toets, actie in (("Ctrl+Z", self.ongedaan), ("Ctrl+Shift+Z", self.opnieuw)):
            QShortcut(QKeySequence(toets), self, actie)
        self.statusBar().showMessage("Ctrl+Z: ongedaan maken · Ctrl+Shift+Z: opnieuw doen", 8000)
        if GEDEELDE_MAP:  # tussendoor naar OneDrive, zodat een crash hooguit een paar minuten werk kost
            self._publiceer_timer = QTimer(self)
            self._publiceer_timer.timeout.connect(lambda: self._publiceer(vrijgeven=False))
            self._publiceer_timer.start(PUBLICEER_MS)

    def _publiceer(self, vrijgeven: bool) -> None:
        try:
            synchronisatie.publiceer(GEDEELDE_MAP, LOKALE_DB, vrijgeven)
        except OSError as e:  # OneDrive even niet bereikbaar: volgende keer opnieuw, de werkkopie is veilig
            self.statusBar().showMessage(f"Opslaan naar de gedeelde map lukte niet: {e}", 10000)

    def ongedaan(self) -> None:
        label = GESCHIEDENIS.ongedaan()
        self._na_geschiedenis(f"Ongedaan gemaakt: {label}" if label else "Niets om ongedaan te maken.")

    def opnieuw(self) -> None:
        label = GESCHIEDENIS.opnieuw()
        self._na_geschiedenis(f"Opnieuw gedaan: {label}" if label else "Niets om opnieuw te doen.")

    def _na_geschiedenis(self, melding: str) -> None:
        """Alle schermen bijwerken: de gegevens zijn teruggezet."""
        self.deelnemers.ververs()
        self.opnames.ververs_deelnemers()
        self.koppelen.ververs()
        self.live.na_wijziging()
        self.bekijken.na_wijziging()
        self.statusBar().showMessage(melding, 6000)

    def _kies(self, rij: int) -> None:
        if rij >= len(self.schermen):  # handleiding, instructie of datamap: geen scherm
            list(self.extra.values())[rij - len(self.schermen)]()
            self.menu.blockSignals(True)
            self.menu.setCurrentRow(self.stapel.currentIndex())
            self.menu.blockSignals(False)
            return
        scherm = self.stapel.widget(rij)
        # Gegevens kunnen op een ander scherm veranderd zijn (bijv. een nieuwe opname of koppeling).
        for naam in ("ververs_deelnemers", "ververs"):
            if hasattr(scherm, naam) and scherm is not self.live:
                getattr(scherm, naam)()
                break
        self.stapel.setCurrentIndex(rij)

    def _open(self, scherm: str, map: str) -> None:
        doel = {"bekijken": self.bekijken, "koppelen": self.koppelen, "live": self.live}[scherm]
        doel.open_opname(map)
        self.menu.blockSignals(True)
        self.menu.setCurrentRow(list(self.schermen.values()).index(doel))
        self.menu.blockSignals(False)
        self.stapel.setCurrentWidget(doel)

    def _open_pdf(self, pad: Path) -> None:
        if not pad.exists():
            QMessageBox.warning(self, "Handleiding", f"{pad.name} niet gevonden in {pad.parent}.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pad)))

    def _kies_datamap(self) -> None:
        """Datamap voor deze computer kiezen (bijv. in OneDrive); geldt na opnieuw starten."""
        vraag = QMessageBox(self)
        vraag.setWindowTitle("Datamap")
        vraag.setText(f"Nu: {DATA_ROOT}" + (" (gedeeld)" if GEDEELDE_MAP else " (alleen op deze computer)")
                      + "\n\nKies een map in OneDrive om dezelfde data op meerdere computers te gebruiken, "
                        "één computer tegelijk.")
        kiezen = vraag.addButton("Map kiezen…", QMessageBox.ButtonRole.AcceptRole)
        standaard = vraag.addButton("Terug naar de standaardmap", QMessageBox.ButtonRole.DestructiveRole)
        vraag.addButton("Annuleren", QMessageBox.ButtonRole.RejectRole)
        vraag.exec()
        if vraag.clickedButton() is standaard:
            bewaar_instellingen({k: v for k, v in lees_instellingen().items() if k != "datamap"})
        elif vraag.clickedButton() is kiezen:
            gekozen = QFileDialog.getExistingDirectory(self, "Datamap kiezen (bijv. in OneDrive)")
            if not gekozen:
                return
            nieuw = Path(gekozen)
            leeg = not ((nieuw / synchronisatie.DATABASE).exists() or (nieuw / "opnames").exists())
            if leeg and zeker(self, f"{nieuw} is nog leeg. De huidige data (database en opnames) daarheen kopiëren?"
                                    "\n\nDat kan even duren; het origineel blijft staan."):
                self._kopieer_data(nieuw)
            bewaar_instellingen({**lees_instellingen(), "datamap": str(nieuw)})
        else:
            return
        QMessageBox.information(self, "Datamap", "Sluit de app en start hem opnieuw om de nieuwe datamap te gebruiken.")

    @bezig
    def _kopieer_data(self, doel: Path) -> None:
        doel.mkdir(parents=True, exist_ok=True)
        if db_pad(DATA_ROOT).exists():
            synchronisatie._kopieer(db_pad(DATA_ROOT), doel / synchronisatie.DATABASE)
        if (DATA_ROOT / "opnames").exists():
            shutil.copytree(DATA_ROOT / "opnames", doel / "opnames", dirs_exist_ok=True)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt-naam
        self.live.sluit()  # stream stoppen en de COM-poort vrijgeven
        if GEDEELDE_MAP:
            self._publiceer(vrijgeven=True)  # andere computer kan verder zodra OneDrive dit binnen heeft
        super().closeEvent(event)


def _toon_fout(soort, fout, tb) -> None:
    """Zonder consolevenster (pythonw via ECG-tool.cmd) zie je een fout anders nooit."""
    tekst = "".join(traceback.format_exception(soort, fout, tb))
    sys.__stderr__ and sys.__stderr__.write(tekst)
    QMessageBox.critical(None, "Fout in de ECG-tool", tekst[-3000:])


def _open_gedeeld() -> bool:
    """Gedeelde datamap: wachten tot hij vrij en gesynchroniseerd is, dan de werkkopie klaarzetten."""
    while (status := synchronisatie.controleer(GEDEELDE_MAP)).soort != "ok":
        vraag = QMessageBox()
        vraag.setWindowTitle("Gedeelde data")
        if status.soort == "in_gebruik":
            vraag.setText(f"De data is in gebruik op {status.computer} (sinds {status.sinds[11:16]}).\n\nSluit de app "
                          "daar eerst af. Overnemen kan, maar wat daar nog niet naar OneDrive is gezet, gaat verloren.")
            door = vraag.addButton("Overnemen", QMessageBox.ButtonRole.DestructiveRole)
        else:
            vraag.setText(f"OneDrive heeft de laatste versie van {status.computer} nog niet binnen. Wacht even en "
                          "probeer opnieuw.")
            door = vraag.addButton("Toch openen (oudere versie)", QMessageBox.ButtonRole.DestructiveRole)
        opnieuw = vraag.addButton("Opnieuw proberen", QMessageBox.ButtonRole.AcceptRole)
        vraag.addButton("Afsluiten", QMessageBox.ButtonRole.RejectRole)
        vraag.setDefaultButton(opnieuw)
        vraag.exec()
        if vraag.clickedButton() is door:
            break
        if vraag.clickedButton() is not opnieuw:
            return False
    synchronisatie.open_gedeeld(GEDEELDE_MAP, LOKALE_DB)
    return True


def main() -> None:
    sys.excepthook = _toon_fout
    app = QApplication(sys.argv)
    app.setApplicationName("ECG-tool P-Cardio")
    app.setStyleSheet(STIJL)
    if GEDEELDE_MAP and not _open_gedeeld():
        return
    leeg_prullenbak(DATA_ROOT)  # verwijderde opnames van een vorige sessie: de geschiedenis is ook weg
    venster = Hoofdvenster()
    venster.resize(1500, 950)
    venster.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
