"""Uitleg die verschijnt bij het ?-icoontje (hover) naast titels, kopjes, knoppen en velden.

Teksten mogen Markdown bevatten. Aanpassen kan hier, zonder de pagina's zelf te hoeven openen.
"""

# --- overzicht ---

# --- deelnemers ---
DEELNEMERS = (
    "Gegevens per persoon. Elke deelnemer krijgt een ID (`D001`, `D002`, …). Zet dat ID in het **User Id**-veld "
    "van de P-Cardio, niet de naam: dat veld wordt niet versleuteld."
)
NAAM = "Voornaam of patiënt-ID: wat voor jullie het makkelijkst herkenbaar is."
LEEFTIJD = "In jaren. Leeg laten als het onbekend is."
GESLACHT = "Kies *onbekend* als het niet is opgegeven."
HARTDECOMPENSATIE = "Bekende hartdecompensatie (hartfalen) ja of nee."
ANDERE_AANDOENING = "Andere bekende ziekte of aandoening, in eigen woorden. Leeg = geen."
BEWERK_DEELNEMER = "Kies een deelnemer om de gegevens aan te passen. Het ID blijft hetzelfde."
VERWIJDER_DEELNEMER = (
    "Haalt de deelnemer uit `deelnemers.csv`. Dat kan alleen als er **geen opnames** van deze deelnemer zijn, zodat "
    "opnames en annotaties altijd bij een deelnemer horen. Het ID wordt daarna niet opnieuw uitgegeven."
)
ALLE_DEELNEMERS = "Alle vastgelegde deelnemers, uit `streamlit/data/deelnemers.csv`."

