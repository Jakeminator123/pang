# -*- coding: utf-8 -*-
"""
standalone_audit.py - Fristående webbplats-audit med AI

Skapar tre dokument från en webbplats-URL:
1. audit_report.json - Detaljerad analys av sajten
2. company_analysis.json - Strukturerad företagsdata
3. company_profile.txt - Läsbar företagsbeskrivning

Krav:
- Python 3.9+
- openai>=1.0.0
- OPENAI_API_KEY i miljövariabel eller .env fil

Användning:
    python standalone_audit.py https://www.example.com
    python standalone_audit.py https://www.example.com --output ./my_output
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# KONFIGURATION
# =============================================================================

# Modeller - ändra vid behov
AUDIT_MODEL = "gpt-5.1"  # För web_search audit
PROFILE_MODEL = "gpt-5.1"  # För company_profile generering

# Reasoning nivå (high/medium/low)
REASONING_LEVEL = "medium"

# Växelkurs för kostnadskalkyl
USD_TO_SEK = 11.0

# =============================================================================
# OPENAI CLIENT
# =============================================================================


def get_api_key() -> str:
    """Hämta API-nyckel från miljövariabel eller .env fil."""
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        # Försök läsa från .env
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip("\"'")
                    break

    if not api_key:
        print("❌ OPENAI_API_KEY saknas!")
        print("   Sätt miljövariabel eller skapa .env fil med:")
        print("   OPENAI_API_KEY=sk-din-nyckel-här")
        sys.exit(1)

    return api_key


def call_openai_api(
    prompt: str,
    model: str = "gpt-5.1",
    reasoning: str = "medium",
    system_prompt: Optional[str] = None,
    timeout: int = 300,
) -> Tuple[str, int, int]:
    """
    Anropa OpenAI Responses API.

    Returns:
        Tuple av (svar_text, input_tokens, output_tokens)
    """
    from openai import OpenAI

    client = OpenAI(api_key=get_api_key())

    # Bygg meddelanden
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Bygg parametrar för Responses API
    params = {
        "model": model,
        "input": messages,
    }

    # Lägg till reasoning för GPT-5.x modeller
    if reasoning and model.startswith("gpt-5"):
        params["reasoning"] = {"effort": reasoning}

    response = client.responses.create(**params, timeout=timeout)

    # Extrahera text från response
    text = ""
    if hasattr(response, "output_text"):
        text = response.output_text
    elif hasattr(response, "output"):
        for item in response.output:
            if hasattr(item, "content"):
                for c in item.content:
                    if hasattr(c, "text"):
                        text += c.text

    # Hämta token-användning
    in_tok = (
        getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    )
    out_tok = (
        getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
    )

    return text, in_tok, out_tok


def call_web_search(
    prompt: str,
    model: str = "gpt-5.1",
    reasoning: str = "medium",
    allowed_domains: Optional[List[str]] = None,
    timeout: int = 300,
) -> Tuple[str, int, int, List[Dict]]:
    """
    Anropa OpenAI Responses API med web_search.

    Returns:
        Tuple av (svar_text, input_tokens, output_tokens, källor)
    """
    from openai import OpenAI

    client = OpenAI(api_key=get_api_key())

    # Bygg web_search verktyg
    web_search_tool = {"type": "web_search"}

    if allowed_domains:
        clean_domains = []
        for domain in allowed_domains[:20]:  # Max 20 domäner
            domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
            if domain:
                clean_domains.append(domain)
        if clean_domains:
            web_search_tool["filters"] = {"allowed_domains": clean_domains}

    # Svenska resultat
    web_search_tool["user_location"] = {
        "type": "approximate",
        "country": "SE",
        "city": "Stockholm",
        "region": "Stockholm",
    }

    # Bygg parametrar
    params = {
        "model": model,
        "tools": [web_search_tool],
        "input": prompt,
    }

    if reasoning and model.startswith("gpt-5"):
        params["reasoning"] = {"effort": reasoning}

    response = client.responses.create(**params, timeout=timeout)

    # Extrahera text
    text = ""
    if hasattr(response, "output_text"):
        text = response.output_text
    elif hasattr(response, "output"):
        for item in response.output:
            if hasattr(item, "content"):
                for c in item.content:
                    if hasattr(c, "text"):
                        text += c.text

    # Token-användning
    in_tok = (
        getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    )
    out_tok = (
        getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
    )

    # Extrahera källor
    sources = []
    try:
        if hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", None) == "web_search_call":
                    action = getattr(item, "action", None)
                    if action and hasattr(action, "sources"):
                        sources.extend(action.sources)
                    elif hasattr(item, "sources"):
                        sources.extend(item.sources)
    except Exception:
        pass

    return text, in_tok, out_tok, sources


def calculate_cost(
    input_tokens: int, output_tokens: int, model: str = "gpt-5.1"
) -> Tuple[float, float]:
    """Beräkna kostnad i USD och SEK."""
    prices = {
        "gpt-5.1": {"input": 1.25, "output": 10.0},
        "gpt-5.1-codex": {"input": 1.25, "output": 10.0},
        "gpt-5": {"input": 1.25, "output": 10.0},
    }

    price = prices.get(model, prices["gpt-5.1"])
    usd = (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
    sek = usd * USD_TO_SEK

    return usd, sek


def parse_json_response(text: str) -> Optional[Dict]:
    """Extrahera JSON från AI-svar."""
    # Försök hitta JSON-block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Försök parsa hela texten
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Försök hitta JSON-objekt
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    return None


# =============================================================================
# AUDIT FUNKTIONER
# =============================================================================


def get_audit_prompt(url: str) -> str:
    """Skapa prompt för webbplats-audit."""
    return f"""Analysera webbplatsen: {url}

