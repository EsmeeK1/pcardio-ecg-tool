"""Telefoon-app (mobiel/): de annotatie-CSV moet door Koppelen, en het Bluetooth-protocol moet hetzelfde decoderen
als de Python-code in kern/."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kern import pcardio_protocol as p
from kern.export import bestandssoort
from kern.opslag import ANNOTATIE_KOLOMMEN, lees_annotaties

MOBIEL = Path(__file__).resolve().parents[2] / "mobiel"
MODULE = (MOBIEL / "annotaties.js").as_uri()
geen_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is niet geïnstalleerd")


def _node(script: str) -> str:
    return subprocess.run(
        ["node", "--input-type=module"], input=script, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout

SCRIPT = f"""
import {{ moment, naarCsv, startPeriode, stopPeriode, sync, verwijder }} from "{MODULE}";
const t = Date.parse("2026-11-04T18:00:00Z"), l = [];
sync(l, t);
startPeriode(l, "Bicep curl, set 1", t + 1000);
moment(l, 'hoest "kort"', t + 1500);
startPeriode(l, "fout geklikt", t + 2000);
startPeriode(l, "Staan", t + 2500);
verwijder(l, 4);
stopPeriode(l, t + 4000);
moment(l, "zomertijd", Date.parse("2026-07-01T10:00:00Z"));
process.stdout.write(naarCsv(l));
"""


@geen_node
def test_csv_van_mobiel_gaat_door_koppelen(tmp_path):
    uit = _node(SCRIPT)
    pad = tmp_path / "annotaties.csv"
    pad.write_text(uit, encoding="utf-8")

    assert uit.splitlines()[0] == ",".join(ANNOTATIE_KOLOMMEN)
    assert bestandssoort(pad) == "annotaties"
    annotaties, correctie = lees_annotaties(pad)
    assert correctie is None
    assert [(a.id, a.soort, a.label) for a in annotaties] == [
        (1, "sync", "sync-sprong"),
        (2, "periode", "Bicep curl, set 1"),
        (3, "moment", 'hoest "kort"'),
        (5, "periode", "Staan"),
        (6, "moment", "zomertijd"),
    ]
    assert {a.tijdbasis for a in annotaties} == {"pc"}

    t = pd.Timestamp("2026-11-04T18:00:00Z")
    curl, staan, zomer = annotaties[1], annotaties[3], annotaties[4]
    assert (curl.t_start, curl.t_eind) == (t + pd.Timedelta("1s"), t + pd.Timedelta("2s"))  # gestopt door volgende
    assert (staan.t_start, staan.t_eind) == (t + pd.Timedelta("2.5s"), t + pd.Timedelta("4s"))
    assert zomer.t_start == pd.Timestamp("2026-07-01T10:00:00Z") and zomer.t_eind is None


@geen_node
def test_bluetooth_protocol_decodeert_als_python():
    configs = p.STANDAARD_CONFIG
    waarden = []
    for c in configs:
        dt = c.datatype
        midden, uitslag = (dt.analoog_max + dt.analoog_min) / 2 / c.gain, (dt.analoog_max - dt.analoog_min) / 4 / c.gain
        waarden.append(midden + uitslag * np.linspace(-1, 1, c.samples_per_pakket * dt.elementen).reshape(-1, dt.elementen))
    pakket = p.maak_datapakket(1_762_279_200.25, 0b11, configs, waarden)
    # Zoals de recorder streamt (Data-pakketten van max. 237 bytes), hier verdeeld over notificaties van 100 bytes.
    stroom = b"".join(p.splits(p.STREAM_ADRES, pakket))
    notificaties = [stroom[i:i + 100].hex() for i in range(0, len(stroom), 100)]
    kapot = bytearray(pakket)
    kapot[-1] ^= 0xFF
    script = f"""
    import {{ CONFIG_ADRES, CONFIG_LENGTE, CoreStroom, PIN, PIN_ADRES, STREAM_ADRES, Samenvoeger, dataPakket,
      decodeerConfig, leesPakket, pakketgrootte, parseDatapakket, streamPakket }} from "{(MOBIEL / "pcardio.js").as_uri()}";
    const hex = (h) => Uint8Array.from(h.match(/../g), (x) => parseInt(x, 16));
    const naarHex = (b) => Buffer.from(b).toString("hex");
    const configs = decodeerConfig(hex("{p.codeer_config(configs).hex()}"));
    const stroom = new CoreStroom(), samen = new Samenvoeger(STREAM_ADRES, pakketgrootte(configs));
    let blok = null;
    for (const n of {json.dumps(notificaties)}) for (const stuk of stroom.voegToe(hex(n))) blok = samen.voegToe(stuk) ?? blok;
    const d = parseDatapakket(blok, configs);
    process.stdout.write(JSON.stringify({{
      tijd: d.tijd, status: d.status, crcOk: d.crcOk, waarden: d.sensoren.map(([, w]) => w),
      kapotOk: parseDatapakket(hex("{bytes(kapot).hex()}"), configs).crcOk,
      grootte: pakketgrootte(configs),
      verzoeken: [leesPakket(CONFIG_ADRES, CONFIG_LENGTE), dataPakket(PIN_ADRES, PIN), streamPakket(pakketgrootte(configs))].map(naarHex),
    }}));
    """
    uit = json.loads(_node(script))

    verwacht = p.parse_datapakket(pakket, configs)
    assert uit["grootte"] == p.pakketgrootte(configs) == len(pakket)
    assert uit["tijd"] == pytest.approx(verwacht.tijd)
    assert (uit["status"], uit["crcOk"], uit["kapotOk"]) == (0b11, True, False)
    for (_, py), js in zip(verwacht.sensoren, uit["waarden"], strict=True):
        np.testing.assert_allclose(np.array(js), py, rtol=0, atol=1e-9)
    assert uit["verzoeken"] == [
        p.lees_pakket(p.CONFIG_ADRES, p.CONFIG_LENGTE).hex(),
        p.data_pakket(p.PIN_ADRES, p.PIN).hex(),
        p.stream_pakket(p.pakketgrootte(configs)).hex(),
    ]
