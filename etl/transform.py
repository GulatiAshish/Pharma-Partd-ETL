"""Transform: clean and type the raw data, remove duplicates, add metrics, check quality."""
import logging

import pandas as pd

log = logging.getLogger(__name__)

RENAME = {
    "Prscrbr_Geo_Lvl": "geo_level",
    "Prscrbr_Geo_Cd": "geo_code",
    "Prscrbr_Geo_Desc": "geo_name",
    "Brnd_Name": "brand_name",
    "Gnrc_Name": "generic_name",
    "Tot_Prscrbrs": "total_prescribers",
    "Tot_Clms": "total_claims",
    "Tot_30day_Fills": "total_30day_fills",
    "Tot_Drug_Cst": "total_drug_cost",
    "Tot_Benes": "total_beneficiaries",
    "Opioid_Drug_Flag": "opioid_flag",
    "Year": "year",
}
NUMERIC = ["total_prescribers", "total_claims", "total_30day_fills",
           "total_drug_cost", "total_beneficiaries"]
KEY = ["year", "geo_level", "geo_code", "brand_name", "generic_name"]  # one row per year+place+drug


class DataQualityError(Exception):
    """Raised when the data is too broken to load."""


def transform(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = raw.rename(columns=RENAME)

    # text: trim spaces; upper-case drug names so "Eliquis " and "ELIQUIS" are the same drug
    for col in ["geo_level", "geo_code", "geo_name", "brand_name", "generic_name"]:
        df[col] = df[col].fillna("").str.strip()
    df["brand_name"] = df["brand_name"].str.upper()
    df["generic_name"] = df["generic_name"].str.upper()
    df.loc[df["geo_level"] == "National", "geo_code"] = "US"  # national rows have a blank code

    # numbers: CMS leaves small (suppressed) values blank -> NaN -> NULL in the database, not 0
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
    df["opioid_flag"] = df["opioid_flag"].eq("Y")

    # a duplicated key would double-count every total downstream
    dupes = df.duplicated(subset=KEY)
    report = {"rows_in": len(df), "dropped_duplicates": int(dupes.sum())}
    df = df[~dupes].copy()

    # derived columns (CMS lists a generic drug with brand name == generic name)
    df["is_generic"] = df["brand_name"] == df["generic_name"]
    df["cost_per_claim"] = (df["total_drug_cost"] / df["total_claims"]).round(2)

    # quality: impossible values stop the run; suppressed values are only counted
    if (df[NUMERIC] < 0).any().any():
        raise DataQualityError("Negative counts or costs found - the source file looks corrupt")
    report["suppressed_beneficiary_rows"] = int(df["total_beneficiaries"].isna().sum())
    report["rows_out"] = len(df)

    log.info("Transform report: %s", report)
    return df.reset_index(drop=True), report