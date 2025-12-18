# server.py
# -*- coding: utf-8 -*-
"""
En robust lokal insamlingsserver för Bolagsverket-trafik (och liknande).
- Tar emot POST /save från din Chrome-extension (valfritt även ren JSON utan "url"/"data").
- Sparar nyttolast som .json i ./data/, med metadata och deduplicering via innehålls-hash.
- Hjälpendpoints: /health, /list, /file/<namn> för snabb felsökning.
- Kräver enbart Flask (pip install flask).

Byggd för Windows 11, men fungerar på alla plattformar.
"""

from flask import Flask, request, jsonify, send_from_directory, abort
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import os
import json
import hashlib
import threading
import re

app = Flask(__name__)

# ========================================
# CONFIGURATION FLAGS
# ========================================
ENABLE_DATA_LOGGING = True      # Save to info_server/ directory
ENABLE_TRAFFIC_LOG = True       # Save to log/traffic.log
ENABLE_DOCUMENT_SAVE = True     # Save interesting docs to log/documents/
ENABLE_KUNGORELSE_CAPTURE = True  # Save individual kungorelse pages to subfolders
# ========================================

# --- Kataloger ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "info_server")
LOG_DIR = os.path.join(BASE_DIR, "log")
LOG_DOCS_DIR = os.path.join(LOG_DIR, "documents")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(LOG_DOCS_DIR, exist_ok=True)

# INDEX_PATH will be dynamic based on date
TRAFFIC_LOG_PATH = os.path.join(LOG_DIR, "traffic.log")
INDEX_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()

LANDING_PAGE_KEYWORDS = [
    "välkommen till post- och inrikes tidningar",
    "familjerätt",
    "bodelning",
    "förvaltarskap",
    "utdelningsförslag",
    "skuldsaneringar",
    "manusstopp",
    "sökresultatet innehåller inte personnummer",
]

VALID_KUNGO_URL_RE = re.compile(r"/poit-app/(?:kungorelse|enskild)/K\d{3,}-\d{2}", re.IGNORECASE)

# Keywords in company names to exclude
NAME_EXCLUDE_KEYWORDS = ("förening", "holding", "lagerbolag")

# Keywords in email domains that indicate accounting firm (bulk registrations)
EMAIL_DOMAIN_EXCLUDE_KEYWORDS = (
    "redovisning", "bokföring", "bokforing", "revision",
    "ekonomi", "accounting", "konto", "skatt", "deklaration"
)


# --- Hjälpare ---

