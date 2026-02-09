from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from pathlib import Path  # PATCH: for template download paths
import re  # for splitting entry model strings
import os
from datetime import time as dt_time
from zoneinfo import ZoneInfo

# NEW: import the three clean renderers from components
from edge_analysis.ui.components import (
    render_entry_model_table,
    render_session_performance_table,
    render_day_performance_table,
)

# PATCH: auto-detect adapter for multiple templates
from edge_analysis.data.template_adapter import adapt_auto

CONFLUENCE_OPTIONS = ["DIV", "Sweep", "DIV & Sweep"]


def _asset_label(name: str) -> str:
    return "GOLD" if str(name) == "Gold" else str(name)


# ─────────────────────────── Session/Date helpers (NEW) ──────────────────────
def _extract_iso_from_notion(v):
    """Accept Notion date property dicts/lists or plain strings/numbers."""
    try:
        if isinstance(v, dict):
            return v.get("start") or v.get("date") or v.get("timestamp") or v.get("name")
        if isinstance(v, (list, tuple)) and v:
            return _extract_iso_from_notion(v[0])
    except Exception:
        pass
    return v


def _coerce_datetime_series(df: pd.DataFrame, tz_name: str = "UTC"):
    """
    Return a UTC-aware datetime Series from a variety of column schemes:
    - single datetime-like column (Date & Time / Datetime / Opened At / Timestamp / Created...)
    - separate Date + Time columns
    - only Date column (defaults to 00:00)
    Handles numbers as epoch s/ms and Notion dicts.
    """
    cand_single = [
        "Date & Time",
        "Datetime",
        "Entry Datetime",
        "Opened At",
        "Timestamp",
        "Created",
        "Created At",
        "Entry Time (UTC)",
        "Time & Date",
    ]
    cand_date = ["Date", "Trade Date", "Entry Date"]
    cand_time = ["Time", "Trade Time", "Entry Time"]

    # 1) Single datetime-like
    for c in cand_single:
        if c in df.columns:
            s = df[c].map(_extract_iso_from_notion)

            def _num_to_ts(x):
                try:
                    if x is None or (isinstance(x, float) and pd.isna(x)):
                        return None
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        x = int(x)
                        if x > 10 ** 11:  # ms
                            return pd.to_datetime(x, unit="ms", utc=True)
                        return pd.to_datetime(x, unit="s", utc=True)
                    return x
                except Exception:
                    return x

            s = s.map(_num_to_ts)
            s_dt = pd.to_datetime(s, utc=True, errors="coerce")
            break
    else:
        s_dt = None

    # 2) Separate Date + Time
    if s_dt is None:
        dcol = next((c for c in cand_date if c in df.columns), None)
        tcol = next((c for c in cand_time if c in df.columns), None)
        if dcol and tcol:
            s_date = pd.to_datetime(df[dcol].map(_extract_iso_from_notion), errors="coerce")
            s_time = df[tcol].astype(str).str.strip().replace({"": "00:00"})
            s_dt = pd.to_datetime(
                s_date.dt.strftime("%Y-%m-%d") + " " + s_time,
                errors="coerce",
            )

    # 3) Only Date
    if s_dt is None:
        dcol = next((c for c in cand_date if c in df.columns), None)
        if dcol:
            s_date = pd.to_datetime(df[dcol].map(_extract_iso_from_notion), errors="coerce")
            s_dt = pd.to_datetime(s_date.dt.strftime("%Y-%m-%d") + " 00:00", errors="coerce")

    if s_dt is None:
        return None  # caller will handle

    # Localize → UTC
    try:
        tz = ZoneInfo(str(tz_name or "UTC"))
        if s_dt.dt.tz is None:
            s_dt = s_dt.dt.tz_localize(tz).dt.tz_convert("UTC")
        else:
            s_dt = s_dt.dt.tz_convert("UTC")
    except Exception:
        # Fallback: assume UTC if localization fails
        if s_dt.dt.tz is None:
            s_dt = s_dt.dt.tz_localize("UTC")
        else:
            s_dt = s_dt.dt.tz_convert("UTC")

    return s_dt


# --- DST-safe market-local session classifier --------------------------------
# Sessions defined in THEIR LOCAL MARKET TIME (handles DST correctly)
_SESSIONS = {
    "Asia": {
        "tz": ZoneInfo("Asia/Tokyo"),
        "start": dt_time(9, 0),
        "end": dt_time(18, 0),
    },  # 09:00–18:00 Tokyo
    "London": {
        "tz": ZoneInfo("Europe/London"),
        "start": dt_time(8, 0),
        "end": dt_time(17, 0),
    },  # 08:00–17:00 London
    "New York": {
        "tz": ZoneInfo("America/New_York"),
        "start": dt_time(8, 0),
        "end": dt_time(17, 0),
    },  # 08:00–17:00 NY
}


def _time_in_window(local_dt: pd.Timestamp, start: dt_time, end: dt_time) -> bool:
    """
    True if local_dt's local time is within [start, end).
    Handles windows that cross midnight (not used here but robust).
    """
    if pd.isna(local_dt):
        return False
    t = local_dt.timetz()
    if start <= end:
        return start <= t < end
    return (t >= start) or (t < end)


def _classify_session_market_local(ts_aware: pd.Timestamp) -> str | None:
    """
    Classify into Asia / London / New York using each market's local clock.
    If multiple sessions overlap, choose by priority: New York > London > Asia.
    (Only used as a fallback now; primary source is the template Session field.)
    """
    if ts_aware is None or pd.isna(ts_aware):
        return None

    active = []
    for name, cfg in _SESSIONS.items():
        local = ts_aware.astimezone(cfg["tz"])
        if _time_in_window(local, cfg["start"], cfg["end"]):
            active.append(name)

    if not active:
        return "Other"

    for winner in ["New York", "London", "Asia"]:
        if winner in active:
            return winner


