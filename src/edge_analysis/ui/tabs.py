from __future__ import annotations
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

# NEW: import the three clean renderers from components
from edge_analysis.ui.components import (
    render_entry_model_table,
    render_session_performance_table,
    render_day_performance_table,
)

CONFLUENCE_OPTIONS = ["DIV", "Sweep", "DIV & Sweep"]

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
            out.loc[mask_nan, "Closed RR"] = out.loc[mask_nan, "Closed RR Num"]

    return out


def outcome_rates_from(df):
    if df.empty or 'Outcome' not in df.columns:
        return dict(total=0, counted=0, wins=0, bes=0, losses=0, win_rate=0.0, be_rate=0.0, loss_rate=0.0)
    counted = df[df['Outcome'].isin(['Win', 'BE', 'Loss'])]
    counted_n = len(counted)
    wins  = int(counted['Outcome'].eq("Win").sum())
    bes   = int(counted['Outcome'].eq("BE").sum())
    losses= int(counted['Outcome'].eq("Loss").sum())
    wr = round((wins   / max(1, counted_n)) * 100.0, 2)
    br = round((bes    / max(1, counted_n)) * 100.0, 2)
    lr = round((losses / max(1, counted_n)) * 100.0, 2)
    return dict(total=len(df), counted=counted_n, wins=wins, bes=bes, losses=losses,
                win_rate=wr, be_rate=br, loss_rate=lr)

def generate_overall_stats(df: pd.DataFrame):
    if df.empty:
        return dict(total=0,wins=0,losses=0,bes=0,win_rate=0.0,loss_rate=0.0,be_rate=0.0,avg_rr=0.0,avg_pnl=0.0,total_pnl=0.0,unknown=0)
    rates = outcome_rates_from(df)
    unknown = rates['total'] - rates['counted']

    # Avg Closed RR from winning trades only
    if {'Closed RR','Outcome'} <= set(df.columns):
        wins_only = df[df['Outcome'] == 'Win']
        avg_rr = float(wins_only['Closed RR'].mean()) if not wins_only.empty and not wins_only['Closed RR'].isna().all() else 0.0
    else:
        avg_rr = 0.0

    avg_pnl = float(df['PnL'].mean()) if 'PnL' in df.columns and not df['PnL'].isna().all() else 0.0
    total_pnl = float(df['PnL'].sum()) if 'PnL' in df.columns and not df['PnL'].isna().all() else 0.0
    return dict(total=rates['total'],wins=rates['wins'],losses=rates['losses'],bes=rates['bes'],
                win_rate=rates['win_rate'],loss_rate=rates['loss_rate'],be_rate=rates['be_rate'],
                avg_rr=avg_rr,avg_pnl=avg_pnl,total_pnl=total_pnl,unknown=unknown)

def _to_alt_values(df: pd.DataFrame):
    if df is None or len(df)==0: return []
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

