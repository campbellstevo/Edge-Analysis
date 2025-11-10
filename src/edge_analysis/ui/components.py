from __future__ import annotations
import pandas as pd
import streamlit as st
import re

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
# CLEAN, BRANDED CARD + TABLE RENDERERS (use CSS injected in app.py)
# ------------------------------------------------------------------------------

def _fmt_int(v):  # small shared formatters
    return "" if pd.isna(v) else f"{int(v)}"

def _fmt_num(v, d: int = 2):
    return "" if pd.isna(v) else f"{float(v):.{d}f}"

def render_entry_model_table(df: pd.DataFrame, title: str = "Entry Model Performance"):
    """
    Render a simple, brand-aligned entry model performance table.
    Required columns: ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]

    Also supports an alternate label column "Instrument" (used by the Instruments tab),
    which is treated as Entry_Model for display.
    """
    if df is None or df.empty:
        return

    # Allow Instruments tab to reuse this renderer:
    # if Entry_Model missing but Instrument present, treat Instrument as Entry_Model.
    if "Entry_Model" not in df.columns and "Instrument" in df.columns:
        df = df.rename(columns={"Instrument": "Entry_Model"}).copy()

    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if any(c not in df.columns for c in expected):
        return

    header_html = (
        '<th class="text">Entry_Model</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
    )

    rows = []
    for _, r in df.iterrows():
        rows.append(
            "<tr>"
            f'<td class="text">{r.get("Entry_Model","")}</td>'
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>'
            "</tr>"
        )

    st.markdown(f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """, unsafe_allow_html=True)

def render_session_performance_table(df: pd.DataFrame, title: str = "Session Performance"):
    """
    Required columns: ["Session", "Trades", "Win %", "BE %", "Loss %"]
    """
    expected = ["Session", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return

    header_html = (
        '<th class="text">Session</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
    )

    rows = []
    for _, r in df.iterrows():
        rows.append(
            "<tr>"
            f'<td class="text">{r.get("Session","")}</td>'
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>'
            "</tr>"
        )

    st.markdown(f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """, unsafe_allow_html=True)

