"""Live sessie met één P-Cardio via de dongle: verbinden, info en configuratie lezen, ECG streamen in een ringbuffer.

De volgorde komt uit de handleiding (§10) en de probe op echte hardware:
verbinden (``$C``/``$W``) → ``$I`` (stop met zoeken) → pincode → info + configuratie lezen → stream → Abort → ``$D``.
Nooit lezen of schrijven tijdens het streamen. De configuratie wordt alleen geschreven met ``bevestigd=True``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from . import pcardio_protocol as p
from .dongle import Dongle
from .pcardio import DATATYPES, SENSOREN, SensorConfig

VERBIND_TIMEOUT_S = 30.0
BUFFER_S = 10.0
PAKKET_INTERVAL_S = 1 / p.PAKKETTEN_PER_SECONDE
GAT_MARGE_S = 0.05  # afwijking van 0,2 s tussen pakketten die als gat telt
GEEN_DATA_S = 2.0  # zo lang zonder pakket = waarschuwing in de app
STIL_S = 10.0  # zo lang zonder pakket tijdens het streamen = verbinding kwijt (ook als de dongle niets meldt)
HERVERBIND_POGING_S = 20.0  # zoeken per poging om opnieuw te verbinden
HERVERBIND_PAUZE_S = 5.0  # pauze tussen twee pogingen


class RingBuffer:
    """De laatste ``seconden`` aan samples per kanaal, met tijden. Veilig vanuit meerdere threads."""

    def __init__(self, seconden: float = BUFFER_S) -> None:
        self.seconden = seconden
        self._slot = threading.Lock()
        self.reset(1.0, ())

    def reset(self, fs: float, kanalen: tuple[str, ...]) -> None:
        with self._slot:
            self.fs, self.kanalen = fs, kanalen
            n = max(1, int(self.seconden * fs))
            self._t = np.full(n, np.nan)
            self._w = np.full((n, len(kanalen)), np.nan)
            self._positie = 0
            self._aantal = 0

    def voeg_toe(self, t_eind: float, waarden: np.ndarray) -> None:
        """``waarden``: samples × kanalen; de laatste sample hoort bij ``t_eind``."""
        n = len(waarden)
        t = t_eind - (n - 1 - np.arange(n)) / self.fs
        with self._slot:
            index = (self._positie + np.arange(n)) % len(self._t)
            self._t[index] = t
            self._w[index] = waarden
            self._positie = (self._positie + n) % len(self._t)
            self._aantal = min(self._aantal + n, len(self._t))

    def lees(self) -> tuple[np.ndarray, np.ndarray]:
        """Kopie in tijdvolgorde: (tijden, waarden)."""
        with self._slot:
            index = (self._positie - self._aantal + np.arange(self._aantal)) % len(self._t)
            return self._t[index].copy(), self._w[index].copy()


class LiveSessie:
    """Toestanden: ``los`` → ``verbinden`` → ``verbonden`` ⇄ ``streamen``; ``bezig`` tijdens kortere stappen.

    Valt de verbinding weg (de dongle meldt het, of er komt ``STIL_S`` seconden geen data), dan is ``verbroken`` True
    en probeert de sessie, als ``automatisch_herverbinden`` aan staat, steeds opnieuw te verbinden; liep de stream,
    dan start die daarna vanzelf weer. Handmatig kan dat met ``herverbind()``.
    """

    def __init__(self, dongle: Dongle) -> None:
        self.dongle = dongle
        self.toestand = "los"
        self.melding: tuple[str, str] | None = None  # (soort, tekst): 'info', 'warning' of 'error'
        self.info: p.Info | None = None
        self.configs: list[SensorConfig] = []
        self.buffer = RingBuffer()
        self.lead_off: bool | None = None
        self.batterij: int | None = None
        self.tellers = {"pakketten": 0, "crc_fout": 0, "onvolledig": 0, "tijdgaten": 0}
        self._samen: p.Samenvoeger | None = None
        self._vorige_tijd: float | None = None
        self._laatste_pakket: float | None = None
        self._werk: threading.Thread | None = None
        self.automatisch_herverbinden = True
        self.verbroken = False  # verbinding onverwacht weggevallen en nog niet hersteld
        self._verbind_args: dict = {}
        self._was_streamen = False
        self._kwijt_slot = threading.Lock()
        self._stop_herverbinden = threading.Event()
        self._gesloten = threading.Event()
        dongle.op_status = lambda status: status.verbonden or self._verbinding_kwijt()
        threading.Thread(target=self._waakhond, name="live-waakhond", daemon=True).start()

    # --- achtergrond: de app mag nooit wachten op de dongle ---

    @property
    def bezig(self) -> bool:
        return self._werk is not None and self._werk.is_alive()

    def op_achtergrond(self, stap: Callable[..., None], *args, **kwargs) -> bool:
        """Voert ``stap`` uit in een thread. False als er al een stap loopt."""
        if self.bezig:
            return False

        def uitvoeren() -> None:
            try:
                stap(*args, **kwargs)
            except Exception as fout:  # noqa: BLE001 - elke fout gaat als melding naar de app
                self.melding = ("error", str(fout))
                if self.toestand in ("verbinden", "bezig"):
                    self.toestand = "verbonden" if self.info else "los"

        self.melding = None
        self._werk = threading.Thread(target=uitvoeren, name=f"live-{stap.__name__}", daemon=True)
        self._werk.start()
        return True

    # --- stappen (blokkerend; vanuit de app via op_achtergrond) ---

    def verbind(self, mac: str | None = None, mac_omgekeerd: bool = False, timeout: float = VERBIND_TIMEOUT_S) -> None:
        if self.toestand != "los":
            raise RuntimeError(f"Al verbonden (toestand: {self.toestand}).")
        self._verbind_args = {"mac": mac, "mac_omgekeerd": mac_omgekeerd}
        self.toestand = "verbinden"
        if self.dongle.vraag_status().verbonden:
            # Nog verbonden van een eerdere sessie die niet netjes afsloot: misschien streamt de recorder nog.
            self.dongle.stop_stream()
            time.sleep(0.3)
        else:
            if mac:
                self.dongle.stuur("W", p.whitelist_data(mac, mac_omgekeerd))
            else:
                self.dongle.stuur("C", p.PCARDIO_NAAM)
            einde = time.monotonic() + timeout
            while not self.dongle.vraag_status().verbonden:
                if time.monotonic() > einde:
                    self.dongle.stuur("I")
                    self.toestand = "los"
                    raise TimeoutError(
                        f"Geen recorder gevonden binnen {timeout:.0f} s. Druk kort op de knop van de P-Cardio "
                        f"(BLE gaat dan adverteren) en probeer opnieuw.",
                    )
                time.sleep(0.5)
        self.dongle.stuur("I")
        time.sleep(0.2)
        self.dongle.schrijf(p.PIN_ADRES, p.PIN)
        self._lees_apparaat()
        self.toestand = "verbonden"
        if self.ecg is None:
            self.melding = ("warning", "De recorder meet nu geen ECG. Schrijf eerst een configuratie met ECG.")

    def _lees_apparaat(self) -> None:
        self.info = p.Info.van_bytes(self.dongle.lees(p.INFO_ADRES, p.INFO_LENGTE))
        self.configs = p.decodeer_config(self.dongle.lees(p.CONFIG_ADRES, p.CONFIG_LENGTE))

    @property
    def ecg(self) -> SensorConfig | None:
        return next((c for c in self.configs if c.sensor_id in p.ECG_SENSOREN), None)

    def start(self) -> None:
        if self.toestand != "verbonden":
            raise RuntimeError(f"Eerst verbinden (toestand: {self.toestand}).")
        ecg = self.ecg
        if ecg is None:
            raise RuntimeError("De recorder meet geen ECG; er valt niets te tonen.")
        onbekend = [c for c in self.configs if c.sensor_id not in SENSOREN or c.type_id not in DATATYPES]
        if onbekend:
            raise RuntimeError(f"Onbekende sensor of datatype in de configuratie: {onbekend}.")
        grootte = p.pakketgrootte(self.configs)
        self.buffer.reset(ecg.rate, SENSOREN[ecg.sensor_id].kanalen)
        self.tellers = dict.fromkeys(self.tellers, 0)
        self._samen = p.Samenvoeger(p.STREAM_ADRES, grootte)
        self._vorige_tijd = None
        self._laatste_pakket = time.monotonic()
        self.toestand = "streamen"
        self.dongle.start_stream(grootte, self._stuk)

    def stop(self) -> None:
        if self.toestand != "streamen":
            return
        self.toestand = "bezig"
        self.dongle.stop_stream()
        time.sleep(0.3)  # nagekomen stukken worden door de dongle-thread weggegooid
        self.toestand = "verbonden"

    def ontkoppel(self) -> None:
        if self.toestand == "streamen":
            self.stop()
        self.toestand = "bezig"  # het ongevraagde $S00 na $D is dan geen 'verbinding verbroken'
        self.dongle.stuur("D")
        time.sleep(0.2)
        self.toestand = "los"
        self.verbroken = False
        self.info = None
        self.configs = []

    def schrijf_config(self, configs: list[SensorConfig], bevestigd: bool = False) -> None:
        """Schrijft de sampling-configuratie. Dat verandert ook wat de recorder zelf opslaat, dus alleen na expliciete
        bevestiging, en alleen als de recorder niet aan het loggen is."""
        if not bevestigd:
            raise PermissionError("De configuratie wordt alleen geschreven na bevestiging.")
        if self.toestand != "verbonden":
            raise RuntimeError(f"Alleen schrijven als de recorder verbonden is en niet streamt (toestand: {self.toestand}).")
        data = p.codeer_config(configs)
        self.toestand = "bezig"
        try:
            self._lees_apparaat()
            if self.info and self.info.logt:
                raise RuntimeError("De recorder is aan het loggen: de configuratie kan nu niet veranderen (foutcode 5).")
            voor = self.dongle.lees(p.FOUTCODE_ADRES, 8)
            self.dongle.schrijf(p.CONFIG_ADRES, data)
            na = self.dongle.lees(p.FOUTCODE_ADRES, 8)
            code = int.from_bytes(na[:4], "little") if na != voor else 0  # code + tijd ongewijzigd = geen nieuwe fout
            self._lees_apparaat()
            if code:
                self.melding = ("error", f"De recorder weigerde de configuratie: foutcode {code} "
                                         f"({p.FOUTCODES.get(code, 'onbekend')}).")
            else:
                self.melding = ("info", "Configuratie geschreven en teruggelezen.")
        finally:
            self.toestand = "verbonden"

    def sluit(self) -> None:
        """Netjes afsluiten, ook na fouten: stream stoppen, ontkoppelen, poort dicht."""
        self._stop_herverbinden.set()
        self._gesloten.set()
        try:
            if self.toestand not in ("los",) and self.dongle.leeft:
                self.ontkoppel()
        except Exception:  # noqa: BLE001 - de poort moet hoe dan ook dicht
            pass
        finally:
            self.dongle.sluit()

    # --- vanuit de dongle-thread ---

    def _waakhond(self) -> None:
        """Merkt ook een verbroken verbinding op als de dongle niets meldt: dan stopt alleen de data."""
        while not self._gesloten.wait(1.0):
            stil = self.seconden_zonder_data
            if stil is not None and stil > STIL_S:
                self._verbinding_kwijt()

    def _verbinding_kwijt(self) -> None:
        with self._kwijt_slot:
            if self.toestand not in ("verbonden", "streamen"):
                return
            self._was_streamen = self.toestand == "streamen"
            self.dongle.vergeet_stream()
            self.toestand = "los"
            self.verbroken = True
        if not (self.automatisch_herverbinden and not self._gesloten.is_set() and self.herverbind()):
            self.melding = ("error", "Verbinding met de recorder verbroken (buiten bereik, uitgezet of batterij leeg?). "
                                     "Klik op Opnieuw verbinden als de recorder weer in de buurt is.")

    # --- opnieuw verbinden ---

    @property
    def herverbindt(self) -> bool:
        return self.verbroken and self.bezig

    def herverbind(self) -> bool:
        """Probeert opnieuw te verbinden tot het lukt of ``stop_herverbinden()``; start daarna de stream als die liep.
        Draait op de achtergrond. False als er al iets loopt."""
        self._stop_herverbinden.clear()
        return self.op_achtergrond(self._herverbind_lus)

    def stop_herverbinden(self) -> None:
        self._stop_herverbinden.set()

    def _herverbind_lus(self) -> None:
        poging = 0
        while not self._stop_herverbinden.is_set():
            if self.dongle.fout or not self.dongle.leeft:
                self.melding = ("error", (self.dongle.fout or "De dongle reageert niet meer.")
                                + " Klik op Ontkoppelen en verbind opnieuw.")
                return
            poging += 1
            tip = " Lukt het niet? Druk kort op de knop van de P-Cardio." if poging > 2 else ""
            self.melding = ("warning", f"Verbinding met de recorder verbroken. Opnieuw verbinden, poging {poging}…{tip}")
            try:
                self.toestand = "los"
                self.verbind(**self._verbind_args, timeout=HERVERBIND_POGING_S)
            except Exception:  # noqa: BLE001 - niet gevonden of time-out: straks opnieuw
                self.toestand = "los"
                self._stop_herverbinden.wait(HERVERBIND_PAUZE_S)
                continue
            self.verbroken = False
            if self._was_streamen and self.ecg is not None:
                self.start()
            self.melding = ("info", f"Verbinding hersteld na {poging} poging(en)"
                                    + (", het ECG loopt weer." if self.toestand == "streamen" else "."))
            return
        self.melding = ("warning", "Opnieuw verbinden gestopt. Klik op Opnieuw verbinden als de recorder weer in de "
                                   "buurt is.")

    def _stuk(self, stuk: p.CoreData) -> None:
        if self._samen is None:
            return
        pakket = self._samen.voeg_toe(stuk)
        self.tellers["onvolledig"] = self._samen.verloren
        if pakket is None:
            return
        try:
            data = p.parse_datapakket(pakket, self.configs)
        except ValueError:
            self.tellers["crc_fout"] += 1
            return
        self._laatste_pakket = time.monotonic()
        if not data.crc_ok:
            self.tellers["crc_fout"] += 1
            return
        self.tellers["pakketten"] += 1
        if self._vorige_tijd is not None and abs(data.tijd - self._vorige_tijd - PAKKET_INTERVAL_S) > GAT_MARGE_S:
            self.tellers["tijdgaten"] += 1
        self._vorige_tijd = data.tijd
        for config, waarden in data.sensoren:
            if config.sensor_id in p.ECG_SENSOREN and config == self.ecg:
                self.buffer.voeg_toe(data.tijd, waarden)
            elif config.sensor_id == p.LEAD_OFF_SENSOR:
                self.lead_off = bool(np.nanmax(waarden) > 0.5)
            elif config.sensor_id == p.BATTERIJ_SENSOR:
                self.batterij = int(waarden[-1, 0])

    # --- voor de app ---

    @property
    def seconden_zonder_data(self) -> float | None:
        if self.toestand != "streamen" or self._laatste_pakket is None:
            return None
        return time.monotonic() - self._laatste_pakket
