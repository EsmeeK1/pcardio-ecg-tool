# kern/ en tests van de ECG-tool

Deze map bevat de logica zonder UI (`kern/`), de helpteksten, de configuratie en de tests van de ECG-tool. De
app zelf staat in [desktop/](../desktop/); installeren en starten staat in de [README in de projectroot](../README.md).
De map heet nog `streamlit/` omdat de eerste versie van de app een Streamlit-app was.

## Bestanden en mappen

```
streamlit/
├── hulp.py                # helpteksten (tooltips in de desktop-app)
├── kern/                  # logica zonder UI (ook te gebruiken vanuit notebooks)
│   ├── pcardio.py         # P-Cardio-bestanden inlezen (CSV + binair)
│   ├── pcardio_protocol.py # live protocol: framing, pakketten, configuratie (zonder I/O)
│   ├── dongle.py          # seriële verbinding met de dongle + gesimuleerde dongle
│   ├── live_sessie.py     # verbinden, streamen, ringbuffer
│   ├── opslag.py          # deelnemers, opnames, annotaties, signalen (ecg.db)
│   ├── synchronisatie.py  # gedeelde datamap (OneDrive), één computer tegelijk
│   ├── koppelen.py        # bestanden inlezen en aan een opname koppelen
│   ├── verwerking.py      # 6 leads, weergavefilter, sync-sprong zoeken
│   ├── beweging.py        # UC-1: activiteit en houding per 20 s
│   ├── kwaliteit.py       # UC-2: signaalkwaliteit per 20 s
│   └── export.py          # gecombineerde export
├── handleiding.pdf        # P-Cardio-instructie voor deelnemers (pagina 1–4 gaan in de handleiding van de app)
├── config/
│   ├── activiteiten.txt   # knoppen voor perioden (één per regel, aan te vullen)
│   └── momenten.txt       # knoppen voor momenten
├── tests/                 # fixtures/probe_dongle.log: ruwe regels van echte hardware (id en MAC vervangen)
└── data/                  # alle gegevens — in .gitignore
    ├── ecg.db             # SQLite: deelnemers, opnames, annotaties
    └── opnames/<YYYY-MM-DD_HHMM>_<deelnemer-id>/
        ├── ruw/           # onveranderde kopie van de ingelezen P-Cardio-bestanden
        ├── signalen/      # ingelezen signalen als parquet (snel laden), plus de UC-2-cache
        └── export/        # gecombineerde exports
```

`data/` bevat namen en gezondheidsgegevens en staat daarom in `.gitignore`. Maak er zelf een back-up van.

### Annotaties (ook in de export)

| Kolom | Betekenis |
|---|---|
| `soort` | `periode`, `moment` of `sync` |
| `label` | activiteit of moment, bijv. `Lopen (rustig)`, `markering` |
| `t_start`, `t_eind` | ISO 8601 met tijdzone; `t_eind` leeg bij een moment |
| `tijdbasis` | `pc` = live gelogd met de pc-klok (klokcorrectie wordt erbij opgeteld), `data` = achteraf in P-Cardio-tijd |
| `opmerking` | vrije tekst |
| `beoordeling`, `beoordeling_opmerking` | signaalkwaliteit: `schoon`, `ruis, QRS herkenbaar`, `onbruikbaar` + toelichting |
| `plaatsing` | experimentconditie van een periode, bijv. `R3-Y3-G1-Z1`; leeg bij oudere opnames |

### Vanuit een notebook

```python
import sys; sys.path.insert(0, "../streamlit")   # pad naar deze map
from kern.opslag import Opname, DATA_ROOT

opname = Opname.alle(DATA_ROOT)[0]
signalen = opname.laad_signalen()              # {"ecg": Signaal, "acc": Signaal, ...}
for a in opname.chronologisch():
    start, eind = opname.in_datatijd(a)        # met klokcorrectie, in P-Cardio-tijd
```

## Belangrijk om te weten

- **6 leads zijn een aanname.** De P-Cardio meet 2 kanalen. De app gaat ervan uit dat `Ecg1` = afleiding I en
  `Ecg2` = afleiding II, en rekent daaruit III, aVR, aVL en aVF af (Einthoven/Goldberger). Dat klopt alleen als
  de elektroden daarvoor geplaatst zijn. De toewijzing staat in `kern/verwerking.py` (`LEAD_I`, `LEAD_II`).
- **Tijdzones.** De CSV-export van de P-Cardio zet de tijdzone in de kolomnaam (`Time (UTC+01:00)`); de app
  rekent alles intern om naar UTC en toont Nederlandse kloktijd. Het binaire bestand bevat Unix-tijd (UTC).
- **Weergavefilter.** Het ECG-filter van 0,5–40 Hz geldt alleen voor de plot; opgeslagen data en export blijven
  ruw.
- **Live protocol.** Wat er op echte hardware afwijkt van de handleiding staat in `kern/pcardio_protocol.py`;
  `scripts/probe_device.py` test de verbinding los van de app.
- **Nog niet ondersteund:** een opname die over meerdere bestanden verdeeld is (bij >512 MB of na opnieuw
  docken).

## Tests

```powershell
pip install pytest                 # eenmalig; niet nodig om de app te draaien
cd streamlit
..\.venv\Scripts\python -m pytest -q
```

De tests gebruiken een tijdelijke datamap (via `ECG_TOOL_DATA`) en schrijven dus niet in `data/`. Optioneel ook met
een echte P-Cardio-export: zet `ECG_TOOL_TESTDATA` op een map met `Ecg_2Ch.csv`.

## Uitbreiden

- **Activiteiten of momenten toevoegen:** een regel in `config/activiteiten.txt` of `config/momenten.txt`.
- **Logica** hoort in `kern/` (zonder UI), zodat die ook in notebooks en tests bruikbaar is.
- **Nieuw pakket nodig?** Zet het in `requirements.txt` en voer `init_repo.cmd` opnieuw uit.