Använd web_search för att hitta information om företaget och dess webbplats.

Returnera ett JSON-objekt med följande struktur:

{{
    "company": {{
        "name": "Företagsnamn",
        "tagline": "Slogan eller kort beskrivning",
        "industry": "Bransch",
        "description": "Detaljerad beskrivning (2-3 meningar)",
        "founded": "År eller 'Okänt'",
        "location": "Stad, Land",
        "size": "Antal anställda eller 'Okänt'"
    }},
    "contact": {{
        "email": "email@example.com eller null",
        "phone": "Telefonnummer eller null",
        "address": "Adress eller null"
    }},
    "content": {{
        "hero_title": "Exakt rubrik från hemsidan",
        "hero_subtitle": "Underrubrik om den finns",
        "cta_text": "Call-to-action text (t.ex. 'Kontakta oss')",
        "key_services": ["Tjänst 1", "Tjänst 2", "Tjänst 3"],
        "unique_selling_points": ["USP 1", "USP 2"],
        "target_audience": "Beskrivning av målgrupp"
    }},
    "design": {{
        "primary_color": "#hexkod (uppskattad från sajten)",
        "secondary_color": "#hexkod",
        "accent_color": "#hexkod",
        "font_family": "Typsnitt om det går att identifiera",
        "style": "modern/klassisk/minimalistisk/etc",
        "overall_impression": "Kort beskrivning av designen"
    }},
    "strengths": [
        "Styrka 1",
        "Styrka 2",
        "Styrka 3"
    ],
    "weaknesses": [
        "Svaghet/förbättringsområde 1",
        "Svaghet/förbättringsområde 2"
    ],
    "recommendations": [
        "Rekommendation för ny sajt 1",
        "Rekommendation för ny sajt 2",
        "Rekommendation för ny sajt 3"
    ],
    "scores": {{
        "design": 7,
        "content": 8,
        "usability": 7,
        "mobile": 8,
        "seo": 6,
        "overall": 7
    }}
}}

