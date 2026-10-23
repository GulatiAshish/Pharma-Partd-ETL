"""Load: star schema (dim_drug, dim_geo, fact_prescription). Re-running a year replaces it.

Runs on SQLite by default; pass a MySQL URL to use MySQL instead.
"""
import logging

import pandas as pd
from sqlalchemy import (Boolean, Column, Float, ForeignKey, Integer, MetaData,
                        String, Table, UniqueConstraint, create_engine, delete, select)

log = logging.getLogger(__name__)
metadata = MetaData()

dim_drug = Table(
    "dim_drug", metadata,
    Column("drug_id", Integer, primary_key=True, autoincrement=True),
    Column("brand_name", String(200), nullable=False),
    Column("generic_name", String(200), nullable=False),
    Column("is_generic", Boolean, nullable=False),
    Column("opioid_flag", Boolean, nullable=False),
    UniqueConstraint("brand_name", "generic_name", name="uq_drug"),
)

dim_geo = Table(
    "dim_geo", metadata,
    Column("geo_id", Integer, primary_key=True, autoincrement=True),
    Column("geo_level", String(20), nullable=False),
    Column("geo_code", String(10), nullable=False),
    Column("geo_name", String(100), nullable=False),
    UniqueConstraint("geo_level", "geo_code", name="uq_geo"),
)

fact_prescription = Table(
    "fact_prescription", metadata,
    Column("year", Integer, primary_key=True),
    Column("drug_id", Integer, ForeignKey("dim_drug.drug_id"), primary_key=True),
    Column("geo_id", Integer, ForeignKey("dim_geo.geo_id"), primary_key=True),
    Column("total_prescribers", Float),
    Column("total_claims", Float),
    Column("total_30day_fills", Float),
    Column("total_drug_cost", Float),
    Column("total_beneficiaries", Float),
    Column("cost_per_claim", Float),
)


def _upsert_dim(conn, table, df: pd.DataFrame, key_cols: list[str], id_col: str) -> pd.DataFrame:
    """Insert dimension rows that aren't in the table yet; return the key -> id lookup."""
    existing = pd.DataFrame(conn.execute(select(table)).mappings().all())
    incoming = df.drop_duplicates(subset=key_cols)
    if not existing.empty:
        merged = incoming.merge(existing[key_cols], on=key_cols, how="left", indicator=True)
        incoming = merged[merged["_merge"] == "left_only"].drop(columns="_merge")
    if not incoming.empty:
        conn.execute(table.insert(), incoming.to_dict("records"))
    log.info("%s: %d new rows", table.name, len(incoming))
    lookup = pd.DataFrame(conn.execute(select(table)).mappings().all())
    return lookup[key_cols + [id_col]]


def load(df: pd.DataFrame, db_url: str) -> None:
    engine = create_engine(db_url)
    metadata.create_all(engine)  # creates the tables only if they don't exist

    with engine.begin() as conn:  # one transaction: everything is saved, or nothing is
        drug_map = _upsert_dim(conn, dim_drug,
                               df[["brand_name", "generic_name", "is_generic", "opioid_flag"]],
                               ["brand_name", "generic_name"], "drug_id")
        geo_map = _upsert_dim(conn, dim_geo, df[["geo_level", "geo_code", "geo_name"]],
                              ["geo_level", "geo_code"], "geo_id")

        # swap names for ids, keep only the fact table's columns, NaN -> None (SQL NULL)
        fact = (df.merge(drug_map, on=["brand_name", "generic_name"])
                  .merge(geo_map, on=["geo_level", "geo_code"]))
        fact_cols = [c.name for c in fact_prescription.columns]
        fact = fact[fact_cols].astype(object).where(fact[fact_cols].notna(), None)

        # delete this run's years first, so loading the same year twice never duplicates rows
        years = sorted(int(y) for y in fact["year"].unique())
        conn.execute(delete(fact_prescription).where(fact_prescription.c.year.in_(years)))
        conn.execute(fact_prescription.insert(), fact.to_dict("records"))

    log.info("Loaded %s fact rows for years %s", f"{len(fact):,}", years)