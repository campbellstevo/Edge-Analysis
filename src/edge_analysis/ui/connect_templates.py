# src/edge_analysis/ui/connect_notion.py
from __future__ import annotations
from pathlib import Path
import os, json, base64, secrets, requests
from urllib.parse import urlencode
import pandas as pd
import streamlit as st

# ADAPTERS (existing JSON adapter kept; plus new profile-based path)
from edge_analysis.data.template_adapter import adapt_auto, adapt_df

# Profile discovery for the picker (YAML/JSON/TOML)
try:
    from edge_analysis.data.template_profiles import discover_profiles
except Exception:
    discover_profiles = None  # graceful if Step 2 not added yet

# -------------------- SHARED HELPERS --------------------

# Best-effort rerun shim (works whether your global shim is present or not)
def _safe_rerun():
    try:
        from app import _st_rerun  # your global shim if defined in app.py
        _st_rerun()
    except Exception:
        try:
            st.rerun()
        except Exception:
            try:
                st.experimental_rerun()  # older streamlit
            except Exception:
                pass

def _render_source_badge():
    src = st.session_state.get("data_source", "demo")
    label = "NOTION" if src == "notion" else "UPLOADED" if src == "uploaded" else "DEMO"
    st.caption(f"Data source: **{label}**")

# -------------------- NEW OAUTH CONNECT PAGE --------------------

BRAND_PURPLE = "#4800ff"
AUTH_BASE = "https://api.notion.com/v1/oauth/authorize"
TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_VER = "2022-06-28"  # pin a version

def _oauth_cfg():
    client_id = os.getenv("NOTION_CLIENT_ID") or st.secrets.get("NOTION_CLIENT_ID")
    client_secret = os.getenv("NOTION_CLIENT_SECRET") or st.secrets.get("NOTION_CLIENT_SECRET")
    redirect_uri = (
        os.getenv("NOTION_REDIRECT_URI")
        or st.secrets.get("NOTION_REDIRECT_URI")
        or "https://edge-analysis.streamlit.app/"
    )
    return client_id, client_secret, redirect_uri

def _auth_url():
    client_id, _, redirect_uri = _oauth_cfg()
    st.session_state["oauth_state"] = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "owner": "user",  # change to "workspace" if you prefer
        "redirect_uri": redirect_uri,
        "state": st.session_state["oauth_state"],
    }
    return f"{AUTH_BASE}?{urlencode(params)}"

def _exchange_code_for_token(code: str) -> dict:
    client_id, client_secret, redirect_uri = _oauth_cfg()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VER,
    }
    body = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    r = requests.post(TOKEN_URL, headers=headers, data=json.dumps(body), timeout=30)
    r.raise_for_status()
    return r.json()

