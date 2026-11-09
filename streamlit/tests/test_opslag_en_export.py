from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kern.export import bestandssoort, gecombineerd, lees_export
from kern.opslag import Deelnemers, Opname, lees_annotaties, nu
from kern.pcardio import Signaal
from kern.plots import DetailOpties, detail, selectie_tijden
from kern.verwerking import dun_uit, ecg_filter, overlap_fractie, zes_leads, zoek_sync


def _deelnemer(root: Path):
    return Deelnemers(root).toevoegen("Esmee", 1996, "vrouw", False, "")


def test_deelnemers(tmp_path: Path) -> None:
    register = Deelnemers(tmp_path)
    a = register.toevoegen("Esmee", 1996, "vrouw", False)
    b = register.toevoegen("P-1234", None, "onbekend", True, "astma")
    assert (a.id, b.id) == ("D001", "D002")
    opgeslagen = {d.id: d for d in register.alle()}["D002"]
    assert opgeslagen.andere_aandoening == "astma" and opgeslagen.hartdecompensatie is True
    b.geboortejaar = 1965
    register.bijwerken(b)
    assert {d.id: d for d in register.alle()}["D002"].geboortejaar == 1965
    with pytest.raises(ValueError, match="voornaam"):
        register.toevoegen(" ", 2025, "man", False)


def test_deelnemer_verwijderen(tmp_path: Path) -> None:
    register = Deelnemers(tmp_path)
    zonder = register.toevoegen("Zonder opname", None, "onbekend", False)
    met = register.toevoegen("Met opname", None, "onbekend", False)
    Opname.nieuw(met, nu(), root=tmp_path)

    with pytest.raises(ValueError, match="1 opname"):
        register.verwijder(met.id)
    with pytest.raises(ValueError, match="Onbekende deelnemer"):
        register.verwijder("D999")
    register.verwijder(zonder.id)
    assert [d.id for d in register.alle()] == [met.id]

    # Een verwijderd ID wordt nooit opnieuw uitgegeven, ook niet het hoogste.
    hoogste = register.toevoegen("Weg", None, "onbekend", False)
    register.verwijder(hoogste.id)
    assert register.toevoegen("Nieuw", None, "onbekend", False).id == "D004"


def test_live_annoteren_en_laden(tmp_path: Path) -> None:
    opname = Opname.nieuw(_deelnemer(tmp_path), nu(), root=tmp_path)
    opname.sync()
    opname.start_periode("Zitten")
    time.sleep(0.05)
    opname.moment("Hoest")
    opname.start_periode("Lopen (rustig)")
    opname.sluit_live_af()

    geladen = Opname.laad(opname.map)
    perioden = [a for a in geladen.chronologisch() if a.soort == "periode"]
    assert [p.label for p in perioden] == ["Zitten", "Lopen (rustig)"]
    assert all(p.t_eind is not None for p in perioden)
    assert perioden[0].t_eind == perioden[1].t_start
    assert geladen.info.live_afgesloten
    assert len(geladen.syncs) == 1


def test_klokcorrectie(tmp_path: Path) -> None:
    opname = Opname.nieuw(_deelnemer(tmp_path), nu(), root=tmp_path)
    a = opname.moment("Hoest")
    opname.zet_klokcorrectie(2.5, "handmatig")
    start, _ = opname.in_datatijd(a)
    assert (start - a.t_start).total_seconds() == pytest.approx(2.5)
    b = opname.voeg_toe("moment", "achteraf", start, tijdbasis="data")
    assert opname.in_datatijd(b)[0] == start


