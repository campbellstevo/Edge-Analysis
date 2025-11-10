from __future__ import annotations
from typing import Any, Dict, List, Optional
import re
import pandas as pd
from notion_client.errors import APIResponseError
from notion_client import Client

# ---- simple property flattener (Notion → plain dict) ----
def _flatten_props(props: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in props.items():
        t = v.get("type")
        if t == "title":
            out[k] = " ".join([r.get("plain_text", "") for r in v.get("title", [])]).strip()
        elif t == "rich_text":
            out[k] = " ".join([r.get("plain_text", "") for r in v.get("rich_text", [])]).strip()
        elif t == "select":
            out[k] = (v.get("select") or {}).get("name")
        elif t == "multi_select":
            out[k] = ", ".join([s.get("name", "") for s in v.get("multi_select", []) if s.get("name")])
        elif t == "number":
            out[k] = v.get("number")
        elif t == "date":
            out[k] = (v.get("date") or {}).get("start")
        elif t == "checkbox":
            out[k] = bool(v.get("checkbox"))
        elif t == "people":
            out[k] = ", ".join([p.get("name", "") for p in v.get("people", []) if p.get("name")])
        elif t == "status":
            out[k] = (v.get("status") or {}).get("name")
        elif t == "url":
            out[k] = v.get("url")
        else:
            out[k] = None
    return out

# ---- helpers / mapping ----
DATE_FIELDS    = ["Day/Time/Date of Trade", "Date"]
PAIR_FIELDS    = ["Pair", "Instrument"]
SESSION_FIELDS = ["Session"]  # we trust this from the template
ENTRY_FIELDS   = ["Entry Model"]
RESULT_FIELDS  = ["Result"]
RR_FIELDS      = ["Closed RR"]
PNL_FIELDS     = ["PnL"]

def _first_nonempty(row: Dict[str, Any], fields: List[str]) -> Optional[str]:
    for f in fields:
        val = row.get(f)
        if val not in (None, "", "NaN"):
            return val
    return None

# ---- Session cleaner: use template value, no time-based logic ----
def _clean_session_value(v):
    """
    Normalise session values coming from the Notion template.
    We do NOT derive anything from the time – we just clean the label.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    s_lower = s.lower()
    if "asia" in s_lower:
        return "Asia"
    if "london" in s_lower:
        return "London"
    if "new york" in s_lower or s_lower in {"ny", "ny session"}:
        return "New York"
    # Any other custom label, just return as-is
    return s

# RR parsing: ranges like "+9-10" -> 9.5; "9–10" -> 9.5; "-1 to -2" -> -1.5
_RR_RANGE_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*([+-]?\d+(?:\.\d+)?)', re.I)
def parse_closed_rr(x):
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return float("nan")
    s = str(x).strip()
    if not s:
        return float("nan")
    m = _RR_RANGE_RE.search(s)
    if m:
        a = float(m.group(1)); b = float(m.group(2))
        return (a + b) / 2.0
    try:
        return float(s.replace("+", ""))
    except Exception:
        return float("nan")

# ---- NEW: build Confluence from checkbox flags ----
def _build_confluence_from_flags_df(df: pd.DataFrame) -> Optional[pd.Series]:
    """
    Look for checkbox columns for DIV / Sweep and build a single
    'Confluence' series:
      - DIV & Sweep
      - DIV
      - Sweep
      - None
    Supports column names: DIV?, DIV, Sweep?, Sweep (case-insensitive).
    """
    if df is None or df.empty:
        return None

    cols_lower = {str(c).strip().lower(): c for c in df.columns}

    div_col = cols_lower.get("div?") or cols_lower.get("div")
    sweep_col = cols_lower.get("sweep?") or cols_lower.get("sweep")

    if not div_col and not sweep_col:
        # no flags present, nothing to build
        return None

    def _calc(row: pd.Series):
        has_div = bool(row.get(div_col)) if div_col else False
        has_sweep = bool(row.get(sweep_col)) if sweep_col else False

        if has_div and has_sweep:
            return "DIV & Sweep"
        if has_div:
            return "DIV"
        if has_sweep:
            return "Sweep"
        return None

    return df.apply(_calc, axis=1)

# ---- main loader ----
def load_trades_from_notion(
    token: Optional[str],
    database_id: Optional[str],
    page_size: int = 100,
) -> pd.DataFrame:
    # Safety: if creds are missing, don't even try
    if not token or not database_id:
        print("[edge_analysis] Missing Notion token or database_id.")
        return pd.DataFrame()

    # Debug: which notion_client is actually imported?
    try:
        import notion_client as nc  # type: ignore
        print(
            "[edge_analysis] notion_client module:",
            getattr(nc, "__file__", "<?>"),
            "version:",
            getattr(nc, "__version__", "<?>"),
        )
    except Exception as e:
        print(f"[edge_analysis] Could not introspect notion_client module: {e!r}")

    # Create client
    try:
        client = Client(auth=token)
    except Exception as e:
        # Log to Streamlit/Cloud logs but don't crash the app
        print(f"[edge_analysis] Failed to create Notion client: {e!r}")
        return pd.DataFrame()

    # Defensive checks around databases endpoint
    if not hasattr(client, "databases"):
        print(f"[edge_analysis] Client missing 'databases' attribute: {type(client)}")
        return pd.DataFrame()

    if not hasattr(client.databases, "query"):
        print(
            "[edge_analysis] client.databases has no 'query' method.",
            "Type:", type(client.databases),
            "Dir:", dir(client.databases),
        )
        return pd.DataFrame()

    results: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None

    while True:
        try:
            resp = client.databases.query(
                database_id=database_id,
                page_size=page_size,
                start_cursor=next_cursor,
            )
        except APIResponseError as e:
            print(
                f"[edge_analysis] APIResponseError while querying Notion DB {database_id}: "
                f"status={getattr(e, 'status', None)}, "
                f"code={getattr(e, 'code', None)}, "
                f"message={getattr(e, 'message', None)}, "
                f"body={getattr(e, 'body', None)}"
            )
            return pd.DataFrame()
        except Exception as e:
            print(f"[edge_analysis] Unexpected Notion query error: {e!r}")
            return pd.DataFrame()

        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        next_cursor = resp.get("next_cursor")

    rows = [_flatten_props(r.get("properties", {})) for r in results]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=["Date", "Pair", "Session", "Entry Model", "Result", "Closed RR", "PnL", "Confluence"]
        )

    out = pd.DataFrame()
    out["Date"] = pd.to_datetime(
        df.apply(lambda r: _first_nonempty(r, DATE_FIELDS), axis=1),
        errors="coerce",
        utc=True
    ).dt.tz_localize(None)

    out["Pair"] = df.apply(lambda r: _first_nonempty(r, PAIR_FIELDS), axis=1)

    # 🔑 Session pulled directly from template + cleaned
    out["Session"] = df.apply(
        lambda r: _clean_session_value(_first_nonempty(r, SESSION_FIELDS)),
        axis=1
    )

    out["Entry Model"] = df.apply(lambda r: _first_nonempty(r, ENTRY_FIELDS), axis=1)
    out["Result"]      = df.apply(lambda r: _first_nonempty(r, RESULT_FIELDS), axis=1)
    out["Closed RR"]   = df.apply(lambda r: parse_closed_rr(_first_nonempty(r, RR_FIELDS)), axis=1)
    out["PnL"]         = pd.to_numeric(
        df.apply(lambda r: _first_nonempty(r, PNL_FIELDS),
        axis=1),
        errors="coerce"
    )

    # 🔁 pass checkbox flags through so template_adapter can see them
    for flag_name in ["DIV?", "DIV", "Sweep?", "Sweep"]:
        if flag_name in df.columns and flag_name not in out.columns:
            out[flag_name] = df[flag_name]

    # 🧠 Optional: build Confluence directly for downstream tabs
    conf_series = _build_confluence_from_flags_df(df)
    if conf_series is not None:
        out["Confluence"] = conf_series

    return out
