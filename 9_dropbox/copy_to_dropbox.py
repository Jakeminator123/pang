#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
copy_to_dropbox.py - Kopiera datum-mapp till Dropbox

Användning:
    python copy_to_dropbox.py [datum-mapp]

Om inget datum anges, försöker vi först TARGET_DATE env var,
sedan senaste mappen från djupanalys/.
"""

import io
import os
import shutil
import sys
import zipfile
import time
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

# Fix encoding for Windows terminal (only when running standalone, not when imported)
if sys.platform == "win32" and __name__ == "__main__":
    try:
        if (
            not isinstance(sys.stdout, io.TextIOWrapper)
            or getattr(sys.stdout, "encoding", None) != "utf-8"
        ):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
    except (AttributeError, ValueError):
        pass  # Already wrapped or buffer closed, skip
    try:
        if (
            not isinstance(sys.stderr, io.TextIOWrapper)
            or getattr(sys.stderr, "encoding", None) != "utf-8"
        ):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
    except (AttributeError, ValueError):
        pass  # Already wrapped or buffer closed, skip

# Find project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEGMENT_DIR = PROJECT_ROOT / "2_segment_info"
DJUPANALYS_DIR = SEGMENT_DIR / "djupanalys"
JOCKE_DIR = PROJECT_ROOT / "10_jocke"


def find_latest_date_folder() -> Path:
    """Hitta senaste datum-mappen i djupanalys."""
    if not DJUPANALYS_DIR.exists():
        raise FileNotFoundError(f"djupanalys mapp saknas: {DJUPANALYS_DIR}")

    date_folders = [
        d
        for d in DJUPANALYS_DIR.iterdir()
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8
    ]

    if not date_folders:
        raise FileNotFoundError("Inga datum-mappar hittades i djupanalys/")

    return sorted(date_folders, key=lambda x: x.name)[-1]


def extract_email_domain(email: str) -> Optional[str]:
    """Extract and normalize email domain."""
    if not email or pd.isna(email):
        return None

    email_str = str(email).strip()
    if not email_str or "@" not in email_str:
        return None

    try:
        domain = email_str.split("@")[1].strip().lower()
        return domain if domain else None
    except (IndexError, AttributeError):
        return None


def find_email_column(df: pd.DataFrame) -> Optional[str]:
    """Find email column in DataFrame."""
    email_columns = ["email", "E-post", "E-post (från content.txt)", "emails_found"]

    for col in email_columns:
        if col in df.columns:
            return col

    # Try case-insensitive search
    for col in df.columns:
        col_lower = str(col).lower()
        if "email" in col_lower or "e-post" in col_lower or "mail" in col_lower:
            return col

    return None


def deduplicate_excel_by_email_domain(excel_path: Path) -> Tuple[int, dict]:
    """
    Deduplicate Excel file by email domain.
    Returns: (rows_removed, domains_deduplicated_dict)
    """
    if not excel_path.exists():
        return 0, {}

    try:
        # Read all sheets up front to avoid re-opening while writing
        with pd.ExcelFile(excel_path, engine="openpyxl") as xls:
            sheet_names = xls.sheet_names
            if not sheet_names:
                return 0, {}
            sheets = {name: xls.parse(name) for name in sheet_names}

        # Process first sheet (usually the main data sheet)
        main_sheet = sheet_names[0]
        df = sheets[main_sheet]
        original_count = len(df)

        # Find email column
        email_col = find_email_column(df)
        if not email_col:
            print(
                f"  Warning: No email column found in {excel_path.name}, skipping deduplication"
            )
            return 0, {}

        print(f"  Found email column: '{email_col}' in sheet '{main_sheet}'")

        # Extract domains and track duplicates
        domains_seen = {}
        rows_to_keep = []
        rows_removed = 0
        domains_deduplicated = {}

        for idx, row in df.iterrows():
            email = row.get(email_col)
            domain = extract_email_domain(email)

            if domain is None:
                rows_to_keep.append(idx)
            elif domain not in domains_seen:
                domains_seen[domain] = idx
                rows_to_keep.append(idx)
            else:
                rows_removed += 1
                if domain not in domains_deduplicated:
                    domains_deduplicated[domain] = []
                domains_deduplicated[domain].append(idx)

        df_deduplicated = df.loc[rows_to_keep].reset_index(drop=True)
        sheets[main_sheet] = df_deduplicated

        print(f"  [DEBUG] Writing deduplicated Excel: {excel_path.name}")
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for sheet_name, sheet_df in sheets.items():
                sheet_df.to_excel(writer, index=False, sheet_name=sheet_name)

        print(
            f"  OK: Deduplicated: {rows_removed} rows removed ({original_count} -> {len(df_deduplicated)})"
        )

        if domains_deduplicated:
            print(f"  Domains deduplicated: {len(domains_deduplicated)}")
            for domain, indices in list(domains_deduplicated.items())[
                :5
            ]:  # Show first 5
                print(f"     - {domain}: {len(indices)} duplicate(s) removed")
            if len(domains_deduplicated) > 5:
                print(f"     ... and {len(domains_deduplicated) - 5} more domains")

        return rows_removed, domains_deduplicated

    except Exception as e:
        print(f"  Error deduplicating {excel_path.name}: {e}")
        import traceback, sys

        traceback.print_exc(file=sys.stdout)
        return 0, {}


def deduplicate_excel_files_in_folder(folder: Path) -> Tuple[int, dict]:
    """
    Find and deduplicate all Excel files in folder.
    Returns: (total_rows_removed, all_domains_deduplicated)
    """
    excel_files = list(folder.glob("*.xlsx"))

    if not excel_files:
        return 0, {}

    print()
    print("=" * 60)
    print("DEDUPLICATING EXCEL FILES BY EMAIL DOMAIN")
    print("=" * 60)

    total_removed = 0
    all_domains = {}

    for excel_file in excel_files:
        print(f"\nProcessing: {excel_file.name}")
        removed, domains = deduplicate_excel_by_email_domain(excel_file)
        total_removed += removed
        all_domains.update(domains)

    print()
    print("=" * 60)
    print(f"OK: Deduplication complete: {total_removed} total rows removed")
    print("=" * 60)

    return total_removed, all_domains


def find_dropbox_folder() -> Path:
    """Hitta Dropbox-mapp."""
    dropbox_paths = [
        Path.home() / "Dropbox",
        Path("C:/Users") / os.getenv("USERNAME", "User") / "Dropbox",
        Path("D:/Dropbox"),
    ]

    for path in dropbox_paths:
        if path.exists() and path.is_dir():
            return path

    raise FileNotFoundError("Hittade ingen Dropbox-mapp")


def create_zip_from_folder(folder: Path, zip_path: Path) -> bool:
    """Skapa zip-fil från hela mappen."""
    print(f"Skapar zip-fil från {folder.name}...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Gå igenom alla filer och mappar
        for root, dirs, files in os.walk(folder):
            for file in files:
                file_path = Path(root) / file
                # Hoppa över om det är zip-filen vi skapar (samma fil eller i samma mapp)
                if file_path == zip_path or file_path.name == zip_path.name:
                    continue

                # Relativ sökväg från mappen som zippas
                arcname = file_path.relative_to(folder)
                zipf.write(file_path, arcname)
                print(f"  Lägger till: {arcname}")

    print(
        f"OK: Zip-fil skapad: {zip_path.name} ({zip_path.stat().st_size / 1024 / 1024:.2f} MB)"
    )
    return True


def copy_date_folder_to_dropbox(date_folder: Path, dropbox_base: Path) -> bool:
    """Zippa datum-mapp och kopiera zip-fil till Dropbox."""
    try:
        # Deduplicate Excel files before copying
        deduplicate_excel_files_in_folder(date_folder)
        time.sleep(0.2)

        # Create final harmonized Excel file
        try:
            from create_final_excel import create_final_excel

            final_path = create_final_excel(date_folder)
            if final_path:
                print(f"Final Excel created: {final_path.name}")
        except ImportError:
            print("Warning: create_final_excel not available")
        except Exception as e:
            print(f"Warning: Could not create final Excel: {e}")
            import traceback, sys

            traceback.print_exc(file=sys.stdout)

        # Skapa zip-fil temporärt (i samma mapp som date_folder)
        zip_filename = f"{date_folder.name}.zip"
        temp_zip = date_folder.parent / zip_filename

        # Ta bort gammal zip om den finns
        if temp_zip.exists():
            print(f"Tar bort gammal zip-fil: {temp_zip.name}")
            temp_zip.unlink()

        # Skapa zip-fil från hela mappen
        if not create_zip_from_folder(date_folder, temp_zip):
            return False

        # Kopiera zip-fil till önskad Dropbox-mapp (direkt till leads)
        dropbox_target_dir = Path(r"C:/Users/Propietario/Dropbox/leads")
        dropbox_target_dir.mkdir(parents=True, exist_ok=True)

        dropbox_zip = dropbox_target_dir / zip_filename

        # Ta bort gammal zip i Dropbox om den finns
        if dropbox_zip.exists():
            print(f"Tar bort gammal zip i Dropbox: {dropbox_zip.name}")
            dropbox_zip.unlink()

        # Kopiera zip till både Dropbox och data_bundles
        data_bundles_dir = JOCKE_DIR / "data_bundles"
        data_bundles_dir.mkdir(parents=True, exist_ok=True)
        bundle_zip = data_bundles_dir / zip_filename

        destinations = [
            (dropbox_zip, "Dropbox"),
            (bundle_zip, "data_bundles"),
        ]

        for dest_path, dest_name in destinations:
            try:
                if dest_path.exists():
                    dest_path.unlink()
                shutil.copy2(temp_zip, dest_path)
                print(f"OK: Zip kopierad till {dest_name}: {dest_path.name}")
            except Exception as e:
                print(f"Warning: Kunde inte kopiera till {dest_name}: {e}")

        print(f"   Storlek: {temp_zip.stat().st_size / 1024 / 1024:.2f} MB")
        time.sleep(0.2)

        # Ta bort temporär zip-fil
        try:
            if temp_zip.exists():
                temp_zip.unlink()
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"[ERROR] copy_date_folder_to_dropbox: {e}")
        import traceback, sys

        traceback.print_exc(file=sys.stdout)
        return False


def main():
    """Huvudfunktion."""
    print("=" * 60)
    print("KOPIERA TILL DROPBOX")
    print("=" * 60)

    # Hitta datum-mapp
    # Priority: 1. CLI arg, 2. TARGET_DATE env var, 3. Latest folder
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        date_folder = DJUPANALYS_DIR / date_str
        if not date_folder.exists():
            print(f"Error: Datum-mapp saknas: {date_folder}")
            return 1
        print(f"[CLI] Använder datum-mapp: {date_folder.name}")
    else:
        # Check TARGET_DATE env var first
        target_date = os.environ.get("TARGET_DATE", "")
        if target_date and (DJUPANALYS_DIR / target_date).exists():
            date_folder = DJUPANALYS_DIR / target_date
            print(f"[TARGET_DATE] Använder datum-mapp: {date_folder.name}")
        else:
            try:
                date_folder = find_latest_date_folder()
                if target_date:
                    print(
                        f"[WARN] TARGET_DATE={target_date} ej funnen, använder senaste: {date_folder.name}"
                    )
                else:
                    print(f"Använder senaste datum-mapp: {date_folder.name}")
            except FileNotFoundError as e:
                print(f"Error: {e}")
                return 1

    print(f"[INFO] Full path: {date_folder}")

    # Hitta Dropbox
    try:
        dropbox_base = find_dropbox_folder()
        print(f"Dropbox-mapp: {dropbox_base}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("Vanliga platser: ~/Dropbox, C:/Users/[USER]/Dropbox, D:/Dropbox")
        return 1

    # Kopiera
    try:
        copy_date_folder_to_dropbox(date_folder, dropbox_base)
        return 0
    except Exception as e:
        print(f"Error: Fel vid kopiering: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
