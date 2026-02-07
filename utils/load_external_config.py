#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_external_config.py - Load pipeline configuration from the dashboard API

Fetches configuration from the dashboard (jocke.onrender.com) and applies it
to the local config files so the pipeline runs with the latest settings.

Usage in main.py:
    from utils.load_external_config import fetch_and_apply_dashboard_config
    fetch_and_apply_dashboard_config(dashboard_url, jocke_api_key)
"""

import json
import os
import shutil
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POIT_CONFIG = PROJECT_ROOT / "1_poit" / "config.txt"
SEGMENT_CONFIG = PROJECT_ROOT / "2_segment_info" / "config_simple.txt"
SAJT_CONFIG = PROJECT_ROOT / "3_sajt" / "config_ny.txt"
BACKUP_DIR = PROJECT_ROOT / ".cursor" / "config_backups"

MAIL_TONE_KEYS = ("formality", "salesiness", "flattery", "length")


# ---------------------------------------------------------------------------
# Dashboard fetch
# ---------------------------------------------------------------------------

def fetch_config_from_dashboard(
    dashboard_url: str, api_key: str, timeout: int = 10
) -> Optional[Dict[str, Any]]:
    """
    Fetch pipeline configuration from the dashboard API.

    Args:
        dashboard_url: Base URL of the dashboard (e.g. https://jocke.onrender.com)
        api_key: JOCKE_API key for authentication
        timeout: HTTP timeout in seconds

    Returns:
        Parsed config dict or None on failure
    """
    url = f"{dashboard_url.rstrip('/')}/api/config"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        if resp.getcode() == 200:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and "poit" in data and "segment" in data and "sajt" in data:
                return data
            print(f"[DASHBOARD CONFIG] Unexpected response format from {url}")
            return None
    except urllib.error.HTTPError as e:
        print(f"[DASHBOARD CONFIG] HTTP {e.code} from {url}: {e.reason}")
    except urllib.error.URLError as e:
        print(f"[DASHBOARD CONFIG] Cannot reach {url}: {e.reason}")
    except Exception as e:
        print(f"[DASHBOARD CONFIG] Error fetching config: {e}")
    return None


def push_config_to_dashboard(
    dashboard_url: str, api_key: str, config: Dict[str, Any], timeout: int = 10
) -> bool:
    """
    Push pipeline configuration to the dashboard API.

    Args:
        dashboard_url: Base URL of the dashboard
        api_key: JOCKE_API key for authentication
        config: Config dict to push
        timeout: HTTP timeout in seconds

    Returns:
        True on success
    """
    url = f"{dashboard_url.rstrip('/')}/api/config"
    body = json.dumps(config).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("X-API-Key", api_key)
    req.add_header("Content-Type", "application/json")

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode() == 200
    except Exception as e:
        print(f"[DASHBOARD CONFIG] Error pushing config: {e}")
        return False


def fetch_and_apply_dashboard_config(dashboard_url: str, api_key: str) -> bool:
    """
    Fetch config from dashboard and apply to local config files.

    Returns:
        True if config was successfully fetched and applied
    """
    config = fetch_config_from_dashboard(dashboard_url, api_key)
    if config is None:
        return False

    # Backup before overwriting
    try:
        backup_configs()
    except Exception as e:
        print(f"[DASHBOARD CONFIG] Backup warning: {e}")

    # Apply
    success, message = apply_external_config(config)
    print(f"[DASHBOARD CONFIG] {message}")
    return success


# ---------------------------------------------------------------------------
# Config writers (write fetched config to local files)
# ---------------------------------------------------------------------------

def backup_configs() -> Path:
    """Create backup of all config files before overwriting."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_subdir = BACKUP_DIR / f"dashboard_override_{timestamp}"
    backup_subdir.mkdir(parents=True, exist_ok=True)

    for config_file in [POIT_CONFIG, SEGMENT_CONFIG, SAJT_CONFIG]:
        if config_file.exists():
            backup_path = backup_subdir / f"{config_file.parent.name}_{config_file.name}"
            shutil.copy2(config_file, backup_path)

    return backup_subdir


def write_poit_config(config: Dict[str, Any]) -> bool:
    """Write to 1_poit/config.txt"""
    try:
        poit_data = config.get("poit", {})
        max_kun = poit_data.get("MAX_KUN_DAG", 150)
        
        lines = [
            f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# Använd MAX_KUN_DAG=ALL för obegränsat",
            f"MAX_KUN_DAG={'ALL' if max_kun == 0 else max_kun}"
        ]
        
        POIT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        POIT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[CONFIG] Error writing poit config: {e}")
        return False


def write_segment_config(config: Dict[str, Any]) -> bool:
    """Write to 2_segment_info/config_simple.txt"""
    try:
        segment_data = config.get("segment", {})
        # Mail tone may be nested inside MAIL or at top level
        mail_tone = config.get("mail_tone", {})
        
        lines = [
            f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# Run with: python ALLA.py",
            "",
        ]
        
        # PIPELINE section
        pipeline = segment_data.get("PIPELINE", {})
        lines.append("# --- PIPELINE ---")
        lines.append("[PIPELINE]")
        lines.append(f"source_dir = {pipeline.get('source_dir', '1_poit/info_server')}")
        lines.append(f"max_companies = {pipeline.get('max_companies', 150)}")
        lines.append(f"delete_csv = {pipeline.get('delete_csv', 'y')}")
        lines.append("")
        
        # RESEARCH section
        research = segment_data.get("RESEARCH", {})
        lines.append("# --- AI-RESEARCH ---")
        lines.append("[RESEARCH]")
        lines.append(f"enabled = {research.get('enabled', 'y')}")
        lines.append(f"model = {research.get('model', 'gpt-4o')}")
        lines.append(f"max_searches = {research.get('max_searches', 3)}")
        lines.append(f"search_persons = {research.get('search_persons', 'y')}")
        lines.append(f"max_persons = {research.get('max_persons', 2)}")
        lines.append("")
        
        # DOMAIN section
        domain = segment_data.get("DOMAIN", {})
        lines.append("# --- DOMÄNVERIFIERING ---")
        lines.append("[DOMAIN]")
        lines.append(f"timeout_seconds = {domain.get('timeout_seconds', 5)}")
        lines.append(f"max_crawl = {domain.get('max_crawl', 5)}")
        lines.append(f"parallel_checks = {domain.get('parallel_checks', 5)}")
        lines.append("")
        
        # MAIL section (includes tone settings)
        mail = segment_data.get("MAIL", {})
        lines.append("# --- MAIL ---")
        lines.append("[MAIL]")
        lines.append(f"enabled = {mail.get('enabled', 'y')}")
        lines.append(f"model = {mail.get('model', 'gpt-4o')}")
        lines.append(f"min_confidence = {mail.get('min_confidence', 40)}")
        lines.append(f"max_mails = {mail.get('max_mails', 110)}")
        lines.append(f"formality = {mail_tone.get('formality', mail.get('formality', 4))}")
        lines.append(f"salesiness = {mail_tone.get('salesiness', mail.get('salesiness', 3))}")
        lines.append(f"flattery = {mail_tone.get('flattery', mail.get('flattery', 2))}")
        lines.append(f"length = {mail_tone.get('length', mail.get('length', 5))}")
        lines.append("")
        
        SEGMENT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        SEGMENT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[CONFIG] Error writing segment config: {e}")
        return False


def write_sajt_config(config: Dict[str, Any]) -> bool:
    """Write to 3_sajt/config_ny.txt"""
    try:
        sajt_data = config.get("sajt", {})
        
        lines = [
            f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "# --- EVALUATION ---",
            f"evaluate = {sajt_data.get('evaluate', 'y')}",
            f"threshold = {sajt_data.get('threshold', 0.80)}",
            f"max_total_judgement_approvals = {sajt_data.get('max_total_judgement_approvals', 4)}",
            "",
            "# --- SITE GENERATION ---",
            f"re_input_website_link = {sajt_data.get('re_input_website_link', 'y')}",
            f"max_sites = {sajt_data.get('max_sites', 4)}",
            "",
            "# --- AUDIT ---",
            f"audit_enabled = {sajt_data.get('audit_enabled', 'y')}",
            f"audit_threshold = {sajt_data.get('audit_threshold', 0.85)}",
            f"re_input_audit = {sajt_data.get('re_input_audit', 'y')}",
            f"max_audits = {sajt_data.get('max_audits', 10)}",
        ]
        
        SAJT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        SAJT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[CONFIG] Error writing sajt config: {e}")
        return False


def apply_external_config(config: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Apply config dict by writing to local config files.

    Args:
        config: Config dict with poit, segment, sajt keys

    Returns:
        (success, message)
    """
    results = []

    if write_poit_config(config):
        results.append("1_poit/config.txt")

    if write_segment_config(config):
        results.append("2_segment_info/config_simple.txt")

    if write_sajt_config(config):
        results.append("3_sajt/config_ny.txt")

    if len(results) == 3:
        return True, f"Updated: {', '.join(results)}"
    elif results:
        return True, f"Partially updated: {', '.join(results)}"
    else:
        return False, "No config files were updated"


def convert_value(val: str) -> Any:
    """Convert string value to appropriate type."""
    if val.lower() in ("y", "yes", "true", "on"):
        return "y"
    if val.lower() in ("n", "no", "false", "off"):
        return "n"
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val