def _json_dumps(obj) -> str:
    """Stabil och läsbar JSON-dump (UTF-8, sorterade nycklar)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def _sha1_short(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]


def _now_str() -> str:
    # Lokal tid YYYYMMDD_HHMMSS
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _log_traffic(method: str, url: str, status: str, meta: dict) -> None:
    """Log traffic to log/traffic.log with max 300 lines rotation."""
    if not ENABLE_TRAFFIC_LOG:
        return
        
    with LOG_LOCK:
        try:
            # Read existing lines
            lines = []
            if os.path.exists(TRAFFIC_LOG_PATH):
                with open(TRAFFIC_LOG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            
            # Skip repetitive bot-like patterns
            if len(lines) > 2:
                last_line = lines[-1] if lines else ""
                # Don't log identical consecutive requests
                if url[:50] in last_line:
                    return
            
            # Create new log entry with human-readable format
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Simplify URL for readability
            if "/kungorelse/K" in url:
                match = re.search(r'(K\d+[-/]\d+)', url)
                if match:
                    short_url = f"kungorelse/{match.group(1)}"
                else:
                    short_url = url.split('/')[-1][:30]
            else:
                short_url = url.split('/')[-1][:30] if '/' in url else url[:30]
            
            entry = f"[{timestamp}] {short_url} - {status}"
            if meta.get("item_count") and meta["item_count"] > 1:
                entry += f" ({meta['item_count']} items)"
            entry += "\n"
            
            # Keep only last 299 lines + new entry = 300 total
            lines = lines[-(299):] if len(lines) >= 299 else lines
            lines.append(entry)
            
            # Write back
            with open(TRAFFIC_LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass  # Silent fail to reduce noise


def _validate_kungorelse_payload(url: str | None, text: str | None) -> tuple[bool, str]:
    """Snabb heuristik för att sålla bort PoIT-startsidan och andra irrelevanta sidor."""
    if not isinstance(url, str) or not url:
        return False, "missing_url"
    
    # VIKTIGT: Bara acceptera faktiska kungörelse-sidor, INTE enskild-sidor
    if "/enskild/" in url.lower():
        return False, "enskild_page_not_allowed"
    
    if not VALID_KUNGO_URL_RE.search(url):
        return False, "invalid_kungorelse_url"
    
    if not isinstance(text, str) or not text.strip():
        return False, "empty_text"
    
    # Kontrollera att texten är tillräckligt lång (minst 500 tecken för faktiskt innehåll)
    if len(text.strip()) < 500:
        return False, "content_too_short"
    
    # Kontrollera att det inte är en länk-sida (många länkar men lite text)
    link_count = text.lower().count("href") + text.lower().count("kungorelse/k")
    if link_count > 5 and len(text.strip()) < 1000:
        return False, "link_page_detected"

    lower_text = text.lower()
    hits = sum(1 for kw in LANDING_PAGE_KEYWORDS if kw in lower_text)
    if hits >= 3:
        return False, "landing_page_detected"

    return True, ""


def _save_interesting_document(data: dict | list, url: str) -> None:
    """Save interesting documents to log/documents/ with max 10 files."""
    try:
        # Check if interesting (has list with kungorelseid items)
        interesting = False
        unique_content = False
        
        if isinstance(data, list) and len(data) > 0:
            # Check if first item has kungorelseid or similar
            if isinstance(data[0], dict) and "kungorelseid" in data[0]:
                interesting = True
                # Check if we have unique content (not just IDs)
                if any(key in data[0] for key in ["rubrik", "text", "beskrivning", "innehall"]):
                    unique_content = True
        elif isinstance(data, dict):
            # Check for interesting single documents
            if any(key in data for key in ["kungorelsetext", "beslut", "arende", "handling"]):
                interesting = True
                unique_content = True
        
        if not interesting or not unique_content:
            return
        
        # Limit to 10 files - delete oldest
        files = [f for f in os.listdir(LOG_DOCS_DIR) if f.endswith(".json")]
        files.sort()  # oldest first
        while len(files) >= 10:
            oldest = files.pop(0)
            os.remove(os.path.join(LOG_DOCS_DIR, oldest))
        
        # Save new document (compressed format to reduce bot footprint)
        filename = f"doc_{_now_str()}.json"
        path = os.path.join(LOG_DOCS_DIR, filename)
        
        # Extract only meaningful content
        if isinstance(data, list):
            filtered_data = []
            for item in data[:20]:  # Max 20 items to avoid huge files
                if isinstance(item, dict):
                    filtered = {k: v for k, v in item.items() 
                               if k in ["kungorelseid", "namn", "rubrik", "text", "datum"]}
                    if filtered:
                        filtered_data.append(filtered)
            data = filtered_data
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "items": len(data) if isinstance(data, list) else 1, 
                      "data": data, "timestamp": _now_str()}, 
                     f, ensure_ascii=False, indent=2)
        
        print(f"[INTERESTING] Saved {filename} ({len(data) if isinstance(data, list) else 1} items)")
    except Exception as e:
        print(f"[DOC SAVE ERROR] {e}")


def _get_index_path():
    """Get index path for today's date folder (or TARGET_DATE if set)"""
    import os
    date_str = os.environ.get('TARGET_DATE', datetime.now().strftime("%Y%m%d"))
    print(f"[SERVER] _get_index_path: Använder datum: {date_str} (TARGET_DATE={'satt' if os.environ.get('TARGET_DATE') else 'ej satt'})")
    date_folder = os.path.join(DATA_DIR, date_str)
    os.makedirs(date_folder, exist_ok=True)
    return os.path.join(date_folder, "_index.json")


