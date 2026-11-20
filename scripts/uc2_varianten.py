"""Varianten van de UC-2-beslisregels op de proxy-labels (segmenten.parquet uit uc2_alle.py)."""
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
d = pd.read_parquet("streamlit/data/_analyse_uc2/segmenten.parquet")
RUST = ["Zitten", "Staan", "Half liggend", "Liggen op de rug", "Liggen op de zij (rechts)", "Liggen op de zij (links)",
        "Zitten (achterover)", "rust"]
CONTACT = ["Lopen, plakker half los (LA)", "Plakker half los (RA)", "Plakker half los (LA)", "Plakker half los (LL)",
           "Draad los (RA)", "Lead Disconnected (RA)", "Lead-off test - [electrode] los (RA)"]
BEWEGING = ["Lopen (rustig)", "Lopen (stevig)", "Armen bewegen", "Traplopen", "Verzitten", "Springen", "Staan (bezig)"]


def label(d, goed=0.9, matig=0.5, drift=15.0, drift_alleen_met_slechte_slagen=False, drift_I=None):
    gmin = d[["goed_I", "goed_II"]].min(axis=1)
    dI, dII = d["drift_db_I"], d["drift_db_II"]
    teI = dI > (drift_I if drift_I is not None else drift)
    teII = dII > drift
    if drift_alleen_met_slechte_slagen:
        teI, teII = teI & (d["goed_I"] < goed), teII & (d["goed_II"] < goed)
    onbr = d["lead_off"] | (d["rand"] > 0) | (d["slagen"] == 0) | teI | teII
    return np.where(onbr, "onbruikbaar", np.where(gmin >= goed, "goed", np.where(gmin >= matig, "matig", "onbruikbaar")))


VARIANTEN = {
    "V0 huidig (0,9 / 15 dB)": {},
    "V1 drift-grens 20 dB": {"drift": 20.0},
    "V2 drift telt alleen met slechte slagen": {"drift_alleen_met_slechte_slagen": True},
    "V3 goed-grens 0,8": {"goed": 0.8},
    "V4 = V2 + V3": {"drift_alleen_met_slechte_slagen": True, "goed": 0.8},
}
rijen = []
rust = d[d["label"].isin(RUST) & (d["activiteit"] == "rust")]
for naam, kw in VARIANTEN.items():
    rij = {"variant": naam}
    for bev in ("sticker", "lanyard"):
        r = rust[rust["bevestiging"] == bev]
        rij[f"rust {bev}: niet goed %"] = round(100 * (label(r, **kw) != "goed").mean(), 1)
        rij[f"rust {bev}: onbruikbaar %"] = round(100 * (label(r, **kw) == "onbruikbaar").mean(), 1)
    c = d[d["label"].isin(CONTACT)]
    rij["contact: niet goed"] = f"{(label(c, **kw) != 'goed').sum()}/{len(c)}"
    b = d[d["label"].isin(BEWEGING)]
    rij["beweging: niet goed %"] = round(100 * (label(b, **kw) != "goed").mean(), 1)
    rijen.append(rij)
print(f"rust (UC-1 rust): sticker {len(rust[rust.bevestiging == 'sticker'])}, lanyard "
      f"{len(rust[rust.bevestiging == 'lanyard'])} segmenten; contact {d['label'].isin(CONTACT).sum()}; "
      f"beweging {d['label'].isin(BEWEGING).sum()}")
print(pd.DataFrame(rijen).set_index("variant").T.to_string())
c = d[d["label"].isin(CONTACT)]
print(c[["opname", "label", "goed_I", "goed_II", "goed_III", "drift_db_I", "drift_db_II", "drift_db_III", "lead_off", "rand",
         "kwaliteit", "plakker"]].round(2).to_string())
