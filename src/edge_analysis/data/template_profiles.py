from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re
import json
import pandas as pd

# --- Optional dependencies for YAML/TOML ---
try:
    import yaml  # PyYAML
except Exception:
    yaml = None

try:
    import tomllib  # py311+
except Exception:
    try:
        import tomli as tomllib  # fallback
    except Exception:
        tomllib = None


CANON = ["Date","Pair","Session","Entry Model","Entry Confluence","Outcome","Closed RR","PnL","Is Complete"]

# --------- Profile loading ---------
def _load_one_profile(path: Path) -> dict:
    ext = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if ext in (".yml", ".yaml"):
        if not yaml:
            raise RuntimeError("PyYAML not installed: pip install pyyaml")
        return yaml.safe_load(text)
    if ext == ".json":
        return json.loads(text)
    if ext in (".toml",):
        if not tomllib:
            raise RuntimeError("TOML loader not available (tomllib/tomli)")
        return tomllib.loads(text)
    raise ValueError(f"Unsupported profile extension: {ext}")

def discover_profiles(dirpath: Path) -> List[dict]:
    out = []
    for p in dirpath.glob("*.*"):
        if p.suffix.lower() in (".yml",".yaml",".json",".toml"):
            prof = _load_one_profile(p)
            prof["_path"] = str(p)
            out.append(prof)
    return out

# --------- Auto-match scoring ---------
def _score_profile(df: pd.DataFrame, profile: dict) -> int:
    score = 0
    ident = (profile or {}).get("identity", {})
    cols = set(c.lower() for c in df.columns)

    # contains_columns (exact or case-insensitive)
    needed = [c.lower() for c in ident.get("contains_columns", [])]
    if needed:
        # +3 per satisfied column
        score += sum(3 for c in needed if c in cols)

    # contains_values: [{column, equals}]
    for cond in ident.get("contains_values", []):
        col = cond.get("column")
        val = cond.get("equals")
        if col and col in df.columns and val is not None:
            try:
                if (df[col] == val).any():
                    score += 2
            except Exception:
                pass

    # columns mapping coverage
    mapped = (profile.get("columns") or {})
    score += sum(1 for k,v in mapped.items() if v in df.columns)
    return score

def pick_best_profile(df: pd.DataFrame, profiles: List[dict]) -> Optional[dict]:
    if not profiles:
        return None
    scored = sorted([( _score_profile(df,p), p) for p in profiles], key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    return best if best_score > 0 else None

# --------- Normalization helpers ---------
def _parse_rr(v: object, rr_regex: str) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(rr_regex, s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except Exception:
        return None

def _parse_conf_list(v: object, delims: List[str]) -> List[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            if isinstance(x, dict) and "name" in x:
                out.append(str(x["name"]).strip())
            else:
                out.append(str(x).strip())
        return [x for x in out if x]
    s = str(v).strip()
    if not s:
        return []
    # JSON list?
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
        try:
            j = json.loads(s)
            if isinstance(j, list):
                out = []
                for x in j:
                    if isinstance(x, dict) and "name" in x: out.append(str(x["name"]).strip())
                    else: out.append(str(x).strip())
                return [x for x in out if x]
            if isinstance(j, dict) and "name" in j:
                return [str(j["name"]).strip()]
        except Exception:
            pass
    # Delimited text
    for sep in delims:
        if sep in s:
            return [x.strip() for x in s.split(sep) if x.strip()]
    return [s]

def _truthy_falsy_map(truthy: List[str], falsy: List[str]):
    T = set(x.lower() for x in truthy)
    F = set(x.lower() for x in falsy)
    def to_boolish(x):
        s = str(x).strip().lower()
        if s in T: return True
        if s in F: return False
        return None
    return to_boolish

# --------- Main normalize ----------
def normalize_with_profile(df: pd.DataFrame, profile: dict, overrides: Optional[Dict[str,str]] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy()
    pf = profile or {}
    cols_map = (pf.get("columns") or {}).copy()
    overrides = overrides or {}
    # apply per-DB overrides if provided
    for k, v in overrides.items():
        if v: cols_map[k] = v

    settings = pf.get("settings") or {}
    date_fmt = settings.get("date_format") or "%Y-%m-%d"
    rr_regex = settings.get("rr_regex") or r"(-?\d+(?:[.,]\d+)?)"
    delims = settings.get("conf_delims") or [";", ",", "|", "/", "&", "•"]
    truthy = settings.get("complete_truthy") or ["1","true","yes","done","closed","complete"]
    falsy  = settings.get("complete_falsy")  or ["0","false","no","open","active"]
    to_boolish = _truthy_falsy_map(truthy, falsy)

    out = pd.DataFrame(index=df.index)

    # Direct copies (source → canonical)
    for canon in CANON:
        src = cols_map.get(canon)
        if src and src in df.columns:
            out[canon] = df[src]
        else:
            out[canon] = None

    # Parse Date if present (best-effort; don't crash)
    if "Date" in out.columns:
        try:
            out["Date"] = pd.to_datetime(out["Date"], format=date_fmt, errors="coerce")
        except Exception:
            pass

    # RR → float
    if "Closed RR" in out.columns:
        out["Closed RR"] = out["Closed RR"].map(lambda v: _parse_rr(v, rr_regex))

    # Confluence list + first
    if "Entry Confluence" in out.columns:
        clist = out["Entry Confluence"].map(lambda v: _parse_conf_list(v, delims))
        out["Entry Confluence List"] = clist
        out["__first_conf"] = clist.map(lambda L: (L[0] if isinstance(L, list) and L else None))

    # Is Complete → boolish
    if "Is Complete" in out.columns:
        out["Is Complete"] = out["Is Complete"].map(to_boolish)

    # Value maps (Outcome / Session / etc.)
    for field, mapping in (pf.get("maps") or {}).items():
        if field in out.columns:
            out[field] = out[field].map(lambda x: mapping.get(str(x), x) if x is not None else x)

    # Keep originals too (non-breaking)
    for c in df.columns:
        if c not in out.columns:
            out[c] = df[c]

    return out
