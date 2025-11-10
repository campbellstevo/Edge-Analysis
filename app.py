from __future__ import annotations 
import os
import sys
import base64
import secrets               # for OAuth state
import requests              # for token exchange
import hashlib               # PATCH: PKCE S256
import time                  # PATCH: cache timestamps
import re                    # PATCH: DB link parsing
from urllib.parse import urlencode, urlparse  # PATCH: urlparse for DB link
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

# --- PATCH: rerun shim (works across Streamlit versions) ---------------------
def _st_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()  # type: ignore[attr-defined]
        except Exception:
            pass

# --- PATCH (Mobile-fit): compact typography & spacing on small screens ---
st.markdown("""
<style>
@media (max-width: 480px) {
  .block-container { padding-left: .6rem !important; padding-right: .6rem !important; padding-top: .5rem !important; }
  html { font-size: 14px; } body, p, span, div { line-height: 1.15; }
  .entry-card { padding: 14px 14px; border-radius: 12px; }
  .entry-card h2 { font-size: 20px; margin: 0 0 6px 0; }
  table.entry-model-table, table.session-perf-table, table.day-perf-table { font-size: 12px; table-layout: fixed; width: 100%; }
  .entry-model-table thead th, .entry-model-table tbody td, .session-perf-table thead th, .session-perf-table tbody td, .day-perf-table thead th, .day-perf-table tbody td {
    padding: 8px 6px; line-height: 1.15; word-break: break-word; hyphens: auto;
  }
  .entry-model-table td:nth-child(2), .session-perf-table td:nth-child(2), .day-perf-table td:nth-child(2) { width: 64px; }
  .entry-model-table td:nth-child(3), .session-perf-table td:nth-child(3), .day-perf-table td:nth-child(3) { width: 72px; }
  .stTabs [data-baseweb="tab"] { padding: 6px 10px; }
  .stTabs [data-baseweb="tab"] p { font-size: 14px; margin: 0; }
  div[data-testid="stMetricValue"] { font-size: 24px; }
  div[data-testid="stMetricDelta"] { font-size: 12px; }
  .stMetric { padding: 6px 8px; }
  .stAltairChart, .stPlotlyChart, .stVegaLiteChart { margin-top: 4px; margin-bottom: 8px; }
}
</style>
""", unsafe_allow_html=True)

# --- PATCH (1): Card + clean table CSS (added once, near top) ---
st.markdown("""
<style>
.entry-card { background:#fff; border-radius:16px; padding:20px 24px; box-shadow:0 6px 22px rgba(0,0,0,.06); }
.entry-card h2 { margin:0 0 10px 0; font-size:28px; line-height:1.2; font-weight:800; }
.entry-model-table { width:100%; border-collapse:separate; border-spacing:0; font-size:16px; }
.entry-model-table thead th { text-align:left; font-weight:700; background:#f6f7fb; padding:12px 10px; border-bottom:2px solid #4800ff; }
.entry-model-table tbody td { padding:12px 10px; border-bottom:1px solid #eef0f5; }
.entry-model-table tbody tr:nth-child(even) td { background:#fafbff; }
.entry-model-table td.num, .entry-model-table th.num { text-align:right; }
.entry-model-table td.text, .entry-model-table th.text { text-align:left; }
.entry-card .table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.entry-model-table { table-layout:fixed; min-width:520px; }
.entry-model-table th, .entry-model-table td { word-wrap:break-word; overflow-wrap:anywhere; }
</style>
""", unsafe_allow_html=True)

# --- Mobile-only: make tabs wrap into multiple rows ---
st.markdown("""
<style>
@media (max-width: 768px) {
  div[data-baseweb="tab-list"] { flex-wrap: wrap !important; overflow: visible !important; gap: 8px 12px !important; }
  div[data-baseweb="tab"] { flex: 0 1 auto !important; margin: 0 !important; }
  div[data-baseweb="tab-list"]::before, div[data-baseweb="tab-list"]::after { content: none !important; display: none !important; }
}
</style>
""", unsafe_allow_html=True)

