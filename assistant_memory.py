"""Hindsight Memory Client

This module provides a lightweight wrapper around the Hindsight Vectorize API
and adds a local fallback store for reliability.

Functions:
- save_memory(user_id, key, value)
- get_memory(user_id, key)
- update_memory(user_id, key, value)

Security:
- API key is loaded from environment variables using dotenv.
- Local fallback storage is SQLite-based and used only when API calls fail.
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv = None

HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY")
HINDSIGHT_API_URL = os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.ai/v1")
LOCAL_MEMORY_DB = Path("hindsight_memory.db")
LOCAL_MEMORY_TABLE = "memory_store"
TIMEOUT_SECONDS = 6

# Example Hindsight endpoint values:
# HINDSIGHT_API_URL=https://api.hindsight.ai/v1
# HINDSIGHT_API_KEY=your_hindsight_api_key_here


class MemoryError(Exception):
    pass


@dataclass
class MemoryResult:
    user_id: str
    key: str
    value: Any
    source: str


def _create_local_db() -> None:
    """Ensure the local fallback database exists."""
    with sqlite3.connect(LOCAL_MEMORY_DB) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {LOCAL_MEMORY_TABLE} (
                user_id TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, memory_key)
            )
            """
        )
        conn.commit()


def _get_headers() -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if HINDSIGHT_API_KEY:
        headers["Authorization"] = f"Bearer {HINDSIGHT_API_KEY}"
        headers["X-API-Key"] = HINDSIGHT_API_KEY
    return headers


def _call_hindsight_api(method: str, endpoint: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
    """Call Hindsight API safely and raise MemoryError on problems."""
    url = f"{HINDSIGHT_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = _get_headers()

    if not HINDSIGHT_API_KEY:
        raise MemoryError("Missing Hindsight API key. Set HINDSIGHT_API_KEY in .env.")

    try:
        response = requests.request(
            method,
            url,
            json=payload,
            params=params,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MemoryError(f"Hindsight API request failed: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise MemoryError("Invalid JSON from Hindsight API.") from exc


def _save_local_memory(user_id: str, key: str, value: Any) -> MemoryResult:
    _create_local_db()
    serialized = json.dumps(value, ensure_ascii=False)
    with sqlite3.connect(LOCAL_MEMORY_DB) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {LOCAL_MEMORY_TABLE} (user_id, memory_key, memory_value, updated_at) VALUES (?, ?, ?, datetime('now'))",
            (user_id, key, serialized),
        )
        conn.commit()
    return MemoryResult(user_id=user_id, key=key, value=value, source="local")


def _get_local_memory(user_id: str, key: str) -> Optional[MemoryResult]:
    _create_local_db()
    with sqlite3.connect(LOCAL_MEMORY_DB) as conn:
        row = conn.execute(
            f"SELECT memory_value FROM {LOCAL_MEMORY_TABLE} WHERE user_id = ? AND memory_key = ?",
            (user_id, key),
        ).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        value = row[0]
    return MemoryResult(user_id=user_id, key=key, value=value, source="local")


def save_memory(user_id: str, key: str, value: Any) -> MemoryResult:
    """Save a key/value pair for a user in Hindsight memory."""
    payload = {
        "user_id": user_id,
        "key": key,
        "value": value,
    }
    try:
        result = _call_hindsight_api("POST", "/memories", payload=payload)
        if result.get("success"):
            return MemoryResult(user_id=user_id, key=key, value=value, source="hindsight")
        raise MemoryError("Hindsight API reported failure while saving memory.")
    except MemoryError:
        return _save_local_memory(user_id, key, value)


def get_memory(user_id: str, key: str) -> Optional[MemoryResult]:
    """Retrieve a memory value for the given user and key."""
    try:
        result = _call_hindsight_api("GET", "/memories", params={"user_id": user_id, "key": key})
        if "value" in result:
            return MemoryResult(user_id=user_id, key=key, value=result["value"], source="hindsight")
    except MemoryError:
        pass

    return _get_local_memory(user_id, key)


def update_memory(user_id: str, key: str, value: Any) -> MemoryResult:
    """Update an existing memory entry for a user."""
    payload = {
        "value": value,
    }
    try:
        result = _call_hindsight_api("PUT", f"/memories/{user_id}/{key}", payload=payload)
        if result.get("success"):
            return MemoryResult(user_id=user_id, key=key, value=value, source="hindsight")
        raise MemoryError("Hindsight API reported failure while updating memory.")
    except MemoryError:
        return _save_local_memory(user_id, key, value)
