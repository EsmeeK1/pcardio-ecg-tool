import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import shutil
import math
import streamlit as st

# Stel de pagina-configuratie in om de lay-out aan te passen
st.set_page_config(layout="wide")


# Define ECGDataLoader class (in case it's not imported from a module)
class ECGDataLoader:
    def __init__(self, directory):
        self.directory = directory
        self.ecg_counter = 1

    def load_files_to_dataframe(self):
        all_data = []
        loaded_files = []  # Voeg een lijst toe om de ingeladen bestanden op te slaan
        ecg_counts = {}  # Dictionary om aantal ECG's per bestand op te slaan

        for filename in os.listdir(self.directory):
            if filename.endswith('.txt'):
                file_path = os.path.join(self.directory, filename)
                
                # Tel het aantal regels in het bestand
                with open(file_path, 'r') as file:
                    line_count = sum(1 for line in file)
                
                # Bereken het aantal ECG's in het bestand
                num_ecgs = line_count // 2560  # Aantal ECG's (afgerond naar beneden als er niet precies een veelvoud van 2560 is)
                ecg_counts[filename] = num_ecgs  # Sla het aantal ECG's op voor dit bestand

                loaded_files.append(filename)  # Voeg de bestandsnaam toe aan de lijst
                label = os.path.splitext(filename)[0]
                ecg_id = f"ECG_{self.ecg_counter}"
                self.ecg_counter += 1
                file_data = self._process_file(file_path)
                file_data['label'] = label
                file_data['ecg_id'] = ecg_id
                file_data['source_file'] = file_path  # Sla het pad van het bronbestand op
                all_data.append(file_data)
        
        # Toon de lijst van ingeladen bestanden en het aantal ECG's in elk bestand in Streamlit
        st.write("Ingeladen bestanden en aantal ECG's per bestand:")
        for file, count in ecg_counts.items():
            st.write(f"Bestand: {file}, Aantal ECG's: {count}")
        
        df = pd.concat(all_data, ignore_index=True)
        return df

    def _process_file(self, path):
        with open(path, 'r') as file:
            lines = file.read().splitlines()
        data = []
        for line in lines:
            columns = line.split('\t')
            if len(columns) == 3:
                date = columns[0]
                time = columns[1]
                value = columns[2]
                datetime = f"{date} {time}"
                data.append({
                    'datetime': datetime,
                    'date': date,
                    'time': time,
                    'value': value
                })
        return pd.DataFrame(data)


# Stel het pad in naar de directory met de data
script_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.dirname(script_dir)  # Ga een niveau omhoog naar de root van het project
directory_path = os.path.join(base_dir, 'data/appbakkers/classificatie/')
save_directory_path = os.path.join(base_dir, 'data/appbakkers/saved_chunks/')

if not os.path.exists(save_directory_path):
    try:
        os.makedirs(save_directory_path)
        st.write(f"Created save directory: {save_directory_path}")
    except Exception as e:
        st.write(f"Failed to create save directory: {e}")

# Laad de ECG-gegevens en chunk ze als ze nog niet zijn ingeladen
if 'ecg_data' not in st.session_state:
    loader = ECGDataLoader(directory_path)
    df = loader.load_files_to_dataframe()

    chunk_size = 2560  # Afhankelijk van je sample rate
    total_chunks = math.ceil(len(df) / chunk_size)

    X = []
    y = []
    file_sources = []

    for i in range(total_chunks):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        chunk_df = df.iloc[start_idx:end_idx].copy()
        unique_ecg_ids = chunk_df['ecg_id'].unique()

        if len(unique_ecg_ids) == 1:
            current_ecg_id = unique_ecg_ids[0]
            chunk_values = chunk_df[['date', 'time', 'value']].values
            if len(chunk_values) == chunk_size:
                X.append(chunk_values)
                y.append(chunk_df['label'].iloc[0])
                file_sources.append(chunk_df['source_file'].iloc[0])
            else:
                st.write(f"Skipping chunk {i+1} because it does not have {chunk_size} data points.")
        else:
            st.write(f"Skipping chunk {i+1} due to multiple ECG IDs: {unique_ecg_ids}")

    st.session_state.ecg_data = X
    st.session_state.labels = y
    st.session_state.current_chunk = 0
    st.session_state.file_sources = file_sources
else:
    X = st.session_state.ecg_data
    y = st.session_state.labels
    file_sources = st.session_state.file_sources

# Functie om een chunk op te slaan in een txt-bestand en de originele data bij te werken
def save_chunk_to_txt(chunk_data, label, source_file):
    if label == 'Goed':
        file_path = os.path.join(save_directory_path, 'goede_ecgs.txt')
    elif label == 'Fout':
        file_path = os.path.join(save_directory_path, 'foute_ecgs.txt')
    else:
        return
    
    # Opslaan van de chunk data in het juiste txt-bestand
    with open(file_path, 'a') as f:
        for row in chunk_data:
            f.write(f"{row[0]}\t{row[1]}\t{row[2]}\n")
    st.write(f"Chunk succesvol opgeslagen in {file_path}")

    # Verwijder de chunk uit het originele bestand
    remaining_data = pd.read_csv(source_file, sep='\t', header=None, names=['date', 'time', 'value'])
    processed_chunk = pd.DataFrame(chunk_data, columns=['date', 'time', 'value'])
    remaining_data = remaining_data.iloc[len(processed_chunk):]  # Verwijder de verwerkte chunk

    # Sla de resterende data op in het originele bestand
    remaining_data.to_csv(source_file, sep='\t', header=False, index=False)
    st.write(f"Originele bestand bijgewerkt: {source_file}")

# Toon de huidige chunk
chunk_to_plot = st.session_state.current_chunk

if chunk_to_plot < len(X):
    chunk_data = X[chunk_to_plot]
    source_file = file_sources[chunk_to_plot]

    # Converteer de waarde kolom naar een float voor plotting
    plot_values = chunk_data[:, 2].astype(float)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(plot_values, label=f'Chunk {chunk_to_plot + 1} (Label: {y[chunk_to_plot]})')
    ax.set_title('ECG Chunk Data')
    ax.set_xlabel('Sample Index')
    ax.set_ylabel('Value')
    ax.legend()
    ax.grid(True)

    st.pyplot(fig)
else:
    st.write("Geen meer ECG data om te tonen.")

# Plaats de knoppen naast elkaar
col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 2, 2])

with col3:
    if st.button('Fout'):
        save_chunk_to_txt(chunk_data, 'Fout', source_file)
        if st.session_state.current_chunk < len(X) - 1:
            st.session_state.current_chunk += 1
        st.rerun()

with col4:
    if st.button('Goed'):
        save_chunk_to_txt(chunk_data, 'Goed', source_file)
        if st.session_state.current_chunk < len(X) - 1:
            st.session_state.current_chunk += 1
        st.rerun()