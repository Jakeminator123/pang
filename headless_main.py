#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
headless_main.py - HEADLESS variant av datapipelinen

Användning:
    python headless_main.py           # Kör med inställningar från config-filer
    python headless_main.py <nummer>  # Kör med master-nummer (t.ex. python headless_main.py 10)
    python headless_main.py 10 --visible  # Visa Chrome-fönster (för CAPTCHA)

SKILLNAD MOT main.py:
- Använder HEADLESS scraping (headless_1_poit/) istället för GUI-baserad (1_poit/automation/)
- Snabbare: ~6-10s per sida istället för ~25s
- Ingen bildigenkänning eller pyautogui
- Behöver fortfarande Chrome men styr via Playwright CDP

Master-nummer styr ALLT:
- Antal företag att skrapa
- Antal företag att analysera
- Antal företag att generera mail för
- Antal företag att köra site audit på

Kör i sekvens:
1. Starta Flask-server (1_poit/server.py) - för framtida användning
2. HEADLESS scraping (headless_1_poit/) - snabbare än GUI
3. Kör process_raw_data.py (bearbetar rådata)
4. Kör segmentering pipeline (2_segment_info/ALLA.py)
5. Kör evaluation och generera hemsidor (3_sajt/)
6. Kopiera till Dropbox (9_dropbox/)
7. Bearbeta styrelsedata (10_jocke/)
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

# Encoding: PowerShell 7+ och Python 3.10+ har native UTF-8 stöd på Windows.
# Ingen manuell wrapping behövs längre.

# PoIT local collector server (Flask)
POIT_SERVER_HOST = "127.0.0.1"
POIT_SERVER_PORT = 51234
POIT_SERVER_BASE_URL = f"http://{POIT_SERVER_HOST}:{POIT_SERVER_PORT}"

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Ladda .env från projektroten
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[INFO] Laddade .env från {env_path}")
    else:
        print(f"[WARN] .env-fil saknas i {env_path}")
except ImportError:
    print("[WARN] python-dotenv saknas - installera med: pip install python-dotenv")

POIT_DIR = PROJECT_ROOT / "1_poit"
AUTOMATION_DIR = POIT_DIR / "automation"
SEGMENT_DIR = PROJECT_ROOT / "2_segment_info"
SAJT_DIR = PROJECT_ROOT / "3_sajt"
UTVARDERING_DIR = PROJECT_ROOT / "3_utvardering"
READY_DIR = PROJECT_ROOT / "8_ready"
DROPBOX_DIR = PROJECT_ROOT / "9_dropbox"

# Logging paths
LOG_DIR = PROJECT_ROOT / "logs"
STEP_LOG_DIR = LOG_DIR / "steps"
RUN_LOG_FILE: Optional[Path] = None
RUN_TS: str = ""

# Lock file to prevent concurrent pipeline runs
PIPELINE_LOCK_FILE = LOG_DIR / ".pipeline_lock"


def ensure_log_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STEP_LOG_DIR.mkdir(parents=True, exist_ok=True)


def acquire_pipeline_lock() -> bool:
    """
    Försök skaffa pipeline-lock. Returnerar True om lock kunde skaffas, False annars.
    """
    ensure_log_dirs()
    
    if PIPELINE_LOCK_FILE.exists():
        # Kolla om lock-filen är gammal (mer än 2 timmar = troligen stuck process)
        lock_age = time.time() - PIPELINE_LOCK_FILE.stat().st_mtime
        if lock_age > 7200:  # 2 timmar
            log_warn(f"⚠️  Gammal lock-fil hittades ({lock_age/3600:.1f} timmar gammal) - tar bort den")
            try:
                PIPELINE_LOCK_FILE.unlink()
            except Exception as e:
                log_error(f"Kunde inte ta bort gammal lock-fil: {e}")
                return False
        else:
            # Läs lock-info om den finns
            try:
                lock_info = PIPELINE_LOCK_FILE.read_text(encoding="utf-8").strip()
                log_error("=" * 60)
                log_error("🚫 PIPELINE REDAN KÖRS!")
                log_error("=" * 60)
                log_error(f"En annan pipeline-körning pågår redan.")
                if lock_info:
                    log_error(f"Lock-info: {lock_info}")
                log_error("")
                log_error("Vänta tills den andra körningen är klar, eller:")
                log_error(f"  - Ta bort lock-filen manuellt: {PIPELINE_LOCK_FILE}")
                log_error("  - Eller vänta 2 timmar (lock-filen tas bort automatiskt)")
                log_error("=" * 60)
            except Exception:
                pass
            return False
    
    # Skapa lock-fil med info om denna körning
    try:
        lock_info = f"Started: {datetime.now().isoformat()}\nPID: {os.getpid()}\nCommand: {' '.join(sys.argv)}"
        PIPELINE_LOCK_FILE.write_text(lock_info, encoding="utf-8")
        return True
    except Exception as e:
        log_error(f"Kunde inte skapa lock-fil: {e}")
        return False


def release_pipeline_lock():
    """Ta bort pipeline-lock."""
    try:
        if PIPELINE_LOCK_FILE.exists():
            PIPELINE_LOCK_FILE.unlink()
    except Exception as e:
        log_warn(f"Kunde inte ta bort lock-fil: {e}")


def setup_run_logging() -> Path:
    """Prepare per-run logging and return path to main log file."""
    global RUN_LOG_FILE, RUN_TS
    RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
    ensure_log_dirs()
    RUN_LOG_FILE = LOG_DIR / f"main_{RUN_TS}.log"
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
    """Timestamp för loggning."""
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


def check_server_running() -> bool:
    """Kontrollera om servern redan körs på PoIT-serverns port."""
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((POIT_SERVER_HOST, POIT_SERVER_PORT))
        sock.close()
        return result == 0
    except Exception:
        return False