def _signalen(t0: pd.Timestamp, seconden: int = 20) -> dict[str, Signaal]:
    t_ecg = t0 + pd.to_timedelta(np.arange(seconden * 250) / 250, unit="s")
    t_acc = t0 + pd.to_timedelta(np.arange(seconden * 100) / 100, unit="s")
    rng = np.random.default_rng(0)
    acc = np.column_stack([rng.normal(0, 0.01, len(t_acc)), rng.normal(0, 0.01, len(t_acc)), np.ones(len(t_acc))])
    acc[1000, 2] = 4.0  # landing op t0 + 10 s
    return {
        "ecg": Signaal(
            "ecg",
            pd.DataFrame({"tijd": t_ecg, "Ecg1": np.sin(np.arange(len(t_ecg))), "Ecg2": np.cos(np.arange(len(t_ecg)))}),
            {"Ecg1": "mV", "Ecg2": "mV"},
            "test",
        ),
        "acc": Signaal(
            "acc",
            pd.DataFrame({"tijd": t_acc, "AccX": acc[:, 0], "AccY": acc[:, 1], "AccZ": acc[:, 2]}),
            {"AccX": "g", "AccY": "g", "AccZ": "g"},
            "test",
        ),
    }


def test_sync_en_export(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    signalen = _signalen(t0)
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    # pc-klok loopt 1,2 s achter op de P-Cardio
    opname.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))
    opname.voeg_toe("periode", "Springen", t0 + pd.Timedelta(seconds=12), t0 + pd.Timedelta(seconds=14))
    opname.voeg_toe("moment", "Hoest", t0 + pd.Timedelta(seconds=15))

    resultaat = zoek_sync(signalen["acc"].data, opname.syncs[0].t_start)
    assert resultaat is not None and resultaat.duidelijk
    assert resultaat.correctie_s == pytest.approx(1.2, abs=0.02)
    opname.zet_klokcorrectie(resultaat.correctie_s, "sync")

    opname.bewaar_signalen(signalen, [])
    geladen = Opname.laad(opname.map).laad_signalen()
    assert set(geladen) == {"ecg", "acc"}
    pd.testing.assert_frame_equal(geladen["acc"].data, signalen["acc"].data)

    df = gecombineerd(opname, geladen)
    assert {"Ecg1", "Ecg2", "III", "aVR", "AccZ", "acc_magnitude", "activiteit", "moment"} <= set(df.columns)
    springen = df.loc[df["activiteit"] == "Springen", "t_s"]
    assert springen.min() == pytest.approx(13.2, abs=0.01)
    assert springen.max() == pytest.approx(15.2, abs=0.01)
    assert df.loc[df["moment"] == "Hoest", "t_s"].iloc[0] == pytest.approx(16.2, abs=0.01)
    assert len(df) == 20 * 250


