from __future__ import annotations
import re
import numpy as np
import pandas as pd

_INSTRUMENT_PATTERNS=[
    (re.compile(r"xau|gold",re.I),"Gold"),
    (re.compile(r"nas|ndx|nasdaq|us100",re.I),"NASDAQ"),
    (re.compile(r"audusd|aud\/?usd|\bau\b|\baud\b",re.I),"AUDUSD"),
]

def infer_instrument(v):
    s=str(v) if not pd.isna(v) else ""
    for pat,name in _INSTRUMENT_PATTERNS:
        if pat.search(s): return name
    s=s.strip()
    return s if s else "Unknown"

def normalize_session(s:str)->str:
    t=str(s).lower().strip()
    if not t or t=="nan": return None
    if re.search(r"\bny\b|nyc|new ?york|us session|us open|new-?york",t): return "New York"
    if re.search(r"london|ldn|uk session|eu session|euro",t): return "London"
    if re.search(r"asia|asian|tokyo|sydney",t): return "Asia"
    return t.title()

def _split_listish(x):
    if pd.isna(x): return []
    s=str(x).strip()
    return [p.strip() for p in re.split(r"[;,]",s) if p.strip()] if s else []

def normalize_entry_model(x:str)->str:
    if not isinstance(x,str): return ""
    t=x.strip().lower()
    if not t: return ""
    if "internal fbos" in t: return "Internal FBoS Protected Structure"
    if "external fbos" in t: return "External FBOS Protected Structure"
    if "internal protected structure" in t: return "Internal Protected Structure"
    if "external protected structure" in t: return "External Protected Structure"
    if "internal no close" in t: return "Internal No Close"
    if "external no close" in t: return "External No Close"
    if t in {"yes","no","n/a","na"}: return ""
    return t.title()

def build_models_list(entry_model, multi_entry):
    models=_split_listish(entry_model)+_split_listish(multi_entry)
    models=[normalize_entry_model(m) for m in models if m]
    # Try to preserve known set first else unique sorted
    if models:
        MODEL_SET=[
            "Internal FBoS Protected Structure","Internal No Close","Internal Protected Structure",
            "External FBOS Protected Structure","External No Close","External Protected Structure",
        ]
        keep=[]
        for m in models:
            if m in MODEL_SET and m not in keep: keep.append(m)
        if keep: return keep
    return sorted(set(models))

_RR_RANGE_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*([+-]?\d+(?:\.\d+)?)', re.I)
def parse_closed_rr(x):
    if x is None or (isinstance(x, float) and pd.isna(x)): return np.nan
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip()
    if not s: return np.nan
    m = _RR_RANGE_RE.search(s)
    if m:
        a = float(m.group(1)); b = float(m.group(2))
        return (a + b) / 2.0
    s = s.replace('+', '')
    try: return float(s)
    except Exception: return np.nan

def normalize_result_label(x:str)->str:
    if not isinstance(x,str): return ""
    t=x.strip().lower()
    if t=="early close (ended up being a win)": return "WIN"
    if t=="early close (ended up being a be)":  return "WIN"
    if t=="full tp":                            return "WIN"
    if t in {"breakeven","break even","b/e"}:   return "BE"
    if t=="loss":                               return "LOSS"
    return ""

def classify_outcome_from_fields(result_raw, closed_rr, pnl):
    label=normalize_result_label(result_raw)
    if label=="WIN": return "Win"
    if label=="BE":  return "BE"
    if label=="LOSS":return "Loss"
    if pd.notna(closed_rr):
        try:
            rr=float(closed_rr)
            if rr>0: return "Win"
            if rr==0: return "BE"
            if rr<0: return "Loss"
        except Exception: pass
    if pd.notna(pnl):
        try:
            p=float(pnl)
            if p>0: return "Win"
            if p==0: return "BE"
            if p<0: return "Loss"
        except Exception: pass
    return "Unknown"

def normalize_account_group(s:str):
    if not isinstance(s,str) or not s.strip(): return None
    t=s.strip().lower()
    mapping={
        "late ft":"Forward Test",
        "ft on demo challenge":"Forward Test",
        "live on challenge":"Challenge Accounts",
        "live on funded":"Funded Account",
        "live on personal":"Personal Accounts",
        "live on track record & trade copier":"Personal Accounts",
        "track record account":"Track Record Account",
        "live on track record":"Track Record Account",
        "trade copier":"Track Record Account",
    }
    return mapping.get(t, s.strip().title())

def build_duration_bin(minutes: float):
    if pd.isna(minutes): return np.nan
    v=float(minutes)
    if v <= 30: return "≤30m"
    if v <= 120: return "30m–2h"
    if v <= 360: return "2–6h"
    return ">6h"

