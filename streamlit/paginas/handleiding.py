"""Handleiding van de ECG-tool: begrippen, uitleg per pagina en problemen oplossen."""

from __future__ import annotations

import streamlit as st

import hulp
from ui import link

st.title("Handleiding", help="Alles over het gebruik van de ECG-tool. Bij de meeste knoppen en velden staat ook een ?-icoontje met uitleg.")

snel, begrippen, paginas, problemen, bestanden = st.tabs(
    ["Snel aan de slag", "Begrippen", "De pagina's", "Problemen oplossen", "Bestanden"],
)

# --- snel aan de slag ---
with snel:
    st.markdown(
        """
### Wat doet de ECG-tool?

Je maakt een opname met de P-Cardio. Terwijl die loopt, houd je in de app bij **wat de deelnemer doet**
(zitten, lopen, springen, …). Na de opname laad je de data van de P-Cardio in, en de app legt die twee
over elkaar. Zo zie je per activiteit hoe het ECG-signaal eruitziet, met de beweging eronder.

### Zo verloopt een opname

| | Wat | Waar |
|---|---|---|
| **Vóór** | Deelnemer vastleggen, P-Cardio instellen en de tijd gelijkzetten met deze pc | **Deelnemers**, P-Cardio |
| **Tijdens** | Sync-sprong, activiteiten en momenten aanklikken | **Live opname** |
| **Na** | P-Cardio-bestanden inlezen, koppelen, klokcorrectie bevestigen | **Data koppelen** |
| **Analyse** | Per activiteit bekijken, corrigeren en beoordelen | **Bekijken & annoteren** |
| **Optioneel** | Alles in één CSV voor een notebook | **Export** |

### Eerste keer?

Begin met de **test-opname**: een korte opname van ± 8 minuten waarmee je alle stappen één keer doorloopt.
Wil je eerst oefenen zonder P-Cardio? Op die pagina kun je ook een oefenopname maken met bestaande data.

Bij de meeste knoppen en velden staat een **?**-icoontje: ga er met de muis op staan voor uitleg.
""",
    )
    link("paginas/testopname.py", "Naar de test-opname")

# --- begrippen ---
with begrippen:
    st.markdown(
        """
### Opname
Eén meting met de P-Cardio bij één deelnemer. Een opname bundelt de gegevens (wie, wanneer, plek van de
elektroden, instellingen), de annotaties en, na het koppelen, de P-Cardio-data.

### Annotatie
Alles wat je vastlegt over wat er gebeurde. Er zijn drie soorten:

- **Periode**: een activiteit met een **begin en een eind**, bijv. *Lopen (rustig)* van 10:03:00 tot 10:04:00.
  In de plots een **gekleurd vlak**.
- **Moment**: **één tijdstip**, bijv. *Hoest* of *Elektrode los*. In de plots een **oranje lijn**.
- **Sync-sprong**: een speciaal moment om de klokken gelijk te zetten (zie hieronder). In de plots een **rode
  stippellijn**.

Live kan er maar **één periode tegelijk** lopen: start je een nieuwe, dan stopt de vorige op hetzelfde moment.
Achteraf kun je perioden ook laten overlappen.

### Twee klokken en de sync-sprong
De **P-Cardio** zet een tijd bij elke meting, de **pc** zet een tijd bij elke klik in de app. Die twee klokken
lopen nooit precies gelijk (het gelijkzetten gaat per hele seconde, en klokken lopen uit elkaar).

De **sync-sprong** is één gebeurtenis die op beide klokken terechtkomt: jij klikt op het moment dat de
deelnemer landt (pc-klok), en de landing is een piek in de accelerometer (P-Cardio-klok). Het verschil tussen
die twee is de **klokcorrectie**. De app zoekt de piek zelf op; jij controleert het in een plot.

Voor perioden van een minuut maakt een seconde verschil weinig uit, maar voor momenten (een hoest duurt minder
dan een seconde) wel. Doe de sprong aan het **begin** en het **eind**: dan zie je ook of de klokken tijdens de
opname uit elkaar zijn gaan lopen.
""",
    )
    st.markdown("### De P-Cardio-klok gelijkzetten\n" + hulp.KLOK_GELIJKZETTEN_UITLEG)
    st.markdown("### Klokcorrectie\n" + hulp.KLOKCORRECTIE_UITLEG)
    st.markdown(
        """
### Tijdbasis: pc of data
- Annotaties die je **live** maakt, staan in **pc-tijd**. De klokcorrectie wordt erbij opgeteld.
- Annotaties die je **achteraf** in de plot maakt, staan meteen in **P-Cardio-tijd** en schuiven dus niet mee
  als je de klokcorrectie aanpast.

### Label en beoordeling
Houd die twee bewust uit elkaar:

- het **label** zegt **wat de deelnemer deed** (*Lopen*);
- de **beoordeling** zegt **hoe het signaal eruitziet**: *schoon*, *ruis, QRS herkenbaar* of *onbruikbaar*.

"Lopen" betekent niet automatisch "slecht signaal" — juist dat willen we te weten komen.

### 6 leads
De P-Cardio meet **2 kanalen** (Ecg1 en Ecg2). De app rekent daaruit vier extra afleidingen uit (III, aVR, aVL,
aVF) met de wetten van Einthoven. Dat klopt alleen als **Ecg1 = afleiding I** en **Ecg2 = afleiding II**, dus
als de elektroden daarvoor geplaatst zijn. In de zijbalk van **Bekijken & annoteren** kies je bij
**ECG-kanalen** welke afleidingen je ziet; standaard alleen **I (= Ecg1)**.

### ECG-filter (alleen weergave)
Het ruwe signaal heeft vaak een flinke offset, langzame drift en wat ruis, waardoor de hartslagen klein of
onrustig lijken. Het **ECG-filter 0,5–40 Hz** (zijbalk, standaard aan) haalt dat eruit, zoals klinische
ECG-viewers doen. Het filter geldt **alleen voor de plot**: de opgeslagen data en de export blijven ruw. Uit =
het signaal zoals de hardware het meet; drift en ruis zijn zelf ook artefacten, dus kijk bij twijfel naar
allebei.
""",
    )

