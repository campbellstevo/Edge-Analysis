from __future__ import annotations
import os
import sys
import base64
from pathlib import Path
import pandas as pd
import streamlit as st

# ---------------------------- import path for src/ ----------------------------
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))

# ------------------------------- brand colors --------------------------------
BRAND_PURPLE = "#4800ff"

# --------------------------- Page config / assets -----------------------------
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

# Tab favicon (extra nudge)
if FAVICON.exists():
    try:
        favicon_b64 = base64.b64encode(FAVICON.read_bytes()).decode()
        st.markdown(
            f"""<link rel="shortcut icon" href="data:image/png;base64,{favicon_b64}">""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass

# ------------------------ Secrets / runtime helpers ---------------------------
def _get_query_param(name: str) -> str | None:
    try:
        val = st.query_params.get(name)
        if isinstance(val, list):
            return val[0] if val else None
        return val
    except Exception:
        try:
            qp = st.experimental_get_query_params()
            if name in qp and qp[name]:
                return qp[name][0]
        except Exception:
            pass
    return None

def _runtime_secret(key: str, default=None):
    """Priority: session override -> URL query param -> secrets/env."""
    override_key = f"override_{key}"
    val = st.session_state.get(override_key)
    if val:
        return val

    if key == "NOTION_TOKEN":
        qp = _get_query_param("notion_token")
        if qp:
            return qp
    if key == "DATABASE_ID":
        qp = _get_query_param("database_id")
        if qp:
            return qp

    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

# ------------------------------- package imports ------------------------------
from edge_analysis.data.notion_adapter import load_trades_from_notion
from edge_analysis.core.constants import MODEL_SET, INSTRUMENT_CANONICAL, SESSION_CANONICAL
from edge_analysis.core.parsing import (
    infer_instrument, normalize_session, build_models_list, parse_closed_rr,
    classify_outcome_from_fields, normalize_account_group, build_duration_bin,
)
from edge_analysis.ui.theme import apply_theme, inject_global_css, inject_header
from edge_analysis.ui.components import show_light_table
from edge_analysis.ui.tabs import render_all_tabs, generate_overall_stats

# --------------------------- UI helpers (NEW) ---------------------------------
def _inject_dropdown_css():
    """
    Global: make all Streamlit selectboxes look like non-editable button dropdowns,
    hide the text caret, and use a bold chevron icon (not a triangle).
    """
    # Inline SVG chevron (dark ink). NOTE: # must be %23 inside data-URL.
    chevron_svg = (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
        "<path d='M6 9l6 6 6-6' fill='none' stroke='%230f172a' stroke-width='2' "
        "stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
    )

    st.markdown(
        f"""
        <style>
        :root {{
            --ea-brand: {BRAND_PURPLE};
        }}
        /* Unify ALL selectboxes across app (sidebar + main) */
        /* PATCH: restrict to the select's internal search input so normal text inputs remain editable */
        [data-baseweb="select"] input[aria-autocomplete="list"] {{
            caret-color: transparent !important;   /* no flashing text caret */
            pointer-events: none !important;       /* not editable */
            user-select: none !important;
            opacity: 0 !important;
            width: 0 !important;
            min-width: 0 !important;
        }}
        [data-baseweb="select"] [role="combobox"],
        [data-baseweb="select"] > div {{
            cursor: pointer !important;
        }}
        /* Hide Streamlit/BaseWeb built-in dropdown icon to avoid double-arrows */
        [data-baseweb="select"] svg {{
            display: none !important;
        }}
        /* Add our own bold chevron */
        [data-baseweb="select"] > div {{
            position: relative !important;
        }}
        [data-baseweb="select"] > div::after {{
            content: "";
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            width: 16px;
            height: 16px;
            background-image: url("{chevron_svg}");
            background-repeat: no-repeat;
            background-size: 16px 16px;
            opacity: 0.9;
            pointer-events: none;
        }}

        /* PATCH SAFETY: ensure normal text/password/textarea inputs stay fully interactive */
        [data-testid="stTextInput"] input,
        [data-testid="stPassword"] input,
        [data-testid="stTextArea"] textarea {{
            pointer-events: auto !important;
            opacity: 1 !important;
            width: 100% !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------- data loading/cleaning ---------------------------
@st.cache_data(show_spinner=True)
def load_live_df(token: str | None, dbid: str | None) -> pd.DataFrame:
    if not (token and dbid):
        return pd.DataFrame()

    raw = load_trades_from_notion(token, dbid)
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]

    if "Closed RR" in df.columns:
        df["Closed RR"] = df["Closed RR"].apply(parse_closed_rr)
    if "PnL" in df.columns:
        df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["DayName"] = df["Date"].dt.day_name()
        df["Hour"] = df["Date"].dt.hour

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

    df["Outcome"] = df.apply(
        lambda r: classify_outcome_from_fields(r.get("Result"), r.get("Closed RR"), r.get("PnL")),
        axis=1,
    )

    if "Rating" in df.columns:
        df["Stars"] = df["Rating"].apply(lambda s: s.count("⭐") if isinstance(s, str) else None)
    if "Risk Management" in df.columns:
        df["Risk %"] = df["Risk Management"].astype(str).str.extract(r'(\d+(?:\.\d+)?)\s*%')[0].astype(float)
    if "Trade Duration" in df.columns:
        df["Trade Duration"] = pd.to_numeric(df["Trade Duration"], errors="coerce")
        df["Duration Bin"] = df["Trade Duration"].apply(build_duration_bin)
    if "Account" in df.columns:
        df["Account Group"] = df["Account"].apply(normalize_account_group)

    has_date = df.get("Date").notna() if "Date" in df.columns else pd.Series(False, index=df.index)
    has_signal = (
        df.get("PnL").notna()
        | df.get("Closed RR").notna()
        | df.get("Result", "").astype(str).str.strip().ne("")
        | df.get("Entry Model", "").astype(str).str.strip().ne("")
    ).fillna(False)

    return df[has_date & has_signal].copy()

# ------------------------------- Connect page --------------------------------
def render_connect_page():
    """
    Light settings page (same look as Dashboard).
    """
    # Ensure same theme shell and header as dashboard
    styler = apply_theme()   # locked to light
    inject_global_css()
    inject_header("light")

    # Scoped light overrides for this page
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}

        /* Keep the whole app light on this page as well */
        [data-testid="stAppViewContainer"],
        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stSidebar"] {{
            background: #ffffff !important;
        }}

        /* Sidebar text and content readable on light */
        [data-testid="stSidebar"] * {{
            color: #0f172a !important;
        }}

        /* Settings wrapper scope */
        .connect-scope, .connect-scope * {{
            color: #0f172a !important;
        }}

        /* Inputs (force light text and border even on focus/hover) */
        .connect-scope [data-testid="stTextInput"] input,
        .connect-scope [data-testid="stPassword"] input,
        .connect-scope [data-testid="stTextArea"] textarea {{
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 10px !important;
            box-shadow: none !important;
        }}
        .connect-scope [data-testid="stTextInput"] input:focus,
        .connect-scope [data-testid="stPassword"] input:focus,
        .connect-scope [data-testid="stTextArea"] textarea:focus {{
            border: 1px solid var(--brand) !important;
            box-shadow: 0 0 0 2px rgba(72,0,255,0.12) !important;
            outline: none !important;
        }}
        .connect-scope ::placeholder {{
            color: #64748b !important;
            opacity: 1 !important;
        }}
        /* Eye icon area */
        .connect-scope [data-testid="stTextInput"] button {{
            background: #ffffff !important;
            border-left: 1px solid #e5e7eb !important;
        }}
        .connect-scope [data-testid="stTextInput"] button svg {{ color:#0f172a !important; }}

        /* Buttons */
        .connect-scope .stButton > button {{
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 12px !important;
            padding: 0.5rem 1rem !important;
            box-shadow: none !important;
            cursor: pointer !important;
        }}
        .connect-scope .stButton > button:hover,
        .connect-scope .stButton > button:focus {{
            background: #f9fafb !important;
            color: #0f172a !important;
            border-color: #e5e7eb !important;
        }}

        /* Expander headers - light; open area stays white */
        .connect-scope [data-testid="stExpander"] > details {{
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 12px !important;
            overflow: hidden !important;
        }}
        .connect-scope [data-testid="stExpander"] summary,
        .connect-scope [data-testid="stExpander"] div[role="button"] {{
            background: #f3f4f6 !important;
            color: #0f172a !important;
            border-bottom: 1px solid #e5e7eb !important;
            padding: .65rem .9rem !important;
        }}
        .connect-scope [data-testid="stExpander"] > details[open] > div {{
            background: #ffffff !important;
            padding: .75rem .9rem !important;
        }}

        /* Inline code pills in guide - light */
        .connect-scope code {{
            background: #eef2ff !important;
            color: #0f172a !important;
            padding: 2px 6px;
            border-radius: 6px;
        }}

        /* Success/info alerts readable */
        .connect-scope .stAlert {{
            background: #ecfdf5 !important;
            border: 1px solid #bbf7d0 !important;
            color: #064e3b !important;
            border-radius: 12px !important;
        }}
        .connect-scope .stAlert * {{ color: #064e3b !important; }}

        /* Smaller logo so content sits higher */
        .header-logo-img {{
            transform: scale(0.7);
            transform-origin: center;
            margin-bottom: 0.25rem !important;
        }}

        /* Kill stray legacy dark boxes */
        .css-1d391kg, .css-1kyxreq, .css-1avcm0n {{
            background: transparent !important;
        }}

        /***** Visual walkthrough styles *****/
        .ea-walk {{ font-size: 15.5px; line-height: 1.55; }}
        .ea-walk h4 {{
          margin: 0.75rem 0 0.5rem 0; 
          font-size: 16px; 
          font-weight: 800; 
          color: #0f172a;
        }}
        .ea-quicklinks {{
          display: flex; gap: 8px; flex-wrap: wrap; margin: 2px 0 10px 0;
        }}
        .ea-link {{
          display: inline-flex; align-items: center; gap: 6px;
          padding: 6px 10px; border: 1px solid #e5e7eb; border-radius: 10px;
          background: #ffffff; color: #0f172a; text-decoration: none; font-weight: 600;
        }}
        .ea-link:hover {{ background: #f9fafb; }}
        .ea-steps {{ 
          display: grid; 
          grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); 
          gap: 10px; 
          align-items: stretch;
        }}
        .ea-step {{
          background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
          padding: 10px 12px; display: flex; gap: 10px; align-items: flex-start;
          /* WRAP FIX: prevent overhanging text */
          overflow: hidden; 
        }}
        .ea-num {{
          width: 26px; height: 26px; flex: 0 0 26px; border-radius: 8px;
          display: inline-flex; align-items: center; justify-content: center;
          font-weight: 800; background: #eef2ff; color: var(--brand);
        }}
        /* WRAP FIX: let the text block shrink and wrap inside the card */
        .ea-step > div {{
          min-width: 0;                   /* allow flex child to shrink */
          white-space: normal;            /* ensure multi-line layout */
          overflow-wrap: anywhere;        /* modern wrapping for long tokens */
          word-break: break-word;         /* fallback wrapping */
        }}
        .ea-mono {{ 
          background: #eef2ff; padding: 2px 6px; border-radius: 6px; 
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; 
          /* WRAP FIX: allow long URLs/IDs to break mid-token */
          overflow-wrap: anywhere; 
          word-break: break-all;
        }}
        .ea-check, .ea-troubleshoot {{
          margin-top: 8px; padding: 10px 12px; border-radius: 12px; 
          border: 1px solid #e5e7eb; background: #ffffff;
        }}
        .ea-list {{ margin: 6px 0 0 0; padding-left: 18px; }}
        .ea-kbd {{ padding: 1px 6px; border: 1px solid #e5e7eb; border-bottom-width: 2px; border-radius: 6px; background: #fff; font-weight: 700; }}

        /* >>> PATCH: make the 32-character ID segment purple & bold <<< */
        .ea-id {{
          color: var(--brand);
          font-weight: 800;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="connect-scope">', unsafe_allow_html=True)

        st.title("Connect Notion")
        st.write(
            "Use your **own Notion credentials** for this session only. "
            "These are **not** saved on any server."
        )

        # --- NEW: Visual walkthrough (replaces old quick guide) ---
        with st.expander("Visual walkthrough", expanded=True):
            st.markdown(
                """
                <div class="ea-walk">
                  <div class="ea-quicklinks">
                    <a class="ea-link" href="https://www.notion.so/my-integrations" target="_blank">🔗 Open Notion Integrations</a>
                    <a class="ea-link" href="https://www.notion.so" target="_blank">🏠 Open Notion</a>
                  </div>

                  <h4>🔑 Create your Notion token</h4>
                  <div class="ea-steps">
                    <div class="ea-step"><span class="ea-num">1</span><div><strong>Go to</strong> <span class="ea-mono">notion.com/my-integrations</span> → click <strong>+ New integration</strong>.</div></div>
                    <div class="ea-step"><span class="ea-num">2</span><div><strong>Name it</strong> (e.g., <strong>Edge Analysis</strong>) and pick your workspace.</div></div>
                    <div class="ea-step"><span class="ea-num">3</span><div>Under <strong>Capabilities</strong>, enable <strong>Read content</strong> → <strong>Submit</strong>.</div></div>
                    <div class="ea-step"><span class="ea-num">4</span><div><strong>Copy</strong> the <em>Internal Integration Token</em> (starts with <span class="ea-mono">secret_</span>). That’s your <strong>Notion Token</strong>.</div></div>
                  </div>

                  <h4>🗂️ Get your Database ID</h4>
                  <div class="ea-steps">
                    <div class="ea-step"><span class="ea-num">1</span><div>Open your database. If it’s inline, choose <strong>Open as page</strong>.</div></div>
                    <div class="ea-step"><span class="ea-num">2</span><div>Click <strong>Share</strong> → <strong>Connect to / Add connections</strong> → choose your integration (e.g., <em>Edge Analysis</em>).</div></div>
                    <div class="ea-step"><span class="ea-num">3</span><div>
                      Click the <strong>⋯</strong> (top-right) → <strong>Copy link</strong>. The URL looks like:<br>
                      <span class="ea-mono">https://www.notion.so/My-DB-Name-<span class="ea-id">12345678abcd1234ef567890abcd1234</span>?v=...</span><br>
                      The 32-character part before <span class="ea-mono">?v=</span> is your <strong>Database ID</strong> (dashes are fine).
                    </div></div>
                  </div>

                  <div class="ea-check">
                    <strong>✅ Quick checklist</strong>
                    <ul class="ea-list">
                      <li>Token starts with <span class="ea-mono">secret_</span></li>
                      <li>Database is <strong>Connected</strong> to your integration via <strong>Share → Connect</strong></li>
                      <li>Have a 32-character <strong>Database ID</strong></li>
                    </ul>
                  </div>

                  <div class="ea-troubleshoot">
                    <strong>🛠️ Troubleshooting</strong>
                    <ul class="ea-list">
                      <li>Don’t see <span class="ea-kbd">Connect to</span>? Duplicate the DB to a workspace you own.</li>
                      <li>No ID in the link? Make sure it’s a <strong>full page</strong> database, then copy link again.</li>
                    </ul>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        current_token = _runtime_secret("NOTION_TOKEN")
        current_dbid = _runtime_secret("DATABASE_ID")

        c1, c2 = st.columns(2)
        with c1:
            notion_token = st.text_input(
                "Notion Token",
                value="" if not current_token else current_token,
                type="password",
                key="settings_notion_token",
            )
        with c2:
            database_id = st.text_input(
                "Database ID",
                value="" if not current_dbid else current_dbid,
                key="settings_database_id",
            )

        a, b, _ = st.columns([1, 1, 2])
        with a:
            if st.button("Use for this session", key="btn_use_session"):
                if notion_token and database_id:
                    st.session_state["override_NOTION_TOKEN"] = notion_token.strip()
                    st.session_state["override_DATABASE_ID"] = database_id.strip()
                    st.success("All set! Switch to the Dashboard.")
                else:
                    st.error("Please provide both Notion Token and Database ID.")
        with b:
            if st.button("Clear session credentials", key="btn_clear_session"):
                st.session_state.pop("override_NOTION_TOKEN", None)
                st.session_state.pop("override_DATABASE_ID", None)
                st.info("Session overrides cleared.")

        st.caption("Tip: you can also prefill via URL query params: `?notion_token=...&database_id=...`")
        st.markdown('</div>', unsafe_allow_html=True)

# -------------------------------- Dashboard -----------------------------------
def render_dashboard():
    # Purple accent banner text
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}
        .live-banner {{
            text-align: center;
            margin: -8px 0 16px 0;
            font-weight: 800;
            font-size: 22px;
            color: var(--brand);
        }}

        /* Ensure sidebar is light and text is black on Dashboard */
        [data-testid="stSidebar"] {{
            background: #ffffff !important;
        }}
        [data-testid="stSidebar"] * {{
            color: #0f172a !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    styler = apply_theme()   # locked to light
    inject_global_css()
    inject_header("light")

    token = _runtime_secret("NOTION_TOKEN")
    dbid = _runtime_secret("DATABASE_ID")

    with st.spinner("Fetching trades from Notion…"):
        df = load_live_df(token, dbid)

    st.markdown("<div class='live-banner'>Live Notion Connected</div>", unsafe_allow_html=True)

    if not (token and dbid):
        st.warning("Add Notion credentials in **Settings → Connect Notion** to load your data.")
        return
    if df.empty:
        st.info("No data yet. Add trades, adjust filters, or check credentials.")
        return

    # ---------------- Sidebar Filters (button-style dropdowns) -----------------
    st.sidebar.markdown("### Filters")

    instruments = sorted(df["Instrument"].dropna().unique().tolist())
    instruments = [i for i in instruments if i != "DUMMY ROW"]

    # Display label mapping: Gold -> GOLD (value still 'Gold')
    def _inst_label(v: str) -> str:
        return "GOLD" if v == "Gold" else v

    inst_opts = ["All"] + instruments
    sel_inst = st.sidebar.selectbox(
        "Instrument",
        inst_opts,
        index=0,
        format_func=_inst_label,
        key="filters_inst_select",
    )

    em_opts = ["All"] + MODEL_SET
    sel_em = st.sidebar.selectbox(
        "Entry Model",
        em_opts,
        index=0,
        format_func=lambda x: x,
        key="filters_em_select",
    )

    sess_opts = ["All"] + sorted(set(SESSION_CANONICAL) | set(df["Session Norm"].dropna().unique()))
    sel_sess = st.sidebar.selectbox(
        "Session",
        sess_opts,
        index=0,
        format_func=lambda x: x,
        key="filters_sess_select",
    )

    # ---------------- Apply Filters -------------------------------------------
    mask = pd.Series(True, index=df.index)
    if sel_inst != "All":
        mask &= (df["Instrument"] == sel_inst)
    if sel_em != "All":
        mask &= df["Entry Models List"].apply(lambda lst: sel_em in lst if isinstance(lst, list) else False)
    if sel_sess != "All":
        mask &= (df["Session Norm"] == sel_sess)

    f = df[mask].copy()
    f["PnL_from_RR"] = f["Closed RR"].fillna(0.0)

    stats = generate_overall_stats(f)

    # ---------------- KPIs / cards -------------------------------------------
    if "Closed RR" in f.columns:
        wins_only = f[f["Outcome"] == "Win"]
        avg_rr_wins = float(wins_only["Closed RR"].mean()) if not wins_only.empty else 0.0
    else:
        avg_rr_wins = 0.0
    total_pnl_rr = float(f["PnL_from_RR"].sum())

    st.markdown('<div class="kpi-grid">', unsafe_allow_html=True)
    for label, value in [
        ("TOTAL TRADES", stats["total"]),
        ("WIN %", f"{stats['win_rate']:.2f}%"),
        ("BE %", f"{stats['be_rate']:.2f}%"),
        ("LOSS %", f"{stats['loss_rate']:.2f}%"),
        ("AVG CLOSED RR (WINS ONLY)", f"{avg_rr_wins:.2f}"),
        ("TOTAL PNL (FROM RR)", f"{total_pnl_rr:,.2f}"),
    ]:
        value_html = (
            f"<div class='value' style='color: var(--brand);'>{value}</div>"
            if label == "TOTAL PNL (FROM RR)"
            else f"<div class='value'>{value}</div>"
        )
        st.markdown(
            f"<div class='kpi'><div class='label'>{label}</div>{value_html}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)

    # Tabs (charts/tables). Any selectboxes inside will also pick up the global
    # CSS so they render like button dropdowns without a text caret.
    render_all_tabs(f, df, styler, show_light_table)

# --------------------------------- Router -------------------------------------
def _detect_default_layout_index() -> int:
    layout_qp = (_get_query_param("layout") or "").lower()
    if layout_qp in {"m", "mobile", "phone"}:
        return 1
    return 0

def main() -> None:
    # (NEW) Global dropdown styling injected BEFORE any selectboxes are drawn.
    _inject_dropdown_css()

    st.sidebar.markdown("## Settings")
    # radios -> selectboxes (already in your version) so they look like dropdowns with our chevron
    page = st.sidebar.selectbox(
        "Page",
        ["Dashboard", "Connect Notion"],
        index=0,
        key="nav_page",
    )

    layout_choice = st.sidebar.selectbox(
        "Layout",
        ["Desktop Layout", "Mobile Layout"],
        index=_detect_default_layout_index(),
        key="layout_choice",
    )
    # Keep session flags as before
    st.session_state["layout_index"] = 1 if layout_choice == "Mobile Layout" else 0
    st.session_state["layout_mode"] = "mobile" if layout_choice == "Mobile Layout" else "desktop"

    if page == "Connect Notion":
        render_connect_page()
    else:
        render_dashboard()

if __name__ == "__main__":
    main()
