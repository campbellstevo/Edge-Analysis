from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

CANONICAL_ORDER = [
    "Date","Pair","Session","Entry Model","Confluence",
    "Outcome","Closed RR","PnL","Is Complete","Star Rating","Notes"
]

def _read_any(path: Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        sep = "\t" if p.suffix.lower() == ".tsv" else ","
        return pd.read_csv(p, sep=sep, dtype=str).fillna("")
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {p.suffix}")

def _coerce(s: pd.Series, kind: str) -> pd.Series:
    if kind == "date":
        return pd.to_datetime(s, errors="coerce").dt.date
    if kind == "float":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\.\-]", "", regex=True), errors="coerce")
    if kind == "int":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\-]", "", regex=True), errors="coerce").astype("Int64")
    if kind == "bool":
        return s.astype(str).strip().str.lower().isin(["true","1","yes","y","✅"])
    return s

def _normalize(val: str, rules: dict) -> str:
    if val is None: return ""
    s = str(val).strip().lower()
    for target, variants in (rules or {}).items():
        for v in variants:
            if s == str(v).lower():
                return target
    return val

def _load_maps(dir_path: Path) -> list[dict]:
    out = []
    dir_path.mkdir(parents=True, exist_ok=True)
    for p in sorted(dir_path.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            m = json.load(f)
        m["_name"] = p.stem
        out.append(m)
    return out

def _score(headers: list[str], m: dict) -> float:
    src = set((m.get("columns") or {}).keys())
    raw = set(headers)
    if not src: return 0.0
    inter = len(raw & src); uni = len(raw | src)
    return inter / uni if uni else 0.0

def _choose(df: pd.DataFrame, maps: list[dict], min_score: float = 0.15) -> dict | None:
    ranked = sorted((( _score(list(df.columns), m), m) for m in maps), key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= min_score else None

def _adapt_with(df: pd.DataFrame, m: dict) -> pd.DataFrame:
    rename = {src: dst for src, dst in (m.get("columns") or {}).items() if src in df.columns}
    out = df.rename(columns=rename).copy()
    # ensure columns
    for col in CANONICAL_ORDER:
        if col not in out.columns:
            out[col] = ""
    # normalize
    for col, rules in (m.get("normalizers") or {}).items():
        if col in out.columns:
            out[col] = out[col].apply(lambda v: _normalize(v, rules))
    # coerce
    for col, kind in (m.get("coercions") or {}).items():
        if col in out.columns:
            out[col] = _coerce(out[col], kind)
    # derived
    if "Date" in out.columns:
        dts = pd.to_datetime(out["Date"], errors="coerce")
        out["DayName"] = dts.dt.day_name()
        out["Month"]   = dts.dt.to_period("M").astype(str)
        out["Week"]    = dts.dt.isocalendar().week.astype("Int64")
    order = CANONICAL_ORDER + [c for c in out.columns if c not in CANONICAL_ORDER]
    return out[order]

def adapt_auto(file_path: str | Path, mappings_dir: str | Path = "config/templates"):
    df = _read_any(Path(file_path))
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps)
    if not chosen:
        return df, None
    return _adapt_with(df, chosen), chosen.get("_name")

# NEW: allow adapting in-memory DataFrames (e.g., live Notion pulls)
def adapt_df(df: pd.DataFrame, mappings_dir: str | Path = "config/templates"):
    """
    Adapt an in-memory dataframe using the same mapping chooser as file-based adapt_auto().
    Returns (adapted_df, mapping_name_or_None).
    """
    if df is None or df.empty:
        return df, None
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps)
    if not chosen:
        return df, None
    return _adapt_with(df, chosen), chosen.get("_name")
