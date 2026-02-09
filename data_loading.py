"""
Data loading module for Edge Analysis.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add src directory to Python path
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))

from typing import Optional
import pandas as pd
import streamlit as st
import re

# Import Notion adapter and parsing helpers
from edge_analysis.data.notion_adapter import load_trades_from_notion
from edge_analysis.data.template_adapter import adapt_df  # NEW: Import template adapter
from edge_analysis.core.parsing import (
    infer_instrument,
    normalize_session,
    build_models_list,
    parse_closed_rr,
    classify_outcome_from_fields,
    normalize_account_group,
    build_duration_bin,
)


@st.cache_data(show_spinner=True, ttl=300)
def load_live_df(token: Optional[str], dbid: Optional[str]) -> pd.DataFrame:
    if not (token and dbid):
        return pd.DataFrame()

    # Fetch raw trades from Notion (returns ALL columns)
    raw = load_trades_from_notion(token, dbid)
    if raw is None or raw.empty:
        return pd.DataFrame()

    # NEW: Apply template mapping to rename columns
    # This maps "Targeted RR" → "Target RR", "GAP Alignment" → "Gap Alignment", etc.
    adapted, template_name = adapt_df(raw, mappings_dir="config/templates")
    
    # Use adapted dataframe if template was found, otherwise use raw
    df = adapted if template_name else raw
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Parse numeric columns
    if "Closed RR" in df.columns:
        df["Closed RR"] = df["Closed RR"].apply(parse_closed_rr)
    if "PnL" in df.columns:
        df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")

    # Vectorized date operations
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        dt_accessor = df["Date"].dt
        df["DayName"] = dt_accessor.day_name()
        df["Hour"] = dt_accessor.hour

    # Instrument and session normalization
    df["Instrument"] = df["Pair"].apply(infer_instrument) if "Pair" in df.columns else "Unknown"
    df["Session Norm"] = df.get("Session", pd.Series(index=df.index, dtype=object)).apply(normalize_session)

    # Entry models list
    if "Multi Entry Model Entry" in df.columns:
        df["Entry Models List"] = df.apply(
            lambda r: build_models_list(r.get("Entry Model"), r.get("Multi Entry Model Entry")),
            axis=1,
        )
    else:
        df["Entry Models List"] = df.get("Entry Model", "").apply(lambda v: build_models_list(v, None))

    # Entry confluence list
    if "Entry Confluence" in df.columns:
        df["Entry Confluence List"] = df["Entry Confluence"].fillna("").astype(str).apply(
            lambda s: [x.strip() for x in re.split(r"[;,]", s) if x.strip()]
        )
    else:
        df["Entry Confluence List"] = [[] for _ in range(len(df))]

    # Outcome classification
    df["Outcome"] = df.apply(
        lambda r: classify_outcome_from_fields(r.get("Result"), r.get("Closed RR"), r.get("PnL")),
        axis=1,
    )

    # Star ratings
    if "Rating" in df.columns:
        df["Stars"] = df["Rating"].apply(lambda s: s.count("⭐") if isinstance(s, str) else None)

    # Risk percentage
    if "Risk Management" in df.columns:
        df["Risk %"] = df["Risk Management"].astype(str).str.extract(r"(\d+(?:\.\d+)?)\s*%")[0].astype(float)

    # Trade duration
    if "Trade Duration" in df.columns:
        df["Trade Duration"] = pd.to_numeric(df["Trade Duration"], errors="coerce")
        df["Duration Bin"] = df["Trade Duration"].apply(build_duration_bin)

    # Account grouping
    if "Account" in df.columns:
        df["Account Group"] = df["Account"].apply(normalize_account_group)

    # Filter valid trades (handle None safely)
    has_date = df["Date"].notna() if "Date" in df.columns else pd.Series(False, index=df.index)
    
    # Build has_signal safely
    conditions = []
    if "PnL" in df.columns:
        conditions.append(df["PnL"].notna())
    if "Closed RR" in df.columns:
        conditions.append(df["Closed RR"].notna())
    if "Result" in df.columns:
        conditions.append(df["Result"].astype(str).str.strip().ne(""))
    if "Entry Model" in df.columns:
        conditions.append(df["Entry Model"].astype(str).str.strip().ne(""))
    
    if conditions:
        has_signal = conditions[0]
        for cond in conditions[1:]:
            has_signal = has_signal | cond
    else:
        has_signal = pd.Series(False, index=df.index)

    return df[has_date & has_signal].copy()
