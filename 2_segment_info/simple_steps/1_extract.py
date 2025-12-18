#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1_extract.py - Step 1: Data extraction and domain guessing

Simplified version that:
- Copies date folders from source to djupanalys/
- Extracts company info from content.txt (name, orgnr, email, verksamhet, people)
- Generates domain guess from company name (simple heuristics, no AI)
- Saves everything in ONE file: company_data.json per K-folder
- Updates kungorelser_*.xlsx with extracted data

Respects TARGET_DATE environment variable if set.
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# =============================================================================
# CONFIGURATION LOADER
# =============================================================================


def load_config(config_path: Path) -> Dict[str, str]:
    """Load simplified config file."""
    cfg = {}
    if not config_path.exists():
        return cfg

    section = ""
    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].upper()
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip().upper()
            val = val.split("#")[0].strip()  # Remove inline comments
            full_key = f"{section}_{key}" if section else key
            cfg[full_key] = val
    return cfg


def find_pang_root(start: Path) -> Path:
    """Find pang root directory."""
    current = start
    for _ in range(5):
        if (current / "1_poit").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start.parent


# =============================================================================
# DATA EXTRACTION
# =============================================================================


def extract_emails(text: str) -> List[str]:
    """Extract email addresses from text."""
    if not text:
        return []
    emails = set(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text))
    return sorted({e.lower() for e in emails})


def extract_phones(text: str) -> List[str]:
    """Extract Swedish phone numbers from text."""
    if not text:
        return []
    patterns = [
        r"\b0\d{1,3}[- ]?\d{2,3}[- ]?\d{2,3}[- ]?\d{2,4}\b",
        r"\b\+46[- ]?\d{1,3}[- ]?\d{2,3}[- ]?\d{2,3}[- ]?\d{2,4}\b",
    ]
    phones = []
    for pattern in patterns:
        phones.extend(re.findall(pattern, text))
    # Clean and deduplicate
    cleaned = []
    for p in phones:
        p_clean = re.sub(r"[- ]", "", p)
        if len(p_clean) >= 8 and p_clean not in cleaned:
            cleaned.append(p)
    return cleaned[:3]  # Max 3 phones


def extract_people(text: str) -> List[Dict[str, str]]:
    """Extract board members from content.txt."""
    people = []
    if not text:
        return people

    # Pattern: personnummer followed by name
    # Example: 19721024-0391 Ståhl, Johan Fredrik, Servando Bolag AB, Box 5814...
    patterns = [
        (
            r"Styrelseledamot(?:er)?(?:\s*,?\s*verkställande direktör)?[:\s]+(.*?)(?=Styrelsesuppleanter|Firmateckning|$)",
            "Styrelseledamot",
        ),
        (r"Styrelsesuppleanter[:\s]+(.*?)(?=Firmateckning|$)", "Styrelsesuppleant"),
    ]

    for pattern, role in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            section = match.group(1)
            # Extract people with personnummer
            person_pattern = r"(\d{8}-\d{4})\s+([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+(?:\s+[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*),\s+([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+(?:\s+[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*)"
            for m in re.finditer(person_pattern, section):
                personnr, efternamn, fornamn = m.groups()
                full_name = f"{fornamn.strip()} {efternamn.strip()}"
                people.append(
                    {
                        "name": full_name,
                        "role": role,
                        "personnr": personnr[:6] + "-XXXX",  # Mask for privacy
                    }
                )

    # Deduplicate by name
    seen = set()
    unique = []
    for p in people:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)

    return unique[:5]  # Max 5 people


