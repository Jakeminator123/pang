#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PANG Konfigurationshanterare
============================
Ett modernt GUI för att hantera alla inställningar på ett ställe.

Fungerar på: Windows, macOS, Linux

Kör: python config_gui.py
"""

import configparser
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any, Dict, List, Optional, Tuple

def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or bool(
        os.environ.get("VIRTUAL_ENV")
    )


def _ensure_user_site_on_path() -> None:
    try:
        import site

        if site.ENABLE_USER_SITE and site.USER_SITE and site.USER_SITE not in sys.path:
            sys.path.append(site.USER_SITE)
    except Exception:
        pass


def _ensure_pip() -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        try:
            import ensurepip

            ensurepip.bootstrap()
            return True
        except Exception:
            return False


def install_package(package_name: str, import_name: Optional[str] = None) -> bool:
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        pass

    print(f"📦 Installerar {package_name}...")
    if not _ensure_pip():
        print("⚠️ Kunde inte starta pip. Installera pip och försök igen.")
        return False

    install_cmds = []
    if not _in_venv():
        install_cmds.append(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--disable-pip-version-check",
                "--quiet",
                package_name,
            ]
        )
    install_cmds.append(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            package_name,
        ]
    )

    last_error: Optional[Exception] = None
    for cmd in install_cmds:
        try:
            subprocess.check_call(cmd)
            _ensure_user_site_on_path()
            __import__(import_name)
            print(f"   ✅ {package_name} installerat")
            return True
        except Exception as exc:
            last_error = exc

    print(f"   ⚠️ Kunde inte installera {package_name}: {last_error}")
    return False


_ensure_user_site_on_path()
try:
    import customtkinter as ctk
except ImportError:
    if install_package("customtkinter"):
        import customtkinter as ctk
    else:
        print("❌ customtkinter saknas och kunde inte installeras automatiskt.")
        raise SystemExit(1)

# =============================================================================
# SÖKVÄGAR (plattformsoberoende)
# =============================================================================

# GUI ligger i gui/ mappen, projektroten är en nivå upp
GUI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GUI_DIR.parent

POIT_CONFIG = PROJECT_ROOT / "1_poit" / "config.txt"
SEGMENT_CONFIG = PROJECT_ROOT / "2_segment_info" / "config_simple.txt"
SAJT_CONFIG = PROJECT_ROOT / "3_sajt" / "config_ny.txt"
ENV_FILE = PROJECT_ROOT / ".env"
BACKUP_DIR = PROJECT_ROOT / ".cursor" / "config_backups"
DEFAULT_CONFIG = GUI_DIR / "default_config.json"  # Standardvärden för fabriksåterställning
GUI_SETTINGS = GUI_DIR / "gui_settings.json"  # GUI-specifika inställningar

# Plattformsdetektering
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def _escape_osascript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def launch_pipeline(cmd_suffix: str) -> None:
    python_exe = sys.executable

    if IS_WINDOWS:
        command = (
            'title PANG Pipeline & '
            'chcp 65001 >nul & '
            f'cd /d "{PROJECT_ROOT}" & '
            'set PYTHONIOENCODING=utf-8 & '
            f'"{python_exe}" main.py{cmd_suffix}'
        )
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["cmd.exe", "/k", command], creationflags=creationflags)
        return

    if IS_MAC:
        script = (
            f'cd "{PROJECT_ROOT}" && '
            "export PYTHONIOENCODING=utf-8 && "
            f'"{python_exe}" main.py{cmd_suffix}'
        )
        osa = f'tell application "Terminal" to do script "{_escape_osascript(script)}"'
        subprocess.Popen(["osascript", "-e", osa])
        return

    script = (
        f'cd "{PROJECT_ROOT}" && '
        "export PYTHONIOENCODING=utf-8 && "
        f'"{python_exe}" main.py{cmd_suffix}; exec bash'
    )
    subprocess.Popen(["x-terminal-emulator", "-e", script])
# =============================================================================
# TEMA OCH FÄRGER - Förbättrat professionellt färgschema
# =============================================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Professionellt, harmoniskt färgschema inspirerat av moderna design-system
COLORS = {
    # Bakgrunder - mjuka, djupa toner
    "bg_dark": "#0a0e1a",           # Mycket mörk bakgrund
    "bg_main": "#0f1419",           # Huvudbakgrund
    "bg_card": "#1a1f2e",          # Kort-bakgrund med subtil blåton
    "bg_card_hover": "#1f2535",    # Hover-state för kort
    "bg_input": "#252b3a",          # Input-fält
    "bg_input_focus": "#2d3445",    # Focus-state för inputs
    "bg_elevated": "#1e2432",       # Upphöjda element
    
    # Borders - subtila, mjuka linjer
    "border": "#2a3142",            # Standard border
    "border_light": "#1e2535",      # Ljusare border
    "border_focus": "#4a5568",      # Focus border
    
    # Accent-färger - professionella, harmoniska
    "accent": "#3b82f6",            # Modern blå (primary action)
    "accent_hover": "#2563eb",      # Mörkare blå vid hover
    "accent_light": "#60a5fa",      # Ljusare blå för highlights
    "accent_gradient_start": "#3b82f6",  # Gradient start
    "accent_gradient_end": "#2563eb",   # Gradient end
    
    # Sekundära färger
    "secondary": "#8b5cf6",         # Lila/purple för sekundära actions
    "secondary_hover": "#7c3aed",
    "success": "#10b981",           # Grön för success
    "success_hover": "#059669",
    "warning": "#f59e0b",           # Orange för varningar
    "warning_hover": "#d97706",
    "error": "#ef4444",             # Röd för fel
    "error_hover": "#dc2626",
    
    # Text - tydlig hierarki
    "text": "#e2e8f0",              # Standard text (ljusare)
    "text_dim": "#94a3b8",          # Dimmer text
    "text_bright": "#f1f5f9",       # Ljusaste text
    "text_muted": "#64748b",        # Muted text
    
    # Special
    "highlight": "#f97316",         # Orange highlight
    "highlight_hover": "#ea580c",
}

# Typografi - initieras först efter att root-fönstret skapats.
# (CTkFont kräver att en Tk-root redan finns, annars får man: "Too early to use font")
FONTS: Dict[str, Any] = {}

# Spacing - konsistent spacing-system
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

# =============================================================================
# INSTÄLLNINGSDEFINITIONER MED BESKRIVNINGAR
# =============================================================================

# Varje inställning har: (default_värde, typ, beskrivning, tooltip)
SETTINGS_DEFINITIONS = {
    # ===== SKRAPNING (1_poit) =====
    "scraping": {
        "_title": "🔍 Skrapning",
        "_description": "Styr hur data hämtas från Bolagsverket",
        "_icon": "🔍",
        
        "MAX_KUN_DAG": {
            "default": 150,
            "type": "number",
            "label": "Max kungörelser per dag",
            "description": "Hur många företag som ska skrapas från Bolagsverket per körning.",
            "tooltip": "Sätt till 0 för obegränsat. Rekommenderat: 50-200 för testning, 500+ för produktion.",
            "min": 0,
            "max": 9999,
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== PIPELINE (2_segment_info) =====
    "pipeline": {
        "_title": "⚡ Pipeline",
        "_description": "Grundläggande inställningar för databearbetning",
        "_icon": "⚡",
        
        "max_companies": {
            "default": 150,
            "type": "number",
            "label": "Max företag att bearbeta",
            "description": "Begränsar hur många företag som går igenom AI-analysen.",
            "tooltip": "Påverkar kostnad och tid. Börja med lågt värde (10-20) för testning.",
            "min": 0,
            "max": 9999,
            "used_in_code": True,
            "advanced": False,
        },
        "delete_csv": {
            "default": True,
            "type": "switch",
            "label": "Radera CSV efter konvertering",
            "description": "Ta bort CSV-filer efter de konverterats till Excel.",
            "tooltip": "Sparar diskutrymme. CSV behålls i Excel-formatet.",
            "used_in_code": True,
            "advanced": False,
        },
        "source_dir": {
            "default": "1_poit/info_server",
            "type": "entry",
            "label": "Källmapp för rådata",
            "description": "Varifrån datum-mappar kopieras innan bearbetning.",
            "tooltip": "Teknisk inställning. Ändra endast om du vet vad du gör.",
            "used_in_code": True,
            "advanced": True,
        },
    },
    
    # ===== AI-RESEARCH (2_segment_info) =====
    "research": {
        "_title": "🤖 AI-Research",
        "_description": "Inställningar för AI-driven företagsundersökning",
        "_icon": "🤖",
        
        "enabled": {
            "default": True,
            "type": "switch",
            "label": "Aktivera AI-research",
            "description": "Använd OpenAI för att söka information om företag online.",
            "tooltip": "Kostar pengar per sökning. Ger bättre domänmatchning och kontaktinfo.",
            "used_in_code": True,
            "advanced": False,
        },
        "model": {
            "default": "gpt-4o",
            "type": "dropdown",
            "label": "AI-modell",
            "description": "Vilken OpenAI-modell som används för research.",
            "tooltip": "gpt-4o = bäst kvalitet, gpt-4o-mini = billigare men sämre.",
            "options": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "used_in_code": True,
            "advanced": False,
        },
        "max_searches": {
            "default": 3,
            "type": "number",
            "label": "Sökningar per företag",
            "description": "Antal webbsökningar som görs för varje företag.",
            "tooltip": "Fler sökningar = bättre data men högre kostnad. 3-5 rekommenderas.",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
        "search_persons": {
            "default": True,
            "type": "switch",
            "label": "Sök efter personer",
            "description": "Sök efter kontaktuppgifter för styrelsemedlemmar.",
            "tooltip": "Hjälper hitta direkta e-postadresser istället för info@.",
            "used_in_code": True,
            "advanced": False,
        },
        "max_persons": {
            "default": 2,
            "type": "number",
            "label": "Max personer att söka",
            "description": "Hur många styrelsemedlemmar som undersöks.",
            "tooltip": "Fler personer = mer data men högre kostnad.",
            "min": 0,
            "max": 5,
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== DOMÄNVERIFIERING =====
    "domain": {
        "_title": "🌍 Domänverifiering",
        "_description": "Hur företagshemsidor hittas och verifieras",
        "_icon": "🌍",
        
        "timeout_seconds": {
            "default": 5,
            "type": "number",
            "label": "HTTP-timeout (sekunder)",
            "description": "Max väntetid när en domän kontrolleras.",
            "tooltip": "Längre timeout = fångar långsamma sidor men tar mer tid.",
            "min": 2,
            "max": 30,
            "used_in_code": False,  # Definierad men inte använd i 2_research.py ännu
            "advanced": True,
        },
        "max_crawl": {
            "default": 5,
            "type": "number",
            "label": "Max domäner att verifiera",
            "description": "Antal domänkandidater som testas per företag.",
            "tooltip": "Fler = bättre chans att hitta rätt domän men tar längre tid.",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
        "parallel_checks": {
            "default": 5,
            "type": "number",
            "label": "Parallella domänkontroller",
            "description": "Antal domäner som kontrolleras samtidigt (påverkar hastighet).",
            "tooltip": "Högre = snabbare men mer belastning. Inte implementerat ännu.",
            "min": 1,
            "max": 10,
            "used_in_code": False,
            "advanced": True,
        },
    },
    
    # ===== MAIL-GENERERING =====
    "mail": {
        "_title": "✉️ Mail-generering",
        "_description": "Inställningar för automatisk e-postgenerering",
        "_icon": "✉️",
        
        "enabled": {
            "default": True,
            "type": "switch",
            "label": "Aktivera mail-generering",
            "description": "Skapa personliga säljmail automatiskt.",
            "tooltip": "Använder OpenAI för att skriva mail baserat på företagsdata.",
            "used_in_code": True,
            "advanced": False,
        },
        "model": {
            "default": "gpt-4o",
            "type": "dropdown",
            "label": "AI-modell för mail",
            "description": "Vilken modell som skriver mailen.",
            "tooltip": "gpt-4o skriver bättre mail men kostar mer.",
            "options": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "used_in_code": True,
            "advanced": False,
        },
        "min_confidence": {
            "default": 40,
            "type": "slider",
            "label": "Min domän-confidence (%)",
            "description": "Lägsta säkerhet på domänmatchning för att generera mail.",
            "tooltip": "Högre = färre mail men säkrare att de når rätt. 40% är bra start.",
            "min": 0,
            "max": 100,
            "used_in_code": True,
            "advanced": False,
        },
        "max_mails": {
            "default": 110,
            "type": "number",
            "label": "Max mail att generera",
            "description": "Begränsar antal mail per körning.",
            "tooltip": "Sätt till 0 för obegränsat. Påverkar kostnad.",
            "min": 0,
            "max": 9999,
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== MAIL TON & STIL =====
    "mail_tone": {
        "_title": "🎨 Mail: Ton & Stil",
        "_description": "Justera hur mailen låter - från casual till formellt",
        "_icon": "🎨",
        
        "formality": {
            "default": 4,
            "type": "slider",
            "label": "Formalitet",
            "description": "1 = Avslappnat/kompis • 10 = Formellt/affärsmässigt",
            "tooltip": "Lågt = 'Tjena!', Högt = 'Med vänlig hälsning'. 4-5 passar de flesta.",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
        "salesiness": {
            "default": 3,
            "type": "slider",
            "label": "Säljighet",
            "description": "1 = Bara information • 10 = Aggressiv försäljning",
            "tooltip": "Lågt = neutral info, Högt = 'KÖP NU!'. Rekommenderat: 2-4.",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
        "flattery": {
            "default": 2,
            "type": "slider",
            "label": "Smicker",
            "description": "1 = Rakt på sak • 10 = 'Ni är fantastiska!'",
            "tooltip": "Lågt = ärligt, Högt = inställsamt. Svenska gillar lågt (1-3).",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
        "length": {
            "default": 5,
            "type": "slider",
            "label": "Längd",
            "description": "1 = Ultra-kort (~80 ord) • 10 = Längre (~200 ord)",
            "tooltip": "Kortare mail läses oftare. 4-6 är sweet spot.",
            "min": 1,
            "max": 10,
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== SITE GENERATION (3_sajt) =====
    "evaluation": {
        "_title": "📋 Utvärdering",
        "_description": "Vilka företag som ska få demo-hemsida",
        "_icon": "📋",
        
        "evaluate": {
            "default": True,
            "type": "switch",
            "label": "Aktivera utvärdering",
            "description": "Filtrera företag innan sajt-generering.",
            "tooltip": "Om av: alla företag kan få sajt. Om på: AI bedömer vilka som är värda.",
            "used_in_code": True,
            "advanced": False,
        },
        "threshold": {
            "default": 0.80,
            "type": "decimal",
            "label": "Min confidence för sajt",
            "description": "Lägsta AI-säkerhet för att generera demo-sajt.",
            "tooltip": "0.80 = 80% säkerhet. Högre = färre men bättre matchade sajter.",
            "min": 0.0,
            "max": 1.0,
            "step": 0.05,
            "used_in_code": True,
            "advanced": False,
        },
        "max_total_judgement_approvals": {
            "default": 4,
            "type": "number",
            "label": "Max godkända företag",
            "description": "Begränsar hur många företag som kan godkännas.",
            "tooltip": "0 = obegränsat. Styr kostnad för v0.dev API.",
            "min": 0,
            "max": 100,
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== DEMO-SAJTER =====
    "sites": {
        "_title": "🏗️ Demo-sajter",
        "_description": "Automatisk hemsidegenerering via v0.dev",
        "_icon": "🏗️",
        
        "max_sites": {
            "default": 4,
            "type": "number",
            "label": "Max sajter per körning",
            "description": "Hur många demo-hemsidor som genereras.",
            "tooltip": "v0.dev kostar per sajt. Börja med 2-5 för testning.",
            "min": 0,
            "max": 50,
            "used_in_code": True,
            "advanced": False,
        },
        "re_input_website_link": {
            "default": True,
            "type": "switch",
            "label": "Lägg till sajt-länk i mail",
            "description": "Infoga preview-URL i genererade mail automatiskt.",
            "tooltip": "Gör mailet mer personligt med 'Vi har redan byggt en demo åt er'.",
            "used_in_code": True,
            "advanced": False,
        },
    },
    
    # ===== AUDIT =====
    "audit": {
        "_title": "🔬 Webbplats-audit",
        "_description": "Analysera företagens befintliga hemsidor",
        "_icon": "🔬",
        
        "audit_enabled": {
            "default": True,
            "type": "switch",
            "label": "Aktivera audit",
            "description": "Kör automatisk analys av företagens hemsidor.",
            "tooltip": "Skapar PDF-rapport med förbättringsförslag.",
            "used_in_code": True,
            "advanced": False,
        },
        "audit_threshold": {
            "default": 0.85,
            "type": "decimal",
            "label": "Min domän-confidence för audit",
            "description": "Endast audit företag där vi är säkra på domänen.",
            "tooltip": "0.85 = 85%. Högre = säkrare att vi analyserar rätt sajt.",
            "min": 0.0,
            "max": 1.0,
            "step": 0.05,
            "used_in_code": True,
            "advanced": False,
        },
        "max_audits": {
            "default": 10,
            "type": "number",
            "label": "Max audits per körning",
            "description": "Begränsar antal webbplats-analyser.",
            "tooltip": "Varje audit tar tid. 10-20 är rimligt.",
            "min": 0,
            "max": 100,
            "used_in_code": True,
            "advanced": False,
        },
        "re_input_audit": {
            "default": True,
            "type": "switch",
            "label": "Lägg till audit-länk i mail",
            "description": "Infoga länk till audit-rapporten i mailet.",
            "tooltip": "Visar att vi redan analyserat deras sajt.",
            "used_in_code": True,
            "advanced": False,
        },
    },
}


# =============================================================================
# CONFIG LOADERS
# =============================================================================


def load_poit_config() -> Dict[str, Any]:
    """Ladda 1_poit/config.txt"""
    config = {"MAX_KUN_DAG": 150}
    if POIT_CONFIG.exists():
        for line in POIT_CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if val.upper() == "ALL":
                    config[key] = 0
                else:
                    try:
                        config[key] = int(val)
                    except ValueError:
                        config[key] = val
    return config


def load_segment_config() -> Dict[str, Any]:
    """Ladda 2_segment_info/config_simple.txt som INI"""
    config = {}
    
    if SEGMENT_CONFIG.exists():
        parser = configparser.ConfigParser()
        parser.read(SEGMENT_CONFIG, encoding="utf-8")
        for section in parser.sections():
            section_upper = section.upper()
            config[section_upper] = {}
            for key, val in parser.items(section):
                try:
                    config[section_upper][key] = int(val)
                except ValueError:
                    try:
                        config[section_upper][key] = float(val)
                    except ValueError:
                        config[section_upper][key] = val
    return config


def load_sajt_config() -> Dict[str, Any]:
    """Ladda 3_sajt/config_ny.txt"""
    config = {}
    
    if SAJT_CONFIG.exists():
        for line in SAJT_CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                try:
                    config[key] = int(val)
                except ValueError:
                    try:
                        config[key] = float(val)
                    except ValueError:
                        config[key] = val
    return config


def load_gui_settings() -> Dict[str, str]:
    """Ladda GUI-specifika inställningar (email, dashboard etc.)"""
    defaults = {
        "email": "jakob.olof.eberg@gmail.com",
        "dashboard_url": os.environ.get("DASHBOARD_URL", "https://jocke.onrender.com/").rstrip("/"),
        "jocke_api": os.environ.get("JOCKE_API", "12345"),
    }
    
    if GUI_SETTINGS.exists():
        try:
            with open(GUI_SETTINGS, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for key in defaults:
                    if key in saved:
                        defaults[key] = saved[key]
        except Exception:
            pass

    return defaults


def save_gui_settings(settings: Dict[str, str]):
    """Spara GUI-specifika inställningar"""
    try:
        with open(GUI_SETTINGS, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Kunde inte spara GUI-inställningar: {e}")




# =============================================================================
# DEFAULT CONFIG (fabriksåterställning)
# =============================================================================


def load_default_config() -> Dict[str, Any]:
    """
    Läs standardvärden från default_config.json.
    
    Returns:
        Dict med standardvärden för alla config-filer
    """
    if not DEFAULT_CONFIG.exists():
        raise FileNotFoundError(f"Standardkonfiguration saknas: {DEFAULT_CONFIG}")
    
    with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def restore_to_defaults() -> Tuple[bool, str]:
    """
    Återställ alla config-filer till standardvärden.
    
    Returns:
        (success: bool, message: str)
    """
    try:
        # Läs standardvärden
        defaults = load_default_config()
        
        # Spara POIT config
        poit_defaults = defaults.get("poit", {})
        max_kun = poit_defaults.get("MAX_KUN_DAG", 150)
        save_poit_config(max_kun)
        
        # Spara Segment config
        segment_defaults = defaults.get("segment", {})
        save_segment_config(segment_defaults)
        
        # Spara Sajt config
        sajt_defaults = defaults.get("sajt", {})
        save_sajt_config(sajt_defaults)
        
        return True, "Alla inställningar återställda till standardvärden!"
        
    except FileNotFoundError as e:
        return False, f"Standardkonfiguration saknas: {e}"
    except Exception as e:
        return False, f"Fel vid återställning: {e}"


# =============================================================================
# CONFIG SAVERS
# =============================================================================


def backup_configs():
    """Skapa backup av alla config-filer"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for config_file in [POIT_CONFIG, SEGMENT_CONFIG, SAJT_CONFIG]:
        if config_file.exists():
            backup_name = f"{config_file.stem}_{timestamp}{config_file.suffix}"
            backup_path = BACKUP_DIR / backup_name
            backup_path.write_text(config_file.read_text(encoding="utf-8"), encoding="utf-8")
    
    return BACKUP_DIR / f"backup_{timestamp}"


