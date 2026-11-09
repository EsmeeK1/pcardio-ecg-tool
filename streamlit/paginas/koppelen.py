"""P-Cardio-bestanden of een eerdere export inladen, koppelen aan een opname en de klokcorrectie bepalen."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import hulp
from kern.koppelen import SOORT_LABEL, bestanden_in_map, binnen_data, voorstellen
from kern.koppelen import lees_in as koppel_lees_in
from kern.opslag import DATA_ROOT, Deelnemers, Opname
from kern.pcardio import Signaal
from kern.plots import sync_figuur
from kern.verwerking import zoek_sync
from ui import kies_opname, klok, laad_signalen, opname_label, opname_velden

st.title("Data koppelen", help=hulp.KOPPELEN)

UPLOAD_MAP = DATA_ROOT / "_upload"


# --- 1. inlezen ---


def lees_in(paden: list[Path]) -> None:
    r = koppel_lees_in(paden, UPLOAD_MAP)
    st.session_state.ingelezen = {
        "signalen": r.signalen,
        "bestanden": [str(p) for p in r.bestanden],
        "soorten": r.soorten,
        "annotaties": r.annotaties,
        "opname_id": r.opname_id,
        "meldingen": r.meldingen,
        "fouten": r.fouten,
    }


st.subheader("1. Bestanden inlezen", help=hulp.INLEZEN)
uploaden, lokaal = st.tabs(["Uploaden", "Bestand of map op deze pc"])
with uploaden:
    bestanden = st.file_uploader(
        "Bestanden", type=["csv", "txt", "zip"], accept_multiple_files=True, help=hulp.UPLOAD,
    )
    if st.button("Inlezen", key="lees_upload", disabled=not bestanden, type="primary"):
        if UPLOAD_MAP.exists():
            shutil.rmtree(UPLOAD_MAP)
        UPLOAD_MAP.mkdir(parents=True)
        paden = []
        for bestand in bestanden:
            pad = UPLOAD_MAP / bestand.name
            pad.write_bytes(bestand.getbuffer())
            paden.append(pad)
        with st.spinner("Inlezen…"):
            lees_in(paden)
with lokaal:
    st.caption("Handig voor grote bestanden (geen uploadlimiet).")
    invoer = st.text_input("Pad naar een bestand of map", placeholder=r"C:\Users\...\P-Cardio\sessie1", help=hulp.PAD)
    if st.button("Inlezen", key="lees_lokaal", disabled=not invoer.strip(), type="primary"):
        pad = Path(invoer.strip().strip('"'))
        if pad.is_dir():
            paden = bestanden_in_map(pad)
        else:
            paden = [pad]
        if not paden:
            st.error(f"Geen .csv-, .txt- of .zip-bestanden gevonden in {pad}")
        else:
            shutil.rmtree(UPLOAD_MAP, ignore_errors=True)
            with st.spinner("Inlezen…"):
                lees_in(paden)

ingelezen = st.session_state.get("ingelezen")
if ingelezen:
    for fout in ingelezen["fouten"]:
        st.error(fout)
    for melding in ingelezen["meldingen"]:
        st.warning(melding)
    if ingelezen["soorten"]:
        st.dataframe(
            pd.DataFrame(
                [{"bestand": naam, "herkend als": SOORT_LABEL[soort]} for naam, soort in ingelezen["soorten"].items()],
            ),
            hide_index=True,
        )
    if ingelezen["annotaties"]:
        a = ingelezen["annotaties"]
        st.info(
            f"{a['bestand']}: {len(a['lijst'])} annotaties"
            + (f", klokcorrectie {a['klokcorrectie_s']:+.2f} s." if a["klokcorrectie_s"] is not None else "."),
        )
    signalen: dict[str, Signaal] = ingelezen["signalen"]
    if signalen:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "signaal": naam,
                        "bestand": s.bron,
                        "kanalen": ", ".join(f"{k} ({s.eenheden.get(k, '')})" for k in s.kanalen),
                        "samples": len(s.data),
                        "sample rate (Hz)": round(s.fs, 2),
                        "start": klok(s.start),
                        "eind": klok(s.eind),
                        "duur (min)": round((s.eind - s.start).total_seconds() / 60, 1),
                    }
                    for naam, s in signalen.items()
                ],
            ),
            hide_index=True,
            width="stretch",
        )
        if "ecg" not in signalen:
            st.warning("Er zit geen ECG-signaal tussen de ingelezen bestanden.")


# --- 2. koppelen ---


if ingelezen and (ingelezen["signalen"] or ingelezen["annotaties"]):
    signalen = ingelezen["signalen"]
    nieuwe_annotaties = ingelezen["annotaties"]
    st.subheader("2. Koppelen aan een opname", help=hulp.KOPPEL_OPNAME)
    opnames = {o.info.id: o for o in Opname.alle(DATA_ROOT)}
    kandidaten = voorstellen(signalen, Opname.alle(DATA_ROOT)) if signalen else []
    bestand_id = ingelezen["opname_id"]
    keuzes: dict[str, str] = {}
    if bestand_id in opnames:
        st.success(f"Voorstel: **{opname_label(opnames[bestand_id])}** — zelfde opname-ID als de bestandsnaam.")
        keuzes[bestand_id] = opname_label(opnames[bestand_id])
    elif kandidaten:
        beste, score = kandidaten[0]
        st.success(
            f"Voorstel: **{opname_label(beste)}** — {score:.0%} van de live annotaties valt binnen deze data.",
        )
    elif signalen:
        st.info(
            "Geen bestaande opname past bij deze data, dus er wordt een **nieuwe opname** gemaakt. Dat klopt als "
            "er niet live geannoteerd is: annoteer daarna op **Bekijken**. Een klokcorrectie of sync-sprong is "
            "dan niet nodig. Hoort de data toch bij een bestaande opname (bijv. als de klokken flink "
            "verschillen)? Kies die hieronder.",
        )
    elif nieuwe_annotaties:
        st.info(
            "Alleen annotaties, bijv. van de telefoon-app: maak er een **nieuwe opname** van en vul hieronder de "
            "gegevens in. Lees daarna de P-Cardio-bestanden in; die worden dan aan deze opname voorgesteld.",
        )
    for opname, score in kandidaten:
        keuzes.setdefault(opname.info.id, f"{opname_label(opname)}  ({score:.0%} overlap)")
    for opname in opnames.values():
        keuzes.setdefault(opname.info.id, opname_label(opname))
    nieuw = {"__nieuw__": "Nieuwe opname" + ("" if nieuwe_annotaties else " (alleen data, achteraf annoteren)")}
    # Zonder voorstel is een nieuwe opname de standaard, niet een willekeurige bestaande.
    keuzes = {**keuzes, **nieuw} if bestand_id in opnames or kandidaten else {**nieuw, **keuzes}

    gekozen = st.selectbox("Opname", list(keuzes), format_func=lambda k: keuzes[k])
    doel = None
    deelnemers = []
    if gekozen == "__nieuw__":
        deelnemers = Deelnemers(DATA_ROOT).alle()
        if not deelnemers:
            st.warning("Voeg eerst een deelnemer toe op de pagina **Deelnemers**.")
        per_id = {d.id: d for d in deelnemers}
        ids = list(per_id)
        uit_bestand = bestand_id.rsplit("_", 1)[1] if bestand_id else None
        deelnemer_id = st.selectbox(
            "Deelnemer", ids, index=ids.index(uit_bestand) if uit_bestand in ids else 0,
            format_func=lambda i: per_id[i].weergave,
        )
        velden = opname_velden("de pc of telefoon waarmee geannoteerd is")
    else:
        doel = opnames[gekozen]
        if signalen and doel.heeft_signalen:
            st.warning(
                f"Aan deze opname is al data gekoppeld ({', '.join(doel.info.bronbestanden)}). "
                f"Koppelen vervangt die.",
            )
        if nieuwe_annotaties and doel.annotaties:
            st.warning(f"Vervangt de {len(doel.annotaties)} bestaande annotaties van deze opname.")
        if bestand_id and gekozen != bestand_id:
            st.caption(f"Let op: de bestandsnaam hoort bij opname {bestand_id}.")

    # Passen de annotaties bij de data (de nieuwe, of anders die van de opname)?
    toch = True
    data = signalen or (laad_signalen(doel) if doel is not None and doel.heeft_signalen else {})
    if nieuwe_annotaties and nieuwe_annotaties["lijst"] and data:
        correctie = nieuwe_annotaties["klokcorrectie_s"]
        if correctie is None:
            correctie = (doel.info.klokcorrectie_s if doel is not None else None) or 0.0
        totaal = len(nieuwe_annotaties["lijst"])
        binnen = binnen_data(nieuwe_annotaties["lijst"], correctie, data)
        if binnen == totaal:
            st.success(f"Alle {totaal} annotaties vallen binnen de data.")
        elif binnen:
            st.warning(f"{totaal - binnen} van {totaal} annotaties vallen buiten de data.")
        else:
            st.error("Geen enkele annotatie valt binnen de data. Hoort het annotatiebestand wel bij deze opname?")
            toch = st.checkbox("Toch koppelen")

    if st.button(
        "Koppel", type="primary", help=hulp.KOPPEL,
        disabled=not toch or (gekozen == "__nieuw__" and not deelnemers),
    ):
        try:
            if gekozen == "__nieuw__":
                # Begin van de data, of zonder data het begin van de annotaties (bijv. alleen een telefoon-CSV).
                starts = [s.start for s in signalen.values()] or [a.t_start for a in nieuwe_annotaties["lijst"]]
                if not starts:
                    raise ValueError("Het annotatiebestand is leeg.")
                doel = Opname.nieuw(per_id[deelnemer_id], min(starts), root=DATA_ROOT, live_afgesloten=True, **velden)
            with st.spinner("Opslaan…"):
                if signalen:
                    doel.bewaar_signalen(signalen, [Path(p) for p in ingelezen["bestanden"]])
                if nieuwe_annotaties:
                    doel.vervang_annotaties(nieuwe_annotaties["lijst"], nieuwe_annotaties["klokcorrectie_s"])
        except ValueError as fout:
            st.error(str(fout))
            st.stop()
        shutil.rmtree(UPLOAD_MAP, ignore_errors=True)
        del st.session_state.ingelezen
        st.session_state.klok_opname = doel.info.id
        st.success(f"Gekoppeld aan {opname_label(doel)}.")
        st.rerun()


# --- 3. klokcorrectie ---

st.divider()
st.subheader("3. Klokcorrectie", help=hulp.KLOKCORRECTIE)
with st.expander("Wat doet de klokcorrectie?"):
    st.markdown(hulp.KLOKCORRECTIE_UITLEG)
opname = kies_opname("klok_opname", alleen_met_data=True)
if opname is not None:
    huidig = opname.info.klokcorrectie_s
    st.markdown(
        f"Huidige correctie: **{huidig:+.2f} s** ({opname.info.klokcorrectie_bron})"
        if huidig is not None
        else "Huidige correctie: **nog niet bepaald** (er wordt 0 s gebruikt).",
    )
    signalen_opname = laad_signalen(opname)
    syncs = opname.syncs
    voorstel = None
    if opname.annotatie_bereik is None:
        st.info(
            "Er is niet live geannoteerd, dus een klokcorrectie is niet nodig. Annotaties die je op **Bekijken** "
            "maakt, staan direct in de tijd van de P-Cardio-data.",
        )
    elif not syncs:
        st.info("Deze opname heeft geen sync-sprong. Vul de correctie zo nodig handmatig in.")
    elif "acc" not in signalen_opname:
        st.info("Geen accelerometerdata om de sync-sprong in te zoeken. Vul de correctie handmatig in.")
    else:
        # Standaard ±120 s: de klok van de P-Cardio loopt ruim een minuut uit (+76 s op 4 nov 2026). Met ±5 s viel
        # de echte sprong buiten het venster en werd een kleine beweging als "duidelijke" piek gekozen.
        zoek_s = st.slider("Zoekvenster rond elk sync-moment (± s)", 1.0, 300.0, 120.0, 0.5, help=hulp.ZOEKVENSTER)
        resultaten = []
        for sync in syncs:
            resultaat = zoek_sync(signalen_opname["acc"].data, sync.t_start, zoek_s)
            if resultaat is None:
                st.warning(
                    f"Sync van {klok(sync.t_start)}: geen accelerometerdata in het zoekvenster. Lopen de klokken "
                    f"meer dan {zoek_s:.0f} s uiteen? Vergroot het zoekvenster of corrigeer handmatig.",
                )
                continue
            resultaten.append(resultaat)
            with st.expander(
                f"Sync {klok(sync.t_start)} → piek {klok(resultaat.t_piek)}: {resultaat.correctie_s:+.2f} s"
                + ("" if resultaat.duidelijk else "  (let op: geen duidelijke piek)"),
                expanded=not resultaat.duidelijk or len(syncs) == 1,
            ):
                st.plotly_chart(sync_figuur(signalen_opname["acc"], resultaat, zoek_s), width="stretch")
        duidelijk = [r for r in resultaten if r.duidelijk]
        if duidelijk:
            voorstel = float(np.mean([r.correctie_s for r in duidelijk]))
            if len(duidelijk) >= 2:
                drift = duidelijk[-1].correctie_s - duidelijk[0].correctie_s
                st.caption(f"Verschil tussen eerste en laatste sync: {drift:+.2f} s (klokdrift + reactietijd).")
            if st.button(f"Gebruik voorstel: {voorstel:+.2f} s", type="primary", help=hulp.GEBRUIK_VOORSTEL):
                opname.zet_klokcorrectie(round(voorstel, 3), "sync")
                st.rerun()
        elif resultaten:
            st.warning(
                "Geen duidelijke piek gevonden. Vergroot het zoekvenster (de P-Cardio-klok loopt soms meer dan een "
                "minuut uit), of controleer de plot en vul de correctie handmatig in.",
            )

    with st.form("handmatig"):
        waarde = st.number_input(
            "Handmatige correctie (s)",
            value=float(huidig if huidig is not None else (voorstel or 0.0)),
            step=0.1,
            format="%.3f",
            help=hulp.HANDMATIG,
        )
        if st.form_submit_button("Opslaan"):
            opname.zet_klokcorrectie(waarde, "handmatig")
            st.rerun()
