#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_from_segment.py - Kör pipeline från segmentering (hoppar över scraping)

Användning:
    python main_from_segment.py           # Kör från ALLA.py och framåt
    python main_from_segment.py 10        # Kör med master-nummer 10
    python main_from_segment.py -20251215 # Kör med specifikt datum
    python main_from_segment.py --skip-process  # Hoppa över process_raw_data.py

Kör i sekvens (hoppar över steg 1-3):
4. Kör process_raw_data.py (skapar CSV/DB från JSON) - kan hoppas över med --skip-process
5. Kör segmentering pipeline (2_segment_info/ALLA.py)
6. Kör evaluation och generera hemsidor (3_sajt/)
7. Kopiera till Dropbox (9_dropbox/)
8. Bearbeta styrelsedata (10_jocke/)
"""

import asyncio
import configparser
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from utils.erase import run_full_cleanup

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Ladda .env från projektroten
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[INFO] Laddade .env från {env_path}")
except ImportError:
    pass

POIT_DIR = PROJECT_ROOT / "1_poit"
AUTOMATION_DIR = POIT_DIR / "automation"
SEGMENT_DIR = PROJECT_ROOT / "2_segment_info"
SAJT_DIR = PROJECT_ROOT / "3_sajt"
DROPBOX_DIR = PROJECT_ROOT / "9_dropbox"

# Logging paths
LOG_DIR = PROJECT_ROOT / "logs"
STEP_LOG_DIR = LOG_DIR / "steps"
RUN_LOG_FILE: Optional[Path] = None
RUN_TS: str = ""


def ensure_log_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STEP_LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_run_logging() -> Path:
    global RUN_LOG_FILE, RUN_TS
    RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
    ensure_log_dirs()
    RUN_LOG_FILE = LOG_DIR / f"main_from_segment_{RUN_TS}.log"
    RUN_LOG_FILE.write_text("", encoding="utf-8")
    return RUN_LOG_FILE


def append_run_log(line: str):
    if RUN_LOG_FILE is None:
        return
    try:
        with RUN_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_info(msg: str):
    line = f"[INFO {ts()}] {msg}"
    print(line)
    append_run_log(line)


def log_error(msg: str):
    line = f"[ERROR {ts()}] {msg}"
    print(line)
    append_run_log(line)


def log_warn(msg: str):
    line = f"[WARN {ts()}] {msg}"
    print(line)
    append_run_log(line)


def prompt_yes_no(question: str, default: bool = False) -> bool:
    """Simple interactive yes/no prompt."""
    if not sys.stdin.isatty():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    while True:
        ans = input(question + suffix).strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes", "j", "ja"):
            return True
        if ans in ("n", "no", "nej"):
            return False
        print("Svara med y/yes eller n/no.")


def prompt_int(question: str, default: Optional[int] = None) -> Optional[int]:
    """Simple interactive integer prompt."""
    if not sys.stdin.isatty():
        return default
    suffix = f" [{default}]" if default is not None else ""
    ans = input(f"{question}{suffix}: ").strip()
    if not ans:
        return default
    try:
        return int(ans)
    except ValueError:
        print("Ogiltigt tal, använder default.")
        return default


def run_script(
    step_name: str, script_path: Path, cwd: Path = None
) -> Tuple[int, float, Path, List[str]]:
    """Kör ett Python-skript med loggning till fil."""
    if cwd is None:
        cwd = script_path.parent

    ensure_log_dirs()
    step_log = STEP_LOG_DIR / f"{step_name}_{RUN_TS}.log"
    tail: List[str] = []

    target_date = os.environ.get("TARGET_DATE", "NOT_SET")
    log_info(f"Kör [{step_name}]: {script_path.name} (cwd={cwd}, TARGET_DATE={target_date})")
    start_time = time.time()

    try:
        env = os.environ.copy()
        with step_log.open("w", encoding="utf-8") as lf:
            lf.write(f"[INFO {ts()}] Running {script_path} (cwd={cwd})\n")
            lf.write(f"[INFO {ts()}] TARGET_DATE={target_date}\n")
            lf.flush()

            process = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            assert process.stdout is not None
            for line in process.stdout:
                clean = line.rstrip()
                print(clean)
                lf.write(clean + "\n")
                lf.flush()
                tail.append(clean)
                if len(tail) > 25:
                    tail.pop(0)

            result_code = process.wait()
            duration = time.time() - start_time
            lf.write(f"[INFO {ts()}] Exit code {result_code} after {duration:.1f}s\n")
            status = "OK" if result_code == 0 else f"FEL ({result_code})"
            log_info(f"Klar [{step_name}]: {status} ({duration:.1f}s) - logg: {step_log}")
            return result_code, duration, step_log, tail
    except Exception as e:
        duration = time.time() - start_time
        log_error(f"Körfel [{step_name}]: {e}")
        try:
            with step_log.open("a", encoding="utf-8") as lf:
                lf.write(f"[ERROR {ts()}] {e}\n")
        except Exception:
            pass
        return 1, duration, step_log, tail


def summarize_failure(step_name: str, exit_code: Any, log_path: Path, tail_lines: List[str]):
    log_error(f"Steg {step_name} misslyckades (exit {exit_code})")
    if tail_lines:
        log_error("Sista rader från loggen:")
        for line in tail_lines[-8:]:
            log_error(f"  {line}")
    log_error(f"Se loggfil: {log_path}")


def get_latest_date_dir(base_dir: Path) -> Optional[Path]:
    if not base_dir.exists():
        return None

    date_dirs = []
    for item in base_dir.iterdir():
        if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
            date_dirs.append(item)

    if not date_dirs:
        return None

    date_dirs.sort(key=lambda x: x.name)
    return date_dirs[-1]


def get_target_date_dir(base_dir: Path) -> Optional[Path]:
    if not base_dir.exists():
        return None

    target_date = os.environ.get("TARGET_DATE", "")
    target_path = base_dir / target_date if target_date else None

    if target_path and target_path.exists():
        log_info(f"[TARGET_DATE] Använder {target_path.name} i {base_dir.name}/")
        return target_path

    latest = get_latest_date_dir(base_dir)
    if latest:
        if target_date:
            log_warn(f"TARGET_DATE={target_date} ej funnen i {base_dir.name}/, använder senaste: {latest.name}")
        else:
            log_info(f"Använder senaste datummapp: {latest.name}")
        return latest

    return None


def load_sajt_config() -> Dict[str, Any]:
    """Läs config från 3_sajt/config_ny.txt."""
    config = {
        "evaluate": True,
        "threshold": 0.80,
        "max_sites": 30,
        "max_total_judgement_approvals": 0,
        "re_input_website_link": True,
        "audit_enabled": False,
        "audit_threshold": 0.60,
        "max_audits": 10,
        "re_input_audit": True,
    }
    
    config_path = SAJT_DIR / "config_ny.txt"
    if not config_path.exists():
        log_warn(f"Config-fil saknas: {config_path}")
        return config
    
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key in ("evaluate", "audit_enabled", "re_input_website_link", "re_input_audit"):
                    config[key] = value.lower() in ("y", "yes", "true", "1")
                elif key in ("threshold", "audit_threshold"):
                    config[key] = float(value)
                elif key in ("max_sites", "max_audits", "max_total_judgement_approvals"):
                    config[key] = int(value)
    except Exception as e:
        log_warn(f"Kunde inte läsa sajt-config: {e}")
    
    return config


async def run_company_evaluation(date_folder: Path) -> Tuple[int, int]:
    """Kör evaluation för alla företag i en datum-mapp."""
    try:
        sys.path.insert(0, str(SAJT_DIR))
        from evaluate_companies import evaluate_companies_in_folder  # type: ignore[import-not-found]

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            log_error("OPENAI_API_KEY saknas - hoppar över evaluation")
            return 0, 0

        log_info(f"Bedömer företag i {date_folder.name}...")
        results = await evaluate_companies_in_folder(
            date_folder, api_key, model="gpt-4o-mini", save_to_folders=True
        )

        worthy_count = sum(1 for r in results if r.get("should_get_site", False))
        total_evaluated = len(results)

        log_info(f"Evaluation klar: {total_evaluated} bedömda, {worthy_count} värda företag")
        return total_evaluated, worthy_count

    except ImportError as e:
        log_error(f"Kunde inte importera evaluate_companies: {e}")
        return 0, 0
    except Exception as e:
        log_error(f"Fel vid evaluation: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0


async def generate_sites_for_worthy_companies(date_folder: Path) -> Tuple[int, int]:
    """Generera hemsidor för värda företag (styrs av config)."""
    sajt_config = load_sajt_config()
    max_sites = sajt_config["max_sites"]
    threshold = sajt_config["threshold"]
    
    log_info(f"Site-inställningar: threshold={threshold:.0%}, max={max_sites}")
    
    try:
        sys.path.insert(0, str(SAJT_DIR / "all_the_scripts"))
        from batch_generate import generate_site_for_company  # type: ignore[import-not-found]

        sys.path.insert(0, str(SAJT_DIR))
        from evaluate_companies import find_company_folders, load_evaluation_from_folder  # type: ignore[import-not-found]

        all_companies = find_company_folders(date_folder, filter_worthy=False)

        worthy_companies = []
        for company_folder in all_companies:
            evaluation = load_evaluation_from_folder(company_folder)
            if not evaluation:
                continue
            if not evaluation.get("should_get_site", False):
                continue
            # Kolla threshold
            if evaluation.get("confidence", 0) < threshold:
                continue
            # Skippa om redan har preview
            if (company_folder / "preview_url.txt").exists():
                continue
            worthy_companies.append(company_folder)

        if not worthy_companies:
            log_warn("Inga värda företag hittades för site generation")
            return 0, 0

        # Begränsa till max_sites (0 = obegränsat)
        selected_companies = worthy_companies[:max_sites] if max_sites > 0 else worthy_companies

        log_info(f"Genererar hemsidor för {len(selected_companies)} av {len(worthy_companies)} kvalificerade företag")

        generated_count = 0
        for idx, company_folder in enumerate(selected_companies, 1):
            company_name = company_folder.name
            try:
                company_data_file = company_folder / "company_data.json"
                if company_data_file.exists():
                    data = json.loads(company_data_file.read_text(encoding="utf-8"))
                    company_name = data.get("company_name", company_folder.name)
            except (OSError, json.JSONDecodeError, KeyError):
                pass

            log_info(f"  [{idx}/{len(selected_companies)}] Genererar hemsida för: {company_name}...")

            try:
                result = await generate_site_for_company(
                    company_folder.name,
                    date_folder,
                    v0_api_key=None,
                    openai_key=None,
                    use_openai_enhancement=True,
                    use_images=True,
                    fetch_actual_costs=True,
                )

                preview_url = result.get("preview_url", "N/A")
                log_info(f"    ✅ Klart! Preview URL: {preview_url}")
                generated_count += 1

                if idx < len(selected_companies):
                    await asyncio.sleep(2)

            except Exception as e:
                log_error(f"    ❌ Fel vid generering: {e}")
                continue

        log_info(f"Site generation klar: {generated_count} hemsidor genererade")
        return len(worthy_companies), generated_count

    except ImportError as e:
        log_error(f"Kunde inte importera batch_generate: {e}")
        return 0, 0
    except Exception as e:
        log_error(f"Fel vid site generation: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0


async def run_audits_for_companies(date_folder: Path) -> Tuple[int, int]:
    """
    Kör audits för företag med verifierad domän och tillräcklig confidence.
    
    Audits analyserar företagets BEFINTLIGA hemsida och genererar:
    - audit_report.json - Detaljerad analys med scores
    - audit_report.pdf - Snygg PDF-rapport
    - company_analysis.json - Strukturerad företagsdata
    - company_profile.txt - Läsbar profil
    """
    sajt_config = load_sajt_config()
    
    if not sajt_config["audit_enabled"]:
        log_info("Audits är inaktiverade i config (audit_enabled = n)")
        return 0, 0
    
    threshold = sajt_config["audit_threshold"]
    max_antal = sajt_config["max_audits"]
    
    log_info(f"Audit-inställningar: threshold={threshold:.0%}, max={max_antal}")
    
    try:
        sys.path.insert(0, str(SAJT_DIR / "all_the_scripts"))
        from standalone_audit import run_audit_to_folder  # type: ignore[import-not-found]
        
        company_dirs = [d for d in date_folder.iterdir() if d.is_dir() and d.name.startswith("K")]
        
        qualified_companies = []
        
        for company_dir in company_dirs:
            company_data_file = company_dir / "company_data.json"
            if not company_data_file.exists():
                continue
            
            try:
                data = json.loads(company_data_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            
            domain_info = data.get("domain", {})
            domain_url = domain_info.get("guess", "")
            confidence = domain_info.get("confidence", 0)
            status = domain_info.get("status", "unknown")
            
            if not domain_url:
                continue
            if status not in ("verified", "ai_verified", "match"):
                continue
            if confidence < threshold:
                continue
            
            # Skippa om audit redan finns
            if (company_dir / "audit_report.json").exists():
                continue
            
            qualified_companies.append({
                "dir": company_dir,
                "domain": domain_url,
                "confidence": confidence,
                "company_name": data.get("company_name", company_dir.name),
            })
        
        if not qualified_companies:
            log_info("Inga företag kvalificerade för audit")
            return 0, 0
        
        to_audit = qualified_companies[:max_antal] if max_antal > 0 else qualified_companies
        
        log_info(f"Kör audits för {len(to_audit)} av {len(qualified_companies)} kvalificerade företag")
        
        audited_count = 0
        for idx, company in enumerate(to_audit, 1):
            company_dir = company["dir"]
            domain_url = company["domain"]
            company_name = company["company_name"]
            confidence = company["confidence"]
            
            if not domain_url.startswith("http"):
                domain_url = f"https://{domain_url}"
            
            log_info(f"  [{idx}/{len(to_audit)}] Audit: {company_name} ({domain_url}, {confidence:.0%})")
            
            try:
                result = run_audit_to_folder(domain_url, company_dir)
                
                if result.get("audit_pdf"):
                    log_info(f"    ✅ PDF skapad: audit_report.pdf")
                else:
                    log_info(f"    ✅ Audit klar")
                
                audited_count += 1
                
                if idx < len(to_audit):
                    await asyncio.sleep(1)
                    
            except Exception as e:
                log_error(f"    ❌ Audit misslyckades: {e}")
                continue
        
        log_info(f"Audits klara: {audited_count} av {len(to_audit)} lyckades")
        return len(qualified_companies), audited_count
        
    except ImportError as e:
        log_error(f"Kunde inte importera standalone_audit: {e}")
        return 0, 0
    except Exception as e:
        log_error(f"Fel vid audits: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0


MAIL_GREETING_KEYWORDS = ("hej", "hejsan", "tjena", "tjabba", "hallå", "god ")


def generate_dummy_data_for_testing(date_folder: Path, max_companies: int = 0) -> Dict[str, int]:
    """
    Generera dummy-data för testning utan AI-kostnader.
    
    Skapar:
    - evaluation.json i varje K-mapp (med dummy should_get_site, confidence, reasoning)
    - preview_url.txt för ~20% av företagen (med dummy URL)
    - audit_report.json för ~30% av företagen (med dummy scores)
    
    Args:
        date_folder: Datum-mapp att bearbeta
        max_companies: Max antal företag att bearbeta (0 = alla)
    
    Returns:
        Dict med antal genererade filer per typ
    """
    log_info("[DUMMY] Genererar testdata utan AI...")
    
    # Hitta alla K-mappar
    company_dirs = [
        d for d in date_folder.iterdir()
        if d.is_dir() and d.name.startswith("K") and "-" in d.name
    ]
    
    if max_companies > 0:
        company_dirs = company_dirs[:max_companies]
    
    if not company_dirs:
        log_warn("[DUMMY] Inga K-mappar hittades")
        return {"evaluations": 0, "previews": 0, "audits": 0}
    
    log_info(f"[DUMMY] Bearbetar {len(company_dirs)} företag...")
    
    evaluations_created = 0
    previews_created = 0
    audits_created = 0
    
    for idx, company_dir in enumerate(company_dirs):
        company_name = company_dir.name
        
        # Läs företagsnamn från company_data.json om det finns
        company_data_file = company_dir / "company_data.json"
        if company_data_file.exists():
            try:
                data = json.loads(company_data_file.read_text(encoding="utf-8"))
                company_name = data.get("company_name", company_dir.name)
            except (json.JSONDecodeError, OSError):
                pass
        
        # 1. Skapa dummy evaluation.json
        eval_file = company_dir / "evaluation.json"
        if not eval_file.exists():
            # Variera dummy-värdena lite
            should_get_site = (idx % 3) != 0  # ~67% får "ja"
            confidence = 0.5 + (idx % 5) * 0.1  # 0.5-0.9
            
            dummy_eval = {
                "should_get_site": should_get_site,
                "confidence": confidence,
                "reasoning": f"[DUMMY TEST DATA] Företag {company_name} - automatiskt genererad testdata utan AI.",
                "_dummy": True,
                "_generated_at": datetime.now().isoformat(),
            }
            eval_file.write_text(json.dumps(dummy_eval, ensure_ascii=False, indent=2), encoding="utf-8")
            evaluations_created += 1
        
        # 2. Skapa dummy preview_url.txt för ~20% av företagen
        preview_file = company_dir / "preview_url.txt"
        if not preview_file.exists() and (idx % 5) == 0:
            dummy_url = f"https://dummy-preview.example.com/{company_dir.name}"
            preview_file.write_text(dummy_url, encoding="utf-8")
            previews_created += 1
        
        # 3. Skapa dummy audit_report.json för ~30% av företagen
        audit_file = company_dir / "audit_report.json"
        if not audit_file.exists() and (idx % 3) == 0:
            dummy_audit = {
                "company": {
                    "name": company_name,
                    "industry": "Dummy-bransch",
                },
                "scores": {
                    "design": 3 + (idx % 3),
                    "content": 2 + (idx % 4),
                    "usability": 3 + (idx % 2),
                    "mobile": 2 + (idx % 3),
                    "seo": 3 + (idx % 2),
                    "overall": 3.0,
                },
                "strengths": ["[DUMMY] Styrka 1", "[DUMMY] Styrka 2"],
                "weaknesses": ["[DUMMY] Svaghet 1", "[DUMMY] Svaghet 2"],
                "recommendations": ["[DUMMY] Rekommendation 1", "[DUMMY] Rekommendation 2"],
                "_meta": {
                    "url": f"https://dummy-site.example.com/{company_dir.name}",
                    "audit_date": datetime.now().isoformat(),
                    "_dummy": True,
                },
            }
            audit_file.write_text(json.dumps(dummy_audit, ensure_ascii=False, indent=2), encoding="utf-8")
            audits_created += 1
    
    log_info(f"[DUMMY] Klart: {evaluations_created} evaluations, {previews_created} previews, {audits_created} audits")
    
    return {
        "evaluations": evaluations_created,
        "previews": previews_created,
        "audits": audits_created,
    }


def _collect_preview_audit_entries(date_folder: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not date_folder.exists():
        return entries

    for folder in date_folder.iterdir():
        if not folder.is_dir() or not folder.name.startswith("K") or "-" not in folder.name:
            continue

        preview_url = None
        preview_file = folder / "preview_url.txt"
        if preview_file.exists():
            try:
                preview_text = preview_file.read_text(encoding="utf-8").strip()
                if preview_text:
                    preview_url = preview_text
            except OSError:
                pass

        audit_link = None
        audit_pdf = folder / "audit_report.pdf"
        audit_json = folder / "audit_report.json"
        profile_file = folder / "company_profile.txt"
        link_source = None
        if audit_pdf.exists():
            link_source = audit_pdf
        elif audit_json.exists():
            link_source = audit_json
        elif profile_file.exists():
            link_source = profile_file

        if link_source:
            try:
                audit_link = link_source.resolve().as_uri()
            except OSError:
                audit_link = str(link_source.resolve())

        if preview_url or audit_link:
            entries.append({
                "folder_name": folder.name,
                "folder_path": folder,
                "preview_url": preview_url,
                "audit_link": audit_link,
            })

    return entries


def _update_mail_ready_with_links(date_folder: Path, entries: List[Dict[str, Any]]) -> int:
    xlsx = date_folder / "mail_ready.xlsx"
    if not xlsx.exists():
        return 0
    try:
        df = pd.read_excel(xlsx, sheet_name="Mails")
    except Exception as exc:
        log_warn(f"Misslyckades med att läsa mail_ready.xlsx: {exc}")
        return 0

    if "folder" not in df.columns:
        log_warn("mail_ready.xlsx saknar kolumnen 'folder' – kan inte uppdatera länkar")
        return 0

    if "site_preview_url" not in df.columns:
        df["site_preview_url"] = ""
    if "audit_note" not in df.columns:
        df["audit_note"] = ""

    folder_series = df["folder"].astype(str).str.strip()
    updated_rows = 0
    mail_col = "mail_content" if "mail_content" in df.columns else None

    for entry in entries:
        folder = entry["folder_name"]
        mask = folder_series == folder
        if not mask.any():
            continue
        row_updated = False
        if entry["preview_url"]:
            df.loc[mask, "site_preview_url"] = entry["preview_url"]
            row_updated = True
        if entry["audit_link"]:
            df.loc[mask, "audit_note"] = entry["audit_link"]
            row_updated = True

        if mail_col and row_updated:
            mail_file = entry["folder_path"] / "mail.txt"
            if mail_file.exists():
                try:
                    raw_content = mail_file.read_text(encoding="utf-8")
                    parts = raw_content.split("=" * 60, 1)
                    body_only = parts[1].strip() if len(parts) > 1 else raw_content.strip()
                    df.loc[mask, mail_col] = body_only
                except OSError:
                    pass

        if row_updated:
            updated_rows += int(mask.sum())

    if updated_rows:
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Mails", index=False)

    return updated_rows


def _update_kungorelser_excel(date_folder: Path, entries: List[Dict[str, Any]]) -> int:
    date_str = date_folder.name
    xlsx = date_folder / f"kungorelser_{date_str}.xlsx"
    if not xlsx.exists():
        matches = list(date_folder.glob("kungorelser_*.xlsx"))
        if not matches:
            return 0
        xlsx = matches[0]

    try:
        sheets = pd.read_excel(xlsx, sheet_name=None)
    except Exception as exc:
        log_warn(f"Misslyckades med att läsa {xlsx.name}: {exc}")
        return 0

    df = sheets.get("Data")
    if df is None or "Mapp" not in df.columns:
        log_warn(f"{xlsx.name} saknar bladet 'Data' eller kolumnen 'Mapp'")
        return 0

    if "Preview URL" not in df.columns:
        df["Preview URL"] = ""
    if "Audit Link" not in df.columns:
        df["Audit Link"] = ""

    folder_series = df["Mapp"].astype(str).str.strip().str.replace("/", "-", regex=False)

    updated_rows = 0
    for entry in entries:
        folder = entry["folder_name"]
        mask = folder_series == folder
        if not mask.any():
            continue
        row_updated = False
        if entry["preview_url"]:
            df.loc[mask, "Preview URL"] = entry["preview_url"]
            row_updated = True
        if entry["audit_link"]:
            df.loc[mask, "Audit Link"] = entry["audit_link"]
            row_updated = True
        if row_updated:
            updated_rows += int(mask.sum())

    if updated_rows:
        sheets["Data"] = df
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            for name, sheet_df in sheets.items():
                sheet_df.to_excel(writer, sheet_name=name, index=False)

    return updated_rows


def _insert_snippet_after_greeting(content: str, snippet: str) -> Tuple[str, bool]:
    if not snippet.strip():
        return content, False
    lines = content.splitlines()
    insert_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if any(stripped.startswith(greet) for greet in MAIL_GREETING_KEYWORDS):
            insert_idx = idx + 1
            while insert_idx < len(lines) and not lines[insert_idx].strip():
                insert_idx += 1
            break
    snippet_block = ["", snippet.strip(), ""]
    if insert_idx is None:
        new_content = "\n".join(snippet_block + lines)
    else:
        new_content = "\n".join(lines[:insert_idx] + snippet_block + lines[insert_idx:])
    return new_content, True


def _update_mail_txt_with_links(entries: List[Dict[str, Any]]) -> int:
    updated = 0
    for entry in entries:
        preview_url = entry.get("preview_url")
        audit_link = entry.get("audit_link")
        if not preview_url and not audit_link:
            continue
        mail_file = entry["folder_path"] / "mail.txt"
        if not mail_file.exists():
            continue
        try:
            content = mail_file.read_text(encoding="utf-8")
        except OSError:
            continue

        snippet_parts = []
        if preview_url and preview_url not in content:
            snippet_parts.append(f"Vi har redan tagit fram en kostnadsfri demosajt åt er: {preview_url}")
        if audit_link and audit_link not in content:
            snippet_parts.append(f"Vi gjorde också en snabb webbplats-audit åt er: {audit_link}")

        if not snippet_parts:
            continue

        snippet = "\n".join(snippet_parts)
        new_content, changed = _insert_snippet_after_greeting(content, snippet)
        if not changed or new_content == content:
            continue
        try:
            mail_file.write_text(new_content, encoding="utf-8")
            updated += 1
        except OSError:
            continue

    return updated


def sync_preview_and_audit_links(date_folder: Path) -> None:
    try:
        entries = _collect_preview_audit_entries(date_folder)
    except Exception as exc:
        log_warn(f"Misslyckades att samla preview/audit-länkar: {exc}")
        return

    if not entries:
        log_info("[LINK SYNC] Inga preview- eller audit-länkar att uppdatera")
        return

    mail_ready_rows = _update_mail_ready_with_links(date_folder, entries)
    kungorelser_rows = _update_kungorelser_excel(date_folder, entries)
    mail_files = _update_mail_txt_with_links(entries)

    log_info(
        "[LINK SYNC] Uppdaterade länkar för "
        f"{len(entries)} företag (mail_ready={mail_ready_rows}, "
        f"kungorelser={kungorelser_rows}, mail.txt={mail_files})"
    )


def copy_to_dropbox(date_folder: Path) -> bool:
    """Kopiera datum-mapp till Dropbox."""
    try:
        dropbox_script = DROPBOX_DIR / "copy_to_dropbox.py"

        if dropbox_script.exists() and dropbox_script.stat().st_size > 0:
            sys.path.insert(0, str(DROPBOX_DIR))
            try:
                from copy_to_dropbox import copy_date_folder_to_dropbox, find_dropbox_folder  # type: ignore[import-not-found]

                log_info(f"Kopierar {date_folder.name} till Dropbox...")

                try:
                    dropbox_base = find_dropbox_folder()
                    log_info(f"Dropbox-mapp: {dropbox_base}")
                except FileNotFoundError as e:
                    log_warn(f"Hittade ingen Dropbox-mapp: {e}")
                    return False

                if copy_date_folder_to_dropbox(date_folder, dropbox_base):
                    log_info("✅ Dropbox-kopiering klar")
                    return True
                else:
                    log_error("Dropbox-kopiering misslyckades")
                    return False

            except ImportError as e:
                log_error(f"Kunde inte importera copy_to_dropbox: {e}")
                return False
            finally:
                if str(DROPBOX_DIR) in sys.path:
                    sys.path.remove(str(DROPBOX_DIR))

        log_error(f"copy_to_dropbox.py saknas: {dropbox_script}")
        return False

    except Exception as e:
        log_error(f"Fel vid Dropbox-kopiering: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_config_with_master_number(master_number: int):
    """Uppdatera alla config-filer med master-nummer."""
    log_info(f"Uppdaterar config-filer med master-nummer: {master_number}")

    try:
        config_segment = SEGMENT_DIR / "config_ny.txt"
        if config_segment.exists():
            parser = configparser.ConfigParser()
            parser.optionxform = str
            parser.read(config_segment, encoding="utf-8")

            if not parser.has_section("RUNNER"):
                parser.add_section("RUNNER")
            parser.set("RUNNER", "max_companies_for_testing", str(master_number))

            if not parser.has_section("ANALYZE"):
                parser.add_section("ANALYZE")
            parser.set("ANALYZE", "analyze_max_companies", str(master_number))

            if not parser.has_section("VERIFY"):
                parser.add_section("VERIFY")
            parser.set("VERIFY", "verify_max_companies", str(master_number))

            if not parser.has_section("FINALIZE"):
                parser.add_section("FINALIZE")
            parser.set("FINALIZE", "finalize_max_companies", str(master_number))
            parser.set("FINALIZE", "site_audit_max_antal", str(master_number))

            if not parser.has_section("MAIL"):
                parser.add_section("MAIL")
            parser.set("MAIL", "mail_max_companies", str(master_number))

            with open(config_segment, "w", encoding="utf-8") as f:
                parser.write(f)
            log_info(f"  - Uppdaterade {config_segment.name}")

        os.environ["RUNNER_MAX_COMPANIES_FOR_TESTING"] = str(master_number)
        log_info("  - Satte miljövariabler")

    except Exception as e:
        log_error(f"Fel vid uppdatering av config: {e}")
        return False

    return True


def parse_date_argument(date_arg: str) -> Optional[str]:
    """Parse datumargument i olika format."""
    if not date_arg.startswith("-"):
        return None

    try:
        date_part = date_arg[1:]
        now = datetime.now()

        if len(date_part) == 8 and date_part.isdigit():
            year = int(date_part[:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            if month < 1 or month > 12 or day < 1 or day > 31:
                return None
            try:
                target_date = datetime(year, month, day)
                return target_date.strftime("%Y%m%d")
            except ValueError:
                return None

        elif len(date_part) == 4 and date_part.isdigit():
            month = int(date_part[:2])
            day = int(date_part[2:4])
            if month < 1 or month > 12 or day < 1 or day > 31:
                return None
            try:
                target_date = datetime(now.year, month, day)
                return target_date.strftime("%Y%m%d")
            except ValueError:
                return None

        elif len(date_part) <= 2 and date_part.isdigit():
            day = int(date_part)
            if day < 1 or day > 31:
                return None
            try:
                target_date = datetime(now.year, now.month, day)
                return target_date.strftime("%Y%m%d")
            except ValueError:
                return None

        return None
    except (ValueError, IndexError):
        return None


def main():
    """Huvudfunktion - kör pipeline från segmentering och framåt."""
    setup_run_logging()
    log_info(f"Run-logg: {RUN_LOG_FILE}")

    raw_args = sys.argv[1:]
    master_number = None
    target_date_str = None
    skip_process = False
    interactive_mode = sys.stdin.isatty()
    use_ai = True
    do_cleanup = False

    for arg in raw_args:
        if arg == "--skip-process":
            skip_process = True
        elif arg.startswith("-") and arg[1:].isdigit():
            num_part = arg[1:]
            if len(num_part) <= 2:
                master_number = int(num_part)
            else:
                parsed_date = parse_date_argument(arg)
                if parsed_date:
                    target_date_str = parsed_date
                else:
                    log_error(f"Ogiltigt datumargument: {arg}")
                    return 1
        elif arg.isdigit():
            master_number = int(arg)
        elif arg in ("--help", "-h"):
            print("""Kör pipeline från segmentering (hoppar över scraping)

