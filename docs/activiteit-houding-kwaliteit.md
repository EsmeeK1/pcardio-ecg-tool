# Activiteit, houding en kwaliteit: berekeningen en keuzes

> **Intern.** Dit document beschrijft onze eigen aanpak. Niet delen met het studentenproject.

Dit document legt uit hoe de ECG-tool per segment de activiteit en houding bepaalt (UC-1) en hoe hij de
signaalkwaliteit beoordeelt (UC-2). Bij elke stap staan de berekening, de drempel en de reden voor die keuze.

**Bronnen**

| Wat | Waar |
|---|---|
| Code UC-1 | [streamlit/kern/beweging.py](../streamlit/kern/beweging.py) |
| Code UC-2 | [streamlit/kern/kwaliteit.py](../streamlit/kern/kwaliteit.py) |
| Tests | [test_beweging.py](../streamlit/tests/test_beweging.py), [test_kwaliteit.py](../streamlit/tests/test_kwaliteit.py) |
| Onderbouwing | repo `secu-sense-wp4`: `experiments/uc1_beweging/README.md` (notebooks 01–03) en `experiments/uc2_kwaliteit/README.md` (notebook 01) |
| Eisen | *Use-cases en requirements Secu-Sense WP4* v0.4 (AI-01 t/m AI-06, HW-06, HW-08) |

**Status (20-11-2026)**

- De UC-1-drempel voor de lanyard is getoetst met leave-one-out per opname. De andere drempels zijn startwaarden.
- UC-2 heeft nog geen enkele handmatige beoordeling. Alle UC-2-drempels zijn daarom gekozen op proxy-labels:
  de omstandigheid tijdens de opname, niet het oordeel over het ECG zelf. Op 20-11 zijn de regels getoetst over alle
  38 opnames en aangescherpt (zie [journal 2026-11-20](journal/2026-11-20-uc2-afronden.md)).
- UC-2 draait ook live: een badge met de kwaliteit van de laatste 20 s, elke 5 s opnieuw (§5).
- Alle cijfers komen van **twee deelnemers** (D001 en D002). Er is weinig data met de sticker.

---

## 1. Van opname naar segmenten

1. **Rooster van 20 s** vanaf de eerste acc-sample. Een onvolledig laatste stuk valt weg.
2. **UC-1** bepaalt per segment de activiteit en de houding, alleen uit acc (en gyro, ter informatie).
3. **UC-2** knipt het ECG op dezelfde start- en eindtijden en bepaalt het kwaliteitslabel. De oorzaak komt uit UC-1.

**Waarom 20 s?**
- AI-01 legt vast dat UC-1 en UC-2 dezelfde segmenten gebruiken, zodat elk kwaliteitslabel een activiteit heeft.
- Kortere vensters scoren slechter voor rust tegen beweging (notebook 03): 98,3% bij 20 s, 96,9% bij 10 s, 95,5% bij
  5 s en 94,5% bij 2 s. Een korte verzitting vult een venster van 2 s, maar valt weg in 20 s.
- Een korter venster vraagt ook een andere drempel: 0,016 g bij 2 s, tegen 0,028 g bij 20 s.

**Knippen op tijdstempel, niet op samplenummer.** Volgens de tijdstempels meet de P-Cardio ± 249,3 Hz, niet precies
250 Hz. Wie op samplenummer knipt, laat het ECG-venster wegschuiven ten opzichte van acc en annotaties: tot 50 s
bij lange opnames. UC-2 zoekt daarom per segment de eerste ECG-sample op tijd (`searchsorted`). Daarna wordt het
segment van 249 naar 250 Hz geresampled (`resample_poly`), zodat alle vensters en filters op 250 Hz rekenen.

**Te weinig data.**
- UC-1: zijn er minder dan 90% van de verwachte acc-samples (`MIN_DEKKING`), dan zijn activiteit en houding
  `onbekend` (pad 1a).
- UC-2: een segment zonder volledig ECG, of met NaN erin, valt weg.

---

## 2. Activiteit (UC-1): rust, beweging of lopen

### Berekening

