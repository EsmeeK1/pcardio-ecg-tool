# ECG-tool P-Cardio

Streamlit-app om eigen P-Cardio-opnames vast te leggen, te annoteren en te bekijken. Bedoeld om de hardware te
testen: hoe ziet het signaal eruit bij zitten, lopen, springen, …, en welke artefacten ontstaan daarbij. Hoort
bij het [opnameprotocol](../docs/opnameprotocol-p-cardio.md).

## Opstarten

Installeren (Python 3.12.x, `init_repo.cmd`, `.venv`) staat stap voor stap in de
[README in de projectroot](../README.md). Daarna, vanuit de projectroot:

```powershell
.venv\Scripts\Activate.ps1
streamlit run streamlit\app.py
```

De app opent op <http://localhost:8501>. Stoppen: `Ctrl+C` in de terminal.

In WSL gebruik je een eigen Linux-venv (`source <venv>/bin/activate`) en `streamlit run streamlit/app.py`. Een
Windows-venv werkt niet in WSL en andersom.

## Werkwijze

| Pagina | Wat je er doet |
|---|---|
| **Test-opname stap voor stap** | Een korte eerste opname (± 8 minuten opnemen) met afvinkbare stappen, van voorbereiden tot bekijken. Ook: een oefenopname maken met de data van januari 2026 (`data/test/`, zie hieronder). |
| **Handleiding** | Begrippen (periode, moment, sync-sprong, klokcorrectie, tijdbasis), uitleg per pagina, problemen oplossen, bestanden. |
| **Deelnemers** | Persoon vastleggen: voornaam of patiënt-ID, leeftijd, geslacht, hartdecompensatie ja/nee, andere bekende aandoening. Krijgt een ID (`D001`, …) — die zet je ook in het `User Id`-veld van de P-Cardio. |
| **Live opname** | Tijdens de opname: **sync-sprong**, **perioden** (activiteit met begin en eind) en **momenten** (één tijdstip, bijv. hoest) loggen met de pc-klok. Een nieuwe periode stopt de vorige. Fout geklikt? Pas het aan of verwijder het in het logboek onderaan. |
| **Live ECG** | Het ECG van de P-Cardio live bekijken via de 2M BLE-dongle (of een gesimuleerde dongle om te oefenen). Alleen kijken, er wordt niets opgeslagen. Tijdens het streamen staat er ook een klein live-ECG op **Live opname**. |
| **Data koppelen** | Na de opname: P-Cardio-bestanden inlezen, koppelen aan de juiste opname en de klokcorrectie bepalen. |
| **Bekijken & annoteren** | Per periode, moment of vrij venster de 6 leads met accelerometer, gyroscoop en overige kanalen eronder. Met de muis op het signaal zie je ook het label. Bladeren met **◀ Terug** / **Verder ▶** (Shift+← / Shift+→) en **Vorige** / **Volgende** annotatie (Shift+↑ / Shift+↓). Annotaties corrigeren (label, begin/eind verschuiven), beoordelen, of nieuwe toevoegen. |
| **Export** | Eén CSV per opname (of per periode) met ECG, 6 leads, beweging en de kolommen `activiteit`, `moment`, `plaatsing` en `experiment` per sample. |

### Live opname

1. Start de opname en klik als eerste op **Sync-sprong**: tel samen af, de deelnemer springt één keer, en jij
   klikt op het moment van landen. Doe dat liefst ook aan het eind.
2. Klik op een activiteit als die begint, en op **Stop periode** als de rustpauze begint.
3. Klik op een moment (of **Markeer nu**) zodra er iets gebeurt; de omschrijving kun je achteraf aanpassen.

Elke klik wordt direct opgeslagen. Browser dicht of app herstart? Kies **Opname hervatten**.

**Experimenten:** vul bij het starten het optionele veld **Experiment** in (bijv. *Elektrodeplaatsing 21-10*). Het
geldt voor de hele opname. Boven de periodeknoppen staat het veld **Plaatsing** (bijv. *R3-Y3-G1-Z1*). Dat wordt
opgeslagen bij elke periode die je start en blijft staan tot je het wijzigt. Beide velden zijn later aan te passen
in het logboek en op **Bekijken & annoteren**, en komen in de export.

### Live ECG