def test_export_terug_inlezen(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    bron = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    bron.voeg_toe("sync", "sync-sprong", t0 + pd.Timedelta(seconds=8.8))
    bron.voeg_toe("periode", "Springen", t0 + pd.Timedelta(seconds=12), t0 + pd.Timedelta(seconds=14), opmerking="x")
    bron.zet_klokcorrectie(1.2, "sync")
    data_pad, annotaties_pad = tmp_path / "volledig.csv", tmp_path / "annotaties.csv"
    gecombineerd(bron, _signalen(t0)).to_csv(data_pad, index=False)
    bron.annotaties_df().to_csv(annotaties_pad, index=False)
    assert (bestandssoort(data_pad), bestandssoort(annotaties_pad)) == ("export", "annotaties")

    signalen = {s.naam: s for s in lees_export(data_pad)}
    assert set(signalen) == {"ecg", "acc"}
    assert signalen["ecg"].kanalen == ["Ecg1", "Ecg2"] and signalen["acc"].kanalen == ["AccX", "AccY", "AccZ"]
    assert signalen["ecg"].start == t0 and len(signalen["ecg"].data) == 20 * 250

    annotaties, correctie = lees_annotaties(annotaties_pad)
    assert correctie == pytest.approx(1.2)
    doel = Opname.nieuw(_deelnemer(tmp_path), t0 + pd.Timedelta(hours=1), root=tmp_path)
    doel.voeg_toe("moment", "weg", t0)
    doel.vervang_annotaties(annotaties, correctie)
    doel = Opname.laad(doel.map)
    assert [(a.label, a.opmerking) for a in doel.chronologisch()] == [("sync-sprong", ""), ("Springen", "x")]
    assert (doel.info.klokcorrectie_s, doel.info.klokcorrectie_bron) == (pytest.approx(1.2), "geïmporteerd")


def test_experiment_en_plaatsing(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path, experiment="Elektrodeplaatsing 21-10")
    opname.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=2), t0 + pd.Timedelta(seconds=6), plaatsing="R2-Y2-G4")
    opname.voeg_toe("periode", "Armen", t0 + pd.Timedelta(seconds=8), t0 + pd.Timedelta(seconds=10), plaatsing="R1-Y1")
    assert opname.laatste_plaatsing == "R1-Y1"
    opname.wijzig(2, plaatsing="R1-Y2")
    opname.zet_experiment("  Elektrodeplaatsing 22-10 ")

    geladen = Opname.laad(opname.map)
    assert geladen.info.experiment == "Elektrodeplaatsing 22-10"
    assert [a.plaatsing for a in geladen.chronologisch()] == ["R2-Y2-G4", "R1-Y2"]

    df = gecombineerd(geladen, _signalen(t0))
    assert set(df["experiment"]) == {"Elektrodeplaatsing 22-10"}
    assert set(df.loc[df["activiteit"] == "Zitten", "plaatsing"]) == {"R2-Y2-G4"}
    assert set(df.loc[df["activiteit"] == "", "plaatsing"]) == {""}
    pad = tmp_path / "volledig.csv"
    df.to_csv(pad, index=False)
    assert {s.naam for s in lees_export(pad)} == {"ecg", "acc"}  # nieuwe kolommen zijn geen signalen


def test_bestanden_zonder_experiment_en_plaatsing(tmp_path: Path) -> None:
    """Oud formaat zonder database, van vóór de velden experiment en plaatsing: wordt eenmalig overgenomen."""
    (tmp_path / "deelnemers.csv").write_text(
        "id,naam,leeftijd,geslacht,hartdecompensatie,andere_aandoening,aangemaakt\n"
        "D002,Esmee,22,vrouw,nee,,2026-10-07T10:06:00.002+02:00\n",
        encoding="utf-8",
    )
    map_ = tmp_path / "opnames" / "2026-10-07_1305_D003"  # D003 staat niet in deelnemers.csv
    map_.mkdir(parents=True)
    (map_ / "opname.json").write_text(
        '{"id": "2026-10-07_1305_D003", "deelnemer_id": "D003", "gestart": "2026-10-07T13:05:00.798+02:00"}',
        encoding="utf-8",
    )
    (map_ / "annotaties.csv").write_text(
        "id,soort,label,t_start,t_eind,tijdbasis,opmerking,beoordeling,beoordeling_opmerking\n"
        "1,periode,Zitten,2026-10-07T13:05:15.714+02:00,2026-10-07T13:06:16.680+02:00,pc,,,\n",
        encoding="utf-8",
    )
    opname = Opname.laad(map_)
    assert opname.info.experiment == "" and opname.annotaties[0].plaatsing == ""
    assert opname.laatste_plaatsing == ""
    opname.start_periode("Staan", "R2-Y2-G4")  # en daarna gewoon verder schrijven
    assert Opname.laad(map_).annotaties[-1].plaatsing == "R2-Y2-G4"
    assert {d.id: d.naam for d in Deelnemers(tmp_path).alle()} == {"D002": "Esmee", "D003": "D003"}
    assert Deelnemers(tmp_path).toevoegen("Nieuw", None, "onbekend", False).id == "D004"


def test_opname_verwijderen(tmp_path: Path) -> None:
    deelnemer = _deelnemer(tmp_path)
    opname = Opname.nieuw(deelnemer, nu(), root=tmp_path)
    opname.sync()
    opname.verwijder_opname()
    assert Opname.alle(tmp_path) == [] and not opname.map.exists()
    Deelnemers(tmp_path).verwijder(deelnemer.id)  # nu zonder opnames