Per sample de grootte van de versnelling, onafhankelijk van hoe de recorder gedraaid is:

```text
|acc| = √(AccX² + AccY² + AccZ²)          (g; in rust ± 1,00 g door de zwaartekracht)
acc_sd = standaardafwijking van |acc| over het segment
```

Daarna geldt:

```text
acc_sd > 0,029 g                       → beweging, anders rust
beweging
  én sterkste piek in 1,2–2,8 Hz
  én stap_aandeel > 0,33 (sticker) of 0,41 (lanyard)
                                       → lopen
```

Het stapritme komt uit het spectrum van `|acc|`:

1. Welch-spectrum van `|acc| − gemiddelde`, met een venster van 4 s. Bij 100 Hz geeft dat stappen van 0,25 Hz.
2. Zoek in de band 0,5–4 Hz de frequentie met het meeste vermogen. Dat is `stap_hz`.
3. `stap_aandeel` = vermogen binnen ± 0,25 Hz van die piek (3 bins) gedeeld door het vermogen in de hele band.

### Waarom zo

| Keuze | Reden |
|---|---|
| `|acc|` in plaats van de losse assen | Hangt niet af van hoe de recorder zit. De zwaartekracht is in rust een constante 1 g, dus de spreiding meet alleen beweging. |
| Standaardafwijking als maat | De eenvoudigste maat die het verschil haalt (B1: regels in plaats van een model, uitlegbaar volgens AI-14). Lineaire versnelling (laagdoorlaat of Madgwick) was niet beter (notebook 03). |
| **0,029 g** | Leave-one-out per opname, lanyard: **89% gebalanceerd** (89% rust, 89% beweging). De drempel bleef over de rondes stabiel op 0,029–0,038 g. Ook D001 → D002 en D002 → D001 scoorden 88% en 89%. Notebook 03 vond 0,028 g als beste drempel bij 20 s. |
| Sticker dezelfde drempel (B3) | Er zijn maar twee sticker-opnames. Eén drempel voor sticker en lanyard samen scoorde beter (73%) dan een aparte drempel per bevestiging (56%). |
| Geen gyro in de regel (B2) | `acc_sd` scoorde 91%, `gyro_sd` 89% (beste drempel op dezelfde data). Eén kenmerk is eenvoudiger. `gyro_sd` wordt wel berekend, ter uitleg. |
| Beweging in een deel van het segment = beweging (pad 3a) | Volgt vanzelf uit de spreiding: 27 van de 28 overgangssegmenten werden beweging. |
| Stapband 1,2–2,8 Hz (B5) | Overgenomen uit ecg-ai notebook 06. Lopen geeft een smalle piek bij 1,75–2,0 Hz die 60–97% van het vermogen bevat, maar alleen als het hele segment lopen is. |
| Lopen apart houden (B6) | Lopen gaf in eigen metingen de meeste storing. Het maakt de oorzaak in UC-2 en de melding in UC-3 specifiek. |
| Geen zitten of staan | Op de borst meet de sensor bij beide dezelfde stand, en er hangt geen beslissing van af. In ecg-ai notebook 06 werd staan maar in 23% herkend. |

### Hoe goed (leave-one-out per opname)

| | Lanyard | Sticker |
|---|---|---|
| Rust/beweging, gebalanceerd | **89%** | 56% per bevestiging, 73% samen |
| Lopen, recall / precisie | 66% / 86% | 43% / 64% |

- De meeste fouten zijn rust die beweging heet (123 van 1158 lanyard-segmenten), vooral in een zitperiode van
  147 min. Waarschijnlijk zijn dat echte kleine bewegingen binnen een grof label.
- Gemist lopen (42 van 108):
  - 12 keer stilstaan binnen een lopen-periode;
  - 14 keer een piek buiten de band, vaak rond 1 Hz (de schrede in plaats van de stap);
  - 16 keer een zwakke piek.
- Een bredere band (0,8–2,8 Hz) gaf 69% / 87%, alleen `acc_sd` gaf 79% / 77%. Geen van beide haalt 80/80. De keuze
  is uitgesteld tot er opnames met schone labels zijn.

