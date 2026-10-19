# Opnameprotocol P-Cardio (basis)

Dit protocol helpt je op weg met de P-Cardio en de ECG-tool. Het is een **startpunt, geen eindversie**: het legt
vast wat je minimaal moet doen om bruikbare, vergelijkbare opnames te krijgen. De rest zoek je zelf uit. Elke
sectie eindigt daarom met **Zoek zelf uit**: vragen waar dit protocol bewust geen antwoord op geeft.

Wat je ontdekt, schrijf je op (sectie 11). Zo groeit dit protocol mee met wat we leren.

**Doe je dit voor het eerst?** Volg in de app **Test-opname stap voor stap**. Die pagina loopt dit protocol in
het kort door, met een programma van ± 8 minuten.

---

## 1. Doel

We willen weten **hoe het ECG van de P-Cardio eruitziet tijdens gewone activiteiten**, en welke artefacten
(verstoringen) ontstaan door beweging, ademhaling, contact van de elektroden en de manier van dragen.

Daarvoor leg je per opname vast:

- het signaal (ECG, accelerometer en gyroscoop) uit de P-Cardio;
- **wanneer** de deelnemer **wat** deed (perioden en momenten, live gelogd in de app);
- **hoe** er gemeten is (plaatsing, huidvoorbereiding, configuratie).

Zonder die laatste twee is het signaal achteraf niet goed te interpreteren.

## 2. Benodigdheden en rollen

**Spullen**

- P-Cardio-recorder, opgeladen (batterij > 50%)
- Docking-station met USB-kabel
- Elektroden of sticker, afhankelijk van de plaatsing (sectie 5)
- Pc met de ECG-tool (zie de [README](../README.md)) en de PCardio-software van 2M
- Optioneel: de 2M BLE-dongle, om live mee te kijken

**Rollen**: werk met z'n tweeën.

- **Deelnemer**: draagt de P-Cardio en doet de activiteiten.
- **Operator**: bedient de app en klikt perioden en momenten aan.

**Handleidingen**

- `docs/PCARDIO-User-Manual.pdf`: de handleiding van de recorder
- `streamlit/handleiding.pdf`: de handleiding voor deelnemers

**Privacy**: de deelnemer krijgt in de app een ID (`D001`, …). Alleen dat ID komt op de recorder en in
gedeelde bestanden, nooit de naam.

> **Zoek zelf uit**
> - Hoe lang gaat de batterij mee bij deze configuratie? Is 50% genoeg voor jouw opname?
> - Wat staat er in `config.txt` op de recorder, en wat gebeurt er als je die weghaalt?

## 3. Klok van de P-Cardio gelijkzetten

De P-Cardio zet een tijd bij elke meting, en de app zet de tijd van **de pc** bij elke klik. Om signaal en
annotaties aan elkaar te koppelen, moeten die klokken zo goed mogelijk gelijk lopen.

1. Zet de P-Cardio in de docking.
2. Zet met de PCardio-software van 2M (via de USB-verbinding) het `Time`-register gelijk aan de tijd van **de pc
   waarop je straks annoteert**.
3. Doe dit **vlak vóór** de opname.

Dit kan **niet** vanuit de ECG-tool en **niet** via `config.txt`. Vergeten? Met de sync-sprong (sectie 6) rekent
de app het verschil later alsnog uit.

> **Zoek zelf uit**
> - Hoeveel loopt de klok van de P-Cardio uit over een uur? En over een dag?
> - Hoe nauwkeurig kun je de klok gelijkzetten: op de seconde of beter?

## 4. Meetconfiguratie

Gebruik als standaard deze configuratie. De app vult hem al in bij **Live opname**, en kan hem naar de recorder
schrijven via **Live ECG**:

| Sensor | Instelling |
|---|---|
| ECG, 2 kanalen | 250 Hz, gain x6 |
| Accelerometer | 100 Hz, x2 |
| Gyroscoop | 100 Hz, x2 |
| Lead-off, button marker, tap marker, batterij | 5 Hz |