def _load_index() -> dict:
    index_path = _get_index_path()
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_index(idx: dict) -> None:
    index_path = _get_index_path()
    tmp = index_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, index_path)


TARGET_KEYS = {
    # nycklar vi bryr oss extra om (heuristik)
    "kungorelseObjektNamn",
    "kungorelseObjektPersonOrgnummer",
    "kungorelseObjektPersonNamn",
    "kungorelseId",
    "amnesomradeId",
    "kungorelsetypId",
    "underRubrikId",
}


def _has_any_target_keys(obj) -> bool:
    """Rekursivt: finns några 'intressanta' nycklar i datan?"""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in TARGET_KEYS:
                    return True
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def _extract_metadata(url: str | None, body_obj) -> dict:
    """
    Skapa rik metadata:
    - url, host, path, query (som dict)
    - item_count (om lista), contains_target_keys, timestamp
    """
    meta = {
        "timestamp": _now_str(),
        "url": url or None,
        "host": None,
        "path": None,
        "query": None,
        "item_count": None,
        "contains_target_keys": False,
    }

    if url:
        try:
            u = urlparse(url)
            meta["host"] = u.hostname
            meta["path"] = u.path
            # parse_qs ger listor per nyckel
            q = parse_qs(u.query)
            # gör om listor med längd 1 till värde
            meta["query"] = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                             for k, v in q.items()} or None
        except Exception:
            pass

    if isinstance(body_obj, list):
        meta["item_count"] = len(body_obj)
    elif isinstance(body_obj, dict):
        meta["contains_target_keys"] = _has_any_target_keys(body_obj)

    return meta


def _normalize_company_name(name: str | None) -> str | None:
    """Normalize company name for deduplication."""
    if not isinstance(name, str):
        return None
    collapsed = re.sub(r"\s+", "", name).lower()
    collapsed = re.sub(r"\d+", "", collapsed)
    return collapsed or None


def _should_skip_company(name: str | None) -> bool:
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    return any(keyword in lowered for keyword in NAME_EXCLUDE_KEYWORDS)


def _should_skip_email_domain(email: str | None) -> tuple[bool, str]:
    """Check if email domain indicates accounting firm."""
    if not isinstance(email, str) or "@" not in email:
        return False, ""
    try:
        domain = email.split("@")[1].lower()
        for keyword in EMAIL_DOMAIN_EXCLUDE_KEYWORDS:
            if keyword in domain:
                return True, keyword
    except (IndexError, AttributeError):
        pass
    return False, ""


def _extract_email_from_text(text: str) -> str | None:
    """Extract first email from text content."""
    if not text:
        return None
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0).lower() if match else None


