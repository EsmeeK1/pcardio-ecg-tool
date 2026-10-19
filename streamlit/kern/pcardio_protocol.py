"""Protocol van de P-Cardio via de 2M BLE-dongle: framing, Core Interface-pakketten, samenvoegen en datapakketten.

Geen I/O en geen Streamlit. Gebaseerd op ``docs/PCardio - Interface v7.0.pdf`` (Core Interface, memory map,
datapakketten) en ``docs/PCardio Dongle interface.pdf`` (seriële framing van de dongle), aangevuld met wat
``scripts/probe_device.py`` op echte hardware zag (19-10-2026, firmware 3.3.1.1). Waar de handleiding iets openlaat
of iets anders zegt dan het apparaat doet, staat dat hieronder bij de betreffende constante.
"""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

import numpy as np

from .pcardio import GAINS, SAMPLE_RATES, SENSOREN, SensorConfig, decodeer_blok

# --- seriële framing: '$' + opcode + hex + '\n' ---------------------------------------------------------------

# Opcodes die de dongle stuurt. Andere regels worden genegeerd (bijv. ruis bij het openen van de poort).
ONTVANGEN_OPCODES = frozenset("RS")
PCARDIO_NAAM = b"PCardio"  # Connect-data: '5043617264696F'
MAX_REGEL = 4096  # langere regels zonder '\n' zijn rommel; dan wordt de buffer geleegd


def frame(opcode: str, data: bytes = b"") -> bytes:
    """Bijv. ``frame("T", b"\\x01...")`` -> ``b"$T01...\\n"``."""
    return b"$" + opcode.encode("ascii") + data.hex().upper().encode("ascii") + b"\n"


class RegelLezer:
    """Knipt binnenkomende bytes op in regels; houdt een half ontvangen regel vast tot de rest binnen is."""

    def __init__(self) -> None:
        self._buffer = b""

    def voeg_toe(self, data: bytes) -> list[bytes]:
        self._buffer += data
        *regels, self._buffer = self._buffer.split(b"\n")
        if len(self._buffer) > MAX_REGEL:
            self._buffer = b""
        return [r.rstrip(b"\r") for r in regels if r.strip()]


