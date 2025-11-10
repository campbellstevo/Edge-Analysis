from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
from typing import Optional, Tuple, List, Dict
import re
import os
from datetime import time as dt_time
from zoneinfo import ZoneInfo

# NEW: profile-based fallback (YAML/JSON/TOML)
try:
    from .template_profiles import (
        discover_profiles,
        pick_best_profile,
        normalize_with_profile,
    )
except Exception:
    discover_profiles = pick_best_profile = normalize_with_profile = None

# Canonical order + Session Norm and DayName
CANONICAL_ORDER = [
    "Date", "Pair", "Session", "Session Norm", "Entry Model", "Confluence",
    "Outcome", "Outcome Canonical", "Closed RR", "Closed RR Num",
    "PnL", "Is Complete", "Star Rating", "Notes", "DayName"
]

# ───────────────────────────── IO helpers ─────────────────────────────
def _read_any(path: Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        sep = "\t" if p.suffix.lower() == ".tsv" else ","
        return pd.read_csv(p, sep=sep, dtype=str).fillna("")
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {p.suffix}")

# ───────────────────────────── Coercions ─────────────────────────────
def _coerce(s: pd.Series, kind: str) -> pd.Series:
    if kind == "date":
        return pd.to_datetime(s, errors="coerce").dt.date
    if kind == "float":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\.\-]", "", regex=True), errors="coerce")
    if kind == "int":
        return pd.to_numeric(s.astype(str).str.replace(r"[^\d\-]", "", regex=True), errors="coerce").astype("Int64")
    if kind == "bool":
        return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y", "✅"])
    return s

# ─────────────────────── Case-insensitive utils ──────────────────────
def _cols_lower_map(df: pd.DataFrame) -> Dict[str, str]:
    return {str(c).strip().lower(): c for c in df.columns}

def _find_col(df: pd.DataFrame, name: str) -> Optional[str]:
    if name in df.columns:
        return name
    return _cols_lower_map(df).get(str(name).strip().lower())

# ───────────── Session + day detection (TEMPLATE-DRIVEN SESSIONS) ─────────────
def _clean_session_value(v):
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    sl = s.lower()
    if "asia" in sl:
        return "Asia"
    if "london" in sl:
        return "London"
    if "new york" in sl or sl in {"ny", "ny session"}:
        return "New York"
    return s

def _ensure_session_and_day(out: pd.DataFrame) -> pd.DataFrame:
    if out is None or out.empty:
        return out

    df = out.copy()
    local_out = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
    date_col = _find_col(df, "Date")
    if date_col:
        dts = pd.to_datetime(df[date_col], errors="coerce")
        if dts.dt.tz is None:
            try:
                dts = dts.dt.tz_localize(local_out)
            except Exception:
                pass
        try:
            df["DayName"] = dts.dt.tz_convert(local_out).dt.day_name()
        except Exception:
            df["DayName"] = dts.dt.day_name()
    else:
        if "DayName" not in df.columns:
            df["DayName"] = ""

    sess_col = _find_col(df, "Session")
    if sess_col:
        df["Session Norm"] = df[sess_col].map(_clean_session_value)
    else:
        if "Session Norm" in df.columns:
            df["Session Norm"] = df["Session Norm"].map(_clean_session_value)
        else:
            df["Session Norm"] = ""

    return df

# ─────────────────────── Derived helpers ───────────────────────
def _derive_outcome_canonical(out: pd.DataFrame) -> None:
    if "Outcome Canonical" in out.columns and out["Outcome Canonical"].astype(str).str.strip().ne("").any():
        return
    src = _find_col(out, "Outcome")
    if not src:
        out["Outcome Canonical"] = ""
        return

    def canon(x: str) -> str:
        s = str(x).strip().lower()
        if s in {"win", "won", "w", "profit", "tp"}: return "Win"
        if s in {"be", "break-even", "break even", "breakeven", "scratch"}: return "BE"
        if s in {"loss", "lose", "l", "sl"}: return "Loss"
        return ""
    out["Outcome Canonical"] = out[src].map(canon)

def _derive_closed_rr_num(out: pd.DataFrame) -> None:
    if "Closed RR Num" in out.columns:
        return
    src = _find_col(out, "Closed RR")
    if not src:
        out["Closed RR Num"] = pd.to_numeric(pd.Series([]), errors="coerce")
        return
    out["Closed RR Num"] = pd.to_numeric(
        out[src].astype(str).str.replace(r"[^\d\.\-]", "", regex=True),
        errors="coerce"
    )

# ─────────────────────── Confluence normalization ───────────────────────
def _light_normalize_confluence(out: pd.DataFrame) -> None:
    src = _find_col(out, "Confluence")
    if not src:
        return
    def norm_conf(x: str) -> str:
        if x is None:
            return ""
        s = str(x).strip()
        sl = s.lower()
        if s == "DIV & Sweep": return s
        if re.search(r"\bdiv\b", sl) and re.search(r"\bsweep\b", sl) and not re.search(r"&|,|\+|/", s):
            return "DIV & Sweep"
        if re.search(r"\bdiv\b", sl): return "DIV"
        if re.search(r"\bsweep\b", sl): return "Sweep"
        return s
    out[src] = out[src].map(norm_conf)

