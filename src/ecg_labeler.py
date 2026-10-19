import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import shutil

# Stel de pagina-configuratie in om de lay-out aan te passen
st.set_page_config(layout="wide")

# Bepaal de directory van het huidige script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Stel het pad in naar de directory met de data
directory_path = os.path.join(script_dir, '../data/appbakkers/Corne/')
test_directory_path = os.path.join(script_dir, '../data/appbakkers/test/')
goed_directory_path = os.path.join(test_directory_path, 'goed/')
fout_directory_path = os.path.join(test_directory_path, 'fout/')


# Controleer of het pad correct is
if not os.path.exists(directory_path):
    st.error(f'Directory does not exist: {directory_path}')
else:
    st.write(f'Using directory: {directory_path}')

# Controleer of de subdirectories bestaan, zo niet maak deze aan
if not os.path.exists(goed_directory_path):
    os.makedirs(goed_directory_path)
if not os.path.exists(fout_directory_path):
    os.makedirs(fout_directory_path)

# Function to normalize data
def normalize(series):
    return (series - series.min()) / (series.max() - series.min())

# Read the filenames CSV file
filenames_csv_path = os.path.join(directory_path, 'filenames_corne.csv')
filenames_df = pd.read_csv(filenames_csv_path)

# Haal de huidige index op of stel deze in op 0
if 'file_idx' not in st.session_state:
    st.session_state.file_idx = 0

# Functie om bestand te kopiëren en index te verhogen
def copy_file(label):
    filename = filenames_df['filename'].iloc[st.session_state.file_idx]
    file_path = os.path.join(directory_path, filename)
    
    if label == 'Goed':
        destination_directory = goed_directory_path
    else:
        destination_directory = fout_directory_path

    destination_file_path = os.path.join(destination_directory, filename)
    shutil.copyfile(file_path, destination_file_path)
    st.write(f'File copied to {destination_file_path}')
    
    # Verhoog de index
    st.session_state.file_idx += 1
    if st.session_state.file_idx >= len(filenames_df):
        st.session_state.file_idx = 0  # Ga terug naar de eerste file als we aan het einde zijn

# Haal de bestandsnaam op voor de geselecteerde index
filename = filenames_df['filename'].iloc[st.session_state.file_idx]
file_path = os.path.join(directory_path, filename)

# Lees het geselecteerde ECG-bestand
df = pd.read_csv(file_path)

# Maak een datetime-kolom aan indien niet al aanwezig
if 'datetime' not in df.columns:
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'])

# Stel de datetime-kolom in als de index
df.set_index('datetime', inplace=True)

# Normaliseer de 'value'-kolom
df['value'] = normalize(df['value'])

# Slider voor het aanpassen van de plotgrootte
width = st.slider('Select plot width', min_value=5, max_value=20, value=10)
height = st.slider('Select plot height', min_value=3, max_value=10, value=4)

# Gebruik kolommen om de layout te manipuleren
col1, col2, col3 = st.columns([1, 8, 1])  # Geeft de middelste kolom meer ruimte

with col2:
    # Plot de data
    fig, ax = plt.subplots(figsize=(width, height))
    ax.plot(df.index, df['value'], label='ECG Value')
    ax.set_title(f'ECG Data from {filename}')
    ax.set_xlabel('Time')
    ax.set_ylabel('Normalized Value')
    ax.legend()
    ax.grid(True)

    # Toon de plot in Streamlit
    st.pyplot(fig)

# Voeg CSS toe om de knoppen groter te maken
st.markdown("""
    <style>
    .stButton button {
        width: 250px;
        height: 50px;
        font-size: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# Plaats de knoppen naast elkaar
col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 2, 2])

with col3:
    if st.button('Slecht'):
        st.write(f'{filename} labeled as Slecht')
        copy_file('Slecht')
        st.rerun()

with col4:
    if st.button('Goed'):
        st.write(f'{filename} labeled as Goed')
        copy_file('Goed')
        st.rerun()