def test_zes_leads_einthoven() -> None:
    ecg = pd.DataFrame({"tijd": [0, 1], "Ecg1": [1.0, 2.0], "Ecg2": [3.0, 5.0]})
    leads = zes_leads(ecg)
    np.testing.assert_allclose(leads["I"] + leads["III"] - leads["II"], 0)
    np.testing.assert_allclose(leads["aVR"] + leads["aVL"] + leads["aVF"], 0)


def test_dun_uit_bewaart_pieken() -> None:
    tijd = pd.Series(pd.date_range("2026-01-01", periods=100_000, freq="4ms", tz="UTC"))
    waarden = np.zeros(100_000)
    waarden[54_321] = 9.0
    t, w = dun_uit(tijd, waarden, max_punten=1000)
    assert len(w) <= 1000 and w.max() == 9.0
    assert t.iloc[w.argmax()] == tijd.iloc[54_321] and t.dtype == tijd.dtype


def test_dun_uit_houdt_het_einde() -> None:
    """10 s op 1000 Hz uitgedund naar 8000 punten liet eerder alleen de eerste 8 s zien."""
    tijd = pd.Series(pd.date_range("2026-01-01", periods=10_000, freq="1ms", tz="UTC"))
    t, w = dun_uit(tijd, np.arange(10_000, dtype=float), max_punten=8000)
    assert len(w) <= 8000
    assert t.iloc[0] == tijd.iloc[0] and t.iloc[-1] == tijd.iloc[-1]
    assert w.min() == 0 and w.max() == 9_999


def test_overlap() -> None:
    t = pd.Timestamp("2026-01-01", tz="UTC")
    s = pd.Timedelta(seconds=1)
    assert overlap_fractie(t, t + 10 * s, t + 5 * s, t + 100 * s) == pytest.approx(0.5)
    assert overlap_fractie(t, t + 10 * s, t + 20 * s, t + 30 * s) == 0


def test_ecg_filter_haalt_drift_en_ruis_weg() -> None:
    fs = 250.0
    t = np.arange(int(20 * fs)) / fs
    hart = np.sin(2 * np.pi * 5 * t)  # in de doorlaatband
    ruw = 3.0 + 0.8 * np.sin(2 * np.pi * 0.1 * t) + hart + 0.5 * np.sin(2 * np.pi * 50 * t)
    ruw[1000:1010] = np.nan
    kopie = ruw.copy()

    gefilterd = ecg_filter(ruw, fs)

    np.testing.assert_array_equal(ruw, kopie)  # invoer onveranderd
    assert len(gefilterd) == len(ruw) and np.isnan(gefilterd[1000:1010]).all()
    midden = slice(int(2 * fs), int(18 * fs))  # randen buiten beschouwing
    ok = ~np.isnan(gefilterd[midden])
    fout = gefilterd[midden][ok] - hart[midden][ok]
    assert np.sqrt(np.mean(fout**2)) < 0.05
    assert ecg_filter(np.array([1.0, 2.0, 3.0]), fs).tolist() == [-1.0, 0.0, 1.0]  # te kort: alleen offset eraf


def test_filter_alleen_in_de_plot(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    signalen = _signalen(t0)
    signalen["ecg"].data["Ecg1"] += 5.0  # offset die het filter in de plot weghaalt
    voor = {n: s.data.copy() for n, s in signalen.items()}
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)

    fig = detail(signalen, opname, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=15), DetailOpties(filter=True))
    getoond = np.concatenate([np.asarray(tr.y, dtype=float) for tr in fig.data if tr.name == "I"])
    assert abs(np.nanmean(getoond)) < 1.0  # in de plot is de offset weg

    for naam, data in voor.items():
        pd.testing.assert_frame_equal(signalen[naam].data, data)  # opgeslagen signalen onveranderd
    df = gecombineerd(opname, signalen)
    np.testing.assert_array_equal(df["Ecg1"].to_numpy(), voor["ecg"]["Ecg1"].to_numpy())  # export ruw


