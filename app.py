@st.cache_data(show_spinner=True)
def load_live_df(token: str | None, dbid: str | None) -> pd.DataFrame:
    # Safety: no creds → no query
    if not (token and dbid):
        st.caption("Debug: load_live_df called with missing token/dbid")
        return pd.DataFrame()

    st.caption(f"Debug: calling Notion with dbid={dbid}")
    raw = load_trades_from_notion(token, dbid)

    # Show what Notion actually sent back
    if raw is None:
        st.warning("Debug: Notion returned None (no data).")
        return pd.DataFrame()

    st.caption(f"Debug: raw Notion df shape = {raw.shape}")
    st.dataframe(raw.head(10))

    if raw.empty:
        st.warning("Debug: Notion returned 0 rows. Check that the DB link & workspace share are correct.")
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
        df["Entry Confluence List"] = df["Entry Confluence"].fillna("").astype(str).apply(
            lambda s: [x.strip() for x in _re.split(r"[;,]", s) if x.strip()]
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
        df["Risk %"] = df["Risk Management"].astype(str).str.extract(r"(\d+(?:\.\d+)?)\s*%")[0].astype(float)
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
