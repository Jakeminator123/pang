#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_external_config.py - Load configuration from external Dropbox file

This module allows the pipeline to use configuration values from an external
file (e.g., leads.enviroments.txt in Dropbox) instead of local config files.

Usage:
    Set in .env:
        EXTERNAL_VALUES=Y
        EXTERNAL_CONFIG_PATH=/path/to/Dropbox/leads.enviroments.txt
    
    Then in main.py:
        from utils.load_external_config import load_and_apply_external_config
        if load_and_apply_external_config():
            print("External config applied!")

The external config file should have the same format as the GUI exports:
    # =============================================================================
    # PANG KONFIGURATION
    # =============================================================================
    MAX_KUN_DAG = 150
    
    [PIPELINE]
    max_companies = 150
    
    [RESEARCH]
    enabled = y
    ...
"""

import configparser
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POIT_CONFIG = PROJECT_ROOT / "1_poit" / "config.txt"
SEGMENT_CONFIG = PROJECT_ROOT / "2_segment_info" / "config_simple.txt"
SAJT_CONFIG = PROJECT_ROOT / "3_sajt" / "config_ny.txt"
BACKUP_DIR = PROJECT_ROOT / ".cursor" / "config_backups"

DROPBOX_CANONICAL_FILENAME = "leads.enviroments.txt"

EXTERNAL_CONFIG_FILENAMES = (DROPBOX_CANONICAL_FILENAME,)

MAIL_TONE_KEYS = ("formality", "salesiness", "flattery", "length")

GUI_SETTINGS_PATHS = (
    PROJECT_ROOT / "gui" / "gui_settings.json",
    PROJECT_ROOT / "gui" / "mac" / "gui_settings.json",
)


def _empty_config() -> Dict[str, Any]:
    return {
        "poit": {},
        "segment": {
            "PIPELINE": {},
            "RESEARCH": {},
            "DOMAIN": {},
            "MAIL": {},
        },
        "mail_tone": {},
        "sajt": {},
    }


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_sources_from_dir(dir_path: Path) -> List[Path]:
    sources: List[Path] = []
    candidates = [dir_path, dir_path / "leads"]
    for base in candidates:
        if not base.exists():
            continue
        for filename in EXTERNAL_CONFIG_FILENAMES:
            candidate = base / filename
            if candidate.exists() and candidate.is_file():
                sources.append(candidate)
    return sources


def get_external_config_sources() -> List[Path]:
    sources: List[Path] = []
    gui_sources: List[Path] = []
    for settings_path in GUI_SETTINGS_PATHS:
        if not settings_path.exists():
            continue
        data = _load_json(settings_path)
        dropbox_path = data.get("dropbox_path") or data.get("dropbox_local_path")
        if not dropbox_path:
            continue
        gui_sources.extend(_collect_sources_from_dir(Path(dropbox_path)))

    if gui_sources:
        sources.extend(gui_sources)

    if not sources:
        path_str = os.getenv("EXTERNAL_CONFIG_PATH", "").strip()
        if path_str:
            path = Path(path_str)
            if path.exists():
                if path.is_file():
                    sources.append(path)
                    sources.extend(_collect_sources_from_dir(path.parent))
                elif path.is_dir():
                    sources.extend(_collect_sources_from_dir(path))

    unique: List[Path] = []
    seen = set()
    for src in sources:
        try:
            key = str(src.resolve())
        except OSError:
            key = str(src)
        if key in seen:
            continue
        seen.add(key)
        unique.append(src)
    return unique


def should_use_external_config() -> bool:
    """
    Check if external config should be used.
    
    Returns:
        True if EXTERNAL_VALUES=Y in environment
    """
    return os.getenv("EXTERNAL_VALUES", "N").upper() in ("Y", "YES", "TRUE", "1")


def get_external_config_path() -> Optional[Path]:
    """
    Get the path to external config file.
    
    Returns:
        Path to external config file, or None if not set/not found
    """
    sources = get_external_config_sources()
    return sources[0] if sources else None


def _apply_env_style_key(config: Dict[str, Any], key_upper: str, val: Any) -> bool:
    if key_upper.startswith("PIPELINE_"):
        config["segment"]["PIPELINE"][key_upper[len("PIPELINE_") :].lower()] = val
        return True
    if key_upper.startswith("RESEARCH_"):
        config["segment"]["RESEARCH"][key_upper[len("RESEARCH_") :].lower()] = val
        return True
    if key_upper.startswith("DOMAIN_"):
        config["segment"]["DOMAIN"][key_upper[len("DOMAIN_") :].lower()] = val
        return True
    if key_upper.startswith("MAIL_"):
        mail_key = key_upper[len("MAIL_") :].lower()
        if mail_key in MAIL_TONE_KEYS:
            config["mail_tone"][mail_key] = val
        else:
            config["segment"]["MAIL"][mail_key] = val
        return True
    if key_upper.startswith("SAJT_"):
        config["sajt"][key_upper[len("SAJT_") :].lower()] = val
        return True
    return False


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    base["poit"].update(override.get("poit", {}))
    base["mail_tone"].update(override.get("mail_tone", {}))
    base["sajt"].update(override.get("sajt", {}))
    if "email" in override:
        base["email"] = override["email"]

    segment_override = override.get("segment", {})
    for section in ("PIPELINE", "RESEARCH", "DOMAIN", "MAIL"):
        base["segment"][section].update(segment_override.get(section, {}))
    return base


def _read_poit_config() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if not POIT_CONFIG.exists():
        return data
    for line in POIT_CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = [part.strip() for part in line.split("=", 1)]
        if key.upper() == "MAX_KUN_DAG":
            if val.upper() == "ALL":
                data["MAX_KUN_DAG"] = 0
            else:
                try:
                    data["MAX_KUN_DAG"] = int(val)
                except ValueError:
                    data["MAX_KUN_DAG"] = val
    return data


def _read_segment_config() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "PIPELINE": {},
        "RESEARCH": {},
        "DOMAIN": {},
        "MAIL": {},
    }
    if not SEGMENT_CONFIG.exists():
        return data
    parser = configparser.ConfigParser()
    parser.read(SEGMENT_CONFIG, encoding="utf-8")
    for section in parser.sections():
        section_upper = section.upper()
        if section_upper not in data:
            data[section_upper] = {}
        for key, val in parser.items(section):
            data[section_upper][key] = convert_value(val)
    return data


def _read_sajt_config() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if not SAJT_CONFIG.exists():
        return data
    for line in SAJT_CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = [part.strip() for part in line.split("=", 1)]
        data[key.lower()] = convert_value(val)
    return data


def load_local_config() -> Dict[str, Any]:
    config = _empty_config()
    config["poit"].update(_read_poit_config())
    config["segment"].update(_read_segment_config())
    config["sajt"].update(_read_sajt_config())

    mail_section = config.get("segment", {}).get("MAIL", {})
    for key in MAIL_TONE_KEYS:
        if key in mail_section:
            config["mail_tone"][key] = mail_section[key]

    return config


def parse_external_config(config_path: Path) -> Dict[str, Any]:
    """
    Parse the external config file.
    
    The file format is:
        # Comments
        KEY = value
        
        [SECTION]
        key = value
    
    Args:
        config_path: Path to the external config file
        
    Returns:
        Dict with structure:
        {
            "poit": {"MAX_KUN_DAG": 150},
            "segment": {
                "PIPELINE": {"max_companies": 150, ...},
                "RESEARCH": {"enabled": "y", ...},
                "DOMAIN": {...},
                "MAIL": {...}
            },
            "mail_tone": {"formality": 4, ...},
            "sajt": {"evaluate": "y", ...}
        }
    """
    config = _empty_config()
    
    current_section: Optional[str] = None
    
    try:
        content = config_path.read_text(encoding="utf-8")
        
        for line in content.splitlines():
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                # Check for section hints in comments
                line_upper = line.upper()
                if "SKRAPNING" in line_upper or "1_POIT" in line_upper:
                    current_section = "poit"
                elif "SAJTER" in line_upper or "3_SAJT" in line_upper:
                    current_section = "sajt"
                elif "MAIL TON" in line_upper:
                    current_section = "mail_tone"
                continue
            
            # Section header
            if line.startswith("[") and line.endswith("]"):
                section_name = line[1:-1].upper()
                if section_name in ("PIPELINE", "RESEARCH", "DOMAIN", "MAIL"):
                    current_section = section_name
                else:
                    current_section = section_name.lower()
                continue
            
            # Key=value pair
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                
                # Remove inline comments
                if "#" in val:
                    val = val.split("#")[0].strip()
                
                # Convert value type
                val_converted = convert_value(val)
                
                # Place in correct location
                key_upper = key.upper()
                key_lower = key.lower()
                
                # Special handling for known keys
                if key_upper == "MAX_KUN_DAG":
                    config["poit"]["MAX_KUN_DAG"] = val_converted
                elif key_upper == "EMAIL":
                    config["email"] = val
                elif key_lower in MAIL_TONE_KEYS:
                    config["mail_tone"][key_lower] = val_converted
                elif _apply_env_style_key(config, key_upper, val_converted):
                    pass
                elif current_section == "poit":
                    config["poit"][key_upper] = val_converted
                elif current_section in ("PIPELINE", "RESEARCH", "DOMAIN", "MAIL"):
                    config["segment"][current_section][key_lower] = val_converted
                elif current_section == "sajt":
                    config["sajt"][key_lower] = val_converted
                elif current_section == "mail_tone":
                    config["mail_tone"][key_lower] = val_converted
                else:
                    # Try to auto-detect based on key name
                    if key_lower in ("evaluate", "threshold", "max_total_judgement_approvals",
                                     "max_sites", "re_input_website_link", "audit_enabled",
                                     "audit_threshold", "max_audits", "re_input_audit"):
                        config["sajt"][key_lower] = val_converted
                    elif key_lower in ("enabled", "model", "max_searches", "search_persons", "max_persons"):
                        config["segment"]["RESEARCH"][key_lower] = val_converted
                    elif key_lower in ("max_companies", "delete_csv", "source_dir"):
                        config["segment"]["PIPELINE"][key_lower] = val_converted
                    elif key_lower in ("timeout_seconds", "max_crawl", "parallel_checks"):
                        config["segment"]["DOMAIN"][key_lower] = val_converted
                    elif key_lower in ("min_confidence", "max_mails"):
                        config["segment"]["MAIL"][key_lower] = val_converted
    
    except Exception as e:
        print(f"[EXTERNAL CONFIG] Error parsing {config_path}: {e}")
    
    return config


def convert_value(val: str) -> Any:
    """Convert string value to appropriate type."""
    # Boolean
    if val.lower() in ("y", "yes", "true", "on"):
        return "y"
    if val.lower() in ("n", "no", "false", "off"):
        return "n"
    
    # Integer
    try:
        return int(val)
    except ValueError:
        pass
    
    # Float
    try:
        return float(val)
    except ValueError:
        pass
    
    return val


def backup_configs() -> Path:
    """
    Create backup of all config files before overwriting.
    
    Returns:
        Path to backup directory
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_subdir = BACKUP_DIR / f"external_override_{timestamp}"
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
            "# Config updated from external source",
            f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "#Använd MAX_KUN_DAG=ALL för obegränsat",
            f"MAX_KUN_DAG={'ALL' if max_kun == 0 else max_kun}"
        ]
        
        POIT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        POIT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[EXTERNAL CONFIG] Error writing poit config: {e}")
        return False