# --- live ---
LIVE = (
    "Log tijdens de opname wat de deelnemer doet. De tijdstempels komen van de klok van **deze pc**. Elke klik "
    "wordt direct opgeslagen."
)
LIVE_DEELNEMER = "Staat de deelnemer er niet bij? Voeg die eerst toe op de pagina **Deelnemers**."
ELEKTRODEN = (
    "Hoe de P-Cardio en de elektroden op de borst zitten, volgens de handleiding van de P-Cardio:\n\n"
    "- **Optie 1: met sticker**: de P-Cardio met een sticker midden op de borst.\n"
    "- **Optie 2: met lanyard**: de P-Cardio aan een koord om de nek.\n\n"
    "Klik op **📷 Foto's** voor de plaatjes van beide opties.\n\n"
    "**Waarom?** De plek bepaalt voor een groot deel hoe het signaal eruitziet. Als een opname veel ruiziger is "
    "dan een andere, kun je hiermee nagaan of dat aan de plaatsing lag."
)
HUIDVOORBEREIDING = (
    "Hoe de huid is voorbereid en wat er afweek van de gekozen optie. Bijvoorbeeld: *'Huid schoongemaakt met "
    "alcohol, niet geschoren. Groene elektrode iets lager geplakt.'* Een foto maken mag ook; noteer dan hier waar "
    "die staat."
)
CONFIGURATIE = (
    "De **instellingen van de P-Cardio** tijdens deze opname: welke sensoren aan staan, met welke **gain** "
    "(versterking) en **sample rate** (metingen per seconde). Het vakje is al ingevuld met de instellingen uit "
    "het opnameprotocol.\n\n"
    "Pas het alleen aan als je de P-Cardio **anders hebt ingesteld**, bijv. ECG op gain x4 omdat het signaal "
    "klipte. Zo weet je achteraf met welke instellingen deze data gemaakt is."
)
GELIJKGEZET = (
    "**Wat betekent dit?** Er zijn twee klokken: die van de **P-Cardio** (die zet een tijd bij elke meting) en "
    "die van **deze pc** (die zet een tijd bij elke klik in deze app). Om straks te weten welk stuk signaal bij "
    "'lopen' hoort, moeten die twee klokken gelijk lopen.\n\n"
    "**Wat moet je doen?** Zet vlak vóór de opname, terwijl de P-Cardio in de docking zit, de tijd van de "
    "P-Cardio gelijk aan de tijd van deze pc (het `Time`-register, sectie 3 van het opnameprotocol). "
    "Dat kan **niet** vanuit deze app en **niet** via `config.txt`, maar alleen via Bluetooth of de USB-verbinding, "
    "bijv. met de PCardio-software van 2M. Zie de **Handleiding** → *Begrippen* voor de details. "
    "Vink dit vakje aan als je dat gedaan hebt.\n\n"
    "**Vergeten?** Geen ramp: met de sync-sprong rekent de app het verschil later alsnog uit. Maar als de klokken "
    "minuten of uren verschillen, moet je de correctie handmatig opzoeken."
)
NOTITIES = "Bijzonderheden van deze opname, bijv. 'deelnemer had net gesport'."
EXPERIMENT = (
    "Bij welk experiment deze opname hoort, bijv. *Elektrodeplaatsing 21-10*. Geldt voor de hele opname en komt "
    "in elke regel van de export (kolom `experiment`). Optioneel. Geen namen: alleen deelnemer-ID's."
)
PLAATSING = (
    "De omstandigheid tijdens deze periode, bijv. de elektrodeplaatsing *R3-Y3-G1-Z1*. Wordt opgeslagen bij elke "
    "periode die je start en **blijft staan** tot je hem wijzigt: bij een volgende activiteit hoef je niets opnieuw "
    "te typen. Komt in de export (kolom `plaatsing`). Optioneel."
)
HERVATTEN = "Opnames die nog niet zijn afgesloten, bijv. na het per ongeluk sluiten van de browser."
KLOK = "Huidige tijd van deze pc. Deze tijd komt in de annotaties."
SYNC = (
    "Tel samen af; de deelnemer springt één keer en jij klikt **precies op het moment van landen**. De landing is "
    "een piek in de accelerometer, waarmee de app het verschil tussen de klokken uitrekent. Doe dit aan het begin "
    "en liefst ook aan het eind."
)
STOP_PERIODE = "Stopt de lopende periode, bijv. aan het begin van een rustpauze."
AFSLUITEN = "Stopt een lopende periode en sluit de live opname af. Aanpassen kan daarna nog in het logboek."
PERIODEN = (
    "Een **periode** heeft een begin en een eind (zitten, lopen, springen, …). Klik als de activiteit begint; een "
    "nieuwe periode stopt de vorige op hetzelfde moment. De knoppen komen uit `config/activiteiten.txt`."
)
ANDERE_ACTIVITEIT = "Een activiteit die niet in de lijst staat. Typ een omschrijving en klik op **Start periode**."
MOMENTEN = (
    "Een **moment** is één tijdstip zonder duur (hoest, elektrode los, …). Het tijdstip is het moment van klikken, "
    "dus klik meteen. De knoppen komen uit `config/momenten.txt`."
)
ANDER_MOMENT = "Een moment dat niet in de lijst staat. Let op: het tijdstip is het moment dat je op **Markeer** klikt."
LOGBOEK = (
    "Alles wat er gelogd is, nieuwste bovenaan. Je kunt **label**, **plaatsing** en **opmerking** direct in de "
    "tabel aanpassen. "
    "Fout geklikt? Vink *verwijder?* aan en klik op de knop eronder."
)
VERWIJDER_REGELS = "Verwijdert alle regels waarbij *verwijder?* is aangevinkt."

