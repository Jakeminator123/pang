#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_final_excel.py - Create a harmonized final Excel file with multiple sheets

Creates final_<date>.xlsx with sheets:
1. Sammanfattning - Pipeline statistics and overview
2. Huvuddata - All companies with key columns
3. Personer - Parsed board members (förnamn, efternamn, mellannamn, etc.)
4. Mail - Generated mails from mail_ready.xlsx
5. Evaluation - Evaluation results (should_get_site, confidence, preview_url)

Usage:
    from create_final_excel import create_final_excel
    create_final_excel(date_folder)
"""

import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Fix encoding for Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass


def parse_person_string(person_str: str) -> Dict[str, str]:
    """
    Parse a person string into structured data.

    Format examples:
    - "19681029-4063 Jirestig, Eva Susanne Agneta, FÖRENINGSGATAN 4, 372 36 RONNEBY"
    - "Styrelseledamot: 19871105-7136 Witasp, Erik Tomas Björn, TAMMER..."

    Returns dict with: personnummer, efternamn, fornamn, mellannamn, adress, postnummer, ort, titel
    """
    result = {
        "personnummer": "",
        "efternamn": "",
        "fornamn": "",
        "mellannamn": "",
        "adress": "",
        "postnummer": "",
        "ort": "",
        "titel": "",
    }

    if not person_str or pd.isna(person_str):
        return result

    person_str = str(person_str).strip()

    # Check for title prefix (before colon)
    title_match = re.match(r"^([^:]+):\s*(.+)$", person_str)
    if title_match:
        result["titel"] = title_match.group(1).strip()
        person_str = title_match.group(2).strip()

    # Pattern: YYYYMMDD-XXXX followed by name and address
    pnr_pattern = r"^(\d{8}-\d{4})\s+(.+)$"
    pnr_match = re.match(pnr_pattern, person_str)

    if pnr_match:
        result["personnummer"] = pnr_match.group(1)
        rest = pnr_match.group(2)

        # Split by comma - typically: lastname, firstname middle, address, postalcode city
        parts = [p.strip() for p in rest.split(",")]

        if len(parts) >= 1:
            result["efternamn"] = parts[0]

        if len(parts) >= 2:
            # Second part is first name + middle names
            names = parts[1].split()
            if names:
                result["fornamn"] = names[0]
                if len(names) > 1:
                    result["mellannamn"] = " ".join(names[1:])

        if len(parts) >= 3:
            result["adress"] = parts[2]

        if len(parts) >= 4:
            # Last part is postal code + city
            postal_parts = parts[3].split()
            if len(postal_parts) >= 2:
                result["postnummer"] = " ".join(postal_parts[:2])
                result["ort"] = " ".join(postal_parts[2:])
            elif len(postal_parts) == 1:
                result["ort"] = postal_parts[0]
    else:
        # Fallback: just store the whole string
        result["efternamn"] = person_str

    return result


def parse_multiple_persons(
    cell_value: str, role_prefix: str = ""
) -> List[Dict[str, str]]:
    """Parse a cell that may contain multiple persons (separated by newlines or semicolons)."""
    if not cell_value or pd.isna(cell_value):
        return []

    cell_str = str(cell_value).strip()

    # Split by newlines or semicolons
    persons = re.split(r"[\n;]", cell_str)

    results = []
    for person in persons:
        person = person.strip()
        if person:
            parsed = parse_person_string(person)
            if role_prefix and not parsed["titel"]:
                parsed["titel"] = role_prefix
            results.append(parsed)

    return results


def load_evaluation_data(date_folder: Path) -> Dict[str, Dict]:
    """Load evaluation.json from each K-folder."""
    evaluations = {}

    for k_folder in date_folder.iterdir():
        if k_folder.is_dir() and k_folder.name.startswith("K") and "-" in k_folder.name:
            eval_file = k_folder / "evaluation.json"
            if eval_file.exists():
                try:
                    data = json.loads(eval_file.read_text(encoding="utf-8"))
                    evaluations[k_folder.name] = data
                except Exception:
                    pass

            # Also check for preview_url.txt
            preview_file = k_folder / "preview_url.txt"
            if preview_file.exists():
                try:
                    preview_url = preview_file.read_text(encoding="utf-8").strip()
                    if k_folder.name in evaluations:
                        evaluations[k_folder.name]["preview_url"] = preview_url
                    else:
                        evaluations[k_folder.name] = {"preview_url": preview_url}
                except Exception:
                    pass

    return evaluations


def load_company_data(date_folder: Path) -> Dict[str, Dict]:
    """Load company_data.json from each K-folder."""
    companies = {}

    for k_folder in date_folder.iterdir():
        if k_folder.is_dir() and k_folder.name.startswith("K") and "-" in k_folder.name:
            data_file = k_folder / "company_data.json"
            if data_file.exists():
                try:
                    data = json.loads(data_file.read_text(encoding="utf-8"))
                    companies[k_folder.name] = data
                except Exception:
                    pass

    return companies


def create_summary_sheet(
    date_folder: Path,
    main_df: pd.DataFrame,
    mail_df: Optional[pd.DataFrame],
    evaluations: Dict[str, Dict],
) -> pd.DataFrame:
    """Create summary statistics sheet."""
    date_str = date_folder.name

    total_companies = len(main_df)

    # Count domains
    with_domain = 0
    if "domain_verified" in main_df.columns:
        with_domain = main_df["domain_verified"].notna().sum()
    elif "domain_guess" in main_df.columns:
        with_domain = main_df["domain_guess"].notna().sum()

    # Count mails
    mail_count = len(mail_df) if mail_df is not None else 0

    # Count evaluations
    worthy_count = sum(
        1 for e in evaluations.values() if e.get("should_get_site", False)
    )
    with_preview = sum(1 for e in evaluations.values() if e.get("preview_url"))

    summary_data = [
        {"Nyckel": "Datum", "Värde": date_str},
        {"Nyckel": "Skapad", "Värde": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        {"Nyckel": "", "Värde": ""},
        {"Nyckel": "Totalt antal företag", "Värde": total_companies},
        {"Nyckel": "Med domän", "Värde": with_domain},
        {"Nyckel": "Mail genererade", "Värde": mail_count},
        {"Nyckel": "", "Värde": ""},
        {"Nyckel": "Bedömda företag", "Värde": len(evaluations)},
        {"Nyckel": "Värda företag (ska få sajt)", "Värde": worthy_count},
        {"Nyckel": "Med preview-URL", "Värde": with_preview},
    ]

    return pd.DataFrame(summary_data)


def create_huvuddata_sheet(
    main_df: pd.DataFrame, evaluations: Dict[str, Dict], company_data: Dict[str, Dict]
) -> pd.DataFrame:
    """Create main data sheet with all companies."""
    # Start with main DataFrame
    df = main_df.copy()

    # Find folder column
    folder_col = None
    for col in ["Mapp", "Kungörelse-id"]:
        if col in df.columns:
            folder_col = col
            break

    # Add evaluation columns
    df["Ska få sajt"] = ""
    df["Konfidens"] = ""
    df["Preview URL"] = ""

    if folder_col:
        for idx, row in df.iterrows():
            folder = str(row[folder_col]).replace("/", "-").strip()

            # Add evaluation data
            if folder in evaluations:
                eval_data = evaluations[folder]
                df.at[idx, "Ska få sajt"] = (
                    "Ja" if eval_data.get("should_get_site", False) else "Nej"
                )
                df.at[idx, "Konfidens"] = f"{eval_data.get('confidence', 0):.0%}"
                df.at[idx, "Preview URL"] = eval_data.get("preview_url", "")

    # Reorder columns - put important ones first
    priority_cols = [
        "Mapp",
        "Kungörelse-id",
        "Företagsnamn",
        "Org.nr",
        "E-post",
        "domain_verified",
        "domain_guess",
        "Ska få sajt",
        "Konfidens",
        "Preview URL",
    ]

    ordered_cols = []
    for col in priority_cols:
        if col in df.columns:
            ordered_cols.append(col)

    # Add remaining columns
    for col in df.columns:
        if col not in ordered_cols:
            ordered_cols.append(col)

    return df[ordered_cols]


def create_personer_sheet(main_df: pd.DataFrame) -> pd.DataFrame:
    """Create persons sheet with parsed board members."""
    persons_rows = []

    # Find folder column
    folder_col = None
    for col in ["Mapp", "Kungörelse-id"]:
        if col in main_df.columns:
            folder_col = col
            break

    # Board member columns to parse
    board_columns = [
        ("Styrelseledamöter", "Styrelseledamot"),
        ("Styrelsesuppleanter", "Styrelsesuppleant"),
        ("Styrelse (övrigt)", "Styrelse"),
    ]

    for idx, row in main_df.iterrows():
        folder = (
            str(row.get(folder_col, "")).replace("/", "-").strip() if folder_col else ""
        )
        company_name = str(row.get("Företagsnamn", ""))
        org_nr = str(row.get("Org.nr", ""))

        for col_name, role in board_columns:
            if col_name in main_df.columns:
                cell_value = row.get(col_name, "")
                persons = parse_multiple_persons(cell_value, role)

                for person in persons:
                    persons_rows.append(
                        {
                            "Kungörelse-id": folder,
                            "Företagsnamn": company_name,
                            "Org.nr": org_nr,
                            "Roll": person.get("titel", role),
                            "Personnummer": person.get("personnummer", ""),
                            "Efternamn": person.get("efternamn", ""),
                            "Förnamn": person.get("fornamn", ""),
                            "Mellannamn": person.get("mellannamn", ""),
                            "Adress": person.get("adress", ""),
                            "Postnummer": person.get("postnummer", ""),
                            "Ort": person.get("ort", ""),
                        }
                    )

    if not persons_rows:
        # Return empty DataFrame with correct columns
        return pd.DataFrame(
            columns=[
                "Kungörelse-id",
                "Företagsnamn",
                "Org.nr",
                "Roll",
                "Personnummer",
                "Efternamn",
                "Förnamn",
                "Mellannamn",
                "Adress",
                "Postnummer",
                "Ort",
            ]
        )

    return pd.DataFrame(persons_rows)


def create_mail_sheet(mail_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Create mail sheet from mail_ready.xlsx."""
    if mail_df is None or mail_df.empty:
        return pd.DataFrame(
            columns=["Företagsnamn", "Email", "Ämne", "Mail-text", "Status"]
        )

    return mail_df.copy()


