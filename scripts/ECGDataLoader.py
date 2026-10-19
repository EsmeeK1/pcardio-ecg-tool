import os
import pandas as pd

class ECGDataLoader:
    """
    A class used to handle the loading and extraction of ECG data from multiple text files in a directory.
    Each file's data is loaded into a pandas DataFrame with additional labels and unique ECG IDs.
    """

    def __init__(self, directory):
        """
        Initializes the ECGDataLoader with the directory containing text files to be processed.

        :param directory: The directory path containing .txt files.
        """
        self.directory = directory
        self.ecg_counter = 1  # Start ID counter

    def load_files_to_dataframe(self):
        """
        Load all .txt files from the directory into a single pandas DataFrame.
        Each row represents one line from the file, with datetime, date, time, value, a label (filename),
        and a unique ecg_id that identifies rows from the same file.

        :return: A pandas DataFrame with columns datetime, date, time, value, label, and ecg_id.
        """
        all_data = []

        for filename in os.listdir(self.directory):
            if filename.endswith('.txt'):
                # Extract label from filename (e.g., file name without extension)
                label = os.path.splitext(filename)[0]

                # Set a unique ECG ID for this file
                ecg_id = f"ECG_{self.ecg_counter}"
                self.ecg_counter += 1

                file_path = os.path.join(self.directory, filename)
                file_data = self._process_file(file_path)

                # Add label and ecg_id to each row
                file_data['label'] = label
                file_data['ecg_id'] = ecg_id

                # Append the DataFrame to the list
                all_data.append(file_data)

        # Concatenate all DataFrames into a single DataFrame
        df = pd.concat(all_data, ignore_index=True)
        return df

    def _process_file(self, path):
        """
        Process a single .txt file, extracting date, time, and value from each line.
        Assumes each line is formatted as: date\t time\t value

        :param path: The file path to the text file to be processed.
        :return: A pandas DataFrame with columns datetime, date, time, and value.
        """
        with open(path, 'r') as file:
            lines = file.read().splitlines()

        data = []
        for line in lines:
            columns = line.split('\t')  # Splitting based on tabs
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