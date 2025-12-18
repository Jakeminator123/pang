"""
Interaktivt script för att välja företag och generera preview-sajter.
Kör direkt: python interactive_batch.py
"""

import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Lägg all_the_scripts i path för imports (fungerar oavsett cwd eller om scriptet körs via main.py)
scripts_dir = Path(__file__).parent / "all_the_scripts"
sys.path.insert(0, str(scripts_dir))

GENERATE_AVAILABLE = True
try:
    from batch_generate import generate_site_for_company  # type: ignore
except ImportError:
    try:
        batch_mod = importlib.import_module("all_the_scripts.batch_generate")
        generate_site_for_company = batch_mod.generate_site_for_company
    except Exception as e:
        print(f"❌ Fel: Kan inte importera batch_generate: {e}")
        GENERATE_AVAILABLE = False

# Importera evaluate-funktionen för auto-bedömning
EVALUATE_AVAILABLE = True
try:
    from evaluate_companies import evaluate_companies_in_folder  # type: ignore
except ImportError:
    try:
        eval_mod = importlib.import_module("evaluate_companies")
        evaluate_companies_in_folder = eval_mod.evaluate_companies_in_folder
    except Exception as e:
        print(f"❌ Fel: Kan inte importera evaluate_companies: {e}")
        EVALUATE_AVAILABLE = False


# Base katalog för djupanalys
BASE_DJUPANALYS_DIR = (
    Path(__file__).parent.parent / "2_segment_info" / "djupanalys"
)

# Config file
CONFIG_FILE = Path(__file__).parent / "config.txt"


def load_config() -> dict:
    """Ladda konfiguration från config.txt."""
    config = {
        "evaluate": "n",
        "threshold": "0.5",  # Default: 50% confidence minimum
        "audit_enabled": "n",
        "audit_threshold": "0.85",
        "re_input_website_link": "n",
        "re_input_audit": "n",
        "max_sites": "0",    # 0 = ingen gräns
        "max_audits": "0",   # 0 = ingen gräns
    }
    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text(encoding="utf-8").strip()
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue  # Skip empty lines and comments
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    config[key] = value.lower() if key == "evaluate" else value
        except Exception:
            pass
    return config


