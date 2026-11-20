"""UC-2 over alle opnames: per segment kenmerken, label en proxy-label (periode waar het segment helemaal in valt).
Leest de opnames in OneDrive alleen; schrijft geen cache. Uitvoer: <repo>/streamlit/data/_analyse_uc2/segmenten.parquet

    .venv/Scripts/python <dit script>   (vanuit de projectroot)
"""
import os
import sys
import time
from pathlib import Path

REPO = Path.cwd()
UIT = REPO / "streamlit" / "data" / "_analyse_uc2"
os.environ["ECG_TOOL_DATA"] = r"C:\Users\Esmee Werk\OneDrive - AppBakkers\AppBakkers - pcardio-ecg-data"
os.environ["ECG_TOOL_DB"] = str(UIT / "ecg.db")
sys.path.insert(0, str(REPO / "streamlit"))

import pandas as pd  # noqa: E402

from kern.beweging import beweging_per_segment  # noqa: E402
from kern.kwaliteit import kenmerken_per_segment, kwaliteit_per_segment  # noqa: E402
from kern.opslag import DATA_ROOT, Opname  # noqa: E402

delen = []
for o in Opname.alle(DATA_ROOT):
    if not o.heeft_signalen:
        continue
    s = o.laad_signalen()
    ecg, acc = s.get("ecg"), s.get("acc")
    if ecg is None or acc is None or not {"Ecg1", "Ecg2"} <= set(ecg.kanalen):
        print("overgeslagen", o.info.id)
        continue
    t = time.perf_counter()
    bev = "lanyard" if "lanyard" in o.info.elektroden.lower() else "sticker"
    bw = beweging_per_segment(acc.data, s["gyro"].data if "gyro" in s else None, acc.fs, bev)
    lo = s.get("lead_off")
    k = kenmerken_per_segment(ecg.data, lo.data if lo is not None else None, bw["start"])
    q = kwaliteit_per_segment(k, bw)
    if q.empty:
        continue
    perioden = [(a.label, *o.in_datatijd(a)) for a in o.annotaties if a.soort == "periode"]
    perioden = [p for p in perioden if p[2] is not None]
    q["label"] = [next((lab for lab, b, e in perioden if b <= r.start and r.eind <= e), None) for r in q.itertuples()]
    q = q.merge(bw[["start", "houding", "acc_sd"]], on="start", how="left")
    q["opname"], q["deelnemer"], q["bevestiging"] = o.info.id, o.info.deelnemer_id, bev
    q["experiment"] = o.info.experiment
    delen.append(q)
    print(f"{o.info.id}: {len(q)} segmenten, {q['label'].notna().sum()} met label, {time.perf_counter() - t:.1f} s")

alle = pd.concat(delen, ignore_index=True)
alle.to_parquet(UIT / "segmenten.parquet", index=False)
print("totaal", len(alle), "segmenten,", alle["label"].notna().sum(), "met label")