# ───────────────────────────── Growth (patched to auto-detect date col) ──────
def _growth_tab(f: pd.DataFrame, df_all: pd.DataFrame, styler):
    st.markdown('<div class="section">', unsafe_allow_html=True)

    # Use ONLY the complete slice
    if f is None or f.empty:
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown('</div>', unsafe_allow_html=True); return

    g = f.copy()

    # --- Find a usable date column ---
    date_col = None
    if 'Date' in g.columns:
        date_col = 'Date'
    else:
        for c in g.columns:
            cl = str(c).strip().lower()
            if cl == 'date' or 'date' in cl or 'time' in cl:
                date_col = c
                break

    if not date_col:
        st.warning("No date-like column found in complete trades.")
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown('</div>', unsafe_allow_html=True); return

    # --- Coerce to real datetimes ---
    g['__Date'] = (
        g[date_col].astype(str)
                    .str.replace(r"\s*\(GMT.*\)$", "", regex=True)
    )
    g['__Date'] = pd.to_datetime(g['__Date'], errors='coerce')

    # Drop NaT
    g = g[g['__Date'].notna()].copy()
    if g.empty:
        with st.expander("Debug: date parsing", expanded=False):
            try:
                st.write("Sample raw values:", f[date_col].head(5).tolist())
            except Exception:
                pass
        st.info("No dated rows yet. Add some trades or adjust filters.")
        st.markdown('</div>', unsafe_allow_html=True); return

    # Remove timezone if present
    try:
        if getattr(g['__Date'].dt, 'tz', None) is not None:
            g['__Date'] = g['__Date'].dt.tz_localize(None)
    except Exception:
        pass

    # Ensure PnL_from_RR exists (prefer numeric RR if present)
    if 'PnL_from_RR' not in g.columns:
        rr_col = 'Closed RR Num' if 'Closed RR Num' in g.columns else 'Closed RR'
        g['PnL_from_RR'] = g.get(rr_col, 0.0).fillna(0.0)

    # Controls
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        bucket = st.selectbox("Time Bucket", ["Day", "Week", "Month"], index=1, key="growth_bucket")
    with c2:
        wr_mode = st.selectbox("Win Rate Mode", ["Cumulative", "Rolling (7 trades)"], index=0, key="growth_wr")

    # Sort and bucket
    g = g.sort_values('__Date').copy()
    if bucket == "Day":
        g['Bucket'] = g['__Date'].dt.floor("D"); axis_fmt = "%b %d"
    elif bucket == "Week":
        per = g['__Date'].dt.to_period("W-MON")
        g = g[per.notna()].copy()
        g['Bucket'] = per[per.notna()].apply(lambda r: r.start_time); axis_fmt = "%b %d"
    else:
        per = g['__Date'].dt.to_period("M")
        g = g[per.notna()].copy()
        g['Bucket'] = per[per.notna()].apply(lambda r: r.start_time); axis_fmt = "%b %Y"

    # Equity (RR)
    eq_df = g.groupby('Bucket', as_index=False)['PnL_from_RR'].sum().rename(columns={'PnL_from_RR':'PnLBucket'})
    eq_df['CumPnL'] = eq_df['PnLBucket'].fillna(0).cumsum()

    x_time = alt.X('Bucket:T', title=None, axis=alt.Axis(format=axis_fmt, labelAngle=0, labelLimit=140), scale=alt.Scale(nice=False, padding=0))
    pnl_vals = _to_alt_values(eq_df[['Bucket', 'CumPnL']])

    # Win rate
    wr = g[['__Date', 'Bucket', 'Outcome']].dropna()
    wr = wr[wr['Outcome'].isin(['Win', 'BE', 'Loss'])]
    wr_vals = []
    if not wr.empty:
        if wr_mode == "Cumulative":
            wr2 = wr.groupby('Bucket').agg(trades=('Outcome','count'), wins=('Outcome', lambda s: (s=="Win").sum())).reset_index()
            wr2['CumTrades'] = wr2['trades'].cumsum(); wr2['CumWins'] = wr2['wins'].cumsum()
            wr2['Win %'] = np.where(wr2['CumTrades']>0, (wr2['CumWins']/wr2['CumTrades'])*100.0, 0.0)
            wr_plot = wr2[['Bucket','Win %']].copy()
        else:
            wr_sorted = wr.sort_values('__Date').copy()
            wr_sorted['IsWin'] = wr_sorted['Outcome'].eq("Win").astype(float)
            wr_sorted['Rolling Win %'] = wr_sorted.groupby('Bucket')['IsWin'].apply(lambda s: s.rolling(7, min_periods=1).mean()*100.0).values
            wr_plot = wr_sorted.groupby('Bucket', as_index=False).apply(lambda x: x.iloc[-1]).reset_index(drop=True)[['Bucket','Rolling Win %']].rename(columns={'Rolling Win %':'Win %'})
        wr_plot['Win %'] = wr_plot['Win %'].round(2)
        wr_vals = _to_alt_values(wr_plot[['Bucket','Win %']])

    # Charts
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("### Cumulative PnL (RR)")
        if pnl_vals:
            area = alt.Chart(alt.Data(values=pnl_vals)).mark_area(opacity=0.12, color="#4800ff").encode(x=x_time, y=alt.Y('CumPnL:Q', title='Cumulative PnL (RR)'))
            line = alt.Chart(alt.Data(values=pnl_vals)).mark_line(strokeWidth=2, color="#4800ff", interpolate='linear').encode(x=x_time, y='CumPnL:Q')
            st.altair_chart(styler(alt.layer(area, line).properties(height=320)), use_container_width=True)
        else:
            st.info("Not enough data for PnL chart.")
    with c_right:
        st.markdown("### Win Rate (%)")
        if wr_vals:
            line_color = "#0f172a" if st.session_state.get("ui_theme","light") == "light" else "#e5e7eb"
            xwr = alt.X('Bucket:T', title=None, axis=alt.Axis(format=axis_fmt, labelAngle=0, labelLimit=140), scale=alt.Scale(nice=False, padding=0))
            line = alt.Chart(alt.Data(values=wr_vals)).mark_line(strokeWidth=2, color=line_color, interpolate='linear').encode(x=xwr, y=alt.Y('Win %:Q', title='Win Rate (%)', scale=alt.Scale(domain=[0,100]))).properties(height=320)
            st.altair_chart(styler(line), use_container_width=True)
        else:
            st.info("Not enough data for Win Rate chart.")

    latest_wr = float(pd.DataFrame(wr_vals)['Win %'].dropna().iloc[-1]) if wr_vals else float('nan')
    latest_eq = float(pd.DataFrame(pnl_vals)['CumPnL'].dropna().iloc[-1]) if pnl_vals else float('nan')
    st.markdown(f"<div class='muted'>Latest Win %: <b>{latest_wr:.2f}%</b> &nbsp;|&nbsp; Cumulative PnL: <b>{latest_eq:,.2f} R</b></div>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------ Other tabs -----------------------------------
def _entry_models_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    # Title comes from the renderer; don't duplicate here
    if f.empty:
        st.info("No trades for current filters.")
    else:
        em = f.explode('Entry Models List')
        em = em[em['Entry Models List'].notna()]
        if em.empty:
            st.info("No entry model data.")
        else:
            rates = []
            counted = em[em['Outcome'].isin(['Win','BE','Loss'])]
            for model, group in counted.groupby('Entry Models List'):
                r = outcome_rates_from(group)
                rates.append(dict(Entry_Model=model, Trades=len(group), **{"Win %": r['win_rate'], "BE %": r['be_rate'], "Loss %": r['loss_rate']}))
            if rates:
                entry_model_df = pd.DataFrame(rates).sort_values('Win %', ascending=False)
                render_entry_model_table(entry_model_df, title="Entry Model Performance")
            else:
                st.info("No counted outcomes yet.")
    st.markdown('</div>', unsafe_allow_html=True)

def _sessions_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    # Title comes from the renderer
    if f.empty or 'Session Norm' not in f.columns or f['Session Norm'].isna().all():
        st.info("No session data.")
    else:
        counted = f[f['Outcome'].isin(['Win','BE','Loss'])]
        rates=[]
        for sess, g in counted.groupby('Session Norm'):
            r = outcome_rates_from(g)
            rates.append(dict(Session=sess, Trades=len(g), **{"Win %": r['win_rate'], "BE %": r['be_rate'], "Loss %": r['loss_rate']}))
        session_df = pd.DataFrame(rates).sort_values('Win %', ascending=False)
        render_session_performance_table(session_df, title="Session Performance")
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- Days-only (Mon–Fri), no hours/duration in this tab ----------
def _time_days_tab(f: pd.DataFrame, show_table):
    st.markdown('<div class="section">', unsafe_allow_html=True)
    # Title comes from the renderer
    counted = f[f['Outcome'].isin(['Win','BE','Loss'])]

    # Prefer DayName if present; else fall back to a 'Day' column
    day_col = 'DayName' if 'DayName' in counted.columns else ('Day' if 'Day' in counted.columns else None)
    if not day_col or counted.empty:
        st.info("No day-of-week signal in current slice.")
        st.markdown('</div>', unsafe_allow_html=True); return

    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    df_days = counted[counted[day_col].isin(order)].copy()
    if df_days.empty:
        st.info("No Mon–Fri data in current slice.")
        st.markdown('</div>', unsafe_allow_html=True); return

    df_days['__Day'] = pd.Categorical(df_days[day_col], categories=order, ordered=True)

    perf = (df_days.groupby('__Day').apply(lambda g: pd.Series({
        "Trades": len(g),
        "Win %": round((g['Outcome'].eq("Win").mean() * 100.0), 2),
        "BE %":  round((g['Outcome'].eq("BE").mean()  * 100.0), 2),
        "Loss %":round((g['Outcome'].eq("Loss").mean()* 100.0), 2),
        "Avg RR": round(g['Closed RR'].mean(), 2) if 'Closed RR' in g.columns else None
    })).reset_index().rename(columns={'__Day': 'Day'}))

    day_df = perf.sort_values('Day')
    render_day_performance_table(day_df, title="Day Performance (Mon–Fri)")
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- (Unused for now) Confluence & Coach tabs kept for later ----------
def _confluence_tab(f: pd.DataFrame, show_table):
    # kept for future use; not referenced in render_all_tabs
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Confluence: DIV, Sweep, DIV & Sweep")
    st.info("This tab is disabled for now.")
    st.markdown('</div>', unsafe_allow_html=True)

def _coach_tab(f: pd.DataFrame):
    # kept for future use; not referenced in render_all_tabs
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("## Edge Coach (disabled for now)")
    st.info("Coach is hidden for now.")
    st.markdown('</div>', unsafe_allow_html=True)

# ----------------------- Data tab (uses FILTERED-ALL) -----------------------
def _data_tab(f_all: pd.DataFrame, show_table):
    """
    Show counts of data entries for NASDAQ, GOLD and AUDUSD with
    'Complete' vs 'Incomplete' totals.
    """
    st.markdown('<div class="section">', unsafe_allow_html=True)
    st.markdown("### Data Completeness by Instrument")

    if f_all is None or f_all.empty:
        st.info("No rows for the current filters.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    def _bucket(val: str) -> str | None:
        s = (str(val) if val is not None else "").strip().upper()
        if s in {"NASDAQ", "GOLD", "AUDUSD"}:
            return s
        return None

    g = f_all.copy()
    g["__bucket"] = g["Instrument"].apply(_bucket)
    g = g[g["__bucket"].notna()]
    if g.empty:
        st.info("No entries found for NASDAQ, GOLD or AUDUSD in the current slice.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # Completeness
    if "Is Complete" in g.columns:
        g["__complete"] = g["Is Complete"].fillna(False)
    elif {"Outcome Canonical", "Closed RR Num"} <= set(g.columns):
        has_outcome = g["Outcome Canonical"].isin(["Win", "BE", "Loss"])
        has_rr = g["Closed RR Num"].notna()
        has_date = g["Date"].notna() if "Date" in g.columns else True
        g["__complete"] = has_date & has_outcome & has_rr
    else:
        has_closed_rr = g["Closed RR"].notna() if "Closed RR" in g.columns else False
        has_result = g["Result"].astype(str).str.strip().ne("").fillna(False) if "Result" in g.columns else False
        has_pnl = g["PnL"].notna() if "PnL" in g.columns else False
        has_date = g["Date"].notna() if "Date" in g.columns else False
        g["__complete"] = has_date & (has_closed_rr | has_result | has_pnl)

    wanted = ["NASDAQ", "GOLD", "AUDUSD"]
    out_rows = []
    for name in wanted:
        sub = g[g["__bucket"] == name]
        total = int(len(sub))
        complete = int(sub["__complete"].sum()) if total else 0
        incomplete = total - complete
        out_rows.append({"Instrument": name, "Total": total, "Complete": complete, "Incomplete": incomplete})

    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]
    for col, row in zip(cols, out_rows):
        with col:
            st.markdown(
                f"""
                <div class='kpi'>
                  <div class='label'>{row["Instrument"]}</div>
                  <div class='value'>{row["Total"]}</div>
                  <div class='muted'>Complete: <b>{row["Complete"]}</b></div>
                  <div class='muted'>Incomplete: <b>{row["Incomplete"]}</b></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)

def render_all_tabs(f: pd.DataFrame, df_all: pd.DataFrame, styler, show_table):
    # completion-aware slice
    f_perf = _prep_perf_df(f)
    df_all_safe = df_all.copy() if df_all is not None else df_all

    # Removed Confluence and Coach for now
    t1, t2, t3, t4, t5 = st.tabs(
        ["Growth","Entry Models","Sessions","Time & Days","Data"]
    )
    with t1: _growth_tab(f_perf, df_all_safe, styler)
    with t2: _entry_models_tab(f_perf, show_table)
    with t3: _sessions_tab(f_perf, show_table)
    with t4: _time_days_tab(f_perf, show_table)      # Days only (Mon–Fri)
    with t5: _data_tab(df_all_safe, show_table)      # filtered-all completeness
