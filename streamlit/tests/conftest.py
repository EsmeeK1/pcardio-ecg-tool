import os
import sys
import tempfile
from pathlib import Path

# Pagina-tests schrijven naar een tijdelijke map, nooit naar streamlit/data/. Moet vóór het importeren van
# kern.opslag gezet worden.
os.environ["ECG_TOOL_DATA"] = tempfile.mkdtemp(prefix="ecg_tool_test_")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
