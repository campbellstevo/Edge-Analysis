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

def _fmt_int(v):
    return "" if pd.isna(v) else f"{int(v)}"

def _fmt_num(v, d: int = 2):
    return "" if pd.isna(v) else f"{float(v):.{d}f}"

def render_entry_model_table(df: pd.DataFrame, title: str = "Entry Model Performance"):
    if df is None or df.empty:
        return
    if "Entry_Model" not in df.columns and "Instrument" in df.columns:
        df = df.rename(columns={"Instrument": "Entry_Model"}).copy()
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if any(c not in df.columns for c in expected):
        return
    headers = [
        '<th class="text">Entry_Model</th>',
        '<th class="num">Trades</th>',
        '<th class="num">Win %</th>',
        '<th class="num">BE %</th>',
        '<th class="num">Loss %</th>',
    ]
    if "Net PnL (R)" in df.columns:
        headers.append('<th class="num">Net PnL (R)</th>')
    if "Expectancy (R)" in df.columns:
        headers.append('<th class="num">Expectancy (R)</th>')
    header_html = "".join(headers)
    rows = []
    for _, r in df.iterrows():
        row_cells = [
            f'<td class="text">{r.get("Entry_Model","")}</td>',
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>',
        ]
        if "Net PnL (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Net PnL (R)"))}</td>')
        if "Expectancy (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Expectancy (R)"))}</td>')
        rows.append(f"<tr>{''.join(row_cells)}</tr>")
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
    expected = ["Session", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    headers = [
        '<th class="text">Session</th>',
        '<th class="num">Trades</th>',
        '<th class="num">Win %</th>',
        '<th class="num">BE %</th>',
        '<th class="num">Loss %</th>',
    ]
    if "Net PnL (R)" in df.columns:
        headers.append('<th class="num">Net PnL (R)</th>')
    if "Expectancy (R)" in df.columns:
        headers.append('<th class="num">Expectancy (R)</th>')
    header_html = "".join(headers)
    rows = []
    for _, r in df.iterrows():
        row_cells = [
            f'<td class="text">{r.get("Session","")}</td>',
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>',
        ]
        if "Net PnL (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Net PnL (R)"))}</td>')
        if "Expectancy (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Expectancy (R)"))}</td>')
        rows.append(f"<tr>{''.join(row_cells)}</tr>")
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
    expected = ["Day", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    headers = [
        '<th class="text">Day</th>',
        '<th class="num">Trades</th>',
        '<th class="num">Win %</th>',
        '<th class="num">BE %</th>',
        '<th class="num">Loss %</th>',
    ]
    if "Net PnL (R)" in df.columns:
        headers.append('<th class="num">Net PnL (R)</th>')
    if "Expectancy (R)" in df.columns:
        headers.append('<th class="num">Expectancy (R)</th>')
    header_html = "".join(headers)
    rows = []
    for _, r in df.iterrows():
        row_cells = [
            f'<td class="text">{r.get("Day","")}</td>',
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>',
        ]
        if "Net PnL (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Net PnL (R)"))}</td>')
        if "Expectancy (R)" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Expectancy (R)"))}</td>')
        rows.append(f"<tr>{''.join(row_cells)}</tr>")
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

def render_timeframe_table(df: pd.DataFrame, title: str = "Timeframe Performance"):
    """
    Required columns: Entry_Model, Trades, Win %, BE %, Loss %
    Optional: Avg RR, Profit Factor
    """
    expected = ["Entry_Model", "Trades", "Win %", "BE %", "Loss %"]
    if df is None or df.empty or any(c not in df.columns for c in expected):
        return
    headers = [
        '<th class="text">Timeframe</th>',
        '<th class="num">Trades</th>',
        '<th class="num">Win %</th>',
        '<th class="num">BE %</th>',
        '<th class="num">Loss %</th>',
    ]
    if "Avg RR" in df.columns:
        headers.append('<th class="num">Avg RR</th>')
    if "Profit Factor" in df.columns:
        headers.append('<th class="num">Profit Factor</th>')
    header_html = "".join(headers)
    rows = []
    for _, r in df.iterrows():
        row_cells = [
            f'<td class="text">{r.get("Entry_Model","")}</td>',
            f'<td class="num">{_fmt_int(r.get("Trades"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Win %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("BE %"))}</td>',
            f'<td class="num">{_fmt_num(r.get("Loss %"))}</td>',
        ]
        if "Avg RR" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Avg RR"))}</td>')
        if "Profit Factor" in df.columns:
            row_cells.append(f'<td class="num">{_fmt_num(r.get("Profit Factor"))}</td>')
        rows.append(f"<tr>{''.join(row_cells)}</tr>")
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
