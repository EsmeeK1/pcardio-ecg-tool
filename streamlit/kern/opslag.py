"""Opslag van deelnemers, opnames, annotaties en signalen in ``streamlit/data/``.

Structuur::

    data/
    ├── deelnemers.csv
    └── opnames/<YYYY-MM-DD_HHMM>_<deelnemer-id>/
        ├── opname.json          metadata + klokcorrectie
        ├── annotaties.csv       perioden, momenten en sync-momenten
        ├── ruw/                 kopie van de ingeladen P-Cardio-bestanden
        ├── signalen/            ingelezen signalen (parquet, snel te laden)
        └── export/              gecombineerde exports

Elke wijziging wordt direct weggeschreven (via een tijdelijk bestand, zodat een crash geen half bestand
achterlaat).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

import pandas as pd

from .pcardio import Signaal

# Standaard streamlit/data/; ECG_TOOL_DATA wijst een andere map aan (bijv. voor tests).
DATA_ROOT = Path(os.environ.get("ECG_TOOL_DATA") or Path(__file__).resolve().parents[1] / "data")
WEERGAVE_TZ = "Europe/Amsterdam"

GESLACHTEN = ["man", "vrouw", "anders", "onbekend"]
SOORTEN = ("periode", "moment", "sync")
TIJDBASES = ("pc", "data")
BEOORDELINGEN = ["", "schoon", "ruis, QRS herkenbaar", "onbruikbaar"]


def nu() -> datetime:
    """Huidige lokale tijd mét tijdzone."""
    return datetime.now().astimezone()


def iso(tijd: datetime | pd.Timestamp) -> str:
    return tijd.isoformat(timespec="milliseconds")


def als_timestamp(tijd: datetime | pd.Timestamp | str) -> pd.Timestamp:
    """Naar een tz-aware ``pd.Timestamp`` in UTC."""
    ts = pd.Timestamp(tijd)
    if ts.tzinfo is None:
        raise ValueError(f"Tijd zonder tijdzone: {tijd!r}")
    return ts.tz_convert("UTC")


def _schrijf(pad: Path, inhoud: str) -> None:
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as bestand:
        bestand.write(inhoud)
    tmp.replace(pad)


# --- deelnemers --------------------------------------------------------------------------------------


@dataclass
class Deelnemer:
    id: str
    naam: str
    leeftijd: int | None
    geslacht: str
    hartdecompensatie: bool
    andere_aandoening: str = ""
    aangemaakt: str = ""

    @property
    def weergave(self) -> str:
        return f"{self.naam} ({self.id})"


class Deelnemers:
    def __init__(self, root: str | Path = DATA_ROOT) -> None:
        self.root = Path(root)

    def alle(self) -> list[Deelnemer]:
        if not self.pad.exists():
            return []
        df = pd.read_csv(self.pad, dtype=str, keep_default_na=False)
        return [
            Deelnemer(
                id=rij["id"],
                naam=rij["naam"],
                leeftijd=int(rij["leeftijd"]) if rij["leeftijd"] else None,
                geslacht=rij["geslacht"],
                hartdecompensatie=rij["hartdecompensatie"] == "ja",
                andere_aandoening=rij["andere_aandoening"],
                aangemaakt=rij["aangemaakt"],
            )
            for _, rij in df.iterrows()
        ]

    def toevoegen(
        self,
        naam: str,
        leeftijd: int | None,
        geslacht: str,
        hartdecompensatie: bool,
        andere_aandoening: str = "",
    ) -> Deelnemer:
        alle = self.alle()
        # Ook ID's van opnames meetellen: een verwijderde deelnemer mag zijn ID niet doorgeven aan een nieuwe.
        gebruikt = [d.id for d in alle] + [o.info.deelnemer_id for o in Opname.alle(self.root)]
        nummer = max((int(i[1:]) for i in gebruikt if i[1:].isdigit()), default=0) + 1
        deelnemer = Deelnemer(
            id=f"D{nummer:03d}",
            naam=naam,
            leeftijd=leeftijd,
            geslacht=geslacht,
            hartdecompensatie=hartdecompensatie,
            andere_aandoening=andere_aandoening,
            aangemaakt=iso(nu()),
        )
        self._valideer(deelnemer)
        self._schrijf_alle([*alle, deelnemer])
        return deelnemer

    def bijwerken(self, deelnemer: Deelnemer) -> None:
        self._valideer(deelnemer)
        alle = self.alle()
        if deelnemer.id not in {d.id for d in alle}:
            raise ValueError(f"Onbekende deelnemer '{deelnemer.id}'. Beschikbaar: {[d.id for d in alle]}")
        self._schrijf_alle([deelnemer if d.id == deelnemer.id else d for d in alle])

    def opnames(self, id: str) -> list[Opname]:
        return [o for o in Opname.alle(self.root) if o.info.deelnemer_id == id]

    def verwijder(self, id: str) -> None:
        """Alleen een deelnemer zonder opnames kan weg; opnames en annotaties blijven zo altijd herleidbaar."""
        alle = self.alle()
        if id not in {d.id for d in alle}:
            raise ValueError(f"Onbekende deelnemer '{id}'. Beschikbaar: {[d.id for d in alle]}")
        aantal = len(self.opnames(id))
        if aantal:
            raise ValueError(
                f"Deelnemer {id} heeft {aantal} opname(s) en kan daarom niet verwijderd worden. "
                f"Verwijder eerst de opnames (map `opnames/`) als dat echt de bedoeling is.",
            )
        self._schrijf_alle([d for d in alle if d.id != id])

    def _valideer(self, deelnemer: Deelnemer) -> None:
        if not deelnemer.naam.strip():
            raise ValueError("Vul een voornaam of patiënt-ID in.")
        if deelnemer.geslacht not in GESLACHTEN:
            raise ValueError(f"Onbekend geslacht '{deelnemer.geslacht}'. Beschikbaar: {GESLACHTEN}")
        if deelnemer.leeftijd is not None and not 0 <= deelnemer.leeftijd <= 120:
            raise ValueError(f"Ongeldige leeftijd: {deelnemer.leeftijd}")

    def _schrijf_alle(self, deelnemers: list[Deelnemer]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            [
                {
                    **asdict(d),
                    "leeftijd": "" if d.leeftijd is None else d.leeftijd,
                    "hartdecompensatie": "ja" if d.hartdecompensatie else "nee",
                }
                for d in deelnemers
            ],
            columns=[f.name for f in fields(Deelnemer)],
        )
        _schrijf(self.pad, df.to_csv(index=False))

    @property
    def pad(self) -> Path:
        return self.root / "deelnemers.csv"


# --- annotaties --------------------------------------------------------------------------------------


@dataclass
class Annotatie:
    id: int
    soort: str
    label: str
    t_start: pd.Timestamp
    t_eind: pd.Timestamp | None = None
    tijdbasis: str = "pc"
    opmerking: str = ""
    beoordeling: str = ""
    beoordeling_opmerking: str = ""
    plaatsing: str = ""  # experimentconditie per periode, bijv. "R3-Y3-G1-Z1"

    @property
    def duur_s(self) -> float | None:
        if self.t_eind is None:
            return None
        return (self.t_eind - self.t_start).total_seconds()


ANNOTATIE_KOLOMMEN = [f.name for f in fields(Annotatie)]


def _rij(a: Annotatie) -> dict[str, object]:
    """Annotatie als tabelrij, met de tijden als lokale ISO-tekst."""
    return {
        **asdict(a),
        "t_start": iso(a.t_start.tz_convert(WEERGAVE_TZ)),
        "t_eind": iso(a.t_eind.tz_convert(WEERGAVE_TZ)) if a.t_eind is not None else "",
    }


def lees_annotaties(pad: str | Path) -> tuple[list[Annotatie], float | None]:
    """Annotaties uit ``annotaties.csv`` of een annotatie-export.

    Een export heeft ook ``t_start_data``; het verschil met ``t_start`` van een live (pc) annotatie is de
    klokcorrectie die bij het exporteren gold. Zonder die kolom of zonder live annotaties: ``None``.
    """
    df = pd.read_csv(pad, dtype=str, keep_default_na=False)
    annotaties = [
        Annotatie(
            id=int(rij["id"]),
            soort=rij["soort"],
            label=rij["label"],
            t_start=als_timestamp(rij["t_start"]),
            t_eind=als_timestamp(rij["t_eind"]) if rij["t_eind"] else None,
            tijdbasis=rij["tijdbasis"],
            opmerking=rij["opmerking"],
            beoordeling=rij["beoordeling"],
            beoordeling_opmerking=rij["beoordeling_opmerking"],
            plaatsing=rij.get("plaatsing", ""),  # ontbreekt in bestanden van vóór oktober 2026
        )
        for _, rij in df.iterrows()
    ]
    live = df[df["tijdbasis"] == "pc"] if "t_start_data" in df else df.iloc[:0]
    correctie = None
    if len(live):
        verschil = als_timestamp(live["t_start_data"].iloc[0]) - als_timestamp(live["t_start"].iloc[0])
        correctie = round(verschil.total_seconds(), 3)
    return annotaties, correctie


# --- opnames -----------------------------------------------------------------------------------------


@dataclass
class OpnameInfo:
    id: str
    deelnemer_id: str
    gestart: str
    leeftijd_bij_opname: int | None = None
    elektroden: str = ""
    huidvoorbereiding: str = ""
    configuratie: str = ""
    pcardio_tijd_gelijkgezet: bool = False
    notities: str = ""
    experiment: str = ""  # geldt voor de hele opname, bijv. "Elektrodeplaatsing 21-10"
    live_afgesloten: bool = False
    klokcorrectie_s: float | None = None
    klokcorrectie_bron: str = ""
    bronbestanden: list[str] = field(default_factory=list)


class Opname:
    def __init__(self, map: str | Path, info: OpnameInfo, annotaties: list[Annotatie]) -> None:
        self.map = Path(map)
        self.info = info
        self.annotaties = annotaties

    @classmethod
    def nieuw(
        cls,
        deelnemer: Deelnemer,
        gestart: datetime | pd.Timestamp,
        root: str | Path = DATA_ROOT,
        **velden: object,
    ) -> Opname:
        lokaal = als_timestamp(gestart).tz_convert(WEERGAVE_TZ)
        id = f"{lokaal:%Y-%m-%d_%H%M}_{deelnemer.id}"
        map = Path(root) / "opnames" / id
        if map.exists():
            raise ValueError(f"Opname {id} bestaat al. Kies die opname, of wacht een minuut.")
        map.mkdir(parents=True)
        info = OpnameInfo(
            id=id,
            deelnemer_id=deelnemer.id,
            gestart=iso(lokaal),
            leeftijd_bij_opname=deelnemer.leeftijd,
            **velden,
        )
        opname = cls(map, info, [])
        opname._opslaan()
        return opname

    @classmethod
    def laad(cls, map: str | Path) -> Opname:
        map = Path(map)
        info_pad = map / "opname.json"
        if not info_pad.exists():
            raise FileNotFoundError(f"Geen opname.json in {map}")
        info = OpnameInfo(**json.loads(info_pad.read_text(encoding="utf-8")))
        pad = map / "annotaties.csv"
        annotaties = lees_annotaties(pad)[0] if pad.exists() else []
        return cls(map, info, annotaties)

    @staticmethod
    def alle(root: str | Path = DATA_ROOT) -> list[Opname]:
        map = Path(root) / "opnames"
        if not map.exists():
            return []
        return [
            Opname.laad(p)
            for p in sorted(map.iterdir(), reverse=True)
            if (p / "opname.json").exists()
        ]

    # --- annotaties ---

    def voeg_toe(
        self,
        soort: str,
        label: str,
        t_start: datetime | pd.Timestamp,
        t_eind: datetime | pd.Timestamp | None = None,
        tijdbasis: str = "pc",
        opmerking: str = "",
        plaatsing: str = "",
    ) -> Annotatie:
        if soort not in SOORTEN:
            raise ValueError(f"Onbekende soort '{soort}'. Beschikbaar: {list(SOORTEN)}")
        if tijdbasis not in TIJDBASES:
            raise ValueError(f"Onbekende tijdbasis '{tijdbasis}'. Beschikbaar: {list(TIJDBASES)}")
        if not label.strip():
            raise ValueError("Een annotatie heeft een label nodig.")
        annotatie = Annotatie(
            id=max((a.id for a in self.annotaties), default=0) + 1,
            soort=soort,
            label=label.strip(),
            t_start=als_timestamp(t_start),
            t_eind=als_timestamp(t_eind) if t_eind is not None else None,
            tijdbasis=tijdbasis,
            opmerking=opmerking,
            plaatsing=plaatsing.strip(),
        )
        self.annotaties.append(annotatie)
        self._opslaan()
        return annotatie

    def start_periode(self, label: str, plaatsing: str = "") -> Annotatie:
        """Live: start een periode; een lopende periode wordt op hetzelfde moment gestopt."""
        tijd = nu()
        if self.actieve_periode is not None:
            self.actieve_periode.t_eind = als_timestamp(tijd)
        return self.voeg_toe("periode", label, tijd, plaatsing=plaatsing)

    @property
    def laatste_plaatsing(self) -> str:
        """Plaatsing van de laatst gestarte periode: het live veld begint hiermee (ook na hervatten)."""
        perioden = [a for a in self.annotaties if a.soort == "periode"]
        return max(perioden, key=lambda a: a.id).plaatsing if perioden else ""

    def zet_experiment(self, experiment: str) -> None:
        self.info.experiment = experiment.strip()
        self._opslaan()

    def stop_periode(self) -> None:
        if self.actieve_periode is not None:
            self.actieve_periode.t_eind = als_timestamp(nu())
            self._opslaan()

    def moment(self, label: str, opmerking: str = "") -> Annotatie:
        return self.voeg_toe("moment", label, nu(), opmerking=opmerking)

    def sync(self) -> Annotatie:
        return self.voeg_toe("sync", "sync-sprong", nu())

    def sluit_live_af(self) -> None:
        self.stop_periode()
        self.info.live_afgesloten = True
        self._opslaan()

    def wijzig(self, id: int, **velden: object) -> Annotatie:
        annotatie = self.zoek(id)
        onbekend = set(velden) - set(ANNOTATIE_KOLOMMEN)
        if onbekend:
            raise ValueError(f"Onbekende velden {sorted(onbekend)}. Beschikbaar: {ANNOTATIE_KOLOMMEN}")
        for naam, waarde in velden.items():
            if naam in ("t_start", "t_eind") and waarde is not None:
                waarde = als_timestamp(waarde)
            setattr(annotatie, naam, waarde)
        if annotatie.t_eind is not None and annotatie.t_eind < annotatie.t_start:
            raise ValueError("Het eind van een periode ligt vóór het begin.")
        self._opslaan()
        return annotatie

    def verwijder(self, ids: list[int]) -> None:
        onbekend = set(ids) - {a.id for a in self.annotaties}
        if onbekend:
            raise ValueError(f"Onbekende annotatie-id's: {sorted(onbekend)}")
        self.annotaties = [a for a in self.annotaties if a.id not in ids]
        self._opslaan()

    def vervang_annotaties(self, annotaties: list[Annotatie], klokcorrectie_s: float | None) -> None:
        """Import: alle annotaties vervangen, en de klokcorrectie overnemen als die bekend is."""
        self.annotaties = list(annotaties)
        if klokcorrectie_s is not None:
            self.info.klokcorrectie_s = klokcorrectie_s
            self.info.klokcorrectie_bron = "geïmporteerd"
        self._opslaan()

    def zoek(self, id: int) -> Annotatie:
        for annotatie in self.annotaties:
            if annotatie.id == id:
                return annotatie
        raise ValueError(f"Onbekende annotatie-id {id}. Beschikbaar: {[a.id for a in self.annotaties]}")

    def chronologisch(self) -> list[Annotatie]:
        return sorted(self.annotaties, key=lambda a: (self.naar_datatijd(a.t_start, a.tijdbasis), a.id))

    # --- tijd ---

    def naar_datatijd(self, tijd: pd.Timestamp, tijdbasis: str) -> pd.Timestamp:
        """Pc-tijd (sessie-logger) -> P-Cardio-tijd, met de klokcorrectie. Datatijd blijft gelijk."""
        if tijdbasis == "data":
            return tijd
        return tijd + pd.Timedelta(seconds=self.info.klokcorrectie_s or 0.0)

    def in_datatijd(self, annotatie: Annotatie) -> tuple[pd.Timestamp, pd.Timestamp | None]:
        start = self.naar_datatijd(annotatie.t_start, annotatie.tijdbasis)
        eind = self.naar_datatijd(annotatie.t_eind, annotatie.tijdbasis) if annotatie.t_eind is not None else None
        return start, eind

    def zet_klokcorrectie(self, correctie_s: float | None, bron: str) -> None:
        self.info.klokcorrectie_s = correctie_s
        self.info.klokcorrectie_bron = bron
        self._opslaan()

    def annotaties_df(self) -> pd.DataFrame:
        """Alle annotaties, met de tijden zowel zoals gelogd als omgerekend naar P-Cardio-tijd."""
        rijen = []
        for a in self.chronologisch():
            start, eind = self.in_datatijd(a)
            rijen.append(
                {
                    **_rij(a),
                    "duur_s": round(a.duur_s, 1) if a.duur_s is not None else None,
                    "t_start_data": iso(start.tz_convert(WEERGAVE_TZ)),
                    "t_eind_data": iso(eind.tz_convert(WEERGAVE_TZ)) if eind is not None else "",
                },
            )
        return pd.DataFrame(
            rijen,
            columns=[*ANNOTATIE_KOLOMMEN, "duur_s", "t_start_data", "t_eind_data"],
        )

    # --- signalen ---

    def bewaar_signalen(self, signalen: dict[str, Signaal], bronbestanden: list[Path]) -> None:
        """Kopieer de ruwe bestanden naar ``ruw/`` en sla de ingelezen signalen op als parquet."""
        ruw = self.map / "ruw"
        ruw.mkdir(exist_ok=True)
        for bron in bronbestanden:
            doel = ruw / bron.name
            if bron.resolve() != doel.resolve():
                shutil.copy2(bron, doel)

        if self.signalen_map.exists():
            shutil.rmtree(self.signalen_map)
        self.signalen_map.mkdir()
        meta = {}
        for naam, signaal in signalen.items():
            signaal.data.to_parquet(self.signalen_map / f"{naam}.parquet", index=False)
            meta[naam] = {"eenheden": signaal.eenheden, "bron": signaal.bron}
        _schrijf(self.signalen_map / "signalen.json", json.dumps(meta, indent=2, ensure_ascii=False))

        self.info.bronbestanden = sorted(b.name for b in bronbestanden)
        self._opslaan()

    def laad_signalen(self) -> dict[str, Signaal]:
        meta_pad = self.signalen_map / "signalen.json"
        if not meta_pad.exists():
            return {}
        meta = json.loads(meta_pad.read_text(encoding="utf-8"))
        return {
            naam: Signaal(
                naam,
                pd.read_parquet(self.signalen_map / f"{naam}.parquet"),
                info["eenheden"],
                info["bron"],
            )
            for naam, info in meta.items()
        }

    def _opslaan(self) -> None:
        _schrijf(self.map / "opname.json", json.dumps(asdict(self.info), indent=2, ensure_ascii=False))
        df = pd.DataFrame(
            [_rij(a) for a in sorted(self.annotaties, key=lambda a: a.id)],
            columns=ANNOTATIE_KOLOMMEN,
        )
        _schrijf(self.map / "annotaties.csv", df.to_csv(index=False))

    @property
    def actieve_periode(self) -> Annotatie | None:
        """Live gestarte periode zonder eind."""
        open_ = [a for a in self.annotaties if a.soort == "periode" and a.tijdbasis == "pc" and a.t_eind is None]
        return open_[-1] if open_ else None

    @property
    def syncs(self) -> list[Annotatie]:
        return [a for a in self.chronologisch() if a.soort == "sync"]

    @property
    def signalen_map(self) -> Path:
        return self.map / "signalen"

    @property
    def heeft_signalen(self) -> bool:
        return (self.signalen_map / "signalen.json").exists()

    @property
    def annotatie_bereik(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Eerste en laatste tijdstip van de live (pc-tijd) annotaties."""
        tijden = [a.t_start for a in self.annotaties if a.tijdbasis == "pc"]
        tijden += [a.t_eind for a in self.annotaties if a.tijdbasis == "pc" and a.t_eind is not None]
        return (min(tijden), max(tijden)) if tijden else None