def extract_company_info(text: str) -> Dict[str, str]:
    """Extract structured company info from content.txt."""
    info = {
        "company_name": "",
        "orgnr": "",
        "verksamhet": "",
        "sate": "",
        "address": "",
        "email": "",
        "typ": "",
        "bildat": "",
    }

    if not text:
        return info

    # Company name: "Företagsnamn: X" or from header
    name_match = re.search(r"Företagsnamn[:\s]+([^\n]+)", text, re.IGNORECASE)
    if name_match:
        info["company_name"] = name_match.group(1).strip()
    else:
        # Try header format: "CompanyName AB, 559548-9963"
        header_match = re.search(
            r"([A-ZÀ-ÖØ-Ý][^,\n]+(?:AB|HB|KB|Ek\.\s*för\.?)?)[,\s]+(\d{6}-\d{4})", text
        )
        if header_match:
            info["company_name"] = header_match.group(1).strip()

    # Org.nr
    orgnr_match = re.search(
        r"(?:Org\s*nr|Organisationsnummer)[:\s]+(\d{6}-\d{4})", text, re.IGNORECASE
    )
    if orgnr_match:
        info["orgnr"] = orgnr_match.group(1)
    else:
        # Fallback: find pattern in text
        orgnr_fallback = re.search(r"\b(\d{6}-\d{4})\b", text)
        if orgnr_fallback:
            info["orgnr"] = orgnr_fallback.group(1)

    # Verksamhet
    verk_match = re.search(
        r"Verksamhet[:\s]+([^\n]+(?:\n(?![A-ZÅÄÖ][a-zåäö]*:)[^\n]+)*)",
        text,
        re.IGNORECASE,
    )
    if verk_match:
        info["verksamhet"] = re.sub(r"\s+", " ", verk_match.group(1).strip())[:500]

    # Säte
    sate_match = re.search(r"Säte[:\s]+([^\n,]+)", text, re.IGNORECASE)
    if sate_match:
        info["sate"] = sate_match.group(1).strip()

    # Address
    addr_match = re.search(r"Postadress[:\s]+([^\n]+)", text, re.IGNORECASE)
    if addr_match:
        info["address"] = addr_match.group(1).strip()

    # Email from E-post field
    email_match = re.search(
        r"E-post[:\s]+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
        text,
        re.IGNORECASE,
    )
    if email_match:
        info["email"] = email_match.group(1).lower()

    # Typ
    typ_match = re.search(r"Typ[:\s]+([^\n]+)", text, re.IGNORECASE)
    if typ_match:
        info["typ"] = typ_match.group(1).strip()

    # Bildat
    bildat_match = re.search(r"Bildat[:\s]+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if bildat_match:
        info["bildat"] = bildat_match.group(1)

    return info


# =============================================================================
# DOMAIN GUESSING (Simple heuristics, no AI)
# =============================================================================

GENERIC_EMAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "live.se",
    "icloud.com",
    "me.com",
    "msn.com",
    "telia.com",
    "bredband.net",
    "spray.se",
    "home.se",
    "comhem.se",
    "tele2.se",
}

# Keywords in email domains that indicate accounting firm (bulk registration)
ACCOUNTING_DOMAIN_KEYWORDS = {
    "redovisning", "bokföring", "bokforing", "revision",
    "ekonomi", "accounting", "konto", "skatt", "deklaration",
    "revisionsbyrå", "revisionsbyra", "ekonomibyrå", "ekonomibyra",
}

# Keywords in company names to skip
NAME_EXCLUDE_KEYWORDS = {"förening", "holding", "lagerbolag"}


def should_skip_company(company_name: str, emails: List[str]) -> Tuple[bool, str]:
    """
    Check if company should be skipped (accounting firm registration or excluded name).
    Returns: (should_skip, reason)
    """
    # Check company name for excluded keywords
    if company_name:
        name_lower = company_name.lower()
        for kw in NAME_EXCLUDE_KEYWORDS:
            if kw in name_lower:
                return True, f"name_keyword:{kw}"

    # Check email domain for accounting keywords
    if emails:
        email = emails[0].lower()
        if "@" in email:
            try:
                domain = email.split("@")[1]
                for kw in ACCOUNTING_DOMAIN_KEYWORDS:
                    if kw in domain:
                        return True, f"accounting_domain:{kw}"
            except IndexError:
                pass

    return False, ""


def get_email_category(emails: List[str]) -> str:
    """Categorize email: 'direct' (company domain), 'generic' (gmail etc), or 'unknown'."""
    if not emails:
        return "unknown"
    email = emails[0].lower()
    if "@" not in email:
        return "unknown"
    try:
        domain = email.split("@")[1]
        if domain in GENERIC_EMAIL_DOMAINS:
            return "generic"
        return "direct"
    except IndexError:
        return "unknown"


