from __future__ import annotations
import re
from typing import Optional

from ..schema import RESULT_WIN, RESULT_BE, RESULT_LOSS

# Normalization helpers -------------------------------------------------------
_WS = re.compile(r"\s+")

def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip().lower())

# Result mapping (covers your specific variants)
_VARIANTS_TO_RESULT = {
    # Wins
    "full tp": RESULT_WIN,
    "early close (ended up being a win)": RESULT_WIN,
    "early close (ended up being a be)": RESULT_WIN,  # as per your rule
    "win": RESULT_WIN,
    # Break-even
    "breakeven": RESULT_BE,
    "be": RESULT_BE,
    # Losses
    "loss": RESULT_LOSS,
    "loss is a loss": RESULT_LOSS,
}

def normalize_result(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    key = _norm(str(value))
    # tolerate minor typos
    key = key.replace("lo ss", "loss").replace("breakevn", "breakeven")
    return _VARIANTS_TO_RESULT.get(key, None)

# Closed RR parsing -----------------------------------------------------------
_RANGE = re.compile(r"^\s*([+\-]?\d+(?:\.\d+)?)\s*(?:-\s*([+\-]?\d+(?:\.\d+)?))?\s*$")

def parse_closed_rr(value: Optional[str | float | int]) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    m = _RANGE.match(s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return None
    lo = float(m.group(1))
    hi = m.group(2)
    if hi is None:
        return lo
    return (lo + float(hi)) / 2.0
