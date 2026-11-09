"""Opslag van deelnemers, opnames, annotaties en signalen in ``streamlit/data/``.

Structuur::

    data/
    ├── ecg.db                   SQLite: deelnemers, opnames (metadata + klokcorrectie) en annotaties
    └── opnames/<YYYY-MM-DD_HHMM>_<deelnemer-id>/
        ├── ruw/                 kopie van de ingeladen P-Cardio-bestanden
        ├── signalen/            ingelezen signalen (parquet, snel te laden)
        └── export/              gecombineerde exports

Elke wijziging is één transactie: een crash laat geen half bijgewerkte opname achter. Bestaat ``ecg.db`` nog niet,
dan worden ``deelnemers.csv`` en per opname ``opname.json`` en ``annotaties.csv`` (het oude formaat) eenmalig
overgenomen. Die bestanden blijven staan, maar worden daarna niet meer gelezen of bijgewerkt.
"""

from __future__ import annotations

import contextvars
import functools
import json
import os
import shutil
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

import pandas as pd

from .pcardio import Signaal

# Standaard streamlit/data/; ECG_TOOL_DATA wijst een andere map aan (bijv. voor tests).
DATA_ROOT = Path(os.environ.get("ECG_TOOL_DATA") or Path(__file__).resolve().parents[1] / "data")
WEERGAVE_TZ = "Europe/Amsterdam"