def load_evaluation_from_folder(company_folder: Path) -> Optional[dict]:
    """Ladda bedömning från evaluation.json i företagsmappen."""
    eval_file = company_folder / "evaluation.json"
    if not eval_file.exists():
        return None
    
    try:
        import json
        return json.loads(eval_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_company_worthy(company_folder: Path, require_evaluation: bool = False, min_confidence: float = 0.0) -> bool:
    """Kontrollera om företaget är 'värdigt' baserat på evaluation.json.
    
    Args:
        company_folder: Företagsmapp att kontrollera
        require_evaluation: Om True, kräv att evaluation.json finns (annars returnera True om saknas)
        min_confidence: Minsta confidence-nivå (0.0-1.0) för att anses värdigt
    """
    evaluation = load_evaluation_from_folder(company_folder)
    if not evaluation:
        # Om require_evaluation=True, kräv att bedömning finns
        if require_evaluation:
            return False
        # Annars, för bakåtkompatibilitet, anta att det är värdigt om ingen bedömning finns
        return True
    
    # Kontrollera om should_get_site är True
    if not evaluation.get("should_get_site", False):
        return False
    
    # Kontrollera confidence-nivå om threshold är satt
    if min_confidence > 0.0:
        confidence = evaluation.get("confidence", 0.0)
        if confidence < min_confidence:
            return False
    
    return True


def find_date_folders(base_dir: Path) -> List[Path]:
    """Hitta alla datum-mappar i djupanalys (t.ex. 20251208)."""
    if not base_dir.exists():
        raise FileNotFoundError(f"Katalogen finns inte: {base_dir}")
    
    folders = [
        d
        for d in base_dir.iterdir()
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8  # YYYYMMDD format
    ]
    
    return sorted(folders, key=lambda p: p.name, reverse=True)  # Nyaste först


def find_company_folders(date_dir: Path, filter_worthy: bool = False, min_confidence: float = 0.0) -> List[Path]:
    """Hitta alla företagsmappar i en datum-mapp (K + siffror + '-25').
    
    Args:
        date_dir: Datum-mapp att söka i
        filter_worthy: Om True, filtrera bort företag som inte är 'värdiga'
                       (kräver att evaluation.json finns och should_get_site=True)
        min_confidence: Minsta confidence-nivå (0.0-1.0) för att anses värdigt
    """
    if not date_dir.exists():
        raise FileNotFoundError(f"Katalogen finns inte: {date_dir}")
    
    folders = [
        d
        for d in date_dir.iterdir()
        if d.is_dir() and d.name.startswith("K") and d.name.endswith("-25")
    ]
    
    # Filtrera bort icke-värdiga företag om begärt
    # När filter_worthy=True, kräv att evaluation.json finns (require_evaluation=True)
    if filter_worthy:
        folders = [f for f in folders if is_company_worthy(f, require_evaluation=True, min_confidence=min_confidence)]
    
    return sorted(folders, key=lambda p: p.name)


def read_company_domain(company_dir: Path) -> tuple[Optional[str], float]:
    """Hämta domän och confidence (0-100) från company_data.json om den finns."""
    data_file = company_dir / "company_data.json"
    if not data_file.exists():
        return None, 0.0
    try:
        import json

        data = json.loads(data_file.read_text(encoding="utf-8"))
        dom = data.get("domain", {}) or {}
        conf = dom.get("confidence", 0) or 0
        try:
            conf = float(conf)
            if conf <= 1.0:
                conf *= 100.0
        except Exception:
            conf = 0.0

        status = dom.get("status", "")
        guess = dom.get("guess")
        best = dom.get("best_domain") or dom.get("best_guess")

        url = None
        if status in ("verified", "match") and guess:
            url = guess
        elif best:
            url = best
        elif guess:
            url = guess

        return url, conf
    except Exception:
        return None, 0.0


def append_mail_footer(
    company_dir: Path,
    preview_url: Optional[str],
    audit_path: Optional[str],
    add_preview: bool,
    add_audit: bool,
):
    mail_file = company_dir / "mail.txt"
    if not mail_file.exists():
        return
    content = mail_file.read_text(encoding="utf-8")
    changed = False

    if add_preview and preview_url and preview_url not in content:
        content += f"\n\nPS: Vi har skapat en kostnadsfri demosajt åt er: {preview_url}"
        changed = True

    if add_audit and audit_path and audit_path not in content:
        content += f"\n\nPS: Vi gjorde en snabb webbplats-audit: {audit_path}"
        changed = True

    if changed:
        mail_file.write_text(content, encoding="utf-8")


def update_mail_ready(
    date_dir: Path,
    updates: List[Dict[str, Optional[str]]],
    add_preview: bool,
    add_audit: bool,
):
    """Uppdatera mail_ready.xlsx med preview/audit om kolumnen 'folder' finns."""
    xlsx = date_dir / "mail_ready.xlsx"
    if not xlsx.exists():
        return
    try:
        import pandas as pd

        df = pd.read_excel(xlsx)
        if "folder" not in df.columns:
            return
        if add_preview and "site_preview_url" not in df.columns:
            df["site_preview_url"] = ""
        if add_audit and "audit_note" not in df.columns:
            df["audit_note"] = ""

        for u in updates:
            folder = u.get("folder")
            if not folder:
                continue
            mask = df["folder"] == folder
            if not mask.any():
                continue
            if add_preview and u.get("preview_url"):
                df.loc[mask, "site_preview_url"] = u["preview_url"]
            if add_audit and u.get("audit_note"):
                df.loc[mask, "audit_note"] = u["audit_note"]

        df.to_excel(xlsx, index=False)
    except Exception:
        # Låt bli att krascha om filen har oväntad struktur
        return


def display_date_folders(folders: List[Path], filter_worthy: bool = False, min_confidence: float = 0.0) -> None:
    """Visa lista över tillgängliga datum-mappar."""
    if not folders:
        print("❌ Inga datum-mappar hittades.")
        return
    
    print(f"\n{'='*60}")
    print(f"📅 Tillgängliga datum-mappar ({len(folders)} st):")
    print(f"{'='*60}")
    
    for idx, folder in enumerate(folders, 1):
        # Räkna företag i varje mapp
        companies_all = find_company_folders(folder, filter_worthy=False)
        companies_filtered = find_company_folders(folder, filter_worthy=filter_worthy, min_confidence=min_confidence)
        date_str = folder.name
        # Formatera datum: YYYYMMDD -> YYYY-MM-DD
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            formatted_date = date_str
        
        if filter_worthy and len(companies_filtered) < len(companies_all):
            print(f"  {idx:2d}. {formatted_date} ({date_str}) - {len(companies_filtered)}/{len(companies_all)} företag (filtrerade)")
        else:
            print(f"  {idx:2d}. {formatted_date} ({date_str}) - {len(companies_filtered)} företag")
    
    print(f"{'='*60}\n")


def display_companies(folders: List[Path], date_folder: str = "") -> None:
    """Visa lista över tillgängliga företag."""
    if not folders:
        print("❌ Inga företagsmappar hittades.")
        return
    
    print(f"\n{'='*60}")
    if date_folder:
        print(f"📁 Företag i {date_folder} ({len(folders)} st):")
    else:
        print(f"📁 Tillgängliga företag ({len(folders)} st):")
    print(f"{'='*60}")
    
    for idx, folder in enumerate(folders, 1):
        # Försök läsa company_name om möjligt
        company_data_file = folder / "company_data.json"
        company_name = folder.name
        if company_data_file.exists():
            try:
                import json
                data = json.loads(company_data_file.read_text(encoding="utf-8"))
                company_name = data.get("company_name", folder.name)
            except:
                pass
        
        print(f"  {idx:2d}. {folder.name} - {company_name}")
    
    print(f"{'='*60}\n")


def prompt_date_selection(folders: List[Path]) -> List[Path]:
    """Fråga användaren att välja datum-mappar."""
    if not folders:
        return []
    
    while True:
        print("Välj datum-mapp:")
        print("  • Skriv nummer (t.ex. '1') för en datum-mapp")
        print("  • Skriv flera nummer med komma (t.ex. '1,3') för flera")
        print("  • Skriv 'all' för alla datum-mappar")
        print("  • Skriv 'q' för att avbryta")
        
        choice = input("\nDitt val: ").strip().lower()
        
        if choice in ("q", "quit", "exit", ""):
            return []
        
        if choice == "all":
            return folders
        
        # Parse nummer
        selected: List[Path] = []
        parts = [p.strip() for p in choice.split(",") if p.strip()]
        
        for part in parts:
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(folders):
                    if folders[idx - 1] not in selected:
                        selected.append(folders[idx - 1])
                else:
                    print(f"⚠️  Nummer {idx} finns inte. Försök igen.")
                    break
            else:
                print(f"⚠️  '{part}' är inte ett giltigt nummer. Försök igen.")
                break
        else:
            # Alla nummer var giltiga
            if selected:
                return selected
        
        # Om vi kom hit, var det ett fel - loopa igen
        print()


def prompt_selection(folders: List[Path]) -> List[Path]:
    """Fråga användaren att välja företag."""
    if not folders:
        return []
    
    while True:
        print("Välj företag:")
        print("  • Skriv nummer (t.ex. '1') för ett företag")
        print("  • Skriv flera nummer med komma (t.ex. '1,3,5') för flera")
        print("  • Skriv 'all' för alla företag")
        print("  • Skriv 'q' för att avbryta")
        
        choice = input("\nDitt val: ").strip().lower()
        
        if choice in ("q", "quit", "exit", ""):
            return []
        
        if choice == "all":
            return folders
        
        # Parse nummer
        selected: List[Path] = []
        parts = [p.strip() for p in choice.split(",") if p.strip()]
        
        for part in parts:
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(folders):
                    if folders[idx - 1] not in selected:
                        selected.append(folders[idx - 1])
                else:
                    print(f"⚠️  Nummer {idx} finns inte. Försök igen.")
                    break
            else:
                print(f"⚠️  '{part}' är inte ett giltigt nummer. Försök igen.")
                break
        else:
            # Alla nummer var giltiga
            if selected:
                return selected
        
        # Om vi kom hit, var det ett fel - loopa igen
        print()


async def generate_with_progress(
    folder: Path,
    companies_dir: Path,
    index: int,
    total: int,
    check_worthy: bool = False,
) -> Optional[dict]:
    """Generera sajt med progress-visning."""
    folder_name = folder.name
    
    # Försök hämta företagsnamn
    company_name = folder_name
    try:
        import json
        company_data_file = folder / "company_data.json"
        if company_data_file.exists():
            data = json.loads(company_data_file.read_text(encoding="utf-8"))
            company_name = data.get("company_name", folder_name)
    except:
        pass
    
    print(f"\n{'─'*60}")
    print(f"[{index}/{total}] 🔄 Genererar sajt för: {company_name} ({folder_name})")
    print(f"{'─'*60}")
    
    # Kontrollera om företaget är värdigt om filtrering är aktiv
    if check_worthy:
        evaluation = load_evaluation_from_folder(folder)
        if evaluation:
            if not evaluation.get("should_get_site", False):
                confidence = int(evaluation.get("confidence", 0) * 100)
                reasoning = evaluation.get("reasoning", "Ingen motivering angiven.")
                print(f"  ⚠️  Företaget är INTE bedömt som värdigt för hemsida!")
                print(f"     Säkerhet: {confidence}%")
                print(f"     Motivering: {reasoning}")
                print(f"  ❌ Hoppar över generering (evaluate=y i config.txt)")
                return None
            else:
                confidence = int(evaluation.get("confidence", 0) * 100)
                print(f"  ✅ Företaget är bedömt som värdigt ({confidence}% säkerhet)")
        else:
            print(f"  ⚠️  Ingen bedömning hittades för detta företag.")
            print(f"     Kör evaluate_companies.py först för att bedöma företaget.")
            print(f"     Eller sätt evaluate=n i config.txt för att tillåta alla företag.")
            print(f"  ❌ Hoppar över generering (evaluate=y kräver bedömning)")
            return None
    
    try:
        result = await generate_site_for_company(
            folder_name,
            companies_dir,
            v0_api_key=None,  # Använder env/standard
            openai_key=None,  # Använder env/standard
            use_openai_enhancement=True,
            use_images=True,
            fetch_actual_costs=True,
        )
        
        preview_url = result.get("preview_url", "N/A")
        cost_info = result.get("cost_info", {})
        estimated_cost = cost_info.get("estimated", {}).get("estimated_cost_usd", 0)
        
        print(f"✅ Klart! Preview URL: {preview_url}")
        print(f"   Kostnad (uppskattad): ${estimated_cost:.6f} USD")
        
        # Visa faktisk kostnad om tillgänglig
        if cost_info.get("actual"):
            actual_cost = cost_info["actual"].get("actual_cost_usd", 0)
            print(f"   Kostnad (faktisk): ${actual_cost:.6f} USD")
        
        return result
        
    except Exception as e:
        print(f"❌ Fel vid generering: {e}")
        return None


async def main():
    """Huvudfunktion för interaktiv batch-generering."""
    print("="*60)
    print("🚀 Interaktiv Preview-Sajt Generator")
    print("="*60)
    
    if not GENERATE_AVAILABLE:
        print("❌ batch_generate saknas. Kontrollera installation/kodbas.")
        return
    if not EVALUATE_AVAILABLE:
        print("❌ evaluate_companies saknas. Kontrollera installation/kodbas.")
        return
    
    # Ladda konfiguration
    config = load_config()
    filter_worthy = config.get("evaluate", "n") == "y"
    
    # Parse threshold (confidence minimum)
    try:
        threshold_str = config.get("threshold", "0.0")
        min_confidence = float(threshold_str)
        if min_confidence < 0.0 or min_confidence > 1.0:
            min_confidence = 0.0
    except (ValueError, TypeError):
        min_confidence = 0.0

    audit_enabled = config.get("audit_enabled", "n") == "y"
    try:
        audit_threshold = float(config.get("audit_threshold", "0.85"))
    except (ValueError, TypeError):
        audit_threshold = 0.85
    re_input_site = config.get("re_input_website_link", "n") == "y"
    re_input_audit = config.get("re_input_audit", "n") == "y"
    try:
        max_sites = int(config.get("max_sites", "0"))
    except (ValueError, TypeError):
        max_sites = 0
    try:
        max_audits = int(config.get("max_audits", "0"))
    except (ValueError, TypeError):
        max_audits = 0
    
    if filter_worthy:
        threshold_pct = int(min_confidence * 100) if min_confidence > 0 else 0
        if threshold_pct > 0:
            print(f"🔍 Filtrering: Endast 'värdiga' företag visas (evaluate=y, threshold={threshold_pct}% i config.txt)")
        else:
            print("🔍 Filtrering: Endast 'värdiga' företag visas (evaluate=y i config.txt)")
    else:
        print("📋 Filtrering: Alla företag visas (evaluate=n i config.txt)")
    
    base_dir = BASE_DJUPANALYS_DIR
    
    if not base_dir.exists():
        print(f"❌ Katalogen finns inte: {base_dir}")
        print("   Kontrollera att sökvägen är korrekt.")
        return
    
    print(f"\n📂 Söker efter datum-mappar i: {base_dir}")
    
    # Steg 1: Hitta datum-mappar
    try:
        date_folders = find_date_folders(base_dir)
    except Exception as e:
        print(f"❌ Fel: {e}")
        return
    
    if not date_folders:
        print("❌ Inga datum-mappar hittades.")
        return
    
    # Visa datum-mappar och låt användaren välja
    display_date_folders(date_folders, filter_worthy=filter_worthy, min_confidence=min_confidence)
    selected_dates = prompt_date_selection(date_folders)
    
    if not selected_dates:
        print("\n👋 Avbrutet. Hejdå!")
        return
    
    # Steg 2: Om evaluate är på, säkerställ bedömning finns – kör auto-bedömning vid behov
    if config.get("evaluate", "n") != "n":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("⚠️  OPENAI_API_KEY saknas, kan inte göra auto-bedömning. Fortsätter utan.")
        else:
            missing_dates: List[Path] = []
            for date_folder in selected_dates:
                companies = find_company_folders(date_folder, filter_worthy=False)
                needs_eval = any(not (c / "evaluation.json").exists() for c in companies)
                if needs_eval:
                    missing_dates.append(date_folder)
            if missing_dates:
                print(f"🔍 Kör auto-bedömning för {len(missing_dates)} datum-mappar...")
                for df in missing_dates:
                    try:
                        await evaluate_companies_in_folder(df, api_key, model="gpt-4o-mini", save_to_folders=True)
                    except Exception as e:
                        print(f"❌ Bedömning misslyckades för {df.name}: {e}")
                print("✅ Auto-bedömning klar.\n")

    # Steg 3: Samla alla företag från valda datum-mappar
    all_companies: List[tuple[Path, Path]] = []  # (company_folder, date_folder)
    companies_without_evaluation = []
    
    for date_folder in selected_dates:
        companies = find_company_folders(date_folder, filter_worthy=filter_worthy, min_confidence=min_confidence)
        for company in companies:
            all_companies.append((company, date_folder))
        
        # Om filtrering är aktiv, räkna även företag utan bedömning eller med låg confidence
        if filter_worthy:
            all_companies_in_folder = find_company_folders(date_folder, filter_worthy=False)
            for company in all_companies_in_folder:
                evaluation = load_evaluation_from_folder(company)
                if not evaluation:
                    companies_without_evaluation.append((company, date_folder))
                elif evaluation.get("should_get_site", False):
                    # Kontrollera om confidence är för låg
                    confidence = evaluation.get("confidence", 0.0)
                    if confidence < min_confidence:
                        companies_without_evaluation.append((company, date_folder))
    
    # Visa varning om filtrering är aktiv och inga företag hittades
    if filter_worthy and not all_companies:
        print("\n⚠️  Inga 'värdiga' företag hittades!")
        if companies_without_evaluation:
            print(f"   {len(companies_without_evaluation)} företag saknar bedömning.")
        print("   Kör evaluate_companies.py först för att bedöma företag.")
        print("   Eller sätt evaluate=n i config.txt för att visa alla företag.")
        return
    
    # Visa varning om några företag saknar bedömning när filtrering är aktiv
    if filter_worthy and companies_without_evaluation:
        print(f"\n⚠️  {len(companies_without_evaluation)} företag saknar bedömning och visas inte:")
        for company, date_folder in companies_without_evaluation[:5]:  # Visa max 5
            company_name = company.name
            try:
                import json
                company_data_file = company / "company_data.json"
                if company_data_file.exists():
                    data = json.loads(company_data_file.read_text(encoding="utf-8"))
                    company_name = data.get("company_name", company.name)
            except:
                pass
            print(f"   • [{date_folder.name}] {company.name} - {company_name}")
        if len(companies_without_evaluation) > 5:
            print(f"   ... och {len(companies_without_evaluation) - 5} till")
        print("   Kör evaluate_companies.py för att bedöma dessa företag.\n")
    
    if not all_companies:
        print("❌ Inga företag hittades i valda datum-mappar.")
        return
    
    # Visa alla företag
    print(f"\n📋 Totalt {len(all_companies)} företag hittades:")
    for idx, (company, date_folder) in enumerate(all_companies, 1):
        company_name = company.name
        try:
            import json
            company_data_file = company / "company_data.json"
            if company_data_file.exists():
                data = json.loads(company_data_file.read_text(encoding="utf-8"))
                company_name = data.get("company_name", company.name)
        except:
            pass
        
        # Visa bedömning om tillgänglig
        evaluation = load_evaluation_from_folder(company)
        status_marker = ""
        if evaluation:
            if evaluation.get("should_get_site"):
                confidence = int(evaluation.get("confidence", 0) * 100)
                status_marker = f" ✅ ({confidence}%)"
            else:
                status_marker = " ❌"
        
        print(f"  {idx:2d}. [{date_folder.name}] {company.name} - {company_name}{status_marker}")
    
    # Låt användaren välja företag
    company_folders = [c[0] for c in all_companies]
    selected_companies = prompt_selection(company_folders)
    
    if not selected_companies:
        print("\n👋 Avbrutet. Hejdå!")
        return

    # Begränsa antal sajter om max_sites > 0
    if max_sites > 0 and len(selected_companies) > max_sites:
        print(f"\nℹ️ Begränsar antal sajter till {max_sites} enligt config (max_sites).")
        selected_companies = selected_companies[:max_sites]
    
    # Bekräfta val
    print(f"\n✅ Du har valt {len(selected_companies)} företag:")
    for folder in selected_companies:
        # Hitta vilken datum-mapp detta företag tillhör
        date_folder_name = "?"
        for company, date_folder in all_companies:
            if company == folder:
                date_folder_name = date_folder.name
                break
        print(f"   • [{date_folder_name}] {folder.name}")
    
    confirm = input("\nFortsätta? (j/n): ").strip().lower()
    if confirm not in ("j", "ja", "y", "yes"):
        print("👋 Avbrutet.")
        return
    
    # Generera sajter
    print(f"\n🚀 Startar generering för {len(selected_companies)} företag...\n")
    
    results = []
    successful = 0
    failed = 0
    mail_ready_updates: Dict[Path, List[Dict[str, Optional[str]]]] = {}
    audit_run_count = 0
    
    for idx, folder in enumerate(selected_companies, 1):
        # Hitta rätt datum-mapp för detta företag
        companies_dir = None
        for company, date_folder in all_companies:
            if company == folder:
                companies_dir = date_folder
                break
        
        if not companies_dir:
            print(f"❌ Kunde inte hitta datum-mapp för {folder.name}")
            failed += 1
            continue
        
        result = await generate_with_progress(
            folder, 
            companies_dir, 
            idx, 
            len(selected_companies),
            check_worthy=filter_worthy
        )
        
        audit_info = None
        preview_url = None

        if result:
            results.append(result)
            successful += 1
            preview_url = result.get("preview_url")

            # Audit-krok
            if audit_enabled:
                if max_audits > 0 and audit_run_count >= max_audits:
                    print(f"AUDIT: {folder.name} skippad (max_audits={max_audits})")
                else:
                    domain_url, dom_conf = read_company_domain(folder)
                    if domain_url and dom_conf >= audit_threshold * 100:
                        try:
                            from all_the_scripts.standalone_audit import run_audit_to_folder

                            audit_info = run_audit_to_folder(domain_url, folder)
                            audit_run_count += 1
                            print(f"AUDIT: {folder.name} {domain_url} OK ({dom_conf:.0f}%)")
                        except Exception as e:
                            audit_run_count += 1
                            print(f"AUDIT: {folder.name} {domain_url} FAIL {e}")
                    else:
                        print(
                            f"AUDIT: {folder.name} skippad (confidence {dom_conf:.0f}% < {audit_threshold*100:.0f}% eller saknar domän)"
                        )

            # Uppdatera mail.txt med länkar om flaggat
            append_mail_footer(
                folder,
                preview_url,
                audit_info.get("audit_file") if audit_info else None,
                add_preview=re_input_site,
                add_audit=re_input_audit,
            )

            # Samla uppdateringar för mail_ready.xlsx
            entry = {
                "folder": folder.name,
                "preview_url": preview_url if re_input_site else None,
                "audit_note": audit_info.get("audit_file") if (re_input_audit and audit_info) else None,
            }
            mail_ready_updates.setdefault(companies_dir, []).append(entry)
        else:
            failed += 1
        
        # Liten paus mellan företag för att undvika rate limits
        if idx < len(selected_companies):
            await asyncio.sleep(2)

    # Uppdatera mail_ready.xlsx per datum
    for date_dir, updates in mail_ready_updates.items():
        if updates:
            update_mail_ready(
                date_dir,
                updates,
                add_preview=re_input_site,
                add_audit=re_input_audit,
            )
    
    # Sammanfattning
    print(f"\n{'='*60}")
    print("📊 Sammanfattning")
    print(f"{'='*60}")
    print(f"Totalt: {len(selected_companies)} företag")
    print(f"✅ Framgångsrika: {successful}")
    print(f"❌ Misslyckade: {failed}")
    
    if results:
        print(f"\n📋 Preview URLs:")
        for result in results:
            folder_name = result.get("folder_name", "N/A")
            preview_url = result.get("preview_url", "N/A")
            print(f"   • {folder_name}: {preview_url}")
    
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Avbrutet av användaren. Hejdå!")
    except Exception as e:
        print(f"\n❌ Oväntat fel: {e}")
        import traceback
        traceback.print_exc()