VIKTIGT:
- Alla poäng ska vara 1-10
- Använd svenska för beskrivningar
- Extrahera faktisk information från sajten, gissa inte
- Om något inte hittas, sätt null eller "Okänt"
"""


def perform_audit(url: str) -> Tuple[Dict, int, int, List]:
    """
    Utför webbplats-audit med AI och web_search.

    Returns:
        Tuple av (audit_data, input_tokens, output_tokens, sources)
    """
    print(f"🔍 Startar audit av: {url}")
    print(f"   Modell: {AUDIT_MODEL}")
    print(f"   Reasoning: {REASONING_LEVEL}")

    # Rensa URL för domänfilter
    clean_url = url.replace("https://", "").replace("http://", "").split("/")[0]

    prompt = get_audit_prompt(url)

    print("   Anropar AI med web_search...")
    text, in_tok, out_tok, sources = call_web_search(
        prompt=prompt,
        model=AUDIT_MODEL,
        reasoning=REASONING_LEVEL,
        allowed_domains=[clean_url],
        timeout=300,
    )

    # Parsa JSON
    audit_data = parse_json_response(text)

    if not audit_data:
        print("   ⚠ Kunde inte parsa JSON, skapar minimal struktur")
        audit_data = {
            "company": {"name": clean_url, "description": text[:500]},
            "raw_response": text,
        }

    # Lägg till metadata
    audit_data["_meta"] = {
        "url": url,
        "audit_date": datetime.now().isoformat(),
        "model": AUDIT_MODEL,
        "sources_count": len(sources),
    }

    return audit_data, in_tok, out_tok, sources


def create_company_analysis(audit_data: Dict) -> Dict:
    """Skapa company_analysis.json från audit-data."""
    company = audit_data.get("company", {})
    content = audit_data.get("content", {})
    contact = audit_data.get("contact", {})
    design = audit_data.get("design", {})

    return {
        "company_name": company.get("name", "Okänt företag"),
        "tagline": company.get("tagline", ""),
        "industry": company.get("industry", "Okänd"),
        "description": company.get("description", ""),
        "target_audience": content.get("target_audience", ""),
        "unique_selling_points": content.get("unique_selling_points", []),
        "services": content.get("key_services", []),
        "contact": {
            "email": contact.get("email"),
            "phone": contact.get("phone"),
            "address": contact.get("address"),
        },
        "branding": {
            "primary_color": design.get("primary_color", "#3b82f6"),
            "secondary_color": design.get("secondary_color", "#1e40af"),
            "accent_color": design.get("accent_color", "#10b981"),
            "font_style": design.get("font_family", "Sans-serif"),
            "design_style": design.get("style", "modern"),
        },
        "content_suggestions": {
            "hero_title": content.get("hero_title", ""),
            "hero_subtitle": content.get("hero_subtitle", ""),
            "cta_text": content.get("cta_text", "Kontakta oss"),
        },
        "source": "audit",
        "created_at": datetime.now().isoformat(),
    }


def generate_company_profile(audit_data: Dict) -> Tuple[str, int, int]:
    """
    Generera läsbar företagsprofil.

    Returns:
        Tuple av (profil_text, input_tokens, output_tokens)
    """
    company = audit_data.get("company", {})
    content = audit_data.get("content", {})
    strengths = audit_data.get("strengths", [])

    prompt = f"""Baserat på följande information om ett företag, skriv en engagerande och professionell 
företagsprofil på svenska (300-500 ord).

Företagsnamn: {company.get("name", "Okänt")}
Bransch: {company.get("industry", "Okänd")}
Beskrivning: {company.get("description", "N/A")}
Plats: {company.get("location", "Sverige")}
Tagline: {company.get("tagline", "")}
Målgrupp: {content.get("target_audience", "")}
Tjänster: {", ".join(content.get("key_services", []))}
Styrkor: {", ".join(strengths)}

Skriv profilen i följande format:

# [Företagsnamn]

[Inledande stycke - fånga essensen av företaget]

## Vad vi gör
[Beskrivning av tjänster/produkter]

## Varför välja oss
[Unika fördelar och styrkor]

## Vår vision
[Framtidsvision och värderingar]

---
Kontakta oss för mer information.