GESLACHTEN = ["man", "vrouw", "anders", "onbekend"]
EERSTE_JAAR = 1900
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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS deelnemers (
    nummer INTEGER PRIMARY KEY AUTOINCREMENT,  -- nooit hergebruikt, ook niet na verwijderen
    id TEXT NOT NULL UNIQUE,
    naam TEXT NOT NULL,
    geboortejaar INTEGER,
    geslacht TEXT NOT NULL,
    hartdecompensatie INTEGER NOT NULL,
    andere_aandoening TEXT NOT NULL DEFAULT '',
    aangemaakt TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS opnames (
    id TEXT PRIMARY KEY,
    deelnemer_id TEXT NOT NULL REFERENCES deelnemers(id) ON DELETE RESTRICT,
    info TEXT NOT NULL  -- OpnameInfo als JSON: velden toevoegen vraagt geen migratie
);
CREATE TABLE IF NOT EXISTS annotaties (
    opname_id TEXT NOT NULL REFERENCES opnames(id) ON DELETE CASCADE,
    id INTEGER NOT NULL,
    soort TEXT NOT NULL,
    label TEXT NOT NULL,
    t_start TEXT NOT NULL,
    t_eind TEXT,
    tijdbasis TEXT NOT NULL,
    opmerking TEXT NOT NULL DEFAULT '',
    beoordeling TEXT NOT NULL DEFAULT '',
    beoordeling_opmerking TEXT NOT NULL DEFAULT '',
    plaatsing TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (opname_id, id)
);
"""


# ECG_TOOL_DB: werkkopie van de database elders (bijv. lokaal, terwijl de opnamemappen op OneDrive staan; zie
# kern.synchronisatie). Geldt alleen voor DATA_ROOT, niet voor andere mappen (tests).
_DB_ELDERS = os.environ.get("ECG_TOOL_DB")


def db_pad(root: str | Path = DATA_ROOT) -> Path:
    if _DB_ELDERS and Path(root).resolve() == DATA_ROOT.resolve():
        return Path(_DB_ELDERS)
    return Path(root) / "ecg.db"


@contextmanager
def _db(root: str | Path):
    """Verbinding met ``ecg.db`` als één transactie (commit aan het eind, rollback bij een fout)."""
    pad = db_pad(root)
    if not pad.exists():
        _maak_db(Path(root))
    with closing(sqlite3.connect(pad, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        if con.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSIE:
            _werk_schema_bij(con)
        with con:
            yield con


SCHEMA_VERSIE = 1  # 1: deelnemers.geboortejaar in plaats van leeftijd (9-11-2026)


def _werk_schema_bij(con: sqlite3.Connection) -> None:
    """Oudere database bijwerken. Versie 0 -> 1: leeftijd wordt geboortejaar (jaar van aanmaken − leeftijd)."""
    with con:
        kolommen = {r[1] for r in con.execute("PRAGMA table_info(deelnemers)")}
        if "leeftijd" in kolommen:
            con.execute("ALTER TABLE deelnemers RENAME COLUMN leeftijd TO geboortejaar")
            for nummer, leeftijd, aangemaakt in con.execute(
                    "SELECT nummer, geboortejaar, aangemaakt FROM deelnemers WHERE geboortejaar IS NOT NULL").fetchall():
                con.execute("UPDATE deelnemers SET geboortejaar = ? WHERE nummer = ?",
                            (_jaar(aangemaakt) - leeftijd, nummer))
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSIE}")


def _jaar(aangemaakt: str) -> int:
    return pd.Timestamp(aangemaakt).year if aangemaakt else nu().year


def _maak_db(root: Path) -> None:
    """Nieuwe database, met het oude formaat erin, eerst als tijdelijk bestand. Pas als alles gelukt is wordt het
    ``ecg.db``: een mislukte migratie laat zo geen lege database achter die de volgende keer niet meer migreert."""
    root.mkdir(parents=True, exist_ok=True)
    db_pad(root).parent.mkdir(parents=True, exist_ok=True)
    tmp = db_pad(root).with_name(f"ecg.db.{os.getpid()}.tmp")  # naast de database: os.replace werkt niet tussen schijven
    tmp.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(tmp)) as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.executescript(_SCHEMA)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSIE}")
            with con:
                _migreer_bestanden(con, root)
        if not db_pad(root).exists():  # een ander proces (Streamlit naast de desktop-app) kan net eerder zijn
            os.replace(tmp, db_pad(root))
    finally:
        tmp.unlink(missing_ok=True)


# --- ongedaan maken / opnieuw doen ----------------------------------------------------------------------------


@dataclass
class _Stap:
    label: str
    root: Path
    db: bytes  # de database van vóór (in 'terug') of van na (in 'vooruit') de stap
    verplaatst: list[tuple[Path, Path]] = field(default_factory=list)  # mappen (van, naar), bijv. naar de prullenbak


class Geschiedenis:
    """Ongedaan maken (Ctrl+Z) en opnieuw doen (Ctrl+Shift+Z) voor alles wat in ``ecg.db`` staat. Per actie (een
    publieke methode met ``@_stap``) een kopie van de database van vóór de actie (± 100 KB). Signalen (parquet) zitten
    er niet in: na koppelen of verschuiven begint de geschiedenis opnieuw (``wis``). Alleen in het geheugen."""

    MAX = 50

    def __init__(self) -> None:
        self.terug: list[_Stap] = []
        self.vooruit: list[_Stap] = []

    def nieuw(self, stap: _Stap) -> None:
        self.terug = [*self.terug, stap][-self.MAX:]
        self.vooruit = []

    def wis(self) -> None:
        self.terug, self.vooruit = [], []

    def ongedaan(self) -> str | None:
        """Laatste stap terugdraaien; geeft het label, of None als er niets ongedaan te maken is."""
        return self._wissel(self.terug, self.vooruit, terug=True)

    def opnieuw(self) -> str | None:
        return self._wissel(self.vooruit, self.terug, terug=False)

    @staticmethod
    def _wissel(van: list[_Stap], naar: list[_Stap], terug: bool) -> str | None:
        if not van:
            return None
        stap = van.pop()
        naar.append(_Stap(stap.label, stap.root, _momentopname(stap.root), stap.verplaatst))
        _herstel(stap.root, stap.db)
        for bron, doel in (reversed(stap.verplaatst) if terug else stap.verplaatst):
            a, b = (doel, bron) if terug else (bron, doel)
            if a.exists() and not b.exists():
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(a), str(b))
        _ruim_lege_mappen_op(stap.root)
        return stap.label


GESCHIEDENIS = Geschiedenis()
_IN_STAP: contextvars.ContextVar[list | None] = contextvars.ContextVar("in_stap", default=None)


def _stap(label: str, root_van=lambda self, *_, **__: self.root):
    """Maakt van een publieke methode één stap in de geschiedenis (ook als die intern vaker schrijft)."""
    def versier(functie):
        @functools.wraps(functie)
        def omhulsel(*args, **kwargs):
            if _IN_STAP.get() is not None:  # binnen een andere stap: die telt
                return functie(*args, **kwargs)
            root = Path(root_van(*args, **kwargs))
            voor, verplaatst = _momentopname(root), []
            token = _IN_STAP.set(verplaatst)
            try:
                uitkomst = functie(*args, **kwargs)
            finally:
                _IN_STAP.reset(token)
            if voor is not None and _momentopname(root) != voor:
                GESCHIEDENIS.nieuw(_Stap(label, root, voor, verplaatst))
            return uitkomst
        return omhulsel
    return versier


def _momentopname(root: Path) -> bytes | None:
    if not db_pad(root).exists():
        return None
    with closing(sqlite3.connect(db_pad(root), timeout=10)) as con:
        return con.serialize()


def _herstel(root: Path, data: bytes) -> None:
    with closing(sqlite3.connect(":memory:")) as bron, closing(sqlite3.connect(db_pad(root), timeout=10)) as doel:
        bron.deserialize(data)
        bron.backup(doel)


def _ruim_lege_mappen_op(root: Path) -> None:
    """Na ongedaan maken van een nieuwe opname: zijn lege map weg, anders weigert dezelfde minuut later."""
    with _db(root) as con:
        bekend = {r[0] for r in con.execute("SELECT id FROM opnames")}
    for map in (root / "opnames").glob("*"):
        if map.is_dir() and map.name not in bekend and not any(map.iterdir()):
            map.rmdir()


def leeg_prullenbak(root: str | Path = DATA_ROOT) -> None:
    """Bij het starten: verwijderde opnames uit een vorige sessie definitief weg (de geschiedenis is dan ook weg)."""
    shutil.rmtree(Path(root) / PRULLENBAK, ignore_errors=True)


PRULLENBAK = "_prullenbak"


def versie(root: str | Path = DATA_ROOT) -> int:
    """Verandert bij elke wijziging in de database: sleutel voor caches."""
    pad = db_pad(root)
    return pad.stat().st_mtime_ns if pad.exists() else 0


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
    geboortejaar: int | None
    geslacht: str
    hartdecompensatie: bool
    andere_aandoening: str = ""
    aangemaakt: str = ""

    @property
    def weergave(self) -> str:
        return f"{self.naam} ({self.id})"

    def leeftijd_op(self, tijd: datetime | pd.Timestamp) -> int | None:
        """Leeftijd in het jaar van ``tijd``. Kan een jaar te hoog zijn: de verjaardag is niet bekend."""
        return None if self.geboortejaar is None else pd.Timestamp(tijd).year - self.geboortejaar


class Deelnemers:
    def __init__(self, root: str | Path = DATA_ROOT) -> None:
        self.root = Path(root)

    def alle(self) -> list[Deelnemer]:
        with _db(self.root) as con:
            return [_deelnemer(rij) for rij in con.execute("SELECT * FROM deelnemers ORDER BY nummer")]

    @_stap("Deelnemer toegevoegd")
    def toevoegen(
        self,
        naam: str,
        geboortejaar: int | None,
        geslacht: str,
        hartdecompensatie: bool,
        andere_aandoening: str = "",
    ) -> Deelnemer:
        deelnemer = Deelnemer("", naam, geboortejaar, geslacht, hartdecompensatie, andere_aandoening, iso(nu()))
        self._valideer(deelnemer)
        with _db(self.root) as con:
            nummer = con.execute(
                "INSERT INTO deelnemers (id, naam, geslacht, hartdecompensatie) VALUES (hex(randomblob(8)), '', '', 0)",
            ).lastrowid
            deelnemer.id = f"D{nummer:03d}"
            _bewaar_deelnemer(con, deelnemer, nummer)
        return deelnemer

    @_stap("Deelnemer gewijzigd")
    def bijwerken(self, deelnemer: Deelnemer) -> None:
        self._valideer(deelnemer)
        with _db(self.root) as con:
            rij = con.execute("SELECT nummer FROM deelnemers WHERE id = ?", (deelnemer.id,)).fetchone()
            if rij is None:
                raise ValueError(f"Onbekende deelnemer '{deelnemer.id}'. Beschikbaar: {self._ids(con)}")
            _bewaar_deelnemer(con, deelnemer, rij["nummer"])

    def opnames(self, id: str) -> list[Opname]:
        return [o for o in Opname.alle(self.root) if o.info.deelnemer_id == id]

    @_stap("Deelnemer verwijderd")
    def verwijder(self, id: str) -> None:
        """Alleen een deelnemer zonder opnames kan weg; opnames en annotaties blijven zo altijd herleidbaar."""
        with _db(self.root) as con:
            if id not in self._ids(con):
                raise ValueError(f"Onbekende deelnemer '{id}'. Beschikbaar: {self._ids(con)}")
            aantal = con.execute("SELECT COUNT(*) FROM opnames WHERE deelnemer_id = ?", (id,)).fetchone()[0]
            if aantal:
                raise ValueError(
                    f"Deelnemer {id} heeft {aantal} opname(s) en kan daarom niet verwijderd worden. "
                    f"Verwijder eerst de opnames als dat echt de bedoeling is.",
                )
            con.execute("DELETE FROM deelnemers WHERE id = ?", (id,))

    @staticmethod
    def _ids(con: sqlite3.Connection) -> list[str]:
        return [r[0] for r in con.execute("SELECT id FROM deelnemers ORDER BY nummer")]

    def _valideer(self, deelnemer: Deelnemer) -> None:
        if not deelnemer.naam.strip():
            raise ValueError("Vul een voornaam of patiënt-ID in.")
        if deelnemer.geslacht not in GESLACHTEN:
            raise ValueError(f"Onbekend geslacht '{deelnemer.geslacht}'. Beschikbaar: {GESLACHTEN}")
        if deelnemer.geboortejaar is not None and not EERSTE_JAAR <= deelnemer.geboortejaar <= nu().year:
            raise ValueError(f"Ongeldig geboortejaar: {deelnemer.geboortejaar} (tussen {EERSTE_JAAR} en {nu().year})")


def _deelnemer(rij: sqlite3.Row) -> Deelnemer:
    return Deelnemer(
        id=rij["id"], naam=rij["naam"], geboortejaar=rij["geboortejaar"], geslacht=rij["geslacht"],
        hartdecompensatie=bool(rij["hartdecompensatie"]), andere_aandoening=rij["andere_aandoening"],
        aangemaakt=rij["aangemaakt"],
    )


def _bewaar_deelnemer(con: sqlite3.Connection, d: Deelnemer, nummer: int) -> None:
    # UPDATE, geen INSERT OR REPLACE: dat verwijdert eerst de rij, en dat weigert de foreign key van opnames.
    con.execute(
        "UPDATE deelnemers SET id = ?, naam = ?, geboortejaar = ?, geslacht = ?, hartdecompensatie = ?, "
        "andere_aandoening = ?, aangemaakt = ? WHERE nummer = ?",
        (d.id, d.naam, d.geboortejaar, d.geslacht, int(d.hartdecompensatie), d.andere_aandoening, d.aangemaakt, nummer),
    )


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
    annotaties = [_annotatie(rij) for _, rij in df.iterrows()]
    live = df[df["tijdbasis"] == "pc"] if "t_start_data" in df else df.iloc[:0]
    correctie = None
    if len(live):
        verschil = als_timestamp(live["t_start_data"].iloc[0]) - als_timestamp(live["t_start"].iloc[0])
        correctie = round(verschil.total_seconds(), 3)
    return annotaties, correctie


def _annotatie(rij) -> Annotatie:
    """Uit een CSV-rij of databaserij (lege tekst of None = geen eind)."""
    return Annotatie(
        id=int(rij["id"]),
        soort=rij["soort"],
        label=rij["label"],
        t_start=als_timestamp(rij["t_start"]),
        t_eind=als_timestamp(rij["t_eind"]) if rij["t_eind"] else None,
        tijdbasis=rij["tijdbasis"],
        opmerking=rij["opmerking"] or "",
        beoordeling=rij["beoordeling"] or "",
        beoordeling_opmerking=rij["beoordeling_opmerking"] or "",
        plaatsing=(rij["plaatsing"] if "plaatsing" in rij.keys() else "") or "",  # ontbreekt vóór oktober 2026
    )


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
    @_stap("Nieuwe opname", root_van=lambda cls, deelnemer, gestart, root=DATA_ROOT, **_: root)
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
        with _db(root) as con:
            if map.exists() or con.execute("SELECT 1 FROM opnames WHERE id = ?", (id,)).fetchone():
                raise ValueError(f"Opname {id} bestaat al. Kies die opname, of wacht een minuut.")
        map.mkdir(parents=True)
        info = OpnameInfo(
            id=id,
            deelnemer_id=deelnemer.id,
            gestart=iso(lokaal),
            leeftijd_bij_opname=deelnemer.leeftijd_op(lokaal),
            **velden,
        )
        opname = cls(map, info, [])
        opname._opslaan()
        return opname

    @classmethod
    def laad(cls, map: str | Path) -> Opname:
        """``map``: de map van de opname (``<root>/opnames/<id>``); de gegevens komen uit ``<root>/ecg.db``."""
        map = Path(map)
        with _db(map.parent.parent) as con:
            rij = con.execute("SELECT info FROM opnames WHERE id = ?", (map.name,)).fetchone()
            if rij is None:
                raise FileNotFoundError(f"Geen opname '{map.name}' in {db_pad(map.parent.parent)}")
            return cls._van_rij(con, map, rij["info"])

    @classmethod
    def _van_rij(cls, con: sqlite3.Connection, map: Path, info: str) -> Opname:
        annotaties = [_annotatie(r) for r in con.execute(
            "SELECT * FROM annotaties WHERE opname_id = ? ORDER BY id", (map.name,))]
        return cls(map, OpnameInfo(**json.loads(info)), annotaties)

    @staticmethod
    def alle(root: str | Path = DATA_ROOT) -> list[Opname]:
        """Nieuwste eerst."""
        with _db(root) as con:
            return [Opname._van_rij(con, Path(root) / "opnames" / r["id"], r["info"])
                    for r in con.execute("SELECT id, info FROM opnames ORDER BY id DESC").fetchall()]

    @_stap("Opname verwijderd")
    def verwijder_opname(self) -> None:
        """Opname weg: gegevens, annotaties én de map met ruwe data, signalen en exports. De map gaat naar de
        prullenbak in de datamap, zodat ongedaan maken hem terugzet; bij de volgende start wordt die geleegd."""
        with _db(self.root) as con:
            con.execute("DELETE FROM opnames WHERE id = ?", (self.info.id,))
        if self.map.exists():
            doel = self.root / PRULLENBAK / self.info.id
            shutil.rmtree(doel, ignore_errors=True)
            doel.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.map), str(doel))
            verplaatst = _IN_STAP.get()
            if verplaatst is not None:
                verplaatst.append((self.map, doel))

    @property
    def root(self) -> Path:
        return self.map.parent.parent

    # --- annotaties ---

    @_stap("Annotatie toegevoegd")
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

    @_stap("Periode gestart")
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

    @_stap("Experiment gewijzigd")
    def zet_experiment(self, experiment: str) -> None:
        self.info.experiment = experiment.strip()
        self._opslaan()

    @_stap("Periode gestopt")
    def stop_periode(self) -> None:
        if self.actieve_periode is not None:
            self.actieve_periode.t_eind = als_timestamp(nu())
            self._opslaan()

    @_stap("Moment gemarkeerd")
    def moment(self, label: str, opmerking: str = "") -> Annotatie:
        return self.voeg_toe("moment", label, nu(), opmerking=opmerking)

    @_stap("Sync-sprong")
    def sync(self) -> Annotatie:
        return self.voeg_toe("sync", "sync-sprong", nu())

    @_stap("Opname afgesloten")
    def sluit_live_af(self) -> None:
        self.stop_periode()
        self.info.live_afgesloten = True
        self._opslaan()

    @_stap("Annotatie gewijzigd")
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

    @_stap("Annotatie verwijderd")
    def verwijder(self, ids: list[int]) -> None:
        onbekend = set(ids) - {a.id for a in self.annotaties}
        if onbekend:
            raise ValueError(f"Onbekende annotatie-id's: {sorted(onbekend)}")
        self.annotaties = [a for a in self.annotaties if a.id not in ids]
        self._opslaan()

    @_stap("Annotaties vervangen")
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

    @_stap("Klokcorrectie gezet")
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
        GESCHIEDENIS.wis()  # signalen zitten niet in de geschiedenis

    def verschuif_signalen(self, seconden: float) -> None:
        """Alle signaaltijden ``seconden`` verschuiven, bijvoorbeeld een uur als de P-Cardio-klok nog op zomertijd
        stond. Annotaties in P-Cardio-tijd schuiven mee; de klokcorrectie (P-Cardio − pc) verandert evenveel, zodat
        live annotaties op dezelfde plek in de data blijven. De ruwe bestanden blijven ongewijzigd."""
        verschil = pd.Timedelta(seconds=seconden)
        for naam, signaal in self.laad_signalen().items():
            signaal.data["tijd"] = signaal.data["tijd"] + verschil
            signaal.data.to_parquet(self.signalen_map / f"{naam}.parquet", index=False)
        for a in self.annotaties:
            if a.tijdbasis == "data":
                a.t_start += verschil
                a.t_eind = a.t_eind + verschil if a.t_eind is not None else None
        if self.info.klokcorrectie_s is not None:
            self.info.klokcorrectie_s = round(self.info.klokcorrectie_s + seconden, 3)
        self._opslaan()
        GESCHIEDENIS.wis()  # signalen zitten niet in de geschiedenis

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

    @_stap("Opnamegegevens gewijzigd")
    def _opslaan(self) -> None:
        with _db(self.root) as con:
            _bewaar_opname(con, self.info, self.annotaties)

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


def _bewaar_opname(con: sqlite3.Connection, info: OpnameInfo, annotaties: list[Annotatie]) -> None:
    """Opname en al haar annotaties in één keer (zelfde semantiek als het oude herschrijven van de bestanden)."""
    con.execute(
        "INSERT INTO opnames (id, deelnemer_id, info) VALUES (?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET deelnemer_id = excluded.deelnemer_id, info = excluded.info",
        (info.id, info.deelnemer_id, json.dumps(asdict(info), ensure_ascii=False)),
    )
    con.execute("DELETE FROM annotaties WHERE opname_id = ?", (info.id,))
    rijen = []
    for a in annotaties:
        rij = _rij(a)
        rij["t_eind"] = rij["t_eind"] or None
        rijen.append((info.id, *(rij[k] for k in ANNOTATIE_KOLOMMEN)))
    con.executemany(
        f"INSERT INTO annotaties (opname_id, {', '.join(ANNOTATIE_KOLOMMEN)}) "
        f"VALUES (?, {', '.join('?' * len(ANNOTATIE_KOLOMMEN))})",
        rijen,
    )


def _migreer_bestanden(con: sqlite3.Connection, root: Path) -> None:
    """Eenmalig: het oude formaat (deelnemers.csv, opname.json, annotaties.csv) in de nieuwe database zetten."""
    pad = root / "deelnemers.csv"
    if pad.exists():
        for _, rij in pd.read_csv(pad, dtype=str, keep_default_na=False).iterrows():
            con.execute(
                "INSERT INTO deelnemers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (int(rij["id"][1:]), rij["id"], rij["naam"], _jaar(rij["aangemaakt"]) - int(rij["leeftijd"])
                 if rij["leeftijd"] else None,
                 rij["geslacht"], int(rij["hartdecompensatie"] == "ja"), rij["andere_aandoening"], rij["aangemaakt"]),
            )
    for info_pad in sorted((root / "opnames").glob("*/opname.json")):
        info = OpnameInfo(**json.loads(info_pad.read_text(encoding="utf-8")))
        info.id = info_pad.parent.name  # de map is leidend (signalen staan daar); 2026-10-21_1336 had een fout id
        if not con.execute("SELECT 1 FROM deelnemers WHERE id = ?", (info.deelnemer_id,)).fetchone():
            # Opname van een deelnemer die niet (meer) in deelnemers.csv staat: bewaar de opname, maak de deelnemer.
            nummer = int(info.deelnemer_id[1:]) if info.deelnemer_id[1:].isdigit() else None
            con.execute(
                "INSERT INTO deelnemers (nummer, id, naam, geslacht, hartdecompensatie) "
                "VALUES (?, ?, ?, 'onbekend', 0)",
                (nummer, info.deelnemer_id, info.deelnemer_id),
            )
        pad = info_pad.parent / "annotaties.csv"
        _bewaar_opname(con, info, lees_annotaties(pad)[0] if pad.exists() else [])
