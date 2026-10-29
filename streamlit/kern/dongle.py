"""Verbinding met de 2M BLE-dongle: de echte seriële poort, of een gesimuleerde dongle met recorder.

Een achtergrondthread leest regels, en stuurt ze door: ``$S`` naar de status, ``$R`` uit het streamgeheugen naar de
stream-callback, andere ``$R`` naar het wachtende verzoek. Er loopt steeds maar één verzoek tegelijk: de dongle en de
recorder kunnen er niet meer aan.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from . import pcardio_protocol as p
from .pcardio import SensorConfig

BAUDRATE = 460800
DONGLE_NAAM = "2M BLE Dongle"
# pyserial geeft op Windows de 'bus reported device description' niet door; daarom ook op VID:PID (Nordic).
DONGLE_VID_PID = (0x1915, 0x521A)
VERZOEK_TIMEOUT_S = 2.0
SCHRIJF_TIMEOUT_S = 1.0
LOG_REGELS = 300


def poorten() -> list[tuple[str, str]]:
    """(poort, omschrijving) van alle seriële poorten, de dongle eerst."""
    from serial.tools import list_ports

    gevonden = []
    for info in list_ports.comports():
        is_dongle = DONGLE_NAAM in f"{info.description} {info.product}" or (info.vid, info.pid) == DONGLE_VID_PID
        gevonden.append((not is_dongle, info.device, f"{info.device}: {info.description}" + (" (dongle)" if is_dongle else "")))
    return [(poort, tekst) for _, poort, tekst in sorted(gevonden)]


def zoek_dongle() -> str | None:
    gevonden = [poort for poort, tekst in poorten() if tekst.endswith("(dongle)")]
    return gevonden[0] if gevonden else None


class Dongle:
    """Gemeenschappelijk deel. Subklassen leveren ``_lees``, ``_schrijf`` en ``_sluit``."""

    def __init__(self) -> None:
        self.status: p.DongleStatus | None = None
        self.fout: str | None = None  # gezet als de leesthread stopt door een fout (bijv. dongle eruit getrokken)
        self.log: deque[tuple[float, str, str]] = deque(maxlen=LOG_REGELS)
        self.ongeldige_regels = 0
        self.op_status: Callable[[p.DongleStatus], None] | None = None
        self._stream: Callable[[p.CoreData], None] | None = None
        self._antwoorden: queue.Queue[p.CoreData] = queue.Queue()
        self._status_gezien = threading.Event()
        self._een_tegelijk = threading.Lock()
        self._lezer = p.RegelLezer()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._lus, name="dongle-lezer", daemon=True)
        self._thread.start()

    # --- subklassen ---

    def _lees(self) -> bytes:
        raise NotImplementedError

    def _schrijf(self, data: bytes) -> None:
        raise NotImplementedError

    def _sluit(self) -> None:
        raise NotImplementedError

    # --- lezen ---

    def _lus(self) -> None:
        try:
            while not self._stop.is_set():
                for regel in self._lezer.voeg_toe(self._lees()):
                    self._verwerk(regel)
        except Exception as fout:  # noqa: BLE001 - elke fout hier betekent: verbinding weg
            if not self._stop.is_set():
                self.fout = f"Verbinding met de dongle verbroken: {fout}"

    def _verwerk(self, regel: bytes) -> None:
        self.log.append((time.time(), "<<", regel.decode("ascii", "replace")))
        bericht = p.parse_regel(regel)
        if bericht is None:
            self.ongeldige_regels += 1
            return
        opcode, data = bericht
        if opcode == "S":
            self.status = p.parse_status(data)
            self._status_gezien.set()
            if self.op_status and self.status:
                self.op_status(self.status)
            return
        core = p.parse_core(data)
        if core is None:
            self.ongeldige_regels += 1
        elif core.adres >= p.STREAM_ADRES:
            if self._stream:
                self._stream(core)
            # Zonder stream (net na Abort nagekomen): weggooien.
        else:
            self._antwoorden.put(core)

    # --- schrijven ---

    def stuur(self, opcode: str, data: bytes = b"") -> None:
        regel = p.frame(opcode, data)
        self.log.append((time.time(), ">>", regel.decode("ascii").rstrip()))
        self._schrijf(regel)

    def vraag_status(self, timeout: float = VERZOEK_TIMEOUT_S) -> p.DongleStatus:
        self._status_gezien.clear()
        self.stuur("S")
        if not self._status_gezien.wait(timeout) or self.status is None:
            raise TimeoutError("De dongle geeft geen antwoord op een statusvraag.")
        return self.status

    def _verzoek(self, pakket: bytes, adres: int, lengte: int, timeout: float) -> bytes:
        if not self._een_tegelijk.acquire(timeout=timeout):
            raise TimeoutError("Er loopt nog een ander verzoek naar de recorder.")
        try:
            while not self._antwoorden.empty():
                self._antwoorden.get_nowait()
            samen = p.Samenvoeger(adres, lengte)
            self.stuur("T", pakket)
            einde = time.monotonic() + timeout
            while (over := einde - time.monotonic()) > 0:
                try:
                    blok = samen.voeg_toe(self._antwoorden.get(timeout=over))
                except queue.Empty:
                    break
                if blok is not None:
                    return blok
            raise TimeoutError(f"Geen (volledig) antwoord van de recorder op adres {adres} binnen {timeout:.0f} s.")
        finally:
            self._een_tegelijk.release()

    def lees(self, adres: int, lengte: int, timeout: float = VERZOEK_TIMEOUT_S) -> bytes:
        if self._stream:
            raise RuntimeError("Niet lezen tijdens het streamen: eerst stoppen.")
        return self._verzoek(p.lees_pakket(adres, lengte), adres, lengte, timeout)

    def schrijf(self, adres: int, data: bytes, timeout: float = VERZOEK_TIMEOUT_S) -> None:
        """De recorder bevestigt een schrijfopdracht met een echo van het Data-pakket."""
        if self._stream:
            raise RuntimeError("Niet schrijven tijdens het streamen: eerst stoppen.")
        if self._verzoek(p.data_pakket(adres, data), adres, len(data), timeout) != data:
            raise RuntimeError(f"De recorder bevestigde de schrijfopdracht op adres {adres} met andere data.")

    def start_stream(self, lengte: int, callback: Callable[[p.CoreData], None]) -> None:
        self._stream = callback
        self.stuur("T", p.stream_pakket(lengte))

    def stop_stream(self) -> None:
        self.stuur("T", p.ABORT_PAKKET)
        self._stream = None

    def vergeet_stream(self) -> None:
        """Na een verbroken verbinding: geen Abort meer sturen, alleen niets meer doorgeven."""
        self._stream = None

    @property
    def leeft(self) -> bool:
        return self._thread.is_alive()

    def sluit(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sluit()


class SerieleDongle(Dongle):
    def __init__(self, poort: str) -> None:
        import serial

        try:
            # write_timeout: zonder blijft een schrijfopdracht eeuwig hangen als de dongle vastloopt (gezien op
            # echte hardware; het proces was daarna alleen nog te stoppen door de dongle eruit te trekken).
            self._poort = serial.Serial(
                poort, BAUDRATE, bytesize=8, parity="N", stopbits=1, timeout=0.05, write_timeout=SCHRIJF_TIMEOUT_S,
            )
        except serial.SerialException as fout:
            raise ConnectionError(
                f"Kan {poort} niet openen. Is de PCardio-app of een ander programma nog verbonden met de dongle? ({fout})",
            ) from fout
        self._poort.dtr = True
        super().__init__()

    def _lees(self) -> bytes:
        return self._poort.read(self._poort.in_waiting or 1)

    def _schrijf(self, data: bytes) -> None:
        import serial

        try:
            self._poort.write(data)
        except serial.SerialTimeoutException as fout:
            raise ConnectionError(
                "De dongle neemt geen data meer aan. Trek hem uit de USB-poort, steek hem er opnieuw in en verbind opnieuw.",
            ) from fout

    def _sluit(self) -> None:
        self._poort.close()


# --- simulator ----------------------------------------------------------------------------------------------


def synthetisch_ecg(t: np.ndarray, hartslag: float = 70.0) -> np.ndarray:
    """PQRST-achtig signaal in mV (som van gaussen per slag) met wat ruis en ademhalingsdrift."""
    periode = 60.0 / hartslag
    fase = np.mod(t, periode) / periode
    golven = [(0.12, 0.16, 0.025), (-0.12, 0.26, 0.008), (1.1, 0.28, 0.01), (-0.25, 0.30, 0.008), (0.3, 0.55, 0.04)]
    ecg = sum(a * np.exp(-((fase - mu) ** 2) / (2 * s**2)) for a, mu, s in golven)
    rng = np.random.default_rng()
    return ecg + 0.1 * np.sin(2 * np.pi * 0.25 * t) + rng.normal(0, 0.015, t.shape)


class SimDongle(Dongle):
    """Dongle plus recorder in software, met hetzelfde byteformaat als de echte hardware (zie de probe):
    antwoorden in Data-pakketten van max. 237 bytes op opeenvolgende adressen, echo bij schrijven, $S ongevraagd na
    $I en $D, 5 datapakketten per seconde."""

    def __init__(self, configs: list[SensorConfig] | None = None, verbind_na_s: float = 0.3) -> None:
        self.configs = list(p.STANDAARD_CONFIG if configs is None else configs)
        self.verbind_na_s = verbind_na_s
        self.geschreven: list[tuple[int, bytes]] = []
        self.logt = False  # of de gesimuleerde recorder zelf opneemt (bit 0 van de apparaatstatus)
        self._uit = bytearray()
        self._toestand = p.DongleStatus.IDLE
        self._verbonden_om: float | None = None
        self._stream_lengte: int | None = None
        self._volgend_pakket = 0.0
        self._pakket_tijd = 0.0
        self._tijd0 = time.time()
        self._slot = threading.Lock()
        super().__init__()

    def _antwoord(self, opcode: str, data: bytes) -> None:
        self._uit += p.frame(opcode, data)

    def _status(self) -> None:
        self._antwoord("S", bytes([self._toestand, 0xF4]))

    def _schrijf(self, data: bytes) -> None:
        with self._slot:
            opcode = chr(data[1])
            if opcode == "S":
                self._status()
            elif opcode in "CW":
                self._toestand = p.DongleStatus.SCANNEN
                self._verbonden_om = time.monotonic() + self.verbind_na_s
            elif opcode == "I":
                if self._toestand == p.DongleStatus.SCANNEN:
                    self._toestand = p.DongleStatus.IDLE
                self._status()
            elif opcode == "D":
                self._toestand, self._stream_lengte = p.DongleStatus.IDLE, None
                self._status()
            elif opcode == "T" and self._toestand == p.DongleStatus.VERBONDEN:
                self._core(bytes.fromhex(data[2:].strip().decode("ascii")))

    def _core(self, pakket: bytes) -> None:
        if pakket[0] == p.OP_ABORT:
            self._stream_lengte = None
            return
        _, adres, lengte = p._CORE_HEADER.unpack_from(pakket)
        if pakket[0] == p.OP_LEES:
            for stuk in p.splits(adres, self._geheugen(adres, lengte)):
                self._antwoord("R", stuk)
        elif pakket[0] == p.OP_DATA:
            data = pakket[p._CORE_HEADER.size:]
            self.geschreven.append((adres, data))
            if adres == p.CONFIG_ADRES:
                self.configs = p.decodeer_config(data)
            self._antwoord("R", pakket)
        elif pakket[0] == p.OP_STREAM:
            self._stream_lengte = lengte
            self._volgend_pakket = time.monotonic()
            self._pakket_tijd = time.time()

    def _geheugen(self, adres: int, lengte: int) -> bytes:
        info = (
            (0x0102030405060708).to_bytes(8, "little") + (0xAABBCCDDEEFF).to_bytes(8, "little")
            + bytes([3, 3, 1, 1]) + bytes(4) + bytes(4) + (100).to_bytes(4, "little")
            + int(self.logt).to_bytes(4, "little") + bytes(8) + bytes([0, 2])
        )
        geheugen = bytearray(512)
        geheugen[:len(info)] = info
        geheugen[p.CONFIG_ADRES:p.CONFIG_ADRES + p.CONFIG_LENGTE] = p.codeer_config(self.configs)
        return bytes(geheugen[adres:adres + lengte])

    def _datapakket(self, t_eind: float) -> bytes:
        waarden = []
        for c in self.configs:
            n = c.samples_per_pakket
            t = t_eind - (n - 1 - np.arange(n)) / c.rate - self._tijd0
            if c.sensor_id in p.ECG_SENSOREN:
                ecg = synthetisch_ecg(t)
                waarden.append(np.column_stack([ecg, 1.3 * ecg])[:, :c.datatype.elementen])
            elif c.sensor_id == p.BATTERIJ_SENSOR:
                waarden.append(np.full((n, 1), 100.0))
            else:
                waarden.append(np.zeros((n, c.datatype.elementen)))
        status = 0b0011_1010 | self.logt  # streamt, BLE verbonden, batterij 75-100 % (zoals op de echte recorder)
        return p.maak_datapakket(t_eind, status, self.configs, waarden)

    def _lees(self) -> bytes:
        time.sleep(0.01)
        with self._slot:
            nu = time.monotonic()
            if self._toestand == p.DongleStatus.SCANNEN and self._verbonden_om and nu >= self._verbonden_om:
                self._toestand = p.DongleStatus.VERBONDEN
            if self._stream_lengte and nu >= self._volgend_pakket:
                self._volgend_pakket += 1 / p.PAKKETTEN_PER_SECONDE
                # Eigen klok in stappen van precies 0,2 s, zoals de recorder (anders overlappen pakketten door jitter).
                self._pakket_tijd += 1 / p.PAKKETTEN_PER_SECONDE
                pakket = self._datapakket(self._pakket_tijd)
                for stuk in p.splits(p.STREAM_ADRES, pakket[:self._stream_lengte]):
                    self._antwoord("R", stuk)
            uit, self._uit = bytes(self._uit), bytearray()
        return uit

    def _sluit(self) -> None:
        pass
