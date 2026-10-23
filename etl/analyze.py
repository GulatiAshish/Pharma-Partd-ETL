"""Run every query in sql/analysis.sql and save each result to outputs/<name>.csv."""
import logging
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

log = logging.getLogger(__name__)
SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "analysis.sql"


def parse_queries(sql_text: str) -> dict[str, str]:
    """Split the file on '-- name: x' markers -> {name: query}."""
    parts = re.split(r"^-- name:\s*(\S+)\s*$", sql_text, flags=re.MULTILINE)
    # parts = [header, name1, sql1, name2, sql2, ...]
    return {parts[i]: parts[i + 1].strip().rstrip(";") for i in range(1, len(parts), 2)}


def run_analysis(db_url: str, out_dir: str = "outputs") -> dict[str, pd.DataFrame]:
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    engine = create_engine(db_url)
    results = {}
    with engine.connect() as conn:
        for name, query in parse_queries(SQL_FILE.read_text()).items():
            df = pd.read_sql(text(query), conn)
            df.to_csv(out / f"{name}.csv", index=False)
            results[name] = df
            log.info("%s -> %d rows", name, len(df))
    return results