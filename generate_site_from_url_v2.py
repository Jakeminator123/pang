# -*- coding: utf-8 -*-
"""
generate_site_from_url_v2.py - Generate improved website from URL or content.txt

Standalone script that:
1. Loads company data from content.txt (Bolagsverket/PoIT format) as PRIMARY source
2. Optionally scrapes/audits an existing website using OpenAI web_search
3. Audits extra sources (news articles, allabolag.se, any website) for more info
4. Generates an improved website using v0 Platform API

Usage:
    # Interaktiv mode (rekommenderas) - med filväljare för content.txt
    python generate_site_from_url_v2.py
    
    # Med content.txt som grund (företag utan hemsida)
    python generate_site_from_url_v2.py --content ./content.txt
    
    # Med content.txt + befintlig hemsida för design
    python generate_site_from_url_v2.py https://www.example.com --content ./content.txt
    
    # Med extra källor (nyhetsartiklar, allabolag, vad som helst)
    python generate_site_from_url_v2.py --content ./content.txt --extra-url https://nyhetsartikel.se/...
    
    # Med output-mapp
    python generate_site_from_url_v2.py --content ./content.txt --output ./my_output

Features:
    - content.txt som PRIMÄR datakälla (Bolagsverket/PoIT kungörelse-format)
    - Interaktiv filväljare (popup) eller manuell sökväg för content.txt
    - Stöd för FLERA extra URLs (nyhetsartiklar, allabolag.se, LinkedIn, etc.)
    - Extra källor kan vara VAD SOM HELST - nyheter, branschinfo, konkurrenter
    - Designelement hämtas från befintlig hemsida (om sådan finns)
    - Företagsinfo från content.txt prioriteras
    - Manuell information kan läggas till interaktivt

content.txt format (Bolagsverket/PoIT):
    - Org nr: 559561-3075
    - Företagsnamn: Tre Magma AB
    - Säte: Stockholm
    - Bildat: 2025-11-25
    - Verksamhet: Beskrivning av verksamheten...
    - etc.

Requirements:
    - OPENAI_API_KEY hårdkodad i skriptet eller i .env/miljövariabel
    - V0_API_KEY hårdkodad i skriptet eller i .env/miljövariabel
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# =============================================================================
# CONTENT.TXT PARSER (Bolagsverket/PoIT format)
# =============================================================================


def parse_content_txt(file_path: Path) -> Optional[Dict]:
    """
    Parse content.txt file (Bolagsverket/PoIT kungörelse format).
    
    Returns a dict with company information extracted from the file.
    """
    if not file_path.exists():
        return None
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"   ⚠ Kunde inte läsa fil: {e}")
        return None
    
    data = {
        "source_file": str(file_path),
        "company": {},
        "contact": {},
        "board": {},
        "financials": {},
        "raw_content": content,
    }
    
    # Extract key fields using regex patterns
    patterns = {
        "org_nr": r"(?:Org\s*nr|Organisationsnummer)[:\s]*(\d{6}-\d{4})",
        "company_name": r"(?:Företagsnamn|Namn/fastighetsbeteckning)[:\s]*([^,\n]+?)(?:,\s*\d{6}-\d{4})?(?:\n|$)",
        "location": r"Säte[:\s]*([^\n]+)",
        "address": r"Postadress[:\s]*([^\n]+)",
        "company_type": r"Typ[:\s]*([^\n]+)",
        "founded": r"Bildat[:\s]*(\d{4}-\d{2}-\d{2})",
        "business_description": r"Verksamhet[:\s]*([^\n]+(?:\n(?![A-ZÅÄÖ][a-zåäö]*:)[^\n]+)*)",
        "share_capital": r"Aktiekapital[:\s]*([^\n]+)",
        "fiscal_year": r"Räkenskapsår[:\s]*([^\n]+)",
        "board_members": r"Styrelseledamöter[:\s]*([^\n]+(?:\n(?![A-ZÅÄÖ][a-zåäö]*:)[^\n]+)*)",
        "board_alternates": r"Styrelsesuppleanter[:\s]*([^\n]+(?:\n(?![A-ZÅÄÖ][a-zåäö]*:)[^\n]+)*)",
        "signing_rights": r"Firmateckning[:\s]*([^\n]+)",
        "county": r"Län[:\s]*([^\n]+)",
        "registration_date": r"Registreringsdatum[:\s]*(\d{4}-\d{2}-\d{2})",
        "kungörelse_id": r"Kungörelse-id[:\s]*([^\n]+)",
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip()
            # Clean up the value
            value = re.sub(r'\s+', ' ', value)
            
            # Map to appropriate category
            if key in ["org_nr", "company_name", "company_type", "founded", "business_description"]:
                data["company"][key] = value
            elif key in ["location", "address", "county"]:
                data["contact"][key] = value
            elif key in ["board_members", "board_alternates", "signing_rights"]:
                data["board"][key] = value
            elif key in ["share_capital", "fiscal_year"]:
                data["financials"][key] = value
            else:
                data[key] = value
    
    # Also try to extract from the structured format at the top (Namn/fastighetsbeteckning line)
    name_match = re.search(r"Namn/fastighetsbeteckning\s*\n\s*([^,\n]+),\s*(\d{6}-\d{4})", content)
    if name_match:
        if not data["company"].get("company_name"):
            data["company"]["company_name"] = name_match.group(1).strip()
        if not data["company"].get("org_nr"):
            data["company"]["org_nr"] = name_match.group(2).strip()
    
    return data


def content_to_audit_data(content_data: Dict) -> Dict:
    """
    Convert parsed content.txt data to audit_data format for generation.
    """
    company = content_data.get("company", {})
    contact = content_data.get("contact", {})
    board = content_data.get("board", {})
    financials = content_data.get("financials", {})
    
    # Build a proper description from business_description
    description = company.get("business_description", "")
    
    # Extract city from location or address
    location = contact.get("location", "")
    address = contact.get("address", "")
    county = contact.get("county", "")
    
    full_location = location
    if county and county not in full_location:
        full_location = f"{location}, {county}" if location else county
    
    audit_data = {
        "company": {
            "name": company.get("company_name", "Okänt företag"),
            "tagline": None,  # Will be generated
            "industry": None,  # Can be inferred from business_description
            "description": description,
            "founded": company.get("founded", "Okänt"),
            "location": full_location,
            "size": "Nystartat" if company.get("founded") else "Okänt",
            "org_nr": company.get("org_nr"),
            "company_type": company.get("company_type"),
        },
        "contact": {
            "email": None,
            "phone": None,
            "address": address,
            "social_media": [],
        },
        "board": {
            "members": board.get("board_members"),
            "alternates": board.get("board_alternates"),
            "signing_rights": board.get("signing_rights"),
        },
        "financials": {
            "share_capital": financials.get("share_capital"),
            "fiscal_year": financials.get("fiscal_year"),
        },
        "products_services": {
            "main_offering": description[:200] if description else None,
            "categories": [],
            "key_products": [],
            "unique_features": [],
        },
        "content": {
            "hero_title": None,
            "hero_subtitle": None,
            "cta_text": "Kontakta oss",
            "key_messages": [],
            "target_audience": None,
            "tone_of_voice": "Professionell",
        },
        "design": {
            "primary_color": "#3b82f6",
            "secondary_color": "#1e40af",
            "accent_color": "#10b981",
            "background_style": "Ljus",
            "font_style": "Modern sans-serif",
            "imagery_style": "Professionell",
            "overall_impression": None,
        },
        "pages": [],
        "strengths": [],
        "weaknesses": [],
        "improvement_suggestions": [],
        "_meta": {
            "source": "content.txt",
            "source_file": content_data.get("source_file"),
            "parsed_at": datetime.now().isoformat(),
        },
    }
    
    return audit_data


def select_file_dialog(title: str = "Välj content.txt", filetypes: List[tuple] = None) -> Optional[Path]:
    """
    Open a file picker dialog using tkinter.
    Returns the selected file path or None if cancelled.
    """
    if filetypes is None:
        filetypes = [("Text files", "*.txt"), ("All files", "*.*")]
    
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Create hidden root window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)  # Bring to front
        
        # Open file dialog
        file_path = filedialog.askopenfilename(
            title=title,
            filetypes=filetypes,
            initialdir=os.getcwd(),
        )
        
        root.destroy()
        
        if file_path:
            return Path(file_path)
        return None
        
    except ImportError:
        print("   ⚠ tkinter inte tillgängligt - använd terminal-input istället")
        return None
    except Exception as e:
        print(f"   ⚠ Kunde inte öppna filväljare: {e}")
        return None

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_MODEL = "gpt-4o"  # For web_search audit
V0_MODEL = "v0-1.5-md"  # For site generation
V0_API_BASE = "https://api.v0.dev/v1"
V0_CHATS_ENDPOINT = f"{V0_API_BASE}/chats"
REQUEST_TIMEOUT = 300.0
POLL_INTERVAL = 4
MAX_POLL_ATTEMPTS = 30

# =============================================================================
# API KEYS (HARDCODED)
# =============================================================================
# OBS: API-nycklar är hårdkodade här för enkelhet.
# För produktion bör dessa ligga i .env eller miljövariabler.

OPENAI_API_KEY = ""  # Sätt din OpenAI API-nyckel här
V0_API_KEY = ""  # Sätt din v0 API-nyckel här


def get_api_key(key_name: str) -> str:
    """Get API key from hardcoded values or environment."""
    # Först försök hårdkodade värden
    if key_name == "OPENAI_API_KEY" and OPENAI_API_KEY:
        return OPENAI_API_KEY
    if key_name == "V0_API_KEY" and V0_API_KEY:
        return V0_API_KEY
    
    # Annars försök miljövariabler
    api_key = os.getenv(key_name)
    if api_key:
        return api_key
    
    # Försök läsa från .env som fallback
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                if key == key_name and value:
                    return value
    
    # Om inget hittas, visa fel
    print(f"❌ {key_name} saknas!")
    print(f"   Sätt den hårdkodad i skriptet eller som miljövariabel")
    sys.exit(1)


# =============================================================================
# OPENAI WEB SEARCH
# =============================================================================


def call_web_search(
    prompt: str,
    model: str = "gpt-4o",
    allowed_domains: Optional[List[str]] = None,
    timeout: int = 300,
) -> Tuple[str, int, int, List[Dict]]:
    """
    Call OpenAI API with web_search tool.

    Returns:
        Tuple of (response_text, input_tokens, output_tokens, sources)
    """
    from openai import OpenAI

    client = OpenAI(api_key=get_api_key("OPENAI_API_KEY"))

    # Build web_search tool
    web_search_tool = {"type": "web_search"}

    if allowed_domains:
        clean_domains = []
        for domain in allowed_domains[:20]:
            domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
            if domain:
                clean_domains.append(domain)
        if clean_domains:
            web_search_tool["search_context_size"] = "high"

    # Swedish results
    web_search_tool["user_location"] = {
        "type": "approximate",
        "country": "SE",
        "city": "Stockholm",
        "region": "Stockholm",
    }

    params = {
        "model": model,
        "tools": [web_search_tool],
        "input": prompt,
    }

    response = client.responses.create(**params, timeout=timeout)

    # Extract text
    text = ""
    if hasattr(response, "output_text"):
        text = response.output_text
    elif hasattr(response, "output"):
        for item in response.output:
            if hasattr(item, "content"):
                for c in item.content:
                    if hasattr(c, "text"):
                        text += c.text

    # Token usage
    in_tok = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    out_tok = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0

    # Extract sources
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


def parse_json_response(text: str) -> Optional[Dict]:
    """Extract JSON from AI response."""
    # Try to find JSON block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try parsing whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    return None


# =============================================================================
# WEBSITE AUDIT
# =============================================================================


def get_audit_prompt(url: str, is_extra_source: bool = False, extra_context: Optional[str] = None) -> str:
    """Create prompt for website audit."""
    context_note = ""
    if is_extra_source and extra_context:
        context_note = f"\nVIKTIGT: Denna URL är en EXTRA källa för att komplettera information från huvudwebbplatsen.\nExtra kontext: {extra_context}\nKombinera information från båda källor för att få en komplett bild.\n"
    elif is_extra_source:
        context_note = "\nVIKTIGT: Denna URL är en EXTRA källa för att komplettera information från huvudwebbplatsen.\nFokusera på information som kanske inte finns på huvudwebbplatsen (företagsstorlek, branschinfo, nyheter, etc).\n"
    
    return f"""Analysera webbplatsen grundligt: {url}
{context_note}
Använd web_search för att hitta ALL information om företaget och dess webbplats.
Gå igenom alla sidor du kan hitta.