---

## 3. Houding (UC-1): rechtop of liggend

### Berekening

```text
g = gemiddelde van (AccX, AccY, AccZ) over het venster    (richting van de zwaartekracht)
kanteling = hoek tussen g en rechtop = arccos( g/|g| · (−1, 0, 0) )   in graden
```

Met de sticker wijst de x-as van de recorder bij rechtop omlaag, vandaar `(−1, 0, 0)`.

| Kanteling | Houding |
|---|---|
| ≤ 45° | rechtop |
| 45°–135° | liggend |
| > 135° | onbekend: de recorder zit omgekeerd |
| bevestiging lanyard | altijd onbekend |
| geen data | onbekend |

**Achteraf** (Bekijken) is het venster het segment van 20 s, zonder marge. **Live** is het venster de laatste 5 s.
Die wordt elke seconde opnieuw berekend, met een marge van 5° (zie hieronder).

### Waarom zo

| Keuze | Reden |
|---|---|
| Gemiddelde over het venster als zwaartekracht | In notebook 03 waren laagdoorlaat (0,3 Hz) en Madgwick (β 0,033) bij elke vensterlengte niet beter dan het gemiddelde: houding 99–100% goed. Op de borst zijn stappen en armbewegingen te klein om de zwaartekracht over 2 s weg te trekken (mediaan bij beweging 24–27°). Madgwick zou wel winnen bij snelle draaiingen, zoals een val, maar die zitten niet in de data. |
| Rechtop = −x | Met de sticker was de zwaartekracht bij staan en lopen stabiel langs −x (spreiding ≤ 0,03, notebook 01). |
| **45°** (B4) | Gangbare grens voor borstmonitors, uit patenten (US 8200321, US 8738118). Het is een ontwerpkeuze van één fabrikant, niet door ons gevalideerd. Op de houdingsopname van 04-11 (sticker) scoorde 45° 99,2–99,7%. |
| **135°** | Daarboven staat de recorder ondersteboven. Dat is geen houding maar een plaatsingsfout. |
| Lanyard: onbekend | Aan een lanyard draait de recorder tot ± 50° weg, ook in rust. De stand zegt dan niets over de houding (HW-06). |
| Live 5 s, elke 1 s | Een venster van 20 s kent een nieuwe houding pas 12–18 s na de wissel; 2–5 s doet dat 12–15 s eerder, bij dezelfde score (notebook 03). |
| Live marge ± 5° | Van rechtop naar liggend pas boven 50°, terug pas onder 40°. Zo springt de houding rond 45° niet heen en weer. Leunen over het aanrecht gaf 47–54° (notebook 03). |

Live wordt de activiteit elke 5 s opnieuw berekend over de laatste 20 s (`LIVE_STAP_S`). Dat getal van 5 s is
gekozen, niet onderzocht: AI-01 laat de stap nog open.

---

## 4. Kwaliteit (UC-2): goed, matig of onbruikbaar

### Voorbewerking

| Stap | Instelling |
|---|---|
| Resamplen | Naar 250 Hz (zie §1) |
| Filter voor slagen | Butterworth band 0,5–40 Hz, 3e orde, zonder faseverschuiving (`sosfiltfilt`) |
| Leads | I = Ecg1, II = Ecg2, III = II − I (Einthoven) |

### R-toppen: alleen op lead II

1. neurokit2 (`ecg_clean` en `ecg_peaks`, methode `neurokit`) zoekt de toppen op het gefilterde lead II.
2. Elke top schuift naar het maximum binnen ± 25 ms.
3. Toppen te dicht bij de rand vallen weg. Er moet 250 ms ervoor en 450 ms erna passen.
4. Dezelfde toppen gelden voor I en III.

Waarom alleen II:
- Per lead zoeken gaat mis als de T-golf groter is dan het QRS-complex. De test
  `test_toppen_uit_ii_bij_grote_t_golf_in_i` controleert dat.
- De uitslag van I is 1,5–5× kleiner dan die van II, en hangt ook nog af van de houding: bij D001 rechter zij
  0,23 mV, rug 0,67 mV, half liggend 0,86 mV. II heeft dat niet.