def save_poit_config(max_kun_dag: int):
    """Spara 1_poit/config.txt"""
    lines = [
        "#Använd MAX_KUN_DAG=ALL för obegränsat",
        f"MAX_KUN_DAG={'ALL' if max_kun_dag == 0 else max_kun_dag}"
    ]
    POIT_CONFIG.write_text("\n".join(lines), encoding="utf-8")


def save_segment_config(config: Dict[str, Any]):
    """Spara 2_segment_info/config_simple.txt"""
    lines = [
        "# Run with: python ALLA.py",
        "",
    ]
    
    section_comments = {
        "PIPELINE": "# --- PIPELINE ---",
        "RESEARCH": "# --- AI-RESEARCH ---",
        "DOMAIN": "# --- DOMÄNVERIFIERING ---",
        "MAIL": "# --- MAIL ---",
    }
    
    for section, values in config.items():
        if section.startswith("_"):
            continue
        lines.append(section_comments.get(section, f"# --- {section} ---"))
        lines.append(f"[{section}]")
        for key, val in values.items():
            lines.append(f"{key} = {val}")
        lines.append("")
    
    SEGMENT_CONFIG.write_text("\n".join(lines), encoding="utf-8")


def save_sajt_config(config: Dict[str, Any]):
    """Spara 3_sajt/config_ny.txt"""
    lines = [
        "",
        "# --- EVALUATION ---",
    ]
    
    eval_keys = ["evaluate", "threshold", "max_total_judgement_approvals"]
    site_keys = ["re_input_website_link", "max_sites"]
    audit_keys = ["audit_enabled", "audit_threshold", "re_input_audit", "max_audits"]
    
    for key in eval_keys:
        if key in config:
            lines.append(f"{key} = {config[key]}")
    
    lines.append("")
    lines.append("# --- SITE GENERATION ---")
    for key in site_keys:
        if key in config:
            lines.append(f"{key} = {config[key]}")
    
    lines.append("")
    lines.append("# --- AUDIT ---")
    for key in audit_keys:
        if key in config:
            lines.append(f"{key} = {config[key]}")
    
    SAJT_CONFIG.write_text("\n".join(lines), encoding="utf-8")


