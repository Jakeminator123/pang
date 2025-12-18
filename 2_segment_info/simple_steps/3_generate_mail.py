#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3_generate_mail.py - Step 3: Generate sales emails

Simplified version that:
- Reads company_data.json + domain status
- Generates personalized email with gpt-4o (balanced cost/quality)
- Saves as mail.txt per company
- Creates mail_ready.xlsx with all mails for review

Respects TARGET_DATE environment variable if set.
"""

import json
import os
import re
import sys

# datetime not needed currently
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("WARNING: openai not installed. Install with: pip install openai")

# =============================================================================
# CONFIGURATION
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
            val = val.split("#")[0].strip()
            full_key = f"{section}_{key}" if section else key
            cfg[full_key] = val
    return cfg


# =============================================================================
# EMAIL GENERATION
# =============================================================================


def guess_recipient_name(email: str, people: List[Dict], company_name: str = "") -> str:
    """
    Guess the recipient's first name from email prefix by matching against people list.
    
    Examples:
    - "peter.maksinen@..." + ["Bengt Peter Maksinen", "Anna ..."] → "Peter" (first name match)
    - "o.olson@..." + ["Frida Jonson", "Olle Olson"] → "Olle" (initial + surname match)
    - "info@..." + ["Anna Berg"] → "Anna" (fallback to first person)
    - "info@..." + [] → "Företagsnamn" or "" (fallback)
    
    Returns: First name of best match, or fallback.
    """
    if not email or "@" not in email:
        # No email - use first person's name or company
        if people:
            first_person = people[0].get("name", "")
            if first_person:
                return first_person.split()[0]
        return ""

    prefix = email.split("@")[0].lower()
    # Clean prefix: split on dots, underscores, dashes
    prefix_parts = re.split(r"[._\-]", prefix)
    prefix_parts = [p.strip() for p in prefix_parts if p.strip()]

    if not people:
        return ""

    best_match_name = ""
    best_score = 0

    for person in people:
        full_name = person.get("name", "")
        if not full_name:
            continue

        name_parts = full_name.split()
        if not name_parts:
            continue

        first_name = name_parts[0]
        surname = name_parts[-1] if len(name_parts) > 1 else ""
        
        for prefix_part in prefix_parts:
            prefix_lower = prefix_part.lower()
            
            # Check each name part (first name, middle names, surname)
            for name_part in name_parts:
                name_lower = name_part.lower()
                
                # Full match or prefix match (at least 3 chars, or 1 char if it's an initial)
                if name_lower == prefix_lower:
                    # Exact match - very high score
                    score = 100 + len(name_lower)
                elif len(prefix_lower) >= 3 and name_lower.startswith(prefix_lower):
                    # Prefix match: "pet" → "Peter"
                    score = 50 + len(prefix_lower)
                elif len(prefix_lower) >= 3 and prefix_lower.startswith(name_lower):
                    # Name is prefix: "peter" starts with "pet" from name
                    score = 40 + len(name_lower)
                elif len(prefix_lower) == 1 and name_lower.startswith(prefix_lower):
                    # Initial match: "o" → "Olle"
                    # Only count if we also match surname in another prefix part
                    # e.g. "o.olson@..." should match "Olle Olson" but not "Oscar Svensson"
                    if surname and any(
                        surname.lower().startswith(p.lower()) or p.lower().startswith(surname.lower())
                        for p in prefix_parts if len(p) >= 3
                    ):
                        score = 80  # High score - initial + surname match
                    else:
                        continue  # Skip initial-only matches
                else:
                    continue
                
                if score > best_score:
                    best_score = score
                    best_match_name = first_name

    # If we found a match, return it
    if best_match_name:
        return best_match_name

    # Fallback: use first person's first name if email looks personal (not info@, kontakt@, etc.)
    generic_prefixes = {"info", "kontakt", "contact", "admin", "hello", "hej", "mail", "post"}
    if prefix_parts and prefix_parts[0].lower() not in generic_prefixes:
        # Email looks personal but no match - still use first person
        if people:
            first_person = people[0].get("name", "")
            if first_person:
                return first_person.split()[0]

    # Last fallback: empty (will use "Hej," without name)
    return ""


def build_email_prompt(data: Dict, recipient_name: str) -> str:
    """Build prompt for email generation."""
    company_name = data.get("company_name", "Företaget")
    verksamhet = data.get("verksamhet", "")
    sate = data.get("sate", "")

    # Domain info
    domain_info = data.get("domain", {})
    domain_guess = domain_info.get("guess", "")
    domain_status = domain_info.get("status", "unknown")
    confidence = domain_info.get("confidence", 0)

    # Emails
    emails = data.get("emails", [])
    email_str = emails[0] if emails else "Ingen"

    # Research info
    research = data.get("research", {})
    research_summary = ""
    if research.get("searches"):
        for s in research["searches"][:2]:
            if s.get("summary"):
                research_summary += f"\n- {s['summary'][:200]}"

    # Build domain situation description - ONLY trust verified/matched domains
    best_domain = research.get("best_domain")

    if domain_status in ("verified", "match") and confidence >= 0.5:
        domain_situation = f"VERIFIERAD HEMSIDA: {domain_guess} - Du kan referera till att du besökt denna."
        offer_focus = "erbjud förbättringar och modernisering av hemsidan"
    elif domain_status == "parked":
        domain_situation = f"Domänen {domain_guess} är parkerad (ingen aktiv hemsida)"
        offer_focus = "erbjud att bygga hemsida och aktivera domänen"
    elif best_domain and research.get("best_confidence", 0) >= 0.5:
        domain_situation = f"VERIFIERAD HEMSIDA: {best_domain} - Du kan referera till att du besökt denna."
        offer_focus = "erbjud förbättringar och modernisering av hemsidan"
    else:
        domain_situation = "INGEN VERIFIERAD HEMSIDA - Företaget verkar sakna hemsida."
        offer_focus = "erbjud att hjälpa dem etablera sig online med domän och hemsida"

    # Build research context
    research_context = ""
    if research_summary:
        research_context = f"\n\nRESEARCH OM FÖRETAGET:{research_summary}"

    # Greeting instruction
    if recipient_name:
        greeting_instruction = f"Börja med 'Hej {recipient_name},' (endast detta namn, inga fler)"
    else:
        greeting_instruction = "Börja med 'Hej,' (utan namn)"

    prompt = f"""Du är en säljare från SajtStudio.se som ska skriva ett personligt e-postmeddelande till ett nyregistrerat företag för att erbjuda hemsidestjänster.