# --- koppelen ---
KOPPELEN = (
    "Na de opname: lees de P-Cardio-bestanden in, koppel ze aan de juiste opname en bepaal het klokverschil. "
    "Daarna kun je de opname bekijken."
)
INLEZEN = (
    "Ondersteund: CSV-exports (`Ecg_2Ch.csv`, `Acc.csv`, `Gyro.csv`, …) en het binaire `data_*.txt` van de "
    "P-Cardio, en een eerdere export van deze app (`…_volledig.csv`, `…_annotaties.csv`, los of in een `.zip`). "
    "De app herkent zelf wat elk bestand is. Kies alle bestanden van **één** opname tegelijk."
)
UPLOAD = "Uploaden is beperkt tot 200 MB per bestand. Gebruik voor grotere bestanden het tabblad ernaast."
PAD = (
    "Pad naar een bestand, of naar een map: dan worden alle `.csv`-, `.txt`- en `.zip`-bestanden erin gelezen "
    "(behalve `config.txt` en `log.txt`)."
)
KOPPEL_OPNAME = (
    "De app stelt de opname voor met hetzelfde ID als de bestandsnaam, of anders die waarvan de live annotaties "
    "in de tijd binnen de data vallen. Klopt dat niet, kies "
    "dan zelf. Kies **Nieuwe opname** als er niet live geannoteerd is; dan annoteer je achteraf."
)
KOPPEL = (
    "Kopieert de bestanden naar de opname (`ruw/`) en slaat de ingelezen signalen op. Bestaande data wordt vervangen. "
    "Een annotatiebestand vervangt alle annotaties van de opname en neemt de klokcorrectie over."
)
KLOKCORRECTIE = (
    "Het aantal seconden dat bij alle **live** gelogde tijden (pc-klok) wordt opgeteld, zodat ze op de tijd van de "
    "P-Cardio-data uitkomen. Nodig zodra er live geannoteerd is. Bepaal het met de sync-sprong (**Gebruik "
    "voorstel**) of vul het handmatig in. Zie het uitklapvak *Wat doet de klokcorrectie?* hieronder."
)
ZOEKVENSTER = (
    "Hoe ver rond het gelogde sync-moment de app naar de landingspiek zoekt. Vergroot dit als de klokken flink "
    "uiteenlopen."
)
GEBRUIK_VOORSTEL = "Gemiddelde van de duidelijk gevonden sync-sprongen. Controleer eerst in de plot of de rode lijn op de piek valt."
HANDMATIG = "Positief = de P-Cardio-klok loopt vóór op de pc. Wordt opgeteld bij alle live gelogde tijden."

