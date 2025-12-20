#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
erase.py - Robust cleanup script for pipeline input/output directories

Removes previous run data to ensure clean pipeline execution.
Can be called as a module or standalone script.

Usage:
    python utils/erase.py              # Clean today's data only (default)
    python utils/erase.py --all       # Clean all date directories
    python utils/erase.py --all-logs  # Also clean old log files

    # As module:
    from utils.erase import cleanup_pipeline_data
    cleanup_pipeline_data(clean_today_only=True, keep_old_logs=True)
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# Fix encoding for Windows terminal
# Only modify when running as standalone script (not when imported)
# This avoids conflicts when imported from main.py which already fixes encoding
if sys.platform == "win32" and __name__ == "__main__":
    import io

    try:
        if (
            not isinstance(sys.stdout, io.TextIOWrapper)
            or getattr(sys.stdout, "encoding", None) != "utf-8"
        ):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
    except (AttributeError, ValueError):
        pass  # Already closed or not a buffer, skip
    try:
        if (
            not isinstance(sys.stderr, io.TextIOWrapper)
            or getattr(sys.stderr, "encoding", None) != "utf-8"
        ):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
    except (AttributeError, ValueError):
        pass  # Already closed or not a buffer, skip

# Project root (utils/erase.py -> utils/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories
POIT_DIR = PROJECT_ROOT / "1_poit"
SEGMENT_DIR = PROJECT_ROOT / "2_segment_info"

# Chrome profile paths
CHROME_PROFILES = [
    PROJECT_ROOT / "1_poit" / "automation" / "chrome_profile",
    PROJECT_ROOT / "headless_1_poit" / "chrome_profile",
]

# Cache folders that are SAFE to delete (won't affect login/session)
CHROME_CACHE_FOLDERS = [
    "Default/Cache",
    "Default/Code Cache", 
    "Default/GPUCache",
    "Default/Service Worker",
    "Default/blob_storage",
    "Default/File System",
    "Default/WebStorage",
    "GrShaderCache",
    "ShaderCache",
    "component_crx_cache",
]

# Files that are SAFE to delete
CHROME_CACHE_FILES = [
    "Default/LOCK",
    "Default/LOG",
    "Default/LOG.old",
]

# NEVER delete these (contains session/login data)
CHROME_PROTECTED = [
    "Default/Cookies",
    "Default/Cookies-journal",
    "Default/Local Storage",
    "Default/Session Storage",
    "Default/Preferences",
    "Default/Secure Preferences",
    "Default/Login Data",
    "Default/Login Data-journal",
    "Default/Extension*",
    "Default/IndexedDB",  # Some sites use this for session
    "Local State",
]