Returnera ett JSON-objekt med följande struktur:

{{
    "company": {{
        "name": "Företagsnamn",
        "tagline": "Slogan eller kort beskrivning",
        "industry": "Bransch",
        "description": "Detaljerad beskrivning (3-5 meningar)",
        "founded": "År eller 'Okänt'",
        "location": "Stad, Land",
        "size": "Antal anställda eller 'Okänt'"
    }},
    "contact": {{
        "email": "email@example.com eller null",
        "phone": "Telefonnummer eller null",
        "address": "Adress eller null",
        "social_media": ["Instagram URL", "Facebook URL", etc]
    }},
    "products_services": {{
        "main_offering": "Huvudsakligt erbjudande",
        "categories": ["Kategori 1", "Kategori 2"],
        "key_products": [
            {{"name": "Produkt 1", "description": "Beskrivning", "price_range": "Prisintervall"}},
            {{"name": "Produkt 2", "description": "Beskrivning", "price_range": "Prisintervall"}}
        ],
        "unique_features": ["Feature 1", "Feature 2"]
    }},
    "content": {{
        "hero_title": "Exakt rubrik från hemsidan",
        "hero_subtitle": "Underrubrik",
        "cta_text": "Call-to-action text",
        "key_messages": ["Budskap 1", "Budskap 2"],
        "target_audience": "Detaljerad beskrivning av målgrupp",
        "tone_of_voice": "Formell/informell/lekfull etc"
    }},
    "design": {{
        "primary_color": "#hexkod",
        "secondary_color": "#hexkod",
        "accent_color": "#hexkod",
        "background_style": "Ljus/mörk/gradient etc",
        "font_style": "Typsnittsstil",
        "imagery_style": "Fotografier/illustrationer/etc",
        "overall_impression": "Detaljerad beskrivning av designen"
    }},
    "pages": [
        {{"name": "Startsida", "key_content": "Beskrivning av innehåll"}},
        {{"name": "Om oss", "key_content": "Beskrivning av innehåll"}},
        {{"name": "Produkter", "key_content": "Beskrivning av innehåll"}}
    ],
    "strengths": ["Styrka 1", "Styrka 2", "Styrka 3"],
    "weaknesses": ["Svaghet 1", "Svaghet 2"],
    "improvement_suggestions": [
        "Konkret förslag 1",
        "Konkret förslag 2",
        "Konkret förslag 3"
    ]
}}

