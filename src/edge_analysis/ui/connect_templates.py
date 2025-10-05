from __future__ import annotations
from pathlib import Path
import pandas as pd
import streamlit as st
from edge_analysis.data.template_adapter import adapt_auto

# Notion template links (yours)
MY_NOTION_TEMPLATE_URL = "https://lumpy-zone-638.notion.site/27d77800f9cb8187ba04f3ed2336a581?v=27d77800f9cb81d2bd55000c05303a28&source=copy_link"
TRADINGPOOLS_TEMPLATE_URL = "https://hallowed-silicon-4e7.notion.site/2743b411646e8039b4d1e70637ff8c80?v=2743b411646e817e94b4000c5bacc90a&source=copy_link"

def render_connect_notion_templates_ui():
    st.subheader("Templates (Notion)")

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

    if not up:
        return

    # Save uploaded file (handy for debugging)
    uploads = Path("uploads"); uploads.mkdir(parents=True, exist_ok=True)
    fpath = uploads / up.name
    with open(fpath, "wb") as f:
        f.write(up.getbuffer())

    # Normalize to canonical schema regardless of source template
    df, mapping_name = adapt_auto(fpath, "config/templates")
    if mapping_name:
        st.success(f"Detected template: **{mapping_name}**")
    else:
        st.warning("No mapping detected. Ensure the header row is intact in your export.")

    # Quick sanity checks
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

    # Preview first rows
    st.dataframe(df.head(25), use_container_width=True)

    # Make uploaded data available app-wide (Dashboard can prefer this)
    st.session_state["uploaded_df"] = df.copy()
    st.info(
        "Data loaded for this session. Open the **Dashboard** to view analytics.  "
        "You can clear it later to fall back to Notion."
    )

    # Optional: clear uploaded data
    if st.button("Clear uploaded data"):
        st.session_state.pop("uploaded_df", None)
        st.info("Cleared uploaded data for this session.")
