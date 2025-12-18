"""
Interactive script to select company folder and start API server.
Run with: python generator/interactive_server.py
"""

import sys
from pathlib import Path
import os

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    # Try to load .env from project root
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Laddade miljövariabler från {env_path}")
    else:
        # Try app/.env as fallback
        env_path = Path(__file__).parent.parent.parent / "app" / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Laddade miljövariabler från {env_path}")
except ImportError:
    print(
        "⚠️  python-dotenv inte installerad. Installera med: pip install python-dotenv"
    )
    print("   Eller sätt miljövariabler manuellt.")

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from api import app
import uvicorn


def find_date_folders(base_dir: Path) -> list[Path]:
    """Find all date folders in djupanalys (e.g. 20251208)."""
    djupanalys_dir = base_dir / "2_segment_info" / "djupanalys"
    if not djupanalys_dir.exists():
        return []
    
    folders = [
        d
        for d in djupanalys_dir.iterdir()
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8  # YYYYMMDD format
    ]
    
    return sorted(folders, key=lambda p: p.name, reverse=True)  # Newest first


def find_company_folders(date_dir: Path) -> list[Path]:
    """Find all company folders in a date folder (K + numbers + '-25')."""
    folders = []
    for item in date_dir.iterdir():
        if (
            item.is_dir()
            and item.name.startswith("K")
            and item.name.endswith("-25")
        ):
            # Check if it has company data files
            if (item / "company_data.json").exists() or (item / "data.json").exists():
                folders.append(item)
    return sorted(folders, key=lambda x: x.name)


def select_date_folder(date_folders: list[Path]) -> Path | None:
    """Interactive date folder selection."""
    if not date_folders:
        print("❌ Inga datum-mappar hittades!")
        print(f"   Sökväg: {Path(__file__).parent.parent.parent / '2_segment_info' / 'djupanalys'}")
        return None

    print("\n" + "=" * 60)
    print("📅 VÄLJ DATUM-MAPP")
    print("=" * 60)
    print()

    for i, date_folder in enumerate(date_folders, 1):
        companies = find_company_folders(date_folder)
        date_str = date_folder.name
        # Format date: YYYYMMDD -> YYYY-MM-DD
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            formatted_date = date_str
        
        print(f"  {i}. {formatted_date} ({date_str}) - {len(companies)} företag")

    print(f"\n  {len(date_folders) + 1}. Alla datum-mappar (server väntar på requests)")
    print(f"  0. Avbryt")
    print()

    while True:
        try:
            choice = input("Välj nummer: ").strip()
            choice_num = int(choice)

            if choice_num == 0:
                return None
            elif choice_num == len(date_folders) + 1:
                return "all"  # Special value for all folders
            elif 1 <= choice_num <= len(date_folders):
                return date_folders[choice_num - 1]
            else:
                print(f"❌ Ogiltigt val. Välj 0-{len(date_folders) + 1}")
        except ValueError:
            print("❌ Ange ett nummer")
        except KeyboardInterrupt:
            print("\n\nAvbrutet.")
            return None


def select_company_folder(companies: list[Path]) -> Path | None:
    """Interactive company folder selection."""
    if not companies:
        print("❌ Inga företagsmappar hittades!")
        return None

    print("\n" + "=" * 60)
    print("📁 VÄLJ FÖRETAGSMAPP")
    print("=" * 60)
    print()

    for i, folder in enumerate(companies, 1):
        # Try to get company name
        company_name = "Okänt företag"
        try:
            import json

            data_file = folder / "company_data.json"
            if not data_file.exists():
                data_file = folder / "data.json"
            if data_file.exists():
                data = json.loads(data_file.read_text(encoding="utf-8"))
                company_name = data.get("company_name", folder.name)
        except:
            pass

        print(f"  {i}. {folder.name}")
        print(f"     {company_name}")
        print()

    print(f"  {len(companies) + 1}. Alla mappar (server väntar på requests)")
    print(f"  0. Avbryt")
    print()

    while True:
        try:
            choice = input("Välj nummer: ").strip()
            choice_num = int(choice)

            if choice_num == 0:
                return None
            elif choice_num == len(companies) + 1:
                return "all"  # Special value for all folders
            elif 1 <= choice_num <= len(companies):
                return companies[choice_num - 1]
            else:
                print(f"❌ Ogiltigt val. Välj 0-{len(companies) + 1}")
        except ValueError:
            print("❌ Ange ett nummer")
        except KeyboardInterrupt:
            print("\n\nAvbrutet.")
            return None


def main():
    """Main interactive server launcher."""
    base_dir = Path(__file__).parent.parent.parent
    
    # Steg 1: Hitta datum-mappar
    date_folders = find_date_folders(base_dir)
    
    if not date_folders:
        print("❌ Inga datum-mappar hittades!")
        print(f"   Sökväg: {base_dir / '2_segment_info' / 'djupanalys'}")
        return
    
    # Välj datum-mapp
    selected_date = select_date_folder(date_folders)
    
    if selected_date is None:
        print("\nAvbrutet.")
        return
    
    # Steg 2: Hitta företag i vald datum-mapp
    if selected_date == "all":
        # Samla alla företag från alla datum-mappar
        all_companies = []
        for date_folder in date_folders:
            companies = find_company_folders(date_folder)
            all_companies.extend(companies)
        companies = sorted(set(all_companies), key=lambda x: x.name)
    else:
        companies = find_company_folders(selected_date)
    
    if not companies:
        print("❌ Inga företagsmappar hittades i vald datum-mapp!")
        return
    
    # Välj företag
    selected = select_company_folder(companies)
    
    if selected is None:
        print("\nAvbrutet.")
        return

    print("\n" + "=" * 60)
    print("🚀 STARTAR SERVER")
    print("=" * 60)

    if selected == "all":
        print("\n✅ Server startar för ALLA företagsmappar")
        print("   Använd API:et för att generera preview för valfri mapp")
    else:
        print(f"\n✅ Server startar för: {selected.name}")
        print(f"   Mapp: {selected}")

    port = int(os.getenv("PORT", 8000))
    print(f"\n🌐 Server körs på: http://localhost:{port}")
    print(f"📚 API docs: http://localhost:{port}/docs")
    print(
        f"🔗 Preview URL: http://localhost:{port}/preview/{selected.name if selected != 'all' else 'K928253-25'}"
    )
    print("\n" + "=" * 60)
    print("Tryck Ctrl+C för att stoppa servern")
    print("=" * 60 + "\n")

    try:
        uvicorn.run(app, host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\n\n👋 Server stoppad.")


if __name__ == "__main__":
    main()