def render_day_performance_table(df: pd.DataFrame, title: str = "Day Performance (Mon–Fri)"):
    """
    Required columns: ["Day", "Trades", "Win %", "BE %", "Loss %", "Avg RR"]
    """
    expected = ["Day", "Trades", "Win %", "BE %", "Loss %", "Avg RR"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return

    header_html = (
        '<th class="text">Day</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
        '<th class="num">Avg RR</th>'
    )

    rows = []
    for _, r in df.iterrows():
        rows.append(
            "<tr>"
            f'<td class="text">{r.get("Day","")}</td>'
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Avg RR"))}</td>'
            "</tr>"
        )

    st.markdown(f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------------------------ 
# NEW: Confluence Performance Table
# ------------------------------------------------------------------------------

def _infer_confluence_perf(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute performance by Confluence tag, returning:
        [Confluence, Trades, Win %, BE %, Loss %]

    Confluence can come from:
      - explicit 'Confluence' column
      - 'DIV?' / 'Sweep?' yes/no columns
      - 'Entry Confluence' strings/lists
    Outcomes are taken from Outcome Canonical if present, else Outcome.
    """
    empty = pd.DataFrame(
        columns=["Confluence", "Trades", "Win %", "BE %", "Loss %"]
    )
    if df is None or df.empty:
        return empty

    work = df.copy()

    # ---------- build/normalize Confluence column ----------------------------
    def _from_yes_no(val) -> bool:
        if val is None:
            return False
        if isinstance(val, float) and pd.isna(val):
            return False
        s = str(val).strip().lower()
        return s in {"yes", "y", "true", "1"}

    def _classify_row(row):
        # Primary: DIV? / Sweep? style columns
        has_div_col = "DIV?" in row.index
        has_sweep_col = "Sweep?" in row.index
        if has_div_col or has_sweep_col:
            div_flag = _from_yes_no(row.get("DIV?"))
            sweep_flag = _from_yes_no(row.get("Sweep?"))
            if div_flag and sweep_flag:
                return "DIV & Sweep"
            if div_flag and not sweep_flag:
                return "DIV"
            if sweep_flag and not div_flag:
                return "Sweep"
            return None

        # Fallback: Entry Confluence / Confluence text or list
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

    if "Confluence" not in work.columns:
        work["Confluence"] = work.apply(_classify_row, axis=1)

    # Normalize labels to exactly: DIV, Sweep, DIV & Sweep
    def _norm_conf(v):
        s = str(v).strip().lower()
        if not s:
            return None
        if "div & sweep" in s or ("div" in s and "sweep" in s):
            return "DIV & Sweep"
        if "div" in s:
            return "DIV"
        if "sweep" in s:
            return "Sweep"
        return None

    work["Confluence"] = work["Confluence"].map(_norm_conf)
    work = work[work["Confluence"].notna()]
    if work.empty:
        return empty

    # ---------- normalize outcome column ------------------------------------
    outcome_col = None
    if "Outcome Canonical" in work.columns:
        outcome_col = "Outcome Canonical"
    elif "Outcome" in work.columns:
        outcome_col = "Outcome"
    else:
        return empty

    work[outcome_col] = work[outcome_col].astype(str).strip().str.lower()

    def _norm_outcome(x):
        s = str(x).strip().lower()
        if s in {"win", "tp", "take profit", "won"}:
            return "Win"
        if s in {"be", "b/e", "break even", "breakeven", "break-even"}:
            return "BE"
        if s in {"loss", "lose", "lost", "sl", "stop loss"}:
            return "Loss"
        return None

    work["_OutcomeNorm"] = work[outcome_col].map(_norm_outcome)
    work = work[work["_OutcomeNorm"].notna()]
    if work.empty:
        return empty

    # ---------- aggregate stats ---------------------------------------------
    gb = work.groupby("Confluence")["_OutcomeNorm"]

    trades = gb.size().rename("Trades")
    win = gb.apply(lambda s: (s == "Win").mean() * 100.0).rename("Win %")
    be = gb.apply(lambda s: (s == "BE").mean() * 100.0).rename("BE %")
    loss = gb.apply(lambda s: (s == "Loss").mean() * 100.0).rename("Loss %")

    out = pd.concat([trades, win, be, loss], axis=1).reset_index()

    # Keep only the three main options and order them nicely
    order = ["DIV", "Sweep", "DIV & Sweep"]
    out = out[out["Confluence"].isin(order)].copy()
    if out.empty:
        return empty

    out["Confluence"] = pd.Categorical(out["Confluence"], categories=order, ordered=True)
    out = out.sort_values("Confluence").reset_index(drop=True)

    for col in ["Win %", "BE %", "Loss %"]:
        out[col] = out[col].round(2)

    return out

def render_confluence_performance_table(df: pd.DataFrame, title: str = "Confluence Performance"):
    """
    Brand-aligned performance table for Confluence.
    Mirrors Entry Model Performance style.
    Expects a *raw trades* dataframe; aggregation is handled inside.
    """
    perf = _infer_confluence_perf(df)
    if perf.empty:
        st.info("No confluence data available.")
        return

    expected = ["Confluence", "Trades", "Win %", "BE %", "Loss %"]
    if any(c not in perf.columns for c in expected):
        return

    header_html = (
        '<th class="text">Confluence</th>'
        '<th class="num">Trades</th>'
        '<th class="num">Win %</th>'
        '<th class="num">BE %</th>'
        '<th class="num">Loss %</th>'
    )

    rows = []
    for _, r in perf.iterrows():
        rows.append(
            "<tr>"
            f'<td class="text">{r.get("Confluence","")}</td>'
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>'
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>'
            "</tr>"
        )

    st.markdown(f"""
    <div class="entry-card">
      <h2>{title}</h2>
      <div class="table-wrap">
        <table class="entry-model-table">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </div>
    """, unsafe_allow_html=True)

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
