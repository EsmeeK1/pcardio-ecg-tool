"""Deelnemers vastleggen en bewerken (gegevens per persoon)."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

import hulp
from kern.opslag import DATA_ROOT, GESLACHTEN, Deelnemer, Deelnemers
from ui import meld, toon_meldingen

register = Deelnemers(DATA_ROOT)

st.title("Deelnemers", help=hulp.DEELNEMERS)
toon_meldingen()


def formulier(sleutel: str, bestaand: Deelnemer | None = None) -> dict[str, object] | None:
    """Toont het formulier; geeft de ingevulde velden terug na verzenden, anders None."""
    with st.form(sleutel, clear_on_submit=bestaand is None):
        naam = st.text_input("Voornaam of patiënt-ID", value=bestaand.naam if bestaand else "", help=hulp.NAAM)
        links, rechts = st.columns(2)
        leeftijd = links.number_input(
            "Leeftijd (jaren)",
            min_value=0,
            max_value=120,
            step=1,
            value=bestaand.leeftijd if bestaand and bestaand.leeftijd is not None else None,
            placeholder="onbekend",
            help=hulp.LEEFTIJD,
        )
        geslacht = rechts.selectbox(
            "Geslacht",
            GESLACHTEN,
            index=GESLACHTEN.index(bestaand.geslacht) if bestaand else 0,
            help=hulp.GESLACHT,
        )
        hartdecompensatie = st.radio(
            "Hartdecompensatie",
            ["nee", "ja"],
            index=1 if bestaand and bestaand.hartdecompensatie else 0,
            horizontal=True,
            help=hulp.HARTDECOMPENSATIE,
        )
        andere = st.text_input(
            "Andere bekende ziekte/aandoening (leeg = geen)",
            value=bestaand.andere_aandoening if bestaand else "",
            help=hulp.ANDERE_AANDOENING,
        )
        if not st.form_submit_button("Opslaan" if bestaand else "Toevoegen", type="primary"):
            return None
    return {
        "naam": naam.strip(),
        "leeftijd": int(leeftijd) if leeftijd is not None else None,
        "geslacht": geslacht,
        "hartdecompensatie": hartdecompensatie == "ja",
        "andere_aandoening": andere.strip(),
    }


nieuw, bewerken = st.tabs(["Nieuwe deelnemer", "Bewerken"])

with nieuw:
    velden = formulier("nieuwe_deelnemer")
    if velden is not None:
        try:
            deelnemer = register.toevoegen(**velden)
            st.success(f"{deelnemer.weergave} toegevoegd.")
        except ValueError as fout:
            st.error(str(fout))

alle = register.alle()

with bewerken:
    if not alle:
        st.info("Nog geen deelnemers.")
    else:
        per_id = {d.id: d for d in alle}
        gekozen = st.selectbox(
            "Deelnemer", list(per_id), format_func=lambda i: per_id[i].weergave, help=hulp.BEWERK_DEELNEMER,
        )
        velden = formulier(f"bewerk_{gekozen}", per_id[gekozen])
        if velden is not None:
            try:
                register.bijwerken(replace(per_id[gekozen], **velden))
                st.success("Opgeslagen.")
                st.rerun()
            except ValueError as fout:
                st.error(str(fout))

        opnames = register.opnames(gekozen)
        with st.popover("Deelnemer verwijderen", help=hulp.VERWIJDER_DEELNEMER):
            if opnames:
                st.warning(
                    f"{per_id[gekozen].weergave} heeft {len(opnames)} opname(s) en kan daarom niet verwijderd "
                    f"worden. Zo blijven opnames en annotaties altijd aan een deelnemer te koppelen.",
                )
            else:
                st.write(f"{per_id[gekozen].weergave} definitief verwijderen?")
                if st.button("Ja, verwijderen", type="primary", key=f"verwijder_{gekozen}"):
                    try:
                        register.verwijder(gekozen)
                        meld("success", f"{per_id[gekozen].weergave} verwijderd.")
                        st.rerun()
                    except ValueError as fout:
                        st.error(str(fout))

st.subheader(f"Alle deelnemers ({len(alle)})", help=hulp.ALLE_DEELNEMERS)
if alle:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "id": d.id,
                    "naam / patiënt-ID": d.naam,
                    "leeftijd": d.leeftijd,
                    "geslacht": d.geslacht,
                    "hartdecompensatie": "ja" if d.hartdecompensatie else "nee",
                    "andere aandoening": d.andere_aandoening,
                }
                for d in alle
            ],
        ),
        hide_index=True,
        width="stretch",
    )
