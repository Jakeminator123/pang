"""
Core generator logic for creating preview pages using v0 Platform API.
Generates React components for companies using v0 Platform API.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import html
import httpx
import asyncio

# Import v0 client and cost tracker
try:
    from .v0_client import V0Client, DEFAULT_MODEL
    from .cost_tracker import estimate_v0_cost, create_cost_entry
except ImportError:
    from v0_client import V0Client, DEFAULT_MODEL
    from cost_tracker import estimate_v0_cost, create_cost_entry

# Price for preview site (SEK)
PRICE_SEK = 12_000

# API keys (read from environment only - never ship defaults)
DEFAULT_V0_API_KEY = os.getenv("V0_API_KEY")
DEFAULT_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
DEFAULT_UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")


# Helper to get industry keywords from verksamhet
def detect_industry_keywords(verksamhet: str) -> List[str]:
    """Detect industry keywords for image search."""
    verksamhet_lower = verksamhet.lower()
    keywords = []

    if any(
        word in verksamhet_lower
        for word in ["kakel", "keramik", "bad", "inredning", "renovering"]
    ):
        keywords.extend(["tiles", "bathroom", "interior design", "home renovation"])
    elif any(
        word in verksamhet_lower
        for word in ["estetik", "botox", "filler", "injektion", "behandling"]
    ):
        keywords.extend(["beauty", "spa", "wellness", "professional"])
    elif any(
        word in verksamhet_lower
        for word in ["projektledning", "konsult", "produktionsteknik", "kvalitet"]
    ):
        keywords.extend(["business", "consulting", "professional", "office"])
    elif any(
        word in verksamhet_lower for word in ["e-handel", "handel", "handla", "butik"]
    ):
        keywords.extend(["ecommerce", "shopping", "retail", "products"])
    else:
        keywords.append("business")

    return keywords[:3]  # Return top 3


async def search_images_unsplash(
    query: str, api_key: Optional[str] = None, count: int = 3
) -> List[Dict[str, str]]:
    """Search for images on Unsplash."""
    if not api_key:
        return []

    try:
        url = f"https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {api_key}", "Accept-Version": "v1"}
        params = {"query": query, "per_page": count, "orientation": "landscape"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                images = []
                for photo in data.get("results", [])[:count]:
                    images.append(
                        {
                            "url": photo["urls"]["regular"],
                            "alt": photo.get("alt_description")
                            or photo.get("description")
                            or query,
                            "photographer": photo["user"]["name"],
                        }
                    )
                return images
    except Exception as e:
        print(f"Warning: Unsplash search failed: {e}")

    return []


async def search_images_pexels(
    query: str, api_key: Optional[str] = None, count: int = 3
) -> List[Dict[str, str]]:
    """Search for images on Pexels."""
    if not api_key:
        return []

    try:
        url = f"https://api.pexels.com/v1/search"
        headers = {"Authorization": api_key}
        params = {"query": query, "per_page": count, "orientation": "landscape"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                images = []
                for photo in data.get("photos", [])[:count]:
                    images.append(
                        {
                            "url": photo["src"]["large"],
                            "alt": photo.get("alt") or query,
                            "photographer": photo["photographer"],
                        }
                    )
                return images
    except Exception as e:
        print(f"Warning: Pexels search failed: {e}")

    return []


async def enhance_prompt_with_openai(
    base_prompt: str, company_data: Dict[str, Any], api_key: Optional[str] = None
) -> str:
    """Use OpenAI to enhance the prompt with better context and suggestions."""
    if not api_key:
        return base_prompt

    try:
        # Build context for OpenAI
        context = f"""Företag: {company_data['company_name']}
Verksamhet: {company_data['verksamhet']}
Ort: {company_data['city']}
Bransch: {company_data.get('verksamhet', '')[:200]}

