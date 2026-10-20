"""Запуск инкрементальной загрузки JSONL в PostgreSQL."""
from __future__ import annotations
import argparse
from pathlib import Path
from database import FactContract, FactLot, FactPlan, DimSubject, get_engine, init_db, load_jsonl

def run(source_dir: str = "data/export", database_url: str | None = None) -> dict[str, int]:
    engine = get_engine(database_url)
    init_db(engine)
    return load_jsonl(engine, source_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default="data/export")
    args = parser.parse_args()
    print(run(args.source_dir))
