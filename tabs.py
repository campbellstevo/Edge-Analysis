from __future__ import annotations
import sys
from pathlib import Path

# Add src directory to Python path
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
import re
import os
from datetime import time as dt_time
from zoneinfo import ZoneInfo

# NEW: import the three clean renderers from components
from edge_analysis.ui.components import (
    render_entry_model_table,
    render_session_performance_table,
    render_day_performance_table,
)

# PATCH: auto-detect adapter for multiple templates
from edge_analysis.data.template_adapter import adapt_auto

CONFLUENCE_OPTIONS = ["DIV", "Sweep", "DIV & Sweep"]


def _asset_label(name: str) -> str:
    return "GOLD" if str(name) == "Gold" else str(name)


# ... [rest of the file remains exactly the same]