1. Sluit de PCardio-app (de dongle kan maar met één programma tegelijk praten) en steek de dongle in een USB-poort.
2. Kies in de zijbalk **Echte dongle**; de poort wordt herkend aan de USB-id van de dongle (`1915:521A`).
3. Klik op **Verbinden**. Vindt hij de recorder niet binnen 30 s: druk kort op de knop van de P-Cardio en probeer
   opnieuw. Daarna **Start**, en na afloop **Ontkoppelen** (geeft de poort weer vrij).

**Verbinding weg** (bijvoorbeeld als je even wegloopt van de laptop): de app merkt dat aan een melding van de
dongle of doordat er 10 s geen data komt, en probeert dan vanzelf steeds opnieuw te verbinden (elke poging tot
20 s, 5 s pauze ertussen). Liep het ECG, dan start het daarna weer. Op **Live ECG** en **Live opname** staat dan
een melding met de knop **Opnieuw verbinden** of **Stop met opnieuw verbinden**. Automatisch opnieuw verbinden
staat aan; uitzetten kan in de zijbalk van **Live ECG**.

De app schrijft alleen de pincode naar de recorder. Meet de recorder geen ECG, dan biedt de pagina aan de
standaardconfiguratie te schrijven; dat gebeurt alleen na bevestiging, want de recorder gebruikt die daarna ook als
hij zelf logt. Het protocol en wat er op echte hardware afwijkt van de handleiding staat in
`kern/pcardio_protocol.py`; `scripts/probe_device.py` test de verbinding los van de app.

### Data koppelen

1. **Inlezen:** upload de bestanden, of geef het pad op naar een bestand of map op de pc (handig voor grote
   `data_*.txt`-bestanden; uploaden is beperkt tot 200 MB per bestand). Kies alle bestanden van één opname
   tegelijk, bijv. `Ecg_2Ch.csv` + `Acc.csv` + `Gyro.csv`.
2. **Koppelen:** de app stelt de opname voor waarvan de live annotaties in de tijd binnen de data vallen. Klopt
   het voorstel niet, kies dan zelf een opname, of maak een nieuwe (als er niet live geannoteerd is: dan
   annoteer je achteraf op **Bekijken & annoteren**).
3. **Klokcorrectie:** de app zoekt rond elk gelogd sync-moment de landing van de sprong in de accelerometer
   (grootste afwijking van |acc|) en laat die zien in een plot. Klopt de piek, klik dan op
   **Gebruik voorstel**. Anders vul je de correctie handmatig in.

De klokcorrectie wordt opgeteld bij alle **live** gelogde tijden (pc-klok). Annotaties die je achteraf in de
plot maakt, liggen al in P-Cardio-tijd en verschuiven niet mee.

## Bestanden en mappen

```
streamlit/
├── app.py                 # startpunt + navigatie
├── ui.py                  # gedeelde Streamlit-onderdelen
├── hulp.py                # teksten van de ?-pop-ups
├── paginas/               # één bestand per pagina
├── kern/                  # logica zonder Streamlit (te gebruiken vanuit notebooks)
│   ├── pcardio.py         # P-Cardio-bestanden inlezen (CSV + binair)
│   ├── pcardio_protocol.py # live protocol: framing, pakketten, configuratie (zonder I/O)
│   ├── dongle.py          # seriële verbinding met de dongle + gesimuleerde dongle
│   ├── live_sessie.py     # verbinden, streamen, ringbuffer
│   ├── opslag.py          # deelnemers, opnames, annotaties, signalen
│   ├── verwerking.py      # 6 leads, weergavefilter, sync-sprong zoeken
│   ├── plots.py           # plotly-figuren
│   └── export.py          # gecombineerde export
├── assets/                # logo en foto elektrodenplaatsing
├── handleiding.pdf        # handleiding voor deelnemers
├── config/
│   ├── activiteiten.txt   # knoppen voor perioden (één per regel, aan te vullen)
│   └── momenten.txt       # knoppen voor momenten
├── tests/                 # fixtures/probe_dongle.log: ruwe regels van echte hardware (id en MAC vervangen)
└── data/                  # alle gegevens — in .gitignore, behalve test/
    ├── deelnemers.csv     # namen: nooit in git
    ├── test/              # oefendata (Ecg_2Ch.csv, Acc.csv, Gyro.csv) voor de oefenopname — in git
    └── opnames/<YYYY-MM-DD_HHMM>_<deelnemer-id>/
        ├── opname.json    # deelnemer, starttijd, configuratie, experiment, notities, klokcorrectie, bronbestanden
        ├── annotaties.csv # perioden, momenten, sync-sprongen
        ├── ruw/           # onveranderde kopie van de ingelezen P-Cardio-bestanden
        ├── signalen/      # ingelezen signalen als parquet (snel laden)
        └── export/        # gecombineerde exports
```