# --- bekijken ---
BEKIJKEN = (
    "Bekijk de opname per periode, moment of vrij venster: de ECG-leads met de beweging eronder, op dezelfde "
    "tijdas. Hier kun je annotaties ook corrigeren, beoordelen en toevoegen."
)
WEERGAVE = "Wat er in de plot getoond wordt. Geldt voor alle opnames."
ECG_KANALEN = (
    "Welke ECG-kanalen in de plot staan. Standaard alleen **I (= Ecg1)**.\n\n"
    "De P-Cardio meet 2 kanalen (Ecg1 en Ecg2). Daaruit worden III, aVR, aVL en aVF berekend. **Aanname:** "
    "Ecg1 = afleiding I en Ecg2 = afleiding II."
)
FILTER = (
    "Een bandfilter van **0,5 tot 40 Hz** op de ECG, zoals klinische ECG-viewers die gebruiken: drift en offset "
    "(< 0,5 Hz) en ruis en netbrom (> 40 Hz) verdwijnen, zodat de hartslagen goed zichtbaar zijn.\n\n"
    "Het filter geldt **alleen voor de plot**. De opgeslagen data en de export blijven altijd ruw.\n\n"
    "Uit = het ruwe signaal zoals de hardware het meet. Kijk bij twijfel naar allebei: drift en ruis zijn zelf "
    "ook artefacten."
)
ACC = "Accelerometer X/Y/Z en de grootte |acc| (zwart). Laat zien wanneer en hoe hard er bewogen wordt."
GYRO = "Gyroscoop X/Y/Z en de grootte |gyro| (zwart). Laat draaibewegingen zien, zoals omdraaien of bukken."
OVERIG = (
    "Andere signalen uit de bestanden, zoals lead-off (elektrodecontact) en markers. De batterij wordt niet "
    "getoond (wel meegenomen in de export)."
)
MARGE = (
    "Geldt alleen als je bij *Segment* een **periode of moment** kiest (niet bij *Vrij venster*). De plot toont dan "
    "de annotatie plus dit aantal seconden ervóór en erna, zodat je de overgang ziet.\n\n"
    "Voorbeeld: een periode *Lopen* van 10:03:00 tot 10:04:00 met een marge van 5 s toont 10:02:55 tot 10:04:05. "
    "Bij een moment (één tijdstip) zie je dus 2 × de marge."
)
SEGMENT = (
    "Kies een periode of moment, of **Vrij venster** om zelf door de opname te bladeren. Met **Vorige** en "
    "**Volgende** loop je alle annotaties op volgorde door."
)
VORIGE_VOLGENDE = (
    "Naar de vorige of volgende annotatie (op tijdsvolgorde). Sneltoets: houd **Shift** ingedrukt en druk op ↑ of ↓."
)
TERUG_VERDER = (
    "Eén venster terug of verder in de opname. Sneltoets: houd **Shift** ingedrukt en druk op ← of →. "
    "Bekijk je een periode of moment, dan ga je verder in **Vrij venster**."
)
VENSTERLENGTE = (
    "Hoeveel seconden er in één keer getoond worden (standaard 10 s). Tot ruim 1 minuut bij 1000 Hz wordt het "
    "signaal volledig getoond; bij langere vensters wordt het uitgedund. Sleep in de plot om in te zoomen."
)
SCROLLBALK = (
    "Schuif om door de hele opname te bladeren, per seconde, in kloktijd; het venster houdt dezelfde lengte. "
    "Bekijk je een periode of moment, "
    "dan ga je met schuiven verder in **Vrij venster**."
)
SLEEPMODUS = (
    "Wat slepen in de plot doet:\n\n"
    "- **Zoomen**: sleep een kader om in te zoomen.\n"
    "- **Selecteren**: sleep over een stuk signaal om het te annoteren. Het begin en eind komen dan vanzelf in "
    "*Nieuwe annotatie in dit venster*.\n\n"
    "Tip: zoom eerst in, schakel dan naar **Selecteren** voor een precieze selectie."
)
RESET_ASSEN = (
    "Zet de zoom terug naar het hele venster en wist een selectie. Dubbelklikken in de plot zet ook de zoom terug. "
    "(Ctrl+R werkt hier niet: dat herlaadt de hele pagina in de browser.)"
)
LABEL_KNOPPEN = (
    "Klik op een label om de periode meteen toe te voegen. Staat het label er niet bij? Typ een eigen label en klik "
    "op **Toevoegen**. De knoppen komen uit `config/activiteiten.txt`."
)
OVERZICHT_PLOT = (
    "De hele opname: ECG-kanaal 1 en |acc|, met de annotaties als gekleurde vlakken. Het rode kader is het venster "
    "dat hieronder groot getoond wordt. **Sleep** over een stuk om er een periode van te maken (handig voor lange "
    "perioden zoals wandelen of zitten). **Klik** op een annotatie in de lijst eronder om hem hieronder te bekijken."
)
KLOKTIJD_INVOER = (
    "Kloktijd zoals op de x-as, bijv. 17:20:05 (seconden mag je weglaten). Sleep je in het overzicht, dan worden "
    "begin en eind vanzelf ingevuld en kun je ze hier bijstellen."
)
DETAIL_PLOT = (
    "Sleep met de muis om in te zoomen (of te selecteren, zie *Slepen in de plot*), dubbelklik of **Reset assen** "
    "om terug te gaan. Gekleurde vlakken = perioden, oranje lijnen = momenten, rode stippellijn = sync-sprong."
)
ANNOTATIE = "Pas de gekozen annotatie aan. Wijzigingen worden pas opgeslagen na **Opslaan**."
LABEL = "Wat de deelnemer deed. Kies **Anders…** om zelf een label te typen."
OPMERKING = "Vrije tekst, bijv. wat je in het signaal opviel."
VERSCHUIF_BEGIN = "Negatief = eerder. Handig als er te laat op de knop is gedrukt."
VERSCHUIF_EIND = "Negatief = eerder, positief = later."
BEOORDELING = (
    "Hoe het **signaal** eruitziet, los van wat de deelnemer deed:\n\n"
    "- **schoon**: QRS duidelijk, geen artefacten\n"
    "- **ruis, QRS herkenbaar**: verstoord maar nog te beoordelen\n"
    "- **onbruikbaar**: QRS niet meer te herkennen"
)
TOELICHTING = "Wat zie je precies? Bijv. 'baseline wander in kanaal 2', 'pieken bij elke stap'."
NIEUWE_ANNOTATIE = (
    "Voeg een annotatie toe binnen het getoonde venster, bijv. als er tijdens de opname iets niet gelogd is. "
    "Selecteer het stuk in de plot (*Slepen in de plot* → **Selecteren**), of vul begin en eind zelf in. Deze "
    "annotaties liggen in P-Cardio-tijd en verschuiven niet mee met de klokcorrectie."
)
SOORT = "**Periode** = begin en eind (activiteit). **Moment** = één tijdstip."
BEGIN_IN_VENSTER = "Seconden vanaf het begin van het venster. Lees de tijd af door in de plot te zoomen."
ALLE_ANNOTATIES = (
    "Alle annotaties van deze opname, met de tijden omgerekend naar P-Cardio-tijd. **tijdbasis** *pc* = live "
    "gelogd, *data* = achteraf toegevoegd."
)