# --- Mobile-only: remove underline highlight under active tab (PATCH) ---
st.markdown("""
<style>
@media (max-width: 768px) {
  .stTabs [data-baseweb="tab-highlight"] { display: none !important; }
  .stTabs [role="tab"][aria-selected="true"] { border-bottom: none !important; box-shadow: none !important; }
}
</style>
""", unsafe_allow_html=True)

# --- PATCH: zero-scroll on mobile with ALL columns visible ---
st.markdown("""
<style>
@media (max-width: 480px) {
  html { font-size: 12.5px; }
  .block-container { padding-left:.45rem !important; padding-right:.45rem !important; padding-top:.4rem !important; }
  .stMetric { padding:4px 6px !important; }
  div[data-testid="stMetricValue"] { font-size:20px !important; }
  div[data-testid="stMetricDelta"] { font-size:11px !important; }
  .entry-card h2 { font-size:17px !important; margin:0 0 4px 0 !important; }
  h2, h3 { font-size:19px !important; margin:8px 0 6px 0 !important; }
  table.entry-model-table, table.session-perf-table, table.day-perf-table {
    width:100% !important; table-layout:fixed !important; font-size:10.5px !important; border-spacing:0 !important; min-width:0 !important;
  }
  .entry-model-table thead th, .entry-model-table tbody td, .session-perf-table thead th, .session-perf-table tbody td, .day-perf-table thead th, .day-perf-table tbody td {
    padding:4px 4px !important; line-height:1.05 !important; word-break:break-word !important; overflow-wrap:anywhere !important; white-space:normal !important; hyphens:auto !important;
  }
  .entry-model-table th:nth-child(1), .entry-model-table td:nth-child(1),
  .session-perf-table th:nth-child(1), .session-perf-table td:nth-child(1),
  .day-perf-table th:nth-child(1), .day-perf-table td:nth-child(1) { width:42% !important; }
  .stTabs [data-baseweb="tab"] { padding:5px 8px !important; }
  .stTabs [data-baseweb="tab"] p { font-size:13px !important; margin:0 !important; }
  .spacer-12 { height:6px !important; }
}
</style>
""", unsafe_allow_html=True)

# Tab favicon
if FAVICON.exists():
    try:
        favicon_b64 = base64.b64encode(FAVICON.read_bytes()).decode()
        st.markdown(f"""<link rel="shortcut icon" href="data:image/png;base64,{favicon_b64}">""", unsafe_allow_html=True)
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

def _get_all_query_params() -> dict:
    try:
        return dict(st.query_params)
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}

def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

