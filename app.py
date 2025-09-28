from __future__ import annotations
import os
import sys
import base64
from pathlib import Path
import pandas as pd
import streamlit as st

# --- make "src/edge_analysis" importable on Streamlit Cloud ---
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))
# --------------------------------------------------------------

# ───────────────────────────── Page config / assets ───────────────────────────
def _find_assets_dir() -> Path:
    candidates = [
        _ROOT / "assets",
        (_ROOT.parent / "assets"),
        Path("assets").resolve(),
    ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return _ROOT / "assets"

ASSETS_DIR = _find_assets_dir()
FAVICON = ASSETS_DIR / "edge_favicon.png"
PAGE_ICON = str(FAVICON) if FAVICON.exists() else None

st.set_page_config(
    page_title="Edge Analysis",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Force custom favicon
if FAVICON.exists():
    try:
        favicon_b64 = base64.b64encode(FAVICON.read_bytes()).decode()
        st.markdown(
            f"""<link rel="shortcut icon" href="data:image/png;base64,{favicon_b64}">""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass

# ───────────────────────────── Secrets / runtime config ───────────────────────
def _get_query_param(name: str) -> str | None:
    try:
        val = st.query_params.get(name)
        if isinstance(val, list):  # older Streamlit used lists
            return val[0] if val else None
        return val
    except Exception:
        # Fallback for very old Streamlit versions
        try:
            qp = st.experimental_get_query_params()
            if name in qp and qp[name]:
                return qp[name][0]
        except Exception:
            pass
    return None

def _runtime_secret(key: str, default=None):
    """
    Priority:
      1) Per-session overrides set on the Settings page (st.session_state)
      2) URL query params (?notion_token=...&database_id=...)
      3) st.secrets / environment (original 'live notion connected')
    """
    # 1) Session override
    override_key = f"override_{key}"
    val = st.session_state.get(override_key)
    if val:
        return val

    # 2) Query params
    if key == "NOTION_TOKEN":
        qp = _get_query_param("notion_token")
        if qp:
            return qp
    if key == "DATABASE_ID":
        qp = _get_query_param("database_id")
        if qp:
            return qp

    # 3) Secrets / env
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

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
def load_live_df(token: str | None, dbid: str | None) -> pd.DataFrame:
    if not (token and dbid):
        # Soft hint shown in Dashboard only when no creds present
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
        import re as _re
        df["Entry Confluence List"] = (
            df["Entry Confluence"].fillna("").astype(str).apply(
                lambda s: [x.strip() for x in _re.split(r"[;,]", s) if x.strip()]
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

# ───────────────────────────── Settings page (per-session creds) ──────────────
def render_settings_page():
    st.title("🔧 Settings")
    st.write("Use your **own Notion credentials** for this session only. These are not saved to the server.")

    # Prefill from current session/query/secrets (masked)
    current_token = _runtime_secret("NOTION_TOKEN")
    current_dbid = _runtime_secret("DATABASE_ID")

    c1, c2 = st.columns(2)
    with c1:
        notion_token = st.text_input(
            "Notion Token",
            value="" if not current_token else current_token,
            type="password",
            help="Paste your Notion internal integration token (starts with 'secret_' or 'ntn_').",
        )
    with c2:
        database_id = st.text_input(
            "Database ID",
            value="" if not current_dbid else current_dbid,
            help="32-char Notion database/page ID (no dashes).",
        )

    a, b, c = st.columns([1,1,2])
    with a:
        if st.button("Use for this session"):
            if notion_token and database_id:
                st.session_state["override_NOTION_TOKEN"] = notion_token.strip()
                st.session_state["override_DATABASE_ID"] = database_id.strip()
                st.success("Session credentials set. Go back to Dashboard.")
            else:
                st.error("Please provide both Notion Token and Database ID.")
    with b:
        if st.button("Clear session credentials"):
            st.session_state.pop("override_NOTION_TOKEN", None)
            st.session_state.pop("override_DATABASE_ID", None)
            st.info("Session overrides cleared.")

    st.markdown("---")
    st.caption("Tip: you can also prefill via URL query params: `?notion_token=...&database_id=...`")

# ───────────────────────────── App (Dashboard) ────────────────────────────────
def render_dashboard():
    # theme + header
    theme_choice = st.sidebar.selectbox(
        "Theme", ["Light", "Dark"], index=0 if st.session_state.get("ui_theme", "light") == "light" else 1
    )
    from edge_analysis.ui.theme import apply_theme, inject_global_css, inject_header  # (reimport safe)
    styler = apply_theme(theme_choice.lower())
    st.session_state["ui_theme"] = theme_choice.lower()
    inject_global_css()
    inject_header(theme_choice.lower())

    # Force sidebar always open & hide collapse button
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebarCloseButton"] {display: none;}
        [data-testid="stSidebarCollapseButton"] {display: none;}
        [data-testid="stSidebar"] {transform: none !important; visibility: visible !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

    # Resolve credentials (session/query/secrets/env)
    token = _runtime_secret("NOTION_TOKEN")
    dbid = _runtime_secret("DATABASE_ID")

    with st.spinner("Fetching trades from Notion…"):
        df = load_live_df(token, dbid)

    if not (token and dbid):
        st.warning("Add Notion credentials in **Settings** to load your data.")
        return
    if df.empty:
        st.info("No data yet. Add trades, adjust filters, or check credentials.")
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

# ───────────────────────────── Router (Dashboard / Settings) ──────────────────
def main() -> None:
    # Simple page switcher in sidebar
    st.sidebar.markdown("## Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Settings"], index=0)

    if page == "Settings":
        render_settings_page()
    else:
        render_dashboard()

if __name__ == "__main__":
    main()
