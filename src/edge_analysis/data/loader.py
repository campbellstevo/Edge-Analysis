from __future__ import annotations
from pathlib import Path
import pandas as pd
import streamlit as st

# Path to bundled demo data
DEMO_PATH = Path(__file__).resolve().parent / "demodata.csv"

def load_demo_data() -> pd.DataFrame:
    """Load built-in demo CSV and coerce important columns."""
    df = pd.read_csv(DEMO_PATH, dtype=str).fillna("")
    # Numeric coercions (safe if missing)
    for c in ("Closed RR", "PnL", "Star Rating"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Is Complete" in df.columns:
        # Demo file uses literal True/False; coerce just in case
        df["Is Complete"] = df["Is Complete"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df

def _get_notion_creds():
    """
    Collect likely Notion credentials/ids from secrets or session.
    Adjust keys here to match your app if needed.
    """
    token = (
        st.secrets.get("NOTION_TOKEN")
        or st.secrets.get("notion", {}).get("access_token")
        or st.session_state.get("notion_access_token")
    )
    database_id = (
        st.session_state.get("notion_db_id")
        or st.secrets.get("notion", {}).get("database_id")
    )
    return token, database_id

def notion_is_connected() -> bool:
    token, database_id = _get_notion_creds()
    return bool(token and database_id)

def load_notion_data() -> pd.DataFrame:
    """
    Delegates to your existing Notion adapter.
    Must return a DataFrame (can be empty).
    """
    from edge_analysis.data.notion_adapter import fetch_trades  # your existing function
    token, database_id = _get_notion_creds()
    return fetch_trades(token=token, database_id=database_id)

@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Default to DEMO; if Notion is connected and returns non-empty, use Notion.
    Falls back gracefully to DEMO if Notion errors or is empty.
    """
    # Start with DEMO as default
    st.session_state["data_source"] = "demo"
    df_demo = load_demo_data()

    if notion_is_connected():
        try:
            df_notion = load_notion_data()
            if df_notion is not None and not df_notion.empty:
                st.session_state["data_source"] = "notion"
                return df_notion
            # If Notion returns empty, stick with demo
            st.info("Notion returned no rows — using demo data.")
        except Exception as e:
            st.warning(f"Notion error: {e}. Using demo data instead.")

    return df_demo
