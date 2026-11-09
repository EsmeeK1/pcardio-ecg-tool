"""Eén datamap op OneDrive (of een andere gedeelde map) voor meerdere computers, één computer tegelijk.

SQLite in een map die OneDrive synchroniseert is riskant: OneDrive kan een half geschreven database uploaden of
conflictkopieën maken. Daarom:

- de app werkt met een **lokale werkkopie** van de database (``ECG_TOOL_DB``); de opnamemappen (ruwe data, signalen,
  exports) staan wél direct in de gedeelde map, die worden maar één keer geschreven;
- ``publiceer`` zet de werkkopie in één keer in de gedeelde map (tijdelijk bestand, dan hernoemen): bij afsluiten en
  af en toe tussendoor;
- een **slotbestand** in de gedeelde map zegt welke computer de data gebruikt. Bij vrijgeven staat de vingerafdruk
  (sha256) van de gepubliceerde database erin; een andere computer begint pas als OneDrive die versie binnen heeft.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SLOT = "ecg-slot.json"
DATABASE = "ecg.db"


@dataclass
class Status:
    soort: str  # "ok", "in_gebruik" (andere computer) of "wacht_op_sync" (OneDrive heeft de laatste versie nog niet)
    computer: str = ""
    sinds: str = ""


def computernaam() -> str:
    return platform.node() or "onbekend"


def lees_slot(map: Path) -> dict | None:
    try:
        return json.loads((Path(map) / SLOT).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):  # geen slot, of een half gesynchroniseerd bestand
        return None


def controleer(map: Path) -> Status:
    """Mag deze computer de gedeelde data nu openen?"""
    slot = lees_slot(map)
    if slot is None:
        return Status("ok")
    if slot.get("status") == "in gebruik" and slot.get("computer") != computernaam():
        return Status("in_gebruik", slot.get("computer", "?"), slot.get("sinds", "?"))
    if slot.get("status") == "vrij" and slot.get("sha") and slot["sha"] != _sha(Path(map) / DATABASE):
        return Status("wacht_op_sync", slot.get("computer", "?"), slot.get("sinds", "?"))
    return Status("ok")


def open_gedeeld(map: Path, lokaal: Path) -> None:
    """Werkkopie klaarzetten en het slot nemen. Na ``controleer`` (of bewust overnemen).

    Was deze computer de laatste gebruiker en is het slot nooit vrijgegeven (crash), dan is de werkkopie het nieuwst:
    die blijft staan en wordt meteen gepubliceerd. Anders wordt de gedeelde database de werkkopie.
    """
    map, lokaal = Path(map), Path(lokaal)
    slot = lees_slot(map)
    eigen_crash = slot and slot.get("status") == "in gebruik" and slot.get("computer") == computernaam()
    gedeeld = map / DATABASE
    lokaal.parent.mkdir(parents=True, exist_ok=True)
    if eigen_crash and lokaal.exists():
        publiceer(map, lokaal, vrijgeven=False)
        return
    if gedeeld.exists():
        _kopieer(gedeeld, lokaal)
    _schrijf_slot(map, "in gebruik", _sha(gedeeld))


def publiceer(map: Path, lokaal: Path, vrijgeven: bool) -> None:
    """Werkkopie in één keer naar de gedeelde map; met ``vrijgeven`` daarna het slot vrij (met vingerafdruk)."""
    map, lokaal = Path(map), Path(lokaal)
    gedeeld = map / DATABASE
    if lokaal.exists():
        tmp = map / f"{DATABASE}.{computernaam()}.tmp"
        _kopieer(lokaal, tmp)
        os.replace(tmp, gedeeld)
    _schrijf_slot(map, "vrij" if vrijgeven else "in gebruik", _sha(gedeeld))


def _kopieer(bron: Path, doel: Path) -> None:
    """Consistente kopie via de backup-API van SQLite (ook als de bron net open is)."""
    tmp = doel.with_name(doel.name + ".kopie")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(bron.resolve().as_uri() + "?mode=ro", uri=True)) as b, \
            closing(sqlite3.connect(tmp)) as d:
        b.backup(d)
    os.replace(tmp, doel)


def _schrijf_slot(map: Path, status: str, sha: str | None) -> None:
    inhoud = {"status": status, "computer": computernaam(), "sinds": datetime.now().astimezone().isoformat(
        timespec="seconds"), "sha": sha}
    tmp = Path(map) / f"{SLOT}.tmp"
    tmp.write_text(json.dumps(inhoud, indent=2), encoding="utf-8")
    os.replace(tmp, Path(map) / SLOT)


def _sha(pad: Path) -> str | None:
    return hashlib.sha256(pad.read_bytes()).hexdigest() if pad.exists() else None