# --- de pagina's ---
with paginas:
    with st.expander("Deelnemers", expanded=True):
        st.markdown(
            """
- **Nieuwe deelnemer**: voornaam of patiënt-ID, leeftijd, geslacht, hartdecompensatie, andere aandoening.
- De deelnemer krijgt een **ID** (`D001`, …). Zet dat ID in het **User Id**-veld van de P-Cardio, niet de naam:
  dat veld wordt op het apparaat niet versleuteld.
- **Bewerken**: gegevens aanpassen; het ID blijft hetzelfde.
- **Deelnemer verwijderen** (onder *Bewerken*): kan alleen als de deelnemer **geen opnames** heeft. Het ID wordt
  daarna niet opnieuw uitgegeven.
""",
        )
        link("paginas/deelnemers.py", "Naar Deelnemers")
    with st.expander("Live opname"):
        st.markdown(
            """
1. **Nieuwe opname**: kies de deelnemer en de plaatsing van de elektroden (**📷 Foto's** toont beide opties),
   controleer de meetconfiguratie en vink aan dat de P-Cardio-tijd is gelijkgezet.
2. **Sync-sprong** aan het begin (en het eind).
3. **Perioden**: klik op een activiteit als die begint; **Stop periode** als de rustpauze begint. Staat de
   activiteit er niet bij? Typ hem bij *Andere activiteit*.
4. **Momenten**: klik meteen als er iets gebeurt. **Markeer nu** legt een moment vast zonder omschrijving; die
   vul je later in het logboek in.
5. **Logboek** onderaan: label en opmerking direct aanpassen; fout geklikt → *verwijder?* aanvinken en op de knop
   eronder klikken.
6. **Opname afsluiten** als je klaar bent.

Bovenaan zie je welke periode loopt en hoe lang al, de klok van de pc, en of er al een sync-sprong is.
Browser per ongeluk dicht? **Opname hervatten** op dezelfde pagina.
""",
        )
        link("paginas/live.py", "Naar Live opname")
    with st.expander("Data koppelen"):
        st.markdown(
            """
1. **Inlezen**: upload de bestanden, of geef het pad naar een map op (handig voor grote `data_*.txt`-bestanden).
   Je kunt CSV-exports (`Ecg_2Ch.csv`, `Acc.csv`, `Gyro.csv`) en het binaire `data_*.txt` gebruiken. Controleer
   in de tabel de sample rates en de start- en eindtijd.
   Een eerdere export van deze app kan ook terug: `…_volledig.csv` en/of `…_annotaties.csv`, los of in een
   `.zip`. De app herkent zelf wat elk bestand is. Annotaties vervangen die van de opname, en de klokcorrectie
   uit het annotatiebestand wordt overgenomen.
2. **Koppelen**: de app stelt de opname voor waarvan de annotaties in de tijd binnen de data vallen. Kies zelf
   als het niet klopt, of kies **Nieuwe opname** als er niet live geannoteerd is.
3. **Klokcorrectie**: per sync-sprong een plot met de gelogde tijd (grijze stippellijn) en de gevonden piek (rode
   lijn). Valt de rode lijn op de landingspiek? Dan **Gebruik voorstel**. Anders handmatig invullen en
   **Opslaan**. De plots verschuiven daarna niet; de opgeslagen waarde zie je bovenaan bij *Huidige correctie*,
   en het effect op **Bekijken & annoteren** (de annotaties schuiven mee).
""",
        )
        link("paginas/koppelen.py", "Naar Data koppelen")
    with st.expander("Bekijken & annoteren"):
        st.markdown(
            """
- **Opname** kiezen bovenaan (alleen opnames met gekoppelde data).
- **Segment**: kies een periode of moment, of **Vrij venster** om zelf te bladeren (met een vensterlengte).
  Met **Vorige** en **Volgende** loop je alle annotaties op volgorde door (sneltoets **Shift+↑** / **Shift+↓**).
- **Zijbalk**: welke ECG-kanalen (standaard alleen I = Ecg1), ECG-filter aan/uit, accelerometer, gyroscoop en
  overige kanalen aan/uit (standaard uit), en de marge rond een annotatie: hoeveel seconden je vóór en na een
  gekozen periode of moment extra ziet.
- **Plot**: met *Slepen in de plot* kies je **Zoomen** of **Selecteren**. **Reset assen** (of dubbelklikken) zet
  de zoom terug. Ga met de muis over de lijnen voor waarden; valt dat tijdstip in een periode of op een moment,
  dan staat het **label** er ook bij. **Overzicht hele opname** (uitklapvak) laat zien waar je zit.
- **Scrollbalk** onder de plot: blader in kloktijd door de hele opname met hetzelfde venster. Met **◀ Terug** en
  **Verder ▶** ga je één heel venster terug of verder (sneltoets **Shift+←** / **Shift+→**).
- **Overzicht hele opname**: sleep over een stuk om er een periode van te maken (handig voor lange perioden
  zoals wandelen). Klik op een annotatie in de lijst eronder om die in de grote plot te openen, vanaf het begin.
  Korte momenten (artefacten, springen) annoteer je beter in de grote plot.
- **Annotatie aanpassen** (als je een periode of moment gekozen hebt): label, opmerking, begin/eind verschuiven
  in seconden, en de beoordeling. Vergeet niet op **Opslaan** te klikken.
- **Nieuwe annotatie in dit venster**: voor iets wat live niet gelogd is. Zet *Slepen in de plot* op
  **Selecteren** en sleep over het stuk; begin en eind komen dan vanzelf in de velden (je kunt ze ook zelf
  invullen). Voor een **periode** klik je daarna op een label-knop, of typ je een eigen label en klik je
  **Toevoegen**. Een **moment** krijgt een label uit de keuzelijst.
""",
        )
        link("paginas/bekijken.py", "Naar Bekijken & annoteren")
    with st.expander("Export"):
        st.markdown(
            """
- **Hele opname** of **één periode** (eventueel met marge).
- Eén rij per ECG-sample met Ecg1/Ecg2, de afgeleide leads, accelerometer, gyroscoop, overige kanalen en de
  kolommen **activiteit** en **moment**.
- Het bestand komt in de map `export/` van de opname; kleinere bestanden kun je ook direct downloaden. Een hele
  opname van een uur is al snel > 150 MB.
""",
        )
        link("paginas/export.py", "Naar Export")