VIKTIGT: Skriv engagerande, professionellt och på ren svenska. Undvik generiska fraser."""

    print("📝 Genererar företagsprofil...")
    text, in_tok, out_tok = call_openai_api(
        prompt=prompt,
        model=PROFILE_MODEL,
        reasoning="low",
        timeout=120,
    )

    return text, in_tok, out_tok


# =============================================================================
# PDF EXPORT
# =============================================================================


def generate_audit_pdf(audit_data: Dict, output_path: Path) -> bool:
    """
    Generera en snygg PDF-rapport från audit-data.

    Returns:
        True om lyckad, False annars
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        print("⚠️  reportlab saknas - installera med: pip install reportlab")
        return False

    try:
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=20,
            spaceAfter=12,
            textColor=colors.HexColor("#1e40af"),
        )
        heading_style = ParagraphStyle(
            "Heading",
            parent=styles["Heading2"],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#1e40af"),
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=body_style,
            leftIndent=20,
            bulletIndent=10,
        )

        story = []
        company = audit_data.get("company", {})
        scores = audit_data.get("scores", {})
        strengths = audit_data.get("strengths", [])
        weaknesses = audit_data.get("weaknesses", [])
        recommendations = audit_data.get("recommendations", [])
        meta = audit_data.get("_meta", {})

        # Titel
        company_name = company.get("name", "Webbplats")
        story.append(Paragraph(f"Webbplats-Audit: {company_name}", title_style))
        story.append(Spacer(1, 0.3 * cm))

        # Meta-info
        url = meta.get("url", "")
        date = meta.get("audit_date", "")[:10] if meta.get("audit_date") else ""
        if url or date:
            meta_text = f"<b>URL:</b> {url}<br/><b>Datum:</b> {date}"
            story.append(Paragraph(meta_text, body_style))
            story.append(Spacer(1, 0.5 * cm))

        # Företagsbeskrivning
        desc = company.get("description", "")
        if desc:
            story.append(Paragraph("Om företaget", heading_style))
            story.append(Paragraph(desc, body_style))

        # Poängtabell
        if scores:
            story.append(Paragraph("Bedömning (1-10)", heading_style))
            score_data = [
                ["Kategori", "Poäng"],
                ["Design", str(scores.get("design", "-"))],
                ["Innehåll", str(scores.get("content", "-"))],
                ["Användbarhet", str(scores.get("usability", "-"))],
                ["Mobilvänlighet", str(scores.get("mobile", "-"))],
                ["SEO", str(scores.get("seo", "-"))],
                ["Helhetsomdöme", str(scores.get("overall", "-"))],
            ]
            t = Table(score_data, colWidths=[8 * cm, 3 * cm])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (1, 0), (1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 0.3 * cm))

        # Styrkor
        if strengths:
            story.append(Paragraph("Styrkor", heading_style))
            for s in strengths:
                story.append(Paragraph(f"• {s}", bullet_style))

        # Svagheter
        if weaknesses:
            story.append(Paragraph("Förbättringsområden", heading_style))
            for w in weaknesses:
                story.append(Paragraph(f"• {w}", bullet_style))

        # Rekommendationer
        if recommendations:
            story.append(Paragraph("Rekommendationer", heading_style))
            for r in recommendations:
                story.append(Paragraph(f"• {r}", bullet_style))

        # Footer
        story.append(Spacer(1, 1 * cm))
        footer = "Rapport genererad av SajtStudio.se"
        story.append(Paragraph(footer, body_style))

        doc.build(story)
        return True
    except Exception as e:
        print(f"⚠️  PDF-generering misslyckades: {e}")
        return False


# =============================================================================
# PROGRAMMATISKT ANROP
# =============================================================================


