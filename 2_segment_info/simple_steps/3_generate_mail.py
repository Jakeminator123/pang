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


def build_email_prompt(data: Dict) -> str:
    """Build prompt for email generation."""
    company_name = data.get("company_name", "Företaget")
    orgnr = data.get("orgnr", "")
    verksamhet = data.get("verksamhet", "")
    sate = data.get("sate", "")
    address = data.get("address", "")

    # Domain info
    domain_info = data.get("domain", {})
    domain_guess = domain_info.get("guess", "")
    domain_status = domain_info.get("status", "unknown")
    confidence = domain_info.get("confidence", 0)

    # People
    people = data.get("people", [])
    people_str = (
        ", ".join([p.get("name", "") for p in people[:3]])
        if people
        else "Ingen angiven"
    )

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
        # NOT VERIFIED - do NOT mention any domain guess!
        domain_situation = "INGEN VERIFIERAD HEMSIDA - Företaget verkar sakna hemsida."
        offer_focus = "erbjud att hjälpa dem etablera sig online med domän och hemsida"

    # Alternative domains from research
    alt_domains_str = ""
    candidates = research.get("domain_candidates", [])
    if candidates and domain_status not in ("verified", "match"):
        alt_list = [
            c.get("domain", "")
            for c in candidates[:3]
            if c.get("domain") != domain_guess
        ]
        if alt_list:
            alt_domains_str = f"\n\nAlternativa domänförslag: {', '.join(alt_list)}"

    # Build research context
    research_context = ""
    if research_summary:
        research_context = f"\n\nRESEARCH OM FÖRETAGET:{research_summary}"

    prompt = f"""Du är en säljare från SajtStudio.se som ska skriva ett personligt e-postmeddelande till ett nyregistrerat företag för att erbjuda hemsidestjänster.

FÖRETAGSINFORMATION:
- Företagsnamn: {company_name}
- Org.nr: {orgnr}
- Verksamhet: {verksamhet}
- Säte: {sate}
- Adress: {address}
- E-post: {email_str}
- Kontaktpersoner: {people_str}

DOMÄNSITUATION:
{domain_situation}{alt_domains_str}{research_context}

UPPGIFT:
Skriv ett kort (150-200 ord), professionellt och personligt e-postmeddelande som:

1. Gratulerar till företagsregistreringen
2. Visar att du förstår deras verksamhet (baserat på verksamhetsbeskrivningen)
3. {offer_focus.capitalize()}
4. Ger konkreta fördelar specifikt för deras bransch
5. Avslutas med en tydlig men inte påträngande call-to-action

REGLER:
- Skriv på svenska
- Var personlig och referera till företagets specifika verksamhet
- Undvik klyschor och alltför säljande språk
- Håll det kort och läsbart
- KRITISKT: Om DOMÄNSITUATION säger "INGEN VERIFIERAD HEMSIDA", påstå ALDRIG att du besökt deras hemsida eller sett deras sajt! Skriv istället att de verkar sakna hemsida och att du vill hjälpa.
- Om DOMÄNSITUATION säger "VERIFIERAD HEMSIDA", KAN du nämna att du tittat på den.
- Avsluta med:
  "Med vänliga hälsningar,
  [Ditt namn]
  SajtStudio.se"

Skriv endast mailet, inget annat:"""

    return prompt


def build_subject_prompt(company_name: str, verksamhet: str, domain_status: str) -> str:
    """Build prompt for subject line."""
    if domain_status in ("verified", "match"):
        situation = "som har hemsida"
    else:
        situation = "utan hemsida"

    return f"""Skapa en kort ämnesrad (max 50 tecken) för ett e-post till {company_name}, ett nyregistrerat företag {situation}.

Verksamhet: {verksamhet if verksamhet else "Ej specificerad"}

Regler:
- Max 50 tecken
- På svenska
- Personlig och relevant
- Inte för säljig eller spam-liknande

Skriv endast ämnesraden, inget annat:"""


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
                    "content": "Du är en professionell säljare som skriver personliga och engagerande e-postmeddelanden.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.7,
        )

        email_text = response.choices[0].message.content.strip()

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
        # Clean up
        subject = subject.replace('"', "").replace("'", "")[:60]
        return subject

    except Exception as e:
        return f"Grattis till nyregistreringen - {e}"[:50]


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

        # Generate email
        email_prompt = build_email_prompt(data)
        email_text, cost_info = generate_email(client, email_prompt, model)

        if "error" in cost_info:
            print(f"    ERROR: {cost_info['error']}")
            continue

        # Generate subject
        subject_prompt = build_subject_prompt(
            company_name,
            data.get("verksamhet", ""),
            data.get("domain", {}).get("status", "unknown"),
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
