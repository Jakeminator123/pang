# -*- coding: utf-8 -*-
"""
process_raw_data.py

Bearbetar bolagsdata från info_server:
- Hittar dagmapp (t.ex. info_server/20251012) och registerfilen kungorelser_YYYYMMDD.json
- Läser undermappar (Kxxxxxx-25) och parsar content.txt
- Skapar CSV + SQLite

ZIP skapas av copy_to_dropbox.py i slutet av pipelinen.

Kräver: Python 3.8+, pandas
Windows 11-kompatibelt.
"""

import csv
import glob
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Fixa encoding för Windows-terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd

# -------------------------
# Hjälpfunktioner (path/IO)
# -------------------------

CANDIDATE_CONTENT_NAMES = [
    "content.txt",
    "context.txt",
    "centext.txt",
]  # hantera stavfel/varianter

# Base directory pointing to 1_poit root
BASE_DIR = Path(__file__).parent.parent.resolve()

# Keywords in company names to exclude
NAME_EXCLUDE_KEYWORDS = (
    "förening", "holding", "lagerbolag", "lagerbolaget", "startplattan",
    "stiftelse", "bostadsrättsförening", "brf ", "ideell", "kapital"
)

# Regex patterns for "shelf companies" (lagerbolag)
LAGERBOLAG_PATTERNS = [
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+\d{5,6}\s+Aktiebolag$", re.IGNORECASE),
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+[A-Z]\s+\d{4,6}\s+AB$", re.IGNORECASE),
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+\d{4,6}\s+AB$", re.IGNORECASE),
]


def normalize_company_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    collapsed = re.sub(r"\s+", "", name).lower()
    collapsed = re.sub(r"\d+", "", collapsed)
    return collapsed or None


def should_skip_company(name: Optional[str]) -> bool:
    """Check if company should be skipped based on name patterns."""
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    
    # Check keywords
    if any(keyword in lowered for keyword in NAME_EXCLUDE_KEYWORDS):
        return True
    
    # Check lagerbolag patterns (e.g., "Startplattan 201499 Aktiebolag", "Lagerbolaget C 28068 AB")
    stripped = name.strip()
    for pattern in LAGERBOLAG_PATTERNS:
        if pattern.match(stripped):
            return True
    
    return False


def deduplicate_companies(companies: List[dict]) -> Tuple[List[dict], Dict[str, int]]:
    stats = {
        "removed": 0,
        "duplicate_ids": 0,
        "duplicate_names": 0,
        "filtered_keywords": 0,
    }
    if not isinstance(companies, list):
        return companies, stats

    seen_ids = set()
    seen_names = set()
    cleaned = []

    for obj in companies:
        if not isinstance(obj, dict):
            cleaned.append(obj)
            continue

        raw_name = (
            obj.get("namn")
            or obj.get("company_name")
            or obj.get("companyName")
            or obj.get("title")
            or obj.get("Företagsnamn")
        )
        if should_skip_company(raw_name):
            stats["filtered_keywords"] += 1
            continue

        raw_id = obj.get("kungorelseid") or obj.get("kungorelseId")
        normalized_id = None
        if isinstance(raw_id, str):
            normalized_id = raw_id.strip().upper().replace("/", "-")
            if normalized_id in seen_ids:
                stats["duplicate_ids"] += 1
                continue

        normalized_name = normalize_company_name(raw_name)
        if normalized_name and normalized_name in seen_names:
            stats["duplicate_names"] += 1
            continue

        cleaned.append(obj)
        if normalized_id:
            seen_ids.add(normalized_id)
        if normalized_name:
            seen_names.add(normalized_name)

    stats["removed"] = len(companies) - len(cleaned)
    return cleaned, stats


def find_info_server_base(start_dir: str = None) -> str:
    """
    Leta rätt på mappen 'info_server' relativt där skriptet körs.
    """
    if start_dir is None:
        start_dir = str(BASE_DIR)
    base = os.path.join(start_dir, "info_server")
    if not os.path.isdir(base):
        raise FileNotFoundError("Hittade inte mappen 'info_server' i aktuell katalog.")
    return base


