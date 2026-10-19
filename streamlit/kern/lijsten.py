"""Keuzelijsten (activiteiten, momenten) uit de tekstbestanden in ``config/``."""

from __future__ import annotations

from pathlib import Path

CONFIG_MAP = Path(__file__).resolve().parents[1] / "config"


def lees_lijst(naam: str) -> list[str]:
    """Eén item per regel; lege regels en regels die met ``#`` beginnen worden overgeslagen."""
    pad = CONFIG_MAP / f"{naam}.txt"
    if not pad.exists():
        beschikbaar = sorted(p.stem for p in CONFIG_MAP.glob("*.txt"))
        raise FileNotFoundError(f"Lijst '{naam}' niet gevonden in {CONFIG_MAP}. Beschikbaar: {beschikbaar}")
    regels = (regel.strip() for regel in pad.read_text(encoding="utf-8").splitlines())
    return [regel for regel in regels if regel and not regel.startswith("#")]