FÖRETAGSINFORMATION:
- Företagsnamn: {company_name}
- Verksamhet: {verksamhet}
- Säte: {sate}
- E-post: {email_str}

DOMÄNSITUATION:
{domain_situation}{research_context}

UPPGIFT:
Skriv ett kort (120-150 ord), professionellt och avslappnat e-postmeddelande som:

1. {greeting_instruction}
2. Nämner kort att ni sett deras nyregistrerade företag (INTE "Grattis!" eller "Välkommen till företagsvärlden/näringslivet" - det låter för klyschigt)
3. Visar att du förstår deras verksamhet kort
4. {offer_focus.capitalize()}
5. Avslutas med enkel call-to-action

VIKTIGA REGLER:
- Skriv på svenska, naturligt och avslappnat
- SKRIV ALDRIG "Ämne:" i brödtexten - ämnesraden hanteras separat
- Tilltala ENDAST en person (den i hälsningen), använd aldrig flera namn
- Undvik klyschor: "Välkommen till näringslivet", "spännande resa", "digitala era"
- Håll det kort och rakt på sak
- Om DOMÄNSITUATION säger "INGEN VERIFIERAD HEMSIDA", påstå ALDRIG att du besökt deras hemsida
- Avsluta med:
  "Med vänliga hälsningar,
  [Ditt namn]
  SajtStudio.se"

Skriv endast mejlet (börja med hälsningen), inget annat:"""

    return prompt


def build_subject_prompt(company_name: str, verksamhet: str) -> str:
    """Build prompt for subject line."""
    # Shorten company name if needed
    short_name = company_name.replace(" AB", "").replace(" Aktiebolag", "").strip()
    if len(short_name) > 25:
        short_name = short_name[:22] + "..."

    return f"""Skapa en kort ämnesrad (max 45 tecken) för ett säljmejl till {short_name}.

Verksamhet: {verksamhet if verksamhet else "Ej specificerad"}