Vul in de PCardio-software het **User Id** in met het deelnemer-ID.

Wijk je af van de standaard, bijvoorbeeld met een lagere gain omdat het signaal klipt? Pas dan bij **Live opname** het veld
**Meetconfiguratie** aan. Zo weet je achteraf hoe deze data gemaakt is.

> **Zoek zelf uit**
> - Wanneer klipt het ECG bij gain x6? Wat verandert er met x4 of x8?
> - Wat levert 500 Hz op ten opzichte van 250 Hz, en wat kost het aan opslag en batterij?
> - Wat doen de button marker en de tap marker precies, en zijn ze bruikbaar als extra sync?

## 5. Deelnemer voorbereiden en elektroden plaatsen

1. Leg de deelnemer vast op de pagina **Deelnemers**.
2. Bereid de huid voor volgens de handleiding van de P-Cardio.
3. Kies een van de twee plaatsingen uit de handleiding. De foto's staan in de app bij **Live opname** → **📷 Foto's**:
   - **Optie 1: met sticker**: de P-Cardio midden op de borst;
   - **Optie 2: met lanyard**: de P-Cardio aan een koord om de nek.
4. Haal de P-Cardio uit de docking. Hij begint dan te loggen met de nieuwe configuratie.
5. **Wacht 2-3 minuten** tot het signaal stabiel is.

Noteer bij **Live opname** de plaatsing en de huidvoorbereiding. Wijk je af, bijvoorbeeld door een elektrode
iets lager te plakken? Schrijf dat erbij. Een foto mag ook.

**Let op:** de app rekent 6 afleidingen uit, in de aanname dat `Ecg1` = afleiding I en `Ecg2` = afleiding II. Dat
klopt alleen als de elektroden daarvoor geplaatst zijn.

> **Zoek zelf uit**
> - Welke plaatsing geeft het schoonste signaal? En welke is het prettigst om te dragen?
> - Welke afleidingen meet de P-Cardio echt bij optie 1 en bij optie 2? Klopt de aanname I/II?
> - Wat doen scheren, schoonmaken met alcohol of gewoon wassen met de signaalkwaliteit?

## 6. Opname starten en sync-sprong

1. Start op de pagina **Live opname** een nieuwe opname. Kies de deelnemer, vul de plaatsing in en vink aan dat
   de klok is gelijkgezet.
2. **Sync-sprong aan het begin:** tel samen af (3-2-1-spring). De deelnemer maakt één sprongetje, en de operator
   klikt op **Sync-sprong** precies op het moment van **landen**.
3. Doe aan het eind van de opname nog een sync-sprong (sectie 8).

De landing is een duidelijke piek in de accelerometer. Daarmee berekent de app achteraf hoeveel de klokken
verschillen (de klokcorrectie).

> **Zoek zelf uit**
> - Hoe nauwkeurig klik je eigenlijk? Vergelijk de klik met de piek in de data.
> - Werkt een andere sync beter, bijvoorbeeld drie keer op de recorder tikken of de knop indrukken?

## 7. Activiteitenprogramma

Het basisprogramma. De operator klikt de activiteit aan als die begint en klikt op **Stop periode** als de rust
begint. Rust ± 20 s tussen de activiteiten.

| # | Activiteit | Duur | Moment(en) |
|---|---|---|---|
| 1 | Zitten | 60 s | 2× **Hoest**, na ± 20 s en ± 40 s |
| 2 | Staan | 60 s | |
| 3 | Lopen (rustig) | 60 s | |
| 4 | Armen bewegen | 30 s | |
| 5 | Springen | 30 s | |
| 6 | Herstel (rustig zitten) | 60 s | |

Gebeurt er iets onverwachts, zoals een elektrode die loslaat of een kabel die je raakt? Klik dan meteen op een
**moment** (of op **Markeer nu**) en pas de omschrijving later aan. Fout geklikt? Corrigeer het in het logboek
onderaan de pagina.

