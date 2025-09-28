from __future__ import annotations 
import os
from pathlib import Path
import base64
import re
import pandas as pd
import streamlit as st

# ───────────────────────────── Page config / assets ───────────────────────────
ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets"
FAVICON = ASSETS_DIR / "edge_favicon.png"
PAGE_ICON = str(FAVICON) if FAVICON.exists() else None

st.set_page_config(
    page_title="Edge Analysis",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",  # start expanded
)

# ───────────────────────────── Secrets helper ─────────────────────────────────
def _secret_or_env(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

# Quick, safe secrets check (temporary; remove later if you like)
with st.expander("🔐 Secrets diagnostics (temporary)", expanded=False):
    keys = list(getattr(st, "secrets", {}).keys()) if hasattr(st, "secrets") else []
    st.write("Keys found:", keys)
    for k in ["NOTION_TOKEN", "DATABASE_ID", "OPENAI_API_KEY"]:
        v = _secret_or_env(k)
        masked = (v[:4] + "…" + v[-4:]) if isinstance(v, str) and len(v) > 8 else (v if v else None)
        st.write(f"{k}:", masked)
    missing = [k for k in ["NOTION_TOKEN", "DATABASE_ID"] if not _secret_or_env(k)]
    if missing:
        st.warning(
            "Missing secrets: " + ", ".join(missing) +
            ". Ensure they're in either %USERPROFILE%\\.streamlit\\secrets.toml "
            "or your project .streamlit\\secrets.toml and that you're starting Streamlit from the project root."
        )

# --- package helpers ---
from edge_analysis.data.notion_adapter import load_trades_from_notion
from edge_analysis.core.constants import MODEL_SET, INSTRUMENT_CANONICAL, SESSION_CANONICAL
from edge_analysis.core.parsing import (
    infer_instrument, normalize_session, build_models_list, parse_closed_rr,
    classify_outcome_from_fields, normalize_account_group, build_duration_bin,
)
from edge_analysis.ui.theme import apply_theme, inject_global_css, inject_header
from edge_analysis.ui.components import show_light_table
from edge_analysis.ui.tabs import render_all_tabs, generate_overall_stats


# ───────────────────────────── Data loading / cleaning ────────────────────────
@st.cache_data(show_spinner=True)
def load_live_df() -> pd.DataFrame:
    token = _secret_or_env("NOTION_TOKEN")
    dbid = _secret_or_env("DATABASE_ID")
    if not (token and dbid):
        st.warning("Add NOTION_TOKEN and DATABASE_ID to `.streamlit/secrets.toml`")
        return pd.DataFrame()

    raw = load_trades_from_notion(token, dbid)
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]

    # numeric coercions
    if "Closed RR" in df.columns:
        df["Closed RR"] = df["Closed RR"].apply(parse_closed_rr)
    if "PnL" in df.columns:
        df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")

    # datetime & derived
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["DayName"] = df["Date"].dt.day_name()
        df["Hour"] = df["Date"].dt.hour

    # normalized fields
    df["Instrument"] = df["Pair"].apply(infer_instrument) if "Pair" in df.columns else "Unknown"
    df["Session Norm"] = df.get("Session", pd.Series(index=df.index, dtype=object)).apply(normalize_session)

    if "Multi Entry Model Entry" in df.columns:
        df["Entry Models List"] = df.apply(
            lambda r: build_models_list(r.get("Entry Model"), r.get("Multi Entry Model Entry")),
            axis=1,
        )
    else:
        df["Entry Models List"] = df.get("Entry Model", "").apply(lambda v: build_models_list(v, None))

    if "Entry Confluence" in df.columns:
        df["Entry Confluence List"] = (
            df["Entry Confluence"].fillna("").astype(str).apply(
                lambda s: [x.strip() for x in re.split(r"[;,]", s) if x.strip()]
            )
        )
    else:
        df["Entry Confluence List"] = [[] for _ in range(len(df))]

    # outcome
    df["Outcome"] = df.apply(
        lambda r: classify_outcome_from_fields(r.get("Result"), r.get("Closed RR"), r.get("PnL")),
        axis=1,
    )

    # stars, risk, duration, accounts
    if "Rating" in df.columns:
        df["Stars"] = df["Rating"].apply(lambda s: s.count("⭐") if isinstance(s, str) else None)
    if "Risk Management" in df.columns:
        df["Risk %"] = df["Risk Management"].astype(str).str.extract(r'(\d+(?:\.\d+)?)\s*%')[0].astype(float)
    if "Trade Duration" in df.columns:
        df["Trade Duration"] = pd.to_numeric(df["Trade Duration"], errors="coerce")
        df["Duration Bin"] = df["Trade Duration"].apply(build_duration_bin)
    if "Account" in df.columns:
        df["Account Group"] = df["Account"].apply(normalize_account_group)

    # keep likely real trades
    has_date = df.get("Date").notna() if "Date" in df.columns else pd.Series(False, index=df.index)
    has_signal = (
        df.get("PnL").notna()
        | df.get("Closed RR").notna()
        | df.get("Result", "").astype(str).str.strip().ne("")
        | df.get("Entry Model", "").astype(str).str.strip().ne("")
    ).fillna(False)

    return df[has_date & has_signal].copy()


