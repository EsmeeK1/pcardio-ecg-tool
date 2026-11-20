# 2026-11-20 · UC-2 live en afronden met data

## 1. Live signaalkwaliteit (UC-2 in Live)

- **Nieuw:** badge **KWALITEIT · LAATSTE 20 S** naast houding en activiteit in Live
  ([desktop/live.py](../../desktop/live.py), `_toon_kwaliteit`).
- Rekent elke 5 s opnieuw over de ECG-ringbuffer van 20 s (`kwaliteit_nu` in
  [kern/kwaliteit.py](../../streamlit/kern/kwaliteit.py)). Gebruikt dezelfde kenmerken en regels als Bekijken.
  De oorzaak komt uit de live activiteit.
- Lead-off in de laatste 20 s: `LiveSessie.lead_off_tijd`, de laatste pakkettijd met lead-off
  ([kern/live_sessie.py](../../streamlit/kern/live_sessie.py)).
- Detail op de badge: het aandeel goede slagen (bij goed), of de oorzaak: `losse draad`, `beweging`,
  `contact rood/geel/groen` of `contact?`.
- **Nog niet:** een melding voor de patiënt na een aanhoudend probleem (UC-3). Zie de beslissing van 10-11: "nog
  niet aan werken".

## 2. UC-2 doorgerekend over alle opnames

**Data.** Er waren 38 opnames met Ecg1, Ecg2 en acc (D001 en D002), samen 4.852 segmenten. Daarvan vallen er 1.747
helemaal binnen een gelabelde periode (het proxy-label).
- `ecg.db` is gekopieerd naar `streamlit/data/_analyse_uc2/`, in `.gitignore`. Vooraf is de sha256 gecontroleerd tegen
  `ecg-slot.json` (`7701765380…`, slot vrij sinds 19-11 17:06).
- De opnames zijn alleen gelezen. In OneDrive is geen cache geschreven.
- De uitkomst per segment staat in `streamlit/data/_analyse_uc2/segmenten.parquet`.

**Bevinding: de meeste valse alarmen in rust komen door lead I.**

| Rust (UC-1 rust, rustlabels) | Niet goed | Waarvan onbruikbaar |
|---|---|---|
| sticker (190 segmenten) | 10,0% | 6,3% |
| lanyard (1.090 segmenten) | 23,1% | 1,3% |

- In 366 van de 398 afwijkende rustsegmenten was lead I de zwakste lead.
- **Sticker, onbruikbaar in rust:** meestal `drift_db_I` net boven 15 dB (15,3–18), terwijl de slagen van lead I
  0,93–1,00 goed waren. Lead I is klein (± 0,55 mV tegen ± 2,6 mV in II), dus daar weegt drift relatief zwaar.
- **Lanyard, matig in rust:** `goed_I` tussen 0,8 en 0,9 (mediaan bij Staan 0,92).

**Varianten getoetst op de proxy-labels:**

| Variant | Rust sticker niet goed | Rust lanyard niet goed | Contactproeven herkend | Beweging niet goed |
|---|---|---|---|---|
| V0 huidig (goed 0,9, drift 15 dB) | 10,0% | 23,1% | 16/16 | 72,5% |
| V1 drift-grens 20 dB | 7,4% | 22,7% | 16/16 | 72,5% |
| V2 drift telt alleen met slechte slagen | 7,4% | 22,6% | 16/16 | 72,5% |
| V3 goed-grens 0,8 | 7,4% | 9,4% | 16/16 | 60,9% |
| **V4 = V2 + V3** | **3,2%** | **8,7%** | **16/16** | **60,9%** |

Over "contactproeven" en "beweging":
- **Contactproeven** zijn Plakker half los (RA, LA, LL), Lopen met plakker half los (LA), Draad los en de lead-off-tests.
- **Beweging** zijn Lopen, Traplopen, Armen bewegen, Verzitten, Springen en Staan (bezig). Dat beweging vaker goed
  wordt, is geen fout. "Beweging verklaart, maar veroordeelt niet": ± een kwart van de bewegingssegmenten heeft een
  goed ECG.

## 3. Beslissing: V4 doorgevoerd

[kern/kwaliteit.py](../../streamlit/kern/kwaliteit.py), `DREMPELS` en `classificeer`:

1. `goed`: 0,9 → **0,8** (aandeel goede slagen in de zwakste van I en II). De drempel per slag blijft r ≥ 0,9 (AI-03).
2. Drift boven 15 dB maakt een segment alleen onbruikbaar als **de slagen in die lead ook slecht zijn**
   (`goed` < 0,8). Drift met goede slagen is goed bruikbaar; het filter haalt de drift voor de slagen weg.

**Effect op alle 4.852 segmenten:**
- 311 gaan van matig naar goed, 72 van onbruikbaar naar goed en 1 van onbruikbaar naar matig.
- Geen enkel segment wordt slechter.
- Alle 17 contactproeven houden hetzelfde label en dezelfde plakker (rood, geel; LL blijft matig/onbekend).

**Waarom het verdedigbaar is:**
- Een half losse plakker gaf in de proeven altijd drift én slechte slagen (RA: 0,17–0,56; LA: 0,15).
- Een ECG met goede slagen is bruikbaar, ook met een schuivende basislijn. Het label blijft "alleen uit het ECG".

**Tests:**
- `test_drift_met_goede_slagen_is_goed` is nieuw.
- De synthetische LL-storing is nu drift + ruis, net als een echte half losse plakker.
- Alles slaagt: 121 geslaagd, 1 overgeslagen.

Geen cache-wissel nodig: de kenmerken zijn niet veranderd, alleen de regels (die draaien elke keer opnieuw).

## 4. Nog open voor UC-2

1. **Plakker groen (LL) wordt nog niet herkend.** Er is maar 1 segment, en daarin was alleen I slecht. Neem de proef
   opnieuw op met LL echt half los, ± 2 min per plakker, bij D001 én D002.
2. **Lanyard in rust: nog 8,7% niet goed.** Dat zijn vooral lead-I-segmenten. Bij UC-3 (melden) een langere duur
   aanhouden voordat er een melding komt.
3. **Alles is getoetst op proxy-labels van 2 deelnemers.** Er zijn geen handmatige beoordelingen. De grenzen kunnen
   nog verschuiven bij meer deelnemers.
4. **`rand`:** in deze data komt `rand` > 0 niet voor in rust. Kanttekening 1 in
   [activiteit-houding-kwaliteit.md](../activiteit-houding-kwaliteit.md) (één piek maakt het segment onbruikbaar) blijft
   theoretisch.

## Zelf opnieuw draaien

Vanuit de projectroot, met de ECG-tool gesloten (slot vrij) en `ecg.db` gekopieerd naar `streamlit/data/_analyse_uc2/`:

```powershell
.venv\Scripts\python scripts\uc2_alle.py        # alle opnames doorrekenen → segmenten.parquet
.venv\Scripts\python scripts\uc2_varianten.py   # varianten van de regels op de proxy-labels
```

`uc2_varianten.py` rekent met eigen regels, los van de code: na een wijziging van `classificeer` V0 daarop gelijkzetten.
Snel per opname kan ook met de knop **Overeenstemming…** in Bekijken.
