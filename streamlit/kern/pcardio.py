"""P-Cardio-bestanden inlezen: CSV-exports en de binaire ``data_*.txt`` van het apparaat.

Beide leveren een lijst ``Signaal``-objecten op met een tijdkolom ``tijd`` in UTC en één kolom per kanaal.

Het binaire formaat volgt ``docs/PCardio - Interface v7.0.pdf`` (§6-§8). De handleiding laat een paar
details open (bytevolgorde, exacte header-velden); die worden bij het inlezen gecontroleerd tegen de
payload-grootte in elke pakketheader, en afwijkingen komen terug als melding of fout.
"""

from __future__ import annotations

import binascii
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# --- signaal -----------------------------------------------------------------------------------------


@dataclass
class Signaal:
    naam: str
    data: pd.DataFrame
    eenheden: dict[str, str]
    bron: str

    @property
    def kanalen(self) -> list[str]:
        return [k for k in self.data.columns if k != "tijd"]

    @property
    def start(self) -> pd.Timestamp:
        return self.data["tijd"].iloc[0]

    @property
    def eind(self) -> pd.Timestamp:
        return self.data["tijd"].iloc[-1]

    @property
    def fs(self) -> float:
        """Geschatte sample rate uit de tijdstempels (de werkelijke rate wijkt af van de nominale)."""
        stappen = self.data["tijd"].diff().dt.total_seconds().to_numpy()[1:]
        stappen = stappen[stappen > 0]
        return float(1.0 / np.median(stappen)) if len(stappen) else float("nan")


# --- algemeen ----------------------------------------------------------------------------------------


def lees_bestand(pad: str | Path) -> tuple[list[Signaal], list[str]]:
    """Lees een CSV-export of een binair ``data_*.txt``-bestand. Geeft signalen en meldingen terug."""
    pad = Path(pad)
    if not pad.exists():
        raise FileNotFoundError(f"Bestand niet gevonden: {pad}")
    if pad.suffix.lower() == ".csv":
        return [lees_csv(pad)], []
    if pad.suffix.lower() == ".txt":
        return lees_binair(pad)
    raise ValueError(f"Onbekend bestandstype '{pad.suffix}' voor {pad.name}. Ondersteund: .csv, .txt")


def combineer(signalen: list[Signaal]) -> dict[str, Signaal]:
    """Zet signalen uit meerdere bestanden bij elkaar, één per naam."""
    resultaat: dict[str, Signaal] = {}
    for signaal in signalen:
        if signaal.naam in resultaat:
            raise ValueError(
                f"Signaal '{signaal.naam}' komt in meerdere bestanden voor "
                f"({resultaat[signaal.naam].bron} en {signaal.bron}). Opnames die over meerdere bestanden "
                f"verdeeld zijn, worden nog niet ondersteund.",
            )
        resultaat[signaal.naam] = signaal
    return resultaat


# --- CSV ---------------------------------------------------------------------------------------------

_TZ_PATROON = re.compile(r"UTC\s*([+-])(\d{1,2}):?(\d{2})?", re.IGNORECASE)
_EENHEID_PATROON = re.compile(r"^(.*?)\s*\((.*)\)\s*$")

_NAAM_OP_KANAAL = [
    ("ecg", "ecg"),
    ("acc", "acc"),
    ("gyr", "gyro"),
    ("mag", "mag"),
    ("emg", "emg"),
    ("lead", "lead_off"),
    ("button", "button_marker"),
    ("tap", "tap_marker"),
    ("batt", "batterij"),
]