# ───────────────────────────── App ────────────────────────────────────────────
def main() -> None:
    # theme + header
    theme_choice = st.sidebar.selectbox(
        "Theme", ["Light", "Dark"], index=0 if st.session_state.get("ui_theme", "light") == "light" else 1
    )
    styler = apply_theme(theme_choice.lower())
    st.session_state["ui_theme"] = theme_choice.lower()
    inject_global_css()
    inject_header(theme_choice.lower())  # logo

    # Force sidebar always open
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebarCloseButton"] {display: none;}
        [data-testid="stSidebarCollapseButton"] {display: none;} /* hide « button */
        [data-testid="stSidebar"] {transform: none !important; visibility: visible !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

    # load data
    with st.spinner("Fetching trades from Notion…"):
        df = load_live_df()
    if df.empty:
        st.info("No data yet. Add trades or check secrets.")
        return

    # filters
    header_color = "#000" if theme_choice == "Light" else "#fff"
    st.sidebar.markdown(f"<h3 style='color:{header_color}'>Filters</h3>", unsafe_allow_html=True)

    instruments = sorted(df["Instrument"].dropna().unique().tolist())
    instruments = [i for i in instruments if i != "DUMMY ROW"]
    inst_opts = ["All"] + instruments
    sel_inst = st.sidebar.selectbox("Instrument", inst_opts, 0)

    em_opts = ["All"] + MODEL_SET
    sel_em = st.sidebar.selectbox("Entry Model", em_opts, 0)

    sess_opts = ["All"] + sorted(set(SESSION_CANONICAL) | set(df["Session Norm"].dropna().unique()))
    sel_sess = st.sidebar.selectbox("Session", sess_opts, 0)

    # filtering mask (no Account filter)
    mask = pd.Series(True, index=df.index)
    if sel_inst != "All":
        mask &= (df["Instrument"] == sel_inst)
    if sel_em != "All":
        mask &= df["Entry Models List"].apply(lambda lst: sel_em in lst if isinstance(lst, list) else False)
    if sel_sess != "All":
        mask &= (df["Session Norm"] == sel_sess)

    f = df[mask].copy()
    f["PnL_from_RR"] = f["Closed RR"].fillna(0.0)

    # KPI
    stats = generate_overall_stats(f)

    # Avg Closed RR only from wins
    if "Closed RR" in f.columns:
        wins_only = f[f["Outcome"] == "Win"]
        avg_rr_wins = float(wins_only["Closed RR"].mean()) if not wins_only.empty else 0.0
    else:
        avg_rr_wins = 0.0
    total_pnl_rr = float(f["PnL_from_RR"].sum())

    st.markdown('<div class="kpi-grid">', unsafe_allow_html=True)
    for label, value in [
        ("Total Trades", stats["total"]),
        ("Win %", f"{stats['win_rate']:.2f}%"),
        ("BE %", f"{stats['be_rate']:.2f}%"),
        ("Loss %", f"{stats['loss_rate']:.2f}%"),
        ("Avg Closed RR (Wins Only)", f"{avg_rr_wins:.2f}"),
        ("Total PnL (from RR)", f"{total_pnl_rr:,.2f}"),
    ]:
        st.markdown(
            f"<div class='kpi'><div class='label'>{label}</div><div class='value'>{value}</div></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)

    # Tabs
    render_all_tabs(f, df, styler, show_light_table)


if __name__ == "__main__":
    main()
