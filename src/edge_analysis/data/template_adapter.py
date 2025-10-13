from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
from typing import Optional, Tuple, List, Dict

# Canonical order used across your app. Extra columns are preserved after these.
CANONICAL_ORDER = [
    "Date", "Pair", "Session", "Entry Model", "Confluence",
    "Outcome", "Closed RR", "PnL", "Is Complete", "Star Rating", "Notes"
]

# ------------------------------ IO helpers -----------------------------------

def _read_any(path: Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        sep = "\t" if p.suffix.lower() == ".tsv" else ","
        return pd.read_csv(p, sep=sep, dtype=str).fillna("")
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {p.suffix}")

# ------------------------------ Coercions ------------------------------------

def _coerce(s: pd.Series, kind: str) -> pd.Series:
    if kind == "date":
        return pd.to_datetime(s, errors="coerce").dt.date
    if kind == "float":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\.\-]", "", regex=True), errors="coerce")
    if kind == "int":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\-]", "", regex=True), errors="coerce").astype("Int64")
    if kind == "bool":
        # Series-safe strip
        return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y", "✅"])
    return s

# ----------------------------- Normalization ---------------------------------

def _normalize(val: str, rules: dict) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    for target, variants in (rules or {}).items():
        for v in variants:
            if s == str(v).lower():
                return target
    return val

# ------------------------- Case-insensitive helpers --------------------------

def _cols_lower_map(df: pd.DataFrame) -> Dict[str, str]:
    """Map lowercase, stripped column name -> actual column name."""
    out: Dict[str, str] = {}
    for c in df.columns:
        out.setdefault(str(c).strip().lower(), c)
    return out

def _find_col(df: pd.DataFrame, name: str) -> Optional[str]:
    """Find a column case-insensitively. Returns the actual column name or None."""
    if name in df.columns:
        return name
    lower_map = _cols_lower_map(df)
    return lower_map.get(str(name).strip().lower())

def _get_coercions_ci(m: dict, df: pd.DataFrame) -> Dict[str, str]:
    """Return {actual_col: kind} for coercions, case-insensitive by key."""
    out: Dict[str, str] = {}
    for key, kind in (m.get("coercions") or {}).items():
        actual = _find_col(df, key)
        if actual:
            out[actual] = kind
    return out

def _get_normalizers_ci(m: dict, df: pd.DataFrame) -> Dict[str, dict]:
    """Return {actual_col: rules} for normalizers, case-insensitive by key."""
    out: Dict[str, dict] = {}
    for key, rules in (m.get("normalizers") or {}).items():
        actual = _find_col(df, key)
        if actual:
            out[actual] = rules
    return out

# ------------------------------- Mappings ------------------------------------

def _load_maps(dir_path: Path) -> List[dict]:
    """
    Load mapping JSON files, tolerant of UTF-8 BOM.
    Tries utf-8 first, then utf-8-sig. Skips unreadable files gracefully.
    """
    out: List[dict] = []
    dir_path.mkdir(parents=True, exist_ok=True)
    for p in sorted(dir_path.glob("*.json")):
        m = None
        # 1) Try plain UTF-8
        try:
            with open(p, "r", encoding="utf-8") as f:
                m = json.load(f)
        except json.JSONDecodeError:
            # 2) Retry with BOM-friendly codec
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    m = json.load(f)
            except Exception:
                m = None
        except Exception:
            m = None

        if not isinstance(m, dict):
            # skip bad file
            continue

        m["_name"] = p.stem
        out.append(m)
    return out

def list_mappings(mappings_dir: str | Path = "config/templates") -> List[str]:
    """List available mapping names (derived from JSON filenames)."""
    maps = _load_maps(Path(mappings_dir))
    return [m.get("_name", "") for m in maps]

# ------------------------------- Scoring -------------------------------------

def _score(headers: List[str], m: dict) -> float:
    """Case-insensitive Jaccard similarity between df headers and mapping 'columns' keys."""
    src = set([str(k).strip().lower() for k in (m.get("columns") or {}).keys()])
    raw = set([str(h).strip().lower() for h in headers])
    if not src:
        return 0.0
    inter = len(raw & src)
    uni = len(raw | src)
    return inter / uni if uni else 0.0

