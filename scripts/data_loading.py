import pandas as pd
import numpy as np
import ast
import wfdb

def load_dataframe(path):
    """
    Load the DataFrame containing the ECG data.

    Parameters:
    path (str): Path to the directory containing the CSV file.

    Returns:
    DataFrame: DataFrame containing the ECG data.
    """

    df = pd.read_csv(path + 'ptbxl_database.csv', index_col='ecg_id')

    df.scp_codes = df.scp_codes.apply(lambda x: ast.literal_eval(x))

    return df



def load_raw_data(df, sampling_rate, path):
    """
    Load raw ECG data files based on the sampling rate.

    Parameters:
    df (DataFrame): DataFrame with file paths and labels.
    sampling_rate (int): Desired sampling rate (100 or 500 Hz).
    path (str): Path to the directory containing ECG files.

    Returns:
    tuple: Array of signals and corresponding labels.
    """
    if sampling_rate == 100:
        data = [wfdb.rdsamp(path + f) for f in df.filename_lr]
    else:
        data = [wfdb.rdsamp(path + f) for f in df.filename_hr]
    data = np.array([signal for signal, meta in data])

    label = df.encoded_labels

    return data, label