def run_audit_to_folder(url: str, output_dir: Path) -> Dict[str, Any]:
    """
    Kör audit mot en URL och sparar resultat i output_dir.
    Returnerar paths och kostnadssammanfattning.
    """
    if not url.startswith("http"):
        url = "https://" + url

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_cost_usd = 0.0
    total_cost_sek = 0.0

    # 1. Audit
    audit_data, in_tok, out_tok, sources = perform_audit(url)
    usd, sek = calculate_cost(in_tok, out_tok, AUDIT_MODEL)
    total_cost_usd += usd
    total_cost_sek += sek

    # 2. Analysis
    analysis = create_company_analysis(audit_data)

    # 3. Profile
    profile_text, in_tok, out_tok = generate_company_profile(audit_data)
    usd, sek = calculate_cost(in_tok, out_tok, PROFILE_MODEL)
    total_cost_usd += usd
    total_cost_sek += sek

    # 4. Save files
    audit_file = output_dir / "audit_report.json"
    analysis_file = output_dir / "company_analysis.json"
    profile_file = output_dir / "company_profile.txt"
    pdf_file = output_dir / "audit_report.pdf"

    audit_file.write_text(
        json.dumps(audit_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    analysis_file.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    profile_file.write_text(profile_text, encoding="utf-8")

    # 5. Generate PDF (försök först med snyggare version)
    pdf_generated = False
    try:
        # Importera det nya skriptet om det finns
        from generate_beautiful_pdf import generate_pdf
        pdf_generated = generate_pdf(audit_data, pdf_file)
    except ImportError:
        # Fallback till gamla metoden
        pdf_generated = generate_audit_pdf(audit_data, pdf_file)
    
    if pdf_generated:
        print(f"   ✓ Skapade PDF: {pdf_file.name}")

    return {
        "url": url,
        "output_dir": str(output_dir),
        "audit_file": str(audit_file),
        "audit_pdf": str(pdf_file) if pdf_generated else None,
        "analysis_file": str(analysis_file),
        "profile_file": str(profile_file),
        "total_cost_usd": total_cost_usd,
        "total_cost_sek": total_cost_sek,
        "sources": len(sources),
    }


# =============================================================================
# HUVUDFUNKTION
# =============================================================================


def main():
    """Huvudfunktion - kör audit och generera alla dokument."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Skapa företagsanalys från webbplats-URL"
    )
    parser.add_argument("url", help="Webbplats-URL att analysera")
    parser.add_argument(
        "--output",
        "-o",
        default="./audit_output",
        help="Output-mapp (default: ./audit_output)",
    )

    args = parser.parse_args()
    url = args.url
    output_dir = Path(args.output)

    # Säkerställ https://
    if not url.startswith("http"):
        url = "https://" + url

    print("=" * 60)
    print("  WEBBPLATS-AUDIT MED AI")
    print("=" * 60)
    print(f"  URL: {url}")
    print(f"  Output: {output_dir}")
    print("=" * 60)

    total_cost_usd = 0
    total_cost_sek = 0

    # 1. Utför audit
    print("\n📊 STEG 1: Webbplats-audit")
    print("-" * 40)

    audit_data, in_tok, out_tok, sources = perform_audit(url)
    usd, sek = calculate_cost(in_tok, out_tok, AUDIT_MODEL)
    total_cost_usd += usd
    total_cost_sek += sek

    print(f"   ✓ Tokens: {in_tok} in / {out_tok} out")
    print(f"   ✓ Kostnad: {sek:.2f} SEK (${usd:.4f})")
    print(f"   ✓ Källor: {len(sources)} hittade")

    # 2. Skapa company_analysis
    print("\n📋 STEG 2: Skapar företagsanalys")
    print("-" * 40)

    analysis = create_company_analysis(audit_data)
    print(f"   ✓ Företag: {analysis['company_name']}")
    print(f"   ✓ Bransch: {analysis['industry']}")

    # 3. Generera företagsprofil
    print("\n📝 STEG 3: Genererar företagsprofil")
    print("-" * 40)

    profile_text, in_tok, out_tok = generate_company_profile(audit_data)
    usd, sek = calculate_cost(in_tok, out_tok, PROFILE_MODEL)
    total_cost_usd += usd
    total_cost_sek += sek

    print(f"   ✓ Kostnad: {sek:.2f} SEK (${usd:.4f})")

    # 4. Spara alla filer
    print("\n💾 STEG 4: Sparar filer")
    print("-" * 40)

    output_dir.mkdir(parents=True, exist_ok=True)

    # audit_report.json
    audit_file = output_dir / "audit_report.json"
    audit_file.write_text(
        json.dumps(audit_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"   ✓ {audit_file}")

    # company_analysis.json
    analysis_file = output_dir / "company_analysis.json"
    analysis_file.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"   ✓ {analysis_file}")

    # company_profile.txt
    profile_file = output_dir / "company_profile.txt"
    profile_file.write_text(profile_text, encoding="utf-8")
    print(f"   ✓ {profile_file}")

    # Sammanfattning
    print("\n" + "=" * 60)
    print("  ✅ AUDIT KLAR!")
    print("=" * 60)
    print(f"  Företag: {analysis['company_name']}")
    print(f"  Bransch: {analysis['industry']}")
    print(f"  Filer: {output_dir}")
    print(f"  Total kostnad: {total_cost_sek:.2f} SEK (${total_cost_usd:.4f})")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