def lees_csv(pad: str | Path) -> Signaal:
    """Lees een CSV-export (``Date``, ``Time (UTC+01:00)``, kanalen met eenheid tussen haakjes)."""
    pad = Path(pad)
    df = pd.read_csv(pad)
    df.columns = df.columns.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

    datum_kol = _kolom_die_begint_met(df, "date", pad)
    tijd_kol = _kolom_die_begint_met(df, "time", pad)
    tijd = _parse_tijd(df[datum_kol], df[tijd_kol], _tz_uit_kolomnaam(tijd_kol))

    kanalen: dict[str, pd.Series] = {}
    eenheden: dict[str, str] = {}
    for kolom in df.columns:
        if kolom in (datum_kol, tijd_kol):
            continue
        match = _EENHEID_PATROON.match(kolom)
        naam, eenheid = (match.group(1), match.group(2)) if match else (kolom, "")
        kanalen[naam] = pd.to_numeric(df[kolom], errors="coerce")
        eenheden[naam] = eenheid
    if not kanalen:
        raise ValueError(f"Geen kanalen gevonden in {pad.name}. Kolommen: {list(df.columns)}")

    data = (
        pd.DataFrame({"tijd": tijd, **kanalen})
        .dropna(subset=["tijd"])
        .sort_values("tijd")
        .reset_index(drop=True)
    )
    return Signaal(_signaalnaam(list(kanalen), pad), data, eenheden, pad.name)


def _kolom_die_begint_met(df: pd.DataFrame, prefix: str, pad: Path) -> str:
    for kolom in df.columns:
        if kolom.lower().startswith(prefix):
            return kolom
    raise ValueError(f"Geen kolom die begint met '{prefix}' in {pad.name}. Kolommen: {list(df.columns)}")


def _tz_uit_kolomnaam(kolom: str) -> float | None:
    """'Time (UTC+01:00)' -> 1.0 (uren). Zonder tijdzone in de naam: None (dan lokale tijd)."""
    match = _TZ_PATROON.search(kolom)
    if not match:
        return None
    teken = -1 if match.group(1) == "-" else 1
    return teken * (int(match.group(2)) + int(match.group(3) or 0) / 60)