Baserat på denna information, förbättra och utöka följande prompt för att skapa en mer professionell och branschspecifik React-landningssida. 
Fokusera på värdeerbjudande, målgrupp och branschtrender."""

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "Du är en expert på webbdesign och marknadsföring. Din uppgift är att förbättra prompts för att skapa bättre webbplatser.",
                },
                {
                    "role": "user",
                    "content": f"{context}\n\nNuvarande prompt:\n{base_prompt}\n\nFörbättra denna prompt med mer specifika detaljer, bättre värdeerbjudande och branschspecifika element. Svara ENDAST med den förbättrade prompten, inget annat.",
                },
            ],
            "temperature": 0.7,
            "max_tokens": 1500,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                result = response.json()
                enhanced = result["choices"][0]["message"]["content"].strip()
                return enhanced
    except Exception as e:
        print(f"Warning: OpenAI enhancement failed: {e}")

    return base_prompt


def safe_read_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """Safely read and parse JSON file."""
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not parse JSON {file_path}: {e}")
        return None


def safe_read_text(file_path: Path) -> str:
    """Safely read text file."""
    if not file_path.exists():
        return ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def escape_html(value: str) -> str:
    """Escape HTML special characters."""
    return html.escape(value)


def format_sek(amount: int) -> str:
    """Format SEK amount with Swedish locale."""
    return f"{amount:,} SEK".replace(",", " ")


def pick(values: List[Optional[str]], fallback: str) -> str:
    """Pick first non-null value from list."""
    for value in values:
        if value is not None and value != "":
            return value
    return fallback


def extract_company_data(folder_path: Path) -> Dict[str, Any]:
    """Extract and normalize company data from folder."""
    company_data = safe_read_json(folder_path / "company_data.json") or {}
    poit_data = safe_read_json(folder_path / "data.json") or {}
    mail_text = safe_read_text(folder_path / "mail.txt")

    # Check if company_data.json is missing or empty
    company_data_file = folder_path / "company_data.json"
    if not company_data_file.exists():
        print(f"  ⚠️  company_data.json saknas i {folder_path.name}")
        print("     → Hemsidan får placeholders för alla fält")
    elif not company_data:
        print(f"  ⚠️  company_data.json är tom i {folder_path.name}")
        print("     → Hemsidan får placeholders för alla fält")

    # Extract with fallbacks
    company_name = pick([company_data.get("company_name"), "Företag"], "Företag")
    orgnr = pick([company_data.get("orgnr")], "")
    verksamhet = pick(
        [company_data.get("verksamhet")], "Verksamhetsbeskrivning saknas."
    )
    city = pick([company_data.get("sate")], "")
    address = pick([company_data.get("address")], "")

    emails = company_data.get("emails", [])
    email = pick([emails[0] if emails else None], "kontakt@example.se")

    phones = company_data.get("phones", [])
    phone = pick([phones[0] if phones else None], "")

    # Warn if using placeholders for critical fields
    if company_name == "Företag":
        print(f"  ⚠️  Företagsnamn saknas - använder placeholder 'Företag'")
    if verksamhet == "Verksamhetsbeskrivning saknas.":
        print(f"  ⚠️  Verksamhetsbeskrivning saknas - hemsidan får väldigt generiskt innehåll!")

    # Extract domain options
    domain_options = []
    if company_data.get("domain"):
        domain = company_data["domain"]
        alternatives = domain.get("alternatives", [])
        domain_options = [
            alt.get("domain") for alt in alternatives if alt.get("domain")
        ]
        if domain.get("guess") and domain.get("guess") not in domain_options:
            domain_options.insert(0, domain.get("guess"))

    # Extract people
    people = []
    for person in company_data.get("people", []):
        people.append(
            {"name": person.get("name", "Team"), "role": person.get("role", "Kontakt")}
        )

    # Extract mail snippet
    mail_lines = mail_text.split("\n")
    mail_snippet = " ".join(mail_lines[7:15]).strip() if len(mail_lines) > 7 else ""

    return {
        "company_name": company_name,
        "orgnr": orgnr,
        "verksamhet": verksamhet,
        "city": city,
        "address": address,
        "email": email,
        "phone": phone,
        "domain_options": domain_options,
        "people": people,
        "poit_url": poit_data.get("url", "https://poit.bolagsverket.se/"),
        "poit_title": poit_data.get("title", "Bolagsverkets registrering"),
        "mail_snippet": mail_snippet,
    }


def generate_subtitle(verksamhet: str, industry_hints: Dict[str, str] = None) -> str:
    """Generate industry-appropriate subtitle."""
    if industry_hints is None:
        industry_hints = {}

    verksamhet_lower = verksamhet.lower()

    # Industry detection
    if any(
        word in verksamhet_lower for word in ["kakel", "keramik", "bad", "inredning"]
    ):
        return "Inspirerande kakel, klinker och badrumsinredning online med trygg leverans och personlig rådgivning."
    elif any(
        word in verksamhet_lower for word in ["estetik", "botox", "filler", "injektion"]
    ):
        return (
            "Professionella estetiska behandlingar med säkerhet och kvalitet i fokus."
        )
    elif any(
        word in verksamhet_lower
        for word in ["projektledning", "konsult", "produktionsteknik"]
    ):
        return "Expertkonsultation inom projektledning, produktionsteknik och kvalitet."
    elif any(word in verksamhet_lower for word in ["e-handel", "handel", "handla"]):
        return "Modern e-handel med fokus på kundnöjdhet och snabb leverans."
    else:
        return "Professionella tjänster anpassade efter dina behov."


async def build_v0_prompt(
    data: Dict[str, Any],
    use_openai: bool = True,
    use_images: bool = True,
    openai_key: Optional[str] = None,
    unsplash_key: Optional[str] = None,
    pexels_key: Optional[str] = None,
) -> str:
    """Build a comprehensive prompt for v0 API based on company data."""
    company_name = data["company_name"]
    verksamhet = data["verksamhet"]
    city = data["city"]
    address = data["address"]
    email = data["email"]
    phone = data["phone"]
    domain_options = data["domain_options"]
    people = data["people"]

    # Build people list text
    people_text = ""
    if people:
        people_text = "\n\nTeam:\n"
        for person in people:
            people_text += f"- {person['name']} ({person['role']})\n"

    # Build domain text
    domain_text = ", ".join(domain_options) if domain_options else "Ej angivet"

    # Base prompt
    base_prompt = f"""Skapa en professionell, modern React-landningssida för {company_name}.

