from __future__ import annotations
import pandas as pd
import streamlit as st

def show_light_table(df: pd.DataFrame, hide_index: bool = True):
    if df is None or df.empty:
        st.info("No rows.")
        return
    df2 = df.copy()
    for col in df2.columns:
        if df2[col].map(lambda x: isinstance(x, list)).any():
            df2[col] = df2[col].apply(lambda v: ", ".join(v) if isinstance(v, list) else v)
    if hide_index:
        df2 = df2.reset_index(drop=True)
    thead = "".join(f"<th>{str(c)}</th>" for c in df2.columns)
    rows = []
    for _, r in df2.iterrows():
        tds = "".join(f"<td>{'' if pd.isna(v) else str(v)}</td>" for v in r)
        rows.append(f"<tr>{tds}</tr>")
    tbody = "".join(rows)
    html = f"<div class='table-wrap'><table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)
# ------------------------------------------------------------------------------
# HEADER (centered logo instead of big title)
# ------------------------------------------------------------------------------

def inject_header():
    """
    Centered logo hero at top. Replaces the big 'Edge Analysis — Live Notion' title.
    """
    from edge_analysis.core.constants import LOGO_LIGHT, LOGO_DARK
    from pathlib import Path

    def _asset_exists(p: str) -> bool:
        return Path(p).exists()

    theme = st.get_option("theme.base") or "light"
    logo_path = LOGO_DARK if (theme == "dark" and _asset_exists(LOGO_DARK)) else LOGO_LIGHT

    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;margin-top:1.0rem;margin-bottom:0.5rem;">
            <img src="{logo_path}" alt="Edge Analysis" style="max-width:380px;height:auto;" />
        </div>
        """,
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------------------
# SIDEBAR CONTROLS (open/close buttons styled black)
# ------------------------------------------------------------------------------

def sidebar_controls():
    """
    Original open/close controls (styled black). Toggles the sidebar width.
    """
    if "ea_sidebar_open" not in st.session_state:
        st.session_state.ea_sidebar_open = True

    col1, col2 = st.columns([0.2, 0.8])
    with col1:
        open_clicked = st.button("Open", key="ea_open")
    with col2:
        close_clicked = st.button("Close", key="ea_close")

    if open_clicked:
        st.session_state.ea_sidebar_open = True
    if close_clicked:
        st.session_state.ea_sidebar_open = False

    css = """
    <style>
      section[data-testid="stSidebar"] {{
        width: {w};
        min-width: {w};
        transition: width 200ms ease, min-width 200ms ease;
        overflow: hidden;
      }}
      button#ea_open, button#ea_close {{
        background: black !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        padding: 6px 14px !important;
      }}
    </style>
    """.format(w=("350px" if st.session_state.ea_sidebar_open else "0px"))

    st.markdown(css, unsafe_allow_html=True)
