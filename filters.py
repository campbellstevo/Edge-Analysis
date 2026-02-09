"""
Filter controls module for Edge Analysis.

This module contains helper functions for rendering the various filter
controls used in the dashboard. Extracting these functions into a
separate module helps keep the main application entry point cleaner.
"""

from __future__ import annotations

from typing import Optional, Union, Tuple
from datetime import date as DateType

import streamlit as st
import pandas as pd

# Replicate SessionKeys and PageNames here to avoid circular imports.

class SessionKeys:
    """Session state key constants (replicated from the main app)."""
    OAUTH_TOKEN = "override_NOTION_TOKEN"
    USER_TOKEN = "user_notion_token"
    USER_ID = "user_id"
    DB_ID = "override_DATABASE_ID"
    NAV_PAGE = "nav_page"
    NAV_TARGET = "nav_page_target"
    LAYOUT = "layout_choice"
    OAUTH_PENDING = "oauth_pending"
    OAUTH_CALLBACK = "oauth_callback_code"


class PageNames:
    """Navigation page names (replicated from the main app)."""
    DASHBOARD = "Dashboard"
    CONNECT = "Connect Notion"


# Type alias for date range selection
DateRange = Union[DateType, Tuple[DateType, DateType]]


def apply_date_filter(df: pd.DataFrame, date_range: Optional[DateRange]) -> pd.Series:
    """
    Apply a date range filter to a dataframe and return a boolean mask.

    Args:
        df: DataFrame with a 'Date' column.
        date_range: Either a single date or a tuple (start, end) indicating
            inclusive start and exclusive end dates.

    Returns:
        A boolean Series mask indexing the dataframe.
    """
    if date_range is None:
        return pd.Series(True, index=df.index)

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        return df["Date"].dt.date.between(start, end)

    # Single date selection
    return df["Date"].dt.date == date_range


def render_filters(
    mobile: bool,
    inst_opts: list,
    em_opts: list,
    sess_opts: list,
    date_mode_options: list,
    min_date: DateType,
    max_date: DateType,
) -> Tuple[str, str, str, Optional[DateRange]]:
    """
    Render filter controls for both desktop and mobile layouts.

    This function mirrors the original `_render_filters` but avoids
    dependencies on the main application by reproducing the necessary
    session key and page name constants locally.

    Args:
        mobile: Whether to render in mobile mode.
        inst_opts: List of instrument options.
        em_opts: List of entry model options.
        sess_opts: List of session options.
        date_mode_options: List of date mode options (e.g., "All", "Custom").
        min_date: Minimum date allowed for the date picker.
        max_date: Maximum date allowed for the date picker.

    Returns:
        A tuple containing the selected instrument, selected entry model,
        selected session, and an optional date range (single date or tuple).
    """

    def _inst_label(v: str) -> str:
        return "GOLD" if v == "Gold" else v

    if mobile:
        st.markdown("### Navigation")
        st.selectbox(
            "Page",
            [PageNames.DASHBOARD, PageNames.CONNECT],
            index=0 if st.session_state.get(SessionKeys.NAV_PAGE) == PageNames.DASHBOARD else 1,
            key=SessionKeys.NAV_PAGE,
        )
        st.selectbox(
            "Layout",
            ["Desktop Layout", "Mobile Layout"],
            index=1 if st.session_state.get(SessionKeys.LAYOUT) == "Mobile Layout" else 0,
            key=SessionKeys.LAYOUT,
        )
        st.markdown("### Filters")
        c1, c2 = st.columns(2, gap="small")
        with c1:
            sel_inst = st.selectbox(
                "Instrument",
                inst_opts,
                index=inst_opts.index(st.session_state.get("filters_inst_select", "All"))
                if st.session_state.get("filters_inst_select", "All") in inst_opts
                else 0,
                format_func=_inst_label,
                key="filters_inst_select",
            )
        with c2:
            sel_sess = st.selectbox(
                "Session",
                sess_opts,
                index=sess_opts.index(st.session_state.get("filters_sess_select", "All"))
                if st.session_state.get("filters_sess_select", "All") in sess_opts
                else 0,
                key="filters_sess_select",
            )
        sel_em = st.selectbox(
            "Entry Model",
            em_opts,
            index=em_opts.index(st.session_state.get("filters_em_select", "All"))
            if st.session_state.get("filters_em_select", "All") in em_opts
            else 0,
            key="filters_em_select",
        )
        container = st
    else:
        st.sidebar.markdown("### Filters")
        sel_inst = st.sidebar.selectbox(
            "Instrument",
            inst_opts,
            index=0,
            format_func=_inst_label,
            key="filters_inst_select",
        )
        sel_em = st.sidebar.selectbox(
            "Entry Model",
            em_opts,
            index=0,
            key="filters_em_select",
        )
        sel_sess = st.sidebar.selectbox(
            "Session",
            sess_opts,
            index=0,
            key="filters_sess_select",
        )
        container = st.sidebar

    # Shared date range logic
    current_mode = st.session_state.get("filters_date_mode", "All")
    if current_mode not in date_mode_options:
        current_mode = "All"

    date_mode = container.selectbox(
        "Date range",
        date_mode_options,
        index=date_mode_options.index(current_mode),
        key="filters_date_mode",
    )

    date_range: Optional[DateRange] = None
    if date_mode == "Custom":
        date_range = container.date_input(
            "Custom dates",
            value=st.session_state.get("filters_date_range", (min_date, max_date)),
            key="filters_date_range",
        )

    return sel_inst, sel_em, sel_sess, date_range