# --- problemen ---
with problemen:
    st.markdown(
        """
| Probleem | Oplossing |
|---|---|
| **Fout geklikt tijdens de opname** | Logboek onderaan **Live opname**: label aanpassen, of *verwijder?* aanvinken en verwijderen. Begin/eind verschuiven kan later op **Bekijken & annoteren**. |
| **Te laat op een periode geklikt** | **Bekijken & annoteren** → kies de periode → *Begin verschuiven* met een negatief getal (bijv. −2 s). |
| **Browser dicht of app herstart** | Er gaat niets verloren. **Live opname** → **Opname hervatten**. |
| **Sync-sprong vergeten** | Geen ramp. Vul op **Data koppelen** de correctie handmatig in (vaak 0 s als de klokken gelijkgezet waren), of zoek in de plot een andere duidelijke beweging op en vergelijk die met een gelogd moment. |
| **Geen voorstel bij het koppelen** | De tijden overlappen niet. Kies de opname zelf. Lopen de klokken minuten of uren uiteen (bijv. zomertijd)? Vergroot het zoekvenster bij de klokcorrectie of vul het verschil handmatig in. |
| **"Geen duidelijke piek" bij de sync-sprong** | Bekijk de plot: zie je de landing wel? Vergroot het zoekvenster, of vul de correctie handmatig in. Spring de volgende keer iets steviger. |
| **Hoest of moment valt niet samen met een verstoring** | Controleer de klokcorrectie. Klopt die, dan is er waarschijnlijk te laat geklikt; verschuif het moment. |
| **Fout bij het inlezen van `data_*.txt`** | De lezer voor het binaire bestand is gebouwd op de handleiding van de P-Cardio en nog niet met een echt bestand getest. Gebruik de CSV-export en meld de foutmelding. |
| **ECG-signaal lijkt plat of hartslagen zijn onzichtbaar** | Zet het **ECG-filter** aan in de zijbalk, en zoom in op een paar seconden (slepen in de plot). |
| **Activiteit staat niet in de lijst** | Live: typ hem bij *Andere activiteit*. Vaker nodig? Voeg een regel toe aan `streamlit/config/activiteiten.txt` (of `momenten.txt`) en herlaad de pagina. |
| **Sneltoets doet niets** | Houd **Shift** ingedrukt en druk op de pijltjestoets; de **+** in *Shift + →* hoort er niet bij. Werkt het nog niet? Klik eerst ergens op een lege plek van de pagina. |
| **App waarschuwt dat de instellingen niet geladen zijn** | Je hebt de app vanuit een andere map gestart. Stop hem (`Ctrl+C`) en start vanuit de projectroot: `streamlit run streamlit/app.py`. Anders is de app ook vanaf andere apparaten op het netwerk te openen. |
| **Upload weigert een groot bestand** | Uploaden is beperkt tot 200 MB. Gebruik het tabblad **Bestand of map op deze pc**. |
""",
    )

