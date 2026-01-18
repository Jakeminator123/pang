"""
Script för att bedöma om företag ska få en hemsida.
Går igenom företagsmappar, läser content.txt och använder OpenAI för att avgöra.
"""

import asyncio
import sys
import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

HTTPX_AVAILABLE = True
try:
    import httpx
except ImportError:
    HTTPX_AVAILABLE = False
    # Vi vill inte döda importörer (t.ex. main.py) direkt; hantera i main

# Base katalog för djupanalys
BASE_DJUPANALYS_DIR = (
    Path(__file__).parent.parent / "2_segment_info" / "djupanalys"
)

# Läs konfiguration från config_ny.txt (INI-format)
CONFIG_FILE = Path(__file__).parent / "config_ny.txt"


def load_config() -> Dict[str, str]:
    """Ladda konfiguration från config_ny.txt (enkel key=value format)."""
    cfg: Dict[str, str] = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                # Store both original and uppercase for compatibility
                key = k.strip().lower()
                cfg[key] = v.strip()
                cfg[key.upper()] = v.strip()
    return cfg


# Läs beskrivning från beskrivning.txt
BESKRIVNING_FILE = Path(__file__).parent / "beskrivning.txt"
TARGET_DESCRIPTION = "Ekonomi, konsulter och företag som det 'käns' har lite pengar eller är lite lite intresserade av att expandera."

if BESKRIVNING_FILE.exists():
    try:
        TARGET_DESCRIPTION = BESKRIVNING_FILE.read_text(encoding="utf-8").strip()
    except:
        pass


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
    if filter_worthy:
        folders = [f for f in folders if is_company_worthy(f, require_evaluation=True, min_confidence=min_confidence)]
    
    return sorted(folders, key=lambda p: p.name)


def read_content_txt(folder_path: Path) -> Optional[str]:
    """Läs content.txt från företagsmapp."""
    content_file = folder_path / "content.txt"
    if not content_file.exists():
        return None
    
    try:
        return content_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def get_company_name(folder_path: Path) -> str:
    """Hämta företagsnamn från company_data.json eller använd mappnamn."""
    company_data_file = folder_path / "company_data.json"
    if company_data_file.exists():
        try:
            data = json.loads(company_data_file.read_text(encoding="utf-8"))
            return data.get("company_name", folder_path.name)
        except:
            pass
    return folder_path.name