def _deduplicate_kungorelse_items(items: list) -> tuple[list, dict]:
    """Remove duplicate entries by kungorelseId, company name, and email domain."""
    base_stats = {
        "removed": 0,
        "duplicate_ids": 0,
        "duplicate_names": 0,
        "duplicate_email_domains": 0,
        "filtered_keywords": 0,
        "filtered_accounting": 0,
    }
    if not isinstance(items, list):
        return items, base_stats

    seen_ids = set()
    seen_names = set()
    seen_email_domains = set()
    cleaned: list = []
    duplicate_ids = 0
    duplicate_names = 0
    duplicate_email_domains = 0
    filtered_keywords = 0
    filtered_accounting = 0

    # Generic email domains to allow duplicates (these are personal, not bulk)
    generic_domains = {"gmail.com", "hotmail.com", "outlook.com", "icloud.com", "yahoo.com", "live.se", "msn.com"}

    for obj in items:
        if not isinstance(obj, dict):
            cleaned.append(obj)
            continue

        raw_name = (
            obj.get("namn")
            or obj.get("company_name")
            or obj.get("companyName")
            or obj.get("title")
        )
        if _should_skip_company(raw_name):
            filtered_keywords += 1
            continue

        # Check email domain for accounting firms
        raw_email = obj.get("email") or obj.get("e-post") or obj.get("epost")
        if raw_email:
            skip_email, reason = _should_skip_email_domain(raw_email)
            if skip_email:
                filtered_accounting += 1
                continue

            # Check for duplicate email domains (but allow generic domains)
            try:
                domain = raw_email.split("@")[1].lower()
                if domain not in generic_domains:
                    if domain in seen_email_domains:
                        duplicate_email_domains += 1
                        continue
                    seen_email_domains.add(domain)
            except (IndexError, AttributeError):
                pass

        raw_id = obj.get("kungorelseid") or obj.get("kungorelseId")
        normalized_id = None
        if isinstance(raw_id, str):
            normalized_id = raw_id.strip().upper().replace("/", "-")
            if normalized_id in seen_ids:
                duplicate_ids += 1
                continue

        normalized_name = _normalize_company_name(raw_name)
        if normalized_name and normalized_name in seen_names:
            duplicate_names += 1
            continue

        cleaned.append(obj)
        if normalized_id:
            seen_ids.add(normalized_id)
        if normalized_name:
            seen_names.add(normalized_name)

    removed = len(items) - len(cleaned)
    return cleaned, {
        "removed": removed,
        "duplicate_ids": duplicate_ids,
        "duplicate_names": duplicate_names,
        "duplicate_email_domains": duplicate_email_domains,
        "filtered_keywords": filtered_keywords,
        "filtered_accounting": filtered_accounting,
    }


def _normalize_payload(incoming: dict | list | str | bytes) -> tuple[dict, bytes]:
    """
    Gör payload-formatet enhetligt:
    - Om inkommande är {url:str, data:obj} -> normalisera till {"meta":..., "data":obj}
    - Om inkommande är ett JSON-objekt/lista -> {"meta":..., "data":incoming}
    - Om inkommande inte är JSON -> packa som {"meta":..., "raw_text": "..."} (ändå JSON-fil)
    Returnerar (obj_for_json_file, raw_bytes_for_hash)
    """
    url = None
    body_obj = None
    raw_text = None

    # Försök fånga raw-data från request först om inget skickats in
    if incoming is None:
        # Läs råa bytes
        incoming_bytes = request.get_data(cache=False) or b""
        # Försök tolka som JSON
        try:
            parsed = json.loads(incoming_bytes.decode("utf-8", "replace"))
            incoming = parsed
        except Exception:
            incoming = None
            raw_text = incoming_bytes.decode("utf-8", "replace")

    # Om vi fick in bytes/str direkt
    if isinstance(incoming, (bytes, bytearray)):
        try:
            body_obj = json.loads(incoming.decode("utf-8", "replace"))
            incoming = body_obj
        except Exception:
            raw_text = incoming.decode("utf-8", "replace")
            incoming = None

    if isinstance(incoming, str):
        # Kan vara JSON-sträng
        try:
            body_obj = json.loads(incoming)
            incoming = body_obj
        except Exception:
            raw_text = incoming
            incoming = None

    # Nu: incoming är antingen dict/list eller None
    if isinstance(incoming, dict) and "data" in incoming:
        # Extension-format {url, data}
        url = incoming.get("url")
        body_obj = incoming.get("data")
    elif isinstance(incoming, (dict, list)):
        # Rå JSON från annan källa
        body_obj = incoming
    else:
        # Icke-JSON; kör på raw_text
        if raw_text is None:
            raw_text = ""  # borde inte hända, men säkra
        meta = _extract_metadata(None, raw_text)
        packed = {"meta": meta, "raw_text": raw_text}
        raw_bytes = _json_dumps(packed).encode("utf-8")
        return packed, raw_bytes

    # Bygg metadata och slutlig struktur
    meta = _extract_metadata(url, body_obj)
    packed = {"meta": meta, "data": body_obj}
    raw_bytes = _json_dumps(packed).encode("utf-8")
    return packed, raw_bytes


def _next_filename(stem: str, suffix: str = ".json") -> str:
    # Ex: kungorelser_20250317_121030_ab12cd34ef56.json
    return f"{stem}_{_now_str()}_{suffix}"


