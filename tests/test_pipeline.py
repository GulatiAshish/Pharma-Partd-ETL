import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from etl.analyze import parse_queries, run_analysis, SQL_FILE
from etl.extract import detect_year
from etl.load import load
from etl.transform import DataQualityError, transform
from pathlib import Path


def raw_rows(year=2023, eliquis_cost="1000"):
    """Tiny fake CMS extract: national + 2 states, 1 brand, 1 generic, 1 opioid."""
    base = {"Tot_Prscrbrs": "10", "Tot_30day_Fills": "120", "Tot_Benes": "", "Year": year,
            "Opioid_Drug_Flag": "N"}
    rows = []
    for lvl, cd, desc in [("National", "", "National"), ("State", "01", "Alabama"),
                          ("State", "02", "Alaska")]:
        rows += [
            {**base, "Prscrbr_Geo_Lvl": lvl, "Prscrbr_Geo_Cd": cd, "Prscrbr_Geo_Desc": desc,
             "Brnd_Name": "Eliquis ", "Gnrc_Name": "apixaban", "Tot_Clms": "100",
             "Tot_Drug_Cst": eliquis_cost},
            {**base, "Prscrbr_Geo_Lvl": lvl, "Prscrbr_Geo_Cd": cd, "Prscrbr_Geo_Desc": desc,
             "Brnd_Name": "Metformin Hcl", "Gnrc_Name": "Metformin Hcl", "Tot_Clms": "200",
             "Tot_Drug_Cst": "400"},
            {**base, "Prscrbr_Geo_Lvl": lvl, "Prscrbr_Geo_Cd": cd, "Prscrbr_Geo_Desc": desc,
             "Brnd_Name": "Oxycodone Hcl", "Gnrc_Name": "Oxycodone Hcl", "Tot_Clms": "50",
             "Tot_Drug_Cst": "150", "Opioid_Drug_Flag": "Y"},
        ]
    return pd.DataFrame(rows)


# ---------- extract ----------
@pytest.mark.parametrize("name,year", [("partd_2023.csv", 2023),
                                       ("medicare_partd_2024_geo.csv", 2024)])
def test_detect_year(name, year):
    assert detect_year(Path(name)) == year


# ---------- transform ----------
def test_transform_cleans_and_derives():
    df, report = transform(raw_rows())
    assert set(df["brand_name"]) == {"ELIQUIS", "METFORMIN HCL", "OXYCODONE HCL"}  # trimmed + upper
    assert (df.loc[df.geo_level == "National", "geo_code"] == "US").all()
    assert df.loc[df.brand_name == "ELIQUIS", "is_generic"].iat[0] == False   # noqa: E712
    assert df.loc[df.brand_name == "METFORMIN HCL", "is_generic"].iat[0] == True  # noqa: E712
    assert df.loc[df.brand_name == "ELIQUIS", "cost_per_claim"].iat[0] == 10.0
    assert df["total_beneficiaries"].isna().all()          # suppressed -> NULL
    assert report["rows_out"] == 9


def test_transform_removes_duplicates():
    raw = pd.concat([raw_rows(), raw_rows().head(2)])
    _, report = transform(raw)
    assert report["dropped_duplicates"] == 2


def test_transform_rejects_negative_values():
    raw = raw_rows()
    raw.loc[0, "Tot_Drug_Cst"] = "-5"
    with pytest.raises(DataQualityError):
        transform(raw)


# ---------- load ----------
def test_load_is_idempotent(tmp_path):
    db = f"sqlite:///{tmp_path/'t.db'}"
    clean, _ = transform(raw_rows())
    load(clean, db)
    load(clean, db)  # second run must not duplicate rows
    with create_engine(db).connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM fact_prescription")).scalar() == 9
        assert c.execute(text("SELECT COUNT(*) FROM dim_drug")).scalar() == 3
        assert c.execute(text("SELECT COUNT(*) FROM dim_geo")).scalar() == 3


# ---------- analysis SQL ----------
def test_all_queries_run_and_yoy_is_correct(tmp_path):
    db = f"sqlite:///{tmp_path/'t.db'}"
    clean, _ = transform(pd.concat([raw_rows(2023, "1000"), raw_rows(2024, "1500")]))
    load(clean, db)
    q = parse_queries(SQL_FILE.read_text())
    assert len(q) == 6
    results = run_analysis(db, out_dir=str(tmp_path / "out"))
    assert all(len(df) > 0 for name, df in results.items())
    top3 = results["03_top3_drugs_per_state"]
    assert top3.loc[top3.rnk == 1, "brand_name"].eq("ELIQUIS").all()
    opioid = results["05_opioid_claim_share_trend_by_state"]
    assert round(opioid["opioid_share_pct"].iat[0], 2) == round(100 * 50 / 350, 2)