"""Maakt 'Handleiding ECG-tool.pdf': eerst de P-Cardio-instructie voor de deelnemer (staand, pagina 1–4 van
streamlit/handleiding.pdf), dan de handleiding van de app uit handleiding.html (A4 liggend, voor de schermafdrukken).

    .venv\\Scripts\\python desktop\\handleiding\\maak_pdf.py
"""

import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument

MAP = Path(__file__).resolve().parent
BRON, UIT = MAP / "handleiding.html", MAP / "Handleiding ECG-tool.pdf"
INSTRUCTIE = MAP.parents[1] / "streamlit" / "handleiding.pdf"
INSTRUCTIE_PAGINAS = range(4)  # pagina 5 en 6 gingen over de oude Streamlit-app


def app_paginas(pad: Path) -> None:
    """handleiding.html als pdf, A4 liggend."""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 - nodig voor lettertypes en afbeeldingen
    pdf = QPdfWriter(str(pad))
    pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
                                  QMarginsF(12, 10, 12, 10), QPageLayout.Unit.Millimeter))
    pdf.setResolution(150)
    doc = QTextDocument()
    doc.setBaseUrl(QUrl.fromLocalFile(str(MAP) + "/"))  # afbeeldingen/… relatief aan deze map
    doc.setHtml(BRON.read_text(encoding="utf-8"))
    doc.setPageSize(QSizeF(pdf.pageLayout().paintRectPixels(pdf.resolution()).size()))
    doc.print_(pdf)


def maak() -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        app_pdf = Path(tmp) / "app.pdf"
        app_paginas(app_pdf)
        uit = PdfWriter()
        instructie = PdfReader(INSTRUCTIE)
        for i in INSTRUCTIE_PAGINAS:
            uit.add_page(instructie.pages[i])
        for pagina in PdfReader(app_pdf).pages:
            uit.add_page(pagina)
        uit.add_metadata({"/Title": "Handleiding ECG-tool P-Cardio", "/Author": "AppBakkers"})
        with UIT.open("wb") as f:
            uit.write(f)
    return UIT


if __name__ == "__main__":
    pad = maak()
    print(f"{pad} ({pad.stat().st_size / 1e6:.1f} MB, {len(PdfReader(pad).pages)} pagina's)")
