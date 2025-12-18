#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_to_sqlite.py - Convert date folder data to SQLite database

Converts Excel files and JSON folders to a single SQLite database for better
querying and performance on the dashboard.

Usage:
    python convert_to_sqlite.py [date_folder]
    
If no date folder is given, uses the latest one in 10_jocke/.
"""

import os
import sys
import io
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd

# Fix encoding for Windows terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOCKE_DIR = PROJECT_ROOT / "10_jocke"


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


def _safe_int(value):
    """Safely convert value to int."""
    if value is None:
        return 0
    try:
        if isinstance(value, str) and not value.strip():
            return 0
        return int(float(str(value)))
    except (ValueError, TypeError):
        return 0


def create_database(db_path: Path):
    """Create SQLite database with schema."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Companies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kungorelse_id TEXT,
            foretagsnamn TEXT,
            org_nr TEXT,
            sate TEXT,
            address TEXT,
            typ TEXT,
            bildat TEXT,
            verksamhet TEXT,
            aktiekapital TEXT,
            räkenskapsår TEXT,
            segment TEXT,
            domain TEXT,
            domain_verified INTEGER,
            emails TEXT,
            phones TEXT,
            phones_found INTEGER,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(kungorelse_id)
        )
    """)
    
    # People table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kungorelse_id TEXT,
            foretagsnamn TEXT,
            org_nr TEXT,
            personnummer TEXT,
            efternamn TEXT,
            fornamn TEXT,
            mellannamn TEXT,
            adress TEXT,
            postnummer TEXT,
            ort TEXT,
            titel TEXT,
            roll TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Company details table (from JSON folders)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kungorelse_id TEXT UNIQUE,
            folder TEXT,
            extracted_at TEXT,
            company_name TEXT,
            orgnr TEXT,
            verksamhet TEXT,
            sate TEXT,
            address TEXT,
            typ TEXT,
            bildat TEXT,
            emails TEXT,
            phones TEXT,
            domain_guess TEXT,
            domain_confidence REAL,
            domain_status TEXT,
            evaluation_data TEXT,
            content_html TEXT,
            content_txt TEXT,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_org_nr ON companies(org_nr)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_kungorelse_id ON companies(kungorelse_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_people_kungorelse_id ON people(kungorelse_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_people_personnummer ON people(personnummer)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_details_kungorelse_id ON company_details(kungorelse_id)")
    
    conn.commit()
    return conn


def load_excel_data(excel_path: Path, conn: sqlite3.Connection):
    """Load data from Excel file into database."""
    if not excel_path.exists():
        print(f"⚠️  Excel file not found: {excel_path}")
        return
    
    print(f"Reading Excel: {excel_path.name}")
    workbook = pd.ExcelFile(excel_path)
    
    cursor = conn.cursor()
    
    # Process main sheet (Huvuddata or first sheet)
    main_sheet_name = None
    for sheet_name in workbook.sheet_names:
        if 'Huvuddata' in sheet_name or sheet_name == workbook.sheet_names[0]:
            main_sheet_name = sheet_name
            break
    
    if main_sheet_name:
        df = pd.read_excel(excel_path, sheet_name=main_sheet_name)
        
        for _, row in df.iterrows():
            # Prepare company data
            company_data = {
                'kungorelse_id': str(row.get('Kungörelse-id', '')),
                'foretagsnamn': str(row.get('Företagsnamn', '')),
                'org_nr': str(row.get('Org.nr', '')),
                'sate': str(row.get('Säte', '')),
                'address': str(row.get('Postadress', '')),
                'typ': str(row.get('Typ', '')),
                'bildat': str(row.get('Bildat', '')),
                'verksamhet': str(row.get('Verksamhet', '')),
                'aktiekapital': str(row.get('Aktiekapital', '')),
                'räkenskapsår': str(row.get('Räkenskapsår', '')),
                'segment': str(row.get('Segment', '')),
                'domain': str(row.get('domain', '')),
                'domain_verified': 1 if row.get('domain_verified') in [True, 'true', 'True', 1] else 0,
                'emails': str(row.get('E-post', '')),
                'phones': str(row.get('Telefon', '')),
                'phones_found': _safe_int(row.get('phones_found', 0)),
                'raw_data': json.dumps(row.to_dict(), ensure_ascii=False, default=str)
            }
            
            # Insert or update company
            cursor.execute("""
                INSERT OR REPLACE INTO companies 
                (kungorelse_id, foretagsnamn, org_nr, sate, address, typ, bildat, 
                 verksamhet, aktiekapital, räkenskapsår, segment, domain, domain_verified,
                 emails, phones, phones_found, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_data['kungorelse_id'],
                company_data['foretagsnamn'],
                company_data['org_nr'],
                company_data['sate'],
                company_data['address'],
                company_data['typ'],
                company_data['bildat'],
                company_data['verksamhet'],
                company_data['aktiekapital'],
                company_data['räkenskapsår'],
                company_data['segment'],
                company_data['domain'],
                company_data['domain_verified'],
                company_data['emails'],
                company_data['phones'],
                company_data['phones_found'],
                company_data['raw_data']
            ))
    
    # Process Personer sheet
    if 'Personer' in workbook.sheet_names:
        people_df = pd.read_excel(excel_path, sheet_name='Personer')
        
        for _, row in people_df.iterrows():
            cursor.execute("""
                INSERT INTO people 
                (kungorelse_id, foretagsnamn, org_nr, personnummer, efternamn, fornamn,
                 mellannamn, adress, postnummer, ort, titel, roll)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(row.get('kungörelse_id', '')),
                str(row.get('företagsnamn', '')),
                str(row.get('org_nr', '')),
                str(row.get('personnummer', '')),
                str(row.get('efternamn', '')),
                str(row.get('fornamn', '')),
                str(row.get('mellannamn', '')),
                str(row.get('adress', '')),
                str(row.get('postnummer', '')),
                str(row.get('ort', '')),
                str(row.get('titel', '')),
                str(row.get('roll', ''))
            ))
    
    conn.commit()
    print(f"✅ Loaded Excel data into database")


def load_json_folders(date_folder: Path, conn: sqlite3.Connection):
    """Load data from JSON folders into database."""
    cursor = conn.cursor()
    
    # Find all K*-folders
    json_folders = [d for d in date_folder.iterdir() 
                   if d.is_dir() and d.name.startswith('K')]
    
    if not json_folders:
        print("⚠️  No JSON folders found")
        return
    
    print(f"Processing {len(json_folders)} JSON folders...")
    
    loaded = 0
    for folder in json_folders:
        try:
            company_data_path = folder / "company_data.json"
            data_json_path = folder / "data.json"
            evaluation_path = folder / "evaluation.json"
            content_html_path = folder / "content.html"
            content_txt_path = folder / "content.txt"
            
            if not company_data_path.exists():
                continue
            
            # Load company_data.json
            with open(company_data_path, 'r', encoding='utf-8') as f:
                company_data = json.load(f)
            
            # Load other files if they exist
            data_json = None
            if data_json_path.exists():
                with open(data_json_path, 'r', encoding='utf-8') as f:
                    data_json = json.load(f)
            
            evaluation_data = None
            if evaluation_path.exists():
                with open(evaluation_path, 'r', encoding='utf-8') as f:
                    evaluation_data = json.load(f)
            
            content_html = None
            if content_html_path.exists():
                with open(content_html_path, 'r', encoding='utf-8') as f:
                    content_html = f.read()
            
            content_txt = None
            if content_txt_path.exists():
                with open(content_txt_path, 'r', encoding='utf-8') as f:
                    content_txt = f.read()
            
            # Extract domain info
            domain_info = company_data.get('domain', {})
            
            cursor.execute("""
                INSERT OR REPLACE INTO company_details
                (kungorelse_id, folder, extracted_at, company_name, orgnr, verksamhet,
                 sate, address, typ, bildat, emails, phones, domain_guess, domain_confidence,
                 domain_status, evaluation_data, content_html, content_txt, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_data.get('folder', '').replace('-25', ''),
                company_data.get('folder', ''),
                company_data.get('extracted_at', ''),
                company_data.get('company_name', ''),
                company_data.get('orgnr', ''),
                company_data.get('verksamhet', ''),
                company_data.get('sate', ''),
                company_data.get('address', ''),
                company_data.get('typ', ''),
                company_data.get('bildat', ''),
                json.dumps(company_data.get('emails', []), ensure_ascii=False),
                json.dumps(company_data.get('phones', []), ensure_ascii=False),
                domain_info.get('guess', ''),
                domain_info.get('confidence', 0.0),
                domain_info.get('status', ''),
                json.dumps(evaluation_data, ensure_ascii=False) if evaluation_data else None,
                content_html,
                content_txt,
                json.dumps(company_data, ensure_ascii=False)
            ))
            
            loaded += 1
            
        except Exception as e:
            print(f"⚠️  Error processing {folder.name}: {e}")
            continue
    
    conn.commit()
    print(f"✅ Loaded {loaded} company details from JSON folders")


