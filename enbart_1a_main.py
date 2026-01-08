#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enbart_1a_main.py - Kör endast 1_poit-stegen och zippa + skicka till Dropbox

Hoppar över 2_segment_info och 3_sajt helt.
Tar mappen från 1_poit/info_server/<datum>/ istället för djupanalys.

Användning:
    python enbart_1a_main.py           # Kör med inställningar från config
    python enbart_1a_main.py 3         # Begränsa till 3 företag (för test)
    python enbart_1a_main.py 10        # Begränsa till 10 företag
"""

import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Load .env
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Directories
POIT_DIR = PROJECT_ROOT / "1_poit"
AUTOMATION_DIR = POIT_DIR / "automation"
INFO_SERVER_DIR = POIT_DIR / "info_server"
DROPBOX_DIR = PROJECT_ROOT / "9_dropbox"
JOCKE_DIR = PROJECT_ROOT / "10_jocke"

# Server config
POIT_SERVER_HOST = "127.0.0.1"
POIT_SERVER_PORT = 51234
POIT_SERVER_BASE_URL = f"http://{POIT_SERVER_HOST}:{POIT_SERVER_PORT}"


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_info(msg: str):
    print(f"[INFO {ts()}] {msg}")


def log_error(msg: str):
    print(f"[ERROR {ts()}] {msg}")


def log_warn(msg: str):
    print(f"[WARN {ts()}] {msg}")


def check_server_running() -> bool:
    """Kontrollera om servern redan körs."""
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
    if check_server_running():
        log_info(f"Servern körs redan på port {POIT_SERVER_PORT} - använder den")
        try:
            import urllib.request
            response = urllib.request.urlopen(f"{POIT_SERVER_BASE_URL}/health", timeout=2)
            if response.getcode() == 200:
                log_info("Servern svarar korrekt på /health")
                return None
        except Exception as e:
            log_warn(f"Servern körs men svarar inte på /health: {e}")
        return None

    log_info("Startar Flask-server i separat PowerShell-fönster...")
    server_path = POIT_DIR / "server.py"
    if not server_path.exists():
        log_error(f"Server-fil saknas: {server_path}")
        return None

    try:
        env = os.environ.copy()
        python_exe = sys.executable
        server_script = str(server_path)
        cwd_path = str(POIT_DIR)

        env_setup = []
        if "TARGET_DATE" in env:
            env_setup.append(f"$env:TARGET_DATE = '{env['TARGET_DATE']}'")
        env_setup.append("$env:PYTHONIOENCODING = 'utf-8'")

        ps_script_content = f"""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FLASK SERVER - Startar..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
{chr(10).join(env_setup)}
Set-Location '{cwd_path}'
& '{python_exe}' '{server_script}'
Write-Host ""
Write-Host "Server avslutad. Tryck valfri tangent..." -ForegroundColor Red
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"""

        import tempfile
        ps_script_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        )
        ps_script_file.write(ps_script_content)
        ps_script_file.close()
        ps_script_path = ps_script_file.name

        # Använd pwsh.exe (PowerShell 7) om tillgängligt, annars powershell.exe
        ps_exe = "pwsh.exe"
        ps_args = [
            ps_exe, "-NoExit", "-ExecutionPolicy", "Bypass",
            "-File", ps_script_path,
        ]

        process = subprocess.Popen(
            ps_args,
            cwd=str(POIT_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )

        log_info("Väntar på server startup (5 sekunder)...")
        time.sleep(5)

        # Verify server responds
        max_retries = 3
        for i in range(max_retries):
            try:
                import urllib.request
                response = urllib.request.urlopen(f"{POIT_SERVER_BASE_URL}/health", timeout=2)
                if response.getcode() == 200:
                    log_info("Server startad och svarar korrekt")
                    return process
            except Exception:
                if i < max_retries - 1:
                    log_info(f"Väntar på server... ({i + 1}/{max_retries})")
                    time.sleep(2)

        log_error("Servern startade inte korrekt")
        return None

    except Exception as e:
        log_error(f"Kunde inte starta server: {e}")
        return None


def run_script(step_name: str, script_path: Path, cwd: Path = None) -> Tuple[int, float]:
    """Kör ett Python-skript. Returnerar (exit code, duration)."""
    if cwd is None:
        cwd = script_path.parent

    log_info(f"Kör [{step_name}]: {script_path.name}")
    start_time = time.time()

    try:
        env = os.environ.copy()
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

        for line in process.stdout:
            print(line.rstrip())

        result_code = process.wait()
        duration = time.time() - start_time
        status = "OK" if result_code == 0 else f"FEL ({result_code})"
        log_info(f"Klar [{step_name}]: {status} ({duration:.1f}s)")
        return result_code, duration

    except Exception as e:
        log_error(f"Körfel [{step_name}]: {e}")
        return 1, time.time() - start_time


def get_target_date_dir(base_dir: Path) -> Optional[Path]:
    """Hämta datummapp baserat på TARGET_DATE eller senaste."""
    if not base_dir.exists():
        return None

    target_date = os.environ.get("TARGET_DATE", "")
    target_path = base_dir / target_date if target_date else None

    if target_path and target_path.exists():
        log_info(f"Använder TARGET_DATE mapp: {target_path.name}")
        return target_path

    # Fallback till senaste
    date_dirs = [
        d for d in base_dir.iterdir()
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8
    ]
    if date_dirs:
        latest = sorted(date_dirs, key=lambda x: x.name)[-1]
        log_info(f"Använder senaste datummapp: {latest.name}")
        return latest

    return None


def create_zip_from_folder(folder: Path, zip_path: Path) -> bool:
    """Skapa zip-fil från mappen."""
    log_info(f"Skapar zip-fil från {folder.name}...")

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder):
                for file in files:
                    file_path = Path(root) / file
                    if file_path == zip_path:
                        continue
                    arcname = file_path.relative_to(folder)
                    zipf.write(file_path, arcname)

        size_mb = zip_path.stat().st_size / 1024 / 1024
        log_info(f"Zip-fil skapad: {zip_path.name} ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        log_error(f"Kunde inte skapa zip: {e}")
        return False


def zip_and_copy_to_dropbox(date_folder: Path) -> bool:
    """
    Zippa mappen från 1_poit/info_server och kopiera till Dropbox.
    Anpassad för att ta mappen från info_server istället för djupanalys.
    """
    try:
        zip_filename = f"{date_folder.name}.zip"
        temp_zip = date_folder.parent / zip_filename

        # Ta bort gammal zip om den finns
        if temp_zip.exists():
            temp_zip.unlink()

        # Skapa zip
        if not create_zip_from_folder(date_folder, temp_zip):
            return False

        # Kopiera till Dropbox
        dropbox_target_dir = Path(r"C:/Users/Propietario/Dropbox/leads")
        if not dropbox_target_dir.exists():
            # Fallback - försök hitta Dropbox
            dropbox_paths = [
                Path.home() / "Dropbox" / "leads",
                Path("D:/Dropbox/leads"),
            ]
            for p in dropbox_paths:
                if p.parent.exists():
                    dropbox_target_dir = p
                    break

        dropbox_target_dir.mkdir(parents=True, exist_ok=True)
        dropbox_zip = dropbox_target_dir / zip_filename

        if dropbox_zip.exists():
            dropbox_zip.unlink()

        # Kopiera till Dropbox
        shutil.copy2(temp_zip, dropbox_zip)
        log_info(f"Zip kopierad till Dropbox: {dropbox_zip}")

        # Kopiera även till data_bundles (för dashboard upload)
        data_bundles_dir = JOCKE_DIR / "data_bundles"
        data_bundles_dir.mkdir(parents=True, exist_ok=True)
        bundle_zip = data_bundles_dir / zip_filename

        if bundle_zip.exists():
            bundle_zip.unlink()
        shutil.copy2(temp_zip, bundle_zip)
        log_info(f"Zip kopierad till data_bundles: {bundle_zip}")

        # Ta bort temporär zip
        try:
            temp_zip.unlink()
        except Exception:
            pass

        return True

    except Exception as e:
        log_error(f"Fel vid zip/kopiering: {e}")
        import traceback
        traceback.print_exc()
        return False


def upload_to_dashboard() -> bool:
    """Ladda upp till dashboard om UPLOAD_SECRET finns."""
    upload_secret = os.environ.get("UPLOAD_SECRET") or os.environ.get("JOCKE_API")
    
    if not upload_secret:
        log_info("Dashboard-upload hoppas över (UPLOAD_SECRET ej satt)")
        return True

    upload_script = DROPBOX_DIR / "upload_to_dashboard.py"
    if not upload_script.exists():
        log_warn(f"Upload-skript saknas: {upload_script}")
        return True

    log_info("Laddar upp till dashboard...")
    exit_code, _ = run_script("dashboard_upload", upload_script, cwd=DROPBOX_DIR)
    return exit_code == 0


def update_config_with_master_number(master_number: int):
    """Uppdatera 1_poit/config.txt med master-nummer."""
    config_poit = POIT_DIR / "config.txt"
    if not config_poit.exists():
        return

    try:
        lines = []
        with open(config_poit, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("MAX_KUN_DAG="):
                    lines.append(f"MAX_KUN_DAG={master_number}\n")
                else:
                    lines.append(line)
        with open(config_poit, "w", encoding="utf-8") as f:
            f.writelines(lines)
        log_info(f"Uppdaterade config med MAX_KUN_DAG={master_number}")
    except Exception as e:
        log_warn(f"Kunde inte uppdatera config: {e}")


def main():
    """Huvudfunktion - kör endast 1_poit och zippa till Dropbox."""
    print()
    print("=" * 60)
    print("  ENBART 1_POIT + ZIP TILL DROPBOX")
    print("  (Hoppar över 2_segment_info och 3_sajt)")
    print("=" * 60)
    print()

    # Parse argument
    master_number = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.isdigit():
            master_number = int(arg)
            log_info(f"Master-nummer: {master_number}")
        elif arg in ("--help", "-h"):
            print(__doc__)
            return 0
        else:
            log_error(f"Okänt argument: {arg}")
            print("Användning: python enbart_1a_main.py [antal]")
            return 1

    # Sätt TARGET_DATE
    target_date_str = datetime.now().strftime("%Y%m%d")
    os.environ["TARGET_DATE"] = target_date_str
    log_info(f"TARGET_DATE: {target_date_str}")

    # Uppdatera config om master_number angavs
    if master_number is not None:
        update_config_with_master_number(master_number)

    server_process = None

    try:
        # STEG 1: Starta server
        print()
        print("-" * 60)
        log_info("STEG 1: SERVER START")
        print("-" * 60)

        server_process = start_server()
        if server_process is None and not check_server_running():
            log_error("Kunde inte starta server - avbryter")
            return 1

        # STEG 2: Scraping
        print()
        print("-" * 60)
        log_info("STEG 2: SCRAPING")
        print("-" * 60)

        date_folder = INFO_SERVER_DIR / target_date_str
        today_json = date_folder / f"kungorelser_{target_date_str}.json"

        if today_json.exists() and today_json.stat().st_size > 0:
            log_info(f"Scraping-data finns redan: {today_json.name}")
        else:
            scrape_script = AUTOMATION_DIR / "scrape_kungorelser.py"
            if scrape_script.exists():
                exit_code, _ = run_script("scraping", scrape_script, cwd=AUTOMATION_DIR)
                if exit_code != 0:
                    log_error("Scraping misslyckades")
                    return 1
            else:
                log_warn(f"Scraping-skript saknas: {scrape_script}")

        # STEG 3: Process raw data
        print()
        print("-" * 60)
        log_info("STEG 3: BEARBETA RÅDATA")
        print("-" * 60)

        process_script = AUTOMATION_DIR / "process_raw_data.py"
        if process_script.exists():
            exit_code, _ = run_script("process_raw_data", process_script, cwd=AUTOMATION_DIR)
            if exit_code != 0:
                log_error("Bearbetning misslyckades")
                return 1
        else:
            log_warn(f"Process-skript saknas: {process_script}")

        # STEG 4: Zippa och kopiera till Dropbox
        # VIKTIGT: Ta mappen från info_server, INTE djupanalys
        print()
        print("-" * 60)
        log_info("STEG 4: ZIPPA OCH KOPIERA TILL DROPBOX")
        print("-" * 60)

        date_folder = get_target_date_dir(INFO_SERVER_DIR)
        if date_folder is None:
            log_error(f"Ingen datummapp hittades i {INFO_SERVER_DIR}")
            return 1

        log_info(f"Zippar mapp: {date_folder}")
        if not zip_and_copy_to_dropbox(date_folder):
            log_error("Zip/kopiering misslyckades")
            return 1

        # STEG 5: Ladda upp till dashboard (valfritt)
        print()
        print("-" * 60)
        log_info("STEG 5: DASHBOARD UPLOAD (valfritt)")
        print("-" * 60)

        upload_to_dashboard()

    except KeyboardInterrupt:
        log_warn("Avbruten av användaren (Ctrl+C)")
        return 1
    except Exception as e:
        log_error(f"Oväntat fel: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if server_process is not None:
            log_info("Servern körs i separat fönster - stäng manuellt om du vill")

    # Sammanfattning
    print()
    print("=" * 60)
    log_info("KLART!")
    print("=" * 60)
    print()
    print("Resultat:")
    print(f"  - Data i: {INFO_SERVER_DIR / target_date_str}")
    print(f"  - Zip i Dropbox: leads/{target_date_str}.zip")
    print(f"  - Zip i data_bundles: 10_jocke/data_bundles/{target_date_str}.zip")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

