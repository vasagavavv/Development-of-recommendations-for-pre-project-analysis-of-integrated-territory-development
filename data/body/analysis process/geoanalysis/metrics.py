import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


def load_tags_from_csv(path: str) -> Dict[str, List[Tuple[str, str]]]:
    """Load metrics tags from CSV and return mapping metric -> list of (key, value).

    Expects CSV with columns: id, metric, key, value (flexible separators).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Tags CSV not found: {path}")

    # try to guess delimiter by sampling the file
    sample = p.read_text(encoding="utf-8", errors="ignore")[:4096]
    sep = ','
    if sample.count(';') > sample.count(','):
        sep = ';'

    # try parsing with detected separator, fall back to common alternatives
    for attempt_sep in (sep, ',', ';', '\t'):
        try:
            df = pd.read_csv(path, comment="#", encoding="utf-8", sep=attempt_sep, header=0, engine="python")
            break
        except Exception:
            df = None
    if df is None:
        raise ValueError(f"Не удалось прочитать CSV файл тегов: {path}")

    df.columns = [c.strip() for c in df.columns]
    lower_cols = [c.lower() for c in df.columns]

    # allow variations in column names
    def find_col(prefixes):
        for pref in prefixes:
            for i, c in enumerate(lower_cols):
                if c.startswith(pref.lower()):
                    return df.columns[i]
        return None

    col_metric = find_col(["metric"])
    col_key = find_col(["key", "k"])
    col_value = find_col(["value", "val"])

    if not col_metric or not col_key or not col_value:
        raise ValueError("CSV must contain Metric, Key and Value columns")

    tags: Dict[str, List[Tuple[str, str]]] = {}
    for _, row in df.iterrows():
        metric = str(row[col_metric]).strip().strip("'\"")
        key = str(row[col_key]).strip().strip("'\"")
        value = str(row[col_value]).strip().strip("'\"")
        if not metric or pd.isna(metric):
            continue
        tags.setdefault(metric, []).append((key, value))

    return tags


def load_colors(path: str) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Colors JSON not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # ensure default exists
    if "default" not in data:
        data["default"] = "#cccccc"
    return data