def _clean_session_value(v):
    """
    Normalise session labels coming from the template/Notion.
    This is the new primary source of truth for sessions.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    sl = s.lower()
    if "asia" in sl:
        return "Asia"
    if "london" in sl:
        return "London"
    if "new york" in sl or sl in {"ny", "ny session"}:
        return "New York"
    # Any other custom label, just return cleaned
    return s


def _ensure_session_and_day(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure we have 'Session Norm' and 'DayName'.

    Priority:
      1) If 'Session Norm' already present and non-null, keep it.
         Still compute DayName if missing.
      2) Else, if 'Session' column exists, derive Session Norm
         from that (template/Notion-driven, NOT from time).
      3) Only if neither Session Norm nor Session exists do we
         fall back to time-based classification from timestamps.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    # ---- Case 1: Session Norm already exists (from adapter/template) ----
    if "Session Norm" in out.columns and not out["Session Norm"].isna().all():
        # Clean labels a bit
        out["Session Norm"] = out["Session Norm"].map(_clean_session_value)

        # Still compute DayName if missing/empty
        if "DayName" not in out.columns or out["DayName"].isna().all():
            s_dt = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
            if s_dt is not None:
                try:
                    local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
                    out["DayName"] = s_dt.dt.tz_convert(local_tz).dt.day_name()
                except Exception:
                    out["DayName"] = s_dt.dt.day_name()
        return out

    # ---- Case 2: No Session Norm, but we DO have a Session column ----
    if "Session" in out.columns:
        out["Session Norm"] = out["Session"].map(_clean_session_value)

        # DayName: derive from datetime if possible, else from Date
        if "DayName" not in out.columns or out["DayName"].isna().all():
            s_dt = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
            if s_dt is not None:
                try:
                    local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
                    out["DayName"] = s_dt.dt.tz_convert(local_tz).dt.day_name()
                except Exception:
                    out["DayName"] = s_dt.dt.day_name()
            elif "Date" in out.columns:
                dts = pd.to_datetime(out["Date"], errors="coerce")
                out["DayName"] = dts.dt.day_name()
        return out

    # ---- Case 3: No Session Norm and no Session → LAST-RESORT time-based ----
    s_dt_utc = _coerce_datetime_series(out, tz_name=os.getenv("EDGE_SESSIONS_TZ", "Australia/Sydney"))
    if s_dt_utc is None:
        out["Session Norm"] = None
        if "DayName" not in out.columns:
            out["DayName"] = None
        return out

    out["__ts_utc"] = s_dt_utc

    # Classify using market-local clocks (DST-safe)
    out["Session Norm"] = out["__ts_utc"].map(_classify_session_market_local)

    # DayName in local user zone (Australia/Sydney default, DST-aware)
    try:
        local_tz = ZoneInfo(os.getenv("EDGE_LOCAL_TZ", "Australia/Sydney"))
        out["DayName"] = out["__ts_utc"].dt.tz_convert(local_tz).dt.day_name()
    except Exception:
        out["DayName"] = out["__ts_utc"].dt.day_name()  # fallback UTC

    return out.drop(columns=["__ts_utc"])


# ---- Completion-aware helpers (non-breaking) --------------------------------
def _prep_perf_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    For performance tabs: use only complete trades when available,
    prefer canonical outcome and numeric RR, but keep original column names.
    """
    if df is None or df.empty:
        return df

    out = df.copy()

    # 1) Filter to complete rows if that flag exists
    if "Is Complete" in out.columns:
        out = out[out["Is Complete"] == True].copy()

    # 2) Prefer canonical outcome but keep column name 'Outcome'
    if "Outcome Canonical" in out.columns:
        if "Outcome" not in out.columns:
            out["Outcome"] = out["Outcome Canonical"]
        else:
            mask_bad = ~out["Outcome"].isin(["Win", "BE", "Loss"])
            out.loc[mask_bad, "Outcome"] = out.loc[mask_bad, "Outcome Canonical"]

    # 3) Prefer numeric RR but keep column name 'Closed RR'
    if "Closed RR Num" in out.columns:
        if "Closed RR" not in out.columns:
            out["Closed RR"] = out["Closed RR Num"]
        else:
            mask_nan = out["Closed RR"].isna()
            out.loc[mask_nan, "Closed RR"] = out["Closed RR Num"]

    # 4) Ensure Session Norm + DayName derived (now template-driven when Session exists)
    try:
        out = _ensure_session_and_day(out)
    except Exception:
        # fail-safe: keep going without sessions/days
        pass

    return out


def outcome_rates_from(df):
    if df.empty or "Outcome" not in df.columns:
        return dict(
            total=0,
            counted=0,
            wins=0,
            bes=0,
            losses=0,
            win_rate=0.0,
            be_rate=0.0,
            loss_rate=0.0,
        )
    counted = df[df["Outcome"].isin(["Win", "BE", "Loss"])]
    counted_n = len(counted)
    wins = int(counted["Outcome"].eq("Win").sum())
    bes = int(counted["Outcome"].eq("BE").sum())
    losses = int(counted["Outcome"].eq("Loss").sum())
    wr = round((wins / max(1, counted_n)) * 100.0, 2)
    br = round((bes / max(1, counted_n)) * 100.0, 2)
    lr = round((losses / max(1, counted_n)) * 100.0, 2)
    return dict(
        total=len(df),
        counted=counted_n,
        wins=wins,
        bes=bes,
        losses=losses,
        win_rate=wr,
        be_rate=br,
        loss_rate=lr,
    )


def _rr_stats(df: pd.DataFrame):
    """
    Helper for performance tables:
    returns (Net PnL (R), Expectancy (R)) from 'Closed RR'.
    """
    if df is None or df.empty or "Closed RR" not in df.columns:
        return (None, None)
    rr = pd.to_numeric(df["Closed RR"], errors="coerce")
    rr = rr.dropna()
    if rr.empty:
        return (None, None)
    net = float(rr.sum())
    ex = float(rr.mean())
    return (net, ex)


