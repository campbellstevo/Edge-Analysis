from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

# Folder this file lives in: src/edge_analysis/
_ROOT = Path(__file__).resolve().parent

# JSON file that actually stores all user data
_STORE_FILE = _ROOT / "user_store.json"


# ----------------------------- low-level helpers -----------------------------


def _empty_store() -> Dict[str, Any]:
    """
    Internal shape of the store:

    {
      "version": 1,
      "users": {
        "<notion_user_id>": {
          "db_id": "...",
          "template": "SRs T1",
          "name": "User Name",
          "email": "user@example.com",
          "last_updated": 1733550000.0
        }
      }
    }
    """
    return {"version": 1, "users": {}}


def _load_raw_store() -> Dict[str, Any]:
    """Load the entire store from disk. If anything goes wrong, return empty."""
    if not _STORE_FILE.exists():
        return _empty_store()

    try:
        data = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_store()
        if "users" not in data or not isinstance(data["users"], dict):
            data["users"] = {}
        if "version" not in data:
            data["version"] = 1
        return data
    except Exception:
        # Corrupt / unreadable file -> start fresh
        return _empty_store()


def _save_raw_store(store: Dict[str, Any]) -> None:
    """Write the entire store to disk. Fail silently if write is not allowed."""
    try:
        _STORE_FILE.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        # On Streamlit Cloud / read-only envs we just skip saving
        pass


# ----------------------------- public API (simple) ---------------------------


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the record for a given Notion user id, or None if not found.
    """
    if not user_id:
        return None
    store = _load_raw_store()
    return store["users"].get(user_id)


def upsert_user(user_id: str, **fields: Any) -> Dict[str, Any]:
    """
    Create or update a user record.

    Example:
        upsert_user(
            user_id,
            db_id="abcd1234...",
            template="SRs T1",
            name="Campbell",
            email="me@example.com",
        )
    """
    if not user_id:
        raise ValueError("user_id is required")

    import time as _time

    store = _load_raw_store()
    users = store["users"]

    current = users.get(user_id, {})
    if not isinstance(current, dict):
        current = {}

    # merge new fields into existing record
    current.update(fields)
    current["last_updated"] = _time.time()

    users[user_id] = current
    store["users"] = users
    _save_raw_store(store)
    return current


def set_user_db(user_id: str, db_id: str, template: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience helper: set / update the Notion database for a user.
    """
    data: Dict[str, Any] = {"db_id": db_id}
    if template is not None:
        data["template"] = template
    return upsert_user(user_id, **data)


def list_users() -> Dict[str, Dict[str, Any]]:
    """
    Return the mapping of all users.

    Shape:
        { "<user_id>": { ...record... }, ... }
    """
    store = _load_raw_store()
    return store["users"]


def delete_user(user_id: str) -> None:
    """
    Remove a user from the store. If the user does not exist, do nothing.
    """
    if not user_id:
        return
    store = _load_raw_store()
    if user_id in store["users"]:
        store["users"].pop(user_id, None)
        _save_raw_store(store)