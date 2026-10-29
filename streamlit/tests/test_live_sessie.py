"""Eind-tot-eind met de gesimuleerde dongle: verbinden → streamen → samples in de buffer → stoppen."""

from __future__ import annotations

import time

import numpy as np
import pytest

from kern import pcardio_protocol as p
from kern.dongle import SimDongle
from kern.live_sessie import LiveSessie, RingBuffer
from kern.pcardio import SensorConfig


@pytest.fixture
def sessie():
    sessie = LiveSessie(SimDongle(verbind_na_s=0.1))
    yield sessie
    sessie.sluit()


def _wacht(voorwaarde, timeout: float = 5.0) -> None:
    einde = time.monotonic() + timeout
    while not voorwaarde():
        assert time.monotonic() < einde, "timeout"
        time.sleep(0.05)


def test_verbinden_streamen_stoppen(sessie: LiveSessie) -> None:
    sessie.verbind()
    assert sessie.toestand == "verbonden"
    assert sessie.info.firmware == "3.3.1.1" and sessie.info.hw_variant == 2
    assert sessie.ecg == SensorConfig(3, 4, 4, 3)

    sessie.start()
    _wacht(lambda: sessie.tellers["pakketten"] >= 5)
    t, w = sessie.buffer.lees()
    assert sessie.buffer.kanalen == ("Ecg1", "Ecg2")
    assert w.shape == (len(t), 2) and len(t) >= 250
    assert np.all(np.diff(t) > 0)
    assert 0.8 < np.nanmax(w[:, 0]) < 1.6  # R-top in mV
    assert sessie.tellers["crc_fout"] == sessie.tellers["onvolledig"] == 0
    assert sessie.lead_off is False and sessie.batterij == 100

    sessie.stop()
    assert sessie.toestand == "verbonden"
    aantal = sessie.tellers["pakketten"]
    time.sleep(0.5)
    assert sessie.tellers["pakketten"] == aantal

    sessie.ontkoppel()
    assert sessie.toestand == "los"
    verzonden = [regel for _, richting, regel in sessie.dongle.log if richting == ">>"]
    assert verzonden[-2:] == ["$T03", "$D"]


def test_opnamestatus_volgt_de_stream(sessie: LiveSessie) -> None:
    """Starten/stoppen met de knop op de recorder is zichtbaar zonder opnieuw te verbinden (bit 0 in elk pakket)."""
    sessie.verbind()
    assert sessie.logt is False
    sessie.start()
    _wacht(lambda: sessie.tellers["pakketten"] >= 1)
    sessie.dongle.logt = True  # knop op de recorder ingedrukt
    _wacht(lambda: sessie.logt is True)
    sessie.dongle.logt = False
    _wacht(lambda: sessie.logt is False)
    sessie.ontkoppel()
    assert sessie.logt is None


def test_niets_geschreven_behalve_pincode(sessie: LiveSessie) -> None:
    sessie.verbind()
    sessie.start()
    _wacht(lambda: sessie.tellers["pakketten"] >= 1)
    sessie.stop()
    assert sessie.dongle.geschreven == [(p.PIN_ADRES, p.PIN)]


def test_config_alleen_na_bevestiging() -> None:
    sessie = LiveSessie(SimDongle(configs=[SensorConfig(5, 1, 6, 4)], verbind_na_s=0.1))
    try:
        sessie.verbind()
        assert sessie.ecg is None and sessie.melding[0] == "warning"
        with pytest.raises(RuntimeError):
            sessie.start()
        with pytest.raises(PermissionError):
            sessie.schrijf_config(p.STANDAARD_CONFIG)
        assert sessie.dongle.geschreven == [(p.PIN_ADRES, p.PIN)]

        sessie.schrijf_config(p.STANDAARD_CONFIG, bevestigd=True)
        assert sessie.configs == p.STANDAARD_CONFIG and sessie.melding[0] == "info"
        assert sessie.dongle.geschreven[-1] == (p.CONFIG_ADRES, p.codeer_config(p.STANDAARD_CONFIG))
    finally:
        sessie.sluit()


def test_geen_lezen_tijdens_streamen(sessie: LiveSessie) -> None:
    sessie.verbind()
    sessie.start()
    with pytest.raises(RuntimeError):
        sessie.dongle.lees(p.INFO_ADRES, p.INFO_LENGTE)


