#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PANG Config GUI - Mac Edition
==============================
Exakt samma GUI som huvudversionen, men med möjlighet att ladda config från Dropbox.

Fungerar på: macOS (och Windows/Linux)

Features:
- Laddar config från Dropbox (om tillgänglig)
- Faller tillbaka till standardvärden
- Alla samma inställningar och beskrivningar
- Tooltips med frågetecken på varje setting
- Spara lokalt

Kör: python3 mac_config_gui.py
"""

import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, filedialog
from typing import Any, Dict, Optional, Tuple

# =============================================================================
# AUTO-INSTALLATION AV BEROENDEN
# =============================================================================

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
    """Installera ett Python-paket om det saknas."""
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        pass

    print(f"📦 Installerar {package_name}...")
    if not _ensure_pip():
        print("   ⚠️ Pip saknas. Installera pip och försök igen.")
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
            print(f"   ✅ {package_name} installerat!")
            return True
        except Exception as exc:
            last_error = exc

    print(f"   ⚠️ Kunde inte installera {package_name}: {last_error}")
    print(f"      Kör manuellt: {sys.executable} -m pip install {package_name}")
    return False

# Installera customtkinter om det saknas
_ensure_user_site_on_path()
try:
    import customtkinter as ctk
except ImportError:
    print("")
    print("🔧 Förbereder första körningen...")
    if install_package("customtkinter"):
        import customtkinter as ctk
    else:
        print("")
        print("❌ Kunde inte installera customtkinter.")
        print(f"   Kör: {sys.executable} -m pip install customtkinter")
        print("")
        input("Tryck Enter för att avsluta...")
        sys.exit(1)

# =============================================================================
# SÖKVÄGAR
# =============================================================================

MAC_GUI_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = MAC_GUI_DIR / "default_config.json"
LOCAL_CONFIG = MAC_GUI_DIR / "local_config.json"
SETTINGS_FILE = MAC_GUI_DIR / "gui_settings.json"
DROPBOX_CANONICAL_FILENAME = "leads.enviroments.txt"
DROPBOX_CONFIG_NAME = DROPBOX_CANONICAL_FILENAME

MAIL_TONE_KEYS = ("formality", "salesiness", "flattery", "length")

# Plattform
IS_MAC = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# =============================================================================
# TEMA OCH FÄRGER - Exakt samma som huvudversionen
# =============================================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    # Bakgrunder - mjuka, djupa toner
    "bg_dark": "#0a0e1a",
    "bg_main": "#0f1419",
    "bg_card": "#1a1f2e",
    "bg_card_hover": "#1f2535",
    "bg_input": "#252b3a",
    "bg_input_focus": "#2d3445",
    "bg_elevated": "#1e2432",
    
    # Borders
    "border": "#2a3142",
    "border_light": "#1e2535",
    "border_focus": "#4a5568",
    
    # Accent-färger
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "accent_light": "#60a5fa",
    
    # Sekundära färger
    "secondary": "#8b5cf6",
    "secondary_hover": "#7c3aed",
    "success": "#10b981",
    "success_hover": "#059669",
    "warning": "#f59e0b",
    "warning_hover": "#d97706",
    "error": "#ef4444",
    "error_hover": "#dc2626",
    
    # Text
    "text": "#e2e8f0",
    "text_dim": "#94a3b8",
    "text_bright": "#f1f5f9",
    "text_muted": "#64748b",
    
    # Special
    "highlight": "#f97316",
    "highlight_hover": "#ea580c",
}

# Fonts (initieras efter att root skapats)
FONTS: Dict[str, Any] = {}

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

# =============================================================================
# INSTÄLLNINGSDEFINITIONER - Exakt samma som huvudversionen
# =============================================================================

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
            "used_in_code": False,
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
# DROPBOX FUNKTIONER
# =============================================================================


def find_dropbox_folder() -> Optional[Path]:
    """Hitta Dropbox-mapp (Mac/Windows/Linux)"""
    paths = [
        Path.home() / "Dropbox",
        Path.home() / "Library" / "CloudStorage" / "Dropbox",  # macOS ny
        Path.home() / "Dropbox (Personal)",
        Path.home() / "Dropbox (Team)",
    ]
    
    if IS_WINDOWS:
        username = os.getenv("USERNAME", "User")
        paths.extend([
            Path(f"C:/Users/{username}/Dropbox"),
            Path("D:/Dropbox"),
            Path("E:/Dropbox"),
        ])
    
    for p in paths:
        if p.exists() and p.is_dir():
            return p
    return None


def find_dropbox_config(dropbox_path: Optional[str] = None) -> Optional[Path]:
    """Sök efter config-fil i Dropbox"""
    dropbox = Path(dropbox_path) if dropbox_path else find_dropbox_folder()
    if not dropbox or not dropbox.exists():
        return None

    name = DROPBOX_CONFIG_NAME
    # FÖRST: Kolla i leads-undermappen (där filen faktiskt ligger)
    leads_subdir = dropbox / "leads" / name
    if leads_subdir.exists():
        return leads_subdir

    # Direkt i root
    direct = dropbox / name
    if direct.exists():
        return direct

    # Rekursivt (max 3 nivåer djupt för prestanda)
    try:
        for found in dropbox.rglob(name):
            if found.is_file():
                return found
    except PermissionError:
        pass

    return None


def parse_dropbox_config(path: Path) -> Dict[str, Any]:
    """
    Parsa en environment-fil från Dropbox till dict.
    Format: KEY=value eller [SECTION] KEY = value
    """
    config = {
        "poit": {},
        "segment": {
            "PIPELINE": {},
            "RESEARCH": {},
            "DOMAIN": {},
            "MAIL": {}
        },
        "sajt": {},
        "mail_tone": {}
    }
    
    current_section = None
    
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            
            # Hoppa över tomma
            if not line:
                continue
            
            # Sektion?
            if line.startswith("[") and line.endswith("]"):
                section_name = line[1:-1].upper()
                if section_name in config["segment"]:
                    current_section = section_name
                continue
            
            # Kommentarer med sektionsinformation
            if line.startswith("#"):
                if "SCRAPING" in line.upper() or "1_POIT" in line.upper():
                    current_section = "poit"
                elif "PIPELINE" in line.upper() or "2_SEGMENT" in line.upper():
                    current_section = "PIPELINE"
                elif "SITES" in line.upper() or "3_SAJT" in line.upper() or "SAJTER" in line.upper():
                    current_section = "sajt"
                continue
            
            # Parsa KEY=value
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                
                # Konvertera värde
                try:
                    if "." in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError:
                    # Behåll som string
                    pass
                
                # Placera i rätt sektion
                key_lower = key.lower()
                key_upper = key.upper()
                
                if key_upper == "MAX_KUN_DAG":
                    config["poit"]["MAX_KUN_DAG"] = val
                elif key_lower in MAIL_TONE_KEYS:
                    config["mail_tone"][key_lower] = val
                elif current_section == "poit":
                    config["poit"][key_upper] = val
                elif current_section in ["PIPELINE", "RESEARCH", "DOMAIN", "MAIL"]:
                    config["segment"][current_section][key_lower] = val
                elif current_section == "sajt":
                    config["sajt"][key_lower] = val
                elif key.startswith("PIPELINE_") or key_lower.startswith("pipeline_"):
                    config["segment"]["PIPELINE"][key_lower.replace("pipeline_", "")] = val
                elif key.startswith("RESEARCH_") or key_lower.startswith("research_"):
                    config["segment"]["RESEARCH"][key_lower.replace("research_", "")] = val
                elif key.startswith("DOMAIN_") or key_lower.startswith("domain_"):
                    config["segment"]["DOMAIN"][key_lower.replace("domain_", "")] = val
                elif key.startswith("MAIL_") or key_lower.startswith("mail_"):
                    mail_key = key_lower.replace("mail_", "")
                    if mail_key in MAIL_TONE_KEYS:
                        config["mail_tone"][mail_key] = val
                    else:
                        config["segment"]["MAIL"][mail_key] = val
                elif key.startswith("SAJT_") or key_lower.startswith("sajt_"):
                    config["sajt"][key_lower.replace("sajt_", "")] = val
                else:
                    # Försök matcha mot kända nycklar
                    if key_lower in ["evaluate", "threshold", "max_total_judgement_approvals", 
                                     "max_sites", "re_input_website_link", "audit_enabled",
                                     "audit_threshold", "max_audits", "re_input_audit"]:
                        config["sajt"][key_lower] = val
                    elif key_lower in ["enabled", "model", "max_searches", "search_persons", "max_persons"]:
                        config["segment"]["RESEARCH"][key_lower] = val
                    elif key_lower in ["max_companies", "delete_csv", "source_dir"]:
                        config["segment"]["PIPELINE"][key_lower] = val
    
    except Exception as e:
        print(f"Fel vid parsning av {path}: {e}")
    
    return config


def load_local_config() -> Dict[str, Any]:
    """Läs lokal config"""
    if LOCAL_CONFIG.exists():
        try:
            with open(LOCAL_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_default_config_file() -> Dict[str, Any]:
    """Läs default config"""
    if DEFAULT_CONFIG.exists():
        try:
            with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return get_builtin_defaults()


def get_builtin_defaults() -> Dict[str, Any]:
    """Inbyggda standardvärden"""
    return {
        "poit": {"MAX_KUN_DAG": 150},
        "segment": {
            "PIPELINE": {"source_dir": "1_poit/info_server", "max_companies": 150, "delete_csv": "y"},
            "RESEARCH": {"enabled": "y", "model": "gpt-4o", "max_searches": 3, "search_persons": "y", "max_persons": 2},
            "DOMAIN": {"timeout_seconds": 5, "max_crawl": 5, "parallel_checks": 5},
            "MAIL": {"enabled": "y", "model": "gpt-4o", "min_confidence": 40, "max_mails": 110}
        },
        "mail_tone": {"formality": 4, "salesiness": 3, "flattery": 2, "length": 5},
        "sajt": {
            "evaluate": "y", "threshold": 0.8, "max_total_judgement_approvals": 4,
            "max_sites": 4, "re_input_website_link": "y",
            "audit_enabled": "y", "audit_threshold": 0.85, "max_audits": 10, "re_input_audit": "y"
        }
    }


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = {
        "poit": dict(base.get("poit", {})),
        "segment": {
            "PIPELINE": dict(base.get("segment", {}).get("PIPELINE", {})),
            "RESEARCH": dict(base.get("segment", {}).get("RESEARCH", {})),
            "DOMAIN": dict(base.get("segment", {}).get("DOMAIN", {})),
            "MAIL": dict(base.get("segment", {}).get("MAIL", {})),
        },
        "mail_tone": dict(base.get("mail_tone", {})),
        "sajt": dict(base.get("sajt", {})),
    }

    merged["poit"].update(override.get("poit", {}))
    merged["mail_tone"].update(override.get("mail_tone", {}))
    merged["sajt"].update(override.get("sajt", {}))

    for section in ("PIPELINE", "RESEARCH", "DOMAIN", "MAIL"):
        merged["segment"][section].update(override.get("segment", {}).get(section, {}))

    mail_section = merged["segment"].get("MAIL", {})
    for key in MAIL_TONE_KEYS:
        if key in mail_section and key not in merged["mail_tone"]:
            merged["mail_tone"][key] = mail_section[key]

    return merged


def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return _merge_config(get_builtin_defaults(), config)


def load_config(dropbox_path: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """
    Ladda config med prioritet:
    1. Dropbox (senaste)
    2. Lokal config
    3. Standardvärden
    
    Returns:
        (config_dict, source_description)
    """
    local = load_local_config()
    if local:
        base = _normalize_config(local)
        base_source = "Lokal config"
    else:
        base = load_default_config_file()
        base_source = "Standardvärden"

    # 1. Försök Dropbox
    dropbox_file = find_dropbox_config(dropbox_path)
    if dropbox_file:
        print(f"[CONFIG] Laddar från Dropbox: {dropbox_file}")
        merged = _merge_config(base, parse_dropbox_config(dropbox_file))
        return merged, f"Dropbox: {dropbox_file.name}"

    print(f"[CONFIG] Laddar {base_source.lower()}")
    return base, base_source


def save_local_config(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Spara config lokalt"""
    try:
        with open(LOCAL_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True, f"Sparad till: {LOCAL_CONFIG}"
    except Exception as e:
        return False, f"Fel vid sparning: {e}"


def load_gui_settings() -> Dict[str, str]:
    """Ladda GUI-inställningar"""
    defaults = {
        "save_path": str(MAC_GUI_DIR),  # Lokal sparväg
        "dropbox_link": "",              # Dropbox-delningslänk
        "dropbox_local_path": "",        # Lokal Dropbox-mapp
        "dropbox_filename": DROPBOX_CANONICAL_FILENAME,  # Filnamn i Dropbox
        "email": "",                     # Email att inkludera i config
        "last_source": ""
    }
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    defaults["dropbox_filename"] = DROPBOX_CANONICAL_FILENAME
    return defaults


def save_gui_settings(settings: Dict[str, str]):
    """Spara GUI-inställningar"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def format_env_config_for_export(config: Dict[str, Any], email: str = "") -> str:
    platform_label = "Windows" if IS_WINDOWS else "macOS" if IS_MAC else "Linux"
    lines = [
        "# =============================================================================",
        "# LEADS ENVIRONMENT CONFIGURATION",
        "# =============================================================================",
        f"# Email: {email}",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Platform: {platform_label}",
        "# =============================================================================",
        "",
        f"EMAIL={email}",
        "",
        "# =============================================================================",
        "# SCRAPING (1_poit)",
        "# =============================================================================",
    ]

    if "poit" in config:
        for key, val in config["poit"].items():
            lines.append(f"{key}={val}")

    lines.append("")
    lines.append("# =============================================================================")
    lines.append("# PIPELINE (2_segment_info)")
    lines.append("# =============================================================================")

    segment = dict(config.get("segment", {}))
    mail_section = dict(segment.get("MAIL", {}))
    mail_section.update(config.get("mail_tone", {}))
    segment["MAIL"] = mail_section

    if segment:
        for section, section_vals in segment.items():
            lines.append("")
            lines.append(f"# [{section}]")
            for key, val in section_vals.items():
                env_key = f"{section}_{key}".upper()
                lines.append(f"{env_key}={val}")

    lines.append("")
    lines.append("# =============================================================================")
    lines.append("# SITES (3_sajt)")
    lines.append("# =============================================================================")

    if "sajt" in config:
        for key, val in config["sajt"].items():
            env_key = f"SAJT_{key}".upper()
            lines.append(f"{env_key}={val}")

    lines.append("")
    lines.append("# =============================================================================")
    lines.append("# END OF CONFIGURATION")
    lines.append("# =============================================================================")

    return "\n".join(lines)


def format_config_for_export(config: Dict[str, Any], email: str = "") -> str:
    """
    Formatera config som läsbar text för export.
    EXAKT samma format som huvudprogrammet (gui/config_gui.py).
    """
    lines = [
        "# =============================================================================",
        "# PANG KONFIGURATION",
        "# =============================================================================",
    ]
    
    if email:
        lines.append(f"# Email: {email}")
    
    lines.append(f"# Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("# =============================================================================")
    lines.append("")
    
    if email:
        lines.append(f"EMAIL={email}")
        lines.append("")
    
    lines.append("# --- SKRAPNING (1_poit) ---")
    
    # POIT config
    if "poit" in config:
        for key, val in config["poit"].items():
            lines.append(f"{key} = {val}")
    
    lines.append("")
    lines.append("# --- PIPELINE (2_segment_info) ---")
    
    # Segment config (merge mail_tone into MAIL)
    segment = dict(config.get("segment", {}))
    mail_section = dict(segment.get("MAIL", {}))
    mail_section.update(config.get("mail_tone", {}))
    segment["MAIL"] = mail_section

    if segment:
        for section, section_vals in segment.items():
            lines.append("")
            lines.append(f"[{section}]")
            for key, val in section_vals.items():
                lines.append(f"{key} = {val}")
    
    lines.append("")
    lines.append("# --- SAJTER (3_sajt) ---")
    
    # Sajt config
    if "sajt" in config:
        for key, val in config["sajt"].items():
            lines.append(f"{key} = {val}")
    
    return "\n".join(lines)


# =============================================================================
# GUI KOMPONENTER
# =============================================================================


class Tooltip:
    """Tooltip med snygg design"""
    
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
    
    def show(self, event=None):
        if self.tooltip_window:
            return
        
        x = self.widget.winfo_rootx() + 30
        y = self.widget.winfo_rooty() + 20
        
        self.tooltip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        try:
            tw.configure(fg_color=COLORS["bg_main"])
        except Exception:
            pass
        
        # Tooltip frame
        frame = ctk.CTkFrame(tw, corner_radius=10, fg_color=COLORS["bg_elevated"],
                             border_width=1, border_color=COLORS["border_focus"])
        frame.pack()
        
        # Header
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 5))
        
        icon_label = ctk.CTkLabel(header, text="💡", font=ctk.CTkFont(size=14))
        icon_label.pack(side="left", padx=(0, 6))
        
        title = ctk.CTkLabel(header, text="Tips", font=FONTS.get("label", ctk.CTkFont(size=14, weight="bold")),
                             text_color=COLORS["accent_light"])
        title.pack(side="left")
        
        # Separator
        sep = ctk.CTkFrame(frame, height=1, fg_color=COLORS["border"])
        sep.pack(fill="x", padx=12, pady=4)
        
        # Text
        label = ctk.CTkLabel(frame, text=self.text, wraplength=320,
                              font=FONTS.get("body_small", ctk.CTkFont(size=12)),
                              text_color=COLORS["text"],
                              justify="left")
        label.pack(padx=12, pady=12)
    
    def hide(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class SettingRow(ctk.CTkFrame):
    """Inställningsrad med tooltip och beskrivning"""
    
    def __init__(self, parent, key: str, definition: Dict[str, Any], current_value: Any = None):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        
        self.key = key
        self.definition = definition
        self.setting_type = definition.get("type", "entry")
        
        value = current_value if current_value is not None else definition.get("default")
        
        # Container
        row_container = ctk.CTkFrame(self, fg_color="transparent")
        row_container.pack(fill="x", padx=0, pady=SPACING["sm"])
        
        # Vänster: Label och beskrivning
        left_frame = ctk.CTkFrame(row_container, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xl"]))
        
        # Label med info-ikon
        label_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        label_frame.pack(anchor="w", pady=(0, SPACING["xs"]))
        
        label = ctk.CTkLabel(label_frame, text=definition.get("label", key),
                              font=FONTS.get("label", ctk.CTkFont(size=14, weight="bold")),
                              text_color=COLORS["text_bright"])
        label.pack(side="left")
        
        # Badge för "Används i kod" status
        used_in_code = definition.get("used_in_code", True)
        if not used_in_code:
            badge = ctk.CTkLabel(label_frame, text="⚠ Ej aktiv", 
                                 font=FONTS.get("caption", ctk.CTkFont(size=11)),
                                 text_color=COLORS["warning"],
                                 fg_color=COLORS["bg_elevated"],
                                 corner_radius=4,
                                 padx=6, pady=2)
            badge.pack(side="left", padx=(SPACING["sm"], 0))
        else:
            badge = ctk.CTkLabel(label_frame, text="✓ Aktiv", 
                                 font=FONTS.get("caption", ctk.CTkFont(size=11)),
                                 text_color=COLORS["success"],
                                 fg_color=COLORS["bg_elevated"],
                                 corner_radius=4,
                                 padx=6, pady=2)
            badge.pack(side="left", padx=(SPACING["sm"], 0))
        
        # Info-knapp med tooltip (frågetecken)
        if definition.get("tooltip"):
            info_btn = ctk.CTkLabel(label_frame, text="ⓘ", 
                                     font=ctk.CTkFont(size=13, weight="normal"),
                                     text_color=COLORS["accent_light"],
                                     cursor="hand2")
            info_btn.pack(side="left", padx=(SPACING["sm"], 0))
            Tooltip(info_btn, definition["tooltip"])
        
        # Beskrivning
        if definition.get("description"):
            desc = ctk.CTkLabel(left_frame, text=definition["description"],
                                 font=FONTS.get("body_small", ctk.CTkFont(size=12)),
                                 text_color=COLORS["text_dim"],
                                 wraplength=450, anchor="w", justify="left")
            desc.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Höger: Input
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
                                       font=FONTS.get("body", ctk.CTkFont(size=14)),
                                       text_color=COLORS["text_bright"])
            self.input.pack()
        
        elif self.setting_type == "decimal":
            self.var = ctk.StringVar(value=str(float(value) if value else 0.0))
            self.input = ctk.CTkEntry(right_frame, textvariable=self.var, width=110, height=36,
                                       fg_color=COLORS["bg_input"],
                                       border_color=COLORS["border"],
                                       border_width=1,
                                       corner_radius=8,
                                       font=FONTS.get("body", ctk.CTkFont(size=14)),
                                       text_color=COLORS["text_bright"])
            self.input.pack()
        
        elif self.setting_type == "slider":
            min_val = definition.get("min", 0)
            max_val = definition.get("max", 100)
            
            slider_container = ctk.CTkFrame(right_frame, fg_color="transparent")
            slider_container.pack()
            
            self.var = ctk.IntVar(value=int(value) if value else min_val)
            
            # Value display
            value_frame = ctk.CTkFrame(slider_container, fg_color=COLORS["bg_elevated"],
                                       corner_radius=8, width=50, height=36)
            value_frame.pack(side="right", padx=(SPACING["md"], 0))
            value_frame.pack_propagate(False)
            
            self.value_label = ctk.CTkLabel(value_frame, textvariable=self.var,
                                             font=FONTS.get("label", ctk.CTkFont(size=14, weight="bold")),
                                             text_color=COLORS["accent"])
            self.value_label.pack(expand=True)
            
            # Slider
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
                                            font=FONTS.get("body", ctk.CTkFont(size=14)),
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
                                       font=FONTS.get("body", ctk.CTkFont(size=14)),
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
    """Sektionskort med professionell design"""
    
    def __init__(self, parent, section_key: str, section_def: Dict[str, Any], 
                 current_values: Dict[str, Any] = None, show_advanced: bool = False):
        super().__init__(parent, corner_radius=16, fg_color=COLORS["bg_card"],
                         border_width=1, border_color=COLORS["border_light"])
        
        self.section_key = section_key
        self.settings: Dict[str, SettingRow] = {}
        
        if current_values is None:
            current_values = {}
        
        # Header
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
                                    font=FONTS.get("h2", ctk.CTkFont(size=20, weight="bold")),
                                    text_color=COLORS["text_bright"])
        title_label.pack(anchor="w")
        
        # Beskrivning
        if section_def.get("_description"):
            desc_label = ctk.CTkLabel(title_frame, text=section_def["_description"],
                                       font=FONTS.get("body_small", ctk.CTkFont(size=12)),
                                       text_color=COLORS["text_dim"])
            desc_label.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Separator
        sep_container = ctk.CTkFrame(self, fg_color="transparent")
        sep_container.pack(fill="x", padx=SPACING["xl"], pady=SPACING["sm"])
        
        sep = ctk.CTkFrame(sep_container, height=2, fg_color=COLORS["border"])
        sep.pack(fill="x")
        
        # Inställningar
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["md"], SPACING["xl"]))
        
        settings_added = 0
        for idx, (key, definition) in enumerate(section_def.items()):
            if key.startswith("_"):
                continue
            
            # Filtrera avancerade inställningar
            is_advanced = definition.get("advanced", False)
            if is_advanced and not show_advanced:
                continue
            
            current_val = current_values.get(key)
            row = SettingRow(content, key, definition, current_val)
            row.pack(fill="x", pady=SPACING["md"] if settings_added > 0 else 0)
            self.settings[key] = row
            settings_added += 1
        
        if settings_added == 0:
            empty_label = ctk.CTkLabel(content, text="Inga inställningar i denna kategori",
                                        font=FONTS.get("body_small", ctk.CTkFont(size=12)),
                                        text_color=COLORS["text_muted"])
            empty_label.pack(pady=SPACING["lg"])
    
    def get_values(self) -> Dict[str, Any]:
        return {key: row.get() for key, row in self.settings.items()}


# =============================================================================
# HUVUDAPPLIKATION
# =============================================================================


class MacConfigGUI(ctk.CTk):
    """Huvudfönstret - Mac Edition"""
    
    def __init__(self):
        super().__init__()
        
        # Initiera fonts
        global FONTS
        if not FONTS:
            FONTS = {
                "h1": ctk.CTkFont(size=28, weight="bold"),
                "h2": ctk.CTkFont(size=20, weight="bold"),
                "h3": ctk.CTkFont(size=16, weight="bold"),
                "body": ctk.CTkFont(size=14),
                "body_small": ctk.CTkFont(size=12),
                "label": ctk.CTkFont(size=14, weight="bold"),
                "button": ctk.CTkFont(size=14, weight="bold"),
                "caption": ctk.CTkFont(size=11),
            }
        
        self.title("🎯 PANG Konfiguration - Mac Edition")
        
        # Anpassa storlek
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

        # Ladda config
        self.config_data, self.config_source = load_config(
            self.gui_settings.get("dropbox_local_path")
        )
        
        self.sections: Dict[str, SectionCard] = {}
        
        self.setup_ui()
    
    def setup_ui(self):
        """Bygg gränssnittet"""
        # Huvudcontainer
        self.main_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_main"])
        self.main_frame.pack(fill="both", expand=True)
        
        # ===== HEADER =====
        header = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_elevated"], height=100,
                              corner_radius=0, border_width=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_content = ctk.CTkFrame(header, fg_color="transparent")
        header_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["lg"])
        
        # Titel-sektion
        title_frame = ctk.CTkFrame(header_content, fg_color="transparent")
        title_frame.pack(side="left", fill="y")
        
        # Logo
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
        
        subtitle = ctk.CTkLabel(text_frame, text="Mac Edition - Synkroniserad med Dropbox",
                                 font=FONTS["body_small"],
                                 text_color=COLORS["text_dim"])
        subtitle.pack(anchor="w", pady=(SPACING["xs"], 0))
        
        # Knappar
        btn_frame = ctk.CTkFrame(header_content, fg_color="transparent")
        btn_frame.pack(side="right", fill="y")
        
        # Ladda om från Dropbox
        self.reload_btn = ctk.CTkButton(btn_frame, text="🔄 Ladda om", width=110, height=44,
                                         command=self.reload_config,
                                         fg_color=COLORS["secondary"],
                                         hover_color=COLORS["secondary_hover"],
                                         corner_radius=10,
                                         font=FONTS["button"],
                                         text_color="#ffffff")
        self.reload_btn.pack(side="left", padx=SPACING["xs"])
        
        # Återställ till standard
        self.reset_btn = ctk.CTkButton(btn_frame, text="⏮️ Återställ", width=110, height=44,
                                        command=self.reset_to_defaults,
                                        fg_color=COLORS["error"],
                                        hover_color=COLORS["error_hover"],
                                        corner_radius=10,
                                        font=FONTS["button"],
                                        text_color="#ffffff")
        self.reset_btn.pack(side="left", padx=SPACING["xs"])
        
        # Spara lokalt-knapp (grön)
        self.save_btn = ctk.CTkButton(btn_frame, text="💾 Spara", width=90, height=50,
                                       command=self.save_config,
                                       fg_color=COLORS["success"],
                                       hover_color=COLORS["success_hover"],
                                       corner_radius=10,
                                       font=FONTS["button"],
                                       text_color="#ffffff")
        self.save_btn.pack(side="left", padx=SPACING["xs"])
        
        # Spara till Dropbox-mapp (blå)
        self.save_dropbox_btn = ctk.CTkButton(btn_frame, text="☁️ Dropbox", width=90, height=50,
                                               command=self.save_to_dropbox,
                                               fg_color=COLORS["accent"],
                                               hover_color=COLORS["accent_hover"],
                                               corner_radius=10,
                                               font=FONTS["button"],
                                               text_color="#ffffff")
        self.save_dropbox_btn.pack(side="left", padx=SPACING["xs"])
        
        # Spara via länk-knapp (orange)
        self.save_link_btn = ctk.CTkButton(btn_frame, text="🔗 Via länk", width=90, height=50,
                                            command=self.save_via_link,
                                            fg_color=COLORS["warning"],
                                            hover_color=COLORS["warning_hover"],
                                            corner_radius=10,
                                            font=FONTS["button"],
                                            text_color="#ffffff")
        self.save_link_btn.pack(side="left", padx=SPACING["xs"])
        
        # ===== INSTÄLLNINGAR FÖR SPARNING =====
        save_settings_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_card"], height=190)
        save_settings_frame.pack(fill="x")
        save_settings_frame.pack_propagate(False)
        
        save_settings_content = ctk.CTkFrame(save_settings_frame, fg_color="transparent")
        save_settings_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["md"])
        
        # Titel för sparinställningar
        save_title = ctk.CTkLabel(save_settings_content, text="📁 Sparinställningar",
                                   font=FONTS["h3"], text_color=COLORS["accent_light"])
        save_title.pack(anchor="w", pady=(0, SPACING["sm"]))
        
        # Rad 1: Lokal sökväg
        row1 = ctk.CTkFrame(save_settings_content, fg_color="transparent")
        row1.pack(fill="x", pady=SPACING["xs"])
        
        path_label = ctk.CTkLabel(row1, text="💾 Lokal sökväg:",
                                  font=FONTS["body"], text_color=COLORS["text"], 
                                  width=130, anchor="w")
        path_label.pack(side="left")
        
        self.save_path_entry = ctk.CTkEntry(row1, width=400, height=32,
                                             placeholder_text="/Users/.../config.txt",
                                             fg_color=COLORS["bg_input"],
                                             border_color=COLORS["border"],
                                             border_width=1, corner_radius=8,
                                             font=FONTS["body_small"],
                                             text_color=COLORS["text_bright"])
        self.save_path_entry.insert(0, self.gui_settings.get("save_path", str(MAC_GUI_DIR)))
        self.save_path_entry.pack(side="left", padx=SPACING["sm"])
        
        browse_btn = ctk.CTkButton(row1, text="📂 Bläddra", width=90, height=32,
                                    command=self.browse_save_path,
                                    fg_color=COLORS["bg_elevated"],
                                    hover_color=COLORS["bg_card_hover"],
                                    corner_radius=8, font=FONTS["caption"],
                                    text_color=COLORS["text"])
        browse_btn.pack(side="left", padx=SPACING["xs"])
        
        # Rad 2: Dropbox-mapp (lokal)
        row2 = ctk.CTkFrame(save_settings_content, fg_color="transparent")
        row2.pack(fill="x", pady=SPACING["xs"])
        
        dropbox_path_label = ctk.CTkLabel(row2, text="☁️ Dropbox-mapp:",
                                          font=FONTS["body"], text_color=COLORS["text"],
                                          width=130, anchor="w")
        dropbox_path_label.pack(side="left")
        
        self.dropbox_path_entry = ctk.CTkEntry(row2, width=400, height=32,
                                                placeholder_text="/Users/.../Dropbox",
                                                fg_color=COLORS["bg_input"],
                                                border_color=COLORS["border"],
                                                border_width=1, corner_radius=8,
                                                font=FONTS["body_small"],
                                                text_color=COLORS["text_bright"])
        dropbox_saved = self.gui_settings.get("dropbox_local_path", "")
        if not dropbox_saved:
            # Auto-detect Dropbox
            auto_dropbox = find_dropbox_folder()
            if auto_dropbox:
                dropbox_saved = str(auto_dropbox)
        self.dropbox_path_entry.insert(0, dropbox_saved)
        self.dropbox_path_entry.pack(side="left", padx=SPACING["sm"])
        
        browse_dropbox_btn = ctk.CTkButton(row2, text="📂 Bläddra", width=90, height=32,
                                            command=self.browse_dropbox_path,
                                            fg_color=COLORS["bg_elevated"],
                                            hover_color=COLORS["bg_card_hover"],
                                            corner_radius=8, font=FONTS["caption"],
                                            text_color=COLORS["text"])
        browse_dropbox_btn.pack(side="left", padx=SPACING["xs"])
        
        auto_detect_btn = ctk.CTkButton(row2, text="🔍 Auto", width=70, height=32,
                                         command=self.auto_detect_dropbox,
                                         fg_color=COLORS["bg_elevated"],
                                         hover_color=COLORS["bg_card_hover"],
                                         corner_radius=8, font=FONTS["caption"],
                                         text_color=COLORS["text"])
        auto_detect_btn.pack(side="left", padx=SPACING["xs"])
        
        # Rad 3: Dropbox-länk (för "Spara via länk")
        row3 = ctk.CTkFrame(save_settings_content, fg_color="transparent")
        row3.pack(fill="x", pady=SPACING["xs"])
        
        link_label = ctk.CTkLabel(row3, text="🔗 Dropbox-länk:",
                                  font=FONTS["body"], text_color=COLORS["text"],
                                  width=130, anchor="w")
        link_label.pack(side="left")
        
        self.dropbox_link_entry = ctk.CTkEntry(row3, width=450, height=32,
                                                placeholder_text="https://www.dropbox.com/scl/fi/...",
                                                fg_color=COLORS["bg_input"],
                                                border_color=COLORS["border"],
                                                border_width=1, corner_radius=8,
                                                font=FONTS["body_small"],
                                                text_color=COLORS["text_bright"])
        self.dropbox_link_entry.insert(0, self.gui_settings.get("dropbox_link", ""))
        self.dropbox_link_entry.pack(side="left", padx=SPACING["sm"])
        
        link_info = ctk.CTkLabel(row3, text="(För delning)",
                                 font=FONTS["caption"], text_color=COLORS["text_muted"])
        link_info.pack(side="left")
        
        # Rad 4: Email
        row4 = ctk.CTkFrame(save_settings_content, fg_color="transparent")
        row4.pack(fill="x", pady=SPACING["xs"])
        
        email_label = ctk.CTkLabel(row4, text="📧 Email:",
                                   font=FONTS["body"], text_color=COLORS["text"],
                                   width=130, anchor="w")
        email_label.pack(side="left")
        
        self.email_entry = ctk.CTkEntry(row4, width=300, height=32,
                                         placeholder_text="din@email.com",
                                         fg_color=COLORS["bg_input"],
                                         border_color=COLORS["border"],
                                         border_width=1, corner_radius=8,
                                         font=FONTS["body_small"],
                                         text_color=COLORS["text_bright"])
        self.email_entry.insert(0, self.gui_settings.get("email", ""))
        self.email_entry.pack(side="left", padx=SPACING["sm"])
        
        email_info = ctk.CTkLabel(row4, text="(Inkluderas i sparad config-fil)",
                                  font=FONTS["caption"], text_color=COLORS["text_muted"])
        email_info.pack(side="left")
        
        # ===== STATUS BAR =====
        status_bar = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg_elevated"], height=36)
        status_bar.pack(fill="x")
        status_bar.pack_propagate(False)
        
        status_content = ctk.CTkFrame(status_bar, fg_color="transparent")
        status_content.pack(fill="both", expand=True, padx=SPACING["xxl"], pady=SPACING["xs"])
        
        self.status_label = ctk.CTkLabel(status_content, 
                                          text=f"📂 Källa: {self.config_source}",
                                          font=FONTS["body_small"],
                                          text_color=COLORS["text_dim"])
        self.status_label.pack(side="left")
        
        # ===== TABVIEW =====
        self.tabview = ctk.CTkTabview(self.main_frame, fg_color=COLORS["bg_main"],
                                       segmented_button_fg_color=COLORS["bg_card"],
                                       segmented_button_selected_color=COLORS["accent"],
                                       segmented_button_selected_hover_color=COLORS["accent_hover"],
                                       segmented_button_unselected_color=COLORS["bg_card"],
                                       segmented_button_unselected_hover_color=COLORS["bg_card_hover"],
                                       text_color=COLORS["text"],
                                       corner_radius=12)
        self.tabview.pack(fill="both", expand=True, padx=SPACING["lg"], pady=SPACING["md"])
        
        # Skapa flikar
        self.tab_scraping = self.tabview.add("🔍 Skrapning")
        self.tab_research = self.tabview.add("🤖 AI-Research")
        self.tab_mail = self.tabview.add("✉️ Mail")
        self.tab_sites = self.tabview.add("🏗️ Sajter")
        self.tab_advanced = self.tabview.add("⚙️ Avancerat")
        
        # Bygg innehåll
        self.setup_scraping_tab()
        self.setup_research_tab()
        self.setup_mail_tab()
        self.setup_sites_tab()
        self.setup_advanced_tab()
    
    def create_scroll_frame(self, parent) -> ctk.CTkScrollableFrame:
        """Skapa en scrollbar frame"""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        return scroll
    
    def get_current_value(self, section: str, key: str) -> Any:
        """Hämta aktuellt värde för en inställning"""
        # Mappa sektion till config-struktur
        if section == "scraping":
            return self.config_data.get("poit", {}).get(key)
        elif section == "pipeline":
            return self.config_data.get("segment", {}).get("PIPELINE", {}).get(key)
        elif section == "research":
            return self.config_data.get("segment", {}).get("RESEARCH", {}).get(key)
        elif section == "domain":
            return self.config_data.get("segment", {}).get("DOMAIN", {}).get(key)
        elif section == "mail":
            return self.config_data.get("segment", {}).get("MAIL", {}).get(key)
        elif section == "mail_tone":
            return self.config_data.get("mail_tone", {}).get(key)
        elif section in ["evaluation", "sites", "audit"]:
            return self.config_data.get("sajt", {}).get(key)
        return None
    
    def create_section_in_scroll(self, scroll: ctk.CTkScrollableFrame, section_key: str, 
                                  show_advanced: bool = False):
        """Skapa en sektion i scroll-frame"""
        section_def = SETTINGS_DEFINITIONS.get(section_key, {})
        
        # Samla aktuella värden
        current_values = {}
        for key in section_def:
            if not key.startswith("_"):
                val = self.get_current_value(section_key, key)
                if val is not None:
                    current_values[key] = val
        
        card = SectionCard(scroll, section_key, section_def, current_values, show_advanced)
        card.pack(fill="x", pady=SPACING["md"])
        self.sections[section_key] = card
    
    def setup_scraping_tab(self):
        scroll = self.create_scroll_frame(self.tab_scraping)
        self.create_section_in_scroll(scroll, "scraping")
        self.create_section_in_scroll(scroll, "pipeline")
    
    def setup_research_tab(self):
        scroll = self.create_scroll_frame(self.tab_research)
        self.create_section_in_scroll(scroll, "research")
        self.create_section_in_scroll(scroll, "domain")
    
    def setup_mail_tab(self):
        scroll = self.create_scroll_frame(self.tab_mail)
        self.create_section_in_scroll(scroll, "mail")
        self.create_section_in_scroll(scroll, "mail_tone")
    
    def setup_sites_tab(self):
        scroll = self.create_scroll_frame(self.tab_sites)
        self.create_section_in_scroll(scroll, "evaluation")
        self.create_section_in_scroll(scroll, "sites")
        self.create_section_in_scroll(scroll, "audit")
    
    def setup_advanced_tab(self):
        scroll = self.create_scroll_frame(self.tab_advanced)
        
        # Visa alla sektioner med avancerade inställningar
        for section_key in SETTINGS_DEFINITIONS:
            section_def = SETTINGS_DEFINITIONS[section_key]
            has_advanced = any(
                definition.get("advanced", False) 
                for key, definition in section_def.items() 
                if not key.startswith("_")
            )
            if has_advanced:
                self.create_section_in_scroll(scroll, section_key, show_advanced=True)
    
    def collect_all_values(self) -> Dict[str, Any]:
        """Samla alla värden från GUI"""
        config = {
            "poit": {},
            "segment": {"PIPELINE": {}, "RESEARCH": {}, "DOMAIN": {}, "MAIL": {}},
            "mail_tone": {},
            "sajt": {}
        }
        
        for section_key, card in self.sections.items():
            values = card.get_values()
            
            if section_key == "scraping":
                config["poit"].update(values)
            elif section_key == "pipeline":
                config["segment"]["PIPELINE"].update(values)
            elif section_key == "research":
                config["segment"]["RESEARCH"].update(values)
            elif section_key == "domain":
                config["segment"]["DOMAIN"].update(values)
            elif section_key == "mail":
                config["segment"]["MAIL"].update(values)
            elif section_key == "mail_tone":
                config["mail_tone"].update(values)
            elif section_key in ["evaluation", "sites", "audit"]:
                config["sajt"].update(values)
        
        return config
    
    def reload_config(self):
        """Ladda om config från Dropbox/lokal"""
        dropbox_path = ""
        if hasattr(self, "dropbox_path_entry"):
            dropbox_path = self.dropbox_path_entry.get().strip()
        if not dropbox_path:
            dropbox_path = self.gui_settings.get("dropbox_local_path", "")

        self.config_data, self.config_source = load_config(dropbox_path or None)
        
        # Uppdatera status
        self.status_label.configure(text=f"📂 Källa: {self.config_source}")
        
        # Återskapa alla sektioner
        self.sections.clear()
        
        # Rensa och återbygg alla tabs
        for tab in [self.tab_scraping, self.tab_research, self.tab_mail, 
                    self.tab_sites, self.tab_advanced]:
            for widget in tab.winfo_children():
                widget.destroy()
        
        self.setup_scraping_tab()
        self.setup_research_tab()
        self.setup_mail_tab()
        self.setup_sites_tab()
        self.setup_advanced_tab()
        
        messagebox.showinfo("Laddad!", f"Config laddad från:\n{self.config_source}")
    
    def browse_save_path(self):
        """Öppna filväljare för lokal sökväg"""
        initial_dir = self.save_path_entry.get() or str(MAC_GUI_DIR)
        if not Path(initial_dir).exists():
            initial_dir = str(Path.home())
        
        path = filedialog.askdirectory(initialdir=initial_dir, title="Välj mapp för lokal config")
        if path:
            self.save_path_entry.delete(0, "end")
            self.save_path_entry.insert(0, path)
            self.save_settings()
    
    def browse_dropbox_path(self):
        """Öppna filväljare för Dropbox-mapp"""
        initial_dir = self.dropbox_path_entry.get() or str(Path.home())
        if not Path(initial_dir).exists():
            initial_dir = str(Path.home())
        
        path = filedialog.askdirectory(initialdir=initial_dir, title="Välj Dropbox-mapp")
        if path:
            self.dropbox_path_entry.delete(0, "end")
            self.dropbox_path_entry.insert(0, path)
            self.save_settings()
    
    def auto_detect_dropbox(self):
        """Auto-detektera Dropbox-mapp (prioriterar leads-undermappen)"""
        dropbox = find_dropbox_folder()
        if dropbox:
            # Prioritera leads-undermappen om den finns
            leads_subdir = dropbox / "leads"
            if leads_subdir.exists() and leads_subdir.is_dir():
                dropbox = leads_subdir
            
            self.dropbox_path_entry.delete(0, "end")
            self.dropbox_path_entry.insert(0, str(dropbox))
            self.save_settings()
            self.status_label.configure(text=f"✅ Hittade Dropbox: {dropbox}")
        else:
            messagebox.showwarning("Ej hittad", "Kunde inte hitta Dropbox-mapp automatiskt.\nAnge sökvägen manuellt.")
    
    def save_settings(self):
        """Spara GUI-inställningar"""
        settings = {
            "save_path": self.save_path_entry.get(),
            "dropbox_local_path": self.dropbox_path_entry.get(),
            "dropbox_link": self.dropbox_link_entry.get(),
            "dropbox_filename": DROPBOX_CANONICAL_FILENAME,
            "email": self.email_entry.get(),
            "last_source": self.config_source
        }
        save_gui_settings(settings)
    
    def save_config(self):
        """Spara config till lokal sökväg"""
        config = self.collect_all_values()
        email = self.email_entry.get()
        save_path = self.save_path_entry.get()
        
        # Spara settings först
        self.save_settings()
        
        # Bestäm filväg
        if save_path:
            save_dir = Path(save_path)
            if save_dir.is_dir():
                target_file = save_dir / "pang_config.txt"
            else:
                target_file = save_dir
        else:
            target_file = LOCAL_CONFIG
        
        try:
            # Skapa mappen om den inte finns
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Formatera och spara
            content = format_config_for_export(config, email)
            target_file.write_text(content, encoding="utf-8")
            
            # Spara också som JSON för snabb inläsning
            json_file = target_file.parent / "local_config.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            self.status_label.configure(text=f"✅ Sparad: {target_file.name}")
            messagebox.showinfo("Sparad!", f"Config sparad till:\n{target_file}")
            
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara:\n{e}")
    
    def save_to_dropbox(self):
        """Spara config till lokal Dropbox-mapp (synkas automatiskt)"""
        config = self.collect_all_values()
        email = self.email_entry.get()
        dropbox_path = self.dropbox_path_entry.get()
        
        # Spara settings först
        self.save_settings()
        
        if not dropbox_path:
            messagebox.showwarning("Ingen sökväg", "Ange Dropbox-mapp eller tryck 'Auto' för att hitta den.")
            return
        
        dropbox_dir = Path(dropbox_path)
        if not dropbox_dir.exists():
            messagebox.showerror("Finns ej", f"Mappen finns inte:\n{dropbox_path}")
            return
        
        # Filnamn i Dropbox
        target_file = dropbox_dir / DROPBOX_CANONICAL_FILENAME
        
        try:
            # Formatera och spara
            content = format_env_config_for_export(config, email)
            target_file.write_text(content, encoding="utf-8")
            
            self.status_label.configure(text=f"☁️ Sparad till Dropbox: {target_file.name}")
            messagebox.showinfo("Dropbox!", f"Config sparad till Dropbox-mapp:\n{target_file}\n\nFilen synkas nu automatiskt med molnet!")
            
        except PermissionError:
            messagebox.showerror("Behörighet", "Ingen skrivbehörighet till Dropbox-mappen.\nKontrollera att Dropbox körs.")
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara till Dropbox:\n{e}")
    
    def save_via_link(self):
        """
        Spara config via Dropbox-länk.
        
        OBS: Dropbox delade länkar är read-only - man kan inte skriva till dem direkt.
        Istället söker vi efter filen lokalt i Dropbox-mappen.
        """
        config = self.collect_all_values()
        email = self.email_entry.get()
        dropbox_link = self.dropbox_link_entry.get()
        dropbox_path = self.dropbox_path_entry.get()
        
        # Spara settings först
        self.save_settings()
        
        if not dropbox_link and not dropbox_path:
            messagebox.showwarning("Ingen länk", 
                "Ange antingen en Dropbox-länk eller en lokal Dropbox-mapp.\n\n"
                "Tips: Om du delar en fil via Dropbox-länk måste du ha filen\n"
                "synkad lokalt för att kunna skriva till den.")
            return
        
        # Försök hitta filen lokalt
        target_file = None
        filename = DROPBOX_CANONICAL_FILENAME
        
        # Sök efter filen i Dropbox-mappen
        if dropbox_path:
            dropbox_dir = Path(dropbox_path)
            if dropbox_dir.exists():
                # Direkt i mappen
                direct = dropbox_dir / filename
                if direct.exists():
                    target_file = direct
                else:
                    # Sök rekursivt
                    try:
                        for found in dropbox_dir.rglob(filename):
                            if found.is_file():
                                target_file = found
                                break
                    except PermissionError:
                        pass
        
        # Om inte hittat, auto-detektera Dropbox
        if not target_file:
            auto_dropbox = find_dropbox_folder()
            if auto_dropbox:
                try:
                    for found in auto_dropbox.rglob(filename):
                        if found.is_file():
                            target_file = found
                            break
                except PermissionError:
                    pass
        
        if not target_file:
            # Skapa filen i Dropbox-mappen
            if dropbox_path:
                dropbox_dir = Path(dropbox_path)
                if dropbox_dir.exists():
                    target_file = dropbox_dir / filename
                    messagebox.showinfo("Skapar fil", 
                        f"Filen '{filename}' hittades inte.\n"
                        f"En ny fil skapas i:\n{dropbox_dir}")
                else:
                    messagebox.showerror("Fel", 
                        f"Dropbox-mappen finns inte:\n{dropbox_path}\n\n"
                        "Ange korrekt sökväg eller tryck 'Auto' för att hitta den.")
                    return
            else:
                messagebox.showerror("Ej hittad", 
                    f"Kunde inte hitta filen '{filename}' i Dropbox.\n\n"
                    "Kontrollera att:\n"
                    "1. Du har Dropbox installerat\n"
                    "2. Filen synkas till din dator\n"
                    "3. Du har angett rätt Dropbox-mapp")
                return
        
        try:
            # Formatera och spara - env-format
            content = format_env_config_for_export(config, email)
            target_file.write_text(content, encoding="utf-8")
            
            self.status_label.configure(text=f"🔗 Sparad via länk: {target_file.name}")
            messagebox.showinfo("Sparat via länk!", 
                f"Config sparad till:\n{target_file}\n\n"
                "Filen synkas automatiskt via Dropbox och blir\n"
                "tillgänglig för alla som delar länken!")
            
        except PermissionError:
            messagebox.showerror("Behörighet", 
                "Ingen skrivbehörighet till filen.\n"
                "Kontrollera att Dropbox körs och att filen inte är låst.")
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte spara:\n{e}")
    
    def reset_to_defaults(self):
        """Återställ till standardvärden"""
        if not messagebox.askyesno("Bekräfta", "Vill du återställa alla inställningar till standardvärden?"):
            return
        
        self.config_data = load_default_config_file()
        self.config_source = "Standardvärden (återställd)"
        
        # Uppdatera UI
        self.reload_config()
        
        messagebox.showinfo("Återställd!", "Alla inställningar återställda till standardvärden.")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    app = MacConfigGUI()
    app.mainloop()
