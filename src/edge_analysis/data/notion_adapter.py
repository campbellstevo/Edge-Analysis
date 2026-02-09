from __future__ import annotations
from typing import Any, Dict, List, Optional
import re
import pandas as pd

try:
    from notion_client import Client
except ImportError:
    raise ImportError("notion-client package is required. Install with: pip install notion-client")


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
SESSION_FIELDS = ["Session"]
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


# RR parsing: ranges like "+9-10" -> 9.5; "9—10" -> 9.5; "-1 to -2" -> -1.5
_RR_RANGE_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(?:-|—|to)\s*([+-]?\d+(?:\.\d+)?)', re.I)


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
        a = float(m.group(1))
        b = float(m.group(2))
        return (a + b) / 2.0
    try:
        return float(s.replace("+", ""))
    except Exception:
        return float("nan")


# ---- main loader ----
def load_trades_from_notion(token: str, database_id: str, page_size: int = 100) -> pd.DataFrame:
    """
    Load trades from a Notion database.
    
    Args:
        token: Notion API token (OAuth or integration token)
        database_id: Notion database ID (32-char hex string)
        page_size: Number of results per page (default 100)
    
    Returns:
        DataFrame with all columns from the Notion database
    
    Raises:
        ValueError: If token or database_id is missing
        AttributeError: If notion-client version is incompatible
        RuntimeError: If the Notion API query fails
    """
    # Validate inputs
    if not token:
        raise ValueError("Notion token is required but was not provided")
    if not database_id:
        raise ValueError("Database ID is required but was not provided")
    
    # Initialize Notion client
    try:
        client = Client(auth=token)
    except Exception as e:
        raise ValueError(f"Failed to initialize Notion client: {e}")

    # Query database with pagination
    results: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    
    try:
        while True:
            # Call the Notion API
            resp = client.databases.query(
                database_id=database_id,
                page_size=page_size,
                start_cursor=next_cursor
            )
            
            results.extend(resp.get("results", []))
            
            # Check if there are more pages
            if not resp.get("has_more"):
                break
            next_cursor = resp.get("next_cursor")
            
    except AttributeError as e:
        # This usually means the notion-client version is wrong
        raise AttributeError(
            f"Notion client error - the 'databases' attribute is missing. "
            f"This may be due to an outdated or incompatible notion-client version. "
            f"Please ensure notion-client==2.2.1 is installed. "
            f"Original error: {e}"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to query Notion database: {type(e).__name__}: {e}")

    # Flatten Notion properties into simple dicts
    rows = [_flatten_props(r.get("properties", {})) for r in results]
    df = pd.DataFrame(rows)
    
    # Return ALL columns from Notion (preserves DIV?, Sweep?, GAP Alignment, etc.)
    if df.empty:
        return pd.DataFrame(columns=[
            "Date", "Pair", "Session", "Entry Model", "Result", "Closed RR", "PnL"
        ])

    # Parse the Date field
    if any(field in df.columns for field in DATE_FIELDS):
        df["Date"] = pd.to_datetime(
            df.apply(lambda r: _first_nonempty(r, DATE_FIELDS), axis=1),
            errors="coerce",
            utc=True
        ).dt.tz_localize(None)

    # Parse Closed RR if it exists
    if any(field in df.columns for field in RR_FIELDS):
        df["Closed RR"] = df.apply(
            lambda r: parse_closed_rr(_first_nonempty(r, RR_FIELDS)), 
            axis=1
        )

    # Parse PnL if it exists
    if any(field in df.columns for field in PNL_FIELDS):
        df["PnL"] = pd.to_numeric(
            df.apply(lambda r: _first_nonempty(r, PNL_FIELDS), axis=1), 
            errors="coerce"
        )

    return df