### Kenmerken per lead (I, II, III)

| Kenmerk | Berekening | Wat het vangt |
|---|---|---|
| `goed` | Knip elke slag van −250 tot +450 ms uit het gefilterde signaal en trek per slag het gemiddelde af. Neem de mediaan-slag. Bereken per slag de correlatie (Pearson) met die mediaan. `goed` = aandeel slagen met r ≥ 0,9. | Beweging en een (half) losse plakker |
| `drift_db` | 10·log₁₀( P(0–0,5 Hz) / P(5–15 Hz) ), met Welch op het ruwe signaal (venster 10 s, stappen van 0,1 Hz) | Een (half) losse plakker: de basislijn zakt weg, de QRS-energie verdwijnt |
| `ruis_db` | 10·log₁₀( P(40–120 Hz) / P(5–15 Hz) ) | Alleen ter uitleg, niet in de regels |
| `uitslag_mv` | Top-tot-top van de mediaan-slag | Alleen ter uitleg, niet in de regels |

Daarnaast per segment:

| Kenmerk | Berekening |
|---|---|
| `lead_off` | Is het lead-off-signaal (5 Hz) ergens in het segment > 0? |
| `rand` | Aandeel samples waarin \|I\| of \|II\| ≥ 350 mV |
| `slagen` | Aantal R-toppen |

Zonder R-toppen is `goed` = 0 en `uitslag_mv` leeg.

### Beslisregels

```text
1. lead_off of rand > 0                         → onbruikbaar, oorzaak "losse draad"
2. goed_min = min(goed_I, goed_II)
   geen slagen, of in I of II: drift_db > 15 dB
     én goed van die lead < 0,8                 → onbruikbaar
   anders goed_min ≥ 0,8                        → goed (klaar, geen oorzaak)
   anders goed_min ≥ 0,5                        → matig
   anders                                       → onbruikbaar
3. Oorzaak bij matig of onbruikbaar (uit UC-1):
   beweging of lopen  → "beweging"
   onbekend           → "onbekend"
   rust               → "mogelijk slecht elektrodecontact" + welke plakker (zie hieronder)
```

**Welke plakker?** In rust wordt een lead "slecht" genoemd als `goed` < 0,8 of `drift_db` > 15 dB. Een storing aan
één elektrode raakt precies de twee leads waar die elektrode in zit (Einthoven):

| Slechte leads | Plakker | Waarom |
|---|---|---|
| I + II | rood (RA) | RA zit in I (LA − RA) en II (LL − RA) |
| I + III | geel (LA) | LA zit in I en III (LL − LA) |
| II + III | groen (LL) | LL zit in II en III |
| een andere combinatie | onbekend | |

### Waarom zo