def ts() -> str:
    """Timestamp for logging."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_info(msg: str):
    """Log info message."""
    print(f"[ERASE {ts()}] {msg}")


def log_warn(msg: str):
    """Log warning message."""
    print(f"[ERASE {ts()}] WARN: {msg}")


def log_error(msg: str):
    """Log error message."""
    print(f"[ERASE {ts()}] ERROR: {msg}")


def load_chrome_cleanup_config() -> dict:
    """
    Load Chrome profile cleanup configuration from environment variables.
    Falls back to sensible defaults if not set.
    
    Returns:
        Dictionary with cleanup settings.
    """
    import os
    
    # Try to load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass
    
    def get_bool(key: str, default: bool) -> bool:
        val = os.environ.get(key, "").lower()
        if val in ("true", "1", "yes", "y"):
            return True
        elif val in ("false", "0", "no", "n"):
            return False
        return default
    
    def get_int(key: str, default: int) -> int:
        val = os.environ.get(key, "")
        try:
            return int(val)
        except (ValueError, TypeError):
            return default
    
    return {
        "enabled": get_bool("CHROME_CACHE_CLEANUP_ENABLED", True),
        "max_size_mb": get_int("CHROME_PROFILE_MAX_SIZE_MB", 200),
        "clean_http_cache": get_bool("CHROME_CLEAN_HTTP_CACHE", True),
        "clean_code_cache": get_bool("CHROME_CLEAN_CODE_CACHE", True),
        "clean_gpu_cache": get_bool("CHROME_CLEAN_GPU_CACHE", True),
        "clean_service_worker": get_bool("CHROME_CLEAN_SERVICE_WORKER", True),
        "clean_blob_storage": get_bool("CHROME_CLEAN_BLOB_STORAGE", True),
        "allow_full_reset": get_bool("CHROME_ALLOW_FULL_RESET", False),
    }


def get_profile_size_mb(profile_dir: Path) -> float:
    """
    Calculate total size of a Chrome profile directory in MB.
    
    Args:
        profile_dir: Path to Chrome profile directory.
    
    Returns:
        Size in megabytes.
    """
    if not profile_dir.exists():
        return 0.0
    
    total_bytes = 0
    try:
        for item in profile_dir.rglob("*"):
            if item.is_file():
                try:
                    total_bytes += item.stat().st_size
                except (OSError, PermissionError):
                    pass
    except Exception:
        pass
    
    return total_bytes / (1024 * 1024)


def clean_chrome_profile_cache(
    profile_dir: Path,
    config: dict = None
) -> Tuple[int, float]:
    """
    Clean cache from a Chrome profile while preserving session/login data.
    
    Args:
        profile_dir: Path to Chrome profile directory.
        config: Optional config dict from load_chrome_cleanup_config().
    
    Returns:
        Tuple of (items_removed, mb_freed).
    """
    if not profile_dir.exists():
        return 0, 0.0
    
    if config is None:
        config = load_chrome_cleanup_config()
    
    if not config["enabled"]:
        log_info(f"Chrome cache cleanup disabled for {profile_dir.name}")
        return 0, 0.0
    
    # Calculate size before cleanup
    size_before = get_profile_size_mb(profile_dir)
    
    items_removed = 0
    
    # Build list of folders to clean based on config
    folders_to_clean = []
    if config["clean_http_cache"]:
        folders_to_clean.extend(["Default/Cache", "Default/Cache2"])
    if config["clean_code_cache"]:
        folders_to_clean.append("Default/Code Cache")
    if config["clean_gpu_cache"]:
        folders_to_clean.extend(["Default/GPUCache", "GrShaderCache", "ShaderCache"])
    if config["clean_service_worker"]:
        folders_to_clean.append("Default/Service Worker")
    if config["clean_blob_storage"]:
        folders_to_clean.extend(["Default/blob_storage", "Default/File System"])
    
    # Always safe to clean these
    folders_to_clean.extend([
        "component_crx_cache",
        "Default/WebStorage",
        "Crashpad",
        "BrowserMetrics",
    ])
    
    # Clean folders
    for folder_name in folders_to_clean:
        folder_path = profile_dir / folder_name
        if folder_path.exists() and folder_path.is_dir():
            try:
                shutil.rmtree(folder_path)
                log_info(f"  Rensade: {folder_name}")
                items_removed += 1
            except PermissionError:
                log_warn(f"  Kunde inte rensa (låst): {folder_name}")
            except Exception as e:
                log_warn(f"  Fel vid rensning av {folder_name}: {e}")
    
    # Clean log files
    for file_name in CHROME_CACHE_FILES:
        file_path = profile_dir / file_name
        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
                items_removed += 1
            except Exception:
                pass
    
    # Calculate size after cleanup
    size_after = get_profile_size_mb(profile_dir)
    mb_freed = max(0, size_before - size_after)
    
    return items_removed, mb_freed


def clean_all_chrome_profiles(full_reset: bool = False) -> Tuple[int, float, List[str]]:
    """
    Clean all Chrome profiles used by the pipeline.
    
    Args:
        full_reset: If True and CHROME_ALLOW_FULL_RESET is enabled,
                   delete entire profiles (requires re-login).
    
    Returns:
        Tuple of (total_items_removed, total_mb_freed, list_of_warnings).
    """
    config = load_chrome_cleanup_config()
    
    log_info("=" * 60)
    log_info("CHROME PROFIL-RENSNING")
    log_info("=" * 60)
    
    total_items = 0
    total_mb_freed = 0.0
    warnings = []
    
    for profile_dir in CHROME_PROFILES:
        if not profile_dir.exists():
            log_info(f"Profil finns inte (OK): {profile_dir.relative_to(PROJECT_ROOT)}")
            continue
        
        # Calculate current size
        size_mb = get_profile_size_mb(profile_dir)
        log_info(f"\nProfil: {profile_dir.relative_to(PROJECT_ROOT)}")
        log_info(f"  Storlek före: {size_mb:.1f} MB")
        
        # Warn if profile is very large
        if size_mb > config["max_size_mb"]:
            warn_msg = f"Profilen är stor ({size_mb:.0f} MB > {config['max_size_mb']} MB)"
            log_warn(f"  ⚠️  {warn_msg}")
            warnings.append(warn_msg)
        
        if full_reset and config["allow_full_reset"]:
            # DANGER: Full profile reset
            log_warn("  🔴 FULLSTÄNDIG RESET - Raderar HELA profilen!")
            try:
                shutil.rmtree(profile_dir)
                total_items += 1
                total_mb_freed += size_mb
                log_info(f"  Profil raderad. Du måste logga in igen!")
            except Exception as e:
                warnings.append(f"Kunde inte radera profil: {e}")
        else:
            # Safe cache cleanup
            items, mb_freed = clean_chrome_profile_cache(profile_dir, config)
            total_items += items
            total_mb_freed += mb_freed
            
            # Show size after cleanup
            size_after = get_profile_size_mb(profile_dir)
            log_info(f"  Storlek efter: {size_after:.1f} MB (frigjorde {mb_freed:.1f} MB)")
    
    log_info("")
    log_info("=" * 60)
    log_info(f"CHROME CLEANUP KLAR: {total_items} objekt, {total_mb_freed:.1f} MB frigjort")
    if warnings:
        log_info(f"Varningar: {len(warnings)}")
    log_info("=" * 60)
    
    return total_items, total_mb_freed, warnings


def remove_path(path: Path, description: str = "") -> bool:
    """
    Safely remove a file or directory.

    Args:
        path: Path to remove
        description: Optional description for logging

    Returns:
        True if removed successfully, False otherwise
    """
    if not path.exists():
        return False

    try:
        if path.is_file():
            path.unlink()
            log_info(f"Removed file: {path.name} {description}")
            return True
        elif path.is_dir():
            shutil.rmtree(path)
            log_info(f"Removed directory: {path.name} {description}")
            return True
    except PermissionError as e:
        log_error(f"Permission denied removing {path}: {e}")
        return False
    except Exception as e:
        log_error(f"Could not remove {path}: {e}")
        return False

    return False


def remove_pycache_dirs(root: Path, label: str = "") -> int:
    """
    Remove all __pycache__ directories under a root path.

    Args:
        root: Base directory to scan
        label: Optional label for logging context

    Returns:
        Number of __pycache__ directories removed
    """
    if not root.exists():
        return 0

    removed = 0
    for pycache_dir in root.rglob("__pycache__"):
        if pycache_dir.is_dir():
            if remove_path(pycache_dir, f"(pycache {label})"):
                removed += 1
    return removed


def clean_today_date_dir(base_dir: Path, date_str: str) -> int:
    """
    Clean today's date directory if it exists.

    Args:
        base_dir: Base directory containing date folders
        date_str: Date string (YYYYMMDD)

    Returns:
        Number of items removed
    """
    date_dir = base_dir / date_str

    if not date_dir.exists():
        return 0

    log_info(f"Cleaning today's date directory: {date_dir.name}/")

    # Remove entire date directory
    if remove_path(date_dir, f"(date: {date_str})"):
        return 1

    return 0


def clean_today_k_folders(base_dir: Path, date_str: str) -> int:
    """
    Clean K-folders (company folders) in today's date directory.

    Args:
        base_dir: Base directory containing date folders
        date_str: Date string (YYYYMMDD)

    Returns:
        Number of K-folders removed
    """
    date_dir = base_dir / date_str

    if not date_dir.exists():
        return 0

    # Find all K-folders (folders starting with "K" and containing "-")
    k_folders = [
        d
        for d in date_dir.iterdir()
        if d.is_dir() and d.name.startswith("K") and "-" in d.name
    ]

    if not k_folders:
        return 0

    log_info(f"Cleaning {len(k_folders)} K-folders from {date_dir.name}/")

    removed_count = 0
    for k_folder in k_folders:
        if remove_path(k_folder, f"(K-folder: {k_folder.name})"):
            removed_count += 1

    return removed_count


def clean_today_logs(log_dir: Path, date_str: str) -> int:
    """
    Clean log files from today in a directory.

    Args:
        log_dir: Directory containing log files
        date_str: Date string (YYYYMMDD)

    Returns:
        Number of log files removed
    """
    if not log_dir.exists():
        return 0

    # Pattern: *_YYYYMMDD_*.log or similar
    pattern = re.compile(rf".*{date_str}.*\.log$", re.IGNORECASE)

    log_files = [f for f in log_dir.iterdir() if f.is_file() and pattern.match(f.name)]

    if not log_files:
        return 0

    log_info(f"Cleaning {len(log_files)} log files from {log_dir.name}/")

    removed_count = 0
    for log_file in log_files:
        if remove_path(log_file, f"(log: {log_file.name})"):
            removed_count += 1

    return removed_count


def truncate_traffic_log(log_path: Path) -> bool:
    """
    Truncate (empty) the traffic log file instead of deleting it.

    Args:
        log_path: Path to traffic.log

    Returns:
        True if truncated successfully
    """
    if not log_path.exists():
        return False

    try:
        log_path.write_text("", encoding="utf-8")
        log_info(f"Truncated traffic log: {log_path.name}")
        return True
    except Exception as e:
        log_error(f"Could not truncate {log_path}: {e}")
        return False


def clean_metadata_files(segment_dir: Path) -> int:
    """
    Clean metadata files that should be regenerated.

    Args:
        segment_dir: 2_segment_info directory

    Returns:
        Number of files removed
    """
    metadata_files = [
        segment_dir / "in" / "companies.jsonl",
        segment_dir / "analysis.jsonl",
        segment_dir / ".metadata" / "manifest.json",
    ]

    removed_count = 0
    for file_path in metadata_files:
        if file_path.exists():
            if remove_path(file_path, "(metadata)"):
                removed_count += 1

    return removed_count


def clean_today_metadata_dir(segment_dir: Path, date_str: str) -> int:
    """
    Clean today's metadata directory in djupanalys.

    Args:
        segment_dir: 2_segment_info directory
        date_str: Date string (YYYYMMDD)

    Returns:
        Number of items removed
    """
    metadata_dir = segment_dir / "djupanalys" / date_str / ".metadata"

    if not metadata_dir.exists():
        return 0

    log_info("Cleaning today's metadata directory: .metadata/")

    # Remove entire .metadata directory
    if remove_path(metadata_dir, f"(metadata for {date_str})"):
        return 1

    return 0


def clean_all_pipeline_data() -> Tuple[int, List[str]]:
    """
    Rensar ALLT i pipeline-mapparna för en helt ren start.
    Anropas före varje körning för att garantera ingen duplicering.
    """
    log_info("=" * 60)
    log_info("TOTAL PIPELINE CLEANUP - Rensar ALLT!")
    log_info("=" * 60)

    total_removed = 0
    errors = []

    try:
        # 1. Rensa HELA info_server mappen
        info_server_dir = POIT_DIR / "info_server"
        if info_server_dir.exists():
            # Ta bort alla datummappar
            for item in info_server_dir.iterdir():
                if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
                    if remove_path(item, f"(date dir: {item.name})"):
                        total_removed += 1
            # Ta bort alla JSON/CSV filer i root
            for pattern in ["*.json", "*.csv", "*.db", "*.xlsx"]:
                for file in info_server_dir.glob(pattern):
                    if remove_path(file, f"({pattern})"):
                        total_removed += 1
            log_info("Rensade info_server/")

        # 2. Rensa HELA djupanalys mappen
        djupanalys_dir = SEGMENT_DIR / "djupanalys"
        if djupanalys_dir.exists():
            # Ta bort alla datummappar
            for item in djupanalys_dir.iterdir():
                if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
                    if remove_path(item, f"(date dir: {item.name})"):
                        total_removed += 1
            # Ta bort ALLA loggfiler
            for log_file in djupanalys_dir.glob("*.log"):
                if remove_path(log_file, "(log)"):
                    total_removed += 1
            # Ta bort zip-arkiv (t.ex. 20251217.zip)
            for zip_file in djupanalys_dir.glob("*.zip"):
                if remove_path(zip_file, "(djupanalys zip)"):
                    total_removed += 1
            log_info("Rensade djupanalys/")

        # 3. Rensa in/ mappen (filer och undermappar)
        in_dir = SEGMENT_DIR / "in"
        if in_dir.exists():
            for item in in_dir.iterdir():
                if item.is_file():
                    if remove_path(item, "(input file)"):
                        total_removed += 1
                elif item.is_dir():
                    # Rensa även undermappar (t.ex. text/)
                    if remove_path(item, f"(input dir: {item.name})"):
                        total_removed += 1
            log_info("Rensade in/")

        # 4. Rensa traffic.log
        traffic_log = POIT_DIR / "log" / "traffic.log"
        if traffic_log.exists():
            if truncate_traffic_log(traffic_log):
                total_removed += 1

        # 5. Rensa screenshot_logs mappen (automation debug-bilder)
        screenshot_logs_dir = POIT_DIR / "automation" / "screenshot_logs"
        if screenshot_logs_dir.exists():
            for item in screenshot_logs_dir.iterdir():
                if item.is_file() and item.suffix.lower() in [".png", ".jpg", ".jpeg"]:
                    if remove_path(item, "(screenshot log)"):
                        total_removed += 1
            log_info("Rensade screenshot_logs/")

        # 6. Rensa huvudlogg-mappen (logs/steps/*.log och logs/main_*.log)
        logs_dir = PROJECT_ROOT / "logs"
        if logs_dir.exists():
            # Rensa step-loggar
            steps_dir = logs_dir / "steps"
            if steps_dir.exists():
                for log_file in steps_dir.glob("*.log"):
                    if remove_path(log_file, "(step log)"):
                        total_removed += 1
            # Rensa main_*.log filer
            for log_file in logs_dir.glob("main_*.log"):
                if remove_path(log_file, "(main log)"):
                    total_removed += 1
            # Rensa alla_*.log filer
            for log_file in logs_dir.glob("alla_*.log"):
                if remove_path(log_file, "(alla log)"):
                    total_removed += 1
            log_info("Rensade logs/")

        # 7. Rensa 10_jocke datummappar (behåller data_bundles/ med zip-arkiv!)
        jocke_dir = PROJECT_ROOT / "10_jocke"
        if jocke_dir.exists():
            for item in jocke_dir.iterdir():
                # Endast radera datummappar, INTE data_bundles/
                if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
                    if remove_path(item, f"(jocke date dir: {item.name})"):
                        total_removed += 1
            log_info("Rensade 10_jocke/ (bevarade data_bundles/)")

        # 8. Rensa root-nivå loggfiler (logg.txt, logg server.txt etc)
        for log_pattern in ["logg*.txt", "logg *.txt"]:
            for log_file in PROJECT_ROOT.glob(log_pattern):
                if log_file.is_file():
                    if remove_path(log_file, "(root log)"):
                        total_removed += 1
        log_info("Rensade root-loggfiler")

        # 9. Rensa __pycache__-mappar (förhindrar gamla bytecode-filer)
        total_removed += remove_pycache_dirs(POIT_DIR, "1_poit")
        total_removed += remove_pycache_dirs(SEGMENT_DIR, "2_segment_info")
        total_removed += remove_pycache_dirs(PROJECT_ROOT / "3_sajt", "3_sajt")
        total_removed += remove_pycache_dirs(PROJECT_ROOT / "utils", "utils")

    except Exception as e:
        error_msg = f"Error during total cleanup: {e}"
        log_error(error_msg)
        errors.append(error_msg)

    log_info("=" * 60)
    log_info(f"TOTAL CLEANUP - Complete. Removed {total_removed} items")
    if errors:
        log_info(f"Errors: {len(errors)}")
    log_info("=" * 60)

    return total_removed, errors


def cleanup_old_directories(base_dir: Path, keep_days: int = 7) -> int:
    """
    Rensa gamla datummappar (YYYYMMDD) som är äldre än keep_days dagar.

    Args:
        base_dir: Basmapp att rensa i
        keep_days: Antal dagar att behålla (default: 7)

    Returns:
        Antal mappar som raderades
    """
    if not base_dir.exists():
        return 0

    from datetime import timedelta

    cutoff_date = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff_date.strftime("%Y%m%d")

    removed_count = 0
    date_dirs = []

    # Hitta alla datummappar
    for item in base_dir.iterdir():
        if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
            date_dirs.append(item)

    # Sortera och ta bort gamla
    date_dirs.sort(key=lambda x: x.name)

    for date_dir in date_dirs:
        if date_dir.name < cutoff_str:
            try:
                log_info(
                    f"Rensar gammal mapp: {date_dir.name} (äldre än {keep_days} dagar)"
                )
                shutil.rmtree(date_dir)
                removed_count += 1
            except Exception as e:
                log_warn(f"Kunde inte radera {date_dir.name}: {e}")

    return removed_count


def run_full_cleanup(keep_days: int = 7, clean_chrome: bool = True) -> Tuple[int, List[str]]:
    """
    Kör komplett cleanup: rensar gamla mappar OCH all data för dagens körning.
    Detta är huvudfunktionen som anropas från main.py vid start.

    Args:
        keep_days: Antal dagar att behålla gamla mappar (default: 7)
        clean_chrome: Om True, rensa Chrome-profilernas cache (default: True)

    Returns:
        Tuple of (total_items_removed, list_of_errors)
    """
    log_info("=" * 60)
    log_info("KOMPLETT CLEANUP - Startar")
    log_info("=" * 60)
    print()

    total_removed = 0
    all_errors = []

    # Steg 1: Rensa gamla mappar (>keep_days dagar)
    log_info("Steg 1: Rensar gamla mappar (>{} dagar)...".format(keep_days))
    try:
        info_server_dir = POIT_DIR / "info_server"
        djupanalys_dir = SEGMENT_DIR / "djupanalys"

        removed_info = cleanup_old_directories(info_server_dir, keep_days=keep_days)
        removed_djup = cleanup_old_directories(djupanalys_dir, keep_days=keep_days)

        log_info(f"Rensade {removed_info} gamla mappar från info_server/")
        log_info(f"Rensade {removed_djup} gamla mappar från djupanalys/")
        total_removed += removed_info + removed_djup
    except Exception as e:
        error_msg = f"Fel vid rensning av gamla mappar: {e}"
        log_error(error_msg)
        all_errors.append(error_msg)

    print()

    # Steg 2: Rensa ALL data för dagens körning
    log_info("Steg 2: Rensar ALL data för dagens körning...")
    try:
        removed_count, errors = clean_all_pipeline_data()
        total_removed += removed_count
        all_errors.extend(errors)
        if not errors:
            log_info(f"Cleanup klar: {removed_count} objekt raderade")
    except Exception as e:
        error_msg = f"Fel vid rensning av all data: {e}"
        log_error(error_msg)
        all_errors.append(error_msg)

    print()

    # Steg 3: Rensa Chrome-profilernas cache (om aktiverat)
    if clean_chrome:
        log_info("Steg 3: Rensar Chrome-profilernas cache...")
        try:
            chrome_items, chrome_mb, chrome_warnings = clean_all_chrome_profiles(full_reset=False)
            total_removed += chrome_items
            all_errors.extend(chrome_warnings)
            log_info(f"Chrome cache rensad: {chrome_items} objekt, {chrome_mb:.1f} MB frigjort")
        except Exception as e:
            error_msg = f"Fel vid rensning av Chrome-profiler: {e}"
            log_error(error_msg)
            all_errors.append(error_msg)
        print()
    
    log_info("=" * 60)
    log_info(f"KOMPLETT CLEANUP - Klar. Totalt {total_removed} objekt raderade")
    if all_errors:
        log_info(f"Varningar/fel: {len(all_errors)}")
    log_info("=" * 60)

    return total_removed, all_errors


def cleanup_pipeline_data(
    clean_today_only: bool = True,
    keep_old_logs: bool = True,
    force_clean_all: bool = False,
) -> Tuple[int, List[str]]:
    """
    Main cleanup function - removes previous run data.

    Args:
        clean_today_only: If True, only clean today's data. If False, clean all date dirs.
        keep_old_logs: If True, keep log files older than today.
        force_clean_all: If True, clean EVERYTHING including all dates and logs (for fresh start)

    Returns:
        Tuple of (total_items_removed, list_of_errors)
    """
    today = datetime.now().strftime("%Y%m%d")
    total_removed = 0
    errors = []

    log_info("=" * 60)
    log_info("PIPELINE CLEANUP - Starting")
    log_info("=" * 60)
    log_info(f"Today's date: {today}")
    log_info(f"Clean today only: {clean_today_only}")
    log_info(f"Keep old logs: {keep_old_logs}")
    log_info(f"Force clean all: {force_clean_all}")
    print()

    # Override settings if force_clean_all is True
    if force_clean_all:
        log_info("FORCE CLEAN ALL aktiverat - rensar ALLT!")
        clean_today_only = False
        keep_old_logs = False

    try:
        # 1. Clean 1_poit/info_server/YYYYMMDD/ (today's scraped data)
        info_server_dir = POIT_DIR / "info_server"
        if info_server_dir.exists():
            # ALLTID rensa dagens mapp helt för att undvika duplicering
            removed = clean_today_date_dir(info_server_dir, today)
            total_removed += removed
            if removed > 0:
                log_info(f"Cleaned today's date directory from info_server/{today}/")

            # Rensa också kungorelser_*.json filer i root (om de finns där)
            for json_file in info_server_dir.glob(f"kungorelser_{today}.json"):
                if remove_path(json_file, "(kungörelse JSON)"):
                    total_removed += 1
            for csv_file in info_server_dir.glob(f"kungorelser_{today}.csv"):
                if remove_path(csv_file, "(kungörelse CSV)"):
                    total_removed += 1

            if not clean_today_only:
                # Clean all date directories
                date_dirs = [
                    d
                    for d in info_server_dir.iterdir()
                    if d.is_dir() and re.fullmatch(r"\d{8}", d.name)
                ]
                for date_dir in date_dirs:
                    if remove_path(date_dir, f"(date: {date_dir.name})"):
                        total_removed += 1
                if date_dirs:
                    log_info(
                        f"Cleaned {len(date_dirs)} date directories from info_server/"
                    )
        else:
            log_warn(f"Directory does not exist: {info_server_dir}")
        print()

        # 2. Clean 2_segment_info/djupanalys/YYYYMMDD/ (today's processed data)
        djupanalys_dir = SEGMENT_DIR / "djupanalys"
        if djupanalys_dir.exists():
            # VIKTIGT: Rensa hela dagens mapp för att undvika duplicering!
            removed = clean_today_date_dir(djupanalys_dir, today)
            total_removed += removed
            if removed > 0:
                log_info(f"Cleaned today's date directory from djupanalys/{today}/")

            if not clean_today_only:
                # Clean all date directories
                date_dirs = [
                    d
                    for d in djupanalys_dir.iterdir()
                    if d.is_dir() and re.fullmatch(r"\d{8}", d.name)
                ]
                for date_dir in date_dirs:
                    if remove_path(date_dir, f"(date: {date_dir.name})"):
                        total_removed += 1
                if date_dirs:
                    log_info(
                        f"Cleaned {len(date_dirs)} date directories from djupanalys/"
                    )
        else:
            log_warn(f"Directory does not exist: {djupanalys_dir}")
        print()

        # 3. Clean 2_segment_info/in/ directory (input data)
        in_dir = SEGMENT_DIR / "in"
        if in_dir.exists():
            # Rensa companies.jsonl och andra input-filer
            for file in in_dir.glob("*.jsonl"):
                if remove_path(file, "(input file)"):
                    total_removed += 1
            for file in in_dir.glob("*.csv"):
                if remove_path(file, "(input file)"):
                    total_removed += 1
            log_info("Cleaned input files from in/")
        print()

        # 4. Clean log files in djupanalys root (today's step logs)
        if djupanalys_dir.exists():
            removed_logs = clean_today_logs(djupanalys_dir, today)
            total_removed += removed_logs
            if removed_logs > 0:
                log_info(f"Cleaned {removed_logs} log files from djupanalys/")
            elif not keep_old_logs:
                # Remove all log files
                log_files = list(djupanalys_dir.glob("*.log"))
                for log_file in log_files:
                    if remove_path(log_file, "(log)"):
                        total_removed += 1
                if log_files:
                    log_info(f"Cleaned {len(log_files)} log files from djupanalys/")
        print()

        # 5. Clean metadata files (always)
        if SEGMENT_DIR.exists():
            removed_meta = clean_metadata_files(SEGMENT_DIR)
            total_removed += removed_meta
            if removed_meta > 0:
                log_info(f"Cleaned {removed_meta} metadata files")
        else:
            log_warn(f"Directory does not exist: {SEGMENT_DIR}")
        print()

        # 6. Clean/truncate 1_poit/log/traffic.log
        traffic_log = POIT_DIR / "log" / "traffic.log"
        if traffic_log.exists():
            if truncate_traffic_log(traffic_log):
                total_removed += 1
        print()

        # 7. Clean old server logs (optional - only if not keeping old logs)
        if not keep_old_logs:
            logs_dir = POIT_DIR / "logs"
            if logs_dir.exists():
                log_files = list(logs_dir.glob("*.log"))
                for log_file in log_files:
                    if remove_path(log_file, "(server log)"):
                        total_removed += 1
                if log_files:
                    log_info(f"Cleaned {len(log_files)} server log files")

    except Exception as e:
        error_msg = f"Error during cleanup: {e}"
        log_error(error_msg)
        errors.append(error_msg)
        import traceback

        traceback.print_exc()

    log_info("=" * 60)
    log_info("PIPELINE CLEANUP - Complete")
    log_info(f"Total items removed: {total_removed}")
    if errors:
        log_info(f"Errors encountered: {len(errors)}")
        for error in errors:
            log_error(f"  - {error}")
    log_info("=" * 60)

    return total_removed, errors


def main():
    """Main entry point for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean pipeline input/output directories before new run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python utils/erase.py              # Clean today's data only (default)
  python utils/erase.py --all        # Clean all date directories
  python utils/erase.py --all-logs   # Also clean old log files
  python utils/erase.py --chrome     # Clean only Chrome profile cache
  python utils/erase.py --chrome-full  # Full Chrome reset (kräver CHROME_ALLOW_FULL_RESET=true)
