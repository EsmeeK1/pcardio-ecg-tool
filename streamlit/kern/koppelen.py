"""Bestanden inlezen en koppelen aan een opname: zonder UI, gedeeld door de Streamlit- en de desktop-app."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .export import bestandssoort, lees_export
from .opslag import Annotatie, Opname, lees_annotaties
from .pcardio import Signaal, combineer, lees_bestand
from .verwerking import overlap_fractie

SOORT_LABEL = {"pcardio": "P-Cardio-data", "export": "Export (volledig)", "annotaties": "Annotaties"}
OPNAME_ID = re.compile(r"\d{4}-\d{2}-\d{2}_\d{4}_D\d+")
GENEGEERD = ("log.txt", "config.txt")  # staan ook op de recorder, zijn geen data


@dataclass
class Ingelezen:
    signalen: dict[str, Signaal] = field(default_factory=dict)
    bestanden: list[Path] = field(default_factory=list)  # databestanden (voor ruw/)
    soorten: dict[str, str] = field(default_factory=dict)  # bestandsnaam -> soort
    annotaties: dict | None = None  # {"bestand", "lijst", "klokcorrectie_s"}
    opname_id: str | None = None  # uit de bestandsnamen
    meldingen: list[str] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)


def bestanden_in_map(map: Path) -> list[Path]:
    return sorted(
        p for p in map.iterdir() if p.suffix.lower() in (".csv", ".txt", ".zip") and p.name not in GENEGEERD
    )


def pak_uit(zip_pad: Path, doel_map: Path) -> list[Path]:
    """Alleen .csv/.txt, plat in ``doel_map`` (mappen in de zip, ook ``../``, worden genegeerd)."""
    doel_map.mkdir(parents=True, exist_ok=True)
    paden = []
    with zipfile.ZipFile(zip_pad) as zf:
        for info in zf.infolist():
            naam = Path(info.filename).name
            if (
                info.is_dir()
                or "__MACOSX" in info.filename
                or Path(naam).suffix.lower() not in (".csv", ".txt")
                or naam in GENEGEERD
            ):
                continue
            doel = doel_map / naam
            doel.write_bytes(zf.read(info))
            paden.append(doel)
    return paden


def lees_in(paden: list[Path], uitpak_map: Path) -> Ingelezen:
    """Herken en lees P-Cardio-bestanden, een export en/of een annotatiebestand. Zips worden in ``uitpak_map``
    uitgepakt. Fouten per bestand komen in ``fouten``; de rest wordt wel ingelezen."""
    r = Ingelezen()
    signalen: list[Signaal] = []
    uitgepakt: list[Path] = []
    for pad in paden:
        if pad.suffix.lower() != ".zip":
            uitgepakt.append(pad)
            continue
        try:
            uitgepakt.extend(pak_uit(pad, uitpak_map))
        except zipfile.BadZipFile:
            r.fouten.append(f"{pad.name}: geen geldig zip-bestand.")
    for pad in uitgepakt:
        try:
            soort = bestandssoort(pad)
            if soort == "annotaties":
                if r.annotaties is not None:
                    r.fouten.append(f"Meerdere annotatiebestanden ({r.annotaties['bestand']} en {pad.name}). Kies er één.")
                    continue
                lijst, correctie = lees_annotaties(pad)
                r.annotaties = {"bestand": pad.name, "lijst": lijst, "klokcorrectie_s": correctie}
            else:
                gelezen, extra = (lees_export(pad), []) if soort == "export" else lees_bestand(pad)
                signalen.extend(gelezen)
                r.bestanden.append(pad)
                r.meldingen.extend(f"{pad.name}: {m}" for m in extra)
            r.soorten[pad.name] = soort
        except (ValueError, KeyError, FileNotFoundError) as fout:
            r.fouten.append(f"{pad.name}: {fout}")
    if {"export", "pcardio"} <= set(r.soorten.values()):
        r.fouten.append("Kies één bron: ruwe P-Cardio-bestanden óf een export, niet allebei.")
        signalen, r.bestanden = [], []
    elif "export" in r.soorten.values() and r.annotaties is None:
        r.meldingen.append(
            "Export zonder annotatiebestand: alleen de data wordt ingelezen. Voeg het bijbehorende "
            "`…_annotaties.csv` toe om ook de annotaties en de klokcorrectie terug te zetten.",
        )
    try:
        r.signalen = combineer(signalen)
    except ValueError as fout:
        r.fouten.append(str(fout))
    gevonden = OPNAME_ID.search(" ".join(r.soorten))
    r.opname_id = gevonden.group(0) if gevonden else None
    return r


def voorstellen(signalen: dict[str, Signaal], opnames: list[Opname]) -> list[tuple[Opname, float]]:
    """Opnames waarvan de live annotaties binnen de tijdspanne van de data vallen, beste eerst."""
    d0 = min(s.start for s in signalen.values())
    d1 = max(s.eind for s in signalen.values())
    scores = []
    for opname in opnames:
        bereik = opname.annotatie_bereik
        if bereik is None:
            continue
        correctie = pd.Timedelta(seconds=opname.info.klokcorrectie_s or 0.0)
        score = overlap_fractie(bereik[0] + correctie, bereik[1] + correctie, d0, d1)
        if score > 0:
            scores.append((opname, score))
    return sorted(scores, key=lambda x: -x[1])


def binnen_data(annotaties: list[Annotatie], correctie_s: float, signalen: dict[str, Signaal]) -> int:
    """Aantal annotaties waarvan het begin (in P-Cardio-tijd) binnen de data valt."""
    d0 = min(s.start for s in signalen.values())
    d1 = max(s.eind for s in signalen.values())
    correctie = pd.Timedelta(seconds=correctie_s)
    return sum(d0 <= a.t_start + (correctie if a.tijdbasis == "pc" else pd.Timedelta(0)) <= d1 for a in annotaties)
