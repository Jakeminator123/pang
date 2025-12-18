"""
Preview storage and management system.
Stores preview metadata and handles cleanup after 2 days.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import asyncio


STORAGE_FILE = Path(__file__).parent / "previews.json"
CLEANUP_INTERVAL_HOURS = 6  # Run cleanup every 6 hours
PREVIEW_EXPIRY_DAYS = 2


def ensure_storage_file():
    """Ensure storage file exists."""
    if not STORAGE_FILE.exists():
        STORAGE_FILE.write_text("{}", encoding="utf-8")


def load_previews() -> Dict[str, Dict[str, Any]]:
    """Load all previews from storage."""
    ensure_storage_file()
    try:
        content = STORAGE_FILE.read_text(encoding="utf-8")
        return json.loads(content) if content.strip() else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_previews(previews: Dict[str, Dict[str, Any]]):
    """Save previews to storage."""
    STORAGE_FILE.write_text(
        json.dumps(previews, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def generate_preview_id() -> str:
    """Generate a unique preview ID."""
    return str(uuid.uuid4())


def create_preview_entry(
    demo_url: str,
    chat_id: Optional[str] = None,
    company_name: Optional[str] = None,
    folder_name: Optional[str] = None,
    cost_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Create a new preview entry and return its unique ID.

    Returns:
        Unique preview ID (UUID string)
    """
    preview_id = generate_preview_id()
    expires_at = datetime.now() + timedelta(days=PREVIEW_EXPIRY_DAYS)

    entry = {
        "id": preview_id,
        "demoUrl": demo_url,
        "chatId": chat_id,
        "company_name": company_name,
        "folder_name": folder_name,
        "cost": cost_info,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "accessed_count": 0,
        "last_accessed": None,
    }

    previews = load_previews()
    previews[preview_id] = entry
    save_previews(previews)

    return preview_id


def get_preview(preview_id: str) -> Optional[Dict[str, Any]]:
    """Get preview by ID and update access stats."""
    previews = load_previews()

    if preview_id not in previews:
        return None

    entry = previews[preview_id]

    # Check if expired
    expires_at = datetime.fromisoformat(entry["expires_at"])
    if datetime.now() > expires_at:
        # Auto-delete expired entry
        del previews[preview_id]
        save_previews(previews)
        return None

    # Update access stats
    entry["accessed_count"] = entry.get("accessed_count", 0) + 1
    entry["last_accessed"] = datetime.now().isoformat()
    previews[preview_id] = entry
    save_previews(previews)

    return entry


def cleanup_expired_previews() -> int:
    """Remove expired previews. Returns count of removed previews."""
    previews = load_previews()
    now = datetime.now()
    expired_ids = []

    for preview_id, entry in previews.items():
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if now > expires_at:
            expired_ids.append(preview_id)

    for preview_id in expired_ids:
        del previews[preview_id]

    if expired_ids:
        save_previews(previews)

    return len(expired_ids)


def get_preview_stats() -> Dict[str, Any]:
    """Get statistics about stored previews."""
    previews = load_previews()
    now = datetime.now()

    total = len(previews)
    active = 0
    expired = 0

    for entry in previews.values():
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if now > expires_at:
            expired += 1
        else:
            active += 1

    return {
        "total": total,
        "active": active,
        "expired": expired,
        "expiry_days": PREVIEW_EXPIRY_DAYS,
    }


async def cleanup_task():
    """Background task to periodically clean up expired previews."""
    while True:
        try:
            removed = cleanup_expired_previews()
            if removed > 0:
                print(f"🧹 Cleaned up {removed} expired preview(s)")
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")

        await asyncio.sleep(CLEANUP_INTERVAL_HOURS * 3600)


def start_cleanup_background_task():
    """Start the cleanup background task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a task
            asyncio.create_task(cleanup_task())
        else:
            # If no loop is running, start one
            loop.run_until_complete(cleanup_task())
    except RuntimeError:
        # Create new event loop if needed
        asyncio.run(cleanup_task())