def write_segment_config(config: Dict[str, Any]) -> bool:
    """Write to 2_segment_info/config_simple.txt"""
    try:
        segment_data = config.get("segment", {})
        mail_tone = config.get("mail_tone", {})
        
        lines = [
            "# =============================================================================",
            "# SIMPLIFIED PIPELINE CONFIGURATION (with AI research)",
            "# =============================================================================",
            f"# Updated from external source: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# Run with: python ALLA.py",
            "",
        ]
        
        # PIPELINE section
        pipeline = segment_data.get("PIPELINE", {})
        lines.append("# Grundläggande pipeline-inställningar")
        lines.append("[PIPELINE]")
        lines.append(f"source_dir = {pipeline.get('source_dir', '1_poit/info_server')}")
        lines.append(f"max_companies = {pipeline.get('max_companies', 150)}")
        lines.append(f"delete_csv = {pipeline.get('delete_csv', 'y')}")
        lines.append("")
        
        # RESEARCH section
        research = segment_data.get("RESEARCH", {})
        lines.append("# AI-research inställningar")
        lines.append("[RESEARCH]")
        lines.append(f"enabled = {research.get('enabled', 'y')}")
        lines.append(f"model = {research.get('model', 'gpt-4o')}")
        lines.append(f"max_searches = {research.get('max_searches', 3)}")
        lines.append(f"search_persons = {research.get('search_persons', 'y')}")
        lines.append(f"max_persons = {research.get('max_persons', 2)}")
        lines.append("")
        
        # DOMAIN section
        domain = segment_data.get("DOMAIN", {})
        lines.append("# Domänverifiering")
        lines.append("[DOMAIN]")
        lines.append(f"timeout_seconds = {domain.get('timeout_seconds', 5)}")
        lines.append(f"max_crawl = {domain.get('max_crawl', 5)}")
        lines.append(f"parallel_checks = {domain.get('parallel_checks', 5)}")
        lines.append("")
        
        # MAIL section (includes tone settings)
        mail = segment_data.get("MAIL", {})
        lines.append("# Mail-generering och ton")
        lines.append("[MAIL]")
        lines.append(f"enabled = {mail.get('enabled', 'y')}")
        lines.append(f"model = {mail.get('model', 'gpt-4o')}")
        lines.append(f"min_confidence = {mail.get('min_confidence', 40)}")
        lines.append(f"max_mails = {mail.get('max_mails', 110)}")
        # Add tone settings to MAIL section
        lines.append(f"formality = {mail_tone.get('formality', 4)}")
        lines.append(f"salesiness = {mail_tone.get('salesiness', 3)}")
        lines.append(f"flattery = {mail_tone.get('flattery', 2)}")
        lines.append(f"length = {mail_tone.get('length', 5)}")
        lines.append("")
        
        SEGMENT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        SEGMENT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[EXTERNAL CONFIG] Error writing segment config: {e}")
        return False