# =========================
# COMPLETION LOGIC (ADD-ON)
# =========================

# We reuse your existing helpers:
# - normalize_result_label(...)
# - parse_closed_rr(...)
# - classify_outcome_from_fields(...)

def _split_tokens_commas_semicolons(x):
    """Split multi-select style strings safely."""
    if pd.isna(x):
        return []
    s = str(x).strip()
    return [t.strip() for t in re.split(r"[;,]", s) if t.strip()] if s else []

def canonical_outcome_from_result(result_raw: str) -> str | None:
    """
    Reduce your multi-select 'Result' to a single canonical outcome:
      - WIN has priority, then BE, then LOSS.
      - Uses your normalize_result_label mapping.
    Returns 'Win'|'BE'|'Loss' or None if undecidable.
    """
    toks = _split_tokens_commas_semicolons(result_raw)
    if not toks:
        return None
    mapped = [normalize_result_label(t) for t in toks]
    if any(m == "WIN" for m in mapped):  return "Win"
    if any(m == "BE"  for m in mapped):  return "BE"
    if any(m == "LOSS"for m in mapped):  return "Loss"
    return None

def coerce_closed_rr_any(raw) -> float | np.nan:
    """
    Robust parser for 'Closed RR' which may contain:
      - Single numbers: '+2', '-1', '0'
      - Ranges: '+2-3' (averaged to 2.5)
      - Multi-select lists: '+0, +1-2, ... , -2' (we take the RIGHT-most parsable)
    Returns float or np.nan.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return np.nan
    s = str(raw).strip()
    if not s:
        return np.nan
    # Try direct parse first (covers numbers and ranges)
    v = parse_closed_rr(s)
    if pd.notna(v):
        return float(v)
    # If it's a list, take the right-most parsable token
    parts = _split_tokens_commas_semicolons(s)
    for p in reversed(parts):
        vv = parse_closed_rr(p)
        if pd.notna(vv):
            return float(vv)
    # Fallback: any number present
    m = re.findall(r"[+-]?\d+(?:\.\d+)?", s)
    if m:
        try:
            return float(m[-1])
        except Exception:
            pass
    return np.nan

def classify_completion_row(row: pd.Series, strict: bool = True) -> tuple[bool, str, str | None, float | np.nan]:
    """
    Determine if a row is 'complete' based on:
      strict=True  -> require BOTH a canonical Outcome and numeric Closed RR
      strict=False -> require EITHER canonical Outcome OR numeric Closed RR

    Returns:
      (is_complete, reason_if_incomplete, outcome_canonical, closed_rr_num)
    """
    # Prefer explicit/canonical from Result; if missing, fall back to your numeric logic.
    outcome_canonical = canonical_outcome_from_result(row.get("Result"))
    closed_rr_num = coerce_closed_rr_any(row.get("Closed RR"))

    if outcome_canonical is None:
        # Fallback: infer from numbers the way YOUR function does
        oc = classify_outcome_from_fields(
            row.get("Result"),
            closed_rr_num,
            row.get("PnL"),
        )
        if oc in {"Win", "BE", "Loss"}:
            outcome_canonical = oc

    has_outcome = outcome_canonical in {"Win", "BE", "Loss"}
    has_rr = pd.notna(closed_rr_num)

    if strict:
        if has_outcome and has_rr:
            return True, "", outcome_canonical, closed_rr_num
        missing = []
        if not has_outcome: missing.append("Outcome")
        if not has_rr:      missing.append("Closed RR")
        return False, "Missing: " + ", ".join(missing), outcome_canonical, closed_rr_num
    else:
        if has_outcome or has_rr:
            return True, "", outcome_canonical, closed_rr_num
        return False, "Missing: Outcome or Closed RR", outcome_canonical, closed_rr_num

def add_completion_flags(df: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    """
    Non-destructive: returns a copy with added columns:
      - 'Outcome Canonical' : 'Win' | 'BE' | 'Loss' | None
      - 'Closed RR Num'     : float (parsed)
      - 'Is Complete'       : bool
      - 'Completion'        : 'Complete' | 'Incomplete'
      - 'Incomplete Reason' : '' or reason string
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    is_complete_vals, reasons, outcomes, rrs = [], [], [], []

    for _, r in out.iterrows():
        ok, why, oc, rr = classify_completion_row(r, strict=strict)
        is_complete_vals.append(ok)
        reasons.append(why)
        outcomes.append(oc)
        rrs.append(rr)

    out["Outcome Canonical"] = outcomes
    out["Closed RR Num"] = rrs
    out["Is Complete"] = is_complete_vals
    out["Completion"] = out["Is Complete"].map(lambda b: "Complete" if b else "Incomplete")
    out["Incomplete Reason"] = reasons
    return out