def normalize_company_name(name: str) -> str:
    """Normalize company name for domain guessing."""
    if not name:
        return ""

    # Lowercase
    name = name.lower()

    # Remove common suffixes
    suffixes = [
        " ab",
        " aktiebolag",
        " hb",
        " handelsbolag",
        " kb",
        " kommanditbolag",
        " ek. för.",
        " ekonomisk förening",
        " i likvidation",
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)]

    # Remove special characters, keep alphanumeric and Swedish chars
    name = re.sub(r"[^\w\såäöÅÄÖ]", "", name)

    # Replace Swedish chars
    replacements = {"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o"}
    for old, new in replacements.items():
        name = name.replace(old, new)

    # Remove spaces and extra whitespace
    name = re.sub(r"\s+", "", name)

    return name[:30]  # Limit length


def guess_domain(company_name: str, emails: List[str]) -> Tuple[str, float, str]:
    """
    Guess domain from company name and emails.
    Returns: (domain, confidence, source)
    """
    # 1. Try to extract from company email (highest confidence)
    for email in emails:
        if "@" in email:
            domain = email.split("@")[1].lower()
            if domain not in GENERIC_EMAIL_DOMAINS:
                return (domain, 0.85, "email")

    # 2. Generate from company name
    normalized = normalize_company_name(company_name)
    if normalized:
        domain = f"{normalized}.se"
        return (domain, 0.4, "company_name")

    return ("", 0.0, "none")


def suggest_alternative_domains(
    company_name: str, primary_domain: str
) -> List[Dict[str, str]]:
    """Generate alternative domain suggestions."""
    alternatives = []
    normalized = normalize_company_name(company_name)

    if not normalized:
        return alternatives

    # Common TLDs
    tlds = [".se", ".com", ".nu"]

    for tld in tlds:
        domain = f"{normalized}{tld}"
        if domain != primary_domain:
            alternatives.append({"domain": domain, "source": "generated"})

    # With common business words
    if len(normalized) < 20:
        for word in ["ab", "grupp", "sweden"]:
            domain = f"{normalized}{word}.se"
            if domain != primary_domain:
                alternatives.append({"domain": domain, "source": "generated"})

    return alternatives[:3]  # Max 3 alternatives


# =============================================================================
# MAIN EXTRACTION LOGIC
# =============================================================================


def process_company_folder(company_dir: Path) -> Optional[Dict]:
    """Process a single K-folder and extract all data."""
    content_file = company_dir / "content.txt"
    if not content_file.exists():
        return None

    try:
        text = content_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Extract all data
    info = extract_company_info(text)
    emails = extract_emails(text)
    phones = extract_phones(text)
    people = extract_people(text)

    # Add email from field if not in list
    if info["email"] and info["email"] not in emails:
        emails.insert(0, info["email"])

    # Check if company should be skipped
    should_skip, skip_reason = should_skip_company(info["company_name"], emails)
    email_category = get_email_category(emails)

    # Guess domain
    domain, confidence, source = guess_domain(info["company_name"], emails)

    # Generate alternatives
    alternatives = (
        suggest_alternative_domains(info["company_name"], domain) if domain else []
    )

    # Build company data
    company_data = {
        "folder": company_dir.name,
        "extracted_at": datetime.now().isoformat(),
        "company_name": info["company_name"],
        "orgnr": info["orgnr"],
        "verksamhet": info["verksamhet"],
        "sate": info["sate"],
        "address": info["address"],
        "typ": info["typ"],
        "bildat": info["bildat"],
        "emails": emails,
        "phones": phones,
        "people": people,
        "domain": {
            "guess": domain,
            "confidence": confidence,
            "source": source,
            "status": "unknown",  # Will be set by step 2
            "alternatives": alternatives,
        },
        # Filtering metadata
        "skip_company": should_skip,
        "skip_reason": skip_reason,
        "email_category": email_category,
    }

    return company_data