def find_dropbox_folder() -> Optional[Path]:
    """Hitta Dropbox-mapp (plattformsoberoende)."""
    # Vanliga platser för Dropbox
    dropbox_paths = [
        Path.home() / "Dropbox",
        Path.home() / "Library" / "CloudStorage" / "Dropbox",  # macOS
    ]
    
    # Windows-specifika platser
    if IS_WINDOWS:
        username = os.getenv("USERNAME", "User")
        dropbox_paths.extend([
            Path(f"C:/Users/{username}/Dropbox"),
            Path("D:/Dropbox"),
            Path("E:/Dropbox"),
        ])
    
    # macOS-specifika platser
    if IS_MAC:
        dropbox_paths.extend([
            Path.home() / "Dropbox (Personal)",
            Path.home() / "Dropbox (Team)",
        ])
    
    for path in dropbox_paths:
        if path.exists() and path.is_dir():
            return path
    
    return None




# =============================================================================
# GUI KOMPONENTER
# =============================================================================


class Tooltip:
    """Förbättrad tooltip med snygg design"""
    
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
    
    def show(self, event=None):
        if self.tooltip_window:
            return
        
        x, y, _, _ = self.widget.bbox("insert") if hasattr(self.widget, 'bbox') else (0, 0, 0, 0)
        x += self.widget.winfo_rootx() + 30
        y += self.widget.winfo_rooty() + 20
        
        self.tooltip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        # CTkToplevel tillåter inte fg_color="transparent" (kastar ValueError).
        # Vi använder istället vanlig bakgrund och låter vår tooltip-frame stå för designen.
        # (Funkar på Windows/macOS/Linux)
        try:
            tw.configure(fg_color=COLORS["bg_main"])
        except Exception:
            pass
        
        # Tooltip frame med shadow-effekt
        frame = ctk.CTkFrame(tw, corner_radius=10, fg_color=COLORS["bg_elevated"],
                             border_width=1, border_color=COLORS["border_focus"])
        frame.pack()
        
        # Header med ikon
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 5))
        
        icon_label = ctk.CTkLabel(header, text="💡", font=ctk.CTkFont(size=14))
        icon_label.pack(side="left", padx=(0, 6))
        
        title = ctk.CTkLabel(header, text="Tips", font=FONTS["label"],
                             text_color=COLORS["accent_light"])
        title.pack(side="left")
        
        # Separator
        sep = ctk.CTkFrame(frame, height=1, fg_color=COLORS["border"])
        sep.pack(fill="x", padx=12, pady=4)
        
        # Text
        label = ctk.CTkLabel(frame, text=self.text, wraplength=320,
                              font=FONTS["body_small"],
                              text_color=COLORS["text"],
                              justify="left")
        label.pack(padx=12, pady=(0, 12))
    
    def hide(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class SettingRow(ctk.CTkFrame):
    """Förbättrad inställningsrad med professionell design"""
    
    def __init__(self, parent, key: str, definition: Dict[str, Any], current_value: Any = None):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        
        self.key = key
        self.definition = definition
        self.setting_type = definition.get("type", "entry")
        
        # Använd current_value om den finns, annars default
        value = current_value if current_value is not None else definition.get("default")
        
        # Container för hela raden med padding
        row_container = ctk.CTkFrame(self, fg_color="transparent")
        row_container.pack(fill="x", padx=0, pady=SPACING["sm"])
        
        # Vänster: Label och beskrivning
        left_frame = ctk.CTkFrame(row_container, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xl"]))
        
        # Label med info-ikon
        label_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        label_frame.pack(anchor="w", pady=(0, SPACING["xs"]))
        
        label = ctk.CTkLabel(label_frame, text=definition.get("label", key),
                              font=FONTS["label"],
                              text_color=COLORS["text_bright"])
        label.pack(side="left")
        
        # Badge för "Används i kod" status
        used_in_code = definition.get("used_in_code", True)  # Default True om inte specificerat
        if not used_in_code:
            badge = ctk.CTkLabel(label_frame, text="⚠ Ej aktiv", 
                                 font=FONTS["caption"],
                                 text_color=COLORS["warning"],
                                 fg_color=COLORS["bg_elevated"],
                                 corner_radius=4,
                                 padx=6, pady=2)
            badge.pack(side="left", padx=(SPACING["sm"], 0))
        else:
            badge = ctk.CTkLabel(label_frame, text="✓ Aktiv", 
                                 font=FONTS["caption"],
                                 text_color=COLORS["success"],
                                 fg_color=COLORS["bg_elevated"],
                                 corner_radius=4,
                                 padx=6, pady=2)
            badge.pack(side="left", padx=(SPACING["sm"], 0))
        
        # Info-knapp med tooltip - mer subtil design
        if definition.get("tooltip"):
            info_btn = ctk.CTkLabel(label_frame, text="ⓘ", 
                                     font=ctk.CTkFont(size=13, weight="normal"),
                                     text_color=COLORS["accent_light"],
                                     cursor="hand2")
            info_btn.pack(side="left", padx=(SPACING["sm"], 0))
            Tooltip(info_btn, definition["tooltip"])
        
        # Beskrivning med bättre spacing
        if definition.get("description"):
            desc = ctk.CTkLabel(left_frame, text=definition["description"],
                                 font=FONTS["body_small"],
                                 text_color=COLORS["text_dim"],
                                 wraplength=450, anchor="w", justify="left")
            desc.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Höger: Input med bättre styling
        right_frame = ctk.CTkFrame(row_container, fg_color="transparent")
        right_frame.pack(side="right")
        
        self.var = None
        self.input = None
        
        if self.setting_type == "number":
            self.var = ctk.StringVar(value=str(int(value) if value else 0))
            self.input = ctk.CTkEntry(right_frame, textvariable=self.var, width=110, height=36,
                                       fg_color=COLORS["bg_input"],
                                       border_color=COLORS["border"],
                                       border_width=1,
                                       corner_radius=8,
                                       font=FONTS["body"],
                                       text_color=COLORS["text_bright"])
            self.input.pack()
        
        elif self.setting_type == "decimal":
            self.var = ctk.StringVar(value=str(float(value) if value else 0.0))
            self.input = ctk.CTkEntry(right_frame, textvariable=self.var, width=110, height=36,
                                       fg_color=COLORS["bg_input"],
                                       border_color=COLORS["border"],
                                       border_width=1,
                                       corner_radius=8,
                                       font=FONTS["body"],
                                       text_color=COLORS["text_bright"])
            self.input.pack()
        
        elif self.setting_type == "slider":
            min_val = definition.get("min", 0)
            max_val = definition.get("max", 100)
            
            slider_container = ctk.CTkFrame(right_frame, fg_color="transparent")
            slider_container.pack()
            
            self.var = ctk.IntVar(value=int(value) if value else min_val)
            
            # Value display med snygg design
            value_frame = ctk.CTkFrame(slider_container, fg_color=COLORS["bg_elevated"],
                                       corner_radius=8, width=50, height=36)
            value_frame.pack(side="right", padx=(SPACING["md"], 0))
            value_frame.pack_propagate(False)
            
            self.value_label = ctk.CTkLabel(value_frame, textvariable=self.var,
                                             font=FONTS["label"],
                                             text_color=COLORS["accent"])
            self.value_label.pack(expand=True)
            
            # Slider med förbättrad design
            self.input = ctk.CTkSlider(slider_container, from_=min_val, to=max_val,
                                        number_of_steps=max_val - min_val,
                                        variable=self.var, width=180, height=20,
                                        button_color=COLORS["accent"],
                                        button_hover_color=COLORS["accent_hover"],
                                        progress_color=COLORS["accent_light"],
                                        fg_color=COLORS["bg_input"])
            self.input.pack(side="right")
        
        elif self.setting_type == "switch":
            is_on = str(value).lower() in ("y", "yes", "true", "1", "on")
            self.var = ctk.BooleanVar(value=is_on)
            self.input = ctk.CTkSwitch(right_frame, text="", variable=self.var,
                                        onvalue=True, offvalue=False,
                                        width=50, height=28,
                                        button_color=COLORS["accent"],
                                        button_hover_color=COLORS["accent_hover"],
                                        progress_color=COLORS["accent_light"],
                                        fg_color=COLORS["bg_input"],
                                        border_color=COLORS["border"],
                                        border_width=1)
            self.input.pack()
        
        elif self.setting_type == "dropdown":
            options = definition.get("options", [])
            self.var = ctk.StringVar(value=str(value) if value else (options[0] if options else ""))
            self.input = ctk.CTkOptionMenu(right_frame, variable=self.var,
                                            values=options, width=160, height=36,
                                            fg_color=COLORS["bg_input"],
                                            button_color=COLORS["accent"],
                                            button_hover_color=COLORS["accent_hover"],
                                            corner_radius=8,
                                            font=FONTS["body"],
                                            text_color=COLORS["text_bright"],
                                            dropdown_fg_color=COLORS["bg_elevated"],
                                            dropdown_hover_color=COLORS["bg_card_hover"],
                                            dropdown_text_color=COLORS["text_bright"])
            self.input.pack()
        
        else:  # entry
            self.var = ctk.StringVar(value=str(value) if value else "")
            self.input = ctk.CTkEntry(right_frame, textvariable=self.var, width=160, height=36,
                                       fg_color=COLORS["bg_input"],
                                       border_color=COLORS["border"],
                                       border_width=1,
                                       corner_radius=8,
                                       font=FONTS["body"],
                                       text_color=COLORS["text_bright"])
            self.input.pack()
    
    def get(self) -> Any:
        if self.var is None:
            return None
        
        val = self.var.get()
        
        if self.setting_type == "switch":
            return "y" if val else "n"
        elif self.setting_type == "number":
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0
        elif self.setting_type == "decimal":
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0
        elif self.setting_type == "slider":
            return int(val)
        
        return val
    
    def set(self, value: Any):
        if self.var is None:
            return
        
        if self.setting_type == "switch":
            self.var.set(str(value).lower() in ("y", "yes", "true", "1", "on"))
        else:
            self.var.set(value)


class SectionCard(ctk.CTkFrame):
    """Förbättrat sektionskort med professionell design"""
    
    def __init__(self, parent, section_key: str, section_def: Dict[str, Any], current_values: Dict[str, Any] = None):
        super().__init__(parent, corner_radius=16, fg_color=COLORS["bg_card"],
                         border_width=1, border_color=COLORS["border_light"])
        
        self.section_key = section_key
        self.settings: Dict[str, SettingRow] = {}
        
        if current_values is None:
            current_values = {}
        
        # Header med gradient-effekt
        header = ctk.CTkFrame(self, fg_color="transparent", corner_radius=16)
        header.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["xl"], SPACING["md"]))
        
        # Icon och titel
        title_container = ctk.CTkFrame(header, fg_color="transparent")
        title_container.pack(side="left", fill="y")
        
        icon = section_def.get("_icon", "⚙️")
        title = section_def.get("_title", section_key)
        
        # Icon med bakgrund
        icon_frame = ctk.CTkFrame(title_container, fg_color=COLORS["bg_elevated"],
                                   corner_radius=10, width=40, height=40)
        icon_frame.pack(side="left", padx=(0, SPACING["md"]))
        icon_frame.pack_propagate(False)
        
        icon_label = ctk.CTkLabel(icon_frame, text=icon, font=ctk.CTkFont(size=20))
        icon_label.pack(expand=True)
        
        # Titel
        title_frame = ctk.CTkFrame(title_container, fg_color="transparent")
        title_frame.pack(side="left", fill="y")
        
        title_label = ctk.CTkLabel(title_frame, text=title,
                                    font=FONTS["h2"],
                                    text_color=COLORS["text_bright"])
        title_label.pack(anchor="w")
        
        # Beskrivning
        if section_def.get("_description"):
            desc_label = ctk.CTkLabel(title_frame, text=section_def["_description"],
                                       font=FONTS["body_small"],
                                       text_color=COLORS["text_dim"])
            desc_label.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Elegant separator med gradient-effekt
        sep_container = ctk.CTkFrame(self, fg_color="transparent")
        sep_container.pack(fill="x", padx=SPACING["xl"], pady=SPACING["sm"])
        
        sep = ctk.CTkFrame(sep_container, height=2, fg_color=COLORS["border"])
        sep.pack(fill="x")
        
        # Inställningar med bättre spacing
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["md"], SPACING["xl"]))
        
        settings_added = 0
        for idx, (key, definition) in enumerate(section_def.items()):
            if key.startswith("_"):
                continue
            
            current_val = current_values.get(key)
            row = SettingRow(content, key, definition, current_val)
            row.pack(fill="x", pady=SPACING["md"] if settings_added > 0 else 0)
            self.settings[key] = row
            settings_added += 1
        
        # Om inga inställningar finns, visa meddelande
        if settings_added == 0:
            empty_label = ctk.CTkLabel(content, text="Inga inställningar i denna kategori",
                                        font=FONTS["body_small"],
                                        text_color=COLORS["text_muted"])
            empty_label.pack(pady=SPACING["lg"])
    
    def get_values(self) -> Dict[str, Any]:
        return {key: row.get() for key, row in self.settings.items()}