# --- bestanden ---
with bestanden:
    st.markdown(
        """
Alle gegevens staan in **`streamlit/data/`**. Die map staat in `.gitignore` (er staan namen in) en wordt dus
**niet** in git bewaard: maak er zelf een back-up van.

```
streamlit/data/
├── deelnemers.csv
└── opnames/<datum>_<tijd>_<deelnemer-id>/
    ├── opname.json        gegevens van de opname + klokcorrectie
    ├── annotaties.csv     perioden, momenten, sync-sprongen
    ├── ruw/               onveranderde kopie van de P-Cardio-bestanden
    ├── signalen/          ingelezen signalen (snel te laden)
    └── export/            gemaakte exports
```

**Keuzelijsten aanpassen:** `streamlit/config/activiteiten.txt` en `momenten.txt`, één item per regel.

**Uitleg bij de ?-icoontjes aanpassen:** `streamlit/hulp.py`.

**In een notebook** gebruiken:

```python
import sys; sys.path.insert(0, "../streamlit")
from kern.opslag import Opname, DATA_ROOT

opname = Opname.alle(DATA_ROOT)[0]
signalen = opname.laad_signalen()           # {"ecg": ..., "acc": ..., "gyro": ...}
for a in opname.chronologisch():
    start, eind = opname.in_datatijd(a)     # in P-Cardio-tijd, met klokcorrectie
```
""",
    )
