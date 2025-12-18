# server.py - Test server for testning folder
# -*- coding: utf-8 -*-
"""
Test server - saves everything to testning/output/
Same as 1_poit/server.py but isolated for testing.
"""

import hashlib
import json
import os
import threading
from datetime import datetime

from flask import Flask, jsonify, request

app = Flask(__name__)

# Paths - save to testning/output/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "output")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

INDEX_LOCK = threading.Lock()


def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def _sha1_short(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]


def _now_str() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_date_folder():
    date_str = datetime.now().strftime("%Y%m%d")
    folder = os.path.join(DATA_DIR, date_str)
    os.makedirs(folder, exist_ok=True)
    return folder, date_str


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "test-collector", "time": _now_str()})


@app.post("/save")
def save():
    """Save API response (kungörelser list)."""
    print("\n[SAVE] POST /save")

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"ok": False, "error": "No data"}), 400

        # Extract the actual data
        if isinstance(data, dict) and "data" in data:
            items = data.get("data", [])
            url = data.get("url", "")
        elif isinstance(data, list):
            items = data
            url = ""
        else:
            items = [data]
            url = ""

        folder, date_str = _get_date_folder()
        filename = f"kungorelser_{date_str}.json"
        path = os.path.join(folder, filename)

        # Load existing or create new
        existing_items = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                existing_items = existing.get("data", [])

        # Merge (avoid duplicates by kungorelseid)
        existing_ids = {
            item.get("kungorelseid")
            for item in existing_items
            if isinstance(item, dict)
        }
        new_items = [
            item
            for item in items
            if isinstance(item, dict) and item.get("kungorelseid") not in existing_ids
        ]

        all_items = existing_items + new_items

        # Save
        output = {
            "meta": {"timestamp": _now_str(), "url": url, "item_count": len(all_items)},
            "data": all_items,
        }

        with open(path, "w", encoding="utf-8") as f:
            f.write(_json_dumps(output))

        print(f"  -> Saved {len(all_items)} items ({len(new_items)} new) to {filename}")

        return jsonify(
            {
                "ok": True,
                "status": "saved",
                "count": len(all_items),
                "new": len(new_items),
            }
        )

    except Exception as e:
        print(f"  -> ERROR: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/save_kungorelse")
def save_kungorelse():
    """Save individual kungörelse page content."""
    print("\n[KUNGORELSE] POST /save_kungorelse")

    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "No data"}), 400

        kung_id = data.get("kungorelseId")
        if not kung_id:
            return jsonify({"ok": False, "error": "No kungorelseId"}), 400

        url = data.get("url", "")
        text = data.get("textContent", "")

        # Skip enskild pages
        if "/enskild/" in url.lower():
            print(f"  -> SKIP {kung_id}: enskild page")
            return jsonify({"ok": True, "status": "skipped", "reason": "enskild"})

        # Skip short content
        if len(text) < 500:
            print(f"  -> SKIP {kung_id}: content too short ({len(text)} chars)")
            return jsonify({"ok": True, "status": "skipped", "reason": "too_short"})

        # Create folder
        folder, _ = _get_date_folder()
        kung_folder = os.path.join(folder, kung_id)

        # Check if already exists
        if os.path.exists(os.path.join(kung_folder, "content.txt")):
            print(f"  -> SKIP {kung_id}: already exists")
            return jsonify({"ok": True, "status": "exists"})

        os.makedirs(kung_folder, exist_ok=True)

        # Save files
        with open(os.path.join(kung_folder, "content.txt"), "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\n")
            f.write(f"Title: {data.get('title', '')}\n")
            f.write(f"Timestamp: {data.get('timestamp', '')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(text)

        with open(
            os.path.join(kung_folder, "content.html"), "w", encoding="utf-8"
        ) as f:
            f.write(data.get("htmlContent", ""))

        with open(os.path.join(kung_folder, "data.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Log enskild if detected in navigation
        if data.get("was_enskild"):
            log_file = os.path.join(
                LOG_DIR, f"enskild_{datetime.now().strftime('%Y%m%d')}.log"
            )
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"{datetime.now().isoformat()}|{kung_id}|{data.get('enskild_url', '')}\n"
                )

        print(f"  -> SAVED {kung_id}")
        return jsonify({"ok": True, "status": "saved", "kungorelseId": kung_id})

    except Exception as e:
        print(f"  -> ERROR: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/list")
def list_files():
    """List saved files."""
    files = []
    for item in os.listdir(DATA_DIR):
        item_path = os.path.join(DATA_DIR, item)
        if os.path.isdir(item_path):
            for f in os.listdir(item_path):
                if f.endswith(".json") or os.path.isdir(os.path.join(item_path, f)):
                    files.append(f"{item}/{f}")
    return jsonify({"ok": True, "files": sorted(files, reverse=True)})


if __name__ == "__main__":
    print("=" * 60)
    print("TEST SERVER")
    print("=" * 60)
    print(f"Output: {DATA_DIR}")
    print(f"Logs: {LOG_DIR}")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=False)