def find_register_and_workdir(base_dir: str) -> Tuple[str, str, str]:
    """
    Försök identifiera dagens JSON-registerfil och arbetsmapp.
    Logik:
      1) Om det finns undermapp med 8-siffrigt datum (t.ex. 20251012) som innehåller 'kungorelser_*.json',
         använd den senaste/den som matchar dagens datum om möjligt.
      2) Annars använd json som ligger direkt i 'base_dir'.
    Returnerar: (json_path, work_dir, date_str)
    """
    # samla alla json-kandidater i base_dir och dess datummappar
    candidates = []
    # JSON i rot av info_server
    candidates.extend(glob.glob(os.path.join(base_dir, "kungorelser_*.json")))
    # JSON i datummappar
    for d in os.listdir(base_dir):
        if re.fullmatch(r"\d{8}", d) and os.path.isdir(os.path.join(base_dir, d)):
            candidates.extend(
                glob.glob(os.path.join(base_dir, d, "kungorelser_*.json"))
            )

    if not candidates:
        raise FileNotFoundError(
            "Hittade ingen registerfil 'kungorelser_YYYYMMDD.json' i 'info_server'."
        )

    # Försök välja json som matchar TARGET_DATE eller dagens datum, annars senaste modifierade
    target_date = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
    preferred = [
        p
        for p in candidates
        if re.search(rf"kungorelser_{target_date}\.json$", os.path.basename(p))
    ]

    if preferred:
        # Om TARGET_DATE är satt och filen finns, använd den
        json_path = preferred[0]
    elif os.environ.get("TARGET_DATE"):
        # Om TARGET_DATE är satt men filen inte finns, försök hitta i rätt datummapp
        target_date_dir = os.path.join(base_dir, target_date)
        if os.path.isdir(target_date_dir):
            # Kolla om det finns JSON i datummappen (kan ha annat namn)
            dir_candidates = glob.glob(
                os.path.join(target_date_dir, "kungorelser_*.json")
            )
            if dir_candidates:
                json_path = max(dir_candidates, key=os.path.getmtime)
            else:
                # Om ingen fil finns i TARGET_DATE mappen, använd senaste modifierade
                json_path = max(candidates, key=os.path.getmtime)
        else:
            # Om TARGET_DATE mappen inte finns, använd senaste modifierade
            json_path = max(candidates, key=os.path.getmtime)
    else:
        # Om ingen TARGET_DATE är satt, använd senaste modifierade
        json_path = max(candidates, key=os.path.getmtime)

    # Extrahera datum ur filnamn, annars använd mappnamn, annars target_date
    m = re.search(r"kungorelser_(\d{8})\.json$", os.path.basename(json_path))
    if m:
        date_str = m.group(1)
    else:
        # prova att plocka 8-siffrigt datum från sökvägen
        m2 = re.search(r"(\d{8})", json_path)
        date_str = m2.group(1) if m2 else target_date

    # Om TARGET_DATE är satt, försäkra att vi använder rätt datum
    work_dir = os.path.dirname(json_path)
    if os.environ.get("TARGET_DATE") and date_str != target_date:
        # Varning: Vi hittade inte filen med TARGET_DATE, använder annan fil
        print(
            f"[WARN] TARGET_DATE={target_date} satt men hittade fil med datum {date_str}"
        )
        # Använd ändå target_date för work_dir om mappen finns
        target_date_dir = os.path.join(base_dir, target_date)
        if os.path.isdir(target_date_dir):
            date_str = target_date
            work_dir = target_date_dir
            # Försök hitta JSON i denna mapp
            json_in_dir = glob.glob(os.path.join(work_dir, "kungorelser_*.json"))
            if json_in_dir:
                json_path = json_in_dir[0]

    return json_path, work_dir, date_str


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text_if_exists(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


# -------------------------
# Parsning av content.txt
# -------------------------

HEADER_LABELS = [
    "Namn/fastighetsbeteckning",
    "Registreringsdatum",
    "Län",
    "Publiceringsdatum",
    "Kungörelse-id",
    "Uppgiftslämnare",
]


def _next_non_empty(lines: List[str], start_idx: int) -> Tuple[Optional[str], int]:
    """Hitta nästa icke-tomma rad från start_idx (exkluderande), returnera (radtext, index)."""
    i = start_idx + 1
    while i < len(lines):
        if lines[i].strip():
            return lines[i].strip(), i
        i += 1
    return None, i


def parse_header(lines: List[str]) -> Dict[str, str]:
    """
    Parsar huvuddelen före 'Kungörelsetext':
    Etikett på en rad, värde på nästa icke-tomma rad.
    Hämtar även 'URL' om första raderna innehåller den.
    """
    data = {}
    # Fånga URL om den finns
    for i in range(min(10, len(lines))):
        if lines[i].startswith("URL:"):
            data["URL"] = lines[i].split("URL:", 1)[1].strip()
            break

    # Bygg en snabb index på label->radindex
    idx_map = {}
    for i, line in enumerate(lines):
        if line.strip() in HEADER_LABELS:
            idx_map[line.strip()] = i

    for label, i in idx_map.items():
        val, _ = _next_non_empty(lines, i)
        if val is not None:
            # Specialfall: "Namn/fastighetsbeteckning" -> "Företagsnamn, ORGNR"
            if label == "Namn/fastighetsbeteckning":
                # Försök dela upp i namn och orgnr
                name = val
                orgnr = ""
                if "," in val:
                    parts = [p.strip() for p in val.split(",", 1)]
                    name = parts[0]
                    orgnr = parts[1] if len(parts) > 1 else ""
                data["Företagsnamn"] = name
                if orgnr:
                    data["Org nr (huvud)"] = orgnr
            else:
                data[label] = val
    return data


def slice_kungorelsetext(lines: List[str]) -> List[str]:
    """
    Returnera raderna under 'Kungörelsetext' fram till '« Tillbaka' (eller slutet).
    """
    try:
        kidx = lines.index("Kungörelsetext")
    except ValueError:
        return []

    end_idx = None
    for i in range(kidx + 1, len(lines)):
        if lines[i].startswith("« Tillbaka"):
            end_idx = i
            break
    if end_idx is None:
        end_idx = len(lines)
    return [line.rstrip() for line in lines[kidx + 1 : end_idx]]


COLON_KEYS_KEEP = {
    # Vanliga nycklar vi vill spara "som är"
    "Org nr",
    "Företagsnamn",
    "Säte",
    "Postadress",
    "E-post",
    "Typ",
    "Bildat",
    "Verksamhet",
    "Räkenskapsår",
    "Aktiekapital",
    "Kallelse",
    "Föreskrift om antal styrelseledamöter/styrelsesuppleanter",
    "Förbehåll/avvikelser/villkor",
    "Firmateckning",
    # Variationer på styrelsefält
    "Styrelseledamöter",
    "Styrelsesuppleanter",
    "Styrelseledamot, ordförande",
    "Styrelseledamot, verkställande direktör",
    "Styrelseledamöter, suppleanter",
    "Styrelseledamot",
    "Styrelse",
}


def parse_kungorelsetext(detail_lines: List[str]) -> Dict[str, str]:
    """
    Parsar kolonavsnittet. Hanterar att vissa värden fortsätter på nästa rad utan kolon.
    Extraherar dessutom 'Antal aktier' ur 'Aktiekapital' om det finns.
    """
    data = {}
    current_key = None

    def append_to_current(val: str):
        if current_key:
            if data.get(current_key):
                data[current_key] += " " + val.strip()
            else:
                data[current_key] = val.strip()

    for raw in detail_lines:
        line = raw.strip()
        if not line:
            continue

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Spara bara intressanta nycklar, men tillåt även okända (vi tar med så mycket som möjligt)
            data[key] = val
            current_key = key
        else:
            # Fortsättning på föregående nyckel (t.ex. Firmateckning-rader)
            append_to_current(line)

    # Specialbehandling: plocka ut "Antal aktier" från "Aktiekapital"
    if "Aktiekapital" in data and "Antal aktier" not in data:
        # Letar efter mönster "Antal aktier: 250" i värdet
        m = re.search(r"Antal aktier:\s*([0-9\.\s]+)", data["Aktiekapital"])
        if m:
            antal = m.group(1).strip().rstrip(".")
            data["Antal aktier"] = antal
            # Rensa bort "Antal aktier"-svansen ur Aktiekapital så bara kapitalet står kvar
            data["Aktiekapital"] = re.split(r"Antal aktier:", data["Aktiekapital"])[
                0
            ].strip()

    # Lätta normaliseringar
    for k in list(data.keys()):
        data[k] = data[k].rstrip(", ")
    return data


# -------------------------
# Segmentering (enkel heuristic)
# -------------------------

SEGMENT_MAP = [
    ("frisör", "Tjänster – Frisör/Skönhet"),
    ("fotograf", "Tjänster – Foto/Video"),
    ("videofilm", "Tjänster – Foto/Video"),
    ("hosting", "IT – Hosting/Drift"),
    ("webbhotell", "IT – Hosting/Drift"),
    ("webb", "IT – Webb/Utveckling"),
    ("utveckling", "IT – Webb/Utveckling"),
    ("konsult", "Konsult – Management/Tech"),
    ("fastighet", "Fastigheter"),
    ("logistik", "Logistik"),
    ("transport", "Transport"),
    ("catering", "Restaurang/Catering"),
    ("restaurang", "Restaurang/Catering"),
    ("utbildning", "Utbildning"),
    ("bygg", "Bygg/Entreprenad"),
    ("måleri", "Bygg/Entreprenad"),
    ("handel", "Handel"),
    ("förvaltning", "Investering/Förvaltning"),
    ("capital", "Investering/Förvaltning"),
    ("invest", "Investering/Förvaltning"),
    ("städ", "Tjänster – Städ"),
]


def categorize(verksamhet: str, namn: str) -> str:
    text = f"{verksamhet or ''} {namn or ''}".lower()
    for kw, seg in SEGMENT_MAP:
        if kw in text:
            return seg
    return "Övrigt"


# -------------------------
# Huvudflöde
# -------------------------


def main():
    # 1) Lokalisera info_server och registerfil
    base_dir = find_info_server_base()  # Uses BASE_DIR by default
    json_path, work_dir, date_str = find_register_and_workdir(base_dir)
    print(f"Arbetsmapp: {work_dir}")
    print(f"Register:   {os.path.basename(json_path)}")
    print(f"Datum:      {date_str}")

    # 2) Läs in register
    reg = read_json(json_path)
    companies = reg.get("data", [])
    companies, dedup_stats = deduplicate_companies(companies)
    if dedup_stats["removed"] or dedup_stats["filtered_keywords"]:
        print(
            "[DEDUP] Removed "
            f"{dedup_stats['removed']} entries "
            f"(same name: {dedup_stats['duplicate_names']}, "
            f"same kungorelseid: {dedup_stats['duplicate_ids']}, "
            f"keyword filtered: {dedup_stats['filtered_keywords']})"
        )

    # 3) Bygg lookup för undermappar: "Kxxxxxx/25" -> "Kxxxxxx-25"
    def id_to_folder(kid: str) -> str:
        return kid.replace("/", "-")

    # VIKTIGT: Filtrera bort företag som saknar content.txt INNAN begränsning
    def has_content_file(kid: str, work_dir: str) -> bool:
        """Kontrollera om företaget har en content.txt-fil."""
        if not kid:
            return False
        folder = id_to_folder(kid)
        folder_path = os.path.join(work_dir, folder)
        if not os.path.isdir(folder_path):
            return False
        for cand in CANDIDATE_CONTENT_NAMES:
            p = os.path.join(folder_path, cand)
            if os.path.exists(p) and os.path.getsize(p) > 200:  # Minst 200 bytes
                return True
        return False

    # Filtrera bort företag utan content.txt
    companies_with_content = [
        c for c in companies if has_content_file(c.get("kungorelseid", ""), work_dir)
    ]
    if len(companies_with_content) < len(companies):
        print(
            f"Filtrerade bort {len(companies) - len(companies_with_content)} företag utan content.txt"
        )
        companies = companies_with_content

    # Begränsa antal företag baserat på miljövariabel eller config (EFTER filtrering)
    max_companies_env = os.environ.get("RUNNER_MAX_COMPANIES_FOR_TESTING")
    if max_companies_env:
        try:
            max_companies = int(max_companies_env)
            if max_companies > 0 and len(companies) > max_companies:
                print(
                    f"Begränsar från {len(companies)} till {max_companies} företag (från master-nummer)"
                )
                companies = companies[:max_companies]

                # Uppdatera JSON-filen för att reflektera begränsningen
                reg["data"] = companies
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(reg, f, ensure_ascii=False, indent=2)
                print(
                    f"Uppdaterade {os.path.basename(json_path)} med begränsat antal företag"
                )
        except ValueError:
            pass

    # 4) Extrahera data per bolag
    rows = []
    for item in companies:
        kid = item.get("kungorelseid", "")  # t.ex. "K756625/25"
        namn = item.get("namn", "")
        publ = item.get("publiceringsdatum", "")
        typ = item.get("kungorelsetyp", "")
        uppg = item.get("uppgiftslamnare", "")
        folder = id_to_folder(kid) if kid else ""

        # Förifyll med registerfält, resten tomt
        base_row = {
            "Kungörelse-id": kid,
            "Mapp": folder,
            "Företagsnamn": namn,
            "Org.nr": "",
            "Registreringsdatum": "",
            "Publiceringsdatum": publ,
            "Län": "",
            "Säte": "",
            "Postadress": "",
            "E-post": "",
            "Typ": "",  # från content
            "Bildat": "",
            "Verksamhet": "",
            "Räkenskapsår": "",
            "Aktiekapital": "",
            "Antal aktier": "",
            "Firmateckning": "",
            "Styrelseledamöter": "",
            "Styrelsesuppleanter": "",
            "Styrelse (övrigt)": "",
            "Källa URL": "",
            "Uppgiftslämnare (register)": uppg,
            "Kungörelsetyp (register)": typ,
            "Segment": "",  # fylls efter parsing
        }

        # 4a) Slå upp content.txt i mappen (om den finns)
        folder_path = os.path.join(work_dir, folder)
        content_txt = None
        if os.path.isdir(folder_path):
            for cand in CANDIDATE_CONTENT_NAMES:
                p = os.path.join(folder_path, cand)
                content_txt = read_text_if_exists(p)
                if content_txt:
                    break

        if content_txt:
            lines = [line.rstrip("\n\r") for line in content_txt.splitlines()]
            header = parse_header(lines)
            details = parse_kungorelsetext(slice_kungorelsetext(lines))

            # Fyll med headerfält
            base_row["Registreringsdatum"] = (
                header.get("Registreringsdatum", "") or base_row["Registreringsdatum"]
            )
            base_row["Län"] = header.get("Län", "") or base_row["Län"]
            base_row["Publiceringsdatum"] = (
                header.get("Publiceringsdatum", "") or base_row["Publiceringsdatum"]
            )
            base_row["Källa URL"] = header.get("URL", "")
            # Org.nr kan förekomma i headern (parsat från namnrad)
            if header.get("Org nr (huvud)"):
                base_row["Org.nr"] = header["Org nr (huvud)"]

            # Fyll från detaljfält (Kungörelsetext)
            # Använd try-get för att inte kasta bort data även om nyckeln varierar
            def g(*keys, default=""):
                for k in keys:
                    if k in details and details[k]:
                        return details[k]
                return default

            base_row["Org.nr"] = g("Org nr", default=base_row["Org.nr"])
            base_row["Företagsnamn"] = g(
                "Företagsnamn", default=base_row["Företagsnamn"]
            )
            base_row["Säte"] = g("Säte", default=base_row["Säte"])
            base_row["Postadress"] = g("Postadress", default=base_row["Postadress"])
            base_row["E-post"] = g("E-post", default=base_row["E-post"])
            base_row["Typ"] = g("Typ", default=base_row["Typ"])
            base_row["Bildat"] = g("Bildat", default=base_row["Bildat"])
            base_row["Verksamhet"] = g("Verksamhet", default=base_row["Verksamhet"])
            base_row["Räkenskapsår"] = g(
                "Räkenskapsår", default=base_row["Räkenskapsår"]
            )
            base_row["Aktiekapital"] = g(
                "Aktiekapital", default=base_row["Aktiekapital"]
            )
            base_row["Antal aktier"] = g(
                "Antal aktier", default=base_row["Antal aktier"]
            )
            base_row["Firmateckning"] = g(
                "Firmateckning", default=base_row["Firmateckning"]
            )

            # Styrelsefält – samla ihop utan att tappa detalj
            led = g("Styrelseledamöter")
            sup = g("Styrelsesuppleanter")
            # ev. ytterligare roller
            extra_roles = []
            for k, v in details.items():
                if k.lower().startswith("styrelse") and k not in (
                    "Styrelseledamöter",
                    "Styrelsesuppleanter",
                ):
                    if v:
                        extra_roles.append(f"{k}: {v}")
            base_row["Styrelseledamöter"] = led
            base_row["Styrelsesuppleanter"] = sup
            base_row["Styrelse (övrigt)"] = "; ".join(extra_roles)

            # Segmentering
            base_row["Segment"] = categorize(
                base_row["Verksamhet"], base_row["Företagsnamn"]
            )

        else:
            # Ingen content – sätt segment efter företagsnamn (ofta ger lite ändå)
            base_row["Segment"] = categorize("", base_row["Företagsnamn"])

        rows.append(base_row)

    # 5) Skapa DataFrame och CSV
    columns = [
        "Kungörelse-id",
        "Mapp",
        "Företagsnamn",
        "Org.nr",
        "Registreringsdatum",
        "Publiceringsdatum",
        "Län",
        "Säte",
        "Postadress",
        "E-post",
        "Typ",
        "Bildat",
        "Verksamhet",
        "Räkenskapsår",
        "Aktiekapital",
        "Antal aktier",
        "Firmateckning",
        "Styrelseledamöter",
        "Styrelsesuppleanter",
        "Styrelse (övrigt)",
        "Segment",
        "Källa URL",
        "Uppgiftslämnare (register)",
        "Kungörelsetyp (register)",
    ]
    df = pd.DataFrame(rows, columns=columns)

    # Sortera "smart": Län -> Segment -> Företagsnamn (tomma län sist)
    with_county = df[df["Län"].str.len() > 0].sort_values(
        ["Län", "Segment", "Företagsnamn"]
    )
    without_county = df[df["Län"].str.len() == 0].sort_values(
        ["Segment", "Företagsnamn"]
    )
    df_sorted = pd.concat([with_county, without_county], ignore_index=True)

    csv_name = f"kungorelser_{date_str}.csv"
    df_sorted.to_csv(
        os.path.join(work_dir, csv_name),
        index=False,
        encoding="utf-8",
        quoting=csv.QUOTE_MINIMAL,
    )
    print(f"CSV skapad: {csv_name}")

    # 6) SQLite
    db_name = f"companies_{date_str}.db"
    db_path = os.path.join(work_dir, db_name)
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            kungorelse_id TEXT,
            mapp TEXT,
            foretagsnamn TEXT,
            orgnr TEXT,
            registreringsdatum TEXT,
            publiceringsdatum TEXT,
            lan TEXT,
            sate TEXT,
            postadress TEXT,
            epost TEXT,
            typ TEXT,
            bildat TEXT,
            verksamhet TEXT,
            rakenskapsar TEXT,
            aktiekapital TEXT,
            antal_aktier TEXT,
            firmateckning TEXT,
            styrelseledamoter TEXT,
            styrelsesuppleanter TEXT,
            styrelse_ovrigt TEXT,
            segment TEXT,
            kalla_url TEXT,
            uppgiftslamnare_register TEXT,
            kungorelsetyp_register TEXT
        )
    """)
    cur.execute("DELETE FROM companies")
    con.commit()

    # Mappa DataFrame-kolumner (svenska rubriker) -> insättningsordning i tabellen
    insert_cols_df = [
        "Kungörelse-id",
        "Mapp",
        "Företagsnamn",
        "Org.nr",
        "Registreringsdatum",
        "Publiceringsdatum",
        "Län",
        "Säte",
        "Postadress",
        "E-post",
        "Typ",
        "Bildat",
        "Verksamhet",
        "Räkenskapsår",
        "Aktiekapital",
        "Antal aktier",
        "Firmateckning",
        "Styrelseledamöter",
        "Styrelsesuppleanter",
        "Styrelse (övrigt)",
        "Segment",
        "Källa URL",
        "Uppgiftslämnare (register)",
        "Kungörelsetyp (register)",
    ]

    insert_sql = """
        INSERT INTO companies (
            kungorelse_id, mapp, foretagsnamn, orgnr, registreringsdatum, publiceringsdatum,
            lan, sate, postadress, epost, typ, bildat, verksamhet, rakenskapsar,
            aktiekapital, antal_aktier, firmateckning, styrelseledamoter, styrelsesuppleanter,
            styrelse_ovrigt, segment, kalla_url, uppgiftslamnare_register, kungorelsetyp_register
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    # Använd df_sorted så DB och CSV matchar exakt
    rows_to_insert = df_sorted[insert_cols_df].fillna("").values.tolist()
    cur.executemany(insert_sql, rows_to_insert)
    con.commit()
    con.close()
    print(f"SQLite skapad: {db_name}")

    # 7) Skapa companies.jsonl för 2_segment_info
    # Detta säkerställer att de nya företagen processas
    companies_jsonl_path = os.path.join(
        os.path.dirname(BASE_DIR),  # Gå upp till projektrot (pang/)
        "2_segment_info",
        "in",
        "companies.jsonl",
    )

    # Skapa in-katalogen om den inte finns
    os.makedirs(os.path.dirname(companies_jsonl_path), exist_ok=True)

    # Konvertera till format som 2_segment_info förväntar sig
    with open(companies_jsonl_path, "w", encoding="utf-8") as f:
        for _, row in df_sorted.iterrows():
            company_data = {
                "id": row.get("Kungörelse-id", ""),
                "name": row.get("Företagsnamn", ""),
                "domain": "",  # Domän gissas senare av 2_segment_info
                "text": "",
            }
            # Hoppa över om id eller name saknas
            if company_data["id"] and company_data["name"]:
                f.write(json.dumps(company_data, ensure_ascii=False) + "\n")

    print(f"Companies JSONL skapad: {companies_jsonl_path} ({len(df_sorted)} företag)")

    # ZIP skapas inte här längre - det görs av copy_to_dropbox.py i slutet av pipelinen
    print("Bearbetning klar. ZIP skapas senare av copy_to_dropbox.py")


if __name__ == "__main__":
    main()
