"""De CSV van de iPhone-app (mobiel/) moet zonder aanpassing door Koppelen: bestandssoort + lees_annotaties."""

import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from kern.export import bestandssoort
from kern.opslag import ANNOTATIE_KOLOMMEN, lees_annotaties

MODULE = (Path(__file__).resolve().parents[2] / "mobiel" / "annotaties.js").as_uri()

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


@pytest.mark.skipif(shutil.which("node") is None, reason="node is niet geïnstalleerd")
def test_csv_van_mobiel_gaat_door_koppelen(tmp_path):
    uit = subprocess.run(
        ["node", "--input-type=module"], input=SCRIPT, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
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