def main():
    """Main function."""
    print("=" * 60)
    print("CONVERT TO SQLITE")
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
    
    # Create database
    db_path = date_folder / "data.db"
    print(f"\nCreating database: {db_path.name}")
    conn = create_database(db_path)
    
    try:
        # Load Excel data
        excel_path = date_folder / "jocke.xlsx"
        if not excel_path.exists():
            excel_path = date_folder / f"kungorelser_{date_folder.name}.xlsx"
        
        if excel_path.exists():
            load_excel_data(excel_path, conn)
        
        # Load JSON folders
        load_json_folders(date_folder, conn)
        
        # Get stats
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM companies")
        company_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM people")
        people_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM company_details")
        details_count = cursor.fetchone()[0]
        
        print()
        print("✅ Conversion complete!")
        print(f"   - Companies: {company_count}")
        print(f"   - People: {people_count}")
        print(f"   - Company details: {details_count}")
        print(f"   - Database: {db_path}")
        
        # Create ZIP file with important data
        print()
        print("Creating ZIP file...")
        import zipfile
        import shutil
        
        zip_path = date_folder / f"{date_folder.name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add database
            if db_path.exists():
                zipf.write(db_path, f"{date_folder.name}/data.db")
            # Add Excel files
            excel_files = [
                date_folder / "jocke.xlsx",
                date_folder / f"kungorelser_{date_folder.name}.xlsx"
            ]
            for excel_file in excel_files:
                if excel_file.exists():
                    zipf.write(excel_file, f"{date_folder.name}/{excel_file.name}")
        
        print(f"✅ Created ZIP: {zip_path.name}")
        
        # Copy to persistent disk if it exists (Render.com)
        persistent_disk = Path("/var/data")
        if persistent_disk.exists() and persistent_disk.is_dir():
            persistent_date_dir = persistent_disk / date_folder.name
            persistent_date_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy database
            if db_path.exists():
                persistent_db = persistent_date_dir / "data.db"
                shutil.copy2(db_path, persistent_db)
                print(f"✅ Copied database to persistent disk: {persistent_db}")
            
            # Copy ZIP
            persistent_zip = persistent_date_dir / zip_path.name
            shutil.copy2(zip_path, persistent_zip)
            print(f"✅ Copied ZIP to persistent disk: {persistent_zip}")
            
            # Copy Excel files
            for excel_file in excel_files:
                if excel_file.exists():
                    persistent_excel = persistent_date_dir / excel_file.name
                    shutil.copy2(excel_file, persistent_excel)
                    print(f"✅ Copied {excel_file.name} to persistent disk")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