def generate_overall_stats(df: pd.DataFrame):
    if df.empty:
        return dict(
            total=0,
            wins=0,
            losses=0,
            bes=0,
            win_rate=0.0,
            loss_rate=0.0,
            be_rate=0.0,
            avg_rr=0.0,
            avg_pnl=0.0,
            total_pnl=0.0,
            unknown=0,
        )
    rates = outcome_rates_from(df)
    unknown = rates["total"] - rates["counted"]

    # Avg Closed RR from winning trades only
    if {"Closed RR", "Outcome"} <= set(df.columns):
        wins_only = df[df["Outcome"] == "Win"]
        avg_rr = (
            float(wins_only["Closed RR"].mean())
            if not wins_only.empty and not wins_only["Closed RR"].isna().all()
            else 0.0
        )
    else:
        avg_rr = 0.0

    avg_pnl = float(df["PnL"].mean()) if "PnL" in df.columns and not df["PnL"].isna().all() else 0.0
    total_pnl = float(df["PnL"].sum()) if "PnL" in df.columns and not df["PnL"].isna().all() else 0.0
    return dict(
        total=rates["total"],
        wins=rates["wins"],
        losses=rates["losses"],
        bes=rates["bes"],
        win_rate=rates["win_rate"],
        loss_rate=rates["loss_rate"],
        be_rate=rates["be_rate"],
        avg_rr=avg_rr,
        avg_pnl=avg_pnl,
        total_pnl=total_pnl,
        unknown=unknown,
    )


def _to_alt_values(df: pd.DataFrame):
    if df is None or len(df) == 0:
        return []
    d = df.reset_index(drop=True).copy()
    for c in d.columns:
        col = d[c]
        if pd.api.types.is_datetime64_any_dtype(col):
            tmp = pd.to_datetime(col, errors="coerce")
            if getattr(tmp.dt, "tz", None) is not None:
                tmp = tmp.dt.tz_localize(None)
            d[c] = tmp.dt.to_pydatetime()
        elif pd.api.types.is_integer_dtype(col):
            d[c] = col.apply(lambda v: None if pd.isna(v) else int(v))
        elif pd.api.types.is_float_dtype(col):
            d[c] = col.apply(lambda v: None if pd.isna(v) else float(v))
        else:
            d[c] = col.astype(object)
    return d.to_dict(orient="records")