def _save_payload(packed_obj: dict, raw_bytes: bytes) -> dict:
    """
    Sparar 'packed_obj' till EN fil per datum för att undvika dubbletter.
    - Använder dagens datum som filnamn.
    - Uppdaterar befintlig fil om den finns.
    - Returnerar metadata om sparningen.
    """
    # Use date as filename base (one file per day)
    import os
    date_str = os.environ.get('TARGET_DATE', datetime.now().strftime("%Y%m%d"))
    print(f"[SERVER] _save_payload: Använder datum: {date_str} (TARGET_DATE={'satt' if os.environ.get('TARGET_DATE') else 'ej satt'})")
    
    # Create date folder if it doesn't exist
    date_folder = os.path.join(DATA_DIR, date_str)
    os.makedirs(date_folder, exist_ok=True)
    
    filename = f"kungorelser_{date_str}.json"
    path = os.path.join(date_folder, filename)
    
    # Calculate hash for deduplication check
    h = _sha1_short(raw_bytes)
    
    if isinstance(packed_obj.get("data"), list):
        cleaned, stats = _deduplicate_kungorelse_items(packed_obj["data"])
        if stats["removed"] or stats["filtered_keywords"] or stats["filtered_accounting"]:
            print(
                "[DEDUP] Removed "
                f"{stats['removed']} entries (same name: {stats['duplicate_names']}, "
                f"same id: {stats['duplicate_ids']}, same email domain: {stats['duplicate_email_domains']}, "
                f"keyword filtered: {stats['filtered_keywords']}, accounting firms: {stats['filtered_accounting']})"
            )
        packed_obj["data"] = cleaned
        if isinstance(packed_obj.get("meta"), dict):
            packed_obj["meta"]["item_count"] = len(cleaned)
        raw_bytes = _json_dumps(packed_obj).encode("utf-8")

    with INDEX_LOCK:
        idx = _load_index()
        
        # Check if this exact data already exists
        if h in idx:
            return {
                "ok": True,
                "status": "duplicate",
                "hash": h,
                "file": idx[h],
                "path": os.path.join(DATA_DIR, idx[h]),
                "meta": packed_obj.get("meta", {}),
            }
        
        # Check if today's file already exists
        if os.path.exists(path):
            try:
                # Read existing data
                with open(path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                
                # Merge with new data (if it's a list of items)
                if "data" in packed_obj and "data" in existing_data:
                    if isinstance(packed_obj["data"], list) and isinstance(existing_data["data"], list):
                        # Count existing items
                        existing_count = len(existing_data["data"])
                        new_count = len(packed_obj["data"])
                        
                        # IMPORTANT: Only save if new list has MORE items than existing
                        if new_count <= existing_count:
                            print(f"[SKIP] New list ({new_count} items) not larger than existing ({existing_count} items)")
                            return {
                                "ok": True,
                                "status": "skipped_smaller",
                                "hash": h,
                                "file": filename,
                                "path": path,
                                "meta": packed_obj.get("meta", {}),
                                "existing_count": existing_count,
                                "new_count": new_count
                            }
                        
                        # Merge lists, avoiding duplicates based on kungorelseid
                        existing_ids = set()
                        for item in existing_data["data"]:
                            if isinstance(item, dict) and "kungorelseid" in item:
                                existing_ids.add(item["kungorelseid"])
                        
                        new_items = []
                        for item in packed_obj["data"]:
                            if isinstance(item, dict) and "kungorelseid" in item:
                                if item["kungorelseid"] not in existing_ids:
                                    new_items.append(item)
                        
                        if new_items:
                            existing_data["data"].extend(new_items)
                            existing_data["meta"]["item_count"] = len(existing_data["data"])
                            packed_obj = existing_data
                            raw_bytes = _json_dumps(packed_obj).encode("utf-8")
                            status = "updated"
                        else:
                            status = "duplicate"
                    else:
                        # Not a list, just overwrite
                        status = "replaced"
                else:
                    status = "replaced"
            except Exception:
                # If can't read/merge, just overwrite
                status = "replaced"
        else:
            status = "created"
        
        # Save the file
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_bytes.decode("utf-8"))
        
        # Update index
        idx[h] = filename
        _save_index(idx)
    
    return {
        "ok": True,
        "status": status,
        "hash": h,
        "file": filename,
        "path": path,
        "meta": packed_obj.get("meta", {}),
    }


