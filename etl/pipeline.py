"""Entry point:  python -m etl.pipeline  [--input data/raw] [--db sqlite:///partd.db]"""
import argparse
import logging
import os
import time

from etl.analyze import run_analysis
from etl.extract import extract
from etl.load import load
from etl.transform import transform


def main() -> None:
    parser = argparse.ArgumentParser(description="CMS Medicare Part D ETL pipeline")
    parser.add_argument("--input", default="data/raw", help="folder with yearly CMS CSV files")
    parser.add_argument("--db", default=os.getenv("DATABASE_URL", "sqlite:///partd.db"),
                        help="SQLAlchemy URL, e.g. mysql+pymysql://user:pwd@localhost/partd")
    parser.add_argument("--skip-analysis", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    log = logging.getLogger("pipeline")

    t0 = time.perf_counter()
    raw = extract(args.input)
    clean, report = transform(raw)
    load_stats = load(clean, args.db)
    if not args.skip_analysis:
        run_analysis(args.db)
    log.info("Done in %.1fs | quality=%s | load=%s", time.perf_counter() - t0, report, load_stats)


if __name__ == "__main__":
    main()