def _choose(
    df: pd.DataFrame,
    maps: List[dict],
    min_score: float = 0.15,
    force_name: Optional[str] = None,
) -> dict | None:
    """
    Choose a mapping by:
      1) explicit force_name if provided (exact match on _name), else
      2) best scoring map by header overlap (case-insensitive), requiring min_score.
    """
    if force_name:
        for m in maps:
            if m.get("_name") == force_name:
                return m
        # If forced name not found, fall through to auto-choose

    ranked = sorted(
        (( _score(list(df.columns), m), m) for m in maps),
        key=lambda x: x[0],
        reverse=True
    )
    return ranked[0][1] if ranked and ranked[0][0] >= min_score else None

# ------------------------------- Adaptation ----------------------------------

def _adapt_with(df: pd.DataFrame, m: dict) -> pd.DataFrame:
    """
    Apply a mapping dict to df, case-insensitively:
      - m["columns"]: {source -> canonical}
      - m["normalizers"]: {canonical_or_any_case -> rules}
      - m["coercions"]: {canonical_or_any_case -> kind}
    """
    out = df.copy()
    lower_map = _cols_lower_map(out)

    # 1) Build a case-insensitive rename map from mapping columns
    rename: Dict[str, str] = {}
    for src, dst in (m.get("columns") or {}).items():
        actual_src = lower_map.get(str(src).strip().lower())
        if actual_src:
            rename[actual_src] = dst
    if rename:
        out = out.rename(columns=rename)

    # 2) Ensure canonical columns exist (preserve extras)
    for col in CANONICAL_ORDER:
        if col not in out.columns:
            out[col] = ""

    # 3) Apply normalizers (case-insensitive by key name from JSON)
    norm_map = _get_normalizers_ci(m, out)
    for col, rules in norm_map.items():
        out[col] = out[col].apply(lambda v: _normalize(v, rules))

    # 4) Apply coercions (case-insensitive by key name from JSON)
    coerce_map = _get_coercions_ci(m, out)
    for col, kind in coerce_map.items():
        out[col] = _coerce(out[col], kind)

    # 5) Derived fields from Date (case-insensitive find)
    date_col = _find_col(out, "Date")
    if date_col:
        dts = pd.to_datetime(out[date_col], errors="coerce")
        out["DayName"] = dts.dt.day_name()
        out["Month"]   = dts.dt.to_period("M").astype(str)
        out["Week"]    = dts.dt.isocalendar().week.astype("Int64")

    # 6) Order canonical -> rest
    order = CANONICAL_ORDER + [c for c in out.columns if c not in CANONICAL_ORDER]
    return out[order]

# --------------------------- Public entrypoints ------------------------------

def adapt_auto(
    file_path: str | Path,
    mappings_dir: str | Path = "config/templates",
    force_mapping: Optional[str] = None,
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Read a file (csv/tsv/xlsx), choose a template mapping (auto or forced),
    and return (adapted_df, mapping_name_or_None).
    """
    df = _read_any(Path(file_path))
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps, force_name=force_mapping)
    if not chosen:
        return df, None
    return _adapt_with(df, chosen), chosen.get("_name")

def adapt_df(
    df: pd.DataFrame,
    mappings_dir: str | Path = "config/templates",
    force_mapping: Optional[str] = None,
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Adapt an in-memory dataframe using the same chooser.
    Optionally force a mapping by name (e.g., 'TradingPools' or 'Mine').
    Returns (adapted_df, mapping_name_or_None).
    """
    if df is None or df.empty:
        return df, None
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps, force_name=force_mapping)
    if not chosen:
        return df, None
    return _adapt_with(df, chosen), chosen.get("_name")

def adapt_with_mapping_name(
    df: pd.DataFrame,
    mapping_name: str,
    mappings_dir: str | Path = "config/templates",
) -> Tuple[pd.DataFrame, str]:
    """
    Directly adapt with an explicit mapping name. Raises if not found.
    """
    maps = _load_maps(Path(mappings_dir))
    chosen = next((m for m in maps if m.get("_name") == mapping_name), None)
    if not chosen:
        raise ValueError(f"Mapping '{mapping_name}' not found in {mappings_dir}")
    return _adapt_with(df, chosen), mapping_name
