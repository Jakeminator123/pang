#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_board_data.py - Parse and restructure board member data in Excel files

Parses columns:
- R: Styrelseledamöter (Board members)
- S: Styrelsesuppleanter (Deputy board members)
- T: Styrelse (övrigt) (Other board roles)

Format pattern:
  [Title:] YYYYMMDD-XXXX Lastname, Firstname Middle, ADDRESS, POSTAL_CODE CITY

Creates new columns for each parsed field and saves as "jocke.xlsx".

Usage:
    python process_board_data.py [date_folder]
    
If no date folder is given, uses the latest one in 10_jocke/.
"""

import os
import sys
import io
import re
import zipfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import pandas as pd

# Fix encoding for Windows terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOCKE_DIR = PROJECT_ROOT / "10_jocke"
DJUPANALYS_DIR = PROJECT_ROOT / "2_segment_info" / "djupanalys"


def find_latest_date_folder() -> Path:
    """Find latest date folder in 10_jocke."""
    if not JOCKE_DIR.exists():
        raise FileNotFoundError(f"10_jocke folder missing: {JOCKE_DIR}")
    
    date_folders = [
        d for d in JOCKE_DIR.iterdir() 
        if d.is_dir() and d.name.isdigit() and len(d.name) == 8
    ]
    
    if not date_folders:
        raise FileNotFoundError("No date folders found in 10_jocke/")
    
    return sorted(date_folders, key=lambda x: x.name)[-1]


def parse_person_string(person_str: str) -> Dict[str, str]:
    """
    Parse a person string into structured data.
    
    Format examples:
    - "19681029-4063 Jirestig, Eva Susanne Agneta, FÖRENINGSGATAN 4 LGH 1201, 372 36 RONNEBY"
    - "Styrelseledamot, verkställande direktör: 19871105-7136 Witasp, Erik Tomas Björn, TAMMER..."
    
    Returns dict with: personnummer, efternamn, fornamn, mellannamn, adress, postnummer, ort, titel
    """
    result = {
        'personnummer': '',
        'efternamn': '',
        'fornamn': '',
        'mellannamn': '',
        'adress': '',
        'postnummer': '',
        'ort': '',
        'titel': ''
    }
    
    if not person_str or pd.isna(person_str):
        return result
    
    person_str = str(person_str).strip()
    
    # Check for title prefix (before colon)
    title_match = re.match(r'^([^:]+):\s*(.+)$', person_str)
    if title_match:
        result['titel'] = title_match.group(1).strip()
        person_str = title_match.group(2).strip()
    
    # Pattern: YYYYMMDD-XXXX followed by name and address
    # Format: personnummer efternamn, förnamn mellannamn, adress, postnummer ort
    pnr_pattern = r'^(\d{8}-\d{4})\s+(.+)$'
    pnr_match = re.match(pnr_pattern, person_str)
    
    if pnr_match:
        result['personnummer'] = pnr_match.group(1)
        rest = pnr_match.group(2)
        
        # Split by comma - typically: lastname, firstname middle, address, postalcode city
        parts = [p.strip() for p in rest.split(',')]
        
        if len(parts) >= 1:
            result['efternamn'] = parts[0]
        
        if len(parts) >= 2:
            # Second part is first name + middle names
            names = parts[1].split()
            if names:
                result['fornamn'] = names[0]
                if len(names) > 1:
                    result['mellannamn'] = ' '.join(names[1:])
        
        if len(parts) >= 3:
            result['adress'] = parts[2]
        
        if len(parts) >= 4:
            # Last part is postal code + city
            postal_parts = parts[3].split()
            if len(postal_parts) >= 2:
                # Postal code is typically "XXX XX" (two parts)
                result['postnummer'] = ' '.join(postal_parts[:2])
                result['ort'] = ' '.join(postal_parts[2:])
            elif len(postal_parts) == 1:
                result['ort'] = postal_parts[0]
    else:
        # Fallback: just store the whole string
        result['efternamn'] = person_str
    
    return result


def parse_multiple_persons(cell_value: str, role_prefix: str = '') -> List[Dict[str, str]]:
    """
    Parse a cell that may contain multiple persons (separated by newlines or semicolons).
    """
    if not cell_value or pd.isna(cell_value):
        return []
    
    cell_str = str(cell_value).strip()
    
    # Split by newlines or semicolons
    persons = re.split(r'[\n;]', cell_str)
    
    results = []
    for person in persons:
        person = person.strip()
        if person:
            parsed = parse_person_string(person)
            if role_prefix and not parsed['titel']:
                parsed['titel'] = role_prefix
            results.append(parsed)
    
    return results


def process_excel_file(excel_path: Path) -> Path:
    """
    Process an Excel file and create a restructured version.
    
    Returns path to the new file.
    """
    print(f"Reading: {excel_path.name}")
    df = pd.read_excel(excel_path)
    
    # Columns to parse
    board_columns = {
        'Styrelseledamöter': 'Styrelseledamot',
        'Styrelsesuppleanter': 'Styrelsesuppleant',
        'Styrelse (övrigt)': ''
    }
    
    # Create new columns for parsed data
    new_columns = [
        'person_personnummer', 'person_efternamn', 'person_fornamn',
        'person_mellannamn', 'person_adress', 'person_postnummer',
        'person_ort', 'person_titel', 'person_roll'
    ]
    
    # Initialize new columns
    for col in new_columns:
        df[col] = ''
    
    # Process each row
    all_persons_data = []
    
    for idx, row in df.iterrows():
        row_persons = []
        
        for col_name, default_role in board_columns.items():
            if col_name in df.columns:
                cell_value = row.get(col_name)
                persons = parse_multiple_persons(cell_value, default_role)
                for p in persons:
                    p['roll'] = default_role if not p['titel'] else p['titel']
                row_persons.extend(persons)
        
        # Store first person's data in the main row
        if row_persons:
            first = row_persons[0]
            df.at[idx, 'person_personnummer'] = first['personnummer']
            df.at[idx, 'person_efternamn'] = first['efternamn']
            df.at[idx, 'person_fornamn'] = first['fornamn']
            df.at[idx, 'person_mellannamn'] = first['mellannamn']
            df.at[idx, 'person_adress'] = first['adress']
            df.at[idx, 'person_postnummer'] = first['postnummer']
            df.at[idx, 'person_ort'] = first['ort']
            df.at[idx, 'person_titel'] = first['titel']
            df.at[idx, 'person_roll'] = first.get('roll', '')
        
        # Collect all persons for the secondary sheet
        for p in row_persons:
            all_persons_data.append({
                'kungörelse_id': row.get('Kungörelse-id', ''),
                'företagsnamn': row.get('Företagsnamn', ''),
                'org_nr': row.get('Org.nr', ''),
                **p
            })
    
    # Create persons DataFrame
    persons_df = pd.DataFrame(all_persons_data)
    
    # Output path
    output_path = excel_path.parent / "jocke.xlsx"
    
    # Write to Excel with multiple sheets
    print(f"Writing: {output_path.name}")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Huvuddata', index=False)
        if not persons_df.empty:
            persons_df.to_excel(writer, sheet_name='Personer', index=False)
    
    print(f"✅ Created: {output_path}")
    print(f"   - Huvuddata: {len(df)} rows")
    print(f"   - Personer: {len(persons_df)} rows")
    
    return output_path


def add_to_zip(zip_path: Path, file_to_add: Path, arcname: str = None):
    """Add a file to an existing zip archive."""
    if not zip_path.exists():
        print(f"⚠️  Zip file not found: {zip_path}")
        return False
    
    if arcname is None:
        arcname = file_to_add.name
    
    # Read existing zip and add new file
    import tempfile
    
    temp_zip = zip_path.parent / f"{zip_path.stem}_temp.zip"
    
    with zipfile.ZipFile(zip_path, 'r') as zip_read:
        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zip_write:
            # Copy existing files
            for item in zip_read.infolist():
                if item.filename != arcname:  # Skip if file already exists
                    zip_write.writestr(item, zip_read.read(item.filename))
            
            # Add new file
            zip_write.write(file_to_add, arcname)
    
    # Replace original with temp
    zip_path.unlink()
    temp_zip.rename(zip_path)
    
    print(f"✅ Added {arcname} to {zip_path.name}")
    return True


def main():
    """Main function."""
    print("=" * 60)
    print("PROCESS BOARD DATA")
    print("=" * 60)
    
    # Find date folder
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        date_folder = JOCKE_DIR / date_str
        if not date_folder.exists():
            print(f"❌ Date folder missing: {date_folder}")
            return 1
    else:
        try:
            date_folder = find_latest_date_folder()
            print(f"Using latest date folder: {date_folder.name}")
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return 1
    
    # Find Excel file
    excel_files = list(date_folder.glob("kungorelser_*.xlsx"))
    if not excel_files:
        print(f"❌ No kungorelser_*.xlsx found in {date_folder}")
        return 1
    
    excel_file = excel_files[0]
    print(f"Processing: {excel_file}")
    
    # Process the file
    try:
        output_file = process_excel_file(excel_file)
    except Exception as e:
        print(f"❌ Error processing file: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Add to zip in djupanalys
    zip_path = DJUPANALYS_DIR / f"{date_folder.name}.zip"
    if zip_path.exists():
        try:
            add_to_zip(zip_path, output_file, f"{date_folder.name}/jocke.xlsx")
        except Exception as e:
            print(f"⚠️  Could not add to zip: {e}")
    else:
        print(f"⚠️  Zip file not found: {zip_path}")
    
    # Convert to SQLite
    print()
    print("Converting to SQLite...")
    try:
        convert_script = JOCKE_DIR / "convert_to_sqlite.py"
        if convert_script.exists():
            import subprocess
            result = subprocess.run(
                [sys.executable, str(convert_script), date_folder.name],
                capture_output=True,
                text=True,
                cwd=str(JOCKE_DIR)
            )
            if result.returncode == 0:
                print("✅ SQLite database created")
            else:
                print(f"⚠️  SQLite conversion warning: {result.stderr}")
        else:
            print("⚠️  convert_to_sqlite.py not found, skipping SQLite conversion")
    except Exception as e:
        print(f"⚠️  Could not convert to SQLite: {e}")
    
    print()
    print("✅ Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