def write_sajt_config(config: Dict[str, Any]) -> bool:
    """Write to 3_sajt/config_ny.txt"""
    try:
        sajt_data = config.get("sajt", {})
        
        lines = [
            "# =============================================================================",
            "# CONFIG FÖR 3_SAJT - Site Generation & Audit",
            "# =============================================================================",
            f"# Updated from external source: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# =============================================================================",
            "",
            "# --- EVALUATION (bedömning av företag) ---",
            f"evaluate = {sajt_data.get('evaluate', 'y')}",
            f"threshold = {sajt_data.get('threshold', 0.80)}",
            f"max_total_judgement_approvals = {sajt_data.get('max_total_judgement_approvals', 4)}",
            "",
            "# --- SITE GENERATION (preview-hemsidor) ---",
            f"re_input_website_link = {sajt_data.get('re_input_website_link', 'y')}",
            f"max_sites = {sajt_data.get('max_sites', 4)}",
            "",
            "# --- AUDIT (analys av befintlig hemsida) ---",
            f"audit_enabled = {sajt_data.get('audit_enabled', 'y')}",
            f"audit_threshold = {sajt_data.get('audit_threshold', 0.85)}",
            f"re_input_audit = {sajt_data.get('re_input_audit', 'y')}",
            f"max_audits = {sajt_data.get('max_audits', 10)}",
        ]
        
        SAJT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        SAJT_CONFIG.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[EXTERNAL CONFIG] Error writing sajt config: {e}")
        return False