def create_evaluation_sheet(
    evaluations: Dict[str, Dict], company_data: Dict[str, Dict]
) -> pd.DataFrame:
    """Create evaluation sheet with all evaluation results."""
    rows = []

    for folder, eval_data in evaluations.items():
        company_name = ""
        if folder in company_data:
            company_name = company_data[folder].get("company_name", "")

        rows.append(
            {
                "Kungörelse-id": folder,
                "Företagsnamn": company_name,
                "Ska få sajt": "Ja"
                if eval_data.get("should_get_site", False)
                else "Nej",
                "Konfidens": f"{eval_data.get('confidence', 0):.0%}",
                "Motivering": eval_data.get("reasoning", ""),
                "Preview URL": eval_data.get("preview_url", ""),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Kungörelse-id",
                "Företagsnamn",
                "Ska få sajt",
                "Konfidens",
                "Motivering",
                "Preview URL",
            ]
        )

    return pd.DataFrame(rows)


def create_final_excel(date_folder: Path) -> Optional[Path]:
    """
    Create final harmonized Excel file with multiple sheets.

    Args:
        date_folder: Path to the date folder (e.g., djupanalys/20251217)

    Returns:
        Path to created file, or None if failed
    """
    print(f"\n{'=' * 60}")
    print("CREATING FINAL HARMONIZED EXCEL")
    print(f"{'=' * 60}")
    print(f"Source: {date_folder}")

    # Find main Excel file
    xlsx_files = list(date_folder.glob("kungorelser_*.xlsx"))
    if not xlsx_files:
        print("ERROR: No kungorelser_*.xlsx found")
        return None

    main_xlsx = xlsx_files[0]
    print(f"Main data: {main_xlsx.name}")

    # Load main data
    try:
        main_df = pd.read_excel(main_xlsx, sheet_name="Data", engine="openpyxl")
        main_df = main_df.fillna("")
        print(f"  Loaded {len(main_df)} rows")
    except Exception as e:
        print(f"ERROR loading main Excel: {e}")
        return None

    # Load mail_ready.xlsx if exists
    mail_df = None
    mail_xlsx = date_folder / "mail_ready.xlsx"
    if mail_xlsx.exists():
        try:
            mail_df = pd.read_excel(mail_xlsx, engine="openpyxl")
            mail_df = mail_df.fillna("")
            print(f"  Mail data: {len(mail_df)} mails")
        except Exception as e:
            print(f"  Warning: Could not load mail_ready.xlsx: {e}")

    # Load evaluation data from K-folders
    evaluations = load_evaluation_data(date_folder)
    print(f"  Evaluations: {len(evaluations)} companies")

    # Load company data
    company_data = load_company_data(date_folder)
    print(f"  Company data: {len(company_data)} companies")

    # Create sheets
    print("\nCreating sheets...")

    summary_df = create_summary_sheet(date_folder, main_df, mail_df, evaluations)
    print("  - Sammanfattning")

    huvuddata_df = create_huvuddata_sheet(main_df, evaluations, company_data)
    print(f"  - Huvuddata ({len(huvuddata_df)} rows)")

    personer_df = create_personer_sheet(main_df)
    print(f"  - Personer ({len(personer_df)} rows)")

    mail_sheet_df = create_mail_sheet(mail_df)
    print(f"  - Mail ({len(mail_sheet_df)} rows)")

    evaluation_df = create_evaluation_sheet(evaluations, company_data)
    print(f"  - Evaluation ({len(evaluation_df)} rows)")

    # Create final Excel file
    final_path = date_folder / f"final_{date_folder.name}.xlsx"

    print(f"\nWriting: {final_path.name}")

    try:
        with pd.ExcelWriter(final_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Sammanfattning", index=False)
            huvuddata_df.to_excel(writer, sheet_name="Huvuddata", index=False)
            personer_df.to_excel(writer, sheet_name="Personer", index=False)
            mail_sheet_df.to_excel(writer, sheet_name="Mail", index=False)
            evaluation_df.to_excel(writer, sheet_name="Evaluation", index=False)

        size_kb = final_path.stat().st_size / 1024
        print(f"OK: Created {final_path.name} ({size_kb:.1f} KB)")
        print(f"{'=' * 60}\n")

        return final_path

    except Exception as e:
        print(f"ERROR writing Excel: {e}")
        return None


def main():
    """Standalone execution - find latest date folder and create final Excel."""
    # Find djupanalys directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    djupanalys_dir = project_root / "2_segment_info" / "djupanalys"

    if not djupanalys_dir.exists():
        print(f"ERROR: djupanalys folder not found: {djupanalys_dir}")
        return 1

    # Find latest date folder
    date_folders = [
        d
        for d in djupanalys_dir.iterdir()
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8
    ]

    if not date_folders:
        print("ERROR: No date folders found in djupanalys/")
        return 1

    latest = sorted(date_folders, key=lambda x: x.name)[-1]
    print(f"Using latest folder: {latest.name}")

    result = create_final_excel(latest)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