def _runtime_secret(key: str, default=None):
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
        :root {{ --ea-brand: {BRAND_PURPLE}; }}
        [data-baseweb="select"] input[aria-autocomplete="list"] {{
            caret-color: transparent !important; pointer-events: none !important; user-select: none !important;
            opacity: 0 !important; width: 0 !important; min-width: 0 !important;
        }}
        [data-baseweb="select"] [role="combobox"], [data-baseweb="select"] > div {{ cursor: pointer !important; }}
        [data-baseweb="select"] svg {{ display: none !important; }}
        [data-baseweb="select"] > div {{ position: relative !important; }}
        [data-baseweb="select"] > div::after {{
            content:""; position:absolute; right:12px; top:50%; transform:translateY(-50%); width:16px; height:16px;
            background-image:url("{chevron_svg}"); background-repeat:no-repeat; background-size:16px 16px; opacity:.9; pointer-events:none;
        }}
        [data-testid="stTextInput"] input, [data-testid="stPassword"] input, [data-testid="stTextArea"] textarea {{
            pointer-events:auto !important; opacity:1 !important; width:100% !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def inject_soft_bg():
    st.markdown(
        """
        <style>
          :root { --ea-bg-soft: #f5f6fb; }
          [data-testid="stAppViewContainer"] { background: var(--ea-bg-soft) !important; }
          header[data-testid="stHeader"], [data-testid="stToolbar"] {
            background: var(--ea-bg-soft) !important;
            border-bottom: none !important;
            box-shadow: none !important;
          }
          [data-testid="stSidebar"] { background: #ffffff !important; }
          [data-testid="stSidebar"] * { color: #0f172a !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def inject_label_fix():
    st.markdown(
        """
        <style>
        [data-testid="stSelectbox"] label,
        [data-testid="stRadio"] label,
        [data-testid="stTextInput"] label { color:#0f172a !important; font-weight:600 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

# --- PATCH (2): Helper to render a clean Entry Model table ---
def render_entry_model_table(df: pd.DataFrame, title: str = "Entry Model Performance"):
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(col not in df.columns for col in expected):
        return

    def fmt_int(v): return "" if pd.isna(v) else f"{int(v)}"
    def fmt_num(v, decimals=2): return "" if pd.isna(v) else f"{float(v):.{decimals}f}"

    header_html = (
        '<th class="text">Entry_Model</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
    )

    rows_html = []
    for _, r in df.iterrows():
        rows_html.append(
            "<tr>"
            f'<td class="text">{r.get("Entry_Model","")}</td>'
            f'<td class="num">{fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{fmt_num(r.get("Loss %"))}</td>'
            "</tr>"
        )

    table_html = f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </div>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)

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
        df["Entry Models List"] = df.apply(lambda r: build_models_list(r.get("Entry Model"), r.get("Multi Entry Model Entry")), axis=1)
    else:
        df["Entry Models List"] = df.get("Entry Model", "").apply(lambda v: build_models_list(v, None))
    if "Entry Confluence" in df.columns:
        import re as _re
        df["Entry Confluence List"] = df["Entry Confluence"].fillna("").astype(str).apply(
            lambda s: [x.strip() for x in _re.split(r"[;,]", s) if x.strip()]
        )
    else:
        df["Entry Confluence List"] = [[] for _ in range(len(df))]
    df["Outcome"] = df.apply(lambda r: classify_outcome_from_fields(r.get("Result"), r.get("Closed RR"), r.get("PnL")), axis=1)
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
# ---- OAuth helpers (PKCE + store) ----
@st.cache_resource
def _oauth_store(): return {}
def _oauth_put(state: str, code_verifier: str): _oauth_store()[state] = {"code_verifier": code_verifier, "ts": time.time()}
def _oauth_pop(state: str): return _oauth_store().pop(state, None)
def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

def _oauth_client():
    cid  = (_runtime_secret("NOTION_OAUTH_CLIENT_ID") or _runtime_secret("NOTION_CLIENT_ID"))
    csec = (_runtime_secret("NOTION_OAUTH_CLIENT_SECRET") or _runtime_secret("NOTION_CLIENT_SECRET"))
    ruri = (_runtime_secret("NOTION_OAUTH_REDIRECT_URI") or _runtime_secret("NOTION_REDIRECT_URI"))
    return cid, csec, ruri

def _exchange_code_for_token(code: str, code_verifier: str | None = None) -> dict | None:
    client_id, client_secret, redirect_uri = _oauth_client()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    if code_verifier: payload["code_verifier"] = code_verifier
    resp = requests.post(
        "https://api.notion.com/v1/oauth/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

# NEW: prepare URL (does NOT redirect) so the UI button matches the PNG flow
def _prepare_oauth_url() -> str | None:
    client_id, _, redirect_uri = _oauth_client()
    if not (client_id and redirect_uri):
        return None
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    st.session_state["oauth_pending"] = {"state": state, "verifier": verifier}
    _oauth_put(state, verifier)
    params = {
        "client_id": client_id, "response_type": "code", "owner": "user",
        "redirect_uri": redirect_uri, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)

def _start_notion_oauth():
    # retained for legacy paths; not used by the new UI button
    auth_url = _prepare_oauth_url()
    if not auth_url:
        st.error("Missing OAuth client settings. Check your secrets.")
        return
    st.markdown(f'<meta http-equiv="refresh" content="0; url={auth_url}">', unsafe_allow_html=True)

def _handle_oauth_callback() -> bool:
    qp = _get_all_query_params()
    code = qp.get("code")[0] if isinstance(qp.get("code"), list) else qp.get("code")
    rstate = qp.get("state")[0] if isinstance(qp.get("state"), list) else qp.get("state")
    if not code or not rstate:
        return False
    rec = _oauth_pop(rstate)
    verifier = (rec or {}).get("code_verifier") or (st.session_state.get("oauth_pending") or {}).get("verifier")
    if not verifier:
        st.session_state["oauth_callback_code"] = code
        st.session_state.pop("oauth_pending", None)
        _clear_query_params()
        st.error("OAuth state verifier missing. Click Finalize sign-in below, or Connect again.")
        return True
    try:
        data = _exchange_code_for_token(code, code_verifier=verifier)
        access_token = data.get("access_token") if data else None
        if not access_token:
            raise RuntimeError("No access_token in Notion response")
        st.session_state["override_NOTION_TOKEN"] = access_token
        st.success("Connected to Notion via OAuth")
        ws = data.get("workspace_name") or data.get("bot_id")
        if ws: st.caption(f"Workspace: {ws}")
    except Exception as e:
        st.error(f"OAuth token exchange failed: {e}")
    finally:
        st.session_state.pop("oauth_pending", None)
        _clear_query_params()
        _st_rerun()
    return True

# -------------------- Database helpers -----------------
NOTION_API_VERSION = _runtime_secret("NOTION_VERSION", "2022-06-28")

def _extract_db_id_from_url_or_id(text: str) -> str | None:
    if not text: return None
    t = text.strip()
    raw = t.replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", raw): return raw.lower()
    try:
        u = urlparse(t); path = (u.path or "").replace("-", "")
        m = re.search(r"([0-9a-fA-F]{32})", path)
        if m: return m.group(1).lower()
    except Exception: pass
    return None

def _verify_database_access(oauth_token: str | None, internal_token: str | None, dbid: str):
    token = oauth_token or internal_token
    if not token: return (False, None, "No Notion token available.")
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_API_VERSION, "Content-Type": "application/json"}
    url = f"https://api.notion.com/v1/databases/{dbid}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200: return (True, 200, r.json())
        else: return (False, r.status_code, r.text)
    except Exception as e:
        return (False, None, f"Request failed: {e}")

# ---- Polished UI block to match the PNG exactly ------------------------------
def _connect_page_css():
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}
        [data-testid="stSidebar"] * {{ color:#0f172a !important; }}

        .connect-wrap {{ max-width: 980px; margin: 0 auto; }}
        .ea-title {{
            display:flex; align-items:center; gap:.6rem;
            font-size:38px; line-height:1.2; font-weight:800; letter-spacing:-0.02em;
            color:#0f172a; margin:6px 0 8px 0;
        }}
        .ea-sub {{ color:#475569; font-size:16px; margin:0 0 16px 0; }}
        .ea-card {{
            background:#fff; border-radius:18px; box-shadow:0 8px 30px rgba(0,0,0,.06);
            border:1px solid rgba(0,0,0,0.06); padding:24px 28px; margin: 10px 0 18px 0;
        }}
        .ea-divider {{ height:1px; background:#e5e7eb; margin:16px 0 12px 0; }}
        .ea-step {{ font-size:22px; font-weight:800; color:#0f172a; margin: 6px 0 6px 0; }}
        .ea-help {{ color:#475569; font-size:15px; margin-bottom:14px; }}

        .stButton>button {{
            border-radius:12px; padding:12px 18px; font-weight:700;
            border:1px solid rgba(0,0,0,0.06); box-shadow:0 2px 6px rgba(0,0,0,0.04);
        }}
        .ea-primary .stButton>button {{ background:var(--brand); color:#fff; border-color:var(--brand); }}
        .ea-secondary .stButton>button {{ background:#fff; color:#111827; }}

        .stTextInput>div>div>input {{
            border: 2px solid #e5e7eb !important; border-radius:12px !important;
            padding:12px 14px !important; font-size:15px !important;
        }}

        .ea-watermark {{ position:fixed; right:18px; bottom:18px; opacity:.18; z-index:0; pointer-events:none; }}
        .ea-watermark img {{ width:160px; max-width:28vw; }}

        @media (max-width: 800px) {{
          .ea-title {{ font-size:30px; }}
          .ea-step {{ font-size:19px; }}
          .ea-card {{ padding:18px 18px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def render_connect_page(mobile: bool):
    styler = apply_theme()   # locked to light
    inject_global_css()
    inject_header("light")
    inject_soft_bg()
    _connect_page_css()

    if _handle_oauth_callback():
        pass

    with st.container():
        st.markdown('<div class="connect-wrap">', unsafe_allow_html=True)

        # Header exactly like mock
        st.markdown('<div class="ea-title">Connect Notion</div>', unsafe_allow_html=True)
        # (Removed the descriptive subtitle under the title as requested)

        st.markdown('<div class="ea-card">', unsafe_allow_html=True)

        # STEP 1
        st.markdown('<div class="ea-step">Step 1 — Connect with Notion (OAuth)</div>', unsafe_allow_html=True)
        st.markdown('<div class="ea-help">Use OAuth to authorize securely. This token is stored for your session only.</div>', unsafe_allow_html=True)

        _cid, _csec, _ruri = _oauth_client()
        missing = []
        if not _cid: missing.append("Client ID")
        if not _csec: missing.append("Client Secret")
        if not _ruri: missing.append("Redirect URI")
        if missing:
            st.warning("OAuth secrets not fully configured: " + ", ".join(missing) +
                       ". Add either NOTION_OAUTH_* or NOTION_* to your `.streamlit/secrets.toml`.")

        # Callback fallback flow
        if st.session_state.get("oauth_callback_code"):
            st.info("We received a callback from Notion but your session was reset.")
            if st.button("Finalize sign-in", key="btn_finalize_oauth"):
                code = st.session_state.get("oauth_callback_code")
                try:
                    data = _exchange_code_for_token(code, code_verifier=None)
                    access_token = data.get("access_token") if data else None
                    if not access_token: raise RuntimeError("No access_token in Notion response")
                    st.session_state["override_NOTION_TOKEN"] = access_token
                    st.success("Notion connected via OAuth")
                    ws = data.get("workspace_name") or data.get("bot_id")
                    if ws: st.caption(f"Workspace: {ws}")
                except Exception as e:
                    st.error(f"OAuth token exchange failed: {e}")
                finally:
                    st.session_state.pop("oauth_callback_code", None)
                    _st_rerun()

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="ea-primary">', unsafe_allow_html=True)
            auth_url = _prepare_oauth_url()
            if auth_url:
                st.link_button("Connect Notion", auth_url)
            else:
                st.button("Connect Notion", disabled=True)
            st.markdown('</div>', unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="ea-secondary">', unsafe_allow_html=True)
            if st.button("Disconnect", key="btn_oauth_clear"):
                st.session_state.pop("override_NOTION_TOKEN", None)
                st.session_state.pop("oauth_pending", None)
                st.session_state.pop("oauth_callback_code", None)
                st.info("Disconnected.")
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.get("override_NOTION_TOKEN"):
            st.success("Connected (token stored for this session only)")
        elif st.session_state.get("oauth_pending"):
            st.info("Completing Notion sign-in...")

        st.markdown('<div class="ea-divider"></div>', unsafe_allow_html=True)

        # STEP 2
        st.markdown('<div class="ea-step">Step 2 — Paste your Notion database link</div>', unsafe_allow_html=True)

        oauth_bundle = st.session_state.get("override_NOTION_TOKEN")
        oauth_token  = oauth_bundle if isinstance(oauth_bundle, str) else st.session_state.get("override_NOTION_TOKEN")

        db_link_default = st.session_state.get("db_link_input", "")
        db_link = st.text_input(
            "Database link or ID",
            value=db_link_default,
            key="db_link_input",
            placeholder="https://www.notion.so/My-DB-Name-1234567abcd1234ef567890abcd1234",
        )
        if db_link:
            dbid = _extract_db_id_from_url_or_id(db_link)
            if not dbid:
                st.error("That doesn’t look like a valid Notion database link or ID.")
            else:
                st.caption(f"Detected database ID: `{dbid}`")
                ok, status, info = _verify_database_access(
                    oauth_token=oauth_token,
                    internal_token=None,
                    dbid=dbid,
                )
                if ok:
                    st.success("Database verified")
                    st.session_state["override_DATABASE_ID"] = dbid
                else:
                    if status == 403:
                        st.warning("Access denied (403). In Notion, open the database → ⋯ → Add connections → choose your app/integration, then try again.")
                        if st.button("Verify again"):
                            _st_rerun()
                    elif status == 404:
                        st.error("Notion can’t find that database (404). Ensure it’s a database (not a page) and the ID/link is correct.")
                    else:
                        st.error(f"Couldn’t verify the database. {info}")

        st.caption("Tip: You can also prefill via URL query params like `?notion_token=...&database_id=...`")
        st.markdown('</div>', unsafe_allow_html=True)  # end big card

        # Watermark
        logo_path = ASSETS_DIR / "edge_logo.png"
        if logo_path.exists():
            try:
                _wm_b64 = base64.b64encode(logo_path.read_bytes()).decode()
                st.markdown(f'<div class="ea-watermark"><img alt="Edge Analysis" src="data:image/png;base64,{_wm_b64}" /></div>', unsafe_allow_html=True)
            except Exception:
                pass

        st.markdown('</div>', unsafe_allow_html=True)  # /connect-wrap

# -------------------------- Mobile CSS helper (PATCH) -------------------------
def _inject_mobile_css(layout_mode: str):
    if layout_mode != "mobile":
        return
    st.markdown("""
    <style>
      [data-testid="stSidebar"] { display: none !important; }
      [data-testid="stAppViewContainer"] > .main { padding-left: 0 !important; }
    </style>
    """, unsafe_allow_html=True)

# -------------------------------- Dashboard -----------------------------------
def render_dashboard(mobile: bool):
    st.markdown(
        f"""
        <style>
        :root {{ --brand: {BRAND_PURPLE}; }}
        .live-banner {{ text-align:center; margin:-8px 0 16px 0; font-weight:800; font-size:22px; color:var(--brand); }}
        [data-testid="stSidebar"] {{ background:#fff !important; }}
        [data-testid="stSidebar"] * {{ color:#0f172a !important; }}

        /* Dashboard watermark */
        .ea-watermark {{ position:fixed; right:18px; bottom:18px; opacity:.18; z-index:0; pointer-events:none; }}
        .ea-watermark img {{ width:160px; max-width:28vw; }}

        /* Empty-state hero */
        .ea-empty-wrap {{
            text-align:center;
            margin: 32px 0 18px 0;
        }}
        .ea-empty-title {{
            font-size:24px;
            font-weight:800;
            color:var(--brand);
            letter-spacing:-0.01em;
        }}
        .ea-empty-btn .stButton>button {{
            background:var(--brand);
            color:#ffffff;
            border:none;
            border-radius:999px;
            padding:12px 24px;
            font-weight:700;
            box-shadow:0 8px 22px rgba(72,0,255,0.22);
        }}
        .ea-empty-btn .stButton>button:hover {{
            filter:brightness(0.96);
        }}
        @media (max-width: 768px) {{
          .ea-empty-wrap {{ margin: 24px 0 14px 0; }}
          .ea-empty-title {{ font-size:20px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    styler = apply_theme()   # locked to light
    inject_global_css()
    inject_header("light")
    inject_soft_bg()

    token = _runtime_secret("NOTION_TOKEN")
    dbid = _runtime_secret("DATABASE_ID")

    with st.spinner("Fetching trades from Notion…"):
        df = load_live_df(token, dbid)

    # ---- Banner + CTA depending on connection status -------------------------
    if token and dbid:
        # Connected: keep the existing banner
        st.markdown("<div class='live-banner'>Live Notion Connected</div>", unsafe_allow_html=True)
    else:
        # Not connected: hero-style empty state only (no extra banner line)
        with st.container():
            st.markdown(
                """
                <div class="ea-empty-wrap">
                  <div class="ea-empty-title">No Notion template is connected yet</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col_left, col_mid, col_right = st.columns([1, 2, 1])
            with col_mid:
                st.markdown('<div class="ea-empty-btn">', unsafe_allow_html=True)
                if st.button(
                    "Connect Notion",
                    key="btn_connect_template",
                    use_container_width=True,
                ):
                    # Set target page for next run (avoid writing nav_page after widget)
                    st.session_state["nav_page_target"] = "Connect Notion"
                    # Layout stays whatever it currently is (desktop/mobile)
                    _st_rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        return

    if df.empty:
        st.info("No data yet. Add trades, adjust filters, or check credentials.")
        return

    instruments = sorted(df["Instrument"].dropna().unique().tolist())
    instruments = [i for i in instruments if i != "DUMMY ROW"]

    def _inst_label(v: str) -> str: return "GOLD" if v == "Gold" else v

    inst_opts = ["All"] + instruments
    em_opts = ["All"] + MODEL_SET
    sess_opts = ["All"] + sorted(set(SESSION_CANONICAL) | set(df["Session Norm"].dropna().unique()))

    # --- NEW: date range defaults (for sidebar/mobile date filter) ---
    if "Date" in df.columns:
        min_date = df["Date"].min().date()
        max_date = df["Date"].max().date()
    else:
        from datetime import date as _date
        min_date = max_date = _date.today()

    if not mobile:
        st.sidebar.markdown("### Filters")
        sel_inst = st.sidebar.selectbox("Instrument", inst_opts, index=0, format_func=_inst_label, key="filters_inst_select")
        sel_em = st.sidebar.selectbox("Entry Model", em_opts, index=0, format_func=lambda x: x, key="filters_em_select")
        sel_sess = st.sidebar.selectbox("Session", sess_opts, index=0, format_func=lambda x: x, key="filters_sess_select")
        date_range = st.sidebar.date_input(
            "Date range",
            value=st.session_state.get("filters_date_range", (min_date, max_date)),
            key="filters_date_range",
        )
    else:
        st.markdown("<div style='height: 8px'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("### Navigation")
            _ = st.selectbox("Page", ["Dashboard", "Connect Notion"],
                             index=0 if st.session_state.get("nav_page", "Dashboard") == "Dashboard" else 1, key="nav_page")
            _ = st.selectbox("Layout", ["Desktop Layout", "Mobile Layout"],
                             index=1 if st.session_state.get("layout_choice", "Desktop Layout") == "Mobile Layout" else 0,
                             key="layout_choice")
            st.markdown("### Filters")
            c1, c2 = st.columns(2, gap="small")
            with c1:
                sel_inst = st.selectbox("Instrument", inst_opts,
                                        index=inst_opts.index(st.session_state.get("filters_inst_select", "All"))
                                        if st.session_state.get("filters_inst_select", "All") in inst_opts else 0,
                                        format_func=_inst_label, key="filters_inst_select")
            with c2:
                sel_sess = st.selectbox("Session", sess_opts,
                                        index=sess_opts.index(st.session_state.get("filters_sess_select", "All"))
                                        if st.session_state.get("filters_sess_select", "All") in sess_opts else 0,
                                        key="filters_sess_select")
            sel_em = st.selectbox("Entry Model", em_opts,
                                  index=em_opts.index(st.session_state.get("filters_em_select", "All"))
                                  if st.session_state.get("filters_em_select", "All") in em_opts else 0,
                                  key="filters_em_select")
            date_range = st.date_input(
                "Date range",
                value=st.session_state.get("filters_date_range", (min_date, max_date)),
                key="filters_date_range",
            )

    mask = pd.Series(True, index=df.index)
    if sel_inst != "All": mask &= (df["Instrument"] == sel_inst)
    if sel_em != "All": mask &= df["Entry Models List"].apply(lambda lst: sel_em in lst if isinstance(lst, list) else False)
    if sel_sess != "All": mask &= (df["Session Norm"] == sel_sess)

    # --- NEW: apply date range mask ---
    from datetime import date as _date_type
    if isinstance(date_range, (list, tuple)):
        if len(date_range) == 2:
            start, end = date_range
            if isinstance(start, _date_type) and isinstance(end, _date_type):
                mask &= df["Date"].dt.date.between(start, end)
    elif isinstance(date_range, _date_type):
        # single date selected
        mask &= df["Date"].dt.date == date_range

    f = df[mask].copy()
    f["PnL_from_RR"] = f["Closed RR"].fillna(0.0)
    stats = generate_overall_stats(f)

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
        value_html = (f"<div class='value' style='color: var(--brand);'>{value}</div>"
                      if label == "TOTAL PNL (FROM RR)" else f"<div class='value'>{value}</div>")
        st.markdown(f"<div class='kpi'><div class='label'>{label}</div>{value_html}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='spacer-12'></div>", unsafe_allow_html=True)

    render_all_tabs(f, df, styler, show_light_table)

    # Watermark (Dashboard)
    logo_path = ASSETS_DIR / "edge_logo.png"
    if logo_path.exists():
        try:
            _wm_b64 = base64.b64encode(logo_path.read_bytes()).decode()
            st.markdown(f'<div class="ea-watermark"><img alt="Edge Analysis" src="data:image/png;base64,{_wm_b64}" /></div>',
                        unsafe_allow_html=True)
        except Exception:
            pass

# --------------------------------- Router -------------------------------------

def _detect_default_layout_index() -> int:
    layout_qp = (_get_query_param("layout") or "").lower()
    if layout_qp in {"m", "mobile", "phone"}: return 1
    return 0

def main() -> None:
    _inject_dropdown_css()
    inject_soft_bg()
    inject_label_fix()

    # Seed layout choice from query param on first run
    if "layout_choice" not in st.session_state:
        st.session_state["layout_choice"] = "Desktop Layout" if _detect_default_layout_index() == 0 else "Mobile Layout"

    # Seed nav_page from query param on first run (so ?page=connect opens Connect Notion)
    if "nav_page" not in st.session_state:
        qp_page = (_get_query_param("page") or "").lower()
        if qp_page.startswith("connect"):
            st.session_state["nav_page"] = "Connect Notion"
        else:
            st.session_state["nav_page"] = "Dashboard"

    # promote nav_page_target -> nav_page before widgets
    if "nav_page_target" in st.session_state:
        st.session_state["nav_page"] = st.session_state.pop("nav_page_target")

    layout_choice_ss = st.session_state.get("layout_choice", "Desktop Layout")
    layout_mode = "mobile" if layout_choice_ss == "Mobile Layout" else "desktop"
    st.session_state["layout_index"] = 1 if layout_mode == "mobile" else 0
    st.session_state["layout_mode"] = layout_mode

    if layout_mode == "desktop":
        st.sidebar.markdown("## Settings")
        st.sidebar.selectbox("Page", ["Dashboard", "Connect Notion"],
                             index=0 if st.session_state.get("nav_page", "Dashboard") == "Dashboard" else 1,
                             key="nav_page")
        # NEW: respect current layout_choice instead of re-reading query params
        current_layout = st.session_state.get("layout_choice", "Desktop Layout")
        st.sidebar.selectbox(
            "Layout",
            ["Desktop Layout", "Mobile Layout"],
            index=0 if current_layout == "Desktop Layout" else 1,
            key="layout_choice",
        )
    else:
        _inject_mobile_css(layout_mode)

    if st.session_state.get("nav_page", "Dashboard") == "Connect Notion":
        render_connect_page(mobile=(layout_mode == "mobile"))
    else:
        render_dashboard(mobile=(layout_mode == "mobile"))

if __name__ == "__main__":
    main()