# --- Endpoints ---

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "collector", "time": _now_str()})


@app.get("/list")
def list_files():
    """Lista sparade filer (senaste först) från datummappar."""
    all_files = []
    
    # Gå igenom alla datummappar
    for item in os.listdir(DATA_DIR):
        item_path = os.path.join(DATA_DIR, item)
        if os.path.isdir(item_path) and item.isdigit() and len(item) == 8:  # YYYYMMDD
            # Leta efter JSON-filer i datummappen
            for f in os.listdir(item_path):
                if f.endswith(".json") and not f.startswith("_"):
                    all_files.append(f"{item}/{f}")
    
    # Även kolla root för bakåtkompatibilitet
    for f in os.listdir(DATA_DIR):
        if f.endswith(".json") and not f.startswith("_") and not os.path.isdir(os.path.join(DATA_DIR, f)):
            all_files.append(f)
    
    all_files.sort(reverse=True)
    return jsonify({
        "ok": True,
        "count": len(all_files),
        "files": all_files[:500]  # skydda mot enorma listor
    })


@app.get("/file/<path:name>")
def get_file(name: str):
    # Säkerhetskontroll: bara .json i data-katalogen
    if not name.endswith(".json"):
        abort(404)
    return send_from_directory(DATA_DIR, name, as_attachment=False)