| Keuze | Reden |
|---|---|
| Lead-off en `rand` eerst (K1) | Bij een losse draad ziet het ECG er toch goed uit: 100% goede slagen, alleen op een grote offset (−379 tot −403 mV). Het label moet dus van lead-off komen, niet van de slagen. |
| Lead-off én ECG-kenmerken | Lead-off ziet "geen contact", niet "slecht contact". Uit de lead-off-test en notebook 01 v0.2 (zie tabel hieronder). |
| **`rand` 350 mV** | Een losse draad zet het signaal op −379 tot −403 mV; gewone offsets blijven onder ± 85 mV. De grens was eerst 380 mV, maar bij één losse draad stond II op −379,5 mV en viel er net onder. Het meetbereik van ± 400 mV is een aanname. |
| **Goede slag r ≥ 0,9** | AI-03. Het is een strenge grens: ook bij 20–40% goede slagen is de mediaan-slag nog herkenbaar. |
| Zwakste kanaal (K2) | UC-4 en UC-5 hebben I én II nodig (AI-09). Lead III telt niet mee voor het label, wel voor de plakker. |
| **Goed ≥ 0,8, matig ≥ 0,5** | Goed was eerst 0,9. Over alle 38 opnames gaf dat 23% "niet goed" in rust aan de lanyard, bijna altijd door lead I (`goed_I` 0,8–0,9). Met 0,8: 8,7% (lanyard) en 3,2% (sticker), en alle contactproeven blijven herkend (20-11). Bij `goed_min` onder 0,5 zit ≤ 1,3% van de rustsegmenten, tegen 35–40% van de bewegingssegmenten. |
| **Drift 15 dB, alleen met slechte slagen** | Een (half) losse plakker gaf +19 tot +47 dB; 95% van alle segmenten zit op ≤ +11 dB. 15 dB ligt ertussen. Drift telt sinds 20-11 alleen als de slagen in die lead ook slecht zijn: lead I is klein (± 0,55 mV), en kwam in rust met de sticker net boven 15 dB terwijl de slagen 0,93–1,00 goed waren. Een half losse plakker gaf in de proeven altijd drift én slechte slagen. |
| Oorzaak uit UC-1, label alleen uit ECG (K3) | "Beweging verklaart, maar veroordeelt niet." Ongeveer een kwart van de segmenten die UC-1 beweging noemt, heeft toch een goed ECG. |
| Geen hartfrequentie of neurokit2-kwaliteit (K4) | De hartfrequentie is altijd plausibel, ook bij een losse plakker. Van de 963 segmenten die neurokit2 (Zhao 2018) "Unacceptable" noemt, hebben er 591 ≥ 90% goede slagen. |
| Snoeren verwisseld niet per segment (K5) | Daarvoor is een referentie nodig: een blauwdruk (UC-4 en UC-5). In notebook 01 werden rood↔geel, geel↔groen en rood↔groen herkend (r 0,99–1,00), rood↔zwart niet. |

**Wat de lead-off-test en de plakkerproeven lieten zien** (D001, sticker, notebook 01):

| Situatie | Lead-off | ECG |
|---|---|---|
| Draad los (RA) | 100% | Signaal op −379 tot −385 mV, toch 100% goede slagen |
| Plakker helemaal los (RA, in rust) | 0 | 0–13% goede slagen, drift +39 dB |
| Plakker helemaal los tijdens lopen (LA) | 100% | I vlak op −403 mV |
| RA half los | 0 | Beide kanalen slechter: 53% / 62% goed, drift +40 / +32 dB |
| LA half los | 0 | Alleen I: 17% goed, drift +30 dB |
| LL half los | 0 | Nauwelijks effect (81% / 100%) |
| RL half los | 0 | Geen effect (RL is de referentie) |

---

## 5. Achteraf en live

| | Achteraf (Bekijken) | Live |
|---|---|---|
| Activiteit | per segment van 20 s | laatste 20 s, elke 5 s opnieuw |
| Houding | per segment van 20 s, grens 45° | laatste 5 s, elke 1 s opnieuw, marge ± 5° |
| Kwaliteit | per segment van 20 s; de kenmerken staan in een cache (`kwaliteit-v1.parquet` in de signalenmap) | laatste 20 s, elke 5 s opnieuw (`kwaliteit_nu`); lead-off telt als er in de laatste 20 s een melding was |
| Bevestiging | keuzelijst; standaard uit de elektrodeplaatsing van de opname: met "lanyard" in de tekst lanyard, anders sticker | idem |

Verandert `kenmerken_segment`, verhoog dan `VERSIE` in `kwaliteit.py`. Anders gebruikt de tool de oude cache.

---

## 6. Alle drempels op een rij

