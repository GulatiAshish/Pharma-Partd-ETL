"""Extract: read the raw CMS Medicare Part D 'by Geography and Drug' CSV files."""
import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# The only CMS columns we need. read_csv stops with a clear error if any is missing.
COLUMNS = [
    "Prscrbr_Geo_Lvl", "Prscrbr_Geo_Cd", "Prscrbr_Geo_Desc",
    "Brnd_Name", "Gnrc_Name",
    "Tot_Prscrbrs", "Tot_Clms", "Tot_30day_Fills", "Tot_Drug_Cst", "Tot_Benes",
    "Opioid_Drug_Flag",
]


def detect_year(path: Path) -> int:
    """The CMS file has no year column, so take it from the file name: partd_2023.csv -> 2023."""
    m = re.search(r"20\d{2}", path.name)
    if not m:
        raise ValueError(f"No year in file name '{path.name}'. Rename it like partd_2023.csv")
    return int(m.group())


def extract(input_dir: str) -> pd.DataFrame:
    files = sorted(Path(input_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {input_dir}")

    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str, usecols=COLUMNS)  # read as text; transform sets the types
        df["Year"] = detect_year(f)
        log.info("Extracted %s rows from %s", f"{len(df):,}", f.name)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)