def test_label_in_hover(tmp_path: Path) -> None:
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    opname.voeg_toe("periode", "Zitten", t0 + pd.Timedelta(seconds=6), t0 + pd.Timedelta(seconds=8), tijdbasis="data")
    opname.voeg_toe("moment", "Hoest", t0 + pd.Timedelta(seconds=7), tijdbasis="data")
    fig = detail(_signalen(t0), opname, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=15), DetailOpties())

    label = next(tr for tr in fig.data if tr.name == "label")
    assert set(label.text) == {"Zitten", "Zitten, Hoest"} and list(label.text).count("Zitten, Hoest") == 1
    assert len(label.x) == 2 * 250 + 1  # alleen punten binnen de periode (2 s op 250 Hz, randen inbegrepen)


def test_selectie_tijden() -> None:
    selectie = {"box": [{"xref": "x", "yref": "y", "x": ["2026-10-05 10:00:12.5", "2026-10-05 10:00:03.25"]}]}
    begin, eind = selectie_tijden(selectie)
    assert begin == pd.Timestamp("2026-10-05 08:00:03.25", tz="UTC")  # zomertijd: UTC+2
    assert eind == pd.Timestamp("2026-10-05 08:00:12.5", tz="UTC")
    assert selectie_tijden({"box": [], "points": []}) is None
    assert selectie_tijden(None) is None