def copy_date_folder(src: Path, dst: Path) -> bool:
    """Copy a date folder - copies K-folders even if date folder already exists."""
    if not dst.exists():
        # New folder - copy everything
        try:
            shutil.copytree(src, dst)
            return True
        except Exception as e:
            print(f"Error copying {src.name}: {e}")
            return False

    # Folder exists - copy missing K-folders individually
    copied_any = False
    for item in src.iterdir():
        if item.is_dir() and item.name.startswith("K") and "-" in item.name:
            target = dst / item.name
            if not target.exists():
                try:
                    shutil.copytree(item, target)
                    copied_any = True
                except Exception as e:
                    print(f"Error copying {item.name}: {e}")

    # Also copy other important files if missing
    for pattern in [
        "kungorelser_*.json",
        "kungorelser_*.csv",
        "kungorelser_*.xlsx",
        "companies_*.db",
    ]:
        for src_file in src.glob(pattern):
            dst_file = dst / src_file.name
            if not dst_file.exists():
                try:
                    shutil.copy2(src_file, dst_file)
                    copied_any = True
                except Exception as e:
                    print(f"Error copying {src_file.name}: {e}")

    return copied_any


def convert_csv_to_xlsx(
    csv_path: Path, xlsx_path: Path, delete_csv: bool = True
) -> bool:
    """Convert CSV to XLSX."""
    try:
        # Detect delimiter
        sample = csv_path.read_text(encoding="utf-8", errors="ignore")[:5000]
        sep = ";" if sample.count(";") > sample.count(",") else ","

        df = pd.read_csv(csv_path, dtype=str, sep=sep, encoding="utf-8").fillna("")
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
            df.to_excel(xw, sheet_name="Data", index=False)

        if delete_csv:
            csv_path.unlink()

        return True
    except Exception as e:
        print(f"CSV conversion error: {e}")
        return False