""",
    )
    parser.add_argument(
        "--all", action="store_true", help="Clean all date directories, not just today"
    )
    parser.add_argument(
        "--all-logs",
        action="store_true",
        help="Also clean old log files (not just today)",
    )
    parser.add_argument(
        "--chrome",
        action="store_true",
        help="Clean only Chrome profile cache (keeps session/login)",
    )
    parser.add_argument(
        "--chrome-full",
        action="store_true",
        help="Full Chrome profile reset (requires CHROME_ALLOW_FULL_RESET=true in .env)",
    )
    parser.add_argument(
        "--no-chrome",
        action="store_true",
        help="Skip Chrome profile cleanup",
    )

    args = parser.parse_args()

    # Handle Chrome-only operations
    if args.chrome or args.chrome_full:
        items, mb_freed, warnings = clean_all_chrome_profiles(full_reset=args.chrome_full)
        if warnings:
            for w in warnings:
                log_warn(w)
            return 1 if args.chrome_full else 0
        return 0

    clean_today_only = not args.all
    keep_old_logs = not args.all_logs

    total_removed, errors = cleanup_pipeline_data(
        clean_today_only=clean_today_only, keep_old_logs=keep_old_logs
    )

    # Also run Chrome cleanup unless --no-chrome
    if not args.no_chrome:
        chrome_items, chrome_mb, chrome_warnings = clean_all_chrome_profiles(full_reset=False)
        total_removed += chrome_items
        errors.extend(chrome_warnings)

    if errors:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