`data/` bevat namen en gezondheidsgegevens en staat daarom in `.gitignore`. Maak er zelf een back-up van.

**Uitzondering:** `data/test/` gaat wél mee in git. Daarin staat de oefendata voor de oefenopname op
**Test-opname stap voor stap** (januari 2026, volwassen man met een hartaandoening).

### annotaties.csv

| Kolom | Betekenis |
|---|---|
| `soort` | `periode`, `moment` of `sync` |
| `label` | activiteit of moment, bijv. `Lopen (rustig)`, `Hoest` |
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
  de elektroden daarvoor geplaatst zijn. Kies in de zijbalk bij **ECG-kanalen** welke afleidingen je ziet
  (standaard alleen I = Ecg1).
  De toewijzing staat in `kern/verwerking.py` (`LEAD_I`, `LEAD_II`).
- **De lezer voor het binaire `data_*.txt` is nog niet getest met een echt bestand.** Hij is gebouwd op de
  interface-handleiding v7.0 (`docs/PCardio - Interface v7.0.pdf`, §6-§8) en getest met een synthetisch bestand volgens die handleiding. De handleiding
  laat een paar details open (bytevolgorde, indeling van de pakketheader); de app controleert die tegen de
  payload-grootte in elke header en geeft een duidelijke fout als het niet klopt. Vergelijk bij de eerste echte
  opname het resultaat met een CSV-export van dezelfde opname.
- **Tijdzones.** De CSV-export van de P-Cardio zet de tijdzone in de kolomnaam (`Time (UTC+01:00)`); de app
  rekent alles intern om naar UTC en toont Nederlandse kloktijd. Het binaire bestand bevat Unix-tijd (UTC).
- **Weergavefilter.** Op **Bekijken & annoteren** staat standaard een ECG-filter van 0,5–40 Hz aan (zijbalk).
  Dat geldt alleen voor de plot; opgeslagen data en export blijven ruw.
- **Nog niet ondersteund:** een opname die over meerdere bestanden verdeeld is (bij >512 MB of na opnieuw
  docken).

## Tests

```powershell
pip install pytest                 # eenmalig; niet nodig om de app te draaien
python -m pytest -q streamlit\tests
```

Staat er oefendata in `data/test/`, dan maakt de test van **Test-opname** daar ook een oefenopname van (± 20 s
extra).

Optioneel ook met een echte P-Cardio-export: zet `ECG_TOOL_TESTDATA` op een map met `Ecg_2Ch.csv`.
De paginatests gebruiken een tijdelijke datamap (via `ECG_TOOL_DATA`) en schrijven dus niet in `data/`.

De pagina's worden los getest met AppTest (Streamlit's testframework).

## Uitbreiden

- **Activiteiten of momenten toevoegen:** een regel in `config/activiteiten.txt` of `config/momenten.txt`.
- **Nieuwe pagina:** maak `paginas/<naam>.py` en voeg een `st.Page(...)` toe aan `PAGINAS` in `app.py`.
- **Logica** hoort in `kern/` (zonder Streamlit), zodat die ook in notebooks en tests bruikbaar is.
- **Huisstijl:** zet geen kleuren in de pagina's. Gebruik de thema-kleuren uit `.streamlit/config.toml` (bijv.
  `type="primary"` voor een knop) en in grafieken `PRIMAIR`, `ORANJE` en `GRAFIEK` uit `kern/plots.py`. Oranje
  is schaars: alleen voor het belangrijkste getal of datapunt. Teksten in het Nederlands, kort, en geschreven voor
  wie de opname doet. Uitleg hoort in `hulp.py` (de ?-pop-ups), niet in de pagina zelf.
- **Nieuw pakket nodig?** Zet het in `requirements.txt` en voer `init_repo.cmd` opnieuw uit.