FÖRETAGSINFORMATION:
- Företagsnamn: {company_name}
- Verksamhet: {verksamhet}
- Ort: {city}
- Adress: {address}
- E-post: {email}
- Telefon: {phone}
- Domän: {domain_text}{people_text}

DESIGNKRAV:
- Modern, professionell design med mörkt tema och accentfärger (teal/cyan eller branschpassande)
- Hero-sektion med företagsnamn och värdeerbjudande
- Sektioner för: Vad vi erbjuder, Vårt team, Kontaktinformation
- Responsiv design (mobile-first)
- Smooth scroll och Intersection Observer animations
- Tailwind CSS för all styling
- Lucide React för ikoner

TEKNISKA KRAV:
- React 18+ med TypeScript
- Next.js App Router struktur
- Tailwind CSS (ingen extern CSS)
- Semantic HTML (nav, main, section, article)
- Accessible (ARIA labels, keyboard navigation)
- SEO-friendly struktur

INNEHÅLL:
- Hero med kraftfull rubrik och värdeerbjudande baserat på verksamheten
- Beskrivning av tjänster/produkter
- Team-sektion med personerna ovan
- Kontaktformulär eller tydlig CTA för kontakt
- Footer med kontaktuppgifter

Anpassa designen efter branschen ({verksamhet[:100]})."""

    # Enhance with OpenAI if enabled
    if use_openai and openai_key:
        print("  🤖 Förbättrar prompt med OpenAI...")
        base_prompt = await enhance_prompt_with_openai(base_prompt, data, openai_key)
        print("  ✅ Prompt förbättrad med OpenAI")
    elif use_openai and not openai_key:
        print("  ⚠️  OPENAI_API_KEY saknas - prompt förbättras INTE!")
        print("     → Lägg till OPENAI_API_KEY i .env-filen")

    # Add images if enabled
    image_section = ""
    if use_images:
        keywords = detect_industry_keywords(verksamhet)
        images = []

        # Try Unsplash first, then Pexels
        if unsplash_key:
            print(f"  🖼️  Söker bilder på Unsplash (nyckelord: {', '.join(keywords)})...")
            for keyword in keywords:
                found = await search_images_unsplash(keyword, unsplash_key, 1)
                images.extend(found)
                if len(images) >= 3:
                    break

        if len(images) < 3 and pexels_key:
            print(f"  🖼️  Söker bilder på Pexels (nyckelord: {', '.join(keywords)})...")
            for keyword in keywords:
                found = await search_images_pexels(keyword, pexels_key, 1)
                images.extend(found)
                if len(images) >= 3:
                    break

        if images:
            image_section = "\n\nBILDER ATT ANVÄNDA:\n"
            for i, img in enumerate(images[:3], 1):
                image_section += f"{i}. {img['url']} (Alt: {img['alt']})\n"
            image_section += "\nAnvänd dessa bilder i hero-sektionen och relevanta sektioner. Sätt lämplig alt-text."
            print(f"  ✅ Hittade {len(images)} bilder")
        elif not unsplash_key and not pexels_key:
            print("  ⚠️  UNSPLASH_ACCESS_KEY och PEXELS_API_KEY saknas - INGA bilder!")
            print("     → Lägg till nycklarna i .env-filen")
        else:
            print("  ⚠️  Hittade inga bilder (bildtjänster svarade inte)")

    return base_prompt + image_section


async def generate_with_v0(
    prompt: str, api_key: Optional[str] = None, model: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    """
    Generate React component using v0 Platform API.

    Args:
        prompt: User prompt for the component
        api_key: v0 API key (optional, uses env var or default)
        model: Model to use (default: v0-1.5-md)

    Returns:
        Dict with chatId, demoUrl, versionId, status, files, etc.
    """
    client = V0Client(api_key)
    return await client.create_chat(prompt, model=model)


def build_html(data: Dict[str, Any]) -> str:
    """Build complete HTML preview page."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Escape all user input
    safe_company = escape_html(data["company_name"])
    safe_verksamhet = escape_html(data["verksamhet"])
    safe_address = escape_html(data["address"])
    safe_city = escape_html(data["city"])
    safe_email = escape_html(data["email"])
    safe_phone = escape_html(data["phone"])
    safe_poit = escape_html(data["poit_url"])
    safe_poit_title = escape_html(data["poit_title"])
    safe_mail_snippet = escape_html(data["mail_snippet"])

    domain_text = (
        " • ".join([escape_html(d) for d in data["domain_options"]])
        if data["domain_options"]
        else "Ej angivet"
    )

    # Build people list
    people_html = ""
    if data["people"]:
        people_html = "".join(
            [
                f'<div class="pill"><strong>{escape_html(p["name"])}</strong><span>{escape_html(p["role"])}</span></div>'
                for p in data["people"]
            ]
        )
    else:
        people_html = '<div class="pill"><strong>Team</strong><span>Presenteras senare</span></div>'

    subtitle = generate_subtitle(data["verksamhet"])

    # Build fact rows
    fact_rows = []
    if data["orgnr"]:
        fact_rows.append(
            f'<div class="fact-row"><div class="label">Org nr</div><div class="value">{escape_html(data["orgnr"])}</div></div>'
        )
    if data["address"]:
        fact_rows.append(
            f'<div class="fact-row"><div class="label">Adress</div><div class="value">{safe_address}</div></div>'
        )
    if data["email"]:
        fact_rows.append(
            f'<div class="fact-row"><div class="label">E-post</div><div class="value">{safe_email}</div></div>'
        )
    if data["phone"]:
        fact_rows.append(
            f'<div class="fact-row"><div class="label">Telefon</div><div class="value">{safe_phone}</div></div>'
        )
    fact_rows.append(
        f'<div class="fact-row"><div class="label">Domän</div><div class="value">{domain_text}</div></div>'
    )

    phone_clean = data["phone"].replace(" ", "").replace("-", "")

    return f"""<!doctype html>
<html lang="sv">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{safe_company} — Preview</title>
  <style>
    :root {{
      --bg: #0f1117;
      --card: #171b23;
      --muted: #9fb2d0;
      --accent: #c5ff7a;
      --accent-2: #7ad2ff;
      --text: #e9eef8;
      --border: rgba(255,255,255,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Inter", system-ui, -apple-system, sans-serif;
      background: radial-gradient(900px at 20% 20%, rgba(197,255,122,0.06), transparent),
                  radial-gradient(900px at 80% 0%, rgba(122,210,255,0.08), transparent),
                  var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 32px 16px 48px;
    }}
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .hero {{
      padding: 28px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: linear-gradient(145deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
      box-shadow: 0 12px 60px rgba(0,0,0,0.35);
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 13px;
      background: rgba(255,255,255,0.03);
    }}
    h1 {{
      margin: 12px 0 4px;
      font-size: clamp(26px, 3vw, 34px);
      letter-spacing: -0.02em;
    }}
    .subtitle {{
      color: var(--muted);
      margin: 0 0 16px;
      font-size: 16px;
    }}
    .cta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 12px 16px;
      border-radius: 12px;
      text-decoration: none;
      font-weight: 600;
      border: 1px solid transparent;
      color: #0a0c10;
    }}
    .button.primary {{ background: var(--accent); }}
    .button.secondary {{
      background: rgba(255,255,255,0.06);
      color: var(--text);
      border-color: var(--border);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .card {{
      padding: 20px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: var(--card);
    }}
    .card h3 {{
      margin: 0 0 8px;
      font-size: 18px;
    }}
    .card p {{ margin: 0 0 10px; color: var(--muted); }}
    ul {{ padding-left: 18px; margin: 6px 0 0; color: var(--text); }}
    li {{ margin-bottom: 6px; }}
    .pill {{
      display: inline-flex;
      gap: 6px;
      padding: 8px 10px;
      margin: 6px 6px 0 0;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--text);
      font-size: 13px;
    }}
    .pill span {{ color: var(--muted); }}
    .fact-row {{
      display: grid;
      grid-template-columns: 130px 1fr;
      gap: 8px;
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
    }}
    .fact-row:last-child {{ border-bottom: none; }}
    .label {{ color: var(--muted); font-size: 14px; }}
    .value {{ color: var(--text); font-weight: 600; }}
    .cost {{
      border: 1px solid var(--border);
      background: linear-gradient(120deg, rgba(197,255,122,0.08), rgba(122,210,255,0.06));
      border-radius: 14px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .cost strong {{ font-size: 22px; }}
    .foot {{
      text-align: center;
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    @media (max-width: 640px) {{
      .fact-row {{ grid-template-columns: 1fr; }}
      .hero {{ padding: 22px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="chip">Preview-läge • {today}</div>
      <h1>{safe_company}</h1>
      <p class="subtitle">{subtitle}</p>
      <div class="cta-row">
        <a class="button primary" href="mailto:{safe_email}">Kontakta oss</a>
        {"<a class=\"button secondary\" href=\"tel:" + phone_clean + "\">Ring " + safe_phone + "</a>" if data["phone"] else ""}
      </div>
    </section>

    <section class="grid">
      <article class="card">
        <h3>Vad vi erbjuder</h3>
        <p>{safe_verksamhet}</p>
        <ul>
          <li>Professionella tjänster anpassade efter dina behov.</li>
          <li>Personlig rådgivning och stöd.</li>
          <li>Tydlig kommunikation och transparenta priser.</li>
          <li>Kvalitet och kundnöjdhet i fokus.</li>
        </ul>
      </article>

      <article class="card">
        <h3>Vårt erbjudande</h3>
        <ul>
          <li>Skräddarsydda lösningar för din verksamhet.</li>
          <li>Erfarenhet och kompetens inom branschen.</li>
          <li>Flexibla avtal och anpassningsbara tjänster.</li>
          <li>Långsiktigt partnerskap.</li>
        </ul>
      </article>

      <article class="card">
        <h3>Team & förtroende</h3>
        {people_html}
        <div class="pill"><strong>Ort</strong><span>{safe_city if safe_city else "Säte saknas"}</span></div>
      </article>
    </section>

    <section class="grid">
      <article class="card">
        <h3>Snabbfakta</h3>
        {"".join(fact_rows)}
      </article>

      <article class="card">
        <h3>Kostnad (demo)</h3>
        <div class="cost">
          <div>Fast pris för denna framtagna preview</div>
          <strong>{format_sek(PRICE_SEK)}</strong>
          <div class="label">Inkluderar design, copy och statisk leverans.</div>
        </div>
      </article>
    </section>

    <section class="card">
      <h3>Bakgrund och källa</h3>
      <p>Denna sida är genererad automatiskt som underlag för {safe_company}.</p>
      <p><strong>Källa:</strong> <a href="{safe_poit}" style="color: var(--accent-2); text-decoration: none;">{safe_poit_title}</a></p>
      {"<p><strong>Mailutkast:</strong> <span style=\"color: var(--muted);\">" + safe_mail_snippet + "</span></p>" if safe_mail_snippet else ""}
    </section>

    <p class="foot">Preview skapad automatiskt — uppdatera innehållet efter behov.</p>
  </main>
</body>
</html>"""