def test_verbinden_timeout() -> None:
    sessie = LiveSessie(SimDongle(verbind_na_s=60))
    try:
        with pytest.raises(TimeoutError, match="knop"):
            sessie.verbind(timeout=0.5)
        assert sessie.toestand == "los"
        assert [r for _, d, r in sessie.dongle.log if d == ">>"][-1] == "$I"
    finally:
        sessie.sluit()


def _recorder_weg(sessie: LiveSessie) -> None:
    """Zoals op echte hardware: de BLE-verbinding valt weg en de dongle meldt $S00."""
    sessie.dongle._toestand = p.DongleStatus.IDLE
    sessie.dongle._stream_lengte = None
    sessie.dongle._verwerk(b"$S00F4")


def test_verbinding_verbroken_zonder_automatisch(sessie: LiveSessie) -> None:
    sessie.automatisch_herverbinden = False
    sessie.verbind()
    sessie.start()
    _recorder_weg(sessie)
    assert sessie.toestand == "los" and sessie.verbroken and sessie.melding[0] == "error"
    assert not sessie.bezig  # geen automatische poging

    # Handmatig opnieuw verbinden: dezelfde recorder, en de stream start weer omdat die liep.
    sessie.herverbind()
    _wacht(lambda: sessie.toestand == "streamen" and not sessie.verbroken)
    aantal = sessie.tellers["pakketten"]
    _wacht(lambda: sessie.tellers["pakketten"] > aantal)


def test_automatisch_opnieuw_verbinden(sessie: LiveSessie) -> None:
    sessie.verbind()
    sessie.start()
    _wacht(lambda: sessie.tellers["pakketten"] >= 1)
    _recorder_weg(sessie)
    assert sessie.verbroken
    _wacht(lambda: sessie.toestand == "streamen" and not sessie.verbroken)
    assert sessie.melding[0] == "info" and "hersteld" in sessie.melding[1]
    verzonden = [r for _, d, r in sessie.dongle.log if d == ">>"]
    assert verzonden.count("$C5043617264696F") == 2  # tweede keer zoeken na het wegvallen


def test_stil_zonder_melding_telt_als_verbroken(sessie: LiveSessie, monkeypatch) -> None:
    import kern.live_sessie as ls

    monkeypatch.setattr(ls, "STIL_S", 1.0)
    sessie.verbind()
    sessie.start()
    _wacht(lambda: sessie.tellers["pakketten"] >= 1)
    sessie.dongle._stream_lengte = None  # recorder stuurt niets meer, de dongle meldt niets
    _wacht(lambda: sessie.verbroken or sessie.melding is not None and "hersteld" in sessie.melding[1])
    _wacht(lambda: sessie.toestand == "streamen" and not sessie.verbroken)


def test_opnieuw_verbinden_stoppen(monkeypatch) -> None:
    import kern.live_sessie as ls

    monkeypatch.setattr(ls, "HERVERBIND_POGING_S", 1.0)
    monkeypatch.setattr(ls, "HERVERBIND_PAUZE_S", 0.2)
    sessie = LiveSessie(SimDongle(verbind_na_s=0.1))
    try:
        sessie.verbind()
        sessie.dongle.verbind_na_s = 60  # recorder blijft onvindbaar
        _recorder_weg(sessie)
        _wacht(lambda: sessie.herverbindt)
        sessie.stop_herverbinden()
        _wacht(lambda: not sessie.bezig)
        assert sessie.verbroken and sessie.toestand == "los" and "gestopt" in sessie.melding[1]
    finally:
        sessie.sluit()


def test_ringbuffer_loopt_rond() -> None:
    buffer = RingBuffer(seconden=1.0)
    buffer.reset(10.0, ("a",))
    for i in range(3):
        buffer.voeg_toe(i * 0.5 + 0.4, np.arange(5.0).reshape(-1, 1) + 5 * i)
    t, w = buffer.lees()
    assert len(t) == 10
    np.testing.assert_allclose(t, np.arange(0.5, 1.45, 0.1))
    np.testing.assert_allclose(w[:, 0], np.arange(5.0, 15.0))