def apply_external_config(config: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Apply external config by writing to local config files.
    
    Args:
        config: Parsed config dict from parse_external_config()
        
    Returns:
        (success: bool, message: str)
    """
    # Backup first
    try:
        backup_dir = backup_configs()
        print(f"[EXTERNAL CONFIG] Backup created: {backup_dir}")
    except Exception as e:
        return False, f"Backup failed: {e}"
    
    # Write each config file
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


def load_and_apply_external_config(sources: Optional[List[Path]] = None) -> bool:
    """
    Main entry point: Load external config and apply it.
    
    This function:
    1. Checks if EXTERNAL_VALUES=Y
    2. Gets the external config path
    3. Parses the external config file
    4. Backs up local configs
    5. Writes external values to local config files
    
    Returns:
        True if external config was successfully applied, False otherwise
    """
    # Check if external config is enabled
    if not should_use_external_config():
        return False
    
    # Get paths to external config(s)
    sources = sources if sources is not None else get_external_config_sources()
    if not sources:
        print("[EXTERNAL CONFIG] EXTERNAL_CONFIG_PATH not set or file not found")
        return False

    try:
        sources = sorted(
            sources,
            key=lambda p: (p.stat().st_mtime, str(p).lower()),
        )
    except OSError:
        pass

    print("[EXTERNAL CONFIG] Loading from:")
    for src in sources:
        print(f"  - {src}")

    config = load_local_config()
    for source in sources:
        parsed = parse_external_config(source)
        _merge_config(config, parsed)
    
    # Check if we got any data
    has_data = (
        config.get("poit")
        or any(config.get("segment", {}).values())
        or config.get("sajt")
        or config.get("mail_tone")
    )
    
    if not has_data:
        print("[EXTERNAL CONFIG] No configuration data found in file")
        return False
    
    # Apply config
    success, message = apply_external_config(config)
    print(f"[EXTERNAL CONFIG] {message}")
    
    return success


def get_config_summary(config: Dict[str, Any]) -> str:
    """Get a human-readable summary of the config."""
    lines = []
    
    if config.get("poit"):
        lines.append(f"  POIT: MAX_KUN_DAG={config['poit'].get('MAX_KUN_DAG', '?')}")
    
    segment = config.get("segment", {})
    if segment.get("PIPELINE"):
        lines.append(f"  PIPELINE: max_companies={segment['PIPELINE'].get('max_companies', '?')}")
    if segment.get("RESEARCH"):
        lines.append(f"  RESEARCH: enabled={segment['RESEARCH'].get('enabled', '?')}")
    if segment.get("MAIL"):
        lines.append(f"  MAIL: enabled={segment['MAIL'].get('enabled', '?')}")
    
    if config.get("sajt"):
        lines.append(f"  SAJT: evaluate={config['sajt'].get('evaluate', '?')}, max_sites={config['sajt'].get('max_sites', '?')}")
    
    return "\n".join(lines) if lines else "  (empty)"


# For testing
if __name__ == "__main__":
    print("Testing external config loader...")
    print(f"EXTERNAL_VALUES: {os.getenv('EXTERNAL_VALUES', 'not set')}")
    print(f"EXTERNAL_CONFIG_PATH: {os.getenv('EXTERNAL_CONFIG_PATH', 'not set')}")
    print()
    
    if should_use_external_config():
        config_path = get_external_config_path()
        if config_path:
            print(f"Loading from: {config_path}")
            config = parse_external_config(config_path)
            print("\nParsed config:")
            print(get_config_summary(config))
            
            print("\nApplying config...")
            success = load_and_apply_external_config()
            print(f"Result: {'Success' if success else 'Failed'}")
        else:
            print("External config path not found")
    else:
        print("External config not enabled (EXTERNAL_VALUES != Y)")