def _parse_tijd(datum: pd.Series, tijd: pd.Series, tz_uren: float | None) -> pd.Series:
    tekst = datum.astype(str).str.strip() + " " + tijd.astype(str).str.strip()
    try:
        lokaal = pd.to_datetime(tekst, format="%Y/%m/%d %H:%M:%S.%f")
    except (ValueError, TypeError):
        # Andere notaties, bijv. na openen/opslaan in Excel ('16:58.4' = mm:ss.s).
        dag = pd.to_datetime(datum, errors="coerce")
        tijd_tekst = tijd.astype(str).str.strip()
        tijd_tekst = tijd_tekst.where(tijd_tekst.str.count(":") >= 2, "00:" + tijd_tekst)
        lokaal = dag + pd.to_timedelta(tijd_tekst, errors="coerce")
    if tz_uren is None:
        return lokaal.dt.tz_localize("Europe/Amsterdam", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return (lokaal.dt.tz_localize("UTC") - pd.Timedelta(tz_uren, unit="h")).rename(None)


def _signaalnaam(kanalen: list[str], pad: Path) -> str:
    eerste = kanalen[0].lower()
    for prefix, naam in _NAAM_OP_KANAAL:
        if eerste.startswith(prefix):
            return naam
    return pad.stem.lower()


# --- binair ------------------------------------------------------------------------------------------

_PREFIX = bytes([0x50, 0x43, 0x41, 0x52, 0x44, 0x49, 0x4F, 0x00])  # "PCARDIO\0"
_CONFIG_GROOTTE = 144
# In echte bestanden (firmware van okt. 2026) staat de sampling-configuratie op byte 72; de handleiding v5 laat
# 60 of 64 vermoeden. Alle kandidaten worden geprobeerd en gecontroleerd tegen de pakketheaders.
_SAMPLING_OFFSETS = (72, 60, 64)
_DATA_OFFSET = 152
_PAKKET_HEADER = 13
_PAKKETTEN_PER_SECONDE = 5
_TICKS_PER_SECONDE = 32768
_CRC_STEEKPROEF = 50  # aantal pakketten waarvan de checksum gecontroleerd wordt
# De PCardio-software van 2M zet de klok van het apparaat op lokale kloktijd, niet op UTC (zoals de
# handleiding suggereert): bestandsnaam en tijdstempels komen overeen met de Nederlandse kloktijd.
APPARAAT_TZ = "Europe/Amsterdam"

GAINS = [1, 2, 3, 4, 6, 8, 12, 16]
SAMPLE_RATES = [1000, 800, 500, 400, 250, 200, 100, 50, 25, 10, 5]


@dataclass(frozen=True)
class _Sensor:
    naam: str
    kanalen: tuple[str, ...]


@dataclass(frozen=True)
class _DataType:
    eenheid: str
    grootte: int
    elementen: int
    signed: bool
    analoog_min: float
    analoog_max: float
    digitaal_min: int
    digitaal_max: int


SENSOREN: dict[int, _Sensor] = {
    0: _Sensor("batterij", ("Batterij",)),
    1: _Sensor("ecg", ("Ecg1",)),
    2: _Sensor("bioz", ("BioZ",)),
    3: _Sensor("ecg", ("Ecg1", "Ecg2")),
    4: _Sensor("emg", ("Emg1", "Emg2")),
    5: _Sensor("acc", ("AccX", "AccY", "AccZ")),
    6: _Sensor("gyro", ("GyrX", "GyrY", "GyrZ")),
    7: _Sensor("mag", ("MagX", "MagY", "MagZ")),
    10: _Sensor("button_marker", ("Button",)),
    11: _Sensor("tap_marker", ("Tap",)),
    12: _Sensor("lead_off", ("LeadOff",)),
}

DATATYPES: dict[int, _DataType] = {
    0: _DataType("%", 1, 1, False, 0, 100, 0, 100),
    1: _DataType("mV", 3, 1, True, -2420, 2420, -8388608, 8388607),
    2: _DataType("Ohm", 3, 1, True, -80666.67, 80666.67, -262144, 262143),
    3: _DataType("mV", 6, 2, True, -2420, 2420, -8388608, 8388607),
    4: _DataType("g", 6, 3, True, -16, 16, -32768, 32767),
    5: _DataType("deg/s", 6, 3, True, -2000, 2000, -28571, 28570),
    6: _DataType("rad/s", 6, 3, True, -34.906585, 34.906585, -28571, 28570),
    7: _DataType("Gauss", 6, 3, True, -49.125, 49.125, -32768, 32767),
    8: _DataType("", 1, 1, False, 0, 1, 0, 1),
}


@dataclass(frozen=True)
class SensorConfig:
    sensor_id: int
    gain_id: int
    rate_id: int
    type_id: int

    @property
    def sensor(self) -> _Sensor:
        return SENSOREN[self.sensor_id]

    @property
    def datatype(self) -> _DataType:
        return DATATYPES[self.type_id]

    @property
    def gain(self) -> int:
        return GAINS[self.gain_id]

    @property
    def rate(self) -> int:
        return SAMPLE_RATES[self.rate_id]

    @property
    def samples_per_pakket(self) -> int:
        return self.rate // _PAKKETTEN_PER_SECONDE

    @property
    def blokgrootte(self) -> int:
        return self.datatype.grootte * self.samples_per_pakket


def lees_sampling_config(config: bytes, payload_grootte: int) -> list[SensorConfig]:
    """Lees de sampling-configuratie uit een config.txt-blok van 144 bytes.

    Alleen een configuratie waarvan de berekende payload precies ``payload_grootte`` bytes is (uit de eerste
    pakketheader), wordt geaccepteerd.
    """
    if len(config) < _CONFIG_GROOTTE:
        raise ValueError(f"Configuratieblok is {len(config)} bytes, verwacht {_CONFIG_GROOTTE}.")
    if config[:8] != _PREFIX:
        raise ValueError(
            f"Geen P-Cardio-bestand: prefix is {config[:8]!r}, verwacht {_PREFIX!r}. "
            f"Is dit een binair data_*.txt-bestand van de P-Cardio?",
        )
    for offset in _SAMPLING_OFFSETS:
        configs = _probeer_sampling_config(config, offset)
        if configs is None:
            continue
        if sum(c.blokgrootte for c in configs) == payload_grootte:
            return configs
    raise ValueError(
        f"Geen geldige sampling-configuratie gevonden op bytes {list(_SAMPLING_OFFSETS)} van de header die past "
        f"bij een payload van {payload_grootte} bytes. Mogelijk wijkt het formaat af van de interface-handleiding v5.",
    )


def _probeer_sampling_config(config: bytes, offset: int) -> list[SensorConfig] | None:
    aantal = int.from_bytes(config[offset:offset + 4], "little")
    if not 0 < aantal <= 16 or offset + 4 + 4 * aantal > _CONFIG_GROOTTE:
        return None
    configs = [SensorConfig(*config[offset + 4 + 4 * i:offset + 8 + 4 * i]) for i in range(aantal)]
    for c in configs:
        if (
            c.sensor_id not in SENSOREN
            or c.type_id not in DATATYPES
            or c.gain_id >= len(GAINS)
            or c.rate_id >= len(SAMPLE_RATES)
        ):
            return None
    return configs


def lees_binair(pad: str | Path) -> tuple[list[Signaal], list[str]]:
    pad = Path(pad)
    inhoud = pad.read_bytes()
    if len(inhoud) < _DATA_OFFSET + _PAKKET_HEADER:
        raise ValueError(f"{pad.name} is te klein ({len(inhoud)} bytes) voor een P-Cardio-databestand.")

    configs, volgorde = _sampling_config_bij_data(inhoud)
    payload_grootte = sum(c.blokgrootte for c in configs)
    pakket_grootte = _PAKKET_HEADER + payload_grootte
    data = inhoud[_DATA_OFFSET:]
    aantal = len(data) // pakket_grootte
    if aantal == 0:
        raise ValueError(f"{pad.name} bevat geen volledige datapakketten (pakketgrootte {pakket_grootte} bytes).")

    meldingen: list[str] = []
    rest = len(data) - aantal * pakket_grootte
    if rest:
        meldingen.append(f"{rest} bytes aan het eind van {pad.name} vormen geen volledig pakket en zijn genegeerd.")

    pakketten = np.frombuffer(data[:aantal * pakket_grootte], dtype=np.uint8).reshape(aantal, pakket_grootte)
    # Payload-size-veld van élk pakket moet kloppen met de configuratie (gecontroleerd met dezelfde bytevolgorde).
    grootte = _uint(pakketten[:, 9:11], volgorde)
    if not np.all(grootte == payload_grootte):
        raise ValueError(
            f"Payload-grootte in de pakketheaders van {pad.name} komt niet overeen met de configuratie "
            f"(verwacht {payload_grootte} bytes, gevonden o.a. {sorted(set(grootte[:5].tolist()))}). "
            f"Mogelijk wijkt het formaat af van de interface-handleiding v5.",
        )
    tijd_eind, gecorrigeerd = _pakkettijden(pakketten, volgorde)
    if gecorrigeerd:
        meldingen.append(
            f"Bij {gecorrigeerd} pakket(ten) in {pad.name} liep de secondeteller van de P-Cardio achter (tijd viel "
            f"1 s terug); gecorrigeerd.",
        )
    if np.any(np.diff(tijd_eind) <= 0):
        meldingen.append(
            f"De tijden in {pad.name} lopen op sommige plekken niet op. Plots en export kunnen daar afwijken.",
        )
    meldingen.extend(_controleer_crc(pakketten, payload_grootte))

    signalen: list[Signaal] = []
    offset = _PAKKET_HEADER
    for config in configs:
        blok = pakketten[:, offset:offset + config.blokgrootte]
        offset += config.blokgrootte
        signalen.append(_decodeer_sensor(config, blok, tijd_eind, volgorde, pad.name))
    return signalen, meldingen


def _sampling_config_bij_data(inhoud: bytes) -> tuple[list[SensorConfig], str]:
    """Sampling-configuratie en bytevolgorde die passen bij het payload-size-veld van het eerste pakket."""
    veld = inhoud[_DATA_OFFSET + 9:_DATA_OFFSET + 11]
    fout: ValueError | None = None
    for volgorde in ("little", "big"):
        try:
            return lees_sampling_config(inhoud[:_CONFIG_GROOTTE], int.from_bytes(veld, volgorde)), volgorde
        except ValueError as e:
            fout = e
    raise fout


def _pakkettijden(pakketten: np.ndarray, volgorde: str) -> tuple[np.ndarray, int]:
    """Tijd (s sinds 1970, UTC) van de laatste sample in elk pakket: Unix-tijd + ticks van 32,768 kHz.

    De P-Cardio zet de ticks soms al op 0 vóórdat de seconde ophoogt; die pakketten vallen dan precies 1 s terug
    in de tijd. Die seconde wordt hier bijgeteld. Geeft ook het aantal gecorrigeerde pakketten terug.
    """
    seconden = _uint(pakketten[:, 0:4], volgorde).astype(np.float64)
    ticks = _uint(pakketten[:, 4:8], volgorde).astype(np.float64)
    tijden = seconden + ticks / _TICKS_PER_SECONDE
    terug = tijden < np.maximum.accumulate(tijden) - 0.5
    return tijden + terug, int(terug.sum())


def _decodeer_sensor(
    config: SensorConfig,
    blok: np.ndarray,
    tijd_eind: np.ndarray,
    volgorde: str,
    bron: str,
) -> Signaal:
    dt = config.datatype
    n = config.samples_per_pakket
    analoog = decodeer_blok(config, blok, volgorde)

    # De pakkettijd hoort bij de laatste sample; eerdere samples liggen 1/rate s eerder.
    terug = (n - 1 - np.arange(n)) / config.rate
    tijden = (tijd_eind[:, None] - terug[None, :]).reshape(-1)

    kanalen = config.sensor.kanalen
    data = pd.DataFrame(analoog, columns=list(kanalen))
    lokaal = pd.Series(pd.to_datetime(tijden, unit="s")).dt.tz_localize(
        APPARAAT_TZ, ambiguous="NaT", nonexistent="shift_forward",
    )
    data.insert(0, "tijd", lokaal.dt.tz_convert("UTC"))
    return Signaal(config.sensor.naam, data, {k: dt.eenheid for k in kanalen}, bron)


def decodeer_blok(config: SensorConfig, blok: np.ndarray, volgorde: str = "little") -> np.ndarray:
    """Ruwe bytes van één sensor (pakketten × blokgrootte, uint8) -> analoge waarden (samples × elementen).

    Formule uit §7 van de handleiding: ``A = ((maxA-minA)/(maxD-minD) * (D - maxD) + maxA) / gain``.
    """
    dt = config.datatype
    ruw = blok.reshape(len(blok), config.samples_per_pakket, dt.elementen, dt.grootte // dt.elementen)
    digitaal = _int(ruw, volgorde, dt.signed).astype(np.float64)
    schaal = (dt.analoog_max - dt.analoog_min) / (dt.digitaal_max - dt.digitaal_min)
    return ((schaal * (digitaal - dt.digitaal_max) + dt.analoog_max) / config.gain).reshape(-1, dt.elementen)


def _uint(bytes_: np.ndarray, volgorde: str) -> np.ndarray:
    """Zet een array (..., k) van bytes om in unsigned integers."""
    waarden = bytes_.astype(np.uint64)
    if volgorde == "big":
        waarden = waarden[..., ::-1]
    machten = (np.uint64(256) ** np.arange(bytes_.shape[-1], dtype=np.uint64))
    return (waarden * machten).sum(axis=-1)


def _int(bytes_: np.ndarray, volgorde: str, signed: bool) -> np.ndarray:
    waarden = _uint(bytes_, volgorde).astype(np.int64)
    if signed:
        bits = 8 * bytes_.shape[-1]
        waarden = np.where(waarden >= 2 ** (bits - 1), waarden - 2 ** bits, waarden)
    return waarden


def _controleer_crc(pakketten: np.ndarray, payload_grootte: int) -> list[str]:
    """CRC-16-CCITT (0x1021, start 0xFFFF) over de payload van de eerste pakketten, als controle."""
    n = min(_CRC_STEEKPROEF, len(pakketten))
    goed = 0
    for pakket in pakketten[:n]:
        verwacht_le = int(pakket[11]) | (int(pakket[12]) << 8)
        verwacht_be = (int(pakket[11]) << 8) | int(pakket[12])
        crc = binascii.crc_hqx(bytes(pakket[_PAKKET_HEADER:_PAKKET_HEADER + payload_grootte]), 0xFFFF)
        goed += crc in (verwacht_le, verwacht_be)
    if goed == n:
        return []
    return [
        f"Checksum klopt in {goed} van de eerste {n} pakketten. Dat kan wijzen op beschadigde data, of op een "
        f"andere checksum-berekening dan in de handleiding staat. Controleer het signaal visueel.",
    ]