Regler:
- Max 45 tecken totalt
- På svenska
- Saklig och konkret, t.ex. "Hemsida för {short_name}?" eller "Webbförslag till {short_name}"
- UNDVIK: "Välkommen", "Grattis", "Spännande", utropstecken
- Skriv ENDAST ämnesraden, inget annat, inga citattecken:"""


def clean_email_text(text: str) -> str:
    """Remove any 'Ämne:' lines from email body."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip().lower()
        # Skip lines that are just subject lines
        if stripped.startswith("ämne:") and len(stripped) < 80:
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def generate_email(
    client: OpenAI, prompt: str, model: str = "gpt-4o"
) -> Tuple[str, Dict]:
    """Generate email using OpenAI."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Du är en professionell säljare som skriver personliga e-postmeddelanden. Skriv aldrig 'Ämne:' i mejlet.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.7,
        )

        email_text = response.choices[0].message.content.strip()
        # Clean up any stray subject lines in body
        email_text = clean_email_text(email_text)

        # Cost calculation (approximate)
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # gpt-4o pricing: $2.50/1M input, $10/1M output
        cost_usd = (input_tokens / 1_000_000) * 2.50 + (
            output_tokens / 1_000_000
        ) * 10.00
        cost_sek = cost_usd * 10.5  # Approximate SEK rate

        cost_info = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "cost_sek": cost_sek,
        }

        return email_text, cost_info

    except Exception as e:
        return f"Error generating email: {e}", {"error": str(e)}


def generate_subject(client: OpenAI, prompt: str, model: str = "gpt-4o") -> str:
    """Generate subject line."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.7,
        )

        subject = response.choices[0].message.content.strip()
        # Clean up: remove quotes, "Ämne:" prefix, limit length
        subject = subject.replace('"', "").replace("'", "")
        if subject.lower().startswith("ämne:"):
            subject = subject[5:].strip()
        return subject[:55]

    except Exception as e:
        return "Hemsida för ert företag?"


# =============================================================================
# MAIN LOGIC
# =============================================================================


def find_company_dirs(date_dir: Path) -> List[Path]:
    """Find all K-folders in date directory."""
    return [
        p
        for p in date_dir.iterdir()
        if p.is_dir() and p.name.startswith("K") and "-" in p.name
    ]


def load_company_data(company_dir: Path) -> Optional[Dict]:
    """Load company_data.json from folder."""
    data_file = company_dir / "company_data.json"
    if not data_file.exists():
        return None
    try:
        return json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def should_generate_mail(data: Dict, cfg: Dict) -> Tuple[bool, str]:
    """Check if mail should be generated for this company."""
    if not data:
        return False, "No data"

    # Check if company was marked for skip (accounting firm, excluded keyword)
    if data.get("skip_company"):
        skip_reason = data.get("skip_reason", "marked_for_skip")
        return False, f"Skipped ({skip_reason})"

    # Must have email
    emails = data.get("emails", [])
    if not emails:
        return False, "No email"

    # Check domain confidence threshold (0-100 scale)
    min_conf = float(cfg.get("MAIL_MIN_CONFIDENCE", "40"))
    domain_info = data.get("domain", {})
    confidence = domain_info.get("confidence", 0)

    # If confidence is 0-1, convert to percentage
    if confidence <= 1.0:
        confidence = confidence * 100

    # Verified/matched domains get bonus
    if domain_info.get("status") in ("verified", "match"):
        confidence = max(confidence, 60)

    if confidence < min_conf:
        return False, f"Low confidence ({confidence:.0f}% < {min_conf}%)"

    return True, "OK"