Användning:
  python main_from_segment.py              # Kör från process_raw_data och framåt
  python main_from_segment.py 10           # Kör med master-nummer 10
  python main_from_segment.py -4           # Kör med master-nummer 4
  python main_from_segment.py -20251215    # Kör med specifikt datum
  python main_from_segment.py 5 -15        # Master-nummer 5, dag 15
  python main_from_segment.py --skip-process  # Hoppa över process_raw_data.py

Hoppar över:
  - Steg 1-3: Cleanup, server start, scraping

Kör:
  - Steg 4: process_raw_data.py (skapar CSV/DB) - hoppa över med --skip-process
  - Steg 5: ALLA.py (segmentering pipeline)
  - Steg 6: Evaluation och site generation
  - Steg 7: Kopiera till Dropbox
  - Steg 8: Bearbeta styrelsedata
""")
            return 0

    log_info("=" * 60)
    log_info("STARTAR PIPELINE FRÅN SEGMENTERING")
    log_info("(Hoppar över scraping - använder befintlig data)")
    log_info("=" * 60)
    log_info(f"Projektrot: {PROJECT_ROOT}")

    # Interaktiva val (endast om terminalen är interaktiv och inga motsvarande flaggar satts)
    if interactive_mode:
        # Fråga om cleanup (OBS: raderar datum-mappar, som i main.py)
        do_cleanup = prompt_yes_no(
            "Köra cleanup som tar bort datum-mappar/loggar (risk att data försvinner)?", default=False
        )

        # Fråga AI-läge: skarpt (AI) eller utan AI
        use_ai = prompt_yes_no("Köra med AI (evaluation/site/audit)?", default=True)

        # Fråga antal företag om inte satt
        if master_number is None:
            master_number = prompt_int("Ange antal företag (master-nummer), tomt = obegränsat", default=None)

    if target_date_str:
        log_info(f"Använder specifikt datum: {target_date_str}")
    else:
        target_date_str = datetime.now().strftime("%Y%m%d")
        log_info(f"Använder dagens datum: {target_date_str}")

    os.environ["TARGET_DATE"] = target_date_str
    log_info(f"TARGET_DATE miljövariabel satt till: {target_date_str}")

    if master_number is not None:
        if master_number < 0 or master_number > 999:
            log_error(f"Master-nummer måste vara mellan 0 och 999 (fick {master_number})")
            return 1
        if master_number > 0:
            log_info(f"Master-nummer: {master_number}")
            if not update_config_with_master_number(master_number):
                log_error("Kunde inte uppdatera config-filer")
                return 1
        else:
            log_info("Master-nummer: 0 (obegränsat)")

    print()
    failures = []

    try:
        # Valfri cleanup (använd med försiktighet om du vill återanvända befintliga datum-mappar)
        if do_cleanup:
            log_info("=" * 60)
            log_info("STEG 0 (Cleanup - valfritt): RENSAR DATA")
            log_info("=" * 60)
            # Viktigt: hoppa info_server/ för att behålla rådata
            removed, errors = run_full_cleanup(
                keep_days=7, clean_chrome=False, skip_info_server=True
            )
            if errors:
                for e in errors:
                    log_warn(e)
            log_info(f"Cleanup klar: {removed} objekt raderade")
            print()

        # Steg 4: Kör process_raw_data.py (skapar CSV/DB från JSON)
        if not skip_process:
            log_info("=" * 60)
            log_info("STEG 4: BEARBETNING AV RÅDATA (process_raw_data.py)")
            log_info("=" * 60)

            process_script = AUTOMATION_DIR / "process_raw_data.py"
            if process_script.exists():
                exit_code, duration, step_log, tail = run_script(
                    "process_raw_data", process_script, cwd=AUTOMATION_DIR
                )
                if exit_code != 0:
                    failures.append((process_script.name, exit_code, step_log))
                    summarize_failure("process_raw_data", exit_code, step_log, tail)
                    return 1
            else:
                log_warn(f"Skript saknas: {process_script} - hoppar över")
            print()
        else:
            log_info("Hoppar över process_raw_data.py (--skip-process)")
            print()

        # Steg 5: Kör segmentering pipeline (ALLA.py)
        log_info("=" * 60)
        log_info("STEG 5: SEGMENTERING PIPELINE (ALLA.py)")
        log_info("=" * 60)

        alla_script = SEGMENT_DIR / "ALLA.py"
        if alla_script.exists():
            exit_code, duration, step_log, tail = run_script(
                "segmentering", alla_script, cwd=SEGMENT_DIR
            )
            if exit_code != 0:
                failures.append((alla_script.name, exit_code, step_log))
                summarize_failure("segmentering", exit_code, step_log, tail)
                return 1
        else:
            log_error(f"Skript saknas: {alla_script}")
            return 1
        print()

        # Steg 6: Evaluation, Site Generation & Audit
        log_info("=" * 60)
        log_info("STEG 6: EVALUATION, SITE GENERATION & AUDIT")
        log_info("=" * 60)

        latest_date_dir: Optional[Path] = None
        djupanalys_dir = SEGMENT_DIR / "djupanalys"
        if djupanalys_dir.exists():
            latest_date_dir = get_target_date_dir(djupanalys_dir)
            if latest_date_dir:
                log_info(f"Bearbetar datum-mapp: {latest_date_dir.name}")

                if use_ai:
                    # 6a: Evaluation
                    log_info("Kör evaluation av företag...")
                    total_evaluated, worthy_count = asyncio.run(
                        run_company_evaluation(latest_date_dir)
                    )

                    # 6b: Site Generation
                    if worthy_count > 0:
                        log_info("Genererar hemsidor för kvalificerade företag...")
                        total_worthy, generated_count = asyncio.run(
                            generate_sites_for_worthy_companies(latest_date_dir)
                        )
                        log_info(f"  - Kvalificerade: {total_worthy}, Genererade: {generated_count}")
                    else:
                        log_warn("Inga värda företag hittades - hoppar över site generation")

                    # 6c: Audit (för företag med verifierad domän)
                    log_info("Kör audits för företag med verifierad domän...")
                    qualified_count, audited_count = asyncio.run(
                        run_audits_for_companies(latest_date_dir)
                    )
                    log_info(f"  - Kvalificerade: {qualified_count}, Auditerade: {audited_count}")

                    # 6d: Synka länkar till mail/excel
                    sync_preview_and_audit_links(latest_date_dir)
                else:
                    # Generera dummy-data för testning
                    log_info("AI avstängt: genererar dummy-data för testning...")
                    dummy_stats = generate_dummy_data_for_testing(
                        latest_date_dir, 
                        max_companies=master_number if master_number and master_number > 0 else 0
                    )
                    log_info(f"  - Evaluations: {dummy_stats['evaluations']}")
                    log_info(f"  - Previews: {dummy_stats['previews']}")
                    log_info(f"  - Audits: {dummy_stats['audits']}")
                    
                    # Synka länkar även med dummy-data
                    sync_preview_and_audit_links(latest_date_dir)
            else:
                log_warn("Hittade ingen datum-mapp i djupanalys/")
        else:
            log_warn("djupanalys/ mapp saknas")
        print()

        # Steg 7: Kopiera till Dropbox
        log_info("=" * 60)
        log_info("STEG 7: KOPIERA TILL DROPBOX")
        log_info("=" * 60)

        djupanalys_dir = SEGMENT_DIR / "djupanalys"
        if djupanalys_dir.exists():
            latest_date_dir = get_target_date_dir(djupanalys_dir)
            if latest_date_dir:
                log_info(f"Kopierar datum-mapp: {latest_date_dir.name}")
                if copy_to_dropbox(latest_date_dir):
                    log_info("✅ Dropbox-kopiering lyckades")
                else:
                    log_warn("⚠️  Dropbox-kopiering misslyckades eller hoppades över")
            else:
                log_warn("Hittade ingen datum-mapp i djupanalys/")
        else:
            log_warn("djupanalys/ mapp saknas")
        print()

        # Steg 8: Bearbeta styrelsedata (10_jocke)
        log_info("=" * 60)
        log_info("STEG 8: BEARBETA STYRELSEDATA")
        log_info("=" * 60)

        jocke_dir = PROJECT_ROOT / "10_jocke"
        if jocke_dir.exists():
            jocke_date_dir = get_target_date_dir(jocke_dir)
            if jocke_date_dir:
                log_info(f"Bearbetar styrelsedata i: {jocke_date_dir.name}")
                process_script = jocke_dir / "process_board_data.py"
                if process_script.exists():
                    exit_code, duration, step_log, tail = run_script(
                        "board_data", process_script, cwd=jocke_dir
                    )
                    if exit_code != 0:
                        summarize_failure("board_data", exit_code, step_log, tail)
                        return 1
                else:
                    log_warn(f"Skript saknas: {process_script}")
            else:
                log_warn("Hittade ingen datum-mapp i 10_jocke/")
        else:
            log_warn("10_jocke/ mapp saknas")
        print()

    except KeyboardInterrupt:
        log_warn("Avbruten av användaren (Ctrl+C)")
    except Exception as e:
        log_error(f"Oväntat fel: {e}")
        import traceback
        traceback.print_exc()

    # Sammanfattning
    log_info("=" * 60)
    log_info("SAMMANFATTNING")
    log_info("=" * 60)

    if failures:
        log_error(f"Antal fel: {len(failures)}")
        for failure in failures:
            script_name = failure[0]
            error = failure[1] if len(failure) > 1 else "okänt fel"
            log_error(f"  - {script_name}: {error}")
        log_info(f"Run-logg: {RUN_LOG_FILE}")
        return 1
    else:
        log_info("✅ Alla steg kördes utan fel!")
        log_info(f"Run-logg: {RUN_LOG_FILE}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