def _fetch_databases(access_token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_VER,
        "Content-Type": "application/json",
    }
    payload = {"query": "", "filter": {"value": "database", "property": "object"}, "page_size": 25}
    r = requests.post("https://api.notion.com/v1/search", headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

# --------- Minimal Notion → DataFrame helpers (preview + normalization) ---------

def _notion_query_database(access_token: str, dbid: str, limit: int = 200) -> list[dict]:
    """
    Returns a list of page objects (raw Notion items) for preview/normalization.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_VER,
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/databases/{dbid}/query"
    payload = {"page_size": 100}
    out = []
    while True:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        if len(out) >= limit:
            break
        nxt = data.get("next_cursor")
        if not nxt:
            break
        payload["start_cursor"] = nxt
    return out[:limit]

def _rich_to_text(rt):
    # Convert Notion rich_text/title array to plain text
    try:
        return "".join([t.get("plain_text","") for t in (rt or [])]).strip()
    except Exception:
        return ""

def _prop_to_value(prop: dict):
    """
    Flatten a Notion property value to a simple Python value suitable for DataFrame.
    Covers the common property types we care about in the trading journal.
    """
    if not isinstance(prop, dict):
        return prop
    t = prop.get("type")
    v = prop.get(t)

    try:
        if t in ("title", "rich_text"):
            return _rich_to_text(v)
        if t == "number":
            return v
        if t == "select":
            return (v or {}).get("name")
        if t == "multi_select":
            return [x.get("name") for x in (v or [])]
        if t == "checkbox":
            return bool(v)
        if t == "date":
            return (v or {}).get("start")
        if t == "status":
            return (v or {}).get("name")
        if t == "url":
            return v
        if t == "email":
            return v
        if t == "phone_number":
            return v
        if t == "people":
            # return list of names or emails
            names = []
            for p in (v or []):
                n = (p.get("name") or p.get("person",{}).get("email") or "").strip()
                if n: names.append(n)
            return names
        if t == "files":
            return [f.get("name") for f in (v or [])]
        if t == "formula":
            # convert to string representation
            fv = (v or {}).get(v.get("type")) if isinstance(v, dict) else v
            return str(fv) if fv is not None else None
        if t == "relation":
            return [x.get("id") for x in (v or [])]
    except Exception:
        pass
    return v if not isinstance(v, dict) else json.dumps(v, ensure_ascii=False)

def _results_to_df(results: list[dict]) -> pd.DataFrame:
    """
    Convert raw Notion results into a DataFrame with columns = property names.
    """
    rows = []
    for item in results:
        props = item.get("properties", {})
        row = {}
        for name, val in props.items():
            row[name] = _prop_to_value(val)
        # keep page id for dedupe/tracing
        row["__page_id"] = item.get("id")
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # fill empties so UI doesn't choke
    return df

# -------------------- Profile picker state (last-used per DB) --------------------

_PROFILE_STATE = Path(".ea_profile_state.json")

def _load_profile_state() -> dict:
    if _PROFILE_STATE.exists():
        try:
            return json.loads(_PROFILE_STATE.read_text())
        except Exception:
            pass
    return {}

def _save_profile_state(state: dict):
    _PROFILE_STATE.write_text(json.dumps(state, indent=2))

def _pick_template_name(default: str | None = None) -> str | None:
    if not discover_profiles:
        st.warning("Template profiles module not available. Did you add Step 2 (template_profiles.py)?")
        return None
    profs = discover_profiles(Path("assets/templates"))
    names = [p.get("name") for p in profs if p.get("name")]
    if not names:
        st.warning("No template profiles found in assets/templates.")
        return None
    idx = names.index(default) if (default in names) else 0
    return st.selectbox("Template profile", names, index=idx)

# -------------------- PAGE RENDER --------------------

def render_connect_page():
    # ----- header / style
    st.markdown(
        f"""
        <style>
        .ea-hero h1 {{ margin-bottom:.25rem }}
        .ea-hero p {{ color:#6b7280; margin-top:0 }}
        .stButton>button, .stLinkButton>button {{
            border-radius:16px; padding:10px 14px; font-weight:600;
            border:1px solid #e5e7eb;
        }}
        .stButton>button:hover, .stLinkButton>button:hover {{ border-color:{BRAND_PURPLE}; }}
        .ea-watermark, .ea-logo-fixed {{
            position: fixed;
            right: 40px;
            bottom: 12px;
        }}
        </style>
        <div class="ea-hero">
          <h1>Connect Notion</h1>
          <p>Authorize Edge Analysis to read your trading database via Notion OAuth.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_source_badge()

    # ----- callback handling
    try:
        qp = st.query_params
    except Exception:
        qp = st.experimental_get_query_params()

    code = qp.get("code")
    state = qp.get("state")
    if isinstance(code, list): code = code[0]
    if isinstance(state, list): state = state[0]

    if code and "notion_auth" not in st.session_state:
        with st.status("Completing Notion sign-in…", expanded=True) as s:
            if state != st.session_state.get("oauth_state"):
                st.error("OAuth state mismatch. Please try again.")
            else:
                try:
                    payload = _exchange_code_for_token(code)
                    st.session_state["notion_auth"] = {
                        "access_token": payload.get("access_token"),
                        "workspace_id": payload.get("workspace_id"),
                        "workspace_name": payload.get("workspace_name") or "(workspace)",
                        "bot_id": payload.get("bot_id"),
                    }
                    # We prefer Notion as data source once connected
                    st.session_state["data_source"] = "notion"
                    s.update(label="Notion connected", state="complete")
                    # clear query params
                    try:
                        st.query_params.clear()
                    except Exception:
                        pass
                except Exception as e:
                    st.error(f"Token exchange failed: {e}")

    authed = "notion_auth" in st.session_state

    # ----- unauthenticated UI
    if not authed:
        st.link_button("Connect Notion", _auth_url(), use_container_width=True)
        st.caption("You’ll be redirected to notion.so to authorize, then returned here automatically.")
        st.divider()
        st.caption("Secure • OAuth 2.0 • No manual tokens")
        return

    # ----- connected UI
    info = st.session_state["notion_auth"]
    st.success(f"Connected ✓ Workspace: **{info.get('workspace_name','(unknown)')}**")

    cols = st.columns([1,1,1])
    with cols[0]:
        if st.button("Disconnect", type="secondary", use_container_width=True):
            for k in ["notion_auth", "selected_database", "normalized_sample"]:
                st.session_state.pop(k, None)
            # If nothing else is connected, fall back to demo
            if st.session_state.get("data_source") == "notion":
                st.session_state["data_source"] = "demo"
            _safe_rerun()

    st.subheader("Choose a database")
    st.caption("We’ll pull your trading stats from the selected database.")
    with st.spinner("Searching your databases…"):
        try:
            dbs = _fetch_databases(info["access_token"])
        except Exception as e:
            st.error(f"Couldn’t list databases: {e}")
            dbs = []

    options = []
    for d in dbs:
        try:
            title = "".join([t["plain_text"] for t in d.get("title", [])]) or "(Untitled)"
        except Exception:
            title = "(Untitled)"
        options.append((f"{title} — {d.get('id','')}", d.get("id")))

    selected_id = None
    if options:
        labels = [o[0] for o in options]
        label = st.selectbox("Database", labels, index=0)
        selected_id = options[labels.index(label)][1]
        st.session_state["selected_database"] = selected_id
        st.success(f"Using database: `{selected_id}`")
    else:
        st.info("No databases found in your workspace. Create one in Notion and refresh this page.")

    st.divider()

    # --------- If a DB is selected, fetch a small sample and normalize via profile ---------
    if selected_id:
        with st.spinner("Pulling a sample from Notion…"):
            try:
                results = _notion_query_database(info["access_token"], selected_id, limit=200)
                df_raw = _results_to_df(results)
            except Exception as e:
                st.error(f"Failed to read rows from Notion: {e}")
                df_raw = pd.DataFrame()

        if df_raw is not None and not df_raw.empty:
            # Template picker + last used per DB
            dbid = str(selected_id)
            state_obj = _load_profile_state()
            last_used = state_obj.get("last_used", {}).get(dbid)
            profile_name = _pick_template_name(default=last_used)

            # Optional: per-DB overrides could be added here; for now we pass none.
            overrides = {}

            # Normalize using profile-based adapter
            df_norm, used_profile = adapt_df(
                df_raw,
                templates_dir="assets/templates",
                profile_name=profile_name,  # can be None to auto-match
                overrides=overrides
            )

            # Remember last used profile per DB
            if used_profile:
                state_obj.setdefault("last_used", {})[dbid] = used_profile
                _save_profile_state(state_obj)

            # Store a tiny normalized sample in session for other pages if needed
            st.session_state["normalized_sample"] = df_norm.head(50).copy()

            # Debug / preview
            with st.expander("🔎 Profile Debug", expanded=False):
                st.write("Profile used:", used_profile or "(none)")
                st.write("Raw rows:", len(df_raw), "• Normalized rows:", len(df_norm))
                cols_to_show = [c for c in [
                    "Date","Pair","Session","Entry Model","Entry Confluence",
                    "Entry Confluence List","__first_conf",
                    "Outcome","Outcome Canonical","Closed RR","Closed RR Num",
                    "PnL","Is Complete"
                ] if c in df_norm.columns]
                if cols_to_show:
                    st.dataframe(df_norm[cols_to_show].head(25), use_container_width=True)
                else:
                    st.write("No expected canonical columns found. Check your template profile mapping.")

        else:
            st.info("This database appears empty (or unreadable). Add a few rows in Notion and refresh.")

    # Optional: show your template uploader beneath (re-using your existing function)
    with st.expander("Import from a Notion template (CSV/XLSX)", expanded=False):
        render_connect_notion_templates_ui_body_only()

    st.divider()
    if st.button("Return to Dashboard", key="btn_return_dashboard", use_container_width=True):
        try:
            from app import nav_page_target
            nav_page_target("Dashboard")
        except Exception:
            st.session_state["page"] = "Dashboard"
            _safe_rerun()

# -------------------- YOUR EXISTING TEMPLATES UI (UNTOUCHED) --------------------

MY_NOTION_TEMPLATE_URL = "https://lumpy-zone-638.notion.site/27d77800f9cb8187ba04f3ed2336a581?v=27d77800f9cb81d2bd55000c05303a28&source=copy_link"
TRADINGPOOLS_TEMPLATE_URL = "https://hallowed-silicon-4e7.notion.site/2743b411646e8039b4d1e70637ff8c80?v=2743b411646e817e94b4000c5bacc90a&source=copy_link"

def render_connect_notion_templates_ui():
    """Call this if you want the classic full-page templates section."""
    st.subheader("Templates (Notion)")
    _render_source_badge()
    render_connect_notion_templates_ui_body_only()

def render_connect_notion_templates_ui_body_only():
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### My Template")
        st.link_button("🔗 Open My Notion Template", MY_NOTION_TEMPLATE_URL, use_container_width=True)
        st.caption("Duplicate in Notion → fill rows → **Export** (⋯ → Export) as CSV/XLSX.")
    with c2:
        st.markdown("### TradingPools Template")
        st.link_button("🔗 Open TradingPools Notion Template", TRADINGPOOLS_TEMPLATE_URL, use_container_width=True)
        st.caption("Duplicate in Notion → fill rows → **Export** (⋯ → Export) as CSV/XLSX.")

    st.divider()
    st.subheader("Upload your filled template")
    up = st.file_uploader(
        "Upload the CSV/TSV/XLSX you exported from Notion. The app auto-detects My Template or TradingPools.",
        type=["csv", "tsv", "xlsx", "xls"],
        key="upload_templates_dual",
    )

    bcol1, bcol2 = st.columns(2)
    with bcol1:
        if st.button("🧹 Clear uploaded data", use_container_width=True):
            st.session_state.pop("uploaded_df", None)
            if st.session_state.get("data_source") == "uploaded":
                st.session_state["data_source"] = "demo"
            st.info("Cleared uploaded data. Falling back to demo (unless Notion is connected).")
            _safe_rerun()
    with bcol2:
        if st.button("↩️ Switch to Demo", use_container_width=True):
            st.session_state.pop("uploaded_df", None)
            st.session_state["data_source"] = "demo"
            st.success("Switched to **Demo** data.")
            _safe_rerun()

    if not up:
        return

    uploads = Path("uploads"); uploads.mkdir(parents=True, exist_ok=True)
    fpath = uploads / up.name
    with open(fpath, "wb") as f:
        f.write(up.getbuffer())

    df, mapping_name = adapt_auto(fpath, "config/templates")
    if mapping_name:
        st.success(f"Detected template: **{mapping_name}**")
    else:
        st.warning("No mapping detected. Ensure the header row is intact in your export.")

    issues: list[str] = []
    for col in ["Date", "Pair", "Outcome", "Closed RR", "Is Complete"]:
        if col not in df.columns:
            issues.append(f"Missing required column: {col}")

    if "Outcome" in df.columns:
        try:
            bad = ~df["Outcome"].isin(["Win", "BE", "Loss"]) & df["Outcome"].notna()
            if bad.any():
                issues.append(
                    f"Unexpected Outcome values: {list(df.loc[bad, 'Outcome'].astype(str).unique()[:5])}"
                )
        except Exception:
            pass

    if issues:
        st.markdown("**Checks**")
        st.markdown("\n".join(f"- {m}" for m in issues))

    st.dataframe(df.head(25), use_container_width=True)

    st.session_state["uploaded_df"] = df.copy()
    st.session_state["data_source"] = "uploaded"
    st.info(
        "Uploaded data loaded for this session. Open the **Dashboard** to view analytics.  "
        "Use the buttons above to clear or switch back to Demo."
    )
    _safe_rerun()