async def evaluate_company(
    folder_path: Path,
    content_text: str,
    api_key: str,
    model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """
    Bedöm om företaget ska få en hemsida med OpenAI.
    
    Returns:
        Dict med 'should_get_site' (bool), 'reasoning' (str), 'confidence' (float)
    """
    company_name = get_company_name(folder_path)
    
    prompt = f"""Du är en expert på att bedöma vilka företag som är potentiella kunder för webbdesign-tjänster.

MÅLGRUPP:
{TARGET_DESCRIPTION}

FÖRETAGSINFORMATION:
Företagsnamn: {company_name}
Mapp: {folder_path.name}

INNEHÅLL FRÅN BOLAGSVERKET:
{content_text[:3000]}  # Begränsa till 3000 tecken för att hålla kostnaden nere

UPPGIFT:
Bedöm om detta företag är en potentiell kund för webbdesign-tjänster baserat på målgruppen ovan.

Svara ENDAST med JSON i detta format:
{{
  "should_get_site": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "Kort motivering på svenska (max 2-3 meningar)"
}}

Tänk på:
- Verkar företaget ha ekonomiska resurser?
- Är det en bransch som behöver professionell webbnärvaro?
- Verkar företaget vara i en expansionsfas?
- Är det relevant för målgruppen ovan?"""

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Du är en expert på att bedöma potentiella kunder för webbdesign-tjänster. Svara alltid med giltig JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            content = result["choices"][0]["message"]["content"].strip()
            
            # Försök parse JSON (kan vara wrapped i markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            try:
                evaluation = json.loads(content)
                return {
                    "should_get_site": evaluation.get("should_get_site", False),
                    "confidence": evaluation.get("confidence", 0.5),
                    "reasoning": evaluation.get("reasoning", "Ingen motivering angiven."),
                    "error": None
                }
            except json.JSONDecodeError:
                # Fallback om JSON parsing misslyckas
                return {
                    "should_get_site": "true" in content.lower() or "ja" in content.lower(),
                    "confidence": 0.5,
                    "reasoning": content[:200],
                    "error": "Kunde inte parse JSON, använder heuristik"
                }
                
    except Exception as e:
        return {
            "should_get_site": False,
            "confidence": 0.0,
            "reasoning": f"Fel vid bedömning: {e}",
            "error": str(e)
        }


async def evaluate_companies_in_folder(
    date_folder: Path,
    api_key: str,
    model: str = "gpt-4o-mini",
    save_to_folders: bool = True,
    max_approvals: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Bedöm alla företag i en datum-mapp."""
    if max_approvals is None:
        cfg = load_config()
        try:
            max_approvals = int(cfg.get("MAX_TOTAL_JUDGEMENT_APPROVALS", "0"))
        except ValueError:
            max_approvals = 0
    approvals = 0

    companies = find_company_folders(date_folder)
    results = []
    
    print(f"\n📂 Bearbetar {len(companies)} företag i {date_folder.name}...\n")
    
    for idx, company_folder in enumerate(companies, 1):
        company_name = get_company_name(company_folder)
        content_text = read_content_txt(company_folder)

        if max_approvals and approvals >= max_approvals:
            print(f"[{idx}/{len(companies)}] ⏭️  {company_name} - Skippas (max approvals {max_approvals})")
            result = {
                "folder": company_folder.name,
                "company_name": company_name,
                "should_get_site": False,
                "confidence": 0.0,
                "reasoning": f"Skippad: max {max_approvals} godkännanden uppnått",
                "error": "limit_reached",
                "evaluated_at": datetime.now().isoformat(),
            }
            results.append(result)
            if save_to_folders:
                save_evaluation_to_folder(company_folder, result)
            continue
        
        if not content_text:
            print(f"[{idx}/{len(companies)}] ⚠️  {company_name} - Saknar content.txt")
            result = {
                "folder": company_folder.name,
                "company_name": company_name,
                "should_get_site": False,
                "confidence": 0.0,
                "reasoning": "Saknar content.txt",
                "error": "no_content",
                "evaluated_at": None
            }
            results.append(result)
            
            # Spara även om det saknas content.txt
            if save_to_folders:
                save_evaluation_to_folder(company_folder, result)
            continue
        
        print(f"[{idx}/{len(companies)}] 🔍 Bedömer: {company_name}...", end=" ", flush=True)
        
        evaluation = await evaluate_company(company_folder, content_text, api_key, model)
        
        status = "✅" if evaluation["should_get_site"] else "❌"
        confidence_pct = int(evaluation["confidence"] * 100)
        
        print(f"{status} ({confidence_pct}% säkerhet)")

        if evaluation.get("should_get_site"):
            approvals += 1
        
        result = {
            "folder": company_folder.name,
            "company_name": company_name,
            "date_folder": date_folder.name,
            "evaluated_at": datetime.now().isoformat(),
            **evaluation
        }
        results.append(result)
        
        # Spara bedömning i företagsmappen
        if save_to_folders:
            save_evaluation_to_folder(company_folder, result)
        
        # Liten paus för att undvika rate limits
        if idx < len(companies):
            await asyncio.sleep(0.5)
    
    return results


def save_evaluation_to_folder(company_folder: Path, evaluation: Dict[str, Any]):
    """Spara bedömning som evaluation.json i företagsmappen."""
    eval_file = company_folder / "evaluation.json"
    try:
        eval_file.write_text(
            json.dumps(evaluation, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"  ⚠️  Kunde inte spara evaluation.json: {e}")


def load_evaluation_from_folder(company_folder: Path) -> Optional[Dict[str, Any]]:
    """Ladda bedömning från evaluation.json i företagsmappen."""
    eval_file = company_folder / "evaluation.json"
    if not eval_file.exists():
        return None
    
    try:
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


def display_results(results: List[Dict[str, Any]]):
    """Visa resultat i CMD."""
    approved = [r for r in results if r.get("should_get_site")]
    rejected = [r for r in results if not r.get("should_get_site")]
    
    print(f"\n{'='*70}")
    print("📊 RESULTAT")
    print(f"{'='*70}")
    print(f"Totalt bedömda: {len(results)}")
    print(f"✅ Rekommenderas hemsida: {len(approved)}")
    print(f"❌ Rekommenderas INTE hemsida: {len(rejected)}")
    
    if approved:
        avg_confidence = sum(r.get("confidence", 0) for r in approved) / len(approved)
        print(f"📈 Genomsnittlig säkerhet (godkända): {int(avg_confidence * 100)}%")
    
    print(f"{'='*70}\n")
    
    if approved:
        print("✅ FÖRETAG SOM REKOMMENDERAS HEMSIDA:\n")
        for result in approved:
            confidence_pct = int(result.get("confidence", 0) * 100)
            print(f"  • {result['company_name']} ({result['folder']})")
            print(f"    Säkerhet: {confidence_pct}%")
            print(f"    Motivering: {result.get('reasoning', 'Ingen motivering')}")
            print()
    
    if rejected:
        print("❌ FÖRETAG SOM INTE REKOMMENDERAS:\n")
        for result in rejected[:10]:  # Visa max 10 första
            confidence_pct = int(result.get("confidence", 0) * 100)
            print(f"  • {result['company_name']} ({result['folder']}) - {confidence_pct}%")
            if len(rejected) > 10:
                print(f"\n  ... och {len(rejected) - 10} till")
                break
        print()


async def main():
    """Huvudfunktion."""
    print("="*70)
    print("🔍 FÖRETAGS-BEDÖMNING FÖR HEMSIDA")
    print("="*70)
    
    if not HTTPX_AVAILABLE:
        print("❌ httpx saknas. Installera med: pip install httpx")
        return
    
    # Kontrollera API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY saknas i miljövariabler!")
        print("   Sätt den i .env-filen eller som miljövariabel.")
        return
    
    base_dir = BASE_DJUPANALYS_DIR
    
    if not base_dir.exists():
        print(f"❌ Katalogen finns inte: {base_dir}")
        return
    
    print(f"\n📂 Söker efter datum-mappar i: {base_dir}")
    
    # Hitta datum-mappar
    try:
        date_folders = find_date_folders(base_dir)
    except Exception as e:
        print(f"❌ Fel: {e}")
        return
    
    if not date_folders:
        print("❌ Inga datum-mappar hittades.")
        return
    
    # Visa datum-mappar
    print(f"\n📅 Tillgängliga datum-mappar ({len(date_folders)} st):")
    for idx, folder in enumerate(date_folders, 1):
        companies = find_company_folders(folder)
        date_str = folder.name
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            formatted_date = date_str
        print(f"  {idx}. {formatted_date} ({date_str}) - {len(companies)} företag")
    
    # Välj datum-mapp
    print("\nVälj datum-mapp (eller 'all' för alla):")
    choice = input("Ditt val: ").strip().lower()
    
    if choice == "all":
        selected_dates = date_folders
    else:
        try:
            idx = int(choice)
            if 1 <= idx <= len(date_folders):
                selected_dates = [date_folders[idx - 1]]
            else:
                print("❌ Ogiltigt val.")
                return
        except ValueError:
            print("❌ Ange ett nummer eller 'all'.")
            return
    
    # Bedöm företag
    all_results = []
    for date_folder in selected_dates:
        results = await evaluate_companies_in_folder(date_folder, api_key)
        all_results.extend(results)
    
    # Visa resultat
    display_results(all_results)
    
    # Spara till fil (valfritt)
    output_file = Path(__file__).parent / "evaluation_results.json"
    output_file.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"💾 Resultat sparade till: {output_file}")
    
    # Tips om config.txt
    print(f"\n💡 Tips: Sätt 'evaluate=y' i config.txt för att filtrera bort")
    print(f"   icke-värdiga företag i interactive_batch.py")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Avbrutet av användaren.")
    except Exception as e:
        print(f"\n❌ Oväntat fel: {e}")
        import traceback
        traceback.print_exc()