def test_mislukte_migratie_laat_geen_lege_database_achter(tmp_path: Path, monkeypatch) -> None:
    import kern.opslag as opslag

    (tmp_path / "deelnemers.csv").write_text(
        "id,naam,leeftijd,geslacht,hartdecompensatie,andere_aandoening,aangemaakt\n"
        "D002,Esmee,22,vrouw,nee,,2026-10-07T10:06:00.002+02:00\n",
        encoding="utf-8",
    )
    echt = opslag._migreer_bestanden
    monkeypatch.setattr(opslag, "_migreer_bestanden", lambda con, root: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        Deelnemers(tmp_path).alle()
    assert not (tmp_path / "ecg.db").exists() and not list(tmp_path.glob("*.tmp"))
    monkeypatch.setattr(opslag, "_migreer_bestanden", echt)
    assert [d.id for d in Deelnemers(tmp_path).alle()] == ["D002"]  # volgende start: alsnog gemigreerd


@pytest.mark.parametrize("naam", [
    "Zoë O'Brien-Ünal", 'Robert"); DROP TABLE deelnemers;--', "陈伟 😀", "x" * 500, "  Spaties eromheen  ",
])
def test_deelnemer_bijzondere_namen(tmp_path: Path, naam: str) -> None:
    register = Deelnemers(tmp_path)
    d = register.toevoegen(naam, 1986, "anders", False, "astma, diabetes; 'x'")
    opgeslagen = {x.id: x for x in register.alle()}[d.id]
    assert opgeslagen.naam == naam and opgeslagen.andere_aandoening == "astma, diabetes; 'x'"


def test_deelnemer_dubbele_naam_mag_en_ongeldige_velden(tmp_path: Path) -> None:
    register = Deelnemers(tmp_path)
    a, b = register.toevoegen("Esmee", 2004, "vrouw", False), register.toevoegen("Esmee", 2004, "vrouw", False)
    assert a.id != b.id and len(register.alle()) == 2
    for jaar in (1899, 2999):
        with pytest.raises(ValueError, match="geboortejaar"):
            register.toevoegen("Ongeldig", jaar, "man", False)
    with pytest.raises(ValueError, match="geslacht"):
        register.toevoegen("Iemand", 1996, "x", False)
    assert len(register.alle()) == 2  # een geweigerde deelnemer laat niets achter, ook geen ID
    assert register.toevoegen("Volgende", None, "onbekend", False).id == "D003"


def test_oude_database_met_leeftijd_wordt_geboortejaar(tmp_path: Path) -> None:
    import sqlite3

    import kern.opslag as opslag

    Deelnemers(tmp_path).alle()  # nieuwe database (versie 1); maak er een van vóór 9-11-2026 van
    con = sqlite3.connect(tmp_path / "ecg.db")
    con.execute("ALTER TABLE deelnemers RENAME COLUMN geboortejaar TO leeftijd")
    con.execute("INSERT INTO deelnemers (nummer, id, naam, leeftijd, geslacht, hartdecompensatie, aangemaakt) "
                "VALUES (1, 'D001', 'Esmee', 22, 'vrouw', 0, '2026-10-07T10:06:00.002+02:00')")
    con.execute("PRAGMA user_version = 0")
    con.commit()
    con.close()
    d = Deelnemers(tmp_path).alle()[0]
    assert d.geboortejaar == 2004
    opname = Opname.nieuw(d, pd.Timestamp("2027-03-01 10:00", tz="UTC"), root=tmp_path)
    assert opname.info.leeftijd_bij_opname == 23
    with sqlite3.connect(tmp_path / "ecg.db") as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == opslag.SCHEMA_VERSIE


def test_ongedaan_maken_en_opnieuw_doen(tmp_path: Path) -> None:
    from kern.opslag import GESCHIEDENIS

    GESCHIEDENIS.wis()
    register = Deelnemers(tmp_path)
    d = register.toevoegen("Undo", 1996, "vrouw", False)
    opname = Opname.nieuw(d, nu(), root=tmp_path)
    opname.start_periode("Zitten")  # één stap, ook al schrijft hij intern twee keer
    opname.wijzig(opname.annotaties[0].id, label="Staan")
    assert [s.label for s in GESCHIEDENIS.terug][-3:] == ["Nieuwe opname", "Periode gestart", "Annotatie gewijzigd"]

    assert GESCHIEDENIS.ongedaan() == "Annotatie gewijzigd"
    assert Opname.laad(opname.map).annotaties[0].label == "Zitten"
    assert GESCHIEDENIS.opnieuw() == "Annotatie gewijzigd"
    assert Opname.laad(opname.map).annotaties[0].label == "Staan"

    (opname.map / "ruw").mkdir()
    (opname.map / "ruw" / "data.txt").write_text("ruw")
    Opname.laad(opname.map).verwijder_opname()
    assert not opname.map.exists() and Opname.alle(tmp_path) == []
    assert GESCHIEDENIS.ongedaan() == "Opname verwijderd"  # map en gegevens terug
    assert (opname.map / "ruw" / "data.txt").read_text() == "ruw" and len(Opname.alle(tmp_path)) == 1
    assert GESCHIEDENIS.opnieuw() == "Opname verwijderd"
    assert not opname.map.exists()
    GESCHIEDENIS.ongedaan()
    shutil.rmtree(opname.map / "ruw")  # een map met data blijft bij ongedaan maken staan; leeg wordt hij opgeruimd

    GESCHIEDENIS.ongedaan()  # Annotatie gewijzigd
    GESCHIEDENIS.ongedaan()  # Periode gestart
    assert GESCHIEDENIS.ongedaan() == "Nieuwe opname"
    assert Opname.alle(tmp_path) == [] and not opname.map.exists()  # lege map opgeruimd
    register.toevoegen("Nieuw", None, "onbekend", False)  # nieuwe actie: opnieuw doen kan niet meer
    assert GESCHIEDENIS.opnieuw() is None


def test_signalen_wissen_de_geschiedenis(tmp_path: Path) -> None:
    from kern.opslag import GESCHIEDENIS

    GESCHIEDENIS.wis()
    t0 = pd.Timestamp("2026-10-05 08:00:00", tz="UTC")
    opname = Opname.nieuw(_deelnemer(tmp_path), t0, root=tmp_path)
    assert GESCHIEDENIS.terug
    opname.bewaar_signalen(_signalen(t0), [])
    assert GESCHIEDENIS.ongedaan() is None
