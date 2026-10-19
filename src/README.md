# ECG-labeler (`ecg_labeler_V2.py`)

Streamlit-dashboard om ECG-fragmenten van 10 seconden handmatig als **Goed** of **Fout** te labelen.
Gemaakt in juli/augustus 2024 voor de eerste eigen opnames (3 personen, 256 Hz, één kanaal).

> **Let op:** de tool **haalt gelabelde fragmenten uit het bronbestand** (het bronbestand werkt als wachtrij).
> Stop er dus **nooit** je enige kopie van de ruwe data in — werk altijd op een kopie.

> **Niet geschikt voor P-Cardio-bestanden:** de tool verwacht één ECG-kanaal in het oude formaat (zie hieronder)
> en vaste fragmenten van 2560 samples (= 10 s bij 256 Hz). P-Cardio-data (meerdere kanalen, ±250 Hz) moet je
> eerst omzetten, of je bekijkt die data liever in een notebook.

---

## Wat de tool doet

1. Leest alle `.txt`-bestanden uit `data/appbakkers/classificatie/`.
2. Hakt elk bestand in fragmenten van 2560 samples. Een restje korter dan 2560 samples wordt overgeslagen.
3. Toont één fragment tegelijk als plot, met de knoppen **Goed** en **Fout**.
4. Na een klik:
   - wordt het fragment toegevoegd aan `data/appbakkers/saved_chunks/goede_ecgs.txt` of `foute_ecgs.txt`;
   - worden de eerste 2560 regels uit het bronbestand verwijderd.

Fragmenten worden op volgorde getoond; er is geen terug- of overslaan-knop. Bij het **laatste** fragment
schuift de app niet verder, dus een tweede klik slaat hetzelfde fragment nog een keer op. Klik daar maar één
keer.

## Invoerformaat

Platte tekst, **tab-gescheiden, geen header**, drie kolommen per regel:

```
<datum>	<tijd>	<waarde>
```

Regels met een ander aantal kolommen worden genegeerd. De bestandsnaam (zonder `.txt`) wordt als naam getoond
in de legenda van de plot.

## Opstarten (lokaal, aanbevolen)

Vanuit de projectroot, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install streamlit pandas numpy matplotlib
```

Alleen deze vier pakketten zijn nodig. De volledige `requirements.txt` werkt ook, maar die installeert ook
TensorFlow e.d.

Zet je data klaar en start de app:

```powershell
mkdir data\appbakkers\classificatie      # eenmalig
# kopieer je .txt-bestanden hierheen (kopie, niet de originelen!)
streamlit run src\ecg_labeler_V2.py
```

De browser opent automatisch op <http://localhost:8501>. De paden in het script zijn relatief aan het script
zelf, dus het maakt niet uit vanuit welke map je `streamlit run` aanroept.

Stoppen: `Ctrl+C` in de terminal.

## Opstarten met Docker (niet recent getest)

De `dockerfile` in de projectroot start dezelfde app:

```powershell
docker build -t ecg-labeler .
docker run -p 8501:8501 -v "${PWD}\data:/app/data" ecg-labeler
```

Open daarna <http://localhost:8501>.

- **Gebruik `-v` (volume)**, anders zit de data in de container en ben je je labels kwijt zodra die stopt.
- De image is gebaseerd op Python 3.9.6 en installeert de volledige `requirements.txt` (incl. TensorFlow). Dat
  maakt hem groot, en het is niet gecontroleerd of alle huidige versies nog op Python 3.9 installeren. Lukt de
  build niet, gebruik dan de lokale variant hierboven.

## Privacy

`data/appbakkers/` staat **niet** in `.gitignore`, en `.txt`-bestanden ook niet. ECG-bestanden die je hier
neerzet, kunnen dus per ongeluk gecommit worden. Controleer `git status` voor je commit, of voeg
`data/appbakkers/` toe aan `.gitignore`.

## Oudere versie

`ecg_labeler.py` is de eerste versie van dezelfde tool (juli 2024). Gebruik `ecg_labeler_V2.py`.