De app heeft meer activiteiten en momenten dan dit programma gebruikt, bijvoorbeeld liggen, traplopen,
praten en bukken. Die lijsten staan in `streamlit/config/activiteiten.txt` en `momenten.txt`, en je mag ze
aanvullen.

> **Zoek zelf uit**
> - Stel een eigen programma samen. Welke activiteiten geven de meeste artefacten?
> - Hoe lang moet een periode duren om er iets zinnigs over te zeggen?
> - Kun je artefacten bewust uitlokken (tegen de kabel tikken, een elektrode deels loshalen) en ze daarna
>   herkennen in het signaal?

## 8. Afsluiten en data van de recorder halen

1. Doe een **tweede sync-sprong** (aftellen, springen, klikken bij het landen).
2. Klik op **Opname afsluiten**.
3. Zet de P-Cardio terug in de docking.
4. Kopieer de bestanden naar de pc: de `data_*.txt`-bestanden, of de CSV-export (`Ecg_2Ch.csv`, `Acc.csv`,
   `Gyro.csv`). Laat `config.txt` op de recorder staan.

Met twee sync-sprongen zie je of de klokken tijdens de opname uit elkaar zijn gaan lopen.

> **Zoek zelf uit**
> - Wat is het verschil tussen het binaire `data_*.txt` en de CSV-export? Geven ze hetzelfde signaal?
> - Wat gebeurt er bij een lange opname: wanneer splitst de recorder het bestand?

## 9. Data koppelen en controleren

Op de pagina **Data koppelen**:

1. **Inlezen:** kies alle bestanden van één opname tegelijk. Controleer de sample rates en de start- en eindtijd.
2. **Koppelen:** de app stelt de opname voor die in de tijd past. Klopt dat? Klik **Koppel**.
3. **Klokcorrectie:** valt bij elke sync-sprong de lijn op de piek? Dan **Gebruik voorstel**. Noteer het verschil
   tussen de eerste en de tweede sprong.

> **Zoek zelf uit**
> - Hoe groot is de klokcorrectie meestal? Is hij stabiel tussen opnames?
> - Wat doe je als de piek niet duidelijk is?

## 10. Bekijken en beoordelen

Op de pagina **Bekijken & annoteren**:

Nog geen eigen opname? Maak op **Test-opname stap voor stap** een oefenopname van de oefendata, en oefen deze
stappen daarmee.

1. Loop de perioden door met **Volgende**. Begin met **Zitten**: zie je de hartslagen?
2. Bekijk het signaal met het **ECG-filter** (0,5–40 Hz) aan en uit. Het filter geldt alleen voor de weergave.
3. Bekijk de hoestmomenten: valt de lijn samen met een verstoring in ECG of accelerometer?
4. Beoordeel elke periode: **schoon**, **ruis, QRS herkenbaar** of **onbruikbaar**, met een korte toelichting.
5. Maak eventueel een **Export** (één CSV met alles per sample) voor verdere analyse in een notebook.

> **Zoek zelf uit**
> - Is één ECG-kanaal gevoeliger voor beweging dan het andere?
> - Kun je met de accelerometer of gyroscoop voorspellen wanneer het ECG onbruikbaar wordt?
> - Zijn de beoordelingen van twee mensen voor dezelfde periode gelijk?

## 11. Evaluatie: wat viel op?

Schrijf na elke opname kort op wat je opviel. Zet het in de **Notities** van de opname, of in een gedeeld
document:

- Werkte de sync-sprong? Hoe groot was de klokcorrectie?
- Welke activiteiten gaven artefacten, en hoe zagen die eruit?
- Wat was onhandig in het protocol of in de app?
- Welke vraag uit **Zoek zelf uit** heb je beantwoord, en wat is het antwoord?

Wat werkt, komt in de volgende versie van dit protocol. Wat niet werkt, gaat eruit.