@app.post("/save_kungorelse")
def save_kungorelse():
    """
    Save kungorelse page content to a dedicated folder.
    Creates a folder named after the kungorelseId (e.g., K739821-25).
    """
    print(f"\n[KUNGORELSE] POST /save_kungorelse från {request.remote_addr}")
    try:
        data = request.get_json()
        if not data:
            print("  -> ERROR: No data received")
            return jsonify({"ok": False, "error": "No data received"}), 400
        
        kungorelse_id = data.get("kungorelseId")
        if not kungorelse_id:
            print("  -> ERROR: No kungorelseId")
            return jsonify({"ok": False, "error": "No kungorelseId"}), 400
        
        print(f"  -> Processing: {kungorelse_id}")
        url = data.get("url")
        text_content = data.get("textContent", "")

        if not ENABLE_KUNGORELSE_CAPTURE:
            print(f"[KUNGORELSE] Capture disabled, skipping {kungorelse_id}")
            return jsonify({
                "ok": True,
                "status": "skipped",
                "kungorelseId": kungorelse_id,
                "message": "Kungorelse capture disabled"
            })
        
        is_valid, invalid_reason = _validate_kungorelse_payload(url, text_content)
        if not is_valid:
            print(f"  -> SKIP {kungorelse_id}: {invalid_reason}")
            return jsonify({
                "ok": True,
                "status": "skipped_invalid_page",
                "kungorelseId": kungorelse_id,
                "reason": invalid_reason,
                "url": url
            })

        # Create folder for this kungorelse in today's date folder
        import os
        date_str = os.environ.get('TARGET_DATE', datetime.now().strftime("%Y%m%d"))
        print(f"[SERVER] save_kungorelse: Använder datum: {date_str} (TARGET_DATE={'satt' if os.environ.get('TARGET_DATE') else 'ej satt'})")
        date_folder = os.path.join(DATA_DIR, date_str)
        os.makedirs(date_folder, exist_ok=True)
        folder_path = os.path.join(date_folder, kungorelse_id)
        
        # Check if already exists and has meaningful content (deduplicering)
        text_file = os.path.join(folder_path, "content.txt")
        if os.path.exists(text_file):
            file_size = os.path.getsize(text_file)
            # If file exists and has content (> 200 bytes = has actual text content, not just headers)
            if file_size > 200:
                print(f"  -> SKIP {kungorelse_id}: Already exists with content ({file_size} bytes)")
                return jsonify({
                    "ok": True,
                    "status": "already_exists",
                    "kungorelseId": kungorelse_id,
                    "path": folder_path,
                    "message": "Kungorelse already saved"
                })
        
        os.makedirs(folder_path, exist_ok=True)
        
        # Save text content
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(f"URL: {data.get('url', 'N/A')}\n")
            f.write(f"Title: {data.get('title', 'N/A')}\n")
            f.write(f"Timestamp: {data.get('timestamp', 'N/A')}\n")
            f.write(f"{'='*60}\n\n")
            f.write(data.get('textContent', ''))
        
        # Save HTML content (for reference)
        html_file = os.path.join(folder_path, "content.html")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(data.get('htmlContent', ''))
        
        # Save full JSON data
        json_file = os.path.join(folder_path, "data.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Log if enabled
        if ENABLE_TRAFFIC_LOG:
            _log_traffic("POST", f"/kungorelse/{kungorelse_id}", "saved", {"kungorelse_id": kungorelse_id})
        
        print(f"[KUNGORELSE] OK Saved {kungorelse_id}")
        print(f"  -> Path: {folder_path}")
        print("  -> Files: content.txt, content.html, data.json")
        
        return jsonify({
            "ok": True,
            "kungorelseId": kungorelse_id,
            "path": folder_path,
            "files": ["content.txt", "content.html", "data.json"]
        })
        
    except Exception as e:
        print(f"[KUNGORELSE ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/save")
def save():
    """
    Huvud-ingång:
    - Tar emot JSON i flera varianter:
        1) { "url": "...", "data": <obj|lista> }  <- rekommenderat från extensionen
        2) <obj|lista>                             <- ren JSON
    - Om body inte är JSON: sparas ändå som JSON med fält "raw_text".
    """
    print(f"\n[REQUEST] POST /save från {request.remote_addr}")
    # 1) Försök läsa JSON direkt
    incoming = None
    try:
        incoming = request.get_json(force=False, silent=True)
        if incoming:
            print(f"  -> JSON mottagen, typ: {type(incoming).__name__}")
    except Exception as e:
        print(f"  -> JSON parse error: {e}")
        incoming = None

    # 2) Normalisera till {meta, data} eller {meta, raw_text}
    packed, raw_bytes = _normalize_payload(incoming)

    # 3) Spara med deduplicering (om aktiverat)
    if ENABLE_DATA_LOGGING:
        result = _save_payload(packed, raw_bytes)
    else:
        result = {
            "ok": True,
            "status": "skipped",
            "hash": "disabled",
            "file": None,
            "meta": packed.get("meta", {})
        }

    # 4) Log traffic (om aktiverat)
    url = packed.get("meta", {}).get("url", "unknown")
    if ENABLE_TRAFFIC_LOG:
        _log_traffic("POST", url, result["status"], packed.get("meta", {}))
    
    # 5) Save interesting documents (om aktiverat)
    if ENABLE_DOCUMENT_SAVE and "data" in packed:
        _save_interesting_document(packed["data"], url)

    # Console output - mer detaljerad logging
    url_display = url[:60] + "..." if len(url) > 60 else url
    status_msg = f"[SAVE] {result['status']}"
    if ENABLE_DATA_LOGGING and result.get('hash'):
        status_msg += f" [{result['hash'][:6]}]"
    if result['status'] != 'duplicate' and result['status'] != 'skipped':
        print(f"{status_msg} | URL: {url_display}")
        if 'meta' in packed and packed['meta'].get('item_count'):
            print(f"  -> {packed['meta']['item_count']} items")
    else:
        print(f"{status_msg} | (duplicate/skipped)")
    return jsonify(result), (200 if result["ok"] else 500)


# --- start ---
if __name__ == "__main__":
    # Kör i dev-läge. För produktion: kör via waitress/uvicorn etc.
    # Windows 11-vänligt.
    app.run(host="127.0.0.1", port=51234, debug=False)
