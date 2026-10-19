# pcardio-ecg-tool

Streamlit-app van AppBakkers voor P-Cardio-opnames: deelnemers vastleggen, live annoteren, live ECG via de
dongle, P-Cardio-data koppelen, bekijken & annoteren en exporteren. Uitleg over de app en de code staat in
[streamlit/README.md](streamlit/README.md).

## Installeren (eenmalig, Windows)

Vereist **Python 3.12.x** (met de Python Launcher `py`). Dubbelklik `init_repo.cmd` of voer het uit in cmd. Het
script maakt `.venv` aan met Python 3.12 en installeert `requirements.txt`.

## Starten

Altijd vanuit de projectroot, anders wordt `.streamlit/config.toml` niet geladen:

```powershell
.venv\Scripts\Activate.ps1
streamlit run streamlit\app.py
```

Krijg je `UnauthorizedAccess` bij het activeren? Voer eenmalig uit:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

## Mappen

| Map | Inhoud |
|---|---|
| `streamlit/` | de app: pagina's, `kern/` (logica zonder Streamlit), tests |
| `scripts/probe_device.py` | losse hardwaretest van dongle en recorder, buiten de app om |
| `docs/` | [opnameprotocol](docs/opnameprotocol-p-cardio.md) en handleidingen van de P-Cardio |

`streamlit/data/` bevat deelnemers- en opnamegegevens en staat in `.gitignore`. Uitzondering: de oefendata
in `streamlit/data/test/` gaat wel mee, zodat je meteen een oefenopname kunt maken.
