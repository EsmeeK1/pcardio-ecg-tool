from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kern import pcardio_protocol as p
from kern.pcardio import SensorConfig, decodeer_blok

# Ruwe seriële regels van scripts/probe_device.py op echte hardware (19-10-2026); id en MAC vervangen door nepwaarden.
PROBE_LOG = Path(__file__).parent / "fixtures" / "probe_dongle.log"


def _probe_regels(richting: str) -> list[bytes]:
    regels = []
    for regel in PROBE_LOG.read_text(encoding="ascii").splitlines():
        _, r, tekst = regel.split(" ", 2)
        if r == richting:
            regels.append(tekst.encode("ascii"))
    return regels


# --- framing ---


def test_frame_pin_en_config_lezen() -> None:
    assert p.frame("T", p.data_pakket(p.PIN_ADRES, p.PIN)) == b"$T028000000004006C6F7665\n"
    assert p.frame("T", p.lees_pakket(p.CONFIG_ADRES, p.CONFIG_LENGTE)) == b"$T01140100004400\n"
    assert p.frame("C", p.PCARDIO_NAAM) == b"$C5043617264696F\n"
    assert p.frame("D") == b"$D\n"


def test_regellezer_halve_regels_en_rommel() -> None:
    lezer = p.RegelLezer()
    assert lezer.voeg_toe(b"\x00\xff$S0") == []
    assert lezer.voeg_toe(b"2F4\r\n$R01") == [b"\x00\xff$S02F4"]
    assert lezer.voeg_toe(b"02\n\n") == [b"$R0102"]
    assert p.parse_regel(b"\x00\xff$S02F4") == ("S", b"\x02\xf4")
    assert p.parse_regel(b"$R0102") == ("R", b"\x01\x02")


@pytest.mark.parametrize("regel", [b"rommel", b"$", b"$X0102", b"$R0G", b"$R012", b"$T0102"])
def test_parse_regel_negeert_ongeldig(regel: bytes) -> None:
    assert p.parse_regel(regel) is None


def test_regellezer_te_lange_rommel_wordt_weggegooid() -> None:
    lezer = p.RegelLezer()
    lezer.voeg_toe(b"x" * (p.MAX_REGEL + 1))
    assert lezer.voeg_toe(b"$S00F4\n") == [b"$S00F4"]


def test_dongle_status() -> None:
    assert p.parse_status(bytes([2, 0xF4])) == p.DongleStatus(2, 244)
    assert p.parse_status(bytes([2, 0xF4])).verbonden
    assert not p.parse_status(bytes([1, 0xF4])).verbonden
    assert p.parse_status(b"") is None


def test_whitelist_mac() -> None:
    assert p.whitelist_data("F5:6A:BF:A8:D9:F2") == bytes.fromhex("F56ABFA8D9F2")
    assert p.whitelist_data("F56ABFA8D9F2", omgekeerd=True) == bytes.fromhex("F2D9A8BF6AF5")
    with pytest.raises(ValueError):
        p.whitelist_data("F56ABF")


# --- Core Interface: voorbeelden uit de handleiding (tabel 4, 5, 6) ---


def test_core_little_endian_voorbeelden() -> None:
    assert p.lees_pakket(16, 4) == bytes([0x01, 0x10, 0, 0, 0, 0x04, 0x00])
    assert p.data_pakket(16, (1).to_bytes(4, "little")) == bytes([0x02, 0x10, 0, 0, 0, 0x04, 0x00, 1, 0, 0, 0])
    assert p.stream_pakket(237) == bytes([0x04, 0x00, 0x00, 0x00, 0x10, 0xED, 0x00])
    assert p.ABORT_PAKKET == b"\x03"


def test_parse_core() -> None:
    assert p.parse_core(p.data_pakket(16, b"\x01\x02")) == p.CoreData(16, b"\x01\x02")
    assert p.parse_core(p.data_pakket(16, b"\x01\x02")[:-1]) is None  # te kort
    assert p.parse_core(p.lees_pakket(16, 2)) is None  # geen Data-pakket


# --- samenvoegen ---


def _stukken(data: bytes, start: int = p.STREAM_ADRES) -> list[p.CoreData]:
    return [p.parse_core(s) for s in p.splits(start, data)]


def test_samenvoegen_zoals_de_hardware() -> None:
    blok = bytes(range(256)) * 2 + bytes(45)  # 557 bytes -> 237 + 237 + 83
    stukken = _stukken(blok)
    assert [(s.adres - p.STREAM_ADRES, len(s.data)) for s in stukken] == [(0, 237), (237, 237), (474, 83)]
    samen = p.Samenvoeger(p.STREAM_ADRES, len(blok))
    assert [samen.voeg_toe(s) for s in stukken] == [None, None, blok]
    assert samen.verloren == 0


def test_samenvoegen_verloren_stuk() -> None:
    blok = bytes(557)
    a, _, c = _stukken(blok)
    samen = p.Samenvoeger(p.STREAM_ADRES, len(blok))
    assert samen.voeg_toe(a) is None
    assert samen.voeg_toe(c) is None  # sluit niet aan: weg
    assert samen.verloren == 1
    assert [samen.voeg_toe(s) for s in _stukken(blok)][-1] == blok  # volgende pakket weer compleet


def test_samenvoegen_midden_in_beginnen() -> None:
    blok = bytes(557)
    samen = p.Samenvoeger(p.STREAM_ADRES, len(blok))
    _, b, c = _stukken(blok)
    assert samen.voeg_toe(b) is None and samen.voeg_toe(c) is None
    assert samen.verloren == 0


# --- sampling-configuratie ---