def main() -> int:
    """Main function."""
    root = Path(__file__).resolve().parent.parent
    cfg = load_config(root / "config_simple.txt")

    print("=" * 60)
    print("STEP 3: GENERATE SALES EMAILS")
    print("=" * 60)
    print(f"Working directory: {root}")

    # Check if enabled
    mail_enabled = cfg.get("MAIL_ENABLED", "y").lower() in ("y", "yes", "true", "1")
    if not mail_enabled:
        print("Mail generation is disabled in config")
        return 0

    # Check OpenAI
    if not OPENAI_AVAILABLE:
        print("ERROR: OpenAI library not available")
        return 1

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        return 1

    try:
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"ERROR: Could not initialize OpenAI client: {e}")
        return 1

    model = cfg.get("MAIL_MODEL", "gpt-4o")
    print(f"Using model: {model}")

    # Find latest date folder
    djupanalys = root / "djupanalys"
    if not djupanalys.exists():
        print("ERROR: djupanalys folder not found. Run steps 1-2 first.")
        return 1

    date_pattern = re.compile(r"^\d{8}$")
    date_dirs = sorted(
        [p for p in djupanalys.iterdir() if p.is_dir() and date_pattern.match(p.name)]
    )

    if not date_dirs:
        print("ERROR: No date folders found")
        return 1

    # Respect TARGET_DATE env var if set
    target_date = os.environ.get("TARGET_DATE", "")
    if target_date and (djupanalys / target_date).exists():
        latest = djupanalys / target_date
        print(f"[TARGET_DATE] Processing specified date: {latest.name}")
    else:
        latest = date_dirs[-1]
        if target_date:
            print(f"[WARN] TARGET_DATE={target_date} not found, using latest: {latest.name}")
        else:
            print(f"Processing latest: {latest.name}")
    
    print(f"[INFO] Date folder path: {latest}")

    # Find company folders
    company_dirs = find_company_dirs(latest)
    print(f"Found {len(company_dirs)} company folders")

    # Limit if configured
    max_companies = int(cfg.get("PIPELINE_MAX_COMPANIES", "0"))
    max_mails = int(cfg.get("MAIL_MAX_MAILS", "0"))

    if max_companies > 0:
        company_dirs = company_dirs[:max_companies]

    # Process companies
    results = []
    total_cost_sek = 0.0
    mails_generated = 0
    skipped_reasons = {}

    for i, company_dir in enumerate(company_dirs, 1):
        data = load_company_data(company_dir)

        # Check if should generate
        should_gen, reason = should_generate_mail(data, cfg)

        if not should_gen:
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            continue

        # Check mail limit
        if max_mails > 0 and mails_generated >= max_mails:
            break

        company_name = data.get("company_name", "Företag")
        print(f"  [{mails_generated + 1}] {company_name}...")

        # Guess recipient name from email
        recipient_email = data.get("emails", [""])[0]
        people = data.get("people", [])
        recipient_name = guess_recipient_name(recipient_email, people, company_name)

        # Generate email
        email_prompt = build_email_prompt(data, recipient_name)
        email_text, cost_info = generate_email(client, email_prompt, model)

        if "error" in cost_info:
            print(f"    ERROR: {cost_info['error']}")
            continue

        # Generate subject
        subject_prompt = build_subject_prompt(
            company_name,
            data.get("verksamhet", ""),
        )
        subject = generate_subject(client, subject_prompt, model)

        # Get recipient email
        recipient = data.get("emails", [""])[0]

        # Save mail.txt
        mail_file = company_dir / "mail.txt"
        with mail_file.open("w", encoding="utf-8") as f:
            f.write(f"Till: {recipient}\n")
            f.write(f"Ämne: {subject}\n")
            f.write("=" * 60 + "\n\n")
            f.write(email_text)
            f.write("\n")

        # Track results
        cost_sek = cost_info.get("cost_sek", 0)
        total_cost_sek += cost_sek
        mails_generated += 1

        results.append(
            {
                "folder": company_dir.name,
                "company": company_name,
                "email": recipient,
                "subject": subject,
                "cost_sek": cost_sek,
                "domain_status": data.get("domain", {}).get("status", "unknown"),
            }
        )

        if i % 10 == 0:
            print(
                f"    Progress: {mails_generated} mails generated, {total_cost_sek:.2f} SEK"
            )

    # Create mail_ready.xlsx
    if results:
        mail_ready_path = latest / "mail_ready.xlsx"
        df = pd.DataFrame(results)

        # Also include email content
        for idx, row in df.iterrows():
            folder = row["folder"]
            mail_file = latest / folder / "mail.txt"
            if mail_file.exists():
                content = mail_file.read_text(encoding="utf-8")
                # Extract just the email body
                parts = content.split("=" * 60, 1)
                if len(parts) > 1:
                    df.at[idx, "mail_content"] = parts[1].strip()

        with pd.ExcelWriter(mail_ready_path, engine="openpyxl") as xw:
            df.to_excel(xw, sheet_name="Mails", index=False)

        print(f"\nCreated: {mail_ready_path.name}")

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Mails generated: {mails_generated}")
    print(f"Total cost: {total_cost_sek:.2f} SEK")
    if mails_generated > 0:
        print(f"Average cost per mail: {total_cost_sek / mails_generated:.4f} SEK")

    if skipped_reasons:
        print("\nSkipped companies:")
        for reason, count in sorted(skipped_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")

    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