# =============================================================================
# HUVUDAPPLIKATION
# =============================================================================


class ConfigGUI(ctk.CTk):
    """Huvudfönstret för konfigurationshanteraren"""
    
    def __init__(self):
        super().__init__()

        # Initiera fonts EFTER att root (self) är skapad
        global FONTS
        if not FONTS:
            FONTS = {
                "h1": ctk.CTkFont(size=28, weight="bold"),      # Huvudtitel
                "h2": ctk.CTkFont(size=20, weight="bold"),      # Sektionstitel
                "h3": ctk.CTkFont(size=16, weight="bold"),      # Undertitel
                "body": ctk.CTkFont(size=14),                   # Brödtext
                "body_small": ctk.CTkFont(size=12),             # Mindre text
                "label": ctk.CTkFont(size=14, weight="bold"),   # Labels
                "button": ctk.CTkFont(size=14, weight="bold"),  # Knappar
                "caption": ctk.CTkFont(size=11),                # Captions
            }
        
        self.title("🎯 PANG Konfiguration")
        
        # Anpassa storlek efter skärm
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        width = min(1000, int(screen_width * 0.8))
        height = min(800, int(screen_height * 0.85))
        
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(800, 600)
        
        # Ladda GUI-inställningar först (för Dropbox-sökväg)
        self.gui_settings = load_gui_settings()

        # Ladda nuvarande config (lokala filer)
        self.poit_config = load_poit_config()
        self.segment_config = load_segment_config()
        self.sajt_config = load_sajt_config()
        
        self.sections: Dict[str, SectionCard] = {}
        
        self.setup_ui()
    
    def setup_ui(self):
        """Bygg gränssnittet med förbättrad design"""
        # Huvudcontainer
        self.main_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_main"])
        self.main_frame.pack(fill="both", expand=True)
        
        # ===== HEADER - Förbättrad design =====
        header = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_elevated"], height=100,
                              corner_radius=0, border_width=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_content = ctk.CTkFrame(header, fg_color="transparent")
        header_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["lg"])
        
        # Titel-sektion
        title_frame = ctk.CTkFrame(header_content, fg_color="transparent")
        title_frame.pack(side="left", fill="y")
        
        # Logo/ikon
        logo_frame = ctk.CTkFrame(title_frame, fg_color=COLORS["accent"],
                                   corner_radius=12, width=48, height=48)
        logo_frame.pack(side="left", padx=(0, SPACING["md"]))
        logo_frame.pack_propagate(False)
        
        logo_label = ctk.CTkLabel(logo_frame, text="🎯", font=ctk.CTkFont(size=24))
        logo_label.pack(expand=True)
        
        # Titel och subtitle
        text_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="y")
        
        title = ctk.CTkLabel(text_frame, text="PANG Konfiguration",
                              font=FONTS["h1"],
                              text_color=COLORS["text_bright"])
        title.pack(anchor="w")
        
        subtitle = ctk.CTkLabel(text_frame, text="Hantera alla inställningar på ett ställe",
                                 font=FONTS["body_small"],
                                 text_color=COLORS["text_dim"])
        subtitle.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Knappar - Alla i samma rad med olika färger
        btn_frame = ctk.CTkFrame(header_content, fg_color="transparent")
        btn_frame.pack(side="right", fill="y")
        
        # Spara-knapp (grön, högre)
        self.save_btn = ctk.CTkButton(btn_frame, text="💾 Spara", width=120, height=50,
                                       command=self.save_all,
                                       fg_color=COLORS["success"],
                                       hover_color=COLORS["success_hover"],
                                       corner_radius=10,
                                       font=FONTS["button"],
                                       text_color="#ffffff",
                                       border_width=0)
        self.save_btn.pack(side="left", padx=SPACING["xs"])
        
        # Synka till Dashboard-knapp (orange/warning färg)
        self.sync_dashboard_btn = ctk.CTkButton(btn_frame, text="☁️ Synka Dashboard", width=150, height=50,
                                               command=self.push_to_dashboard,
                                               fg_color=COLORS["warning"],
                                               hover_color=COLORS["warning_hover"],
                                               corner_radius=10,
                                               font=FONTS["button"],
                                               text_color="#ffffff",
                                               border_width=0)
        self.sync_dashboard_btn.pack(side="left", padx=SPACING["xs"])
        
        # Master-nummer input (kompakt)
        self.master_entry = ctk.CTkEntry(btn_frame, width=70, height=44,
                                          placeholder_text="Master",
                                          fg_color=COLORS["bg_input"],
                                          border_color=COLORS["border"],
                                          border_width=1,
                                          corner_radius=8,
                                          font=FONTS["body_small"],
                                          text_color=COLORS["text_bright"])
        self.master_entry.pack(side="left", padx=SPACING["xs"])
        
        # Kör-knapp (blå, använder master om angivet)
        self.run_btn = ctk.CTkButton(btn_frame, text="▶️ Kör", width=120, height=44,
                                      command=self.run_pipeline,
                                      fg_color=COLORS["accent"],
                                      hover_color=COLORS["accent_hover"],
                                      corner_radius=10,
                                      font=FONTS["button"],
                                      text_color="#ffffff",
                                      border_width=0)
        self.run_btn.pack(side="left", padx=SPACING["xs"])
        
        # Snabbkörning-knapp (lila/purple)
        self.quick_run_btn = ctk.CTkButton(btn_frame, text="🚀 Kör med master", width=140, height=44,
                                            command=self.run_with_master,
                                            fg_color=COLORS["secondary"],
                                            hover_color=COLORS["secondary_hover"],
                                            corner_radius=10,
                                            font=FONTS["button"],
                                            text_color="#ffffff",
                                            border_width=0)
        self.quick_run_btn.pack(side="left", padx=SPACING["xs"])
        
        # Återställ till standard-knapp (röd - varning)
        self.reset_btn = ctk.CTkButton(btn_frame, text="🔄 Återställ", width=120, height=44,
                                        command=self.reset_to_defaults,
                                        fg_color=COLORS["error"],
                                        hover_color=COLORS["error_hover"],
                                        corner_radius=10,
                                        font=FONTS["button"],
                                        text_color="#ffffff",
                                        border_width=0)
        self.reset_btn.pack(side="left", padx=SPACING["xs"])
        
        # ===== DASHBOARD INSTÄLLNINGAR =====
        
        dashboard_settings_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_card"],
                                              corner_radius=0, height=100, border_width=0)
        dashboard_settings_frame.pack(fill="x", pady=(0, 0))
        dashboard_settings_frame.pack_propagate(False)
        
        dashboard_content = ctk.CTkFrame(dashboard_settings_frame, fg_color="transparent")
        dashboard_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["sm"])
        
        # Rad 1: Email + Dashboard URL
        row1 = ctk.CTkFrame(dashboard_content, fg_color="transparent")
        row1.pack(fill="x", pady=(0, SPACING["xs"]))
        
        email_label = ctk.CTkLabel(row1, text="📧 Email:",
                                   font=FONTS["body"],
                                   text_color=COLORS["text"], width=80, anchor="w")
        email_label.pack(side="left", padx=(0, SPACING["sm"]))
        
        self.email_entry = ctk.CTkEntry(row1, width=250, height=32,
                                         placeholder_text="din@email.com",
                                         fg_color=COLORS["bg_input"],
                                         border_color=COLORS["border"],
                                         border_width=1,
                                         corner_radius=8,
                                         font=FONTS["body_small"],
                                         text_color=COLORS["text_bright"])
        self.email_entry.insert(0, self.gui_settings.get("email", ""))
        self.email_entry.pack(side="left", padx=(0, SPACING["lg"]))
        
        url_label = ctk.CTkLabel(row1, text="🌐 Dashboard:",
                                   font=FONTS["body"],
                                   text_color=COLORS["text"], width=100, anchor="w")
        url_label.pack(side="left", padx=(0, SPACING["sm"]))
        
        self.dashboard_url_entry = ctk.CTkEntry(row1, width=280, height=32,
                                         placeholder_text="https://jocke.onrender.com",
                                         fg_color=COLORS["bg_input"],
                                         border_color=COLORS["border"],
                                         border_width=1,
                                         corner_radius=8,
                                         font=FONTS["body_small"],
                                         text_color=COLORS["text_bright"])
        self.dashboard_url_entry.insert(0, self.gui_settings.get("dashboard_url", ""))
        self.dashboard_url_entry.pack(side="left")
        
        # Rad 2: JOCKE_API nyckel + hämta-knapp
        row2 = ctk.CTkFrame(dashboard_content, fg_color="transparent")
        row2.pack(fill="x", pady=(SPACING["xs"], 0))
        
        api_label = ctk.CTkLabel(row2, text="🔑 API-nyckel:",
                                     font=FONTS["body"],
                                     text_color=COLORS["text"], width=100, anchor="w")
        api_label.pack(side="left", padx=(0, SPACING["sm"]))
        
        self.api_key_entry = ctk.CTkEntry(row2, width=200, height=32,
                                                placeholder_text="JOCKE_API",
                                                fg_color=COLORS["bg_input"],
                                                border_color=COLORS["border"],
                                                border_width=1,
                                                corner_radius=8,
                                                font=FONTS["body_small"],
                                                text_color=COLORS["text_bright"],
                                                show="*")
        self.api_key_entry.insert(0, self.gui_settings.get("jocke_api", "12345"))
        self.api_key_entry.pack(side="left", padx=(0, SPACING["md"]))
        
        # Hämta från dashboard-knapp
        pull_btn = ctk.CTkButton(row2, text="⬇ Hämta från Dashboard", width=180, height=32,
                                    command=self.pull_from_dashboard,
                                    fg_color=COLORS["bg_elevated"],
                                    hover_color=COLORS["bg_card_hover"],
                                    corner_radius=8,
                                    font=FONTS["body_small"],
                                    text_color=COLORS["text"],
                                    border_width=1,
                                    border_color=COLORS["border"])
        pull_btn.pack(side="left", padx=(0, SPACING["sm"]))
        
        dash_info = ctk.CTkLabel(row2, 
                                   text="(Config synkas med dashboard-sajten)",
                                   font=FONTS["caption"],
                                   text_color=COLORS["text_muted"])
        dash_info.pack(side="left")
        
        # ===== FLIKAR - Förbättrad design =====
        self.tabview = ctk.CTkTabview(self.main_frame, fg_color=COLORS["bg_main"],
                                       segmented_button_fg_color=COLORS["bg_elevated"],
                                       segmented_button_selected_color=COLORS["accent"],
                                       segmented_button_selected_hover_color=COLORS["accent_hover"],
                                       segmented_button_unselected_color=COLORS["bg_card"],
                                       segmented_button_unselected_hover_color=COLORS["bg_card_hover"],
                                       corner_radius=12,
                                       border_width=0)
        self.tabview.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["lg"])
        
        # Skapa flikar
        self.tab_scraping = self.tabview.add("🔍 Skrapning")
        self.tab_ai = self.tabview.add("🤖 AI-Research")
        self.tab_mail = self.tabview.add("✉️ Mail")
        self.tab_sites = self.tabview.add("🌐 Sajter")
        self.tab_advanced = self.tabview.add("⚙️ Advanced")
        
        self.setup_scraping_tab()
        self.setup_ai_tab()
        self.setup_mail_tab()
        self.setup_sites_tab()
        self.setup_advanced_tab()
        
        # ===== STATUSRAD - Förbättrad design =====
        status_bar = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_elevated"],
                                   corner_radius=0, height=36, border_width=0)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        
        status_content = ctk.CTkFrame(status_bar, fg_color="transparent")
        status_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["sm"])
        
        # Status med ikon
        status_left = ctk.CTkFrame(status_content, fg_color="transparent")
        status_left.pack(side="left")
        
        status_icon = ctk.CTkLabel(status_left, text="✓", font=ctk.CTkFont(size=14),
                                    text_color=COLORS["success"])
        status_icon.pack(side="left", padx=(0, SPACING["sm"]))
        
        self.status = ctk.CTkLabel(status_left, text="Redo",
                                    font=FONTS["caption"],
                                    text_color=COLORS["text_dim"])
        self.status.pack(side="left")
        
        # Plattform-info
        platform_info = f"{'🍎 macOS' if IS_MAC else '🪟 Windows' if IS_WINDOWS else '🐧 Linux'}"
        platform_label = ctk.CTkLabel(status_content, text=platform_info,
                                       font=FONTS["caption"],
                                       text_color=COLORS["text_muted"])
        platform_label.pack(side="right")
    
    def create_section_in_scroll(self, parent, section_key: str, current_values: Dict[str, Any] = None, 
                                  filter_advanced: bool = False):
        """Skapa en sektion i en scrollbar frame med förbättrad spacing
        
        Args:
            parent: Parent widget
            section_key: Nyckel för sektionen i SETTINGS_DEFINITIONS
            current_values: Nuvarande värden från config
            filter_advanced: Om True, visa endast avancerade inställningar. Om False, visa endast icke-avancerade.
        """
        section_def = SETTINGS_DEFINITIONS.get(section_key, {})
        
        # Filtrera inställningar baserat på advanced-flaggan
        if filter_advanced is not None:
            filtered_def = {k: v for k, v in section_def.items() 
                           if k.startswith("_") or v.get("advanced", False) == filter_advanced}
            section_def = filtered_def
        
        # Använd unik key för avancerade sektioner så de inte skriver över vanliga
        storage_key = f"{section_key}_advanced" if filter_advanced else section_key
        
        card = SectionCard(parent, section_key, section_def, current_values)
        card.pack(fill="x", pady=SPACING["lg"], padx=SPACING["sm"])
        self.sections[storage_key] = card
        return card
    
    def setup_scraping_tab(self):
        """Flik för skrapningsinställningar"""
        scroll = ctk.CTkScrollableFrame(self.tab_scraping, fg_color=COLORS["bg_main"],
                                         corner_radius=0, border_width=0)
        scroll.pack(fill="both", expand=True, padx=SPACING["md"], pady=SPACING["md"])
        
        # Skrapning (endast icke-avancerade)
        self.create_section_in_scroll(scroll, "scraping", self.poit_config, filter_advanced=False)
        
        # Pipeline (endast icke-avancerade)
        pipeline_values = self.segment_config.get("PIPELINE", {})
        self.create_section_in_scroll(scroll, "pipeline", pipeline_values, filter_advanced=False)
    
    def setup_ai_tab(self):
        """Flik för AI-inställningar"""
        scroll = ctk.CTkScrollableFrame(self.tab_ai, fg_color=COLORS["bg_main"],
                                         corner_radius=0, border_width=0)
        scroll.pack(fill="both", expand=True, padx=SPACING["md"], pady=SPACING["md"])
        
        # Research (endast icke-avancerade)
        research_values = self.segment_config.get("RESEARCH", {})
        self.create_section_in_scroll(scroll, "research", research_values, filter_advanced=False)
        
        # Domain (endast icke-avancerade)
        domain_values = self.segment_config.get("DOMAIN", {})
        self.create_section_in_scroll(scroll, "domain", domain_values, filter_advanced=False)
    
    def setup_mail_tab(self):
        """Flik för mail-inställningar"""
        scroll = ctk.CTkScrollableFrame(self.tab_mail, fg_color=COLORS["bg_main"],
                                         corner_radius=0, border_width=0)
        scroll.pack(fill="both", expand=True, padx=SPACING["md"], pady=SPACING["md"])
        
        # Mail
        mail_values = self.segment_config.get("MAIL", {})
        self.create_section_in_scroll(scroll, "mail", mail_values)
        
        # Ton & stil
        self.create_section_in_scroll(scroll, "mail_tone", mail_values)
    
    def setup_sites_tab(self):
        """Flik för sajt-inställningar"""
        scroll = ctk.CTkScrollableFrame(self.tab_sites, fg_color=COLORS["bg_main"],
                                         corner_radius=0, border_width=0)
        scroll.pack(fill="both", expand=True, padx=SPACING["md"], pady=SPACING["md"])
        
        # Utvärdering (endast icke-avancerade)
        self.create_section_in_scroll(scroll, "evaluation", self.sajt_config, filter_advanced=False)
        
        # Sites (endast icke-avancerade)
        self.create_section_in_scroll(scroll, "sites", self.sajt_config, filter_advanced=False)
        
        # Audit (endast icke-avancerade)
        self.create_section_in_scroll(scroll, "audit", self.sajt_config, filter_advanced=False)
    
    def setup_advanced_tab(self):
        """Flik för avancerade/tekniska inställningar"""
        scroll = ctk.CTkScrollableFrame(self.tab_advanced, fg_color=COLORS["bg_main"],
                                         corner_radius=0, border_width=0)
        scroll.pack(fill="both", expand=True, padx=SPACING["md"], pady=SPACING["md"])
        
        # Info-text
        info_frame = ctk.CTkFrame(scroll, fg_color=COLORS["bg_elevated"], corner_radius=12)
        info_frame.pack(fill="x", pady=(0, SPACING["lg"]))
        
        info_label = ctk.CTkLabel(info_frame, 
                                   text="⚙️ Avancerade inställningar\n\n"
                                        "Dessa inställningar är mer tekniska och används sällan. "
                                        "Vissa kan vara definierade men inte implementerade i koden ännu.",
                                   font=FONTS["body_small"],
                                   text_color=COLORS["text_dim"],
                                   justify="left",
                                   wraplength=600)
        info_label.pack(padx=SPACING["lg"], pady=SPACING["md"])
        
        # Pipeline (endast avancerade)
        pipeline_values = self.segment_config.get("PIPELINE", {})
        self.create_section_in_scroll(scroll, "pipeline", pipeline_values, filter_advanced=True)
        
        # Domain (endast avancerade)
        domain_values = self.segment_config.get("DOMAIN", {})
        self.create_section_in_scroll(scroll, "domain", domain_values, filter_advanced=True)
    
    def collect_all_values(self) -> Dict[str, Any]:
        """Samla alla värden från UI"""
        result = {
            "poit": {},
            "segment": {
                "PIPELINE": {"source_dir": "1_poit/info_server"},
                "RESEARCH": {},
                "DOMAIN": {"parallel_checks": 5},
                "MAIL": {},
            },
            "sajt": {},
        }
        
        # Scraping
        if "scraping" in self.sections:
            scraping_vals = self.sections["scraping"].get_values()
            result["poit"]["MAX_KUN_DAG"] = scraping_vals.get("MAX_KUN_DAG", 150)
        
        # Pipeline
        if "pipeline" in self.sections:
            pipeline_vals = self.sections["pipeline"].get_values()
            result["segment"]["PIPELINE"].update(pipeline_vals)
        
        # Research
        if "research" in self.sections:
            research_vals = self.sections["research"].get_values()
            result["segment"]["RESEARCH"].update(research_vals)
        
        # Domain (både vanliga och avancerade)
        if "domain" in self.sections:
            domain_vals = self.sections["domain"].get_values()
            result["segment"]["DOMAIN"].update(domain_vals)
        if "domain_advanced" in self.sections:
            domain_advanced_vals = self.sections["domain_advanced"].get_values()
            result["segment"]["DOMAIN"].update(domain_advanced_vals)
        
        # Pipeline (både vanliga och avancerade)
        if "pipeline_advanced" in self.sections:
            pipeline_advanced_vals = self.sections["pipeline_advanced"].get_values()
            result["segment"]["PIPELINE"].update(pipeline_advanced_vals)
        
        # Mail
        if "mail" in self.sections:
            mail_vals = self.sections["mail"].get_values()
            result["segment"]["MAIL"].update(mail_vals)
        
        # Mail tone
        if "mail_tone" in self.sections:
            tone_vals = self.sections["mail_tone"].get_values()
            result["segment"]["MAIL"].update(tone_vals)
        
        # Evaluation
        if "evaluation" in self.sections:
            eval_vals = self.sections["evaluation"].get_values()
            result["sajt"].update(eval_vals)
        
        # Sites
        if "sites" in self.sections:
            sites_vals = self.sections["sites"].get_values()
            result["sajt"].update(sites_vals)
        
        # Audit
        if "audit" in self.sections:
            audit_vals = self.sections["audit"].get_values()
            result["sajt"].update(audit_vals)
        
        return result
    
    @staticmethod
    def _sync_env_key(key: str, value: str):
        """Update or append a KEY=value pair in .env without touching other lines."""
        if not ENV_FILE.exists():
            ENV_FILE.write_text(f"{key}={value}\n", encoding="utf-8")
            return
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"#{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def save_all(self):
        """Spara alla konfigurationer till lokala filer + dashboard"""
        try:
            # Backup först
            backup_path = backup_configs()
            
            # Samla värden
            values = self.collect_all_values()
            
            # Spara till lokala config-filer
            save_poit_config(values["poit"].get("MAX_KUN_DAG", 150))
            save_segment_config(values["segment"])
            save_sajt_config(values["sajt"])
            
            # Synka gui_settings
            email = self.email_entry.get().strip()
            dashboard_url = self.dashboard_url_entry.get().strip().rstrip("/")
            api_key = self.api_key_entry.get().strip()
            self.gui_settings["email"] = email
            self.gui_settings["dashboard_url"] = dashboard_url
            self.gui_settings["jocke_api"] = api_key
            save_gui_settings(self.gui_settings)
            
            # Synka DASHBOARD_URL + JOCKE_API till .env
            if dashboard_url:
                self._sync_env_key("DASHBOARD_URL", dashboard_url)
            if api_key:
                self._sync_env_key("JOCKE_API", api_key)
            
            # Pusha till dashboard
            dashboard_msg = ""
            if dashboard_url and api_key:
                try:
                    from utils.load_external_config import push_config_to_dashboard
                    if push_config_to_dashboard(dashboard_url, api_key, values):
                        dashboard_msg = "Synkad med dashboard!"
                    else:
                        dashboard_msg = "Kunde inte synka med dashboard"
                except Exception as e:
                    dashboard_msg = f"Dashboard-fel: {e}"
            
            # Status-meddelande
            status_msg = "✓ Alla inställningar sparade!"
            info_msg = f"Alla konfigurationer sparade!\n\nBackup skapad i:\n{BACKUP_DIR}"
            
            if dashboard_msg:
                if "Synkad" in dashboard_msg:
                    status_msg += " + Dashboard"
                info_msg += f"\n\nDashboard: {dashboard_msg}"
            
            self.status.configure(text=status_msg, text_color=COLORS["success"])
            
            messagebox.showinfo("Sparat!", info_msg)
            
        except Exception as e:
            self.status.configure(text=f"✗ Fel: {e}", text_color=COLORS["error"])
            messagebox.showerror("Fel", f"Kunde inte spara:\n{e}")
    
    def push_to_dashboard(self):
        """Pusha aktuell config till dashboard-API:t"""
        dashboard_url = self.dashboard_url_entry.get().strip().rstrip("/")
        api_key = self.api_key_entry.get().strip()
        
        if not dashboard_url:
            messagebox.showerror("Fel", "Ange Dashboard-URL!")
            return
        if not api_key:
            messagebox.showerror("Fel", "Ange API-nyckel (JOCKE_API)!")
            return
        
        try:
            values = self.collect_all_values()
            
            from utils.load_external_config import push_config_to_dashboard
            if push_config_to_dashboard(dashboard_url, api_key, values):
                self.status.configure(text="✓ Config pushad till dashboard!",
                                      text_color=COLORS["success"])
                messagebox.showinfo("Synkat!", f"Konfiguration pushad till:\n{dashboard_url}")
            else:
                self.status.configure(text="✗ Kunde inte pusha till dashboard",
                                      text_color=COLORS["error"])
                messagebox.showerror("Fel", "Dashboard svarade inte korrekt.\nKontrollera URL och API-nyckel.")
        except Exception as e:
            self.status.configure(text=f"✗ Fel: {e}", text_color=COLORS["error"])
            messagebox.showerror("Fel", f"Kunde inte synka:\n{e}")
    
    def pull_from_dashboard(self):
        """Hämta config från dashboard och uppdatera GUI-fälten"""
        dashboard_url = self.dashboard_url_entry.get().strip().rstrip("/")
        api_key = self.api_key_entry.get().strip()
        
        if not dashboard_url:
            messagebox.showerror("Fel", "Ange Dashboard-URL!")
            return
        if not api_key:
            messagebox.showerror("Fel", "Ange API-nyckel (JOCKE_API)!")
            return
        
        try:
            from utils.load_external_config import fetch_config_from_dashboard
            config = fetch_config_from_dashboard(dashboard_url, api_key)
            
            if config is None:
                self.status.configure(text="✗ Kunde inte hämta från dashboard",
                                      text_color=COLORS["error"])
                messagebox.showerror("Fel", "Kunde inte hämta config från dashboard.\nKontrollera URL och API-nyckel.")
                return
            
            # Uppdatera lokala config-objekt
            self.poit_config = config.get("poit", {})
            self.segment_config = config.get("segment", {})
            self.sajt_config = config.get("sajt", {})
            
            # Spara till lokala filer
            save_poit_config(self.poit_config.get("MAX_KUN_DAG", 150))
            save_segment_config(self.segment_config)
            save_sajt_config(self.sajt_config)
            
            self.status.configure(text="✓ Config hämtad från dashboard! Starta om GUI:t för att se nya värden.",
                                  text_color=COLORS["success"])
            messagebox.showinfo(
                "Hämtat!",
                "Konfiguration hämtad från dashboard och sparad lokalt.\n\n"
                "Stäng och öppna GUI:t för att se de nya värdena."
            )
        except Exception as e:
            self.status.configure(text=f"✗ Fel: {e}", text_color=COLORS["error"])
            messagebox.showerror("Fel", f"Kunde inte hämta:\n{e}")
    
    def reset_to_defaults(self):
        """Återställ alla inställningar till standardvärden (fabriksåterställning)"""
        # Bekräfta med användaren
        if not messagebox.askyesno(
            "Återställ till standard?",
            "⚠️ VARNING!\n\n"
            "Detta återställer ALLA inställningar till standardvärden.\n\n"
            "Dina nuvarande inställningar kommer att skrivas över!\n\n"
            "En backup skapas automatiskt innan återställning.\n\n"
            "Vill du fortsätta?"
        ):
            return
        
        try:
            # Skapa backup först
            backup_path = backup_configs()
            
            # Återställ till standardvärden
            success, msg = restore_to_defaults()
            
            if success:
                # Ladda om konfigurationer i GUI:t
                self.poit_config = load_poit_config()
                self.segment_config = load_segment_config()
                self.sajt_config = load_sajt_config()
                
                # Uppdatera status
                self.status.configure(text="✓ Återställd till standardvärden!", 
                                      text_color=COLORS["success"])
                
                messagebox.showinfo(
                    "Återställning klar!",
                    f"✓ Alla inställningar återställda till standardvärden!\n\n"
                    f"Backup sparad i:\n{BACKUP_DIR}\n\n"
                    f"OBS: Stäng och öppna GUI:t för att se de nya värdena,\n"
                    f"eller tryck på 'Kör' för att använda standardvärdena direkt."
                )
            else:
                self.status.configure(text=f"✗ {msg}", text_color=COLORS["error"])
                messagebox.showerror("Fel", f"Kunde inte återställa:\n\n{msg}")
                
        except Exception as e:
            self.status.configure(text=f"✗ Fel: {e}", text_color=COLORS["error"])
            messagebox.showerror("Fel", f"Kunde inte återställa:\n{e}")
    
    def run_pipeline(self):
        """Kör main.py - använder master-nummer om angivet"""
        # Kolla om master-nummer är angivet
        master = self.master_entry.get().strip()
        
        if master:
            try:
                master_num = int(master)
                confirm_msg = f"Spara inställningar och starta main.py med master={master_num}?"
            except ValueError:
                messagebox.showerror("Fel", "Master-nummer måste vara ett heltal!")
                return
        else:
            confirm_msg = "Spara inställningar och starta main.py?"
        
        if messagebox.askyesno("Kör pipeline", confirm_msg):
            self.save_all()
            
            if master:
                self.status.configure(text=f"▶ Startar pipeline med master={master_num}...", 
                                      text_color=COLORS["warning"])
            else:
                self.status.configure(text="▶ Startar pipeline...", 
                                      text_color=COLORS["warning"])
            self.update()
            
            # Bygg kommando med eller utan master
            if master:
                cmd_suffix = f" {master_num}"
            else:
                cmd_suffix = ""
            
            launch_pipeline(cmd_suffix)
    
    def run_with_master(self):
        """Kör med master-nummer"""
        master = self.master_entry.get().strip()
        if not master:
            messagebox.showwarning("Saknas", "Ange ett master-nummer först!")
            return
        
        try:
            master_num = int(master)
        except ValueError:
            messagebox.showerror("Fel", "Master-nummer måste vara ett heltal!")
            return
        
        if messagebox.askyesno("Kör pipeline", 
                               f"Starta main.py med master={master_num}?\n\n"
                               f"Detta begränsar alla steg till max {master_num} företag."):
            self.status.configure(text=f"▶ Startar med master={master_num}...", 
                                  text_color=COLORS["warning"])
            self.update()

            launch_pipeline(f" {master_num}")


# =============================================================================
# MAIN
# =============================================================================


def main():
    app = ConfigGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