def generate_preview(
    folder_name: str, base_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Generate preview HTML for a company folder.

    Args:
        folder_name: Name of the company folder (e.g., "K928253-25")
        base_dir: Base directory containing company folders (defaults to parent of generator/)

    Returns:
        Dict with 'html', 'cost', and 'company_name'
    """
    if base_dir is None:
        # Default fallback: assume company folders are in 2_segment_info/djupanalys/20251208
        base_dir = Path(__file__).parent.parent.parent / "2_segment_info" / "djupanalys" / "20251208"

    folder_path = base_dir / folder_name

    if not folder_path.exists():
        raise FileNotFoundError(f"Company folder not found: {folder_path}")

    data = extract_company_data(folder_path)
    html_content = build_html(data)

    cost_info = {
        "amount_sek": PRICE_SEK,
        "formatted": format_sek(PRICE_SEK),
        "company_name": data["company_name"],
        "orgnr": data["orgnr"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return {
        "html": html_content,
        "cost": cost_info,
        "company_name": data["company_name"],
        "folder_name": folder_name,
    }


async def generate_preview_v0(
    folder_name: str,
    base_dir: Optional[Path] = None,
    v0_api_key: Optional[str] = None,
    openai_key: Optional[str] = None,
    unsplash_key: Optional[str] = None,
    pexels_key: Optional[str] = None,
    use_openai_enhancement: bool = True,
    use_images: bool = True,
) -> Dict[str, Any]:
    """
    Generate preview React page using v0 API for a company folder.

    Args:
        folder_name: Name of the company folder (e.g., "K928253-25")
        base_dir: Base directory containing company folders
        v0_api_key: v0 API key (defaults to V0_API_KEY env var)

    Returns:
        Dict with 'demoUrl', 'chatId', 'cost', and 'company_name'
    """
    # Ensure base_dir is a Path object
    if base_dir is None:
        # Default fallback: assume company folders are in 2_segment_info/djupanalys/20251208
        base_dir = Path(__file__).parent.parent.parent / "2_segment_info" / "djupanalys" / "20251208"
    elif not isinstance(base_dir, Path):
        base_dir = Path(base_dir)
    
    folder_path = base_dir / folder_name

    if not folder_path.exists():
        raise FileNotFoundError(
            f"Company folder not found: {folder_path}\n"
            f"  base_dir: {base_dir}\n"
            f"  folder_name: {folder_name}\n"
            f"  Expected path: {folder_path}\n"
            f"  base_dir exists: {base_dir.exists()}\n"
            f"  base_dir contents: {list(base_dir.iterdir()) if base_dir.exists() else 'N/A'}"
        )

    # Extract company data
    data = extract_company_data(folder_path)

    # Get API keys with fallbacks: parameter > env var > hardcoded default
    v0_key = v0_api_key or os.getenv("V0_API_KEY") or DEFAULT_V0_API_KEY
    if not v0_key:
        raise ValueError("V0_API_KEY is required")

    openai_key_final = (
        openai_key or os.getenv("OPENAI_API_KEY") or DEFAULT_OPENAI_API_KEY
    )
    unsplash_key_final = (
        unsplash_key or os.getenv("UNSPLASH_ACCESS_KEY") or DEFAULT_UNSPLASH_ACCESS_KEY
    )
    pexels_key_final = (
        pexels_key or os.getenv("PEXELS_API_KEY") or DEFAULT_PEXELS_API_KEY
    )

    # Build enhanced v0 prompt
    prompt = await build_v0_prompt(
        data,
        use_openai=use_openai_enhancement,
        use_images=use_images,
        openai_key=openai_key_final,
        unsplash_key=unsplash_key_final,
        pexels_key=pexels_key_final,
    )

    # Estimate cost before generation
    estimated_cost = estimate_v0_cost(prompt, DEFAULT_MODEL)

    # Generate with v0 Platform API
    v0_result = await generate_with_v0(prompt, v0_key, DEFAULT_MODEL)

    # Build cost info
    cost_info = {
        "amount_sek": PRICE_SEK,
        "formatted": format_sek(PRICE_SEK),
        "estimated": estimated_cost,
        "company_name": data["company_name"],
        "orgnr": data["orgnr"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return {
        "demoUrl": v0_result["demoUrl"],
        "chatId": v0_result["chatId"],
        "versionId": v0_result.get("versionId"),
        "status": v0_result.get("status"),
        "model": v0_result.get("model"),
        "cost": cost_info,
        "company_name": data["company_name"],
        "folder_name": folder_name,
    }
