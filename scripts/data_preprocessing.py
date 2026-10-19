import pandas as pd
import ast
from utils import aggregate_diagnostic

def preprocess_data(path):
    """
    Perform data preprocessing on the ECG data.

    Parameters:
    path (str): Path to the directory containing CSV files.

    Returns:
    DataFrame: Preprocessed DataFrame with combined and encoded labels of normal and STTC EGC's.
    """
    # Load the annotation data
    Y = pd.read_csv(path + 'ptbxl_database.csv', index_col='ecg_id')

    # Convert scp_codes from string to dictionary
    Y.scp_codes = Y.scp_codes.apply(lambda x: ast.literal_eval(x))

    # Load the scp_statements data
    agg_df = pd.read_csv(path + 'scp_statements.csv', index_col=0)

    # Filter diagnostic statements
    agg_df = agg_df[agg_df.diagnostic == 1]

    # Add diagnostic superclass
    Y['diagnostic_superclass'] = Y.scp_codes.apply(lambda x: aggregate_diagnostic(x, agg_df))

    # Filter for 'STTC' and 'NORM'
    df_sttc = Y[Y['diagnostic_superclass'].astype(str) == "['STTC']"]
    df_norm = Y[Y['diagnostic_superclass'].astype(str) == "['NORM']"]

    # Reset indexes
    df_norm.reset_index(drop=True, inplace=True)
    df_sttc.reset_index(drop=True, inplace=True)

    # Combine DataFrames
    df_combined = pd.concat([df_norm, df_sttc], axis=0)
    df_combined.reset_index(drop=True, inplace=True)

    # Convert to string for encoding
    df_combined['diagnostic_superclass_str'] = df_combined['diagnostic_superclass'].astype(str)

    return df_combined