def test_config_coderen_en_decoderen() -> None:
    data = p.codeer_config(p.STANDAARD_CONFIG)
    assert len(data) == p.CONFIG_LENGTE
    assert data[:8] == bytes([7, 0, 0, 0, 3, 4, 4, 3])
    assert p.decodeer_config(data) == p.STANDAARD_CONFIG


def test_config_validatie_tabel_29() -> None:
    assert p.valideer_config(p.STANDAARD_CONFIG) == []
    fouten = p.valideer_config([SensorConfig(5, 2, 7, 4)])  # accelerometer x3 bestaat niet (voorbeeld tabel 32)
    assert fouten == ["sensor 5 (acc): gain-id 2 niet toegestaan"]
    assert p.valideer_config([SensorConfig(1, 0, 6, 1)])  # ECG op 100 Hz kan niet
    assert p.valideer_config([])
    with pytest.raises(ValueError):
        p.codeer_config([SensorConfig(99, 0, 0, 0)])


def test_pakketgrootte_voorbeeld_handleiding() -> None:
    # Tabel 32/33 (met een geldige gain): acc 50 Hz, button marker, batterij -> 75 bytes, met een header van 13.
    configs = [SensorConfig(5, 1, 7, 4), SensorConfig(10, 0, 10, 8), SensorConfig(0, 0, 10, 0)]
    assert p.pakketgrootte(configs) == 75
    assert p.pakketgrootte(p.STANDAARD_CONFIG) == 557


# --- datapakketten ---


def test_24_bit_tekenuitbreiding_en_omrekening() -> None:
    ecg = SensorConfig(1, 4, 4, 1)  # 1 kanaal, x6, 250 Hz -> 50 samples per pakket
    ruw = np.zeros((1, ecg.blokgrootte), dtype=np.uint8)
    ruw[0, 0:3] = [0x00, 0x00, 0x80]  # -8388608: digitaal minimum
    ruw[0, 3:6] = [0xFF, 0xFF, 0x7F]  # 8388607: digitaal maximum
    ruw[0, 6:9] = [0xFF, 0xFF, 0xFF]  # -1
    waarden = decodeer_blok(ecg, ruw)[:, 0]
    assert waarden[0] == pytest.approx(-2420 / 6)
    assert waarden[1] == pytest.approx(2420 / 6)
    assert waarden[2] == pytest.approx(-2420 / 6 / 8388607.5 * 0.5, abs=1e-3)


def test_crc() -> None:
    assert p.crc(b"123456789") == 0x29B1  # CRC-16/CCITT-FALSE controlewaarde


def test_datapakket_heen_en_terug() -> None:
    configs = p.STANDAARD_CONFIG
    ecg = np.column_stack([np.linspace(-1, 1, 50), np.linspace(2, -2, 50)])
    waarden = [ecg] + [np.zeros((c.samples_per_pakket, c.datatype.elementen)) for c in configs[1:]]
    pakket = p.maak_datapakket(1_800_000_000.5, 0b0011_1010, configs, waarden)
    assert len(pakket) == 557
    data = p.parse_datapakket(pakket, configs)
    assert data.crc_ok and data.status == 0b0011_1010
    assert data.tijd == pytest.approx(1_800_000_000.5)
    np.testing.assert_allclose(data.sensoren[0][1], ecg, atol=1e-3)
    beschadigd = pakket[:20] + bytes([pakket[20] ^ 1]) + pakket[21:]
    assert not p.parse_datapakket(beschadigd, configs).crc_ok


def test_datapakket_verkeerde_grootte() -> None:
    with pytest.raises(ValueError):
        p.parse_datapakket(bytes(557), [SensorConfig(1, 0, 0, 1)])


# --- echte hardware ---


def _probe_core() -> list[p.CoreData]:
    berichten = [p.parse_regel(r) for r in _probe_regels("<<")]
    return [p.parse_core(data) for opcode, data in berichten if opcode == "R"]


def test_probe_verzonden_regels() -> None:
    verzonden = [r.decode() for r in _probe_regels(">>")]
    assert verzonden[:4] == ["$S", "$C5043617264696F", "$S", "$S"]
    assert "$T028000000004006C6F7665" in verzonden
    assert "$T01140100004400" in verzonden


def test_probe_info_en_config() -> None:
    antwoorden = {c.adres: c.data for c in _probe_core() if c.adres < p.STREAM_ADRES}
    assert antwoorden[p.PIN_ADRES] == p.PIN  # echo van de schrijfopdracht
    info = p.Info.van_bytes(antwoorden[p.INFO_ADRES])
    assert info.id == 0x0102030405060708
    assert info.firmware == "3.3.1.1"
    assert (info.batterij, info.hw_versie, info.hw_variant) == (100, 0, 2)
    assert p.decodeer_config(antwoorden[p.CONFIG_ADRES]) == p.STANDAARD_CONFIG


def test_probe_stream() -> None:
    samen = p.Samenvoeger(p.STREAM_ADRES, p.pakketgrootte(p.STANDAARD_CONFIG))
    pakketten = [b for c in _probe_core() if c.adres >= p.STREAM_ADRES if (b := samen.voeg_toe(c)) is not None]
    assert len(pakketten) == 17 and samen.verloren == 0
    data = [p.parse_datapakket(pk, p.STANDAARD_CONFIG) for pk in pakketten]
    assert all(d.crc_ok and d.status & 0b10 for d in data)  # streamt
    assert np.diff([d.tijd for d in data]) == pytest.approx(0.2, abs=0.01)
    # Elektroden zaten niet op iemand: ECG verzadigd op het digitale minimum (-2420 mV / gain 6).
    assert data[5].sensoren[0][1].min() == pytest.approx(-2420 / 6)