# --- export ---
EXPORT = (
    "Eén CSV met een rij per ECG-sample: Ecg1/Ecg2, de afgeleide leads, beweging, overige kanalen en de kolommen "
    "`activiteit` en `moment` uit de annotaties."
)
BEREIK = "De hele opname, of alleen één periode (eventueel met een marge eromheen)."
MARGE_EXPORT = "Extra seconden vóór en na de periode."
ZES_LEADS_EXPORT = "Voegt de berekende leads III, aVR, aVL en aVF toe (aanname: Ecg1 = I, Ecg2 = II)."
MAAK_EXPORT = "Schrijft de CSV naar de map `export/` van de opname. Een hele opname kan >100 MB zijn."
DOWNLOAD_ANNOTATIES = "Alleen de annotaties, met de tijden zowel zoals gelogd als in P-Cardio-tijd."

# --- gedeelde uitleg (uitklapvakken en handleiding) ---
KLOK_GELIJKZETTEN_UITLEG = """
**Kan de klok van de P-Cardio gelijkgezet worden met de pc?** Ja, maar **niet vanuit deze app** en **niet via
`config.txt`**.

- De klok van de P-Cardio is het **`Time`-register**: de tijd in hele seconden (Unix-tijd, adres 132;
  interface-handleiding §5.2.2).
- Dat register is beveiligd. Eerst moet het **pin-register** (adres 128) geschreven worden, daarna de tijd.
- Schrijven kan alleen via **Bluetooth** of via de **USB-verbinding** terwijl de P-Cardio in de docking zit, bijv.
  met de PCardio-software van 2M. Die zet de klok op Nederlandse kloktijd; de app houdt daar rekening mee.
- `config.txt` bevat de tijd **niet** (§8.1). Bestanden op de P-Cardio aanpassen helpt dus niet.
- De handleiding raadt aan de tijd bij te werken als het verschil **groter is dan 1 seconde** (§10.4).

Ook na het gelijkzetten blijft er een klein verschil: het gaat per hele seconde, en klokken lopen tijdens een
opname uit elkaar. Daarom blijft de **sync-sprong** nodig.
"""

KLOKCORRECTIE_UITLEG = """
**Wat doet het?** De annotaties die je **live** maakt, krijgen de tijd van de **pc**. De data krijgt de tijd van
de **P-Cardio**. De klokcorrectie is het aantal seconden dat bij alle live gelogde tijden wordt opgeteld, zodat
ze op de juiste plek in de data vallen.

- **Positief** = de P-Cardio-klok loopt **vóór** op de pc. **Negatief** = de P-Cardio-klok loopt achter.
- Annotaties die je **achteraf** in de plot maakt, liggen al in P-Cardio-tijd en schuiven **niet** mee.
- Zolang er geen correctie is, gebruikt de app **0 s**.

**Wanneer heb je het nodig?** Bij **elke opname met live annotaties**.

- **Momenten** (een hoest duurt minder dan een seconde) vallen al naast de verstoring bij een verschil van een
  seconde. Perioden van een minuut zijn minder gevoelig.
- Zijn de klokken **niet gelijkgezet**, of verschillen ze minuten of uren (bijv. zomertijd)? Dan valt zonder
  correctie alles naast de data, en stelt de app bij het koppelen vaak ook geen opname voor.

**Hoe gebruik je het?**

1. Doe tijdens de live opname een **sync-sprong** aan het begin en aan het eind.
2. Kies op **Data koppelen** bij stap 3 de opname. Per sync-sprong zie je een plot: de **grijze stippellijn** is
   het moment dat je klikte, de **rode lijn** de landingspiek die de app vond.
3. Valt de rode lijn op de landingspiek? Klik dan **Gebruik voorstel** (het gemiddelde van de duidelijke
   sprongen).
4. Geen sync-sprong of geen duidelijke piek? Vul de correctie **handmatig** in: 0 s als de klokken gelijkgezet
   waren, of het verschil tussen een duidelijke beweging in de data en het gelogde moment.
5. Controleer het op **Bekijken & annoteren**: valt de oranje lijn van een hoest samen met een verstoring?

Je kunt de correctie later altijd nog aanpassen; de live annotaties schuiven dan mee.

**Klokdrift:** het verschil tussen de eerste en de laatste sync-sprong laat zien hoeveel de klokken tijdens de
opname uit elkaar liepen (plus je reactietijd). De app gebruikt **één vaste correctie** voor de hele opname, dus
bij een groot verschil kloppen de tijden aan het begin of eind iets minder goed.
"""