# NEW: normalize "Entry Models List" across templates
def _ensure_entry_models_list(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guarantee a column 'Entry Models List' that is a list[str] for each row.
    Accepts alternate columns like 'Entry Model' or 'Entry Models' and splits
    on common delimiters: comma, semicolon, slash, pipe, plus.
    """
    if df is None or df.empty:
        return df

    out = df.copy()

    if "Entry Models List" in out.columns:

        def _coerce_to_list(v):
            if isinstance(v, (list, tuple)):
                return list(v)
            if pd.isna(v) or v == "":
                return []
            return [str(v)]

        out["Entry Models List"] = out["Entry Models List"].apply(_coerce_to_list)
        return out

    # Try alternate source columns
    lower_map = {str(c).strip().lower(): c for c in out.columns}
    alt_col = None
    for key in ("entry models", "entry model", "entry models list"):
        if key in lower_map:
            alt_col = lower_map[key]
            break

    def _split_models(x):
        if isinstance(x, (list, tuple)):
            return [str(i).strip() for i in x if str(i).strip()]
        if pd.isna(x):
            return []
        s = str(x)
        parts = [p.strip() for p in re.split(r"[;,/|+]", s) if p.strip()]
        return parts if parts else ([] if s.strip() == "" else [s.strip()])

    if alt_col:
        out["Entry Models List"] = out[alt_col].apply(_split_models)
    else:
        # no usable column; create empty lists to avoid KeyError downstream
        out["Entry Models List"] = [[] for _ in range(len(out))]

    return out


# NEW: normalize/derive 'Instrument' across templates
def _ensure_instrument_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure there's an 'Instrument' column by copying/deriving it from common
    alternates like Pair, Symbol, Ticker, Market, Asset.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    lower_map = {str(c).strip().lower(): c for c in out.columns}

    def pick(*names):
        for n in names:
            if n in lower_map:
                return lower_map[n]
        return None

    # If already present, try to fill NaNs from alternates
    if "Instrument" in out.columns:
        alt = pick("pair", "symbol", "ticker", "market", "asset")
        if alt is not None:
            mask = out["Instrument"].isna() | (out["Instrument"].astype(str).str.strip() == "")
            out.loc[mask, "Instrument"] = out.loc[mask, alt]
        return out

    # Otherwise create it from the first available alternate
    alt = pick("instrument", "pair", "symbol", "ticker", "market", "asset")
    if alt is not None:
        out["Instrument"] = out[alt]
    # If none found, we just return without Instrument; caller must handle
    return out


# ───────────────────────────── Growth (FIXED DATE HANDLING) ──────────────────
def _growth_tab(f: pd.DataFrame, df_all: pd.DataFrame, styler):
    """
    FIXED: Proper datetime resampling for Day/Week/Month buckets.
    No more duplicate labels or misaligned dates.
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    # Use ONLY the complete slice (already filtered in app.py)
    if f is None or f.empty:
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()

    # --- Find a usable date column ---
    date_col = None
    if "Date" in g.columns:
        date_col = "Date"
    else:
        for c in g.columns:
            cl = str(c).strip().lower()
            if cl == "date" or "date" in cl or "time" in cl:
                date_col = c
                break

    if not date_col:
        st.warning("No date-like column found in complete trades.")
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # --- Coerce to real datetimes ---
    g["__Date"] = g[date_col].astype(str).str.replace(r"\s*\(GMT.*\)$", "", regex=True)
    g["__Date"] = pd.to_datetime(g["__Date"], errors="coerce")

    # Drop NaT
    g = g[g["__Date"].notna()].copy()
    if g.empty:
        with st.expander("Debug: date parsing", expanded=False):
            try:
                st.write("Sample raw values:", f[date_col].head(5).tolist())
            except Exception:
                pass
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Remove timezone to get clean naive datetime
    try:
        if getattr(g["__Date"].dt, "tz", None) is not None:
            g["__Date"] = g["__Date"].dt.tz_localize(None)
    except Exception:
        pass

    # Ensure PnL_from_RR exists (prefer numeric RR if present)
    if "PnL_from_RR" not in g.columns:
        rr_col = "Closed RR Num" if "Closed RR Num" in g.columns else "Closed RR"
        g["PnL_from_RR"] = g.get(rr_col, 0.0).fillna(0.0)

    # Controls (only Time Bucket now; Win Rate Mode is always cumulative)
    c1, _, _ = st.columns([1, 1, 2])
    with c1:
        bucket = st.selectbox(
            "Time Bucket",
            ["Day", "Week", "Month"],
            index=1,
            key="growth_bucket",
        )

    # Sort by date
    g = g.sort_values("__Date").copy()

    # FIXED: Set datetime index for proper resampling
    g_indexed = g.set_index("__Date")

    # FIXED: Resample based on bucket type - use pandas resample for proper datetime handling
    if bucket == "Day":
        # Daily: group by date (no resampling needed, already daily)
        eq_df = (
            g_indexed.groupby(g_indexed.index.date)["PnL_from_RR"]
            .sum()
            .reset_index()
        )
        # Rename the grouped column to "Bucket"
        eq_df.columns = ["Bucket", "PnLBucket"]
        # Convert date back to datetime for consistent handling
        eq_df["Bucket"] = pd.to_datetime(eq_df["Bucket"])
        axis_fmt = "%b %d"
    elif bucket == "Week":
        # Weekly: resample to week start (Monday)
        eq_df = (
            g_indexed["PnL_from_RR"]
            .resample("W-MON", label="left", closed="left")
            .sum()
            .reset_index()
        )
        eq_df.columns = ["Bucket", "PnLBucket"]
        axis_fmt = "%b %d"
    else:  # Month
        # Monthly: resample to month start
        eq_df = (
            g_indexed["PnL_from_RR"]
            .resample("MS")
            .sum()
            .reset_index()
        )
        eq_df.columns = ["Bucket", "PnLBucket"]
        axis_fmt = "%b %Y"

    # Calculate cumulative PnL
    eq_df["CumPnL"] = eq_df["PnLBucket"].fillna(0).cumsum()

    # Prepare Altair data with proper datetime types
    # Use labelOverlap to automatically hide crowded labels
    if bucket == "Week":
        # For weekly: angle labels
        x_time = alt.X(
            "Bucket:T",
            title=None,
            axis=alt.Axis(
                format=axis_fmt,
                labelAngle=-45,
                labelLimit=200,
                labelOverlap=True,  # Auto-hide overlapping labels
            ),
            scale=alt.Scale(nice=False, padding=0.05),
        )
    elif bucket == "Month":
        # For monthly: horizontal
        x_time = alt.X(
            "Bucket:T",
            title=None,
            axis=alt.Axis(
                format=axis_fmt,
                labelAngle=0,
                labelLimit=140,
                labelOverlap=True,  # Auto-hide overlapping labels
            ),
            scale=alt.Scale(nice=False, padding=0),
        )
    else:
        # For daily: automatic label thinning
        x_time = alt.X(
            "Bucket:T",
            title=None,
            axis=alt.Axis(
                format=axis_fmt,
                labelAngle=0,
                labelLimit=140,
                labelOverlap=True,
            ),
            scale=alt.Scale(nice=False, padding=0),
        )
    pnl_vals = _to_alt_values(eq_df[["Bucket", "CumPnL"]])

    # FIXED: Win rate calculation (always cumulative) with proper resampling
    wr = g[["__Date", "Outcome"]].dropna()
    wr = wr[wr["Outcome"].isin(["Win", "BE", "Loss"])]
    wr_vals = []
    if not wr.empty:
        # Create indexed version for resampling
        wr_indexed = wr.set_index("__Date")

        # Resample win rate data to match bucket type
        if bucket == "Day":
            wr_grouped = (
                wr_indexed.groupby(wr_indexed.index.date)
                .agg(
                    trades=("Outcome", "count"),
                    wins=("Outcome", lambda s: (s == "Win").sum()),
                )
                .reset_index()
            )
            wr_grouped.columns = ["Bucket", "trades", "wins"]
            wr_grouped["Bucket"] = pd.to_datetime(wr_grouped["Bucket"])
        elif bucket == "Week":
            wr_grouped = (
                wr_indexed.resample("W-MON", label="left", closed="left")
                .agg(
                    trades=("Outcome", "count"),
                    wins=("Outcome", lambda s: (s == "Win").sum()),
                )
                .reset_index()
            )
            wr_grouped.columns = ["Bucket", "trades", "wins"]
        else:  # Month
            wr_grouped = (
                wr_indexed.resample("MS")
                .agg(
                    trades=("Outcome", "count"),
                    wins=("Outcome", lambda s: (s == "Win").sum()),
                )
                .reset_index()
            )
            wr_grouped.columns = ["Bucket", "trades", "wins"]

        # Calculate cumulative win rate
        wr_grouped["CumTrades"] = wr_grouped["trades"].cumsum()
        wr_grouped["CumWins"] = wr_grouped["wins"].cumsum()
        wr_grouped["Win %"] = np.where(
            wr_grouped["CumTrades"] > 0,
            (wr_grouped["CumWins"] / wr_grouped["CumTrades"]) * 100.0,
            0.0,
        )
        wr_plot = wr_grouped[["Bucket", "Win %"]].copy()
        wr_plot["Win %"] = wr_plot["Win %"].round(2)
        wr_vals = _to_alt_values(wr_plot[["Bucket", "Win %"]])

    # Charts
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("### Cumulative PnL (RR)")
        if pnl_vals:
            area = (
                alt.Chart(alt.Data(values=pnl_vals))
                .mark_area(opacity=0.12, color="#4800ff")
                .encode(
                    x=x_time,
                    y=alt.Y("CumPnL:Q", title="Cumulative PnL (RR)"),
                )
            )
            line = (
                alt.Chart(alt.Data(values=pnl_vals))
                .mark_line(strokeWidth=2, color="#4800ff", interpolate="linear")
                .encode(x=x_time, y="CumPnL:Q")
            )
            st.altair_chart(
                styler(alt.layer(area, line).properties(height=320)),
                use_container_width=True,
            )
        else:
            st.info("Not enough data for PnL chart.")
    with c_right:
        st.markdown("### Win Rate (%)")
        if wr_vals:
            line_color = (
                "#0f172a"
                if st.session_state.get("ui_theme", "light") == "light"
                else "#e5e7eb"
            )
            # Use labelOverlap to automatically hide crowded labels
            if bucket == "Week":
                # For weekly: angle labels
                xwr = alt.X(
                    "Bucket:T",
                    title=None,
                    axis=alt.Axis(
                        format=axis_fmt,
                        labelAngle=-45,
                        labelLimit=200,
                        labelOverlap=True,
                    ),
                    scale=alt.Scale(nice=False, padding=0.05),
                )
            elif bucket == "Month":
                # For monthly: horizontal
                xwr = alt.X(
                    "Bucket:T",
                    title=None,
                    axis=alt.Axis(
                        format=axis_fmt,
                        labelAngle=0,
                        labelLimit=140,
                        labelOverlap=True,
                    ),
                    scale=alt.Scale(nice=False, padding=0),
                )
            else:
                # For daily: automatic
                xwr = alt.X(
                    "Bucket:T",
                    title=None,
                    axis=alt.Axis(
                        format=axis_fmt,
                        labelAngle=0,
                        labelLimit=140,
                        labelOverlap=True,
                    ),
                    scale=alt.Scale(nice=False, padding=0),
                )
            line = (
                alt.Chart(alt.Data(values=wr_vals))
                .mark_line(
                    strokeWidth=2,
                    color=line_color,
                    interpolate="linear",
                )
                .encode(
                    x=xwr,
                    y=alt.Y(
                        "Win %:Q",
                        title="Win Rate (%)",
                        scale=alt.Scale(domain=[0, 100]),
                    ),
                )
                .properties(height=320)
            )
            st.altair_chart(styler(line), use_container_width=True)
        else:
            st.info("Not enough data for Win Rate chart.")

    latest_wr = (
        float(pd.DataFrame(wr_vals)["Win %"].dropna().iloc[-1]) if wr_vals else float("nan")
    )
    latest_eq = (
        float(pd.DataFrame(pnl_vals)["CumPnL"].dropna().iloc[-1])
        if pnl_vals
        else float("nan")
    )
    st.markdown(
        f"<div class='muted'>Latest Win %: <b>{latest_wr:.2f}%</b> &nbsp;|&nbsp; Cumulative PnL: <b>{latest_eq:,.2f} R</b></div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------ Other tabs -----------------------------------
def _entry_models_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Ensure we have a proper list column, regardless of template
    f_norm = _ensure_entry_models_list(f)

    if "Entry Models List" not in f_norm.columns:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Keep only rows that have at least one model
    em = f_norm.copy()
    em = em[
        em["Entry Models List"].apply(
            lambda x: isinstance(x, (list, tuple)) and len(x) > 0
        )
    ]
    if em.empty:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # One row per model
    em = em.explode("Entry Models List", ignore_index=True)
    em = em[em["Entry Models List"].astype(str).str.strip() != ""]
    if em.empty:
        st.info("No entry model data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    counted = em[em["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rates = []
    for model, group in counted.groupby("Entry Models List"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rates.append(
            dict(
                Entry_Model=str(model),
                Trades=len(group),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rates:
        entry_model_df = pd.DataFrame(rates).sort_values("Win %", ascending=False)
        render_entry_model_table(entry_model_df, title="Entry Model Performance")
    else:
        st.info("No counted outcomes yet.")

    st.markdown("</div>", unsafe_allow_html=True)


# ---------- NEW: Confluence tab ----------------------------------------------
def _confluences_tab(f: pd.DataFrame, show_table):
    """
    Confluence Performance tab:
    - Uses DIV? and Sweep? columns (or Entry Confluence as fallback)
    - Aggregates Trades / Win % / BE % / Loss % / Net PnL (R) / Expectancy (R) for:
        DIV, Sweep, DIV & Sweep
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()

    # ---- Figure out which columns are DIV / Sweep (robust, avoids Divergence) ---
    lower_map = {str(c).strip().lower(): c for c in g.columns}

    def _norm_name(name: str) -> str:
        # strip everything except letters and lowercase
        return re.sub(r"[^a-z]", "", name.lower())

    div_col_name = None
    sweep_col_name = None
    for key, col in lower_map.items():
        norm = _norm_name(key)
        if norm == "div" and div_col_name is None:
            div_col_name = col
        if norm == "sweep" and sweep_col_name is None:
            sweep_col_name = col

    # ---- Derive a 'Confluence' label per row --------------------------------
    def _from_yes_no(val) -> bool:
        if val is None:
            return False
        if isinstance(val, float) and pd.isna(val):
            return False
        s = str(val).strip().lower()
        return s in {"yes", "y", "true", "1"}

    def _classify_row(row):
        # Primary path: separate DIV / Sweep columns (your new template)
        if div_col_name is not None or sweep_col_name is not None:
            div_flag = _from_yes_no(row.get(div_col_name)) if div_col_name is not None else False
            sweep_flag = _from_yes_no(row.get(sweep_col_name)) if sweep_col_name is not None else False

            if div_flag and sweep_flag:
                return "DIV & Sweep"
            if div_flag and not sweep_flag:
                return "DIV"
            if sweep_flag and not div_flag:
                return "Sweep"
            return None

        # Fallback: single Entry Confluence-like column (old style)
        for col_name in ["Entry Confluence", "Confluence"]:
            if col_name in row.index:
                v = row[col_name]
                if isinstance(v, (list, tuple, set)):
                    items = [str(x).strip().lower() for x in v]
                else:
                    s = str(v)
                    items = [p.strip().lower() for p in re.split(r"[;,/|+]", s) if p.strip()]

                has_div = any("div" in it for it in items)
                has_sweep = any("sweep" in it for it in items)

                if has_div and has_sweep:
                    return "DIV & Sweep"
                if has_div and not has_sweep:
                    return "DIV"
                if has_sweep and not has_div:
                    return "Sweep"
                return None

        return None

    g["Confluence"] = g.apply(_classify_row, axis=1)
    g = g[g["Confluence"].notna()]
    if g.empty:
        st.info("No DIV / Sweep confluence data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Only counted outcomes
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet for any confluence.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ---- Aggregate to DIV / Sweep / DIV & Sweep -----------------------------
    rows = []
    for conf in CONFLUENCE_OPTIONS:
        sub = counted[counted["Confluence"] == conf]
        if sub.empty:
            continue
        r = outcome_rates_from(sub)
        net_rr, ex_rr = _rr_stats(sub)
        rows.append(
            dict(
                Confluence=conf,
                Trades=len(sub),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rows:
        conf_df = (
            pd.DataFrame(rows)
            .sort_values("Win %", ascending=False)
            .reset_index(drop=True)
        )
        # Reuse Entry Model layout by renaming the label column
        conf_df = conf_df.rename(columns={"Confluence": "Entry_Model"})
        render_entry_model_table(conf_df, title="Confluence Performance")
    else:
        st.info("No confluence stats available.")

    st.markdown("</div>", unsafe_allow_html=True)


def _sessions_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    # Title comes from the renderer
    if f.empty or "Session Norm" not in f.columns or f["Session Norm"].isna().all():
        st.info("No session data.")
    else:
        counted = f[f["Outcome"].isin(["Win", "BE", "Loss"])]
        rates = []
        for sess, g in counted.groupby("Session Norm"):
            r = outcome_rates_from(g)
            net_rr, ex_rr = _rr_stats(g)
            rates.append(
                dict(
                    Session=sess,
                    Trades=len(g),
                    **{
                        "Win %": r["win_rate"],
                        "BE %": r["be_rate"],
                        "Loss %": r["loss_rate"],
                        "Net PnL (R)": net_rr,
                        "Expectancy (R)": ex_rr,
                    },
                )
            )
        session_df = pd.DataFrame(rates).sort_values("Win %", ascending=False)
        render_session_performance_table(session_df, title="Session Performance")
    st.markdown("</div>", unsafe_allow_html=True)


# ---------- NEW: Instruments tab (performance by instrument/pair) ------------
def _instruments_tab(f: pd.DataFrame, show_table):
    """
    Performance by instrument/pair.

    - Normalizes an 'Instrument' column from Instrument/Pair/Symbol/Ticker/Market.
    - Uses only rows in the provided slice (already completion-aware via _prep_perf_df).
    - Computes win / BE / loss rate per instrument and shows it in the same
    card style as Entry Model Performance.
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Normalise the Instrument column (Pair / Symbol / Ticker / Market → Instrument)
    g = _ensure_instrument_column(f)
    if "Instrument" not in g.columns:
        st.info(
            "No instrument/pair column detected (Instrument/Pair/Symbol/Ticker/Market)."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = g.copy()
    g["Instrument"] = g["Instrument"].astype(str).str.strip()
    g = g[g["Instrument"] != ""]
    if g.empty:
        st.info("No instrument values present.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Only counted outcomes
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if counted.empty:
        st.info("No counted outcomes yet for any instrument.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Build the same style table as Entry Models: Instrument | Trades | Win % | BE % | Loss % | Net PnL (R)
    rows = []
    for inst, g_inst in counted.groupby("Instrument"):
        r = outcome_rates_from(g_inst)
        net_rr, ex_rr = _rr_stats(g_inst)
        rows.append(
            dict(
                Instrument=_asset_label(inst),
                Trades=len(g_inst),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rows:
        instrument_df = (
            pd.DataFrame(rows)
            .sort_values("Win %", ascending=False)
            .reset_index(drop=True)
        )
        # Use the same renderer as Entry Models to match theme/colours
        render_entry_model_table(instrument_df, title="Asset Performance")
    else:
        st.info("No instrument stats available.")

    st.markdown("</div>", unsafe_allow_html=True)


# ---------- Days-only (Mon–Fri), no hours/duration in this tab ----------
def _time_days_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    # Title comes from the renderer
    counted = f[f["Outcome"].isin(["Win", "BE", "Loss"])]

    # Prefer DayName if present; else fall back to a 'Day' column
    day_col = "DayName" if "DayName" in counted.columns else ("Day" if "Day" in counted.columns else None)
    if not day_col or counted.empty:
        st.info("No day-of-week signal in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    df_days = counted[counted[day_col].isin(order)].copy()
    if df_days.empty:
        st.info("No Mon–Fri data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    df_days["__Day"] = pd.Categorical(df_days[day_col], categories=order, ordered=True)

    def _agg_day(g):
        r = outcome_rates_from(g)
        net_rr, ex_rr = _rr_stats(g)
        return pd.Series(
            {
                "Trades": len(g),
                "Win %": r["win_rate"],
                "BE %": r["be_rate"],
                "Loss %": r["loss_rate"],
                "Net PnL (R)": net_rr,
                "Expectancy (R)": ex_rr,
            }
        )

    perf = (
        df_days.groupby("__Day")
        .apply(_agg_day)
        .reset_index()
        .rename(columns={"__Day": "Day"})
    )

    day_df = perf.sort_values("Day")
    render_day_performance_table(day_df, title="Day Performance (Mon–Fri)")
    st.markdown("</div>", unsafe_allow_html=True)


# ---------- NEW: GAP Alignment tab -------------------------------------------
def _gap_alignment_tab(f: pd.DataFrame, show_table):
    """
    GAP Alignment tab:
    Groups by 'Gap Alignment' and shows Trades / Win % / BE % / Loss % / Net PnL (R).
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty or "Gap Alignment" not in f.columns:
        st.info("No GAP Alignment data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()
    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    counted["Gap Alignment"] = counted["Gap Alignment"].astype(str).str.strip()
    counted = counted[~counted["Gap Alignment"].isin(["", "nan", "NaN", "None"])]
    if counted.empty:
        st.info("No counted outcomes with GAP Alignment set.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []
    for ga, group in counted.groupby("Gap Alignment"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rows.append(
            dict(
                Entry_Model=ga,
                Trades=len(group),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rows:
        df_gap = pd.DataFrame(rows).sort_values("Entry_Model").reset_index(drop=True)
        render_entry_model_table(df_gap, title="GAP Alignment")
    else:
        st.info("No GAP Alignment stats available.")

    st.markdown("</div>", unsafe_allow_html=True)


# ---------- NEW: Target RR tab -----------------------------------------------
def _parse_target_rr_label(label: str):
    """
    Parse Target RR label strings like:
      - "1-2RR"  -> 1.5
      - "10+RR"  -> 10
      - "4RR"    -> 4
    Used only for sorting buckets nicely.
    """
    if label is None:
        return None
    s = str(label).lower().replace("rr", "").strip()
    if not s:
        return None
    s = s.replace(" ", "")

    # range: a-b
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)[-–]([+-]?\d+(?:\.\d+)?)$", s)
    if m:
        a = float(m.group(1))
        b = float(m.group(2))
        return (a + b) / 2.0

    # plus: a+
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\+$", s)
    if m:
        return float(m.group(1))

    # plain numeric
    try:
        return float(s)
    except Exception:
        return None


def _target_rr_tab(f: pd.DataFrame, show_table):
    """
    Risk to Reward tab:
    Groups by 'Target RR' and shows Trades / Win % / BE % / Loss % / Net PnL (R).
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty or "Targeted RR" not in f.columns:
        st.info("No Target RR data in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()

    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    counted["Targeted RR"] = counted["Targeted RR"].astype(str).str.strip()
    counted = counted[counted["Targeted RR"] != ""]
    if counted.empty:
        st.info("No counted outcomes with Target RR set.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []
    for target, group in counted.groupby("Targeted RR"):
        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)
        rows.append(
            dict(
                Target_RR=target,
                Trades=len(group),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rows:
        df_rr = pd.DataFrame(rows)

        # Nice numeric ordering of buckets (1-2RR, 2-3RR, ... 10+RR)
        df_rr["_sort_num"] = df_rr["Target_RR"].apply(_parse_target_rr_label)
        df_rr = df_rr.sort_values(
            ["_sort_num", "Target_RR"], na_position="last"
        ).reset_index(drop=True)
        df_rr = df_rr.drop(columns=["_sort_num"])

        # Reuse entry model renderer by mapping label column
        df_rr = df_rr.rename(columns={"Target_RR": "Entry_Model"})
        render_entry_model_table(df_rr, title="Risk to Reward")
    else:
        st.info("No Target RR stats available.")

    st.markdown("</div>", unsafe_allow_html=True)


# ---------- NEW: Conditions tab (ETF vs HTF) ---------------------------------
def _conditions_tab(f: pd.DataFrame, show_table):
    """
    Conditions tab:
    Uses 'Conditions ETF' and 'Conditions HTF' (e.g. Trending/Ranging)
    and shows performance for each combination.
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)

    if f is None or f.empty:
        st.info("No trades for current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if "Conditions ETF" not in f.columns and "Conditions HTF" not in f.columns:
        st.info("No Conditions ETF/HTF columns in current data.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    g = f.copy()
    c_etf = "Conditions ETF" if "Conditions ETF" in g.columns else None
    c_htf = "Conditions HTF" if "Conditions HTF" in g.columns else None

    # Normalise empties
    if c_etf:
        g[c_etf] = g[c_etf].astype(str).str.strip()
        g[c_etf] = g[c_etf].replace({"": None})
    if c_htf:
        g[c_htf] = g[c_htf].astype(str).str.strip()
        g[c_htf] = g[c_htf].replace({"": None})

    counted = g[g["Outcome"].isin(["Win", "BE", "Loss"])]
    if c_etf and c_htf:
        mask_has_any = counted[c_etf].notna() | counted[c_htf].notna()
    elif c_etf:
        mask_has_any = counted[c_etf].notna()
    else:
        mask_has_any = counted[c_htf].notna()

    counted = counted[mask_has_any]
    if counted.empty:
        st.info("No Conditions ETF/HTF values in current slice.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows = []

    if c_etf and c_htf:
        group_cols = [c_etf, c_htf]
    elif c_etf:
        group_cols = [c_etf]
    else:
        group_cols = [c_htf]

    for key, group in counted.groupby(group_cols):
        if not isinstance(key, tuple):
            key = (key,)
        etf_val = key[0] if c_etf else None
        htf_val = key[1] if (c_etf and c_htf and len(key) > 1) else (key[0] if (not c_etf and c_htf) else None)

        r = outcome_rates_from(group)
        net_rr, ex_rr = _rr_stats(group)

        # Multi-line label: ETF on first line, HTF on second line
        label_lines = []
        if c_etf:
            label_lines.append(f"ETF: {etf_val or 'N/A'}")
        if c_htf:
            label_lines.append(f"HTF: {htf_val or 'N/A'}")
        label = "<br>".join(label_lines) if label_lines else "Conditions"

        rows.append(
            dict(
                Entry_Model=label,
                ETF=etf_val or "N/A",
                HTF=htf_val or "N/A",
                Trades=len(group),
                **{
                    "Win %": r["win_rate"],
                    "BE %": r["be_rate"],
                    "Loss %": r["loss_rate"],
                    "Net PnL (R)": net_rr,
                    "Expectancy (R)": ex_rr,
                },
            )
        )

    if rows:
        cond_df = (
            pd.DataFrame(rows)
        )

        # Clean ordering: ETF then HTF in a fixed order
        for col_name in ["ETF", "HTF"]:
            if col_name in cond_df.columns:
                cond_df[col_name] = cond_df[col_name].fillna("N/A")
                cond_df[col_name] = pd.Categorical(
                    cond_df[col_name],
                    categories=["Trending", "Ranging", "N/A"],
                    ordered=True,
                )

        cond_df = cond_df.sort_values(
            ["ETF", "HTF", "Win %"],
            ascending=[True, True, False],
        ).reset_index(drop=True)

        render_entry_model_table(cond_df, title="Conditions")
    else:
        st.info("No conditions stats available.")

    st.markdown("</div>", unsafe_allow_html=True)


def _coach_tab(f: pd.DataFrame):
    # kept for future use; not referenced in render_all_tabs
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("## Edge Coach (disabled for now)")
    st.info("Coach is hidden for now.")
    st.markdown("</div>", unsafe_allow_html=True)


# ----------------------- Data tab helpers (ALL instruments, rows of 3) --------
def _render_data_completeness_by_instrument(f_all: pd.DataFrame):
    """
    Show completeness cards for EVERY instrument with at least one row.
    Arranged in rows of 3 cards. Uses existing app styles (kpi/label/value/muted).
    """
    st.markdown("### Data Completeness by Instrument")

    if f_all is None or f_all.empty:
        st.info("No rows for the current filters.")
        return

    # Normalize/derive Instrument
    g = _ensure_instrument_column(f_all.copy())
    if "Instrument" not in g.columns:
        st.info("No instrument-like column found (looked for Instrument/Pair/Symbol/Ticker).")
        return

    # Drop blanks
    g["Instrument"] = g["Instrument"].astype(str).str.strip()
    g = g[g["Instrument"] != ""]
    if g.empty:
        st.info("No instrument values present.")
        return

    # Define completeness robustly
    if "Is Complete" in g.columns:
        g["__complete"] = g["Is Complete"].fillna(False).astype(bool)
    elif {"Outcome Canonical", "Closed RR Num"} <= set(g.columns):
        has_outcome = g["Outcome Canonical"].isin(["Win", "BE", "Loss"])
        has_rr = g["Closed RR Num"].notna()
        has_date = g["Date"].notna() if "Date" in g.columns else True
        g["__complete"] = (has_date & has_outcome & has_rr).fillna(False)
    else:
        has_closed_rr = g["Closed RR"].notna() if "Closed RR" in g.columns else False
        has_result = (
            g["Result"].astype(str).str.strip().ne("").fillna(False)
            if "Result" in g.columns
            else False
        )
        has_pnl = g["PnL"].notna() if "PnL" in g.columns else False
        has_date = g["Date"].notna() if "Date" in g.columns else False
        g["__complete"] = (has_date & (has_closed_rr | has_result | has_pnl)).fillna(False)

    # Aggregate per instrument
    agg = (
        g.groupby("Instrument", dropna=False)
        .agg(total=("Instrument", "size"), complete=("__complete", "sum"))
        .reset_index()
    )
    agg["incomplete"] = agg["total"] - agg["complete"]

    # Sort alphabetically for predictable layout (or by total desc)
    agg = agg.sort_values(["Instrument"]).reset_index(drop=True)

    # Render cards 3-per-row
    per_row = 3
    for i in range(0, len(agg), per_row):
        chunk = agg.iloc[i : i + per_row]
        cols = st.columns(len(chunk))
        for col, (_, r) in zip(cols, chunk.iterrows()):
            with col:
                label = _asset_label(r["Instrument"])
                st.markdown(
                    f"""
                    <div class='kpi'>
                      <div class='label'>{label}</div>
                      <div class='value' style='color:#4800ff'>{int(r['total'])}</div>
                      <div class='muted'>Complete: <b>{int(r['complete'])}</b></div>
                      <div class='muted'>Incomplete: <b>{int(r['incomplete'])}</b></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ----------------------- Data tab (uses FILTERED-ALL) -----------------------
def _data_tab(f_all: pd.DataFrame, show_table):
    """
    Show counts of data entries per Instrument with 'Complete' vs 'Incomplete' totals.
    Displays ALL instruments present, in rows of 3 cards.
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)
    _render_data_completeness_by_instrument(f_all)
    st.markdown("</div>", unsafe_allow_html=True)


# ----------------------- PATCH: Connect Notion templates UI -------------------
def render_connect_notion_templates_ui():
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("## Connect Notion / Templates")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### My Template")
        p1 = Path("assets/templates/my_template.csv")
        if p1.exists():
            st.download_button(
                "⬇️ Download My Template (CSV)",
                data=p1.read_bytes(),
                file_name="my_template.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.warning("Missing: assets/templates/my_template.csv")

    with c2:
        st.markdown("### TradingPools Template")
        p2 = Path("assets/templates/tradingpools_template.csv")
        if p2.exists():
            st.download_button(
                "⬇️ Download TradingPools Template (CSV)",
                data=p2.read_bytes(),
                file_name="tradingpools_template.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.warning("Missing: assets/templates/tradingpools_template.csv")

    st.divider()
    st.subheader("Upload your filled template")
    up = st.file_uploader(
        "CSV/TSV/XLSX supported. Both templates work.",
        type=["csv", "tsv", "xlsx", "xls"],
        key="upload_templates_dual",
    )

    if up:
        uploads = Path("uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        fpath = uploads / up.name
        with open(fpath, "wb") as f:
            f.write(up.getbuffer())

        df, mapping_name = adapt_auto(fpath, "config/templates")
        if mapping_name:
            st.success(f"Detected template: **{mapping_name}**")
        else:
            st.warning(
                "No mapping detected. Add a JSON mapping under config/templates/ if needed."
            )

        # quick sanity checks
        issues = []
        for col in ["Date", "Pair", "Outcome", "Closed RR", "Is Complete"]:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")
        if "Outcome" in df.columns:
            bad = ~df["Outcome"].isin(["Win", "BE", "Loss"]) & df["Outcome"].notna()
            if bad.any():
                issues.append(
                    "Unexpected Outcome values: "
                    + str(list(df.loc[bad, "Outcome"].astype(str).unique()[:5]))
                )

        if issues:
            st.info("Checks:\n\n- " + "\n- ".join(issues))

        st.dataframe(df.head(25), use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ----------------------- UPDATED render_all_tabs (with new tabs) ----
def render_all_tabs(f: pd.DataFrame, df_all: pd.DataFrame, styler, show_table):
    # completion-aware slice
    f_perf = _prep_perf_df(f)
    df_all_safe = df_all.copy() if df_all is not None else df_all

    # Dashboard tabs:
    (
        t1,
        t2,
        t3,
        t4,
        t5,
        t6,
        t7,
        t8,
    ) = st.tabs(
        [
            "Growth",
            "Entry Models",
            "Confluence",
            "Assets",
            "Sessions",
            "Days",
            "Conditions",
            "Data",
        ]
    )

    with t1:
        _growth_tab(f_perf, df_all_safe, styler)

    with t2:
        _entry_models_tab(f_perf, show_table)

    with t3:
        _confluences_tab(f_perf, show_table)

    with t4:
        _instruments_tab(f_perf, show_table)

    with t5:
        _sessions_tab(f_perf, show_table)

    with t6:
        _time_days_tab(f_perf, show_table)  # Days only (Mon–Fri)

    with t7:
        _conditions_tab(f_perf, show_table)

    with t8:
        _data_tab(df_all_safe, show_table)  # filtered-all completeness