def update_excel_with_data(xlsx_path: Path, companies_data: List[Dict]) -> None:
    """Update Excel with extracted company data."""
    if not xlsx_path.exists():
        return

    try:
        df = pd.read_excel(xlsx_path, sheet_name="Data", engine="openpyxl")
        df = df.fillna("")

        # Create lookup by folder name
        data_by_folder = {c["folder"]: c for c in companies_data if c}

        # Find or create columns
        new_cols = [
            "domain_guess",
            "domain_confidence",
            "emails_found",
            "phones_found",
            "people_count",
        ]
        for col in new_cols:
            if col not in df.columns:
                df[col] = ""

        # Find folder column
        folder_col = None
        for col in ["Mapp", "Kungörelse-id", "kungorelseId"]:
            if col in df.columns:
                folder_col = col
                break

        if folder_col:
            for idx, row in df.iterrows():
                folder = str(row[folder_col]).replace("/", "-").strip()
                if folder in data_by_folder:
                    data = data_by_folder[folder]
                    df.at[idx, "domain_guess"] = data["domain"]["guess"]
                    df.at[idx, "domain_confidence"] = (
                        f"{data['domain']['confidence']:.2f}"
                    )
                    df.at[idx, "emails_found"] = ", ".join(data["emails"][:3])
                    df.at[idx, "phones_found"] = ", ".join(data["phones"][:2])
                    df.at[idx, "people_count"] = len(data["people"])

        # Save back
        with pd.ExcelWriter(
            xlsx_path, engine="openpyxl", mode="a", if_sheet_exists="replace"
        ) as xw:
            df.to_excel(xw, sheet_name="Data", index=False)

    except Exception as e:
        print(f"Excel update error: {e}")


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Main function."""
    root = Path(__file__).resolve().parent.parent
    cfg = load_config(root / "config_simple.txt")

    print("=" * 60)
    print("STEP 1: EXTRACT AND PREPARE DATA")
    print("=" * 60)
    print(f"Working directory: {root}")

    # Find source directory
    pang_root = find_pang_root(root)
    source_dir = cfg.get("PIPELINE_SOURCE_DIR", "1_poit/info_server")
    if Path(source_dir).is_absolute():
        info_server = Path(source_dir)
    else:
        info_server = pang_root / source_dir

    if not info_server.exists():
        print(f"ERROR: Source directory not found: {info_server}")
        return 1

    print(f"Source: {info_server}")

    # Create djupanalys directory
    djupanalys = root / "djupanalys"
    djupanalys.mkdir(exist_ok=True, parents=True)

    # Find date folders
    date_pattern = re.compile(r"^\d{8}$")
    date_dirs = sorted(
        [p for p in info_server.iterdir() if p.is_dir() and date_pattern.match(p.name)],
        key=lambda p: p.name,
        reverse=True,  # Newest first
    )

    if not date_dirs:
        print("No date folders found in source directory")
        return 1

    print(f"Found {len(date_dirs)} date folders")

    # Copy missing folders
    delete_csv = cfg.get("PIPELINE_DELETE_CSV", "y").lower() in (
        "y",
        "yes",
        "true",
        "1",
    )
    copied = 0

    for src_dir in date_dirs:
        dst_dir = djupanalys / src_dir.name
        if copy_date_folder(src_dir, dst_dir):
            print(f"  Copied: {src_dir.name}")
            copied += 1

            # Convert CSV to XLSX if needed
            csv_file = next(dst_dir.glob("kungorelser_*.csv"), None)
            if csv_file:
                xlsx_file = dst_dir / csv_file.name.replace(".csv", ".xlsx")
                if not xlsx_file.exists():
                    if convert_csv_to_xlsx(csv_file, xlsx_file, delete_csv):
                        print("    Converted CSV to XLSX")

    if copied > 0:
        print(f"Copied {copied} new date folders")
    else:
        print("All date folders already exist")

    # Process target date folder (respect TARGET_DATE env var if set)
    target_date = os.environ.get("TARGET_DATE", "")
    all_date_dirs = sorted(
        [p for p in djupanalys.iterdir() if p.is_dir() and date_pattern.match(p.name)]
    )

    if target_date and (djupanalys / target_date).exists():
        latest = djupanalys / target_date
        print(f"\n[TARGET_DATE] Processing specified date: {latest.name}")
    elif all_date_dirs:
        latest = all_date_dirs[-1]
        if target_date:
            print(
                f"\n[WARN] TARGET_DATE={target_date} not found, using latest: {latest.name}"
            )
        else:
            print(f"\nProcessing latest: {latest.name}")
    else:
        print("ERROR: No date folders found in djupanalys")
        return 1

    print(f"[INFO] Date folder path: {latest}")

    # Find company folders (K*)
    company_dirs = [
        p
        for p in latest.iterdir()
        if p.is_dir() and p.name.startswith("K") and "-" in p.name
    ]
    print(f"Found {len(company_dirs)} company folders")

    # Limit if configured
    max_companies = int(cfg.get("PIPELINE_MAX_COMPANIES", "0"))
    if max_companies > 0:
        company_dirs = company_dirs[:max_companies]
        print(f"  (Limited to {max_companies} companies)")

    # Extract data from each company
    companies_data = []
    for i, company_dir in enumerate(company_dirs, 1):
        data = process_company_folder(company_dir)
        if data:
            # Save company_data.json
            data_file = company_dir / "company_data.json"
            data_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            companies_data.append(data)

        if i % 20 == 0:
            print(f"  Processed {i}/{len(company_dirs)} companies...")

    print(f"Extracted data from {len(companies_data)} companies")

    # Update Excel
    xlsx_path = next(latest.glob("kungorelser_*.xlsx"), None)
    if xlsx_path:
        update_excel_with_data(xlsx_path, companies_data)
        print(f"Updated Excel: {xlsx_path.name}")

    # Summary
    with_domain = sum(1 for c in companies_data if c and c["domain"]["guess"])
    with_email = sum(1 for c in companies_data if c and c["emails"])
    skipped = sum(1 for c in companies_data if c and c.get("skip_company"))
    active = len(companies_data) - skipped

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Companies processed: {len(companies_data)}")
    print(f"With domain guess: {with_domain}")
    print(f"With email: {with_email}")
    if skipped > 0:
        print(f"Marked for skip (accounting/excluded): {skipped}")
        print(f"Active companies: {active}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