# ─────────────────────── NEW: Checkbox → Confluence ───────────────────────
def _attach_confluence_from_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a single 'Confluence' column from checkbox flags:
    - DIV?   (True/False)
    - Sweep? (True/False)
    """
    if df is None or df.empty:
        return df

    if "DIV?" not in df.columns and "Sweep?" not in df.columns:
        return df

    def _calc(row):
        has_div = bool(row.get("DIV?", False))
        has_sweep = bool(row.get("Sweep?", False))
        if has_div and has_sweep:
            return "DIV & Sweep"
        elif has_div:
            return "DIV"
        elif has_sweep:
            return "Sweep"
        else:
            return None

    df = df.copy()
    df["Confluence"] = df.apply(_calc, axis=1)
    return df

# ───────────────────────────── Mapping loader ─────────────────────────────
def _load_maps(dir_path: Path) -> List[dict]:
    out: List[dict] = []
    dir_path.mkdir(parents=True, exist_ok=True)
    for p in sorted(dir_path.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                m = json.load(f)
        except json.JSONDecodeError:
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    m = json.load(f)
            except Exception:
                m = None
        except Exception:
            m = None
        if isinstance(m, dict):
            m["_name"] = p.stem
            out.append(m)
    return out

def _score(headers: List[str], m: dict) -> float:
    src = set([str(k).strip().lower() for k in (m.get("columns") or {}).keys()])
    raw = set([str(h).strip().lower() for h in headers])
    if not src:
        return 0.0
    inter = len(raw & src)
    uni = len(raw | src)
    return inter / uni if uni else 0.0

def _choose(df: pd.DataFrame, maps: List[dict], min_score: float = 0.15, force_name: Optional[str] = None):
    if force_name:
        for m in maps:
            if m.get("_name") == force_name:
                return m
    ranked = sorted((( _score(list(df.columns), m), m) for m in maps), key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= min_score else None

# ───────────────────────────── Adaptation (JSON) ─────────────────────────────
def _adapt_with(df: pd.DataFrame, m: dict) -> pd.DataFrame:
    out = df.copy()
    lower_map = _cols_lower_map(out)

    # Rename columns
    rename: Dict[str, str] = {}
    for src, dst in (m.get("columns") or {}).items():
        actual_src = lower_map.get(str(src).strip().lower())
        if actual_src:
            rename[actual_src] = dst
    if rename:
        out = out.rename(columns=rename)

    # Ensure canonical columns
    for col in CANONICAL_ORDER:
        if col not in out.columns:
            out[col] = ""

    # Derived & canonical
    _derive_outcome_canonical(out)
    _derive_closed_rr_num(out)
    out = _attach_confluence_from_flags(out)  # ← PATCH: build from checkboxes
    _light_normalize_confluence(out)
    out = _ensure_session_and_day(out)
    return out

# ───────────────────────────── Profile fallback ─────────────────────────────
def _adapt_with_profiles(df: pd.DataFrame, *,
    templates_dir: str | Path = "assets/templates",
    profile_name: Optional[str] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, Optional[str]]:
    if df is None or df.empty:
        return df, None
    if not (discover_profiles and pick_best_profile and normalize_with_profile):
        return df, None
    profiles = discover_profiles(Path(templates_dir))
    profile = None
    if profile_name:
        for p in profiles:
            if (p.get("name") or "").lower() == str(profile_name).lower():
                profile = p
                break
    if profile is None:
        profile = pick_best_profile(df, profiles)
    if profile:
        out = normalize_with_profile(df, profile, overrides=overrides or {})
        out = _attach_confluence_from_flags(out)  # ← PATCH: build from checkboxes
        return out, str(profile.get("name") or Path(profile.get("_path","")).stem)
    return df, None

# ───────────────────────────── Public entrypoints ─────────────────────────────
def adapt_auto(file_path: str | Path,
    mappings_dir: str | Path = "config/templates",
    force_mapping: Optional[str] = None, *,
    templates_dir: str | Path = "assets/templates",
    profile_name: Optional[str] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, Optional[str]]:
    df = _read_any(Path(file_path))
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps, force_name=force_mapping)
    if chosen:
        return _adapt_with(df, chosen), chosen.get("_name")
    df2, prof_name = _adapt_with_profiles(df,
        templates_dir=templates_dir, profile_name=profile_name, overrides=overrides)
    return df2, prof_name

def adapt_df(df: pd.DataFrame,
    mappings_dir: str | Path = "config/templates",
    force_mapping: Optional[str] = None, *,
    templates_dir: str | Path = "assets/templates",
    profile_name: Optional[str] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, Optional[str]]:
    if df is None or df.empty:
        return df, None
    maps = _load_maps(Path(mappings_dir))
    chosen = _choose(df, maps, force_name=force_mapping)
    if chosen:
        return _adapt_with(df, chosen), chosen.get("_name")
    df2, prof_name = _adapt_with_profiles(df,
        templates_dir=templates_dir, profile_name=profile_name, overrides=overrides)
    return df2, prof_name

def adapt_with_mapping_name(df: pd.DataFrame,
    mapping_name: str,
    mappings_dir: str | Path = "config/templates",
) -> Tuple[pd.DataFrame, str]:
    maps = _load_maps(Path(mappings_dir))
    chosen = next((m for m in maps if m.get("_name") == mapping_name), None)
    if not chosen:
        raise ValueError(f"Mapping '{mapping_name}' not found in {mappings_dir}")
    return _adapt_with(df, chosen), mapping_name