def parse_regel(regel: bytes) -> tuple[str, bytes] | None:
    """``b"$R0102"`` -> ``("R", b"\\x01\\x02")``. None bij rommel, onbekende opcode of ongeldige hex."""
    start = regel.find(b"$")
    if start < 0 or len(regel) < start + 2:
        return None
    opcode = chr(regel[start + 1])
    if opcode not in ONTVANGEN_OPCODES:
        return None
    try:
        return opcode, bytes.fromhex(regel[start + 2:].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None


@dataclass(frozen=True)
class DongleStatus:
    """Antwoord op ``$S``. Op echte hardware: ``00F4`` = idle, ``01F4`` = scannen, ``02F4`` = verbonden.

    (Het voorbeeld in de dongle-handleiding noemt ``01F4`` 'verbonden en scannend'; het apparaat gebruikt de
    waarden uit de tekst.) De dongle stuurt dit ook ongevraagd, na ``$I`` en na ``$D``.
    """

    toestand: int
    max_grootte: int

    IDLE = 0
    SCANNEN = 1
    VERBONDEN = 2

    @property
    def verbonden(self) -> bool:
        return self.toestand == self.VERBONDEN

    @property
    def omschrijving(self) -> str:
        return {0: "niet verbonden", 1: "zoekt recorder…", 2: "verbonden"}.get(self.toestand, f"onbekend ({self.toestand})")


def parse_status(data: bytes) -> DongleStatus | None:
    return DongleStatus(data[0], data[1] if len(data) > 1 else 0) if data else None


def whitelist_data(mac: str, omgekeerd: bool = False) -> bytes:
    """MAC zoals op de sticker (``F5:6A:BF:A8:D9:F2`` of ``F56ABFA8D9F2``) -> 6 bytes voor ``$W``.

    De handleiding zegt niet in welke bytevolgorde; ``omgekeerd`` draait de volgorde om (nog niet getest).
    """
    schoon = mac.replace(":", "").replace("-", "").strip()
    data = bytes.fromhex(schoon)
    if len(data) != 6:
        raise ValueError(f"Een MAC-adres is 6 bytes (12 hextekens), '{mac}' is {len(data)} bytes.")
    return data[::-1] if omgekeerd else data


# --- Core Interface ----------------------------------------------------------------------------------------

OP_LEES = 0x01
OP_DATA = 0x02
OP_ABORT = 0x03  # niet in v7; v5 noemt 'Abort Packet (Opcode 3)', en het stopt de stream op echte hardware
OP_STREAM = 0x04
_CORE_HEADER = struct.Struct("<BIH")  # opcode, adres, lengte (little-endian)

# Memory map (§5)
INFO_ADRES, INFO_LENGTE = 0, 46
FOUTCODE_ADRES = 36
PIN_ADRES = 128
PIN = bytes([0x6C, 0x6F, 0x76, 0x65])
CONFIG_ADRES, CONFIG_LENGTE = 276, 68
STREAM_ADRES = 0x10000000


def lees_pakket(adres: int, lengte: int) -> bytes:
    return _CORE_HEADER.pack(OP_LEES, adres, lengte)


def data_pakket(adres: int, data: bytes) -> bytes:
    return _CORE_HEADER.pack(OP_DATA, adres, len(data)) + data


def stream_pakket(lengte: int) -> bytes:
    return _CORE_HEADER.pack(OP_STREAM, STREAM_ADRES, lengte)


ABORT_PAKKET = bytes([OP_ABORT])


@dataclass(frozen=True)
class CoreData:
    adres: int
    data: bytes


def parse_core(pakket: bytes) -> CoreData | None:
    """Een Data-pakket van het apparaat. Op echte hardware zit er altijd precies één compleet Data-pakket in één
    ``$R``-regel (max. 244 bytes: 7 header + 237 data). None als het geen (volledig) Data-pakket is."""
    if len(pakket) < _CORE_HEADER.size or pakket[0] != OP_DATA:
        return None
    _, adres, lengte = _CORE_HEADER.unpack_from(pakket)
    if len(pakket) != _CORE_HEADER.size + lengte:
        return None
    return CoreData(adres, pakket[_CORE_HEADER.size:])


def splits(adres: int, data: bytes, max_data: int = 237) -> list[bytes]:
    """Zoals het apparaat grote antwoorden verstuurt: Data-pakketten op opeenvolgende adressen."""
    return [data_pakket(adres + i, data[i:i + max_data]) for i in range(0, len(data), max_data)] or [data_pakket(adres, b"")]


class Samenvoeger:
    """Voegt Data-pakketten samen tot één blok van ``grootte`` bytes vanaf ``start``.

    Groot antwoord = meerdere Data-pakketten, elk met een eigen adres (gemeten: een streampakket van 557 bytes komt
    als 237 + 237 + 83 bytes op 0x10000000, 0x100000ED en 0x100001DA). Een stuk op het startadres begint een nieuw
    blok; een stuk dat niet aansluit, gooit het halve blok weg (``verloren`` telt die).
    """

    def __init__(self, start: int, grootte: int) -> None:
        self.start, self.grootte = start, grootte
        self._blok = bytearray()
        self.verloren = 0

    def voeg_toe(self, stuk: CoreData) -> bytes | None:
        positie = stuk.adres - self.start
        if positie != len(self._blok):  # sluit niet aan: half blok weg; alleen een stuk op het startadres begint opnieuw
            self.verloren += bool(self._blok)
            self._blok = bytearray()
            if positie:
                return None
        self._blok += stuk.data
        if len(self._blok) < self.grootte:
            return None
        blok, self._blok = bytes(self._blok[:self.grootte]), bytearray()
        return blok


# --- info memory (§5.1) ------------------------------------------------------------------------------------

HW_VERSIES = {0: "V2.1", 1: "V2.2", 7: "V1.X"}
HW_VARIANTEN = {0: "EMG", 1: "1 lead + ademhaling", 2: "6 leads"}
FOUTCODES = {0: "geen fout", 1: "alleen-lezen", 2: "ongeldig adres", 3: "ongeldige lengte", 4: "ongeldige data",
             5: "ongeldige toestand (recorder logt)"}


@dataclass(frozen=True)
class Info:
    id: int
    mac: int
    firmware: str
    vrije_ruimte: int
    bestandsgrootte: int
    batterij: int
    apparaatstatus: int
    foutcode: int
    fout_tijd: int
    hw_versie: int
    hw_variant: int

    @classmethod
    def van_bytes(cls, data: bytes) -> Info:
        if len(data) < INFO_LENGTE:
            raise ValueError(f"Info-blok is {len(data)} bytes, verwacht {INFO_LENGTE}.")
        id_, mac = struct.unpack_from("<QQ", data, 0)
        rest = struct.unpack_from("<6I", data, 20)
        return cls(id_, mac, ".".join(str(b) for b in data[16:20]), *rest, data[44], data[45])

    @property
    def logt(self) -> bool:
        return bool(self.apparaatstatus & 1)

    @property
    def lead_off(self) -> bool:
        return bool(self.apparaatstatus & 8)

    @property
    def hw_tekst(self) -> str:
        return f"{HW_VERSIES.get(self.hw_versie, self.hw_versie)}, {HW_VARIANTEN.get(self.hw_variant, self.hw_variant)}"


# --- sampling-configuratie (§7) -----------------------------------------------------------------------------

_ECG_GAINS = {0, 1, 2, 4, 6}
_ECG_RATES = {0, 2, 4}
_LAAG = ({0}, {10})
# Tabel 29: per sensor de geldige gain-id's, rate-id's en datatype-id's.
GELDIG: dict[int, tuple[set[int], set[int], set[int]]] = {
    0: (*_LAAG, {0}),
    1: (_ECG_GAINS, _ECG_RATES, {1}),
    2: (_ECG_GAINS, _ECG_RATES, {2}),
    3: (_ECG_GAINS, _ECG_RATES, {3}),
    4: (_ECG_GAINS, _ECG_RATES, {3}),
    5: ({0, 1, 3, 5}, {1, 3, 5, 6, 7}, {4}),
    6: ({0, 1, 3, 5, 7}, {1, 3, 5, 6, 7}, {5, 6}),
    7: ({0}, {6, 7}, {7}),
    10: (*_LAAG, {8}),
    11: (*_LAAG, {8}),
    12: (*_LAAG, {8}),
}
ECG_SENSOREN = (1, 3)
LEAD_OFF_SENSOR = 12
BATTERIJ_SENSOR = 0
HEADER = struct.Struct("<IIBHH")  # tijd, ticks, status, payloadgrootte, checksum: 13 bytes (de pseudocode zegt 9)
PAKKETTEN_PER_SECONDE = 5
TICKS_PER_SECONDE = 32768

# De meetconfiguratie uit het opnameprotocol (zie paginas/live.py). Wordt alleen geschreven na bevestiging.
STANDAARD_CONFIG = [
    SensorConfig(3, 4, 4, 3),  # ECG 2-kanaals, gain x6, 250 Hz
    SensorConfig(5, 1, 6, 4),  # accelerometer x2, 100 Hz
    SensorConfig(6, 1, 6, 5),  # gyroscoop x2, 100 Hz, graden/s
    SensorConfig(0, 0, 10, 0),  # batterij
    SensorConfig(10, 0, 10, 8),  # button marker
    SensorConfig(12, 0, 10, 8),  # lead-off
    SensorConfig(11, 0, 10, 8),  # tap marker
]


def decodeer_config(data: bytes) -> list[SensorConfig]:
    if len(data) < CONFIG_LENGTE:
        raise ValueError(f"Sampling-configuratie is {len(data)} bytes, verwacht {CONFIG_LENGTE}.")
    aantal = int.from_bytes(data[:4], "little")
    if aantal > 16:
        raise ValueError(f"Sampling-configuratie noemt {aantal} sensoren; maximaal 16.")
    return [SensorConfig(*data[4 + 4 * i:8 + 4 * i]) for i in range(aantal)]


def codeer_config(configs: list[SensorConfig]) -> bytes:
    fouten = valideer_config(configs)
    if fouten:
        raise ValueError("Ongeldige sampling-configuratie: " + "; ".join(fouten))
    data = len(configs).to_bytes(4, "little") + b"".join(
        bytes([c.sensor_id, c.gain_id, c.rate_id, c.type_id]) for c in configs
    )
    return data.ljust(CONFIG_LENGTE, b"\x00")


def valideer_config(configs: list[SensorConfig]) -> list[str]:
    """Fouten volgens tabel 29 (leeg = geldig)."""
    if not 0 < len(configs) <= 16:
        return [f"{len(configs)} sensoren; moet 1 t/m 16 zijn"]
    fouten = []
    for c in configs:
        if c.sensor_id not in GELDIG:
            fouten.append(f"onbekende sensor {c.sensor_id}")
            continue
        gains, rates, types = GELDIG[c.sensor_id]
        naam = f"sensor {c.sensor_id} ({SENSOREN[c.sensor_id].naam})"
        if c.gain_id not in gains:
            fouten.append(f"{naam}: gain-id {c.gain_id} niet toegestaan")
        if c.rate_id not in rates:
            fouten.append(f"{naam}: sample-rate-id {c.rate_id} niet toegestaan")
        if c.type_id not in types:
            fouten.append(f"{naam}: datatype-id {c.type_id} niet toegestaan")
    return fouten


def config_tekst(configs: list[SensorConfig]) -> str:
    delen = []
    for c in configs:
        naam = SENSOREN[c.sensor_id].naam if c.sensor_id in SENSOREN else f"sensor {c.sensor_id}"
        kanalen = len(SENSOREN[c.sensor_id].kanalen) if c.sensor_id in SENSOREN else 0
        extra = f" {kanalen}-kanaals" if c.sensor_id in ECG_SENSOREN else ""
        delen.append(f"{naam}{extra} {SAMPLE_RATES[c.rate_id]} Hz ×{GAINS[c.gain_id]}")
    return "; ".join(delen)


def pakketgrootte(configs: list[SensorConfig]) -> int:
    return HEADER.size + sum(c.blokgrootte for c in configs)


# --- datapakketten (§6) ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DataPakket:
    tijd: float  # Unix-tijd (s) van de laatste sample, inclusief ticks
    status: int  # bit 0 logt, bit 1 streamt, bit 2-3 BLE, bit 4-5 batterij in kwarten (§6.1.3)
    crc_ok: bool
    sensoren: list[tuple[SensorConfig, np.ndarray]]  # analoge waarden, samples × elementen


def crc(payload: bytes) -> int:
    """CRC-16-CCITT (0x1021, start 0xFFFF). Op echte data: alleen over de payload, opgeslagen als little-endian."""
    return binascii.crc_hqx(payload, 0xFFFF)


def parse_datapakket(pakket: bytes, configs: list[SensorConfig]) -> DataPakket:
    tijd, ticks, status, grootte, checksum = HEADER.unpack_from(pakket)
    payload = pakket[HEADER.size:HEADER.size + grootte]
    verwacht = sum(c.blokgrootte for c in configs)
    if grootte != verwacht or len(payload) != grootte:
        raise ValueError(f"Payload is {grootte} bytes volgens de header ({len(payload)} ontvangen), verwacht {verwacht}.")
    sensoren = []
    positie = 0
    rij = np.frombuffer(payload, dtype=np.uint8)
    for c in configs:
        blok = rij[positie:positie + c.blokgrootte].reshape(1, -1)
        positie += c.blokgrootte
        sensoren.append((c, decodeer_blok(c, blok)))
    return DataPakket(tijd + ticks / TICKS_PER_SECONDE, status, crc(payload) == checksum, sensoren)


def codeer_waarden(config: SensorConfig, analoog: np.ndarray) -> bytes:
    """Omgekeerde van ``decodeer_blok`` (voor de simulator en tests): analoog (samples × elementen) -> bytes."""
    dt = config.datatype
    schaal = (dt.analoog_max - dt.analoog_min) / (dt.digitaal_max - dt.digitaal_min)
    digitaal = np.rint((np.asarray(analoog, dtype=np.float64) * config.gain - dt.analoog_max) / schaal + dt.digitaal_max)
    digitaal = np.clip(digitaal, dt.digitaal_min, dt.digitaal_max).astype(np.int64).reshape(-1)
    breedte = dt.grootte // dt.elementen
    return b"".join(int(d).to_bytes(breedte, "little", signed=dt.signed) for d in digitaal)


def maak_datapakket(tijd: float, status: int, configs: list[SensorConfig], waarden: list[np.ndarray]) -> bytes:
    payload = b"".join(codeer_waarden(c, w) for c, w in zip(configs, waarden))
    seconden = int(tijd)
    ticks = int(round((tijd - seconden) * TICKS_PER_SECONDE))
    return HEADER.pack(seconden, ticks, status, len(payload), crc(payload)) + payload