| Constante | Waarde | Waar | Status |
|---|---|---|---|
| `SEGMENT_S` | 20 s | beweging.py | richtwaarde AI-01 |
| `MIN_DEKKING` | 90% | beweging.py | keuze |
| `BEWEGING_G` | 0,029 g | beweging.py | lanyard: leave-one-out; sticker: voorlopig (B3) |
| `STAP_HZ` | 1,2–2,8 Hz | beweging.py | voorlopig (B5) |
| `STAP_AANDEEL` | 0,33 sticker, 0,41 lanyard | beweging.py | voorlopig; wp4 gebruikt nog 0,41 voor beide |
| `LIGGEND_GRADEN` | 45° | beweging.py | literatuur, één opname getoetst |
| `OMGEKEERD_GRADEN` | 135° | beweging.py | keuze |
| `MARGE_GRADEN` | 5° | beweging.py | keuze |
| `HOUDING_LIVE_S` / `HOUDING_STAP_S` | 5 s / 1 s | beweging.py | notebook 03 |
| `LIVE_STAP_S` | 5 s | beweging.py | keuze, AI-01 open |
| filter | 0,5–40 Hz, 3e orde | kwaliteit.py | keuze |
| slagvenster | −250 / +450 ms | kwaliteit.py | keuze |
| `goede_slag` | r ≥ 0,9 | kwaliteit.py | AI-03 |
| `goed` / `matig` | 0,8 / 0,5 | kwaliteit.py | proxy-labels 38 opnames (20-11) / startwaarde |
| `drift_db` | 15 dB, alleen met slechte slagen | kwaliteit.py | startwaarde, regel aangescherpt 20-11 |
| `rand_mv` | 350 mV | kwaliteit.py | keuze, meetbereik aangenomen |

---

## 7. Kanttekeningen

### Bij het lezen van de code

1. **Eén sample boven 350 mV maakt het hele segment onbruikbaar, met oorzaak "losse draad".** Een korte piek, zoals
   een tik op de recorder, eindigt dan ook als losse draad. Overweeg een minimale duur of een minimaal aandeel.
2. **Live houding bij leunen.** De marge zet de grens op 50°, maar leunen over het aanrecht gaf tot 54°. Dat wordt
   dus "liggend" zodra het langer dan een paar seconden duurt.
3. **Drift in I maakt het segment alleen onbruikbaar als de slagen in I ook slecht zijn** (sinds 20-11). Daarvoor
   gaf drift alleen al "onbruikbaar", wat in rust met de sticker 6,3% vals alarm gaf.
4. **`ruis_db`, `uitslag_mv` en `gyro_sd` worden berekend maar niet gebruikt** in de regels. Ze dienen alleen ter
   uitleg (AI-14).
5. **Tool en wp4 lopen uiteen** bij `STAP_AANDEEL` voor de sticker (0,33 tegen 0,41). Gelijktrekken zodra de drempel
   met leave-one-out getoetst is.
6. **`kwaliteit.py` verwijst naar notebook 01b.** Dat staat (nog) niet in `secu-sense-wp4` op `origin/main`.

### Open punten uit de wp4-notities

1. **Geen beoordelingen voor UC-2.** Alle grenzen zijn gekozen op proxy-labels (op 20-11 over alle 38 opnames
   getoetst). Notebook 02 (leave-one-out op beoordelingen) moet ze nog bevestigen of verschuiven.
2. **Zitten met de sticker gaf 56° kanteling** (D002, 07-10), waarschijnlijk door achterover te leunen. Met 45° wordt
   dat "liggend". Misschien moet "rechtop" een hoekbereik worden, met achterover zitten als aparte uitkomst.
3. **Lanyard in rust:** met goed ≥ 0,8 is nog 8,7% van de rustsegmenten niet goed (was 23% bij 0,9). Bij een
   melding (UC-3) een langere duur aanhouden.
4. **Plakkerproeven op één persoon**, 40–60 s per plakker. LL gaf nauwelijks effect: herhalen met LL verder los, en
   bij een tweede deelnemer.
5. **"Rechtop" ijken per opname** op de loopsegmenten (idee uit ecg-ai 06). Alleen doen als de vaste −x-as
   tekortschiet.

---

## 8. Zelf narekenen

```powershell
cd streamlit
..\.venv\Scripts\python -m pytest tests/test_beweging.py tests/test_kwaliteit.py -q
```

De tests gebruiken synthetische signalen: rust, liggen en lopen; de marge rond 45°; een losse draad; drift die een
plakker aanwijst; drift met goede slagen (blijft goed); een grote T-golf in I; knippen op tijdstempel; de live buffer.
Op 20-11-2026 slaagden ze alle 12.