# --- live ECG ---
LIVE_ECG = (
    "Live het ECG van de P-Cardio bekijken via de 2M BLE-dongle (USB). Alleen kijken: er wordt niets opgeslagen. "
    "De recorder blijft gewoon zelf loggen als dat aan staat. Sluit eerst de PCardio-app: de dongle kan maar met "
    "één programma tegelijk praten."
)
LIVE_MODUS = (
    "**Gesimuleerd**: een nep-dongle met een synthetisch ECG, om de pagina te proberen zonder hardware. "
    "**Echte dongle**: de 2M BLE-dongle in een USB-poort van deze pc."
)
LIVE_POORT = "De COM-poort van de dongle. Wordt herkend aan de USB-id van de dongle; staat er '(dongle)' achter, dan is het die."
LIVE_MAC = (
    "Optioneel: alleen verbinden met déze recorder (MAC-adres, het eerste deel van de QR-code op de achterkant). "
    "Leeg = de eerste P-Cardio die gevonden wordt."
)
LIVE_MAC_OMGEKEERD = (
    "De handleiding zegt niet in welke volgorde de bytes van het MAC-adres verstuurd moeten worden. Vindt de dongle "
    "de recorder niet met een MAC-adres, zet dit dan aan."
)
LIVE_VERBINDEN = (
    "Zoekt de recorder (max. 30 s), leest de gegevens en de meetconfiguratie. Wordt hij niet gevonden: druk kort op "
    "de knop van de P-Cardio, dan gaat hij adverteren."
)
LIVE_START = "Start de live datastroom. Tijdens het streamen kan de app de recorder niet uitlezen."
LIVE_ONTKOPPELEN = "Stopt de datastroom, verbreekt de verbinding met de recorder en geeft de COM-poort vrij."
LIVE_VENSTER = "Hoeveel seconden er in beeld zijn."
LIVE_YSCHAAL = "**Auto** past de schaal aan het signaal aan. **Vast** houdt de schaal stil: makkelijker om te vergelijken."
LIVE_FILTER = "Bandfilter 0,5–40 Hz tegen drift en ruis. Alleen voor de weergave."
LIVE_NETBROM = "Haalt 50 Hz-brom van het lichtnet weg. Alleen voor de weergave."
LIVE_CONFIG = (
    "De recorder meet nu geen ECG. Hiermee schrijf je de standaardconfiguratie uit het opnameprotocol naar de "
    "recorder. **Let op:** de recorder gebruikt die daarna ook als hij zelf logt. Kan alleen als hij niet aan het "
    "loggen is."
)
LIVE_TELLERS = (
    "**Pakketten**: goed ontvangen (5 per seconde). **CRC-fout**: beschadigd, niet getoond. **Onvolledig**: een "
    "stuk van een pakket kwam niet aan. **Tijdgaten**: de tijd tussen twee pakketten was niet 0,2 s (pakket gemist)."
)
LIVE_LOGT = (
    "Of de recorder zelf het ECG opslaat, gelezen bij het verbinden. Gestart of gestopt met de knop daarna? Dan klopt "
    "dit pas weer na Opnieuw verbinden. Op de recorder zelf: knop 1-3 s indrukken, groen = neemt op, oranje = niet."
)
LIVE_LOG = "De laatste regels die tussen de app en de dongle over de seriële poort gingen. Handig bij problemen."
LIVE_AUTO = (
    "Valt de verbinding weg (bijvoorbeeld als je even wegloopt van de laptop), dan probeert de app het vanzelf steeds "
    "opnieuw, en start het ECG weer als dat liep. Ook als de recorder 10 s niets meer stuurt, geldt de verbinding als "
    "verbroken. Uit: dan verbind je zelf opnieuw met de knop."
)
LIVE_OPNIEUW = (
    "Verbindt opnieuw met dezelfde recorder en start het ECG weer als dat liep. Lukt het niet: breng de laptop dichter "
    "bij de recorder, of druk kort op de knop van de P-Cardio (hij adverteert maar beperkte tijd na het wegvallen)."
)
