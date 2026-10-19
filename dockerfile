# Gebruik een officiële Python image als basis
FROM python:3.9.6-slim

# Stel de werkdirectory in de container in
WORKDIR /app

# Kopieer requirements.txt naar de werkdirectory
COPY requirements.txt /app/requirements.txt

# Installeer de vereiste Python-pakketten
RUN pip install --no-cache-dir -r /app/requirements.txt

# Kopieer de rest van de applicatie naar de werkdirectory
COPY . /app

# Kopieer de Streamlit config
COPY .streamlit/config.toml /app/.streamlit/config.toml

# Ga naar de src directory waar je ecg_labeler.py zich bevindt
WORKDIR /app/src

# Stel het commando in om de applicatie uit te voeren
CMD ["streamlit", "run", "ecg_labeler_V2.py", "--server.port=8501", "--server.address=0.0.0.0"]