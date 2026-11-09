"""Live: verbinden met de P-Cardio via de dongle, ECG/acc/gyro live zien, en perioden, momenten en sync-sprongen
loggen met de pc-klok. Elke klik wordt direct (met tijdstempel van het klikmoment) in de database gezet."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from beheer import tabel
from gedeeld import DONKER, GRAFIEK, ORANJE, PRIMAIR, SUBTIEL, TEKST, OpnameVelden, fout, hulp, klok, opname_label, tips, zeker
from kern import pcardio_protocol as p
from kern.beweging import (
    HOUDING_LIVE_S, HOUDING_STAP_S, LIVE_STAP_S, OMGEKEERD_GRADEN, SEGMENT_S, beweging_nu, houding_nu,
)
from kern.dongle import SerieleDongle, SimDongle, poorten, zoek_dongle
from kern.lijsten import lees_lijst
from kern.live_sessie import GEEN_DATA_S, LiveSessie
from kern.opslag import DATA_ROOT, Deelnemers, Opname, nu
from kern.verwerking import ecg_filter, netbrom_filter

TOESTANDEN = {"los": "niet verbonden", "verbinden": "verbinden…", "verbonden": "verbonden", "streamen": "streamt",
              "bezig": "bezig…"}
PLOT_MS, STATUS_MS = 40, 500  # ± 25 beelden per seconde; status twee keer per seconde
POORTEN_MS = 2000  # niet verbonden: zo vaak kijken of er een USB-poort bij of af is
INFO_S = 5  # verbonden maar niet streamend: status van de recorder zo vaak opnieuw uitlezen
LOG_KOLOMMEN = ["soort", "label", "start", "eind", "duur (s)", "plaatsing", "opmerking"]
BEWERKBAAR = {1: "label", 5: "plaatsing", 6: "opmerking"}


class LiveScherm(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.sessie: LiveSessie | None = None
        self.map: str | None = None  # de opname waarin gelogd wordt
        self._beweging: tuple[float, str, pd.Series] | None = None  # activiteit: (tijd, bevestiging, uitkomst)
        self._houding: tuple[float, str, str, float] | None = None  # (tijd, bevestiging, houding, kanteling)

        links = QWidget()
        kolom = QVBoxLayout(links)
        kolom.addWidget(self._recorder_groep())
        kolom.addWidget(self._opname_groep())
        kolom.addWidget(self._perioden_groep())
        kolom.addWidget(self._momenten_groep())
        kolom.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(links)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(470)

        rechts = QWidget()
        r = QVBoxLayout(rechts)
        r.addLayout(self._weergave_balk())
        self.waarschuwing = QLabel()  # balk boven de plots; verborgen als alles goed is
        self.waarschuwing.setWordWrap(True)
        self.waarschuwing.hide()
        r.addWidget(self.waarschuwing)
        plots = self._plots()
        r.addWidget(plots, 3)
        self.badges = Badges(plots)  # houding en activiteit rechtsboven over de plots
        r.addWidget(QLabel("<b>Logboek</b> · dubbelklik op label, plaatsing of opmerking om te wijzigen"))
        self.log = tabel(LOG_KOLOMMEN)
        self.log.setSortingEnabled(False)
        self.log.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.log.itemChanged.connect(self._log_gewijzigd)
        r.addWidget(self.log, 2)
        weg = QPushButton("Verwijder geselecteerde regel")
        weg.clicked.connect(self._verwijder_regel)
        r.addWidget(weg)

        splitter = QSplitter()
        splitter.addWidget(scroll)
        splitter.addWidget(rechts)
        splitter.setSizes([480, 900])
        QVBoxLayout(self).addWidget(splitter)

        for interval, functie in ((PLOT_MS, self._teken), (STATUS_MS, self._status)):
            timer = QTimer(self)
            timer.timeout.connect(functie)
            timer.start(interval)
        poorten_timer = QTimer(self)
        poorten_timer.timeout.connect(self._volg_poorten)
        poorten_timer.start(POORTEN_MS)
        self._toon_opname()

    # --- opbouw ---

    def _recorder_groep(self) -> QGroupBox:
        groep = QGroupBox("Recorder")
        vorm = QFormLayout(groep)
        self.modus = QComboBox()
        self.modus.addItems(["Echte dongle", "Gesimuleerd"])
        self.poort = QComboBox()
        self._poorten: list[tuple[str, str]] = []
        ververs = QPushButton("↻")
        ververs.setFixedWidth(30)
        ververs.clicked.connect(self._ververs_poorten)
        rij = QHBoxLayout()
        rij.addWidget(self.poort, 1)
        rij.addWidget(ververs)
        self.mac = QLineEdit()
        self.mac.setPlaceholderText("optioneel, bijv. D7:3F:…")
        self.mac_omgekeerd = QCheckBox("MAC-bytes omgekeerd")
        self.auto = QCheckBox("Automatisch opnieuw verbinden")
        self.auto.setChecked(True)
        vorm.addRow("Dongle", self.modus)
        vorm.addRow("Poort", rij)
        vorm.addRow("MAC recorder", self.mac)
        vorm.addRow("", self.mac_omgekeerd)
        vorm.addRow("", self.auto)
        knoppen = QGridLayout()
        self.k_verbind, self.k_start, self.k_stop, self.k_los = (
            QPushButton(t) for t in ("Verbinden", "Start", "Stop", "Ontkoppelen"))
        for i, (k, actie) in enumerate([(self.k_verbind, self._verbind), (self.k_start, self._start),
                                        (self.k_stop, self._stop), (self.k_los, self._ontkoppel)]):
            k.clicked.connect(actie)
            knoppen.addWidget(k, 0, i)
        vorm.addRow(knoppen)
        self.status = QLabel("Niet verbonden.")
        self.status.setWordWrap(True)
        vorm.addRow(self.status)
        self.k_config = QPushButton("ECG-configuratie schrijven…")
        self.k_config.clicked.connect(self._schrijf_config)
        vorm.addRow(self.k_config)
        self._ververs_poorten()
        tips((self.modus, hulp.LIVE_MODUS), (self.poort, hulp.LIVE_POORT), (self.mac, hulp.LIVE_MAC),
             (self.mac_omgekeerd, hulp.LIVE_MAC_OMGEKEERD), (self.auto, hulp.LIVE_AUTO), (self.k_verbind, hulp.LIVE_VERBINDEN),
             (self.k_start, hulp.LIVE_START), (self.k_los, hulp.LIVE_ONTKOPPELEN), (self.k_config, hulp.LIVE_CONFIG),
             (self.status, hulp.LIVE_TELLERS))
        return groep

    def _opname_groep(self) -> QGroupBox:
        groep = QGroupBox("Opname")
        v = QVBoxLayout(groep)
        self.opname_tekst = QLabel()
        self.opname_tekst.setWordWrap(True)
        v.addWidget(self.opname_tekst)
        rij = QHBoxLayout()
        for tekst, actie in (("Nieuwe opname…", self._nieuwe_opname), ("Hervatten…", self._hervat)):
            k = QPushButton(tekst)
            k.clicked.connect(actie)
            rij.addWidget(k)
        v.addLayout(rij)
        vorm = QFormLayout()
        self.experiment, self.plaatsing = QLineEdit(), QLineEdit()
        self.experiment.editingFinished.connect(lambda: self._actie(lambda o: o.zet_experiment(self.experiment.text())))
        self.plaatsing.setPlaceholderText("bijv. R3-Y3-G1-Z1 (blijft staan)")
        vorm.addRow("Experiment", self.experiment)
        vorm.addRow("Plaatsing", self.plaatsing)
        v.addLayout(vorm)
        self.k_sync = QPushButton("Sync-sprong")
        self.k_sync.setStyleSheet(f"background:{PRIMAIR}; color:white; font-weight:bold; padding:8px;")
        self.k_sync.clicked.connect(lambda: self._actie(lambda o: o.sync()))
        rij = QHBoxLayout()
        self.k_stop_periode, self.k_afsluiten = QPushButton("Stop periode"), QPushButton("Opname afsluiten…")
        self.k_stop_periode.clicked.connect(lambda: self._actie(lambda o: o.stop_periode()))
        self.k_afsluiten.clicked.connect(self._afsluiten)
        rij.addWidget(self.k_stop_periode)
        rij.addWidget(self.k_afsluiten)
        v.addWidget(self.k_sync)
        v.addLayout(rij)
        self.actief = QLabel()
        v.addWidget(self.actief)
        tips((self.experiment, hulp.EXPERIMENT), (self.plaatsing, hulp.PLAATSING), (self.k_sync, hulp.SYNC),
             (self.k_stop_periode, hulp.STOP_PERIODE), (self.k_afsluiten, hulp.AFSLUITEN))
        return groep

    def _knoppenraster(self, labels: list[str], actie, per_rij: int = 2) -> tuple[QGridLayout, dict[str, QPushButton]]:
        raster, knoppen = QGridLayout(), {}
        for i, label in enumerate(labels):
            k = QPushButton(label)
            k.setCheckable(True)  # alleen om de lopende periode te markeren
            k.clicked.connect(lambda _=False, l=label: actie(l))
            raster.addWidget(k, i // per_rij, i % per_rij)
            knoppen[label] = k
        return raster, knoppen

    def _perioden_groep(self) -> QGroupBox:
        groep = QGroupBox("Perioden (klik = start; de lopende stopt dan)")
        v = QVBoxLayout(groep)
        raster, self.periode_knoppen = self._knoppenraster(lees_lijst("activiteiten"), self._start_periode)
        v.addLayout(raster)
        rij = QHBoxLayout()
        self.vrije_periode = QLineEdit()
        self.vrije_periode.setPlaceholderText("Andere activiteit…")
        self.vrije_periode.returnPressed.connect(self._start_vrije_periode)
        k = QPushButton("Start")
        k.clicked.connect(self._start_vrije_periode)
        rij.addWidget(self.vrije_periode, 1)
        rij.addWidget(k)
        v.addLayout(rij)
        return groep

    def _momenten_groep(self) -> QGroupBox:
        groep = QGroupBox("Momenten")
        v = QVBoxLayout(groep)
        raster, knoppen = self._knoppenraster(
            ["Markeer nu", *lees_lijst("momenten")],
            lambda l: self._actie(lambda o: o.moment("markering" if l == "Markeer nu" else l)),
        )
        for k in knoppen.values():
            k.setCheckable(False)
        v.addLayout(raster)
        rij = QHBoxLayout()
        self.vrij_moment = QLineEdit()
        self.vrij_moment.setPlaceholderText("Ander moment…")
        self.vrij_moment.returnPressed.connect(self._vrij_moment)
        k = QPushButton("Markeer")
        k.clicked.connect(self._vrij_moment)
        rij.addWidget(self.vrij_moment, 1)
        rij.addWidget(k)
        v.addLayout(rij)
        return groep

    def _weergave_balk(self) -> QHBoxLayout:
        rij = QHBoxLayout()
        self.venster = QComboBox()
        self.venster.addItems(["5 s", "10 s", "20 s"])
        self.venster.setCurrentIndex(1)
        self.filter, self.netbrom = QCheckBox("Filter 0,5–40 Hz"), QCheckBox("50 Hz-notch")
        self.filter.setChecked(True)
        self.y_vast = QDoubleSpinBox()
        self.y_vast.setRange(0, 500)
        self.y_vast.setSpecialValueText("auto")
        self.y_vast.setPrefix("± ")
        self.y_vast.setSuffix(" mV")
        self.toon_acc, self.toon_gyro = QCheckBox("Accelerometer"), QCheckBox("Gyroscoop")
        self.toon_acc.toggled.connect(lambda aan: self.plot_acc.setVisible(aan))
        self.toon_gyro.toggled.connect(lambda aan: self.plot_gyro.setVisible(aan))
        self.bevestiging = QComboBox()
        self.bevestiging.addItems(["sticker", "lanyard"])
        for w in (QLabel("Venster"), self.venster, self.filter, self.netbrom, QLabel("Y"), self.y_vast,
                  self.toon_acc, self.toon_gyro, QLabel("Bevestiging"), self.bevestiging):
            rij.addWidget(w)
        rij.addStretch()
        tips((self.venster, hulp.LIVE_VENSTER), (self.filter, hulp.LIVE_FILTER), (self.netbrom, hulp.LIVE_NETBROM),
             (self.y_vast, hulp.LIVE_YSCHAAL), (self.toon_acc, hulp.ACC), (self.toon_gyro, hulp.GYRO),
             (self.bevestiging, hulp.BEVESTIGING))
        return rij

    def _plots(self) -> pg.GraphicsLayoutWidget:
        w = pg.GraphicsLayoutWidget()
        self.plot_ecg = w.addPlot(row=0, col=0)
        self.plot_ecg.setLabel("left", "ECG", "mV")
        self.plot_ecg.addLegend(offset=(10, 5))
        self.lijnen_ecg = [self.plot_ecg.plot(pen=pg.mkPen(GRAFIEK[i], width=1.3), name=n, antialias=True)
                           for i, n in enumerate(("Ecg1 (I)", "Ecg2 (II)"))]
        self.plot_acc = w.addPlot(row=1, col=0)
        self.plot_gyro = w.addPlot(row=2, col=0)
        self.lijnen_beweging = {}
        for plot, naam, eenheid in ((self.plot_acc, "acc", "g"), (self.plot_gyro, "gyro", "°/s")):
            plot.setLabel("left", naam, eenheid)
            plot.setXLink(self.plot_ecg)
            plot.hide()
            self.lijnen_beweging[naam] = [plot.plot(pen=pg.mkPen(c, width=1)) for c in GRAFIEK[:3]] + [
                plot.plot(pen=pg.mkPen(TEKST, width=1.3), antialias=True)]
        self.plot_gyro.setLabel("bottom", "tijd t.o.v. nu", "s")
        for plot in (self.plot_ecg, self.plot_acc, self.plot_gyro):
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setMouseEnabled(x=False, y=True)
        return w

    # --- recorder ---

    def _ververs_poorten(self) -> None:
        """Poortenlijst opnieuw. Een gevonden dongle wordt gekozen; anders blijft de keuze staan als die er nog is."""
        lijst = poorten()
        self._poorten = lijst
        huidig = self.poort.currentData()
        self.poort.clear()
        for poort, tekst in lijst:
            self.poort.addItem(tekst, poort)
        i = self.poort.findData(zoek_dongle() or huidig)
        if i >= 0:
            self.poort.setCurrentIndex(i)

    def _volg_poorten(self) -> None:
        """Niet verbonden: elke paar seconden kijken of er een poort bij of af is (dongle in een andere USB-poort
        gestoken krijgt van Windows een ander COM-nummer). Zonder dit bleef de poort van het opstarten staan."""
        if self.sessie is None and poorten() != self._poorten:
            self._ververs_poorten()

    def _verbind(self) -> None:
        if self.sessie is not None and self.sessie.verbroken:
            self.sessie.herverbind()
            return
        if self.sessie is None:
            try:
                if self.modus.currentText() == "Gesimuleerd":
                    dongle = SimDongle()
                elif self.poort.currentData():
                    if self.poort.currentData() not in dict(poorten()):  # dongle intussen verplaatst
                        self._ververs_poorten()
                    dongle = SerieleDongle(self.poort.currentData())
                else:
                    fout(self, "Geen COM-poort gekozen. Zit de dongle in een USB-poort? Klik dan op ↻.")
                    return
            except ConnectionError as e:
                fout(self, str(e))
                return
            self.sessie = LiveSessie(dongle)
        self.sessie.op_achtergrond(self.sessie.verbind, mac=self.mac.text().strip() or None,
                                   mac_omgekeerd=self.mac_omgekeerd.isChecked())

    def _start(self) -> None:
        if self.sessie:
            self._beweging = self._houding = None
            if not self.sessie.op_achtergrond(self.sessie.start):  # net bezig met de status uitlezen: zo opnieuw
                QTimer.singleShot(300, self._start)

    def _stop(self) -> None:
        if self.sessie:
            self.sessie.op_achtergrond(self.sessie.stop)

    def _ontkoppel(self) -> None:
        sessie, self.sessie = self.sessie, None
        if sessie is not None:
            sessie.sluit()  # ± 1 s, zodat de poort echt vrij is

    def _schrijf_config(self) -> None:
        if self.sessie and zeker(self, f"Schrijft naar de recorder: {p.config_tekst(p.STANDAARD_CONFIG)}.\n\n"
                                       "De recorder gebruikt deze configuratie daarna ook als hij zelf logt."):
            self.sessie.op_achtergrond(self.sessie.schrijf_config, p.STANDAARD_CONFIG, bevestigd=True)

    def sluit(self) -> None:
        self._ontkoppel()

    # --- status (2× per seconde) ---

    def _status(self) -> None:
        s = self.sessie
        toestand = s.toestand if s else "los"
        bezig = s is not None and s.bezig
        verbroken = s is not None and s.verbroken
        for w in (self.modus, self.poort, self.mac, self.mac_omgekeerd):
            w.setEnabled(s is None)
        self.k_verbind.setText("Opnieuw verbinden" if verbroken else "Verbinden")
        self.k_verbind.setEnabled(toestand == "los" and not bezig)
        self.k_start.setEnabled(toestand == "verbonden" and not bezig and s.ecg is not None)
        self.k_stop.setEnabled(toestand == "streamen" and not bezig)
        self.k_los.setEnabled(s is not None)
        self.k_config.setVisible(toestand == "verbonden" and s.ecg is None and not bezig)
        streamt = s is not None and toestand == "streamen"
        self.plot_ecg.setTitle(None if streamt else "Klik op Start om het ECG te zien" if toestand == "verbonden"
                               else "Verbind met de recorder en klik daarna op Start")
        if toestand == "verbonden" and not bezig and time.time() - (s.info_gelezen or 0) > INFO_S:
            s.ververs_info()
        if s is None:
            self.status.setText("Niet verbonden.")
            self._balk([], [])
            self.badges.hide()
        else:
            s.automatisch_herverbinden = self.auto.isChecked()
            info, t = s.info, s.tellers
            batterij = s.batterij if s.batterij is not None else (info.batterij if info else None)
            naam = ("opnieuw verbinden…" if s.herverbindt else "verbinding kwijt" if verbroken
                    else TOESTANDEN.get(toestand, toestand))
            logt = {True: "neemt op", False: "<span style='color:#B00020'><b>neemt NIET op</b></span>"}.get(s.logt, "–")
            moment = ("" if streamt or s.info_gelezen is None
                      else f" <span style='color:#4A6A72'>(uitgelezen {time.strftime('%H:%M:%S', time.localtime(s.info_gelezen))})</span>")
            regels = [f"<b>{naam}</b> · batterij {batterij if batterij is not None else '–'} % · recorder {logt}{moment}"]
            if info:
                regels.append(f"firmware {info.firmware} · {info.hw_tekst} · {p.config_tekst(s.configs) or 'leeg'}")
            regels.append(f"{t['pakketten']} pakketten · {t['crc_fout']} CRC · {t['onvolledig']} onvolledig · "
                          f"{t['tijdgaten']} gaten")
            if s.dongle.fout:
                regels.append(f"<span style='color:#B00020'>{s.dongle.fout} Klik op Ontkoppelen.</span>")
            if s.melding:
                kleur = {"error": "#B00020", "warning": "#8A4B00"}.get(s.melding[0], PRIMAIR)
                regels.append(f"<span style='color:{kleur}'>{s.melding[1]}</span>")
            self.status.setText("<br>".join(regels))
            self._toon_beweging(s)  # eerst: de waarschuwingen gebruiken de houding
            self._waarschuwingen(s)
        self._toon_actief()

    def _balk(self, fouten: list[str], waarschuwingen: list[str]) -> None:
        """Rood bij een probleem met de verbinding, amber bij een probleem met het signaal; weg als alles goed is."""
        if not (fouten or waarschuwingen):
            self.waarschuwing.hide()
            return
        rand, achtergrond = ("#C62828", "#FDECEA") if fouten else ("#FF9806", "#FFF4E5")
        self.waarschuwing.setStyleSheet(f"background:{achtergrond}; border-left:5px solid {rand}; border-radius:4px; "
                                        f"padding:8px 12px; color:#1F2A30; font-size:10.5pt;")
        self.waarschuwing.setText("<br>".join(f"<b>{t}</b>" for t in fouten) + ("<br>" if fouten and waarschuwingen
                                  else "") + "<br>".join(waarschuwingen))
        self.waarschuwing.show()

    def _waarschuwingen(self, s: LiveSessie) -> None:
        teksten, fouten = [], []
        if s.verbroken:
            fouten.append("Verbinding met de recorder kwijt. " + ("Opnieuw verbinden…" if s.herverbindt else
                          "Klik op Opnieuw verbinden als de recorder weer in de buurt is.")
                          + " De recorder slaat zelf door, er gaat geen data verloren.")
        lead_off = s.lead_off if s.toestand == "streamen" else (s.info.lead_off if s.info else None)
        if lead_off:
            teksten.append("Lead-off: een elektrode zit los of maakt slecht contact.")
        elif s.toestand == "streamen" and s.ecg is not None:
            laatste = s.buffer.lees()[1][-s.ecg.rate:]
            grens = 0.999 * s.ecg.datatype.analoog_max / s.ecg.gain
            if len(laatste) and float(np.mean(np.abs(laatste) >= grens)) > 0.5:
                teksten.append("Het ECG zit tegen de rand van het meetbereik: zitten de elektroden goed op de huid?")
        stil = s.seconden_zonder_data
        if stil is not None and stil > GEEN_DATA_S:
            fouten.append(f"Al {stil:.0f} s geen data van de recorder. Buiten bereik? Probeer Stop en Start.")
        graden = self._houding[3] if self._houding and s.toestand == "streamen" else float("nan")
        if self.bevestiging.currentText() == "sticker" and pd.notna(graden) and graden > OMGEKEERD_GRADEN:
            teksten.append(f"Zit de recorder ondersteboven op de sticker? Hij staat {graden:.0f}° gekanteld; "
                           "rechtop hoort bij ± 0°. Draai hem om, anders is de houding onbekend.")
        self._balk(fouten, teksten)

    def _toon_beweging(self, s: LiveSessie) -> None:
        """UC-1 live. Houding over de laatste 5 s, elke seconde (snel, met marge rond 45°); activiteit over de laatste
        20 s, elke 5 s (AI-01: de drempel hoort bij 20 s). Elk met zijn eigen tijdsaanduiding."""
        if s.toestand != "streamen" or s.acc is None:
            self.badges.hide()
            return
        tijd, acc = s.acc_buffer.lees()
        fs, bevestiging = s.acc_buffer.fs, self.bevestiging.currentText()
        if len(tijd) == 0:
            return
        nu_t = tijd[-1]

        def verlopen(vorige, stap):  # opnieuw bij nieuwe data, andere bevestiging of een nieuwe stream (tijd terug)
            return vorige is None or vorige[1] != bevestiging or not 0 <= nu_t - vorige[0] < stap

        if verlopen(self._houding, HOUDING_STAP_S):
            vorige = self._houding[2] if self._houding and self._houding[1] == bevestiging else None
            self._houding = (nu_t, bevestiging, *houding_nu(tijd, acc, fs, bevestiging, vorige))
        if verlopen(self._beweging, LIVE_STAP_S) or self._beweging[2]["activiteit"] == "onbekend":
            self._beweging = (nu_t, bevestiging, beweging_nu(tijd, acc, fs, bevestiging))
        _, _, houding, graden = self._houding
        activiteit = self._beweging[2]
        if bevestiging != "sticker":
            self.badges.houding.zet("onbekend", "Onbekend", "lanyard")
        elif houding == "onbekend" and pd.isna(graden):
            self.badges.houding.zet("onbekend", "Even wachten…", "")
        else:
            self.badges.houding.zet(houding, houding.capitalize(), f"{graden:.0f}°")
        if activiteit["activiteit"] == "onbekend":
            self.badges.activiteit.zet("onbekend", f"Nog {SEGMENT_S - len(tijd) / fs:.0f} s…", "")
        else:
            self.badges.activiteit.zet(activiteit["activiteit"], activiteit["activiteit"].capitalize(),
                                       f"sd {activiteit['acc_sd']:.3f} g")
        self.badges.toon()

    # --- plots (± 25× per seconde) ---

    def _teken(self) -> None:
        s = self.sessie
        if s is None or s.toestand != "streamen":
            return
        t, w = s.buffer.lees()
        if len(t) < 2:
            return
        venster = float(self.venster.currentText().split()[0])
        if self.netbrom.isChecked():
            w = np.column_stack([netbrom_filter(w[:, i], s.buffer.fs) for i in range(w.shape[1])])
        if self.filter.isChecked():  # over de hele buffer filteren en dan knippen: geen inzwaaien links
            w = np.column_stack([ecg_filter(w[:, i], s.buffer.fs) for i in range(w.shape[1])])
        t_laatste = t[-1]
        x = t - t_laatste
        binnen = x >= -venster
        for i, lijn in enumerate(self.lijnen_ecg):
            lijn.setData(x[binnen], w[binnen, i]) if i < w.shape[1] else lijn.clear()
        self.plot_ecg.setXRange(-venster, 0, padding=0)
        if self.y_vast.value() > 0:
            self.plot_ecg.setYRange(-self.y_vast.value(), self.y_vast.value(), padding=0)
        else:
            self.plot_ecg.enableAutoRange(axis="y")
        for naam, buffer, aan in (("acc", s.acc_buffer, self.toon_acc), ("gyro", s.gyro_buffer, self.toon_gyro)):
            if not aan.isChecked():
                continue
            tb, wb = buffer.lees()
            if len(tb) < 2:
                continue
            xb = tb - t_laatste
            m = xb >= -venster
            lijnen = self.lijnen_beweging[naam]
            for i in range(3):
                lijnen[i].setData(xb[m], wb[m, i])
            lijnen[3].setData(xb[m], np.sqrt((wb[m] ** 2).sum(axis=1)))

    # --- opname en annotaties ---

    def open_opname(self, map: str) -> None:
        self.map = map
        o = Opname.laad(map)
        self.plaatsing.setText(o.laatste_plaatsing)
        self.bevestiging.setCurrentText("lanyard" if "lanyard" in o.info.elektroden.lower() else "sticker")
        self._toon_opname()

    def _opname(self) -> Opname | None:
        return Opname.laad(self.map) if self.map else None

    def na_wijziging(self) -> None:
        """Na ongedaan maken / opnieuw doen: bestaat de opname nog? Dan het logboek en de knoppen bijwerken."""
        if self.map:
            try:
                Opname.laad(self.map)
            except FileNotFoundError:
                self.map = None
        self._toon_opname()

    def _actie(self, functie) -> None:
        """Annotatie-actie op de opname; zonder opname eerst een melding."""
        o = self._opname()
        if o is None:
            fout(self, "Start of hervat eerst een opname (Nieuwe opname… of Hervatten…).")
            return
        try:
            functie(o)
        except ValueError as e:
            fout(self, str(e))
        self._toon_opname()

    def _start_periode(self, label: str) -> None:
        self._actie(lambda o: o.start_periode(label, self.plaatsing.text().strip()))

    def _start_vrije_periode(self) -> None:
        label = self.vrije_periode.text().strip()
        if label:
            self._start_periode(label)
            self.vrije_periode.clear()

    def _vrij_moment(self) -> None:
        self._actie(lambda o: o.moment(self.vrij_moment.text().strip() or "markering"))
        self.vrij_moment.clear()

    def _afsluiten(self) -> None:
        o = self._opname()
        if o is not None and zeker(self, "Lopende periode stoppen en de live opname afsluiten?"):
            o.sluit_live_af()
            self.map = None
            self._toon_opname()

    def _nieuwe_opname(self) -> None:
        deelnemers = Deelnemers(DATA_ROOT).alle()
        if not deelnemers:
            fout(self, "Voeg eerst een deelnemer toe (scherm Deelnemers).")
            return
        dialoog = QDialog(self)
        dialoog.setWindowTitle("Nieuwe live opname")
        vorm = QFormLayout(dialoog)
        keuze = QComboBox()
        for d in deelnemers:
            keuze.addItem(d.weergave, d)
        velden = OpnameVelden()
        velden.elektroden.setCurrentIndex(0)  # sticker: de standaard (HW-06)
        vorm.addRow("Deelnemer", keuze)
        vorm.addRow(velden)
        knoppen = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        knoppen.button(QDialogButtonBox.StandardButton.Ok).setText("Start opname")
        knoppen.accepted.connect(dialoog.accept)
        knoppen.rejected.connect(dialoog.reject)
        vorm.addRow(knoppen)
        if dialoog.exec():
            try:
                o = Opname.nieuw(keuze.currentData(), nu(), root=DATA_ROOT, **velden.waarden())
            except ValueError as e:
                fout(self, str(e))
                return
            self.open_opname(str(o.map))

    def _hervat(self) -> None:
        open_ = [o for o in Opname.alle(DATA_ROOT) if not o.info.live_afgesloten]
        if not open_:
            fout(self, "Geen opnames die nog niet afgesloten zijn.")
            return
        namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
        dialoog = QDialog(self)
        dialoog.setWindowTitle("Opname hervatten")
        vorm = QFormLayout(dialoog)
        keuze = QComboBox()
        for o in open_:
            keuze.addItem(opname_label(o, namen), str(o.map))
        vorm.addRow("Opname", keuze)
        knoppen = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        knoppen.accepted.connect(dialoog.accept)
        knoppen.rejected.connect(dialoog.reject)
        vorm.addRow(knoppen)
        if dialoog.exec():
            self.open_opname(keuze.currentData())

    def _toon_opname(self) -> None:
        o = self._opname()
        for w in (self.k_sync, self.k_afsluiten, self.experiment, *self.periode_knoppen.values()):
            w.setEnabled(o is not None)
        if o is None:
            self.opname_tekst.setText("Geen opname actief. Kijken kan ook zonder: dan wordt niets gelogd.")
            self.experiment.clear()
            self._vul_log(None)
            self._toon_actief()
            return
        namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
        self.opname_tekst.setText(f"<b>{opname_label(o, namen)}</b><br>{o.info.id} · {o.info.elektroden}")
        if not self.experiment.hasFocus():
            self.experiment.setText(o.info.experiment)
        self._vul_log(o)
        self._toon_actief(o)

    def _toon_actief(self, o: Opname | None = None) -> None:
        o = o or self._opname()
        actief = o.actieve_periode if o else None
        self.k_stop_periode.setEnabled(actief is not None)
        for label, k in self.periode_knoppen.items():
            k.setChecked(actief is not None and actief.label == label)
        if actief is None:
            self.actief.setText("Geen periode actief." if o else "")
        else:
            verstreken = (pd.Timestamp(nu()) - actief.t_start).total_seconds()
            self.actief.setText(f"<span style='font-size:15pt; color:{ORANJE}'><b>Bezig: {actief.label}</b></span> "
                                f"{int(verstreken // 60)}:{int(verstreken % 60):02d} sinds {klok(actief.t_start)}"
                                + (f" · {len(o.syncs)}× sync" if o.syncs else " · <b>nog geen sync-sprong</b>"))

    def _vul_log(self, o: Opname | None) -> None:
        self.log.blockSignals(True)
        rijen = list(reversed(o.chronologisch())) if o else []
        self.log.setRowCount(len(rijen))
        for r, a in enumerate(rijen):
            waarden = [a.soort, a.label, klok(a.t_start, True), klok(a.t_eind, True) if a.t_eind is not None else "",
                       f"{a.duur_s:.1f}" if a.duur_s is not None else "", a.plaatsing, a.opmerking]
            for k, waarde in enumerate(waarden):
                item = QTableWidgetItem(waarde)
                item.setData(256, a.id)
                if k not in BEWERKBAAR:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.log.setItem(r, k, item)
        self.log.blockSignals(False)

    def _log_gewijzigd(self, item: QTableWidgetItem) -> None:
        veld = BEWERKBAAR.get(item.column())
        if veld:
            self._actie(lambda o: o.wijzig(item.data(256), **{veld: item.text().strip()}))

    def _verwijder_regel(self) -> None:
        rijen = self.log.selectionModel().selectedRows()
        if rijen and zeker(self, "Deze regel uit het logboek verwijderen?"):
            id = self.log.item(rijen[0].row(), 0).data(256)
            self._actie(lambda o: o.verwijder([id]))


class _Badge(QLabel):
    """Eén gekleurd label: kop (wat en over welk venster), waarde groot, detail klein."""

    KLEUREN = {"rechtop": ("#CDEBF3", TEKST), "liggend": (DONKER, "white"), "rust": ("#CDEBF3", TEKST),
               "beweging": (ORANJE, "white"), "lopen": ("#8A4B00", "white"), "onbekend": ("#ECEFF1", SUBTIEL)}

    def __init__(self, kop: str) -> None:
        super().__init__()
        self.kop = kop

    def zet(self, soort: str, waarde: str, detail: str) -> None:
        achtergrond, tekst = self.KLEUREN.get(soort, self.KLEUREN["onbekend"])
        self.setStyleSheet(f"background:{achtergrond}; color:{tekst}; border-radius:8px; padding:5px 12px;")
        self.setText(f"<span style='font-size:7.5pt; letter-spacing:1px'>{self.kop}</span><br>"
                     f"<span style='font-size:14pt; font-weight:700'>{waarde}</span>"
                     + (f" <span style='font-size:9pt'>{detail}</span>" if detail else ""))


class Badges(QWidget):
    """Houding en activiteit als twee labels rechtsboven over de plots; muisklikken gaan erdoorheen naar de plot."""

    def __init__(self, ouder: QWidget) -> None:
        super().__init__(ouder)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        rij = QHBoxLayout(self)
        rij.setContentsMargins(0, 0, 0, 0)
        rij.setSpacing(8)
        self.houding = _Badge(f"HOUDING · LAATSTE {HOUDING_LIVE_S} S")
        self.activiteit = _Badge(f"ACTIVITEIT · LAATSTE {SEGMENT_S} S")
        rij.addWidget(self.houding)
        rij.addWidget(self.activiteit)
        ouder.installEventFilter(self)
        self.hide()

    def toon(self) -> None:
        self._plaats()
        self.show()
        self.raise_()

    def _plaats(self) -> None:
        self.adjustSize()
        ouder = self.parentWidget()
        self.move(ouder.width() - self.width() - 24, 14)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt-naam
        if event.type() == QEvent.Type.Resize:
            self._plaats()
        return False
