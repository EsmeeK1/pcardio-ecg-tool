"""ECG-tool voor de P-Cardio.

Starten vanuit de projectroot:
    streamlit run streamlit/app.py
"""

import streamlit as st

st.set_page_config(page_title="ECG-tool P-Cardio", layout="wide")

from ui import huisstijl  # noqa: E402 - na set_page_config

huisstijl()

# .streamlit/config.toml wordt alleen gelezen als je vanuit de projectroot start.
if st.get_option("server.address") != "localhost":
    st.warning(
        "De instellingen uit `.streamlit/config.toml` zijn niet geladen: de app is mogelijk ook vanaf andere "
        "apparaten op het netwerk te openen. Stop de app en start hem vanuit de projectroot met "
        "`streamlit run streamlit/app.py`.",
    )

PAGINAS = {
    "Start": [
        st.Page("paginas/testopname.py", title="Test-opname stap voor stap"),
        st.Page("paginas/handleiding.py", title="Handleiding"),
    ],
    "Opnemen": [
        st.Page("paginas/deelnemers.py", title="Deelnemers", default=True),
        st.Page("paginas/live.py", title="Live opname"),
        st.Page("paginas/live_ecg.py", title="Live ECG"),
    ],
    "Analyseren": [
        st.Page("paginas/koppelen.py", title="Data koppelen"),
        st.Page("paginas/bekijken.py", title="Bekijken & annoteren"),
        st.Page("paginas/export.py", title="Export"),
    ],
}

st.navigation(PAGINAS).run()