VIKTIGT:
- Var så detaljerad som möjligt
- Använd svenska för beskrivningar
- Extrahera FAKTISK information från sajten
- Ta med alla produkter/tjänster du hittar
- Notera designelement som färger, typografi, bildstil
- Om något inte hittas, sätt null eller "Okänt"
"""


def perform_audit(url: str, is_extra_source: bool = False, extra_context: Optional[str] = None) -> Tuple[Dict, int, int]:
    """
    Perform website audit with AI and web_search.

    Args:
        url: URL to audit
        is_extra_source: If True, this is an extra source (e.g., allabolag.se)
        extra_context: Optional context about why this URL is being audited

    Returns:
        Tuple of (audit_data, input_tokens, output_tokens)
    """
    source_type = "Extra källa" if is_extra_source else "Huvudwebbplats"
    print(f"\n🔍 Auditerar {source_type.lower()}: {url}")
    print(f"   Modell: {AUDIT_MODEL}")

    # Clean URL for domain filter
    clean_url = url.replace("https://", "").replace("http://", "").split("/")[0]

    prompt = get_audit_prompt(url, is_extra_source=is_extra_source, extra_context=extra_context)

    print("   Anropar AI med web_search...")
    text, in_tok, out_tok, sources = call_web_search(
        prompt=prompt,
        model=AUDIT_MODEL,
        allowed_domains=[clean_url],
        timeout=300,
    )

    print(f"   ✓ Tokens: {in_tok:,} in / {out_tok:,} out")
    print(f"   ✓ Källor: {len(sources)} hittade")

    # Parse JSON
    audit_data = parse_json_response(text)

    if not audit_data:
        print("   ⚠ Kunde inte parsa JSON, skapar minimal struktur")
        audit_data = {
            "company": {"name": clean_url, "description": text[:1000]},
            "raw_response": text,
        }

    # Add metadata
    audit_data["_meta"] = {
        "url": url,
        "audit_date": datetime.now().isoformat(),
        "model": AUDIT_MODEL,
        "sources_count": len(sources),
        "is_extra_source": is_extra_source,
    }

    return audit_data, in_tok, out_tok


def merge_audit_data(main_audit: Dict, extra_audit: Dict) -> Dict:
    """
    Merge audit data from main website and extra source.
    Prioritizes main website for design/visual elements, combines other info.
    """
    merged = main_audit.copy()
    
    # Merge company info (extra source may have more details)
    main_company = main_audit.get("company", {})
    extra_company = extra_audit.get("company", {})
    
    merged["company"] = {
        "name": main_company.get("name") or extra_company.get("name"),
        "tagline": main_company.get("tagline") or extra_company.get("tagline"),
        "industry": extra_company.get("industry") or main_company.get("industry"),  # Extra source often better
        "description": extra_company.get("description") or main_company.get("description"),  # Extra source often more detailed
        "founded": extra_company.get("founded") or main_company.get("founded"),
        "location": main_company.get("location") or extra_company.get("location"),
        "size": extra_company.get("size") or main_company.get("size"),  # Extra source often has this
    }
    
    # Merge contact (prefer main, supplement with extra)
    main_contact = main_audit.get("contact", {})
    extra_contact = extra_audit.get("contact", {})
    merged["contact"] = {
        "email": main_contact.get("email") or extra_contact.get("email"),
        "phone": main_contact.get("phone") or extra_contact.get("phone"),
        "address": main_contact.get("address") or extra_contact.get("address"),
        "social_media": list(set((main_contact.get("social_media") or []) + (extra_contact.get("social_media") or []))),
    }
    
    # Merge products/services (combine both)
    main_products = main_audit.get("products_services", {})
    extra_products = extra_audit.get("products_services", {})
    
    # Combine key products
    main_key_products = main_products.get("key_products", [])
    extra_key_products = extra_products.get("key_products", [])
    combined_products = main_key_products.copy()
    
    # Add products from extra source that aren't duplicates
    for extra_prod in extra_key_products:
        if not any(p.get("name") == extra_prod.get("name") for p in combined_products):
            combined_products.append(extra_prod)
    
    merged["products_services"] = {
        "main_offering": main_products.get("main_offering") or extra_products.get("main_offering"),
        "categories": list(set((main_products.get("categories") or []) + (extra_products.get("categories") or []))),
        "key_products": combined_products,
        "unique_features": list(set((main_products.get("unique_features") or []) + (extra_products.get("unique_features") or []))),
    }
    
    # Merge content (prefer main for hero/tone, supplement with extra)
    main_content = main_audit.get("content", {})
    extra_content = extra_audit.get("content", {})
    merged["content"] = {
        "hero_title": main_content.get("hero_title") or extra_content.get("hero_title"),
        "hero_subtitle": main_content.get("hero_subtitle") or extra_content.get("hero_subtitle"),
        "cta_text": main_content.get("cta_text") or extra_content.get("cta_text"),
        "key_messages": list(set((main_content.get("key_messages") or []) + (extra_content.get("key_messages") or []))),
        "target_audience": extra_content.get("target_audience") or main_content.get("target_audience"),  # Extra source often better
        "tone_of_voice": main_content.get("tone_of_voice") or extra_content.get("tone_of_voice"),
    }
    
    # Design: ALWAYS prefer main website (colors, style come from actual site)
    # Only supplement with extra if main is missing
    main_design = main_audit.get("design", {})
    extra_design = extra_audit.get("design", {})
    merged["design"] = {
        "primary_color": main_design.get("primary_color") or extra_design.get("primary_color"),
        "secondary_color": main_design.get("secondary_color") or extra_design.get("secondary_color"),
        "accent_color": main_design.get("accent_color") or extra_design.get("accent_color"),
        "background_style": main_design.get("background_style") or extra_design.get("background_style"),
        "font_style": main_design.get("font_style") or extra_design.get("font_style"),
        "imagery_style": main_design.get("imagery_style") or extra_design.get("imagery_style"),
        "overall_impression": main_design.get("overall_impression") or extra_design.get("overall_impression"),
    }
    
    # Merge pages (combine both)
    main_pages = main_audit.get("pages", [])
    extra_pages = extra_audit.get("pages", [])
    combined_pages = main_pages.copy()
    for extra_page in extra_pages:
        if not any(p.get("name") == extra_page.get("name") for p in combined_pages):
            combined_pages.append(extra_page)
    merged["pages"] = combined_pages
    
    # Merge strengths/weaknesses/improvements (combine both)
    merged["strengths"] = list(set((main_audit.get("strengths") or []) + (extra_audit.get("strengths") or [])))
    merged["weaknesses"] = list(set((main_audit.get("weaknesses") or []) + (extra_audit.get("weaknesses") or [])))
    merged["improvement_suggestions"] = list(set((main_audit.get("improvement_suggestions") or []) + (extra_audit.get("improvement_suggestions") or [])))
    
    # Update metadata
    merged["_meta"]["merged_from"] = [
        main_audit["_meta"].get("url"),
        extra_audit["_meta"].get("url"),
    ]
    merged["_meta"]["merged_at"] = datetime.now().isoformat()
    
    return merged


# =============================================================================
# V0 API CLIENT
# =============================================================================


async def generate_with_v0(prompt: str, api_key: str) -> Dict[str, Any]:
    """
    Generate React component using v0 Platform API.

    Returns:
        Dict with chatId, demoUrl, versionId, status, files, etc.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = """You are an expert React and Next.js developer creating production-ready websites.

TECHNICAL REQUIREMENTS:
- React 18+ functional components with TypeScript
- Tailwind CSS for ALL styling (no external CSS files)
- Lucide React for icons (import from 'lucide-react')
- Next.js App Router conventions
- Responsive design (mobile-first approach)

CODE QUALITY:
- Clean, readable code with proper formatting
- Semantic HTML elements (nav, main, section, article)
- Proper TypeScript types (no 'any')
- Accessible (ARIA labels, keyboard navigation, focus states)
- SEO-friendly structure (proper heading hierarchy)

STYLING:
- Use Tailwind utility classes exclusively
- Consistent spacing scale (4, 8, 12, 16, 24, 32, 48)
- Smooth transitions: transition-all duration-300
- Proper hover/focus/active states
- Beautiful, modern design with attention to detail"""

    payload = {
        "message": prompt,
        "system": system_prompt,
        "chatPrivacy": "private",
        "modelConfiguration": {
            "modelId": V0_MODEL,
            "imageGenerations": False,
        },
        "responseMode": "sync",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(V0_CHATS_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

        chat_id = result.get("id")
        latest_version = result.get("latestVersion", {})
        demo_url = latest_version.get("demoUrl")
        status = latest_version.get("status")

        # Poll for demoUrl if not immediately available
        if not demo_url and status != "failed":
            print("   ⏳ Väntar på demoUrl...")
            for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
                await asyncio.sleep(POLL_INTERVAL)
                poll_response = await client.get(
                    f"{V0_CHATS_ENDPOINT}/{chat_id}", headers=headers
                )
                poll_result = poll_response.json()
                latest_version = poll_result.get("latestVersion", {})
                demo_url = latest_version.get("demoUrl")
                status = latest_version.get("status")

                if status == "completed" and demo_url:
                    break
                elif status == "failed":
                    raise ValueError("v0 generation failed")

                if attempt % 5 == 0:
                    print(f"   ⏳ Väntar... (försök {attempt}/{MAX_POLL_ATTEMPTS})")

        return {
            "chatId": chat_id,
            "demoUrl": demo_url,
            "versionId": latest_version.get("id"),
            "status": status,
            "model": V0_MODEL,
        }


# =============================================================================
# PROMPT BUILDER
# =============================================================================


def build_generation_prompt(audit_data: Dict, manual_info: Optional[str] = None) -> str:
    """Build v0 prompt based on audit data."""
    company = audit_data.get("company", {})
    content = audit_data.get("content", {})
    design = audit_data.get("design", {})
    products = audit_data.get("products_services", {})
    pages = audit_data.get("pages", [])
    improvements = audit_data.get("improvement_suggestions", [])
    strengths = audit_data.get("strengths", [])
    
    # Add manual info if provided
    manual_section = ""
    if manual_info:
        manual_section = f"\n\nMANUELL INFORMATION FRÅN ANVÄNDAREN:\n{manual_info}\n\nVIKTIGT: Använd denna information för att komplettera och förbättra beskrivningen av företaget."

    # Build products section
    products_text = ""
    if products.get("key_products"):
        products_text = "\n\nPRODUKTER/TJÄNSTER:\n"
        for p in products.get("key_products", []):
            products_text += f"- {p.get('name', 'Produkt')}: {p.get('description', '')}\n"

    # Build pages section
    pages_text = ""
    if pages:
        pages_text = "\n\nBEFINTLIGA SIDOR ATT FÖRBÄTTRA:\n"
        for page in pages:
            pages_text += f"- {page.get('name', 'Sida')}: {page.get('key_content', '')}\n"

    # Build improvements section
    improvements_text = ""
    if improvements:
        improvements_text = "\n\nFÖRBÄTTRINGSFÖRSLAG ATT IMPLEMENTERA:\n"
        for imp in improvements:
            improvements_text += f"- {imp}\n"

    prompt = f"""Skapa en FÖRBÄTTRAD och modernare version av webbplatsen för {company.get('name', 'Företaget')}.

FÖRETAGSINFORMATION:
- Företagsnamn: {company.get('name', 'Företaget')}
- Bransch: {company.get('industry', 'Okänd')}
- Beskrivning: {company.get('description', '')}
- Tagline: {company.get('tagline', '')}
- Plats: {company.get('location', '')}
- Företagsstorlek: {company.get('size', 'Okänt')}
- Grundat: {company.get('founded', 'Okänt')}
{manual_section}

NUVARANDE DESIGN (REFERENS - FÖRBÄTTRA DETTA):
- Primärfärg: {design.get('primary_color', '#3b82f6')}
- Sekundärfärg: {design.get('secondary_color', '#1e40af')}
- Accentfärg: {design.get('accent_color', '#10b981')}
- Bildstil: {design.get('imagery_style', 'Modern')}
- Övergripande intryck: {design.get('overall_impression', '')}

INNEHÅLL ATT BEHÅLLA:
- Hero-rubrik: {content.get('hero_title', '')}
- Underrubrik: {content.get('hero_subtitle', '')}
- CTA: {content.get('cta_text', 'Kontakta oss')}
- Målgrupp: {content.get('target_audience', '')}
- Tonalitet: {content.get('tone_of_voice', 'Professionell')}
{products_text}
{pages_text}

STYRKOR ATT BEHÅLLA:
{chr(10).join(['- ' + s for s in strengths]) if strengths else '- Originalets kärnvärden'}
{improvements_text}

DESIGNKRAV FÖR NY SAJT:
1. HERO-SEKTION:
   - Stor, impactful hero med företagets huvudbudskap
   - Professionella bakgrundsbilder/gradienter
   - Tydlig CTA-knapp med hover-effekter
   - Eventuellt animerad text eller element

2. PRODUKTER/TJÄNSTER:
   - Grid-layout för produkter med hover-effekter
   - Kategorier om tillämpligt
   - Prisintervall eller "Kontakta oss för pris"
   
3. OM OSS / FÖRETAGET:
   - Företagets story och värderingar
   - Team-sektion om relevant
   - Trust indicators (år i branschen, kunder, etc)

4. KONTAKT:
   - Kontaktformulär
   - Kontaktuppgifter
   - Social media-länkar
   - Google Maps om adress finns

5. TEKNISKA KRAV:
   - Fully responsive (mobile-first)
   - Smooth scroll navigation
   - Subtle animations med Intersection Observer
   - Proper loading states
   - Accessibility (WCAG 2.1 AA)

6. FOOTER:
   - Snabblänkar
   - Kontaktinfo
   - Social media
   - Copyright

VIKTIGT: 
- Skapa en BÄTTRE version, inte en kopia
- Modern, elegant design med professionellt intryck
- Behåll företagets identitet men uppgradera visuellt
- Använd Lucide React för ikoner
- Tailwind CSS för all styling
- TypeScript med React 18+"""

    return prompt


# =============================================================================
# INTERACTIVE PROMPT
# =============================================================================


def get_user_input() -> Tuple[Optional[str], List[Tuple[str, str]], Optional[str], Optional[Dict]]:
    """
    Interactive prompt to get URL and optional extra information.
    
    Returns:
        Tuple of (main_url, extra_urls_with_context, manual_info, content_data)
        extra_urls_with_context is a list of (url, description) tuples
        content_data is parsed content.txt data (if provided)
    """
    print("=" * 60)
    print("  HEMSIDEGENERERING - INTERAKTIV SETUP")
    print("=" * 60)
    print()
    
    # =========================================================================
    # CONTENT.TXT - Primary data source
    # =========================================================================
    content_data = None
    
    print("📄 STEG 1: Ladda content.txt (Bolagsverket/PoIT-data)")
    print("-" * 40)
    print("   Detta är grunddata om företaget (org.nr, verksamhet, etc.)")
    print()
    print("   Alternativ:")
    print("   [1] Öppna filväljare (popup)")
    print("   [2] Ange sökväg manuellt")
    print("   [3] Använd ./content.txt (standard)")
    print("   [4] Hoppa över (inget content.txt)")
    print()
    
    content_choice = input("   Välj alternativ (1-4): ").strip()
    
    if content_choice == "1":
        # File picker dialog
        print("   📂 Öppnar filväljare...")
        file_path = select_file_dialog("Välj content.txt")
        if file_path:
            print(f"   ✓ Vald fil: {file_path}")
            content_data = parse_content_txt(file_path)
        else:
            print("   ⚠ Ingen fil vald")
    
    elif content_choice == "2":
        # Manual path
        path_input = input("   Ange sökväg till content.txt: ").strip()
        if path_input:
            file_path = Path(path_input)
            if file_path.exists():
                content_data = parse_content_txt(file_path)
                if content_data:
                    print(f"   ✓ Laddade: {file_path}")
            else:
                print(f"   ⚠ Fil finns inte: {file_path}")
    
    elif content_choice == "3" or content_choice == "":
        # Default ./content.txt
        default_path = Path("./content.txt")
        if default_path.exists():
            content_data = parse_content_txt(default_path)
            if content_data:
                print(f"   ✓ Laddade: {default_path}")
        else:
            print("   ⚠ ./content.txt finns inte")
    
    else:
        print("   ℹ Hoppar över content.txt")
    
    # Show parsed content summary
    if content_data and content_data.get("company"):
        company = content_data.get("company", {})
        print()
        print("   📋 Extraherad information:")
        if company.get("company_name"):
            print(f"      Företag: {company.get('company_name')}")
        if company.get("org_nr"):
            print(f"      Org.nr: {company.get('org_nr')}")
        if company.get("founded"):
            print(f"      Bildat: {company.get('founded')}")
        if company.get("business_description"):
            desc = company.get("business_description", "")[:100]
            print(f"      Verksamhet: {desc}...")
    
    print()
    
    # =========================================================================
    # Main URL (optional if content.txt is provided)
    # =========================================================================
    print("🌐 STEG 2: Huvudwebbplats (för design/audit)")
    print("-" * 40)
    
    if content_data:
        print("   content.txt laddad - huvudwebbplats är VALFRI")
        print("   (Lämna tom om företaget inte har hemsida ännu)")
    
    main_url = input("   Ange huvudwebbplatsens URL (eller Enter för att hoppa över): ").strip()
    
    if main_url and not main_url.startswith("http"):
        main_url = "https://" + main_url
    
    if not main_url and not content_data:
        print("❌ Du måste ange antingen content.txt eller en URL!")
        sys.exit(1)
    
    # Convert empty string to None
    if not main_url:
        main_url = None
    
    print()
    
    # =========================================================================
    # Extra URLs (news articles, any website, etc.)
    # =========================================================================
    print("🔗 STEG 3: Extra informationskällor")
    print("-" * 40)
    print("💡 TIPS: Lägg till valfria webbsidor för mer information:")
    print("   • Nyhetsartiklar om företaget/branschen")
    print("   • allabolag.se, proff.se, etc.")
    print("   • Branschrapporter eller konkurrenter")
    print("   • LinkedIn-profiler, sociala medier")
    print("   • Vad som helst som ger kontext!")
    print()
    
    extra_urls_with_context: List[Tuple[str, str]] = []
    
    while True:
        extra_url_choice = input("   Vill du lägga till en extra källa? (j/n): ").strip().lower()
        
        if extra_url_choice not in ["j", "ja", "y", "yes"]:
            break
        
        extra_url = input("      URL: ").strip()
        if not extra_url:
            print("      ⚠ URL saknas, hoppar över...")
            continue
        
        if not extra_url.startswith("http"):
            extra_url = "https://" + extra_url
        
        # Ask what type of information this source provides
        print("      Vad innehåller denna källa?")
        print("      (t.ex. 'nyhetsartikel', 'företagsinfo', 'branschrapport', etc.)")
        source_description = input("      Beskrivning: ").strip()
        
        if not source_description:
            source_description = "Extra informationskälla"
        
        extra_urls_with_context.append((extra_url, source_description))
        print(f"      ✓ Lagt till: {extra_url}")
        print()
    
    # =========================================================================
    # Manual info
    # =========================================================================
    manual_info = None
    print()
    print("✏️  STEG 4: Manuell information")
    print("-" * 40)
    manual_choice = input("   Vill du lägga till manuell information? (j/n): ").strip().lower()
    
    if manual_choice in ["j", "ja", "y", "yes"]:
        print("   Ange information (tryck Enter två gånger när du är klar):")
        lines = []
        while True:
            try:
                line = input()
                if line == "" and lines:  # Empty line after content = done
                    break
                if line:
                    lines.append(line)
            except EOFError:
                break
        manual_info = "\n".join(lines) if lines else None
    
    print()
    print("=" * 60)
    return main_url, extra_urls_with_context, manual_info, content_data


# =============================================================================
# MAIN FUNCTION
# =============================================================================


async def generate_site_from_url(
    url: Optional[str],
    output_dir: Optional[Path] = None,
    extra_urls_with_context: Optional[List[Tuple[str, str]]] = None,
    manual_info: Optional[str] = None,
    content_data: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Main function - audit website and generate improved version.

    Args:
        url: Website URL to audit and improve (optional if content_data provided)
        output_dir: Optional output directory for files
        extra_urls_with_context: List of (url, description) tuples for extra sources
        manual_info: Manual text information about the company
        content_data: Parsed content.txt data (Bolagsverket/PoIT format)

    Returns:
        Dict with demoUrl and metadata
    """
    if url and not url.startswith("http"):
        url = "https://" + url

    if output_dir is None:
        output_dir = Path("./generated_site")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  HEMSIDEGENERERING")
    print("=" * 60)
    if content_data:
        company_name = content_data.get("company", {}).get("company_name", "Okänt")
        print(f"  📄 content.txt: {company_name}")
    if url:
        print(f"  🌐 Huvud-URL: {url}")
    else:
        print(f"  🌐 Huvud-URL: (ingen - använder content.txt som grund)")
    if extra_urls_with_context:
        print(f"  🔗 Extra källor: {len(extra_urls_with_context)}")
        for idx, (extra_url, desc) in enumerate(extra_urls_with_context, 1):
            print(f"    {idx}. {extra_url}")
            print(f"       ({desc})")
    if manual_info:
        print(f"  ✏️  Manuell info: Ja ({len(manual_info)} tecken)")
    print(f"  📁 Output: {output_dir}")
    print("=" * 60)

    total_in_tok = 0
    total_out_tok = 0
    
    # =========================================================================
    # Step 1: Build base audit_data from content.txt OR website audit
    # =========================================================================
    if content_data:
        # Use content.txt as the PRIMARY data source
        print("\n📄 STEG 1: Använder content.txt som grund")
        print("-" * 40)
        audit_data = content_to_audit_data(content_data)
        company_name = audit_data.get("company", {}).get("name", "Okänt")
        print(f"   ✓ Företag: {company_name}")
        print(f"   ✓ Org.nr: {audit_data.get('company', {}).get('org_nr', 'Okänt')}")
        print(f"   ✓ Bildat: {audit_data.get('company', {}).get('founded', 'Okänt')}")
        
        # If URL is also provided, audit it for design/visual elements
        if url:
            print(f"\n📊 STEG 1b: Auditerar hemsida för design")
            print("-" * 40)
            website_audit, in_tok, out_tok = perform_audit(url, is_extra_source=False)
            total_in_tok += in_tok
            total_out_tok += out_tok
            
            # Merge: Keep company info from content.txt, get design from website
            print("   🔗 Kombinerar content.txt + hemsidedesign...")
            
            # Override design from website audit
            if website_audit.get("design"):
                audit_data["design"] = website_audit["design"]
            if website_audit.get("content"):
                # Keep tone/style from website but not overwrite core info
                for key in ["hero_title", "hero_subtitle", "cta_text", "tone_of_voice"]:
                    if website_audit["content"].get(key):
                        audit_data["content"][key] = website_audit["content"][key]
            # Add products/services from website if found
            if website_audit.get("products_services", {}).get("key_products"):
                audit_data["products_services"]["key_products"] = website_audit["products_services"]["key_products"]
            if website_audit.get("products_services", {}).get("categories"):
                audit_data["products_services"]["categories"] = website_audit["products_services"]["categories"]
            
            print(f"   ✓ Design och innehåll från hemsida kombinerad")
    else:
        # No content.txt - audit website as before
        print("\n📊 STEG 1: Analyserar huvudwebbplats")
        print("-" * 40)
        audit_data, in_tok, out_tok = perform_audit(url, is_extra_source=False)
        total_in_tok = in_tok
        total_out_tok = out_tok
    
    # =========================================================================
    # Step 1c: Audit extra URLs if provided
    # =========================================================================
    if extra_urls_with_context:
        base_url = url or "content.txt"
        for idx, (extra_url, source_description) in enumerate(extra_urls_with_context, 1):
            print(f"\n📊 STEG 1c.{idx}: Analyserar extra källa {idx}/{len(extra_urls_with_context)}")
            print("-" * 40)
            print(f"   URL: {extra_url}")
            print(f"   Typ: {source_description}")
            
            extra_context = f"Denna källa ({source_description}) ska komplettera information från {base_url}.\n"
            extra_context += f"Fokusera på: {source_description.lower()}\n"
            extra_context += "Extrahera information som kan hjälpa till att förstå företaget bättre - företagsstorlek, branschinfo, nyheter, målgrupp, produkter/tjänster, etc."
            
            if manual_info:
                extra_context += f"\n\nManuell information från användaren:\n{manual_info}"
            
            extra_audit_data, extra_in_tok, extra_out_tok = perform_audit(
                extra_url,
                is_extra_source=True,
                extra_context=extra_context
            )
            total_in_tok += extra_in_tok
            total_out_tok += extra_out_tok
            
            # Merge audit data (accumulate from all extra sources)
            print(f"\n🔗 Kombinerar information från källa {idx}...")
            audit_data = merge_audit_data(audit_data, extra_audit_data)
            print(f"   ✓ Information från källa {idx} kombinerad")
    
    # =========================================================================
    # Add manual info to audit data if provided
    # =========================================================================
    if manual_info:
        if "manual_info" not in audit_data:
            audit_data["manual_info"] = manual_info
        # Try to enhance company info with manual info if description is weak
        if "company" in audit_data:
            if not audit_data["company"].get("description") or len(audit_data["company"].get("description", "")) < 100:
                audit_data["company"]["description"] = manual_info[:500]
    
    if total_in_tok > 0 or total_out_tok > 0:
        print(f"\n   📊 Totalt tokens: {total_in_tok:,} in / {total_out_tok:,} out")

    # Save audit data
    audit_file = output_dir / "audit_data.json"
    audit_file.write_text(
        json.dumps(audit_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"   ✓ Sparade audit: {audit_file}")

    # Step 2: Build generation prompt
    print("\n📝 STEG 2: Bygger prompt för ny sajt")
    print("-" * 40)
    prompt = build_generation_prompt(audit_data, manual_info=manual_info)

    # Save prompt for reference
    prompt_file = output_dir / "generation_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    print(f"   ✓ Sparade prompt: {prompt_file}")
    print(f"   Promptlängd: {len(prompt):,} tecken")

    # Step 3: Generate with v0
    print("\n🚀 STEG 3: Genererar ny sajt med v0")
    print("-" * 40)
    v0_api_key = get_api_key("V0_API_KEY")

    print("   Anropar v0 Platform API...")
    result = await generate_with_v0(prompt, v0_api_key)

    # Save result
    result_file = output_dir / "generation_result.json"
    result["source_url"] = url
    result["has_content_txt"] = bool(content_data)
    if content_data:
        result["content_txt_source"] = content_data.get("source_file")
    if extra_urls_with_context:
        result["extra_urls"] = [u for u, _ in extra_urls_with_context]
        result["extra_urls_context"] = {u: desc for u, desc in extra_urls_with_context}
    result["has_manual_info"] = bool(manual_info)
    result["generated_at"] = datetime.now().isoformat()
    result["company_name"] = audit_data.get("company", {}).get("name", "Unknown")
    result_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Save demo URL separately for easy access
    if result.get("demoUrl"):
        url_file = output_dir / "preview_url.txt"
        url_file.write_text(result["demoUrl"], encoding="utf-8")

    # Summary
    print("\n" + "=" * 60)
    print("  ✅ GENERERING KLAR!")
    print("=" * 60)
    print(f"  Företag: {result.get('company_name', 'Okänt')}")
    if content_data:
        print(f"  📄 content.txt: ✓")
    if url:
        print(f"  🌐 Huvudkälla: {url}")
    else:
        print(f"  🌐 Huvudkälla: (endast content.txt)")
    if extra_urls_with_context:
        print(f"  🔗 Extra källor: {len(extra_urls_with_context)}")
        for idx, (extra_url, desc) in enumerate(extra_urls_with_context, 1):
            print(f"    {idx}. {extra_url} ({desc})")
    if manual_info:
        print(f"  ✏️  Manuell info: Ja")
    if result.get("demoUrl"):
        print(f"\n  🌐 PREVIEW URL:")
        print(f"  {result['demoUrl']}")
    print(f"\n  📁 Filer sparade i: {output_dir}")
    print("=" * 60)

    return result


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generera förbättrad hemsida från befintlig URL eller content.txt"
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Webbplats-URL att analysera och förbättra (valfri om --content anges)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./generated_site",
        help="Output-mapp (default: ./generated_site)",
    )
    parser.add_argument(
        "--content",
        "-c",
        help="Sökväg till content.txt (Bolagsverket/PoIT-format) som primär datakälla",
    )
    parser.add_argument(
        "--extra-url",
        action="append",
        help="Extra URL för information (nyhetsartiklar, allabolag, etc.) - kan anges flera gånger",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Hoppa över interaktiv prompt (använd endast CLI-argument)",
    )

    args = parser.parse_args()

    # Interactive mode if no URL and no content provided, and not --no-interactive
    if not args.url and not args.content and not args.no_interactive:
        main_url, extra_urls_with_context, manual_info, content_data = get_user_input()
    else:
        # CLI mode
        content_data = None
        
        # Load content.txt if specified
        if args.content:
            content_path = Path(args.content)
            if content_path.exists():
                content_data = parse_content_txt(content_path)
                if content_data:
                    print(f"✓ Laddade content.txt: {content_path}")
            else:
                print(f"❌ content.txt finns inte: {content_path}")
                return 1
        
        # URL is required if no content.txt
        if not args.url and not content_data:
            print("❌ Du måste ange antingen URL eller --content!")
            print("   Kör utan argument för interaktiv mode.")
            return 1
        
        main_url = args.url  # Can be None if content_data is provided
        
        # Convert CLI extra URLs to list of tuples (url, description)
        if args.extra_url:
            extra_urls_with_context = [(url, "Extra informationskälla") for url in args.extra_url]
        else:
            extra_urls_with_context = None
        manual_info = None

    result = asyncio.run(
        generate_site_from_url(
            main_url,
            Path(args.output),
            extra_urls_with_context=extra_urls_with_context,
            manual_info=manual_info,
            content_data=content_data,
        )
    )

    if result.get("demoUrl"):
        print(f"\n✨ Öppna i webbläsare: {result['demoUrl']}")
        return 0
    else:
        print("\n❌ Kunde inte generera preview URL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
