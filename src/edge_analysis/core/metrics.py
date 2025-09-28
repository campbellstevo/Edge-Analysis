from __future__ import annotations 

import pandas as pd
from ..schema import (
    COL_DATE,
    COL_SESSION,
    COL_RESULT,
    COL_CLOSED_RR,
    RESULT_WIN,
    RESULT_BE,
    RESULT_LOSS,
)

# ---------- helpers already in your code ----------
def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard columns exist and types are consistent."""
    if df is None:
        return pd.DataFrame(columns=[COL_DATE, COL_SESSION, COL_RESULT, COL_CLOSED_RR])
    out = df.copy()
    if COL_DATE in out.columns:
        out[COL_DATE] = pd.to_datetime(out[COL_DATE], errors="coerce")
    return out


def win_be_loss_counts(df: pd.DataFrame) -> dict[str, int]:
    """Count Win/BE/Loss outcomes."""
    if df is None or df.empty or COL_RESULT not in df.columns:
        return {RESULT_WIN: 0, RESULT_BE: 0, RESULT_LOSS: 0}
    series = df[COL_RESULT].fillna("")
    return {
        RESULT_WIN: int((series == RESULT_WIN).sum()),
        RESULT_BE: int((series == RESULT_BE).sum()),
        RESULT_LOSS: int((series == RESULT_LOSS).sum()),
    }


def percentages_sum_to_100(wins: int, bes: int, losses: int) -> dict[str, float]:
    """Calculate Win/BE/Loss % (two decimals) that add up to 100.00."""
    total = wins + bes + losses
    if total <= 0:
        return {RESULT_WIN: 0.00, RESULT_BE: 0.00, RESULT_LOSS: 0.00}

    win_p = (wins / total) * 100.0
    be_p  = (bes  / total) * 100.0
    loss_p= (losses / total) * 100.0

    # Round to 2 decimals
    w, b, l = round(win_p, 2), round(be_p, 2), round(loss_p, 2)

    # Adjust rounding drift so sum = 100.00
    drift = round(100.00 - (w + b + l), 2)
    if drift != 0.0:
        if w >= b and w >= l:
            w = round(w + drift, 2)
        elif b >= w and b >= l:
            b = round(b + drift, 2)
        else:
            l = round(l + drift, 2)

    return {RESULT_WIN: w, RESULT_BE: b, RESULT_LOSS: l}


def pnl_from_closed_rr(df: pd.DataFrame) -> float:
    """Sum of Closed RR but only for winning trades."""
    if df is None or df.empty:
        return 0.0
    if COL_CLOSED_RR not in df.columns or COL_RESULT not in df.columns:
        return 0.0
    wins = df[df[COL_RESULT] == RESULT_WIN]
    return float(wins[COL_CLOSED_RR].fillna(0).sum())


def group_win_rates(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Generic grouping for win/BE/loss % by column(s)."""
    if df is None or df.empty:
        return pd.DataFrame()

    dfn = _normalize_df(df)
    if COL_RESULT not in dfn.columns:
        return pd.DataFrame()

    groups = []
    for keys, g in dfn.groupby(by):
        counts = win_be_loss_counts(g)
        perc = percentages_sum_to_100(
            counts[RESULT_WIN], counts[RESULT_BE], counts[RESULT_LOSS]
        )
        row = {}
        if isinstance(keys, tuple):
            for k, v in zip(by, keys):
                row[k] = v
        else:
            row[by[0]] = keys
        row.update(
            {
                "Trades": len(g),
                "Win %": perc[RESULT_WIN],
                "BE %": perc[RESULT_BE],
                "Loss %": perc[RESULT_LOSS],
            }
        )
        groups.append(row)

    return pd.DataFrame(groups)


# ---------- your existing compute_overview ----------
def compute_overview(df: pd.DataFrame) -> dict:
    counts = win_be_loss_counts(df)
    perc = percentages_sum_to_100(
        counts[RESULT_WIN], counts[RESULT_BE], counts[RESULT_LOSS]
    )
    return {
        "counts": counts,
        "percentages": {
            "Win %": perc[RESULT_WIN],
            "BE %": perc[RESULT_BE],
            "Loss %": perc[RESULT_LOSS],
        },
        "pnl_rr_wins_only": pnl_from_closed_rr(df),
    }


# ---------- NEW ADDITIONS ----------
def group_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Win/BE/Loss and percentages grouped by Session."""
    return group_win_rates(df, by=[COL_SESSION])


def cumulative_rr_by_day(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with Date and CumPnL (Closed RR summed per day, cumulative)."""
    dfn = _normalize_df(df)
    if COL_DATE not in dfn.columns or COL_CLOSED_RR not in dfn.columns:
        return pd.DataFrame(columns=[COL_DATE, "CumPnL"])

    g = dfn.copy()
    g[COL_DATE] = pd.to_datetime(g[COL_DATE], errors="coerce")
    g = g.dropna(subset=[COL_DATE])
    if g.empty:
        return pd.DataFrame(columns=[COL_DATE, "CumPnL"])

    g["Bucket"] = g[COL_DATE].dt.floor("D")
    daily = (
        g.groupby("Bucket", as_index=False)[COL_CLOSED_RR]
        .sum()
        .rename(columns={COL_CLOSED_RR: "PnLBucket"})
    )
    daily["CumPnL"] = daily["PnLBucket"].fillna(0).cumsum()
    return daily.rename(columns={"Bucket": COL_DATE})[[COL_DATE, "CumPnL"]]
