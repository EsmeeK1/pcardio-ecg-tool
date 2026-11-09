"""Gedeeld door de schermen: kern importeren, huisstijl, kleine hulpjes en het formulier voor opnamegegevens."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLineEdit, QMessageBox, QPlainTextEdit, QWidget,
)

# kern/ staat (nog) in streamlit/; de desktop-app gebruikt dezelfde code en dezelfde data.
STREAMLIT_MAP = Path(__file__).resolve().parents[1] / "streamlit"
sys.path.append(str(STREAMLIT_MAP))  # achteraan: streamlit/app.py mag desktop/app.py niet verdringen

# Per computer: welke datamap (bijv. in OneDrive). Leeg = de standaardmap streamlit/data.
INSTELLINGEN = Path(os.environ.get("APPDATA") or Path.home()) / "ECG-tool" / "instellingen.json"


def lees_instellingen() -> dict:
    try:
        return json.loads(INSTELLINGEN.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def bewaar_instellingen(instellingen: dict) -> None:
    INSTELLINGEN.parent.mkdir(parents=True, exist_ok=True)
    INSTELLINGEN.write_text(json.dumps(instellingen, indent=2, ensure_ascii=False), encoding="utf-8")


# Gedeelde datamap: opnamemappen daar, de database als lokale werkkopie (zie kern.synchronisatie). Vóór het
# importeren van kern, want DATA_ROOT wordt bij het importeren bepaald. ECG_TOOL_DATA van buiten (tests) gaat voor.
GEDEELDE_MAP: Path | None = None
LOKALE_DB: Path | None = None
if lees_instellingen().get("datamap") and not os.environ.get("ECG_TOOL_DATA"):
    GEDEELDE_MAP = Path(lees_instellingen()["datamap"])
    sleutel = hashlib.sha1(str(GEDEELDE_MAP.resolve()).encode()).hexdigest()[:8]
    LOKALE_DB = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ECG-tool" / f"ecg-{sleutel}.db"
    os.environ["ECG_TOOL_DATA"], os.environ["ECG_TOOL_DB"] = str(GEDEELDE_MAP), str(LOKALE_DB)

import hulp  # noqa: E402
from kern.opslag import WEERGAVE_TZ, Opname  # noqa: E402

PRIMAIR, DONKER, ORANJE, TEKST, SUBTIEL = "#1E6F80", "#14525F", "#FF9806", "#1F2A30", "#4A6A72"
GRAFIEK = [PRIMAIR, ORANJE, "#6EC6DA", DONKER, "#9FDCEB", "#8A4B00"]
PALET = GRAFIEK + ["#3DBDDC", "#39ADC6", "#399FB4"]
STANDAARD_CONFIGURATIE = (
    "ECG 2-kanaals 250 Hz gain x6; Acc 100 Hz x2; Gyro 100 Hz x2; Lead-off 5 Hz; Button Marker 5 Hz; Battery 5 Hz"
)
ELEKTRODE_PLAATSINGEN = ["Optie 1: met sticker", "Optie 2: met lanyard"]
# P-Cardio-instructie voor de deelnemer (staand) + handleiding van de app (liggend); gemaakt met maak_pdf.py
HANDLEIDING = Path(__file__).resolve().parent / "handleiding" / "Handleiding ECG-tool.pdf"

# Geen anti-aliasing en lijndikte 1: bij honderdduizenden punten is dat tientallen keren sneller (gemeten: 18 van 22 s
# ging naar het tekenen). Live (weinig punten) zet het per lijn wel aan.
pg.setConfigOptions(antialias=False, background="w", foreground=TEKST)


def klok(tijd: pd.Timestamp, tienden: bool = False) -> str:
    tekst = pd.Timestamp(tijd).tz_convert(WEERGAVE_TZ).strftime("%H:%M:%S.%f" if tienden else "%H:%M:%S")
    return tekst[:-5] if tienden else tekst


def epoch(tijd: pd.Timestamp | pd.Series):
    """Tijd(en) als seconden sinds 1970 (UTC): de x-as van alle plots (``pg.DateAxisItem`` toont lokale tijd)."""
    if isinstance(tijd, pd.Series):
        return (tijd - _NUL).dt.total_seconds().to_numpy()
    return pd.Timestamp(tijd).timestamp()


_NUL = pd.Timestamp("1970-01-01", tz="UTC")


def opname_label(opname: Opname, namen: dict[str, str]) -> str:
    gestart = pd.Timestamp(opname.info.gestart).strftime("%d-%m-%Y %H:%M")
    extra = f" · {opname.info.experiment}" if opname.info.experiment else ""
    return f"{gestart} · {namen.get(opname.info.deelnemer_id, opname.info.deelnemer_id)}{extra}"


def tips(*paren: tuple[QWidget, str]) -> None:
    """Tooltips uit de helpteksten (``hulp.py``, gedeeld met de Streamlit-app); Markdown wordt eenvoudige opmaak."""
    for widget, tekst in paren:
        html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", tekst)
        html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html)
        widget.setToolTip("<qt>" + re.sub(r"`(.+?)`", r"<code>\1</code>", html) + "</qt>")


def fout(ouder: QWidget, tekst: str) -> None:
    QMessageBox.warning(ouder, "Let op", tekst)


def zeker(ouder: QWidget, vraag: str) -> bool:
    return QMessageBox.question(ouder, "Bevestigen", vraag) == QMessageBox.StandardButton.Yes


def bezig(functie):
    """Wachtcursor tijdens langzaam werk (inlezen, exporteren). Koppel aan een signaal via een lambda: een signaal
    geeft soms een argument mee (index, checked) dat de functie niet verwacht."""
    @functools.wraps(functie)
    def omhulsel(*args, **kwargs):
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return functie(*args, **kwargs)
        finally:
            QGuiApplication.restoreOverrideCursor()
    return omhulsel


class OpnameVelden(QWidget):
    """Gegevens van een opname, voor een nieuwe opname (live of bij koppelen) en voor bewerken."""

    def __init__(self, apparaat: str = "deze pc") -> None:
        super().__init__()
        vorm = QFormLayout(self)
        vorm.setContentsMargins(0, 0, 0, 0)
        self.elektroden = QComboBox()
        self.elektroden.addItems(ELEKTRODE_PLAATSINGEN)
        self.huid = QLineEdit()
        self.configuratie = QLineEdit(STANDAARD_CONFIGURATIE)
        self.gelijkgezet = QCheckBox(f"Tijd van de P-Cardio is vlak voor de opname gelijkgezet met {apparaat}")
        self.experiment = QLineEdit()
        self.experiment.setPlaceholderText("bijv. Elektrodeplaatsing 21-10")
        self.notities = QPlainTextEdit()
        self.notities.setMaximumHeight(70)
        vorm.addRow("Plaatsing elektroden", self.elektroden)
        vorm.addRow("Huidvoorbereiding", self.huid)
        vorm.addRow("Meetconfiguratie", self.configuratie)
        vorm.addRow("", self.gelijkgezet)
        vorm.addRow("Experiment", self.experiment)
        vorm.addRow("Notities", self.notities)
        tips((self.elektroden, hulp.ELEKTRODEN), (self.huid, hulp.HUIDVOORBEREIDING), (self.configuratie, hulp.CONFIGURATIE),
             (self.gelijkgezet, hulp.GELIJKGEZET), (self.experiment, hulp.EXPERIMENT), (self.notities, hulp.NOTITIES))

    def waarden(self) -> dict[str, object]:
        return {
            "elektroden": self.elektroden.currentText(),
            "huidvoorbereiding": self.huid.text().strip(),
            "configuratie": self.configuratie.text().strip(),
            "pcardio_tijd_gelijkgezet": self.gelijkgezet.isChecked(),
            "notities": self.notities.toPlainText().strip(),
            "experiment": self.experiment.text().strip(),
        }

    def zet(self, opname: Opname) -> None:
        i = opname.info
        if i.elektroden and self.elektroden.findText(i.elektroden) < 0:
            self.elektroden.addItem(i.elektroden)
        self.elektroden.setCurrentText(i.elektroden or ELEKTRODE_PLAATSINGEN[1])
        self.huid.setText(i.huidvoorbereiding)
        self.configuratie.setText(i.configuratie)
        self.gelijkgezet.setChecked(i.pcardio_tijd_gelijkgezet)
        self.experiment.setText(i.experiment)
        self.notities.setPlainText(i.notities)