def start_server() -> Optional[subprocess.Popen]:
    """Starta Flask-server i ett separat PowerShell-fönster."""
    # Kontrollera om servern redan körs
    if check_server_running():
        log_info(f"Servern körs redan på port {POIT_SERVER_PORT} - använder den")
        # Verifiera att servern faktiskt svarar på /health
        try:
            import urllib.request

            response = urllib.request.urlopen(f"{POIT_SERVER_BASE_URL}/health", timeout=2)
            if response.getcode() == 200:
                log_info("Servern svarar korrekt på /health")
                return None
            else:
                log_warn("Servern svarar men med fel statuskod")
        except Exception as e:
            log_warn(f"Servern körs men svarar inte på /health: {e}")
        return None

    log_info("Startar Flask-server i separat PowerShell-fönster...")
    server_path = POIT_DIR / "server.py"
    if not server_path.exists():
        log_error(f"Server-fil saknas: {server_path}")
        return None

    try:
        # Skicka med miljövariabler (inklusive TARGET_DATE om den är satt)
        env = os.environ.copy()
        if "TARGET_DATE" in env:
            log_info(f"Skickar TARGET_DATE={env['TARGET_DATE']} till server-processen")

        # Skapa PowerShell-kommando för att starta servern i nytt fönster
        # Använd absolut sökväg för att säkerställa att det fungerar
        python_exe = sys.executable
        server_script = str(server_path)
        cwd_path = str(POIT_DIR)

        # Bygg PowerShell-kommando med korrekt escaping
        # VIKTIGT: Använd $env: för att sätta miljövariabler som ärvs av Python-processen
        env_setup = []
        if "TARGET_DATE" in env:
            target_date_value = env["TARGET_DATE"]
            env_setup.append(f"$env:TARGET_DATE = '{target_date_value}'")
        env_setup.append("$env:PYTHONIOENCODING = 'utf-8'")

        # Skapa en temporär PowerShell-skriptfil för bättre kompatibilitet
        # VIKTIGT: Sätt miljövariabler INNAN vi startar Python så de ärvs korrekt
        ps_script_content = f"""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FLASK SERVER - Startar..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
# Sätt miljövariabler FÖRST - dessa kommer ärvas av Python-processen
{chr(10).join(env_setup)}
# Verifiera att miljövariablerna är satta
Write-Host "Miljövariabler:" -ForegroundColor Yellow
if ($env:TARGET_DATE) {{
    Write-Host "  TARGET_DATE: $env:TARGET_DATE" -ForegroundColor Green
}} else {{
    Write-Host "  TARGET_DATE: EJ SATT" -ForegroundColor Red
}}
Write-Host "  PYTHONIOENCODING: $env:PYTHONIOENCODING" -ForegroundColor Cyan
Set-Location '{cwd_path}'
Write-Host ""
Write-Host "Python: {python_exe}" -ForegroundColor Yellow
Write-Host "Script: {server_script}" -ForegroundColor Yellow
Write-Host "Working Directory: {cwd_path}" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
# Starta Python - miljövariablerna ärvs automatiskt från PowerShell-sessionen
& '{python_exe}' '{server_script}'
Write-Host ""
Write-Host "Server avslutad. Tryck valfri tangent för att stänga..." -ForegroundColor Red
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"""

        # Spara till temporär fil
        import tempfile

        ps_script_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        )
        ps_script_file.write(ps_script_content)
        ps_script_file.close()
        ps_script_path = ps_script_file.name

        # Starta PowerShell i nytt fönster med skriptfilen
        ps_args = [
            "powershell.exe",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",  # Tillåt körning av skript
            "-File",
            ps_script_path,
        ]

        log_info("Öppnar nytt PowerShell-fönster för servern...")
        log_info(f"PowerShell-skript: {ps_script_path}")
        try:
            process = subprocess.Popen(
                ps_args,
                cwd=str(POIT_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE
                if sys.platform == "win32"
                else 0,
            )
        except Exception as e:
            log_error(f"Kunde inte starta PowerShell: {e}")
            # Rensa temporär fil
            try:
                os.unlink(ps_script_path)
            except OSError:
                pass
            return None

        # Vänta på att servern startar
        log_info("Väntar på server startup (5 sekunder)...")
        time.sleep(5)

        # Kontrollera om processen fortfarande körs
        # OBS: PowerShell-processen kan fortfarande köra även om servern inte startat ännu
        # Så vi väntar lite längre innan vi kontrollerar
        time.sleep(2)

        if process.poll() is not None:
            exit_code = process.returncode
            log_error(
                f"PowerShell-processen avslutades omedelbart (exit-kod {exit_code})"
            )
            log_error("Kontrollera PowerShell-fönstret för felmeddelanden")
            # Rensa temporär fil
            try:
                os.unlink(ps_script_path)
            except OSError:
                pass
            return None

        # Verifiera att servern faktiskt svarar
        max_retries = 3
        for i in range(max_retries):
            try:
                import urllib.request

                response = urllib.request.urlopen(
                    f"{POIT_SERVER_BASE_URL}/health", timeout=2
                )
                if response.getcode() == 200:
                    log_info("Server startad och svarar korrekt på /health")
                    log_info(
                        "Servern körs i separat PowerShell-fönster - låt den vara öppen!"
                    )
                    return process
            except Exception:
                if i < max_retries - 1:
                    log_info(
                        f"Servern startar fortfarande, väntar... (försök {i + 1}/{max_retries})"
                    )
                    time.sleep(2)
                else:
                    log_error(
                        "Servern startade men svarar inte på /health efter flera försök"
                    )
                    log_error("Kontrollera PowerShell-fönstret för felmeddelanden")
                    # Rensa temporär fil
                    try:
                        os.unlink(ps_script_path)
                    except OSError:
                        pass
                    # Försök inte stänga processen eftersom den körs i separat fönster
                    return None

        # Rensa temporär fil efter lyckad start
        try:
            # Vänta lite så PowerShell hinner läsa filen
            time.sleep(1)
            os.unlink(ps_script_path)
        except OSError:
            pass

        return process
    except Exception as e:
        log_error(f"Kunde inte starta server: {e}")
        import traceback

        traceback.print_exc()
        return None


def stop_server(process: Optional[subprocess.Popen]):
    """Stäng Flask-server (endast om vi startade den)."""
    if process is None:
        # Om process är None kan det betyda att servern redan körde när vi startade
        # eller att servern inte startades av oss. Kontrollera om servern fortfarande körs.
        if check_server_running():
            log_info(
                "Servern körs fortfarande (startades inte av oss) - låter den vara"
            )
            log_info("Stäng PowerShell-fönstret manuellt om du vill stoppa servern")
        return

    log_info("Servern körs i separat PowerShell-fönster")
    log_info("Stäng PowerShell-fönstret manuellt för att stoppa servern")
    log_info("(Vi stänger inte fönstret automatiskt så du kan se serverns output)")


def run_script(
    step_name: str, script_path: Path, cwd: Path = None
) -> Tuple[int, float, Path, List[str]]:
    """Kör ett Python-skript med loggning till fil. Returnerar (exit code, duration, logpath, tail_lines)."""
    if cwd is None:
        cwd = script_path.parent

    ensure_log_dirs()
    step_log = STEP_LOG_DIR / f"{step_name}_{RUN_TS}.log"
    tail: List[str] = []

    target_date = os.environ.get("TARGET_DATE", "NOT_SET")
    log_info(
        f"Kör [{step_name}]: {script_path.name} (cwd={cwd}, TARGET_DATE={target_date})"
    )
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
            log_info(
                f"Klar [{step_name}]: {status} ({duration:.1f}s) - logg: {step_log}"
            )
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


def summarize_failure(
    step_name: str, exit_code: Any, log_path: Path, tail_lines: List[str]
):
    """Skriv tydlig felöversikt för ett steg."""
    log_error(f"Steg {step_name} misslyckades (exit {exit_code})")
    if tail_lines:
        log_error("Sista rader från loggen:")
        for line in tail_lines[-8:]:
            log_error(f"  {line}")
    log_error(f"Se loggfil: {log_path}")


def get_latest_date_dir(base_dir: Path) -> Optional[Path]:
    """Hitta senaste datummapp (YYYYMMDD) i en given basmapp."""
    if not base_dir.exists():
        return None

    date_dirs = []
    for item in base_dir.iterdir():
        if item.is_dir() and re.fullmatch(r"\d{8}", item.name):
            date_dirs.append(item)

    if not date_dirs:
        return None

    # Sortera och returnera senaste
    date_dirs.sort(key=lambda x: x.name)
    return date_dirs[-1]


def get_target_date_dir(base_dir: Path) -> Optional[Path]:
    """
    Hämta datummapp baserat på TARGET_DATE env var, fallback till senaste.

    Returns: Path till datummappen eller None om ingen finns.
    """
    if not base_dir.exists():
        return None

    target_date = os.environ.get("TARGET_DATE", "")
    target_path = base_dir / target_date if target_date else None

    if target_path and target_path.exists():
        log_info(f"[TARGET_DATE] Använder {target_path.name} i {base_dir.name}/")
        return target_path

    # Fallback till senaste
    latest = get_latest_date_dir(base_dir)
    if latest:
        if target_date:
            log_warn(
                f"TARGET_DATE={target_date} ej funnen i {base_dir.name}/, använder senaste: {latest.name}"
            )
        else:
            log_info(f"Använder senaste datummapp: {latest.name}")
        return latest

    return None


def get_status_paths(date_str: str, ensure_parent: bool = False) -> List[Path]:
    """Returnera möjliga platser för pipeline-statusfilen."""
    paths = []
    info_dir = POIT_DIR / "info_server" / date_str
    djup_dir = SEGMENT_DIR / "djupanalys" / date_str

    for base in [info_dir, djup_dir]:
        if ensure_parent:
            base.mkdir(parents=True, exist_ok=True)
        if base.exists():
            paths.append(base / "pipeline_status.json")
    return paths


def load_pipeline_status(date_str: str) -> Dict[str, Any]:
    """Läs statusfil om den finns, annars default."""
    for path in get_status_paths(date_str):
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    status = json.load(f)
                    if isinstance(status, dict):
                        return status
            except Exception as e:
                log_warn(f"Kunde inte läsa statusfil {path}: {e}")
    return {"date": date_str, "completed_steps": []}


def save_pipeline_status(date_str: str, status: Dict[str, Any]):
    """Spara statusfil till alla relevanta platser."""
    status = dict(status) if status else {}
    status.setdefault("date", date_str)
    status["updated_at"] = datetime.now().isoformat()

    for path in get_status_paths(date_str, ensure_parent=True):
        try:
            path.write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log_info(f"Status sparad: {path}")
        except Exception as e:
            log_warn(f"Kunde inte skriva status till {path}: {e}")


def is_step_done(status: Dict[str, Any], step_key: str) -> bool:
    completed = status.get("completed_steps", [])
    return isinstance(completed, list) and step_key in completed


def mark_step_done(date_str: str, status: Dict[str, Any], step_key: str):
    """Markera ett steg som klart och spara status."""
    if "completed_steps" not in status or not isinstance(
        status["completed_steps"], list
    ):
        status["completed_steps"] = []
    if step_key not in status["completed_steps"]:
        status["completed_steps"].append(step_key)
    save_pipeline_status(date_str, status)


def mark_failed_step(date_str: str, status: Dict[str, Any], step_key: str, detail: str):
    status["failed_step"] = {
        "step": step_key,
        "detail": detail,
        "ts": datetime.now().isoformat(),
    }
    save_pipeline_status(date_str, status)


def copy_final_data_to_ready(date_str: Optional[str] = None) -> bool:
    """
    Kopiera slutligt material från 2_segment_info/djupanalys/ till 8_ready/.

    Args:
        date_str: Datumsträng (YYYYMMDD). Om None, använd senaste mapp.

    Returns:
        True om kopiering lyckades, False annars.
    """
    log_info("Kopierar slutligt material till 8_ready/...")

    # Hitta källmapp
    source_base = SEGMENT_DIR / "djupanalys"
    if not source_base.exists():
        log_error(f"Källmapp saknas: {source_base}")
        return False

    # Hitta datummapp
    if date_str is None:
        date_dir = get_latest_date_dir(source_base)
        if date_dir is None:
            log_error("Hittade ingen datummapp i djupanalys/")
            return False
        date_str = date_dir.name
    else:
        date_dir = source_base / date_str
        if not date_dir.exists():
            log_error(f"Datummapp saknas: {date_dir}")
            return False

    log_info(f"Använder datum: {date_str}")

    # Skapa målmappar
    target_date_dir = READY_DIR / date_str
    target_db_dir = target_date_dir / "databases"
    target_excel_dir = target_date_dir / "excel"
    target_summaries_dir = target_date_dir / "summaries"

    for d in [target_date_dir, target_db_dir, target_excel_dir, target_summaries_dir]:
        d.mkdir(parents=True, exist_ok=True)

    copied_count = 0

    # Kopiera databases
    db_files = list(date_dir.glob("companies_*.db"))
    for db_file in db_files:
        target = target_db_dir / db_file.name
        shutil.copy2(db_file, target)
        log_info(f"  Kopierade DB: {db_file.name}")
        copied_count += 1

    # Kopiera Excel-filer
    xlsx_files = list(date_dir.glob("kungorelser_*.xlsx"))
    for xlsx_file in xlsx_files:
        target = target_excel_dir / xlsx_file.name
        shutil.copy2(xlsx_file, target)
        log_info(f"  Kopierade Excel: {xlsx_file.name}")
        copied_count += 1

    # Kopiera summaries (K-mappar)
    k_dirs = [
        d
        for d in date_dir.iterdir()
        if d.is_dir() and d.name.startswith("K") and "-" in d.name
    ]
    for k_dir in k_dirs:
        target = target_summaries_dir / k_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(k_dir, target)
        log_info(f"  Kopierade summary: {k_dir.name}")
        copied_count += 1

    log_info(f"Kopiering klar: {copied_count} objekt kopierade till {target_date_dir}")
    return True


async def run_company_evaluation(date_folder: Path) -> Tuple[int, int]:
    """
    Kör evaluation för alla företag i en datum-mapp.

    Returns:
        (total_evaluated, worthy_count) - Antal bedömda företag och antal värda företag
    """
    try:
        # Importera funktioner från evaluate_companies.py
        sys.path.insert(0, str(SAJT_DIR))
        from evaluate_companies import evaluate_companies_in_folder  # type: ignore

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

        log_info(
            f"Evaluation klar: {total_evaluated} bedömda, {worthy_count} värda företag"
        )
        return total_evaluated, worthy_count

    except ImportError as e:
        log_error(f"Kunde inte importera evaluate_companies: {e}")
        return 0, 0
    except Exception as e:
        log_error(f"Fel vid evaluation: {e}")
        import traceback

        traceback.print_exc()
        return 0, 0


async def generate_sites_for_worthy_companies(
    date_folder: Path, percentage: float = 0.25
) -> Tuple[int, int]:
    """
    Generera hemsidor för en procentandel av värda företag.

    Args:
        date_folder: Datum-mapp att bearbeta
        percentage: Procentandel av värda företag att generera hemsidor för (0.2-0.3)

    Returns:
        (total_worthy, generated_count) - Antal värda företag och antal genererade hemsidor
    """
    try:
        # Importera funktioner
        sys.path.insert(0, str(SAJT_DIR / "all_the_scripts"))
        from batch_generate import generate_site_for_company  # type: ignore

        sys.path.insert(0, str(SAJT_DIR))
        from evaluate_companies import (  # type: ignore
            find_company_folders,
            load_evaluation_from_folder,
        )

        # Hitta alla företag
        all_companies = find_company_folders(date_folder, filter_worthy=False)

        # Filtrera värda företag
        worthy_companies = []
        for company_folder in all_companies:
            evaluation = load_evaluation_from_folder(company_folder)
            if evaluation and evaluation.get("should_get_site", False):
                worthy_companies.append(company_folder)

        if not worthy_companies:
            log_warn("Inga värda företag hittades för site generation")
            return 0, 0

        # Välj ut procentandel (20-30%)
        num_to_generate = max(1, int(len(worthy_companies) * percentage))
        selected_companies = random.sample(
            worthy_companies, min(num_to_generate, len(worthy_companies))
        )

        log_info(
            f"Genererar hemsidor för {len(selected_companies)} av {len(worthy_companies)} värda företag ({percentage * 100:.0f}%)"
        )

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

            log_info(
                f"  [{idx}/{len(selected_companies)}] Genererar hemsida för: {company_name}..."
            )

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

                # Liten paus mellan genereringar
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


def load_sajt_config() -> Dict[str, Any]:
    """
    Läs audit/site-config från 3_sajt/config_ny.txt.
    
    Returns:
        Dict med config-värden
    """
    config = {
        "audit_enabled": False,
        "audit_threshold": 0.60,
        "audit_max_antal": 10,
        "audit_depth": "LOW",
        "site_enabled": True,
        "site_threshold": 0.80,
        "site_max_antal": 30,
    }
    
    config_path = SAJT_DIR / "config_ny.txt"
    if not config_path.exists():
        log_warn(f"Config-fil saknas: {config_path}")
        return config
    
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # Skip empty lines, comments, and section headers
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == "audit_enabled":
                    config["audit_enabled"] = value.lower() in ("y", "yes", "true", "1")
                elif key == "audit_threshold":
                    config["audit_threshold"] = float(value)
                elif key == "audit_max_antal":
                    config["audit_max_antal"] = int(value)
                elif key == "audit_depth":
                    config["audit_depth"] = value.upper()
                elif key == "site_enabled":
                    config["site_enabled"] = value.lower() in ("y", "yes", "true", "1")
                elif key == "site_threshold":
                    config["site_threshold"] = float(value)
                elif key == "site_max_antal":
                    config["site_max_antal"] = int(value)
    except Exception as e:
        log_warn(f"Kunde inte läsa sajt-config: {e}")
    
    return config


def load_audit_config() -> dict:
    """Load audit settings from 3_sajt/config_ny.txt (wrapper for backwards compatibility)."""
    sajt_config = load_sajt_config()
    return {
        "audit_enabled": sajt_config["audit_enabled"],
        "audit_threshold": sajt_config["audit_threshold"],
        "audit_max_antal": sajt_config["audit_max_antal"],
        "audit_depth": sajt_config["audit_depth"],
    }


async def run_audits_for_qualified_companies(date_folder: Path) -> tuple[int, int]:
    """
    Kör audits för företag med verifierad domän och tillräcklig confidence.
    
    Audits crawlar företagets befintliga hemsida och genererar:
    - audit_report.json - Detaljerad analys
    - audit_report.pdf - Snygg PDF-rapport
    - company_analysis.json - Strukturerad företagsdata
    - company_profile.txt - Läsbar profil
    
    Returns:
        (qualified_count, audited_count) - Antal kvalificerade och antal auditade
    """
    audit_config = load_audit_config()
    
    if not audit_config["audit_enabled"]:
        log_info("Audits är inaktiverade i config (audit_enabled = n i 3_sajt/config_ny.txt)")
        return 0, 0
    
    threshold = audit_config["audit_threshold"]
    max_antal = audit_config["audit_max_antal"]
    
    log_info(f"Audit-inställningar: threshold={threshold:.0%}, max={max_antal}")
    
    try:
        # Importera audit-funktion (dynamisk import från 3_sajt/all_the_scripts)
        sys.path.insert(0, str(SAJT_DIR / "all_the_scripts"))
        from standalone_audit import run_audit_to_folder  # type: ignore[import-not-found]
        
        # Hitta alla K-mappar
        company_dirs = [d for d in date_folder.iterdir() if d.is_dir() and d.name.startswith("K")]
        
        qualified_companies = []
        
        for company_dir in company_dirs:
            # Läs company_data.json
            company_data_file = company_dir / "company_data.json"
            if not company_data_file.exists():
                continue
            
            try:
                data = json.loads(company_data_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            
            # Kontrollera domän
            domain_info = data.get("domain", {})
            domain_url = domain_info.get("guess", "")
            confidence = domain_info.get("confidence", 0)
            status = domain_info.get("status", "unknown")
            
            # Kräv domän med tillräcklig confidence
            if not domain_url:
                continue
            # Acceptera verified, ai_verified, eller match status
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
        
        # Begränsa till max_antal
        to_audit = qualified_companies[:max_antal]
        
        log_info(f"Kör audits för {len(to_audit)} av {len(qualified_companies)} kvalificerade företag")
        
        audited_count = 0
        for idx, company in enumerate(to_audit, 1):
            company_dir = company["dir"]
            domain_url = company["domain"]
            company_name = company["company_name"]
            confidence = company["confidence"]
            
            # Säkerställ https://
            if not domain_url.startswith("http"):
                domain_url = f"https://{domain_url}"
            
            log_info(f"  [{idx}/{len(to_audit)}] Audit: {company_name} ({domain_url}, {confidence:.0%})")
            
            try:
                result = run_audit_to_folder(domain_url, company_dir)
                
                if result.get("audit_pdf"):
                    log_info(f"    ✅ PDF skapad: audit_report.pdf")
                else:
                    log_info(f"    ✅ Audit klar (ingen PDF - reportlab saknas?)")
                
                audited_count += 1
                
                # Kort paus mellan audits
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


def _collect_preview_audit_entries(date_folder: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not date_folder.exists():
        return entries

    for folder in date_folder.iterdir():
        if (
            not folder.is_dir()
            or not folder.name.startswith("K")
            or "-" not in folder.name
        ):
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

        # Prioritera PDF > JSON > TXT
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
            entries.append(
                {
                    "folder_name": folder.name,
                    "folder_path": folder,
                    "preview_url": preview_url,
                    "audit_link": audit_link,
                }
            )

    return entries


def _update_mail_ready_with_links(
    date_folder: Path, entries: List[Dict[str, Any]]
) -> int:
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

        # Uppdatera mail_content så den matchar mail.txt med länkar
        if mail_col and row_updated:
            mail_file = entry["folder_path"] / "mail.txt"
            if mail_file.exists():
                try:
                    new_content = mail_file.read_text(encoding="utf-8")
                    df.loc[mask, mail_col] = new_content
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
        # Fallback till första matchande fil
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

    folder_series = (
        df["Mapp"].astype(str).str.strip().str.replace("/", "-", regex=False)
    )

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
            snippet_parts.append(
                f"Vi har redan tagit fram en kostnadsfri demosajt åt er: {preview_url}"
            )
        if audit_link and audit_link not in content:
            snippet_parts.append(
                f"Vi gjorde också en snabb webbplats-audit åt er: {audit_link}"
            )

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


def _collect_audit_data(date_folder: Path) -> List[Dict[str, Any]]:
    """
    Samla audit-data från alla företagsmappar.
    
    Returns:
        Lista med audit-data för varje företag som har audit_report.json
    """
    audit_entries = []
    
    for folder in date_folder.iterdir():
        if not folder.is_dir() or not folder.name.startswith("K") or "-" not in folder.name:
            continue
        
        audit_file = folder / "audit_report.json"
        if not audit_file.exists():
            continue
        
        try:
            audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        
        # Hämta företagsnamn
        company_name = folder.name
        company_data_file = folder / "company_data.json"
        if company_data_file.exists():
            try:
                company_data = json.loads(company_data_file.read_text(encoding="utf-8"))
                company_name = company_data.get("company_name", folder.name)
            except (json.JSONDecodeError, OSError):
                pass
        
        # Extrahera relevant data
        company_info = audit_data.get("company", {})
        scores = audit_data.get("scores", {})
        meta = audit_data.get("_meta", {})
        strengths = audit_data.get("strengths", [])
        weaknesses = audit_data.get("weaknesses", [])
        recommendations = audit_data.get("recommendations", [])
        
        entry = {
            "folder": folder.name,
            "company_name": company_name,
            "url": meta.get("url", ""),
            "audit_date": meta.get("audit_date", "")[:10] if meta.get("audit_date") else "",
            "industry": company_info.get("industry", ""),
            "design_score": scores.get("design", ""),
            "content_score": scores.get("content", ""),
            "usability_score": scores.get("usability", ""),
            "mobile_score": scores.get("mobile", ""),
            "seo_score": scores.get("seo", ""),
            "overall_score": scores.get("overall", ""),
            "strengths": "; ".join(strengths[:3]) if strengths else "",
            "weaknesses": "; ".join(weaknesses[:3]) if weaknesses else "",
            "recommendations": "; ".join(recommendations[:3]) if recommendations else "",
        }
        audit_entries.append(entry)
    
    return audit_entries


def create_audits_excel_sheet(date_folder: Path) -> int:
    """
    Skapa ett nytt blad 'Audits' i Excel-filerna med audit-data.
    
    Lägger till bladet i:
    - mail_ready.xlsx
    - kungorelser_*.xlsx
    
    Returns:
        Antal filer som uppdaterades
    """
    audit_entries = _collect_audit_data(date_folder)
    
    if not audit_entries:
        log_info("[AUDIT EXCEL] Inga audit-rapporter att lägga till i Excel")
        return 0
    
    # Skapa DataFrame
    df_audits = pd.DataFrame(audit_entries)
    
    # Kolumnordning för bättre läsbarhet
    column_order = [
        "folder", "company_name", "url", "audit_date", "industry",
        "overall_score", "design_score", "content_score", "usability_score",
        "mobile_score", "seo_score", "strengths", "weaknesses", "recommendations"
    ]
    df_audits = df_audits[[c for c in column_order if c in df_audits.columns]]
    
    # Byt namn på kolumner för tydlighet
    column_names = {
        "folder": "Mapp",
        "company_name": "Företag",
        "url": "Hemsida",
        "audit_date": "Audit-datum",
        "industry": "Bransch",
        "overall_score": "Helhet",
        "design_score": "Design",
        "content_score": "Innehåll",
        "usability_score": "Användbarhet",
        "mobile_score": "Mobil",
        "seo_score": "SEO",
        "strengths": "Styrkor",
        "weaknesses": "Svagheter",
        "recommendations": "Rekommendationer",
    }
    df_audits = df_audits.rename(columns=column_names)
    
    updated_files = 0
    
    # Uppdatera mail_ready.xlsx
    mail_ready_xlsx = date_folder / "mail_ready.xlsx"
    if mail_ready_xlsx.exists():
        try:
            # Läs befintliga blad
            with pd.ExcelFile(mail_ready_xlsx) as xls:
                sheets = {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}
            
            # Lägg till/ersätt Audits-bladet
            sheets["Audits"] = df_audits
            
            # Skriv tillbaka
            with pd.ExcelWriter(mail_ready_xlsx, engine="openpyxl") as writer:
                for sheet_name, sheet_df in sheets.items():
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            log_info(f"[AUDIT EXCEL] Lade till 'Audits'-blad i mail_ready.xlsx ({len(audit_entries)} rader)")
            updated_files += 1
        except Exception as e:
            log_warn(f"[AUDIT EXCEL] Kunde inte uppdatera mail_ready.xlsx: {e}")
    
    # Uppdatera kungorelser_*.xlsx
    date_str = date_folder.name
    kungorelser_xlsx = date_folder / f"kungorelser_{date_str}.xlsx"
    if not kungorelser_xlsx.exists():
        matches = list(date_folder.glob("kungorelser_*.xlsx"))
        if matches:
            kungorelser_xlsx = matches[0]
    
    if kungorelser_xlsx.exists():
        try:
            # Läs befintliga blad
            with pd.ExcelFile(kungorelser_xlsx) as xls:
                sheets = {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}
            
            # Lägg till/ersätt Audits-bladet
            sheets["Audits"] = df_audits
            
            # Skriv tillbaka
            with pd.ExcelWriter(kungorelser_xlsx, engine="openpyxl") as writer:
                for sheet_name, sheet_df in sheets.items():
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            log_info(f"[AUDIT EXCEL] Lade till 'Audits'-blad i {kungorelser_xlsx.name} ({len(audit_entries)} rader)")
            updated_files += 1
        except Exception as e:
            log_warn(f"[AUDIT EXCEL] Kunde inte uppdatera {kungorelser_xlsx.name}: {e}")
    
    return updated_files


def copy_to_dropbox(date_folder: Path) -> bool:
    """
    Kopiera datum-mapp till Dropbox.

    Args:
        date_folder: Datum-mapp att kopiera (t.ex. djupanalys/20251208)

    Returns:
        True om kopiering lyckades, False annars
    """
    try:
        # Importera funktioner från copy_to_dropbox.py om den finns
        dropbox_script = DROPBOX_DIR / "copy_to_dropbox.py"

        if dropbox_script.exists() and dropbox_script.stat().st_size > 0:
            # Importera funktionerna direkt istället för att köra som subprocess
            sys.path.insert(0, str(DROPBOX_DIR))
            try:
                from copy_to_dropbox import (  # pyright: ignore[reportMissingImports]
                    copy_date_folder_to_dropbox,
                    find_dropbox_folder,
                )

                log_info(f"Kopierar {date_folder.name} till Dropbox...")

                # Hitta Dropbox-mapp
                try:
                    dropbox_base = find_dropbox_folder()
                    log_info(f"Dropbox-mapp: {dropbox_base}")
                except FileNotFoundError as e:
                    log_warn(f"Hittade ingen Dropbox-mapp: {e}")
                    log_info(
                        "Vanliga platser: ~/Dropbox, C:/Users/[USER]/Dropbox, D:/Dropbox"
                    )
                    return False

                # Kopiera med funktionen från copy_to_dropbox.py
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
                # Ta bort från sys.path
                if str(DROPBOX_DIR) in sys.path:
                    sys.path.remove(str(DROPBOX_DIR))

        # Om skriptet saknas
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
        # Uppdatera 1_poit/config.txt
        config_poit = POIT_DIR / "config.txt"
        if config_poit.exists():
            lines = []
            with open(config_poit, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("MAX_KUN_DAG="):
                        # Sätt till master-numret för scraping
                        lines.append(f"MAX_KUN_DAG={master_number}\n")
                    else:
                        lines.append(line)
            with open(config_poit, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log_info(f"  - Uppdaterade {config_poit.name}")

        # Uppdatera 2_segment_info/config_ny.txt
        # VIKTIGT: Bara uppdatera max_companies-värden, behåll alla thresholds och andra inställningar
        config_segment = SEGMENT_DIR / "config_ny.txt"
        if config_segment.exists():
            parser = configparser.ConfigParser()
            # Använd preserve_case för att behålla originalformatering
            parser.optionxform = str  # Behåll original case
            parser.read(config_segment, encoding="utf-8")

            # Uppdatera RUNNER-sektionen (bara max_companies)
            if not parser.has_section("RUNNER"):
                parser.add_section("RUNNER")
            parser.set("RUNNER", "max_companies_for_testing", str(master_number))

            # Uppdatera ANALYZE-sektionen (bara max_companies)
            if not parser.has_section("ANALYZE"):
                parser.add_section("ANALYZE")
            parser.set("ANALYZE", "analyze_max_companies", str(master_number))
            # BEHÅLLER alla andra ANALYZE-inställningar (modeller, thresholds, etc.)

            # Uppdatera VERIFY-sektionen (bara max_companies)
            if not parser.has_section("VERIFY"):
                parser.add_section("VERIFY")
            parser.set("VERIFY", "verify_max_companies", str(master_number))
            # BEHÅLLER verify_domain_confidence_threshold och andra inställningar

            # Uppdatera FINALIZE-sektionen (bara max_companies)
            if not parser.has_section("FINALIZE"):
                parser.add_section("FINALIZE")
            parser.set("FINALIZE", "finalize_max_companies", str(master_number))

            # Uppdatera SITE-sektionen (bara max_antal)
            if not parser.has_section("SITE"):
                parser.add_section("SITE")
            parser.set("SITE", "site_max_antal", str(master_number))
            # BEHÅLLER site_enabled, site_threshold

            # Uppdatera AUDIT-sektionen (bara max_antal)
            if not parser.has_section("AUDIT"):
                parser.add_section("AUDIT")
            parser.set("AUDIT", "audit_max_antal", str(master_number))
            # BEHÅLLER audit_enabled, audit_threshold, audit_depth

            # Uppdatera MAIL-sektionen (bara max_companies)
            if not parser.has_section("MAIL"):
                parser.add_section("MAIL")
            parser.set("MAIL", "mail_max_companies", str(master_number))
            # BEHÅLLER mail_enabled, mail_min_probability och andra inställningar från config

            # Skriv tillbaka (behåller alla andra värden)
            with open(config_segment, "w", encoding="utf-8") as f:
                parser.write(f)
            log_info(
                f"  - Uppdaterade {config_segment.name} (endast max_companies, behåller alla thresholds och inställningar)"
            )

        # Sätt miljövariabler för att begränsa antal (men inte överskriva thresholds)
        os.environ["RUNNER_MAX_COMPANIES_FOR_TESTING"] = str(master_number)
        os.environ["MAX_KUN_DAG"] = str(master_number)
        # INTE sätt MAIL_ENABLED eller FINALIZE_SITE_AUDIT_THRESHOLD - låt config bestämma
        log_info("  - Satte miljövariabler (endast för antal företag)")

    except Exception as e:
        log_error(f"Fel vid uppdatering av config: {e}")
        return False

    return True


def parse_date_argument(date_arg: str) -> Optional[str]:
    """
    Parse datumargument i olika format:
    - -7 eller -07 = dag 7 i nuvarande månad
    - -1107 = månad 11, dag 7 i nuvarande år
    - -20251107 = komplett datum (år, månad, dag)
    Returnerar YYYYMMDD-sträng eller None om ogiltigt.
    """
    if not date_arg.startswith("-"):
        return None

    try:
        date_part = date_arg[1:]  # Ta bort minus-tecknet

        now = datetime.now()

        # Format 1: Komplett datum (8 siffror) -20251107
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

        # Format 2: Månad och dag (4 siffror) -1107
        elif len(date_part) == 4 and date_part.isdigit():
            month = int(date_part[:2])
            day = int(date_part[2:4])
            if month < 1 or month > 12 or day < 1 or day > 31:
                return None
            try:
                target_date = datetime(now.year, month, day)
                return target_date.strftime("%Y%m%d")
            except ValueError:
                from calendar import monthrange

                last_day = monthrange(now.year, month)[1]
                if day > last_day:
                    target_date = datetime(now.year, month, last_day)
                    return target_date.strftime("%Y%m%d")
                return None

        # Format 3: Bara dag (1-2 siffror) -7 eller -07
        elif len(date_part) <= 2 and date_part.isdigit():
            day = int(date_part)
            if day < 1 or day > 31:
                return None
            try:
                target_date = datetime(now.year, now.month, day)
                return target_date.strftime("%Y%m%d")
            except ValueError:
                from calendar import monthrange

                last_day = monthrange(now.year, now.month)[1]
                if day > last_day:
                    target_date = datetime(now.year, now.month, last_day)
                    return target_date.strftime("%Y%m%d")
                return None

        return None
    except (ValueError, IndexError):
        return None


def main():
    """Huvudfunktion - kör hela pipelinen."""
    # Initiera loggfil direkt
    setup_run_logging()
    log_info(f"Run-logg: {RUN_LOG_FILE}")
    
    # Försök skaffa pipeline-lock för att förhindra samtidiga körningar
    if not acquire_pipeline_lock():
        return 1

    # Parse arguments - hantera master_number, datumargument och --visible
    raw_args = sys.argv[1:]

    master_number = None
    target_date_str = None
    visible_chrome = False  # HEADLESS: Visa Chrome-fönster?
    skip_to_segment = False  # Hoppa över scraping och rådata, starta från segmentering

    # Parse argumenten manuellt för att hantera både nummer och -15 format
    for arg in raw_args:
        if arg == "--visible" or arg == "-v":
            visible_chrome = True
        elif arg == "--alla" or arg == "--from-segment":
            skip_to_segment = True
        elif arg.startswith("-") and arg[1:].isdigit():
            # Först kolla om det är ett kort master-nummer (1-2 siffror, t.ex. -4)
            num_part = arg[1:]
            if len(num_part) <= 2:
                # Detta är master-nummer (t.ex. -4)
                master_number = int(num_part)
            else:
                # Detta är ett datumargument (t.ex. -15, -1107, -20251107)
                parsed_date = parse_date_argument(arg)
                if parsed_date:
                    target_date_str = parsed_date
                else:
                    log_error(f"Ogiltigt datumargument: {arg}")
                    return 1
        elif arg.isdigit():
            # Detta är master-nummer
            master_number = int(arg)
        elif arg in ("--help", "-h"):
            print("""Kör HEADLESS datapipeline (snabbare scraping)

Användning:
  python headless_main.py                    # Kör med inställningar från config-filer
  python headless_main.py 10                 # Kör med master-nummer 10
  python headless_main.py 10 --visible       # Visa Chrome (för CAPTCHA)
  python headless_main.py --alla             # Starta från segmentering (hoppa över scraping)
  python headless_main.py 5 -1218            # Master 5, datum 18 december
  python headless_main.py --help             # Visa denna hjälp

Argument:
  master_number                     Master-nummer som styr antal företag genom hela pipelinen
  --visible, -v                     Visa Chrome-fönster (för debugging/CAPTCHA)
  --alla, --from-segment            Hoppa över scraping och rådata, starta från segmentering
  -<nummer>                         Master-nummer (1-2 siffror, t.ex. -4 för 4 företag)
  -<dag>                            Välj specifik dag i månaden (3+ siffror, t.ex. -15 för 15:e dagen)
  -<månaddag>                       Välj månad och dag (4 siffror, t.ex. -1107 för 11:e månaden, dag 7)
  -<YYYYMMDD>                       Välj komplett datum (8 siffror, t.ex. -20251107 för 2025-11-07)

SKILLNAD MOT main.py:
  - Använder headless scraping (snabbare, ~6-10s per sida)
  - Ingen bildigenkänning eller GUI-automation
  - Sparar till samma plats (1_poit/info_server/)
""")
            return 0

    # Om inget master-nummer angavs, använd None (använder config)
    if master_number is None and target_date_str is None and len(raw_args) > 0:
        # Filtrera bort --visible från kontrollen
        non_flag_args = [a for a in raw_args if a not in ("--visible", "-v")]
        if non_flag_args:
            log_error(f"Okänt argument: {non_flag_args[0]}")
            log_info("Använd: python headless_main.py [master_number] [-dag] [--visible]")
            return 1

    log_info("=" * 60)
    log_info("STARTAR HEADLESS DATAPIPELINE")
    log_info("=" * 60)
    log_info(f"Chrome synlig: {'JA' if visible_chrome else 'NEJ (off-screen)'}")
    log_info(f"Projektrot: {PROJECT_ROOT}")
    log_info(f"Python: {sys.executable}")
    log_info("Config-filer:")
    for cfg_path in [
        PROJECT_ROOT / ".env",
        POIT_DIR / "config.txt",
        SEGMENT_DIR / "config_ny.txt",
    ]:
        exists = "OK" if cfg_path.exists() else "SAKNAS"
        log_info(f"  - {cfg_path.relative_to(PROJECT_ROOT)}: {exists}")

    # Varning om inget master-nummer angavs
    if master_number is None:
        log_warn("⚠️  INGET MASTER-NUMMER ANGIVET!")
        log_warn(
            "⚠️  Pipeline kommer köra med obegränsat antal företag från config-filer"
        )
        log_warn("⚠️  Använd t.ex. 'py main.py -4' för att begränsa till 4 företag")
        log_warn("⚠️  Eller 'py main.py 10' för att begränsa till 10 företag")

    # Om datumargument angavs, visa det
    if target_date_str:
        log_info(f"Använder specifikt datum: {target_date_str}")
    else:
        # Använd dagens datum som standard
        target_date_str = datetime.now().strftime("%Y%m%d")
        log_info(f"Använder dagens datum: {target_date_str}")

    # VIKTIGT: Sätt alltid TARGET_DATE miljövariabel så servern kan använda den
    os.environ["TARGET_DATE"] = target_date_str
    log_info(f"TARGET_DATE miljövariabel satt till: {target_date_str}")

    status = load_pipeline_status(target_date_str)
    if status.get("failed_step"):
        log_warn(f"Tidigare avbrott i steg: {status['failed_step']}")

    # Om master-nummer angivits, uppdatera alla configs
    if master_number is not None:
        if master_number < 0 or master_number > 999:
            log_error(
                f"Master-nummer måste vara mellan 0 (obegränsat) och 999 (fick {master_number})"
            )
            return 1
        if master_number == 0:
            log_info("Master-nummer: 0 (obegränsat - använder config-inställningar)")
        else:
            log_info(f"Master-nummer: {master_number}")
            if not update_config_with_master_number(master_number):
                log_error("Kunde inte uppdatera config-filer")
                return 1
    else:
        log_info("Kör med befintliga config-inställningar")

    print()

    server_process = None
    failures = []

    try:
        # Steg 0: Kör ALLTID komplett cleanup (gamla mappar + all data för dagens körning)
        # VIKTIGT: Cleanup körs ALLTID först oavsett pipeline_status för att garantera ren start
        log_info("=" * 60)
        log_info("STEG 0: KOMPLETT CLEANUP (körs alltid)")
        log_info("=" * 60)

        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from utils.erase import run_full_cleanup

            removed_count, errors = run_full_cleanup(keep_days=7)
            if errors:
                for error in errors:
                    log_warn(f"Cleanup-fel: {error}")
            log_info(f"Cleanup klar: {removed_count} objekt raderade")

            # Återställ pipeline-status efter cleanup (ny körning = ny status)
            status = {"date": target_date_str, "completed_steps": ["cleanup"]}
            save_pipeline_status(target_date_str, status)
            log_info("Pipeline-status återställd för ny körning")
        except ImportError as e:
            log_error(f"Kunde inte importera cleanup-modul: {e}")
            import traceback

            traceback.print_exc()
        except Exception as e:
            log_error(f"Fel vid körning av cleanup: {e}")
            import traceback

            traceback.print_exc()

        # NOTERA: Chrome-cache rensas INTE automatiskt för att bevara browser-session
        # Kör manuellt vid behov: python 1_poit/automation/clear_chrome_cache.py

        print()

        # Steg 1: Starta server (eller använd befintlig)
        log_info("=" * 60)
        log_info("STEG 1: SERVER START")
        log_info("=" * 60)

        server_process = start_server()
        # Om server_process är None kan det betyda:
        # 1. Servern körs redan (OK - fortsätt)
        # 2. Servern kunde inte startas (FEL - avbryt)
        # Kontrollera om servern faktiskt körs och svarar
        if server_process is None:
            if not check_server_running():
                log_error("Kunde inte starta server och ingen server körs - avbryter")
                mark_failed_step(
                    target_date_str, status, "server_start", "Health-check misslyckades"
                )
                return 1
            # Verifiera att servern svarar
            try:
                import urllib.request

                response = urllib.request.urlopen(
                    f"{POIT_SERVER_BASE_URL}/health", timeout=2
                )
                if response.getcode() != 200:
                    log_error("Servern körs men svarar inte korrekt - avbryter")
                    mark_failed_step(
                        target_date_str,
                        status,
                        "server_start",
                        "Health-endpoint svarar inte 200",
                    )
                    return 1
            except Exception as e:
                log_error(f"Servern körs men svarar inte på /health: {e} - avbryter")
                mark_failed_step(
                    target_date_str,
                    status,
                    "server_start",
                    "Undantag vid health-kontroll",
                )
                return 1

        log_info("Servern är redo - fortsätter med pipeline")
        mark_step_done(target_date_str, status, "server_started")
        print()

        # Om --alla flaggan är satt, hoppa över scraping och rådata
        if skip_to_segment:
            log_info("=" * 60)
            log_info("HOPPAR ÖVER SCRAPING OCH RÅDATA")
            log_info("=" * 60)
            log_info("Flaggan --alla används - startar från segmentering (STEG 4)")
            log_info("")
            log_info("Markerar scraping och process_raw_data som klara...")
            
            # Markera scraping och process_raw_data som klara
            mark_step_done(target_date_str, status, "scraping")
            mark_step_done(target_date_str, status, "process_raw_data")
            
            log_info("✓ Hoppar över STEG 2 (scraping) och STEG 3 (rådata)")
            log_info("Fortsätter med STEG 4 (segmentering)...")
            print()
        else:
            # Steg 2: HEADLESS SCRAPING
            log_info("=" * 60)
            log_info("STEG 2: HEADLESS SCRAPING")
            log_info("=" * 60)

        info_server_dir = POIT_DIR / "info_server"
        # Använd TARGET_DATE om det finns, annars dagens datum
        date_str = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
        date_folder = info_server_dir / date_str
        today_json = date_folder / f"kungorelser_{date_str}.json"

        if is_step_done(status, "scraping"):
            log_info("Hoppar över scraping (markerad klar i pipeline_status.json)")
        else:
            # Om dagens JSON redan finns, hoppa över scraping helt
            if today_json.exists() and today_json.stat().st_size > 0:
                log_info(f"✓ Dagens scraping-data finns redan: {today_json}")
                log_info("Hoppar över scraping - data finns redan")
                mark_step_done(target_date_str, status, "scraping")
            else:
                # HEADLESS: Kör headless scraping istället för GUI-baserad
                log_info("Kör HEADLESS scraping (snabbare än GUI-variant)")
                
                # Bestäm antal att scrapa:
                # - Om master_number anges: använd det
                # - Annars: None = låt config_headless.txt bestämma (MAX_KUN_DAG)
                scrape_count = master_number if master_number and master_number > 0 else None
                if scrape_count:
                    log_info(f"Antal att scrapa: {scrape_count} (från argument)")
                else:
                    log_info("Antal att scrapa: styrs av config_headless.txt (MAX_KUN_DAG)")
                log_info(f"Chrome synlig: {'JA' if visible_chrome else 'NEJ'}")
                
                try:
                    # Importera headless scraper (dynamisk import från headless_1_poit)
                    sys.path.insert(0, str(PROJECT_ROOT / "headless_1_poit"))
                    from scrape import run_headless_scrape  # type: ignore[import-not-found]
                    
                    # Kör headless scraping
                    success, total_in_list, scraped_count = asyncio.run(
                        run_headless_scrape(date_str, scrape_count, visible=visible_chrome)
                    )
                    
                    if not success:
                        log_error("Headless scraping misslyckades")
                        mark_failed_step(target_date_str, status, "scraping", "headless failed")
                        return 1
                    
                    log_info(f"✓ Headless scraping klar: {scraped_count}/{total_in_list} kungörelser")
                    mark_step_done(target_date_str, status, "scraping")
                    
                except ImportError as e:
                    log_error(f"Kunde inte importera headless scraper: {e}")
                    log_error("Kontrollera att headless_1_poit/scrape.py finns")
                    mark_failed_step(target_date_str, status, "scraping", f"import error: {e}")
                    return 1
                except Exception as e:
                    log_error(f"Fel vid headless scraping: {e}")
                    import traceback
                    traceback.print_exc()
                    mark_failed_step(target_date_str, status, "scraping", str(e))
                    return 1
                
                print()

        # Verifiera att JSON-fil finns (antingen befintlig eller nyss skapad)
        # Hoppa över verifiering om --alla används (vi behöver inte JSON-filen)
        if not skip_to_segment:
            # Först kolla i TARGET_DATE-mappen specifikt
            target_date_json = date_folder / f"kungorelser_{date_str}.json"
            if target_date_json.exists() and target_date_json.stat().st_size > 0:
                log_info(f"✓ Använder JSON-fil: {target_date_json.name}")
            else:
                # Om inte i TARGET_DATE-mappen, sök i alla mappar
                log_info(
                    "Ingen JSON i dagens mapp - söker fallback bland info_server/**/kungorelser_*.json"
                )
                json_files = list(info_server_dir.glob("**/kungorelser_*.json"))
                if not json_files:
                    log_error(
                        f"Ingen kungorelser_*.json fil hittades i {date_folder} eller någon annan mapp"
                    )
                    log_error("Headless scraping borde ha skapat denna fil.")
                    log_error("Kontrollera att:")
                    log_error("  1. Chrome kunde starta (prova med --visible)")
                    log_error("  2. Inga CAPTCHA blockerade")
                    log_error("  3. API:et svarade korrekt")
                    mark_failed_step(
                        target_date_str, status, "scraping", "JSON-data saknas"
                    )
                    return 1
                fallback_json = max(json_files, key=lambda p: p.stat().st_mtime)
                log_info(f"✓ Använder JSON-fil: {fallback_json.name} (från annan mapp)")

        # Steg 3: Kör process_raw_data.py (hoppas över om --alla används)
        if not skip_to_segment:
            log_info("=" * 60)
            log_info("STEG 3: BEARBETNING AV RÅDATA")
            log_info("=" * 60)

            if is_step_done(status, "process_raw_data"):
                log_info(
                    "Hoppar över process_raw_data (markerad klar i pipeline_status.json)"
                )
            else:
                segmentering_script = AUTOMATION_DIR / "process_raw_data.py"
                if segmentering_script.exists():
                    exit_code, duration, step_log, tail = run_script(
                        "process_raw_data", segmentering_script, cwd=AUTOMATION_DIR
                    )
                    if exit_code != 0:
                        failures.append((segmentering_script.name, exit_code, step_log))
                        summarize_failure("process_raw_data", exit_code, step_log, tail)
                        mark_failed_step(
                            target_date_str, status, "process_raw_data", f"exit {exit_code}"
                        )
                        return 1
                    mark_step_done(target_date_str, status, "process_raw_data")
                else:
                    log_warn(f"Skript saknas: {segmentering_script}")
            print()

        # Steg 4: Kör segmentering pipeline
        log_info("=" * 60)
        log_info("STEG 4: SEGMENTERING PIPELINE")
        log_info("=" * 60)

        if is_step_done(status, "segment_all"):
            log_info("Hoppar över segmentering (markerad klar i pipeline_status.json)")
        else:
            alla_script = SEGMENT_DIR / "ALLA.py"
            if alla_script.exists():
                exit_code, duration, step_log, tail = run_script(
                    "segmentering", alla_script, cwd=SEGMENT_DIR
                )
                if exit_code != 0:
                    failures.append((alla_script.name, exit_code, step_log))
                    summarize_failure("segmentering", exit_code, step_log, tail)
                    mark_failed_step(
                        target_date_str, status, "segment_all", f"exit {exit_code}"
                    )
                    return 1
                mark_step_done(target_date_str, status, "segment_all")
            else:
                log_error(f"Skript saknas: {alla_script}")
                failures.append((alla_script.name, "Saknas"))
                mark_failed_step(
                    target_date_str, status, "segment_all", "skript saknas"
                )
                return 1
        print()

        # Steg 5: Kör evaluation och generera hemsidor för värda företag
        log_info("=" * 60)
        log_info("STEG 5: EVALUATION OCH SITE GENERATION")
        log_info("=" * 60)

        if is_step_done(status, "evaluation"):
            log_info(
                "Hoppar över evaluation/site generation (markerad klar i pipeline_status.json)"
            )
        else:
            evaluation_ran = False
            latest_date_dir: Optional[Path] = None
            # Hitta TARGET_DATE eller senaste datum-mappen från segmentering
            djupanalys_dir = SEGMENT_DIR / "djupanalys"
            if djupanalys_dir.exists():
                latest_date_dir = get_target_date_dir(djupanalys_dir)
                if latest_date_dir:
                    log_info(
                        f"Bearbetar datum-mapp: {latest_date_dir.name} (full path: {latest_date_dir})"
                    )
                    evaluation_ran = True

                    # Kör evaluation
                    log_info("Kör evaluation av företag...")
                    total_evaluated, worthy_count = asyncio.run(
                        run_company_evaluation(latest_date_dir)
                    )

                    if worthy_count > 0:
                        percentage = 0.25  # 25% som standard
                        log_info(
                            f"Genererar hemsidor för {percentage * 100:.0f}% av värda företag..."
                        )
                        total_worthy, generated_count = asyncio.run(
                            generate_sites_for_worthy_companies(
                                latest_date_dir, percentage
                            )
                        )

                        log_info("Site generation sammanfattning:")
                        log_info(f"  - Värda företag: {total_worthy}")
                        log_info(f"  - Genererade hemsidor: {generated_count}")
                    else:
                        log_warn(
                            "Inga värda företag hittades - hoppar över site generation"
                        )

                    # Kör audits för företag med verifierad domän
                    log_info("")
                    log_info("Kör audits för företag med befintlig hemsida...")
                    qualified_count, audited_count = asyncio.run(
                        run_audits_for_qualified_companies(latest_date_dir)
                    )
                    if audited_count > 0:
                        log_info("Audit sammanfattning:")
                        log_info(f"  - Kvalificerade företag: {qualified_count}")
                        log_info(f"  - Genomförda audits: {audited_count}")
                else:
                    log_warn(
                        "Hittade ingen datum-mapp i djupanalys/ - hoppar över evaluation"
                    )
            else:
                log_warn("djupanalys/ mapp saknas - hoppar över evaluation")

            if evaluation_ran:
                if latest_date_dir:
                    sync_preview_and_audit_links(latest_date_dir)
                    # Skapa Audits-blad i Excel-filer
                    create_audits_excel_sheet(latest_date_dir)
                mark_step_done(target_date_str, status, "evaluation")
        print()

        # Steg 6: Kopiera till Dropbox
        log_info("=" * 60)
        log_info("STEG 6: KOPIERA TILL DROPBOX")
        log_info("=" * 60)

        if is_step_done(status, "dropbox"):
            log_info(
                "Hoppar över Dropbox-kopiering (markerad klar i pipeline_status.json)"
            )
        else:
            # Hitta TARGET_DATE eller senaste datum-mappen från segmentering
            djupanalys_dir = SEGMENT_DIR / "djupanalys"
            if djupanalys_dir.exists():
                latest_date_dir = get_target_date_dir(djupanalys_dir)
                if latest_date_dir:
                    log_info(
                        f"Kopierar datum-mapp: {latest_date_dir.name} (full path: {latest_date_dir})"
                    )
                    if copy_to_dropbox(latest_date_dir):
                        log_info("✅ Dropbox-kopiering lyckades")
                        mark_step_done(target_date_str, status, "dropbox")
                    else:
                        log_warn(
                            "⚠️  Dropbox-kopiering misslyckades eller hoppades över"
                        )
                else:
                    log_warn(
                        "Hittade ingen datum-mapp i djupanalys/ - hoppar över Dropbox-kopiering"
                    )
            else:
                log_warn("djupanalys/ mapp saknas - hoppar över Dropbox-kopiering")
        print()

        # Steg 7: Bearbeta styrelsedata (10_jocke)
        log_info("=" * 60)
        log_info("STEG 7: BEARBETA STYRELSEDATA")
        log_info("=" * 60)

        if is_step_done(status, "board_data"):
            log_info("Hoppar över styrelsedata (markerad klar i pipeline_status.json)")
        else:
            jocke_dir = PROJECT_ROOT / "10_jocke"
            if jocke_dir.exists():
                jocke_date_dir = get_target_date_dir(jocke_dir)
                if jocke_date_dir:
                    log_info(
                        f"Bearbetar styrelsedata i: {jocke_date_dir.name} (full path: {jocke_date_dir})"
                    )
                    process_script = jocke_dir / "process_board_data.py"
                    if process_script.exists():
                        exit_code, duration, step_log, tail = run_script(
                            "board_data", process_script, cwd=jocke_dir
                        )
                        if exit_code != 0:
                            summarize_failure("board_data", exit_code, step_log, tail)
                            mark_failed_step(
                                target_date_str,
                                status,
                                "board_data",
                                f"exit {exit_code}",
                            )
                            return 1
                        mark_step_done(target_date_str, status, "board_data")
                    else:
                        log_warn(f"Skript saknas: {process_script}")
                        mark_failed_step(
                            target_date_str, status, "board_data", "skript saknas"
                        )
                        return 1
                else:
                    log_warn(
                        "Hittade ingen datum-mapp i 10_jocke/ - hoppar över styrelsedata-bearbetning"
                    )
            else:
                log_warn("10_jocke/ mapp saknas - hoppar över styrelsedata-bearbetning")
        print()

    except KeyboardInterrupt:
        log_warn("Avbruten av användaren (Ctrl+C)")
    except Exception as e:
        log_error(f"Oväntat fel: {e}")
        import traceback

        traceback.print_exc()
        if "status" in locals():
            mark_failed_step(target_date_str, status, "unexpected", str(e))
    finally:
        # Stäng server
        stop_server(server_process)
        # Ta bort pipeline-lock
        release_pipeline_lock()

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
            if len(failure) > 2 and failure[2]:
                log_error(f"    Logg: {failure[2]}")
        log_info(f"Run-logg: {RUN_LOG_FILE}")
        return 1
    else:
        log_info("✅ Alla steg kördes utan fel!")
        log_info(f"Run-logg: {RUN_LOG_FILE}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
