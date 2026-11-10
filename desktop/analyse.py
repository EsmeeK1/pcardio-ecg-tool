"""Analyse: data koppelen (met klokcorrectie) en een opname bekijken en annoteren."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from beheer import gekozen, tabel, vul
from gedeeld import DONKER, GRAFIEK, ORANJE, PALET, PRIMAIR, SUBTIEL, TEKST, OpnameVelden, bezig, epoch, fout, hulp, \
    klok, opname_label, tips, zeker
from kern.beweging import beweging_per_segment
from kern.koppelen import SOORT_LABEL, Ingelezen, bestanden_in_map, binnen_data, lees_in, voorstellen
from kern.lijsten import lees_lijst
from kern.opslag import BEOORDELINGEN, DATA_ROOT, Deelnemers, Opname
from kern.verwerking import (
    GROTE_CORRECTIE_S, ZES_LEADS, ecg_filter, magnitude, uur_verschoven, zes_leads, zoek_syncs,
)

UITPAK_MAP = DATA_ROOT / "_upload"
IN_BEELD = QBrush(QColor("#FFE6C7"))  # rij van een annotatie die in het venster valt
BEGIN_S, VENSTER_S = 5.0, 10.0  # beginweergave in Bekijken
UC1_KLEUREN = {"rust": "#9FDCEB", "beweging": ORANJE, "lopen": "#8A4B00", "rechtop": "#6EC6DA", "liggend": DONKER,
               "onbekend": "#D9D9D9"}


def robuust_bereik(y: np.ndarray, max_punten: int = 200_000) -> tuple[float, float]:
    """Y-bereik zonder uitschieters (0,5–99,5 percentiel + marge), zoals Live: het inzwaaien van het filter aan het
    begin of één artefact drukt de rest anders plat. Grote reeksen worden eerst uitgedund."""
    y = y[:: max(1, len(y) // max_punten)]
    y = y[np.isfinite(y)]
    if not len(y):
        return -1.0, 1.0
    laag, hoog = np.percentile(y, [0.5, 99.5])
    marge = 0.15 * (hoog - laag) or 0.1
    return float(laag - marge), float(hoog + marge)
NIEUW = "__nieuw__"


def opname_keuze(alleen_met_data: bool = False) -> QComboBox:
    keuze = QComboBox()
    keuze.setMinimumWidth(380)
    vul_opnames(keuze, alleen_met_data)
    return keuze


def vul_opnames(keuze: QComboBox, alleen_met_data: bool = False, extra: list[tuple[str, str]] = (),
                filter=lambda o: True) -> None:
    huidig = keuze.currentData()
    namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
    keuze.blockSignals(True)
    keuze.clear()
    for tekst, data in extra:
        keuze.addItem(tekst, data)
    for o in Opname.alle(DATA_ROOT):
        if (o.heeft_signalen or not alleen_met_data) and filter(o):
            keuze.addItem(opname_label(o, namen), str(o.map))
    keuze.setCurrentIndex(max(keuze.findData(huidig), 0))
    keuze.blockSignals(False)


# --- data koppelen ---------------------------------------------------------------------------------------


class KoppelenScherm(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.ingelezen: Ingelezen | None = None
        self._paden: list[Path] = []  # alle gekozen bestanden; elke keer kiezen voegt toe (ook uit andere mappen)
        inhoud = QWidget()
        v = QVBoxLayout(inhoud)
        v.addWidget(self._inlezen_groep())
        v.addWidget(self._koppel_groep())
        v.addWidget(self._klok_groep())
        v.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inhoud)
        scroll.setWidgetResizable(True)
        QVBoxLayout(self).addWidget(scroll)
        self._toon_ingelezen()

    def _inlezen_groep(self) -> QGroupBox:
        groep = QGroupBox("1. Bestanden inlezen")
        v = QVBoxLayout(groep)
        v.addWidget(QLabel("P-Cardio-bestanden (data_*.txt of CSV), een eerdere export (…_volledig.csv) en/of een "
                           "annotatiebestand (van de telefoon-app of een export), los of in een .zip."))
        rij = QHBoxLayout()
        for tekst, actie in (("Bestanden toevoegen…", self._kies_bestanden), ("Map toevoegen…", self._kies_map),
                             ("Lijst leegmaken", self._leegmaken)):
            k = QPushButton(tekst)
            k.clicked.connect(actie)
            rij.addWidget(k)
        rij.addStretch()
        v.addLayout(rij)
        self.meldingen = QLabel()
        self.meldingen.setWordWrap(True)
        v.addWidget(self.meldingen)
        self.bestanden = tabel(["Bestand", "Herkend als"])
        self.signalen = tabel(["Signaal", "Bestand", "Kanalen", "Samples", "Hz", "Start", "Eind", "Duur (min)"])
        for t in (self.bestanden, self.signalen):
            t.setMaximumHeight(150)
            v.addWidget(t)
        return groep

    def _koppel_groep(self) -> QGroupBox:
        self.koppel = QGroupBox("2. Koppelen aan een opname")
        v = QVBoxLayout(self.koppel)
        self.voorstel = QLabel()
        self.voorstel.setWordWrap(True)
        self.doel = QComboBox()
        self.doel.currentIndexChanged.connect(self._toon_doel)
        self.deelnemer = QComboBox()
        self.velden = OpnameVelden("de pc of telefoon waarmee geannoteerd is")
        self.controle = QLabel()
        self.controle.setWordWrap(True)
        self.toch = QCheckBox("Toch koppelen")
        k = QPushButton("Koppel")
        k.setStyleSheet(f"background:{PRIMAIR}; color:white; font-weight:bold; padding:6px;")
        k.clicked.connect(lambda: self._koppel())
        self.k_koppel = k
        vorm = QFormLayout()
        vorm.addRow("Opname", self.doel)
        vorm.addRow("Deelnemer", self.deelnemer)
        v.addWidget(self.voorstel)
        v.addLayout(vorm)
        v.addWidget(self.velden)
        v.addWidget(self.controle)
        v.addWidget(self.toch)
        v.addWidget(k)
        tips((self.doel, hulp.KOPPEL_OPNAME), (k, hulp.KOPPEL))
        return self.koppel

    def _klok_groep(self) -> QGroupBox:
        groep = QGroupBox("3. Klokcorrectie")
        v = QVBoxLayout(groep)
        v.addWidget(QLabel("De klok van de pc en die van de P-Cardio lopen uiteen. De correctie (P-Cardio − pc) "
                           "zet de live annotaties op de juiste plek in de data. Zoek de sync-sprongen in de "
                           "accelerometer, of vul de correctie handmatig in."))
        self.klok_opname = opname_keuze(alleen_met_data=True)
        self.klok_opname.currentIndexChanged.connect(self._toon_klok)
        self.klok_huidig = QLabel()
        self.zoek_s = QDoubleSpinBox()
        self.zoek_s.setRange(1, 300)
        self.zoek_s.setValue(120)  # de P-Cardio-klok liep +76 s uit op 4 nov 2026
        self.zoek_s.setPrefix("± ")
        self.zoek_s.setSuffix(" s")
        zoek = QPushButton("Zoek sync-sprongen")
        zoek.clicked.connect(lambda: self._zoek_sync())
        self.sync_tekst = QLabel()
        self.sync_tekst.setWordWrap(True)
        self.sync_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.sync_plot.setLabel("left", "|acc|", "g")
        self.sync_plot.setMinimumHeight(200)
        self.k_voorstel = QPushButton()
        self.k_voorstel.clicked.connect(lambda: self._zet_correctie(self._voorstel, "sync"))
        self.uur = QLabel()
        self.uur.setWordWrap(True)
        self.uur.setStyleSheet("background:#FFF4E5; border-left:4px solid #FF9806; padding:6px;")
        self.k_uur = QPushButton()
        self.k_uur.clicked.connect(lambda: self._verschuif_uur())
        self.handmatig = QDoubleSpinBox()
        self.handmatig.setRange(-100000, 100000)
        self.handmatig.setDecimals(3)
        self.handmatig.setSuffix(" s")
        opslaan = QPushButton("Handmatig opslaan")
        opslaan.clicked.connect(lambda: self._zet_correctie(self.handmatig.value(), "handmatig"))
        vorm = QFormLayout()
        vorm.addRow("Opname", self.klok_opname)
        vorm.addRow("Zoekvenster", self.zoek_s)
        v.addLayout(vorm)
        v.addWidget(self.klok_huidig)
        v.addWidget(zoek)
        v.addWidget(self.sync_tekst)
        v.addWidget(self.sync_plot)
        v.addWidget(self.uur)
        v.addWidget(self.k_uur)
        v.addWidget(self.k_voorstel)
        rij = QHBoxLayout()
        rij.addWidget(QLabel("Handmatige correctie"))
        rij.addWidget(self.handmatig)
        rij.addWidget(opslaan)
        rij.addStretch()
        v.addLayout(rij)
        self._voorstel = None
        self._toon_klok()
        tips((self.zoek_s, hulp.ZOEKVENSTER), (self.handmatig, hulp.HANDMATIG), (self.k_voorstel, hulp.GEBRUIK_VOORSTEL),
             (groep, hulp.KLOKCORRECTIE))
        return groep

    def ververs(self) -> None:
        vul_opnames(self.klok_opname, alleen_met_data=True)
        self._toon_ingelezen()

    def open_opname(self, map: str) -> None:
        self.ververs()
        self.klok_opname.setCurrentIndex(max(self.klok_opname.findData(map), 0))
        if self.doel.findData(map) >= 0:
            self.doel.setCurrentIndex(self.doel.findData(map))

    # --- 1. inlezen ---

    def _kies_bestanden(self) -> None:
        paden, _ = QFileDialog.getOpenFileNames(self, "Bestanden toevoegen (meerdere: Ctrl+klik)", "",
                                                "Data (*.txt *.csv *.zip);;Alle bestanden (*)")
        if paden:
            self._lees([Path(p) for p in paden])

    def _leegmaken(self) -> None:
        shutil.rmtree(UITPAK_MAP, ignore_errors=True)
        self.ingelezen, self._paden = None, []
        self._toon_ingelezen()

    def _kies_map(self) -> None:
        map = QFileDialog.getExistingDirectory(self, "Map met P-Cardio-bestanden")
        if map:
            paden = bestanden_in_map(Path(map))
            if paden:
                self._lees(paden)
            else:
                fout(self, f"Geen .csv-, .txt- of .zip-bestanden gevonden in {map}")

    @bezig
    def _lees(self, paden: list[Path]) -> None:
        """Nieuwe bestanden bij de al gekozen bestanden zetten en alles opnieuw inlezen: zo kan de .txt van de
        P-Cardio (D:) samen met de annotatie-CSV van de telefoon (Downloads), ook al staan ze in andere mappen."""
        bekend = {p.resolve() for p in self._paden}
        self._paden += [p for p in paden if p.resolve() not in bekend]
        shutil.rmtree(UITPAK_MAP, ignore_errors=True)
        self.ingelezen = lees_in(self._paden, UITPAK_MAP)
        self._toon_ingelezen()

    def _toon_ingelezen(self) -> None:
        r = self.ingelezen
        self.koppel.setVisible(bool(r and (r.signalen or r.annotaties)))
        if r is None:
            self.meldingen.setText("Nog niets ingelezen.")
            vul(self.bestanden, [], [])
            vul(self.signalen, [], [])
            return
        teksten = [f"<span style='color:#B00020'>{f}</span>" for f in r.fouten]
        teksten += [f"<span style='color:#8A4B00'>{m}</span>" for m in r.meldingen]
        if r.annotaties:
            a = r.annotaties
            teksten.append(f"{a['bestand']}: {len(a['lijst'])} annotaties"
                           + (f", klokcorrectie {a['klokcorrectie_s']:+.2f} s." if a["klokcorrectie_s"] is not None
                              else "."))
        if r.signalen and "ecg" not in r.signalen:
            teksten.append("<span style='color:#8A4B00'>Er zit geen ECG-signaal tussen de ingelezen bestanden.</span>")
        self.meldingen.setText("<br>".join(teksten))
        vul(self.bestanden, [[n, SOORT_LABEL[s]] for n, s in r.soorten.items()], list(r.soorten))
        vul(self.signalen, [[n, s.bron, ", ".join(f"{k} ({s.eenheden.get(k, '')})" for k in s.kanalen), len(s.data),
                             round(s.fs, 2), klok(s.start), klok(s.eind),
                             round((s.eind - s.start).total_seconds() / 60, 1)] for n, s in r.signalen.items()],
            list(r.signalen))
        self._vul_doel()

    # --- 2. koppelen ---

    def _vul_doel(self) -> None:
        r = self.ingelezen
        opnames = Opname.alle(DATA_ROOT)
        namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
        per_id = {o.info.id: o for o in opnames}
        kandidaten = voorstellen(r.signalen, opnames) if r.signalen else []
        keuzes: list[tuple[str, str]] = []
        if r.opname_id in per_id:
            self.voorstel.setText(f"Voorstel: <b>{opname_label(per_id[r.opname_id], namen)}</b> — zelfde opname-ID "
                                  "als de bestandsnaam.")
            keuzes.append((opname_label(per_id[r.opname_id], namen), str(per_id[r.opname_id].map)))
        elif kandidaten:
            beste, score = kandidaten[0]
            self.voorstel.setText(f"Voorstel: <b>{opname_label(beste, namen)}</b> — {score:.0%} van de live "
                                  "annotaties valt binnen deze data.")
        elif r.signalen:
            self.voorstel.setText("Geen bestaande opname past bij deze data, dus er wordt een <b>nieuwe opname</b> "
                                  "gemaakt. Dat klopt als er niet live geannoteerd is; annoteer daarna in Bekijken.")
        else:
            self.voorstel.setText("Alleen annotaties (bijv. van de telefoon-app): maak er een nieuwe opname van, en "
                                  "lees daarna de P-Cardio-bestanden in.")
        for o, score in kandidaten:
            keuzes.append((f"{opname_label(o, namen)}  ({score:.0%} overlap)", str(o.map)))
        gezien = {d for _, d in keuzes}
        keuzes += [(opname_label(o, namen), str(o.map)) for o in opnames if str(o.map) not in gezien]
        nieuw = ("Nieuwe opname" + ("" if r.annotaties else " (alleen data, achteraf annoteren)"), NIEUW)
        keuzes = [*keuzes, nieuw] if (r.opname_id in per_id or kandidaten) else [nieuw, *keuzes]
        self.doel.blockSignals(True)
        self.doel.clear()
        for tekst, data in keuzes:
            self.doel.addItem(tekst, data)
        self.doel.blockSignals(False)
        self.deelnemer.clear()
        for d in Deelnemers(DATA_ROOT).alle():
            self.deelnemer.addItem(d.weergave, d)
        uit_bestand = r.opname_id.rsplit("_", 1)[1] if r.opname_id else None
        for i in range(self.deelnemer.count()):
            if self.deelnemer.itemData(i).id == uit_bestand:
                self.deelnemer.setCurrentIndex(i)
        self._toon_doel()

    def _toon_doel(self) -> None:
        r = self.ingelezen
        if r is None:
            return
        nieuw = self.doel.currentData() == NIEUW
        self.deelnemer.setEnabled(nieuw)
        self.velden.setVisible(nieuw)
        doel = None if nieuw or self.doel.currentData() is None else Opname.laad(self.doel.currentData())
        teksten = []
        if doel is not None:
            if r.signalen and doel.heeft_signalen:
                teksten.append(f"Aan deze opname is al data gekoppeld ({', '.join(doel.info.bronbestanden)}). "
                               "Koppelen vervangt die.")
            if r.annotaties and doel.annotaties:
                teksten.append(f"Vervangt de {len(doel.annotaties)} bestaande annotaties van deze opname.")
        data = r.signalen or (doel.laad_signalen() if doel is not None and doel.heeft_signalen else {})
        ok = True
        if r.annotaties and r.annotaties["lijst"] and data:
            correctie = r.annotaties["klokcorrectie_s"]
            if correctie is None:
                correctie = (doel.info.klokcorrectie_s if doel is not None else None) or 0.0
            totaal = len(r.annotaties["lijst"])
            binnen = binnen_data(r.annotaties["lijst"], correctie, data)
            if binnen == totaal:
                teksten.append(f"Alle {totaal} annotaties vallen binnen de data.")
            elif binnen:
                teksten.append(f"{totaal - binnen} van {totaal} annotaties vallen buiten de data.")
            else:
                teksten.append("<b>Geen enkele annotatie valt binnen de data.</b> Hoort het annotatiebestand wel bij "
                               "deze opname?")
                ok = False
        self.controle.setText("<br>".join(teksten))
        self.toch.setVisible(not ok)
        self.toch.setChecked(False)
        self._annotaties_ok = ok

    @bezig
    def _koppel(self) -> None:
        r = self.ingelezen
        if not (self._annotaties_ok or self.toch.isChecked()):
            fout(self, "De annotaties vallen niet binnen de data. Vink 'Toch koppelen' aan als het toch klopt.")
            return
        try:
            if self.doel.currentData() == NIEUW:
                if self.deelnemer.currentData() is None:
                    raise ValueError("Voeg eerst een deelnemer toe (scherm Deelnemers).")
                starts = [s.start for s in r.signalen.values()] or [a.t_start for a in r.annotaties["lijst"]]
                if not starts:
                    raise ValueError("Het annotatiebestand is leeg.")
                doel = Opname.nieuw(self.deelnemer.currentData(), min(starts), root=DATA_ROOT, live_afgesloten=True,
                                    **self.velden.waarden())
            else:
                doel = Opname.laad(self.doel.currentData())
                vervangen = [t for t, ja in (("de data", r.signalen and doel.heeft_signalen),
                                             (f"{len(doel.annotaties)} annotaties", r.annotaties and doel.annotaties))
                             if ja]
                if vervangen and not zeker(self, f"{doel.info.id} heeft al {' en '.join(vervangen)}. Vervangen?"):
                    return
            if r.signalen:
                doel.bewaar_signalen(r.signalen, r.bestanden)
            if r.annotaties:
                doel.vervang_annotaties(r.annotaties["lijst"], r.annotaties["klokcorrectie_s"])
        except ValueError as e:
            fout(self, str(e))
            return
        shutil.rmtree(UITPAK_MAP, ignore_errors=True)
        self.ingelezen, self._paden = None, []
        self.ververs()
        self.klok_opname.setCurrentIndex(max(self.klok_opname.findData(str(doel.map)), 0))
        self.meldingen.setText(f"<b>Gekoppeld aan {doel.info.id}.</b> Controleer hieronder de klokcorrectie.")

    # --- 3. klokcorrectie ---

    def _klok_opname(self) -> Opname | None:
        return Opname.laad(self.klok_opname.currentData()) if self.klok_opname.currentData() else None

    def _toon_klok(self) -> None:
        o = self._klok_opname()
        self._voorstel = None
        self.k_voorstel.hide()
        self.uur.hide()
        self.k_uur.hide()
        self.sync_plot.clear()
        self.sync_plot.hide()  # pas tonen na Zoek sync-sprongen: leeg is hij alleen verwarrend
        self.sync_tekst.clear()
        if o is None:
            self.klok_huidig.setText("Nog geen opname met data.")
            return
        huidig = o.info.klokcorrectie_s
        self.klok_huidig.setText(f"Huidige correctie: <b>{huidig:+.2f} s</b> ({o.info.klokcorrectie_bron})"
                                 if huidig is not None else "Huidige correctie: <b>nog niet bepaald</b> (0 s).")
        self.handmatig.setValue(huidig or 0.0)
        if o.annotatie_bereik is None:
            self.sync_tekst.setText("Er is niet live geannoteerd, dus een klokcorrectie is niet nodig.")
        elif not o.syncs:
            self.sync_tekst.setText("Deze opname heeft geen sync-sprong. Vul de correctie zo nodig handmatig in.")

    @bezig
    def _zoek_sync(self) -> None:
        o = self._klok_opname()
        if o is None or not o.syncs:
            return
        signalen = o.laad_signalen()
        if "acc" not in signalen:
            fout(self, "Geen accelerometerdata om de sync-sprong in te zoeken. Vul de correctie handmatig in.")
            return
        acc, zoek_s = signalen["acc"], self.zoek_s.value()
        self.sync_plot.clear()
        self.sync_plot.show()
        regels, duidelijk = [], []
        for sync, r in zip(o.syncs, zoek_syncs(acc.data, [s.t_start for s in o.syncs], zoek_s)):
            if r is None:
                regels.append(f"Sync {klok(sync.t_start)}: geen accelerometerdata in het zoekvenster. Vergroot het "
                              "zoekvenster of corrigeer handmatig.")
                continue
            regels.append(f"Sync {klok(sync.t_start)} → piek {klok(r.t_piek)}: <b>{r.correctie_s:+.2f} s</b>"
                          + ("" if r.duidelijk else " <span style='color:#8A4B00'>(geen duidelijke piek)</span>"))
            if r.duidelijk:
                duidelijk.append(r.correctie_s)
            rond = r.t_piek  # rond de gevonden piek: die kan een uur verschoven liggen
            stuk = acc.data[(acc.data["tijd"] >= rond - pd.Timedelta(seconds=zoek_s))
                            & (acc.data["tijd"] <= rond + pd.Timedelta(seconds=zoek_s))]
            self.sync_plot.plot(epoch(stuk["tijd"]), magnitude(stuk, list(acc.kanalen[:3])), pen=pg.mkPen(PRIMAIR))
            if abs(r.correctie_s) <= zoek_s:  # gelogd moment alleen tekenen als het in beeld valt
                self.sync_plot.addItem(pg.InfiniteLine(epoch(sync.t_start),
                                                       pen=pg.mkPen(SUBTIEL, style=Qt.PenStyle.DashLine)))
            self.sync_plot.addItem(pg.InfiniteLine(epoch(r.t_piek), pen=pg.mkPen(ORANJE, width=2)))
        if len(duidelijk) >= 2:
            regels.append(f"Verschil eerste en laatste sync: {duidelijk[-1] - duidelijk[0]:+.2f} s "
                          "(klokdrift + reactietijd).")
        self.sync_tekst.setText("<br>".join(regels) + "<br><span style='color:#4A6A72'>Stippellijn: gelogd moment · "
                                "oranje: gevonden piek</span>")
        # Mediaan: één te vroeg of te laat geklikte sync trekt het voorstel zo niet scheef.
        self._voorstel = round(float(np.median(duidelijk)), 3) if duidelijk else None
        self.k_voorstel.setVisible(self._voorstel is not None)
        self.uur.hide()
        self.k_uur.hide()
        if self._voorstel is not None:
            self.k_voorstel.setText(f"Gebruik voorstel: {self._voorstel:+.2f} s")
            uren = uur_verschoven(self._voorstel)
            if uren:
                self.uur.setText(f"<b>De correctie is ongeveer {uren:+d} uur.</b> Staat de P-Cardio nog op "
                                 f"{'zomertijd' if uren > 0 else 'wintertijd'}? Dan loopt de data een uur "
                                 f"{'voor' if uren > 0 else 'achter'}. Verschuif de data een uur, dan klopt de "
                                 "kloktijd in de plots en exports weer (de ruwe bestanden blijven zoals ze zijn).")
                self.k_uur.setText(f"Data {-uren:+d} uur verschuiven")
                self._uren = uren
                self.k_uur.show()
                self.uur.show()
            elif abs(self._voorstel) > GROTE_CORRECTIE_S:
                self.uur.setText(f"<b>Ongebruikelijk grote correctie ({self._voorstel / 60:+.1f} min).</b> Klopt de "
                                 "klok van de P-Cardio? Gewoonlijk loopt hij maar ± een minuut uit.")
                self.uur.show()
        elif regels:
            self.sync_tekst.setText(self.sync_tekst.text() + "<br><b>Geen duidelijke piek.</b> Vergroot het "
                                    "zoekvenster, of vul de correctie handmatig in.")

    @bezig
    def _verschuif_uur(self) -> None:
        o = self._klok_opname()
        if o is not None and zeker(self, f"Alle signalen van {o.info.id} {-self._uren:+d} uur verschuiven?"):
            o.verschuif_signalen(-3600 * self._uren)
            self._zoek_sync()

    def _zet_correctie(self, waarde: float | None, bron: str) -> None:
        o = self._klok_opname()
        if o is not None and waarde is not None:
            o.zet_klokcorrectie(waarde, bron)
            self._toon_klok()


# --- bekijken & annoteren --------------------------------------------------------------------------------


class BekijkenScherm(QWidget):
    """Overzicht van de hele opname met een sleepbaar venster; daaronder het detail met een sleepbare selectie
    (oranje). Een labelknop maakt van de selectie een periode; een annotatie in de lijst kiezen zet de selectie
    op die annotatie, zodat je begin en eind kunt verslepen en opslaan."""

    def __init__(self) -> None:
        super().__init__()
        self.opname: Opname | None = None
        self.signalen = {}
        self.gekozen_id: int | None = None
        self._overzicht_items: list = []  # annotaties in het overzicht, om opnieuw te kunnen tekenen
        self._getekend: list = []  # y-waarden van de getekende ECG-lijnen, voor de robuuste y-as
        self._segmenten = None  # UC-1-segmenten (x0, tabel), voor de hover
        self._ecg, self._bereik = None, (0.0, 1.0)
        self._tijden, self._in_beeld = [], None  # per rij (begin, eind) in epoch-s; rijen die nu in beeld zijn

        self.keuze = opname_keuze(alleen_met_data=True)
        self.keuze.currentIndexChanged.connect(lambda: self._laad())
        # Filters op de opnamelijst
        self.f_deelnemer, self.f_datum, self.f_bevestiging = QComboBox(), QComboBox(), QComboBox()
        self.f_bevestiging.addItems(["Sticker en lanyard", "sticker", "lanyard"])
        for f in (self.f_deelnemer, self.f_datum, self.f_bevestiging):
            f.currentIndexChanged.connect(lambda: self.ververs())
        filters = QHBoxLayout()
        for w in (QLabel("Opname"), self.keuze, QLabel("Filter:"), self.f_deelnemer, self.f_datum, self.f_bevestiging):
            filters.addWidget(w)
        filters.addStretch()

        self.leads = {k: QCheckBox(k) for k in ZES_LEADS}
        self.leads["I"].setChecked(True)
        for k in ("III", "aVR", "aVL", "aVF"):
            self.leads[k].setToolTip("Berekend uit I en II (Einthoven): geen nieuwe informatie.")
        self.filter = QCheckBox("Filter 0,5–40 Hz")
        self.filter.setChecked(True)
        self.toon_acc, self.toon_gyro = QCheckBox("Accelerometer"), QCheckBox("Gyroscoop")
        self.bevestiging = QComboBox()
        self.bevestiging.addItems(["sticker", "lanyard"])
        self.bevestiging.setToolTip("Bevestiging van de recorder voor UC-1. Aan een lanyard is de houding onbekend.")
        for w in (*self.leads.values(), self.filter):
            w.toggled.connect(lambda _=False: self._teken_detail())
        self.toon_acc.toggled.connect(lambda aan: self._toon_beweging_rij(self.acc_plot, aan))
        self.toon_gyro.toggled.connect(lambda aan: self._toon_beweging_rij(self.gyro_plot, aan))
        self.bevestiging.currentIndexChanged.connect(lambda: self._teken_beweging())
        balk = QHBoxLayout()
        for w in (*self.leads.values(), self.filter, self.toon_acc, self.toon_gyro, QLabel("UC-1 bevestiging"),
                  self.bevestiging):
            balk.addWidget(w)
        balk.addStretch()

        self.grafiek = pg.GraphicsLayoutWidget()
        self.overzicht = self.grafiek.addPlot(row=0, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.overzicht.setMaximumHeight(170)
        self.overzicht.setMouseEnabled(x=True, y=False)
        self.beweging_plot = self.grafiek.addPlot(row=1, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.beweging_plot.setMaximumHeight(70)
        self.beweging_plot.setXLink(self.overzicht)
        self.beweging_plot.setMouseEnabled(x=True, y=False)
        self.beweging_plot.getAxis("left").setTicks([[(0.5, "houding"), (1.5, "activiteit")]])
        self.detail = self.grafiek.addPlot(row=2, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.detail.setMouseEnabled(x=True, y=False)
        self.detail.showGrid(x=True, y=True, alpha=0.2)
        # acc en gyro elk in een eigen rij onder het ECG (zoals bij Live), met dezelfde tijdas
        self.acc_plot = self.grafiek.addPlot(row=3, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.gyro_plot = self.grafiek.addPlot(row=4, col=0, axisItems={"bottom": pg.DateAxisItem()})
        for plot, naam, eenheid in ((self.acc_plot, "acc", "g"), (self.gyro_plot, "gyro", "°/s")):
            plot.setLabel("left", naam, eenheid)
            plot.setXLink(self.detail)
            plot.setMouseEnabled(x=True, y=False)
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.addLegend(offset=(10, 5), colCount=4)
            plot.hide()
        self.venster = pg.LinearRegionItem(brush=pg.mkBrush(255, 152, 6, 40), pen=pg.mkPen(ORANJE))
        self.venster.setZValue(10)
        self.overzicht.addItem(self.venster)
        self.venster.sigRegionChanged.connect(lambda: self.detail.setXRange(*self.venster.getRegion(), padding=0))
        self.detail.sigXRangeChanged.connect(self._x_veranderd)
        self.selectie = pg.LinearRegionItem(brush=pg.mkBrush(255, 152, 6, 60), pen=pg.mkPen(ORANJE, width=2))
        self.selectie.setZValue(10)
        self.detail.addItem(self.selectie)
        self.selectie.sigRegionChanged.connect(self._toon_selectie)
        self.legenda = QLabel("Sleep het oranje venster in het overzicht om door de opname te gaan, of zoom met het "
                              "muiswiel in het detail. Sleep de oranje selectie over het stuk dat je wilt annoteren. "
                              "<b>Ctrl+R</b>: beginweergave · <b>Shift+←/→</b>: venster terug/verder.")
        self.legenda.setWordWrap(True)
        kleur = lambda c, t: f"<span style='background:{c}'>&nbsp;&nbsp;&nbsp;</span> {t}"  # noqa: E731
        self.uc1_legenda = QLabel("UC-1 · activiteit: " + " ".join(kleur(UC1_KLEUREN[k], k) for k in (
            "rust", "beweging", "lopen", "onbekend")) + " · houding: " + " ".join(
            kleur(UC1_KLEUREN[k], k) for k in ("rechtop", "liggend", "onbekend")))
        tips((self.filter, hulp.FILTER), (self.toon_acc, hulp.ACC), (self.toon_gyro, hulp.GYRO),
             (self.uc1_legenda, hulp.BEWEGING))
        self.hover = QLabel(" ")
        self.hover.setStyleSheet(f"color:{SUBTIEL}")
        self.grafiek.scene().sigMouseMoved.connect(self._hover)
        for toets, actie in (("Ctrl+R", self._beginweergave), ("Shift+Left", lambda: self._verschuif(-1)),
                             ("Shift+Right", lambda: self._verschuif(1))):
            QShortcut(QKeySequence(toets), self, actie)

        boven = QWidget()
        b = QVBoxLayout(boven)
        b.setContentsMargins(0, 0, 0, 0)
        b.addLayout(filters)
        b.addLayout(balk)
        b.addWidget(self.legenda)
        b.addWidget(self.uc1_legenda)
        b.addWidget(self.grafiek, 1)
        b.addWidget(self.hover)

        onder = QSplitter()
        self.lijst = tabel(["Soort", "Label", "Begin", "Eind", "Duur (s)", "Plaatsing", "Beoordeling", "Opmerking"])
        self.lijst.setSortingEnabled(False)
        self.lijst.itemSelectionChanged.connect(self._kies_annotatie)
        onder.addWidget(self.lijst)
        onder.addWidget(self._bewerk_paneel())
        onder.setSizes([650, 500])

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(boven)
        splitter.addWidget(onder)
        splitter.setSizes([560, 330])
        QVBoxLayout(self).addWidget(splitter)
        self._geladen: str | None = None  # pas laden als het scherm geopend wordt: opstarten blijft snel

    def _bewerk_paneel(self) -> QWidget:
        paneel = QWidget()
        v = QVBoxLayout(paneel)
        self.selectie_tekst = QLabel()
        v.addWidget(self.selectie_tekst)
        vorm = QFormLayout()
        self.label = QComboBox()
        self.label.setEditable(True)
        self.label.addItems(lees_lijst("activiteiten"))
        self.plaatsing, self.opmerking = QLineEdit(), QLineEdit()
        self.beoordeling = QComboBox()
        for b in BEOORDELINGEN:
            self.beoordeling.addItem(b or "—", b)
        self.toelichting = QPlainTextEdit()
        self.toelichting.setMaximumHeight(50)
        vorm.addRow("Label", self.label)
        vorm.addRow("Plaatsing", self.plaatsing)
        vorm.addRow("Opmerking", self.opmerking)
        vorm.addRow("Beoordeling signaal", self.beoordeling)
        vorm.addRow("Toelichting", self.toelichting)
        v.addLayout(vorm)
        tips((self.label, hulp.LABEL), (self.plaatsing, hulp.PLAATSING), (self.opmerking, hulp.OPMERKING),
             (self.beoordeling, hulp.BEOORDELING), (self.toelichting, hulp.TOELICHTING))
        self.nieuw_paneel = QWidget()
        n = QVBoxLayout(self.nieuw_paneel)
        n.setContentsMargins(0, 0, 0, 0)
        n.addWidget(QLabel("<b>Nieuwe periode over de selectie</b> · klik op een label:"))
        raster = QGridLayout()
        for i, label in enumerate(lees_lijst("activiteiten")):
            k = QPushButton(label)
            k.clicked.connect(lambda _=False, l=label: self._nieuw("periode", l))
            raster.addWidget(k, i // 3, i % 3)
        n.addLayout(raster)
        rij = QHBoxLayout()
        for tekst, actie in (("Periode met label hierboven", lambda: self._nieuw("periode", self.label.currentText())),
                             ("Moment op begin selectie", lambda: self._nieuw("moment", self.label.currentText()))):
            k = QPushButton(tekst)
            k.clicked.connect(actie)
            rij.addWidget(k)
        n.addLayout(rij)
        v.addWidget(self.nieuw_paneel)
        self.bewerk_knoppen = QWidget()
        rij = QHBoxLayout(self.bewerk_knoppen)
        rij.setContentsMargins(0, 0, 0, 0)
        for tekst, actie in (("Wijzigingen opslaan", self._opslaan), ("Verwijderen", self._verwijder),
                             ("Nieuwe annotatie", self._deselecteer)):
            k = QPushButton(tekst)
            k.clicked.connect(actie)
            rij.addWidget(k)
        v.addWidget(self.bewerk_knoppen)
        v.addStretch()
        return paneel

    # --- laden en tekenen ---

    def ververs(self) -> None:
        """Bij het openen van het scherm: lijst bijwerken, en de gekozen opname laden als die nog niet geladen is."""
        self._vul_filters()
        deelnemer, datum, bevestiging = (self.f_deelnemer.currentData(), self.f_datum.currentData(),
                                         self.f_bevestiging.currentIndex())
        vul_opnames(self.keuze, alleen_met_data=True, filter=lambda o: (
            (deelnemer is None or o.info.deelnemer_id == deelnemer)
            and (datum is None or o.info.gestart[:10] == datum)
            and (bevestiging == 0 or self.f_bevestiging.currentText() in o.info.elektroden.lower())))
        if self.keuze.currentData() != self._geladen:
            self._laad()

    def na_wijziging(self) -> None:
        """Na ongedaan maken / opnieuw doen: annotaties opnieuw lezen; de weergave blijft staan."""
        if self.opname is None:
            return
        try:
            self.opname = Opname.laad(self.opname.map)
        except FileNotFoundError:  # de opname zelf is ongedaan gemaakt
            self.opname, self._geladen = None, None
            self.ververs()
            return
        self.gekozen_id = None
        self._vul_lijst()

    def _vul_filters(self) -> None:
        """Keuzes in de filters uit de opnames die er zijn; de huidige keuze blijft staan."""
        opnames = [o for o in Opname.alle(DATA_ROOT) if o.heeft_signalen]
        namen = {d.id: d.weergave for d in Deelnemers(DATA_ROOT).alle()}
        for f, alle, waarden in ((self.f_deelnemer, "Alle deelnemers",
                                  [(namen.get(i, i), i) for i in sorted({o.info.deelnemer_id for o in opnames})]),
                                 (self.f_datum, "Alle datums",
                                  [(pd.Timestamp(d).strftime("%d-%m-%Y"), d)
                                   for d in sorted({o.info.gestart[:10] for o in opnames}, reverse=True)])):
            huidig = f.currentData()
            f.blockSignals(True)
            f.clear()
            f.addItem(alle, None)
            for tekst, data in waarden:
                f.addItem(tekst, data)
            f.setCurrentIndex(max(f.findData(huidig), 0))
            f.blockSignals(False)

    def open_opname(self, map: str) -> None:
        for f in (self.f_deelnemer, self.f_datum, self.f_bevestiging):  # filters los, zodat de opname erin staat
            f.blockSignals(True)
            f.setCurrentIndex(0)
            f.blockSignals(False)
        self._vul_filters()
        vul_opnames(self.keuze, alleen_met_data=True)
        self.keuze.setCurrentIndex(max(self.keuze.findData(map), 0))
        self._laad()

    @bezig
    def _laad(self) -> None:
        map = self.keuze.currentData()
        self._geladen = map
        self.opname = Opname.laad(map) if map else None
        self.signalen = self.opname.laad_signalen() if self.opname else {}
        self._ecg, self._gefilterd, self._segmenten = None, {}, None
        if self.opname is not None:
            self.bevestiging.blockSignals(True)
            self.bevestiging.setCurrentText("lanyard" if "lanyard" in self.opname.info.elektroden.lower() else "sticker")
            self.bevestiging.blockSignals(False)
        self.overzicht.clear()
        self._overzicht_items = []
        self.overzicht.addItem(self.venster)
        if not self.signalen:
            self.detail.clear()
            self._vul_lijst()
            return
        ecg = self.signalen.get("ecg")
        if ecg is not None:
            # Tijd uit de originele kolom (zes_leads maakt er objecten van); 1 kanaal heet hier gewoon "I".
            df = (zes_leads(ecg.data) if {"Ecg1", "Ecg2"} <= set(ecg.kanalen)
                  else ecg.data.rename(columns={ecg.kanalen[0]: "I"}))
            self._ecg = (epoch(ecg.data["tijd"]), df, ecg.fs, ecg.eenheden.get(ecg.kanalen[0], ""))
            self._gefilterd = {"I": ecg_filter(df["I"].to_numpy(dtype=float), ecg.fs)}  # zonder basislijndrift
            lijn = self.overzicht.plot(self._ecg[0], self._gefilterd["I"], pen=pg.mkPen(PRIMAIR))
        else:
            eerste = next(iter(self.signalen.values()))
            lijn = self.overzicht.plot(epoch(eerste.data["tijd"]), eerste.data[eerste.kanalen[0]].to_numpy(dtype=float),
                                       pen=pg.mkPen(PRIMAIR))
        lijn.setDownsampling(auto=True, method="peak")
        lijn.setClipToView(True)
        self._bereik = (lijn.xData[0], lijn.xData[-1])
        self.overzicht.setYRange(*robuust_bereik(lijn.yData), padding=0)  # uitschieters niet bepalend
        self.venster.setBounds(self._bereik)
        self._teken_beweging()
        self._teken_beweging_rijen()
        self._vul_lijst()
        self._beginweergave()

    def _beginweergave(self) -> None:
        """Wat je ziet bij het openen van een opname (Ctrl+R): het hele overzicht, en 10 s in het detail vanaf 5 s:
        in de eerste seconden zwaaien de recorder en het filter nog uit."""
        if not self.signalen:
            return
        x0, x1 = self._bereik
        self.overzicht.setXRange(x0, x1, padding=0.01)
        begin = x0 + BEGIN_S if x1 - x0 > BEGIN_S + VENSTER_S else x0
        self.venster.setRegion((begin, min(begin + VENSTER_S, x1)))
        self._deselecteer()

    def _verschuif(self, richting: int) -> None:
        """Shift+←/→: het venster één vensterbreedte terug of verder, binnen de opname."""
        if not self.signalen:
            return
        a, b = self.venster.getRegion()
        stap = richting * (b - a)
        stap = max(self._bereik[0] - a, min(stap, self._bereik[1] - b))
        self.venster.setRegion((a + stap, b + stap))

    def _x_veranderd(self) -> None:
        """Detail ingezoomd of verschoven: venster in het overzicht volgt, y-as op wat er nu in beeld is."""
        x0, x1 = self.detail.getViewBox().viewRange()[0]
        self.venster.setRegion((x0, x1))
        self._markeer_in_beeld(x0, x1)
        if self._ecg is None:
            return
        x = self._ecg[0]
        i0, i1 = np.searchsorted(x, [x0, x1])
        stukken = [y[i0:i1] for y in self._getekend]
        if stukken and sum(map(len, stukken)):
            self.detail.setYRange(*robuust_bereik(np.concatenate(stukken)), padding=0)

    def _toon_beweging_rij(self, plot, aan: bool) -> None:
        plot.setVisible(aan)
        if aan:
            plot.setXRange(*self.detail.getViewBox().viewRange()[0], padding=0)

    def _teken_beweging_rijen(self) -> None:
        for plot, naam in ((self.acc_plot, "acc"), (self.gyro_plot, "gyro")):
            plot.clear()
            sig = self.signalen.get(naam)
            if sig is None:
                continue
            x = epoch(sig.data["tijd"])
            kanalen = list(sig.kanalen[:3])
            for i, k in enumerate(kanalen):
                lijn = plot.plot(x, sig.data[k].to_numpy(dtype=float), pen=pg.mkPen(GRAFIEK[i], width=1), name=k)
                lijn.setDownsampling(auto=True, method="peak")
                lijn.setClipToView(True)
            lijn = plot.plot(x, magnitude(sig.data, kanalen), pen=pg.mkPen(TEKST, width=1), name=f"|{naam}|")
            lijn.setDownsampling(auto=True, method="peak")
            lijn.setClipToView(True)

    def _teken_detail(self) -> None:
        bereik = self.detail.getViewBox().viewRange()[0]
        self.detail.clear()
        self.detail.addItem(self.selectie)
        self._getekend = []
        if self._ecg is None:
            return
        x, df, fs, eenheid = self._ecg
        kleuren = iter(PALET)
        for k, vak in self.leads.items():
            if not vak.isChecked() or k not in df:
                continue
            if self.filter.isChecked():
                if k not in self._gefilterd:
                    self._gefilterd[k] = ecg_filter(df[k].to_numpy(dtype=float), fs)
                y = self._gefilterd[k]
            else:
                y = df[k].to_numpy(dtype=float)
            lijn = self.detail.plot(x, y, pen=pg.mkPen(next(kleuren), width=1), name=k)
            lijn.setDownsampling(auto=True, method="peak")
            lijn.setClipToView(True)
            self._getekend.append(y)
        self.detail.setLabel("left", "ECG", eenheid)
        self._teken_annotaties()
        self.detail.setXRange(*bereik, padding=0)
        self._x_veranderd()

    def _teken_beweging(self) -> None:
        self.beweging_plot.clear()
        if "acc" not in self.signalen:
            return
        acc, gyro = self.signalen["acc"], self.signalen.get("gyro")
        s = beweging_per_segment(acc.data, gyro.data if gyro else None, acc.fs, self.bevestiging.currentText())
        if s.empty:
            return
        x0, breedte = epoch(s["start"]), (s["eind"] - s["start"]).dt.total_seconds().to_numpy()
        self._segmenten = (x0, s)
        for kolom, y0 in (("activiteit", 1.05), ("houding", 0.05)):
            self.beweging_plot.addItem(pg.BarGraphItem(
                x0=x0, width=breedte, y0=y0, height=0.9, pen=pg.mkPen(None),
                brushes=[pg.mkBrush(UC1_KLEUREN[w]) for w in s[kolom]],
            ))
        self.beweging_plot.setYRange(0, 2, padding=0)

    def _hover(self, positie) -> None:
        """Onder de plot: tijd, en boven de UC-1-balk ook activiteit, houding en de kenmerken van dat segment."""
        for plot in (self.beweging_plot, self.detail, self.acc_plot, self.gyro_plot, self.overzicht):
            if plot.isVisible() and plot.sceneBoundingRect().contains(positie):
                t = plot.getViewBox().mapSceneToView(positie).x()
                break
        else:
            return
        tekst = klok(pd.Timestamp(t, unit="s", tz="UTC"), True)
        if self._segmenten is not None and plot is self.beweging_plot:
            x0, s = self._segmenten
            i = int(np.searchsorted(x0, t, side="right")) - 1
            if 0 <= i < len(s) and t < x0[i] + 20:
                r = s.iloc[i]
                tekst += (f" · <b>activiteit: {r['activiteit']}</b> · <b>houding: {r['houding']}</b> · "
                          f"sd |acc| {r['acc_sd']:.3f} g · kanteling {r['kanteling']:.0f}°")
        self.hover.setText(tekst)

    def _teken_annotaties(self) -> None:
        o = self.opname
        for item in self._overzicht_items:
            self.overzicht.removeItem(item)
        self._overzicht_items = []
        perioden = sorted({a.label for a in o.annotaties if a.soort == "periode"})
        kleur = {label: PALET[i % len(PALET)] for i, label in enumerate(perioden)}
        for plot in (self.overzicht, self.detail):
            for a in o.chronologisch():
                start, eind = o.in_datatijd(a)
                if a.soort == "periode" and eind is not None:
                    c = QColor(kleur[a.label])
                    c.setAlpha(110 if a.id == self.gekozen_id else 45)
                    item = pg.LinearRegionItem((epoch(start), epoch(eind)), movable=False, brush=pg.mkBrush(c),
                                               pen=pg.mkPen(None))
                    item.setZValue(-10)
                else:
                    stijl = pg.mkPen(ORANJE, style=Qt.PenStyle.DashLine) if a.soort == "sync" else pg.mkPen("#8A4B00")
                    item = pg.InfiniteLine(epoch(start), pen=stijl)
                plot.addItem(item)
                if plot is self.detail:
                    tekst = pg.TextItem(a.label, color=TEKST, anchor=(0, 0))
                    tekst.setPos(epoch(start), self.detail.getViewBox().viewRange()[1][1])
                    plot.addItem(tekst)
                else:
                    self._overzicht_items.append(item)

    def _vul_lijst(self) -> None:
        o = self.opname
        self._ids, self._tijden, self._in_beeld = [], [], None
        rijen = []
        if o is not None:
            for a in o.chronologisch():
                start, eind = o.in_datatijd(a)
                self._tijden.append((epoch(start), epoch(eind if eind is not None else start)))
                rijen.append([a.soort, a.label, klok(start, True), klok(eind, True) if eind is not None else "",
                              f"{a.duur_s:.1f}" if a.duur_s is not None else "", a.plaatsing, a.beoordeling,
                              a.opmerking])
                self._ids.append(a.id)
        self.lijst.blockSignals(True)
        vul(self.lijst, rijen, self._ids)
        self.lijst.blockSignals(False)
        self._teken_detail()  # tekent ook de annotaties opnieuw, in detail en overzicht

    def _markeer_in_beeld(self, x0: float, x1: float) -> None:
        """Rijen van annotaties die in het venster vallen lichtoranje (de kleur van het venster), en de tabel naar de
        eerste daarvan scrollen. Alleen als de set verandert: slepen blijft zo vlot."""
        in_beeld = {r for r, (a, b) in enumerate(self._tijden) if a <= x1 and b >= x0}
        if in_beeld == self._in_beeld:
            return
        self._in_beeld = in_beeld
        for r in range(self.lijst.rowCount()):
            kleur = IN_BEELD if r in in_beeld else QBrush()
            for k in range(self.lijst.columnCount()):
                self.lijst.item(r, k).setBackground(kleur)
        if in_beeld:
            self.lijst.scrollToItem(self.lijst.item(min(in_beeld), 0), QAbstractItemView.ScrollHint.PositionAtTop)

    # --- selectie en annotaties ---

    def _toon_selectie(self) -> None:
        a, b = self.selectie.getRegion()
        t0, t1 = pd.Timestamp(a, unit="s", tz="UTC"), pd.Timestamp(b, unit="s", tz="UTC")
        wat = "Gekozen annotatie" if self.gekozen_id is not None else "Selectie"
        self.selectie_tekst.setText(f"<b>{wat}:</b> {klok(t0, True)} – {klok(t1, True)} ({b - a:.1f} s)")

    def _selectie_tijden(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        a, b = self.selectie.getRegion()
        return pd.Timestamp(a, unit="s", tz="UTC"), pd.Timestamp(b, unit="s", tz="UTC")

    def _deselecteer(self) -> None:
        self.gekozen_id = None
        self.lijst.clearSelection()
        a, b = self.venster.getRegion()
        self.selectie.setRegion((a + (b - a) / 3, a + 2 * (b - a) / 3))
        self.opmerking.clear()
        self.toelichting.clear()
        self.beoordeling.setCurrentIndex(0)
        if self.opname is not None:
            self.plaatsing.setText(self.opname.laatste_plaatsing)
        self.nieuw_paneel.show()
        self.bewerk_knoppen.hide()
        self._toon_selectie()

    def _kies_annotatie(self) -> None:
        id = gekozen(self.lijst)
        if id is None or self.opname is None:
            return
        self.gekozen_id = id
        a = self.opname.zoek(id)
        start, eind = self.opname.in_datatijd(a)
        s0, s1 = epoch(start), epoch(eind if eind is not None else start)
        marge = max(5.0, 0.2 * (s1 - s0))
        self.venster.setRegion((s0 - marge, s1 + marge))
        self.selectie.setRegion((s0, s1))
        self.label.setCurrentText(a.label)
        self.plaatsing.setText(a.plaatsing)
        self.opmerking.setText(a.opmerking)
        self.beoordeling.setCurrentIndex(max(self.beoordeling.findData(a.beoordeling), 0))
        self.toelichting.setPlainText(a.beoordeling_opmerking)
        self.nieuw_paneel.hide()
        self.bewerk_knoppen.show()
        self._teken_detail()
        self._toon_selectie()

    def _nieuw(self, soort: str, label: str) -> None:
        if self.opname is None:
            return
        t0, t1 = self._selectie_tijden()
        try:
            self.opname.voeg_toe(soort, label, t0, t1 if soort == "periode" else None, tijdbasis="data",
                                 opmerking=self.opmerking.text().strip(), plaatsing=self.plaatsing.text().strip())
        except ValueError as e:
            fout(self, str(e))
            return
        self.opname = Opname.laad(self.opname.map)
        self._vul_lijst()
        # Selectie direct na de nieuwe periode: zo annoteer je snel achter elkaar.
        self.selectie.setRegion((epoch(t1), epoch(t1) + (epoch(t1) - epoch(t0))))

    def _opslaan(self) -> None:
        o, id = self.opname, self.gekozen_id
        if o is None or id is None:
            return
        a = o.zoek(id)
        t0, t1 = self._selectie_tijden()
        # Terug naar de tijdbasis van de annotatie: live (pc) annotaties staan in pc-tijd.
        correctie = pd.Timedelta(seconds=0 if a.tijdbasis == "data" else (o.info.klokcorrectie_s or 0.0))
        try:
            o.wijzig(id, label=self.label.currentText().strip() or a.label, plaatsing=self.plaatsing.text().strip(),
                     opmerking=self.opmerking.text().strip(), beoordeling=self.beoordeling.currentData(),
                     beoordeling_opmerking=self.toelichting.toPlainText().strip(), t_start=t0 - correctie,
                     t_eind=(t1 - correctie) if a.t_eind is not None else None)
        except ValueError as e:
            fout(self, str(e))
            return
        self.opname = Opname.laad(o.map)
        self._vul_lijst()
        self._herselecteer(id)

    def _herselecteer(self, id: int) -> None:
        for r in range(self.lijst.rowCount()):
            if self.lijst.item(r, 0).data(256) == id:
                self.lijst.selectRow(r)

    def _verwijder(self) -> None:
        if self.opname is None or self.gekozen_id is None:
            return
        a = self.opname.zoek(self.gekozen_id)
        if zeker(self, f"Annotatie '{a.label}' ({a.soort}) verwijderen?"):
            self.opname.verwijder([a.id])
            self.opname = Opname.laad(self.opname.map)
            self._vul_lijst()
            self._deselecteer()
