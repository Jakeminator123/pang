#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2_research.py - Step 2: AI-powered research and domain discovery

Features:
- Web search to find company information and contacts
- Web search to find domain candidates
- Crawl/verify domain candidates to check if they belong to the company
- Detect parked domains

Respects TARGET_DATE environment variable if set.
"""

import json

# logging not used currently
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Load .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv

    if (PROJECT_ROOT / ".env").exists():
        load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import requests
    import urllib3
    from bs4 import BeautifulSoup

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None
    BeautifulSoup = None

# =============================================================================
# CONFIGURATION
# =============================================================================


def load_config(config_path: Path) -> Dict[str, str]:
    """Load config file."""
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
# WEB SEARCH
# =============================================================================


def extract_text_from_response(response) -> str:
    """Extract text from OpenAI response."""
    try:
        return response.output_text.strip()
    except Exception:
        out = getattr(response, "output", []) or []
        pieces = []
        for item in out:
            content = getattr(item, "content", []) or []
            for block in content:
                text = (
                    block.get("text")
                    if isinstance(block, dict)
                    else getattr(block, "text", None)
                )
                if text:
                    pieces.append(text)
        return "\n".join(pieces).strip()


def collect_citations(response) -> List[Dict[str, str]]:
    """Extract URL citations from response."""
    citations = []
    out = getattr(response, "output", []) or []
    for item in out:
        content = getattr(item, "content", []) or []
        for block in content:
            annotations = (
                block.get("annotations")
                if isinstance(block, dict)
                else getattr(block, "annotations", None)
            )
            if not annotations:
                continue
            for ann in annotations:
                a_type = (
                    ann.get("type")
                    if isinstance(ann, dict)
                    else getattr(ann, "type", None)
                )
                if a_type == "url_citation":
                    url = (
                        ann.get("url")
                        if isinstance(ann, dict)
                        else getattr(ann, "url", "")
                    )
                    title = (
                        ann.get("title")
                        if isinstance(ann, dict)
                        else getattr(ann, "title", "")
                    )
                    if url:
                        citations.append({"url": url, "title": title or url})
    # Dedupe
    seen = set()
    unique = []
    for c in citations:
        if c["url"] not in seen:
            unique.append(c)
            seen.add(c["url"])
    return unique


def web_search(client: OpenAI, query: str, model: str) -> Tuple[str, List[Dict]]:
    """Run web search and return (text, citations)."""
    tools_variants = [
        [{"type": "web_search"}],
        [{"type": "web_search_preview"}],
    ]

    for tools in tools_variants:
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"{query}\n\nSvara kort och inkludera källhänvisningar.",
                            }
                        ],
                    }
                ],
                tools=tools,
            )
            text = extract_text_from_response(response)
            citations = collect_citations(response)
            return text, citations
        except Exception:
            continue

    return "", []


def extract_domains_from_text(text: str, company_name: str) -> List[Tuple[str, float]]:
    """Extract domains from text with confidence scores."""
    if not text:
        return []

    domains = []
    seen = set()

    # Company keywords for matching
    company_lower = company_name.lower()
    company_words = [
        w
        for w in re.sub(
            r"\b(ab|aktiebolag|hb|kb)\b", "", company_lower, flags=re.I
        ).split()
        if len(w) >= 3
    ]

    # Domain patterns
    patterns = [
        r"https?://(?:www\.)?([a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]?\.(?:se|com|nu|org|net|io))",
        r"(?:^|\s)([a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]?\.(?:se|com|nu|org|net|io))(?:\s|$|/|,)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            domain = match.group(1).lower().replace("www.", "")

            # Skip blocked domains
            if (
                domain in seen
                or domain in BLOCKED_DOMAINS
                or any(b in domain for b in BLOCKED_DOMAINS)
            ):
                continue

            # Calculate confidence
            domain_name = domain.split(".")[0]
            name_matches = any(
                kw in domain_name or domain_name in kw for kw in company_words
            )

            # Check context
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 100)
            context = text[start:end].lower()
            context_mentions = any(w in context for w in company_words[:2])

            if name_matches and context_mentions:
                confidence = 0.85
            elif name_matches:
                confidence = 0.65
            elif context_mentions:
                confidence = 0.40
            else:
                confidence = 0.20

            domains.append((domain, confidence))
            seen.add(domain)

    return sorted(domains, key=lambda x: -x[1])


# =============================================================================
# DOMAIN CRAWLING
# =============================================================================

# Domains to always skip (info sites, never a company's own site)
BLOCKED_DOMAINS = {
    # Email providers
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    # Social media
    "google.com",
    "facebook.com",
    "linkedin.com",
    "twitter.com",
    "instagram.com",
    # Swedish business info sites
    "ratsit.se",
    "kreditrapporten.se",
    "syna.se",
    "upplysningar.syna.se",
    "allabolag.se",
    "hitta.se",
    "eniro.se",
    "merinfo.se",
    "foretagsfakta.se",
    "bolagsfakta.se",
    "proff.se",
    "solidinfo.se",
    "uc.se",
    "bisnode.se",
    "bolagsverket.se",
    "infotorg.se",
    "creditsafe.se",
    "dun.se",
    # Other generic
    "wikipedia.org",
    "youtube.com",
    "apple.com",
    "microsoft.com",
}

PARKING_INDICATORS = [
    "domain parking",
    "parked domain",
    "this domain",
    "domain for sale",
    "buy this domain",
    "parkering",
    "domänparkering",
    "sedo",
    "godaddy",
    "namecheap",
    "domän till salu",
    "köp denna domän",
    "hugedomains",
    "svenskadomaner",
    "svenskadomäner",
    "dan.com",
    "afternic",
]


def crawl_domain(
    domain: str, company_name: str, timeout: int = 8
) -> Optional[Dict[str, Any]]:
    """Crawl domain and analyze if it belongs to company."""
    if not REQUESTS_AVAILABLE:
        return None

    domain_clean = (
        domain.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
    )
    url = f"https://{domain_clean}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
    }

    try:
        resp = requests.get(
            url, headers=headers, timeout=timeout, allow_redirects=True, verify=False
        )

        if resp.status_code != 200:
            return {"domain": domain, "status": "error", "http_code": resp.status_code}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts/styles
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else ""

        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc.get("content", "") if meta_desc else ""

        headings = [
            h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])[:10]
        ]

        text = soup.get_text(" ", strip=True)
        words = text.split()[:1500]
        text = " ".join(words)

        # Check for parking
        content_lower = (
            title_text + " " + description + " " + " ".join(headings) + " " + text
        ).lower()
        is_parked = any(ind in content_lower for ind in PARKING_INDICATORS)

        # Check company match
        company_lower = company_name.lower()
        company_words = [
            w
            for w in re.sub(
                r"\b(ab|aktiebolag)\b", "", company_lower, flags=re.I
            ).split()
            if len(w) >= 3
        ]

        company_mentioned = company_lower in content_lower
        words_found = sum(1 for w in company_words if w in content_lower)
        match_ratio = words_found / len(company_words) if company_words else 0

        is_match = not is_parked and (company_mentioned or match_ratio >= 0.5)

        return {
            "domain": domain,
            "url": str(resp.url),
            "status": "parked" if is_parked else ("match" if is_match else "no_match"),
            "is_parked": is_parked,
            "is_match": is_match,
            "match_ratio": round(match_ratio, 2),
            "title": title_text[:100],
            "description": description[:200],
            "text_sample": text[:500],
        }

    except requests.exceptions.Timeout:
        return {"domain": domain, "status": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"domain": domain, "status": "connection_error"}
    except Exception as e:
        return {"domain": domain, "status": "error", "error": str(e)[:100]}


# =============================================================================
# AI DOMAIN VERIFICATION
# =============================================================================


def verify_domain_with_ai(
    client: OpenAI,
    model: str,
    company_data: Dict,
    crawl_result: Dict,
) -> Dict[str, Any]:
    """Use AI to verify if a crawled domain actually belongs to the company."""
    if not crawl_result.get("text_sample"):
        return {"verified": False, "reason": "No content to analyze"}

    company_name = company_data.get("company_name", "")
    orgnr = company_data.get("orgnr", "")
    verksamhet = company_data.get("verksamhet", "")
    sate = company_data.get("sate", "")

    domain = crawl_result.get("domain", "")
    site_title = crawl_result.get("title", "")
    site_desc = crawl_result.get("description", "")
    site_text = crawl_result.get("text_sample", "")[:800]

    prompt = f"""Analysera om denna hemsida tillhör detta specifika företag.

FÖRETAG ATT VERIFIERA:
- Namn: {company_name}
- Org.nr: {orgnr}
- Verksamhet: {verksamhet}
- Stad: {sate}

HEMSIDA ({domain}):
- Titel: {site_title}
- Beskrivning: {site_desc}
- Innehåll: {site_text}

VIKTIGT: 
- Om hemsidan tillhör ETT ANNAT företag med liknande namn, svara NEJ
- Kolla verksamhet, stad, och om det verkar vara samma organisation
- PR-byråer, mediebolag, etc som råkar ha liknande namn är INTE samma företag

Svara ENDAST med JSON:
{{"verified": true/false, "confidence": 0.0-1.0, "reason": "kort förklaring"}}"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1,
        )
        result_text = response.choices[0].message.content.strip()

        # Parse JSON response
        import json as json_module

        # Clean up response
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        result = json_module.loads(result_text)
        return result

    except Exception as e:
        return {"verified": False, "reason": f"AI verification failed: {str(e)[:50]}"}


# =============================================================================
# MAIN RESEARCH LOGIC
# =============================================================================


def research_company(
    client: OpenAI,
    model: str,
    company_data: Dict,
    cfg: Dict,
) -> Dict[str, Any]:
    """Run AI research for a company."""
    company_name = company_data.get("company_name", "")
    verksamhet = company_data.get("verksamhet", "")
    people = company_data.get("people", [])
    current_domain = company_data.get("domain", {}).get("guess", "")

    research = {
        "company": company_name,
        "searches": [],
        "domain_candidates": [],
        "crawl_results": [],
        "best_domain": None,
        "best_confidence": 0.0,
        "researched_at": datetime.now().isoformat(),
    }

    if not company_name:
        return research

    max_searches = int(cfg.get("RESEARCH_MAX_SEARCHES", "4"))
    search_persons = cfg.get("RESEARCH_SEARCH_PERSONS", "y").lower() in (
        "y",
        "yes",
        "true",
        "1",
    )
    max_persons = int(cfg.get("RESEARCH_MAX_PERSONS", "2"))
    max_crawl = int(cfg.get("DOMAIN_MAX_CRAWL", "3"))

    # Build search queries
    queries = []

    # Company + domain searches
    queries.append(f"{company_name} hemsida website")
    if verksamhet:
        queries.append(f"{company_name} {verksamhet[:50]} kontakt")
    queries.append(f'"{company_name}" site:se')

    # Person searches
    if search_persons and people:
        for person in people[:max_persons]:
            name = person.get("name", "")
            if name:
                queries.append(f"{name} {company_name} kontakt email")

    # Run searches
    all_domains = []

    for query in queries[:max_searches]:
        text, citations = web_search(client, query, model)

        search_result = {
            "query": query,
            "summary": text[:500] if text else "",
            "sources": citations[:5],
        }
        research["searches"].append(search_result)

        # Extract domains from results
        if text:
            found = extract_domains_from_text(text, company_name)
            all_domains.extend(found)

        # Extract domains from citations
        for cite in citations:
            url = cite.get("url", "")
            if url:
                domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                if domain_match:
                    domain = domain_match.group(1).lower()
                    # Skip blocked sites
                    if domain not in BLOCKED_DOMAINS and not any(
                        b in domain for b in BLOCKED_DOMAINS
                    ):
                        all_domains.append((domain, 0.5))

    # Dedupe and sort domains
    domain_scores = {}
    for domain, conf in all_domains:
        if domain not in domain_scores or conf > domain_scores[domain]:
            domain_scores[domain] = conf

    # Add current domain if exists
    if current_domain and current_domain not in domain_scores:
        domain_scores[current_domain] = company_data.get("domain", {}).get(
            "confidence", 0.4
        )

    # Sort by confidence
    sorted_domains = sorted(domain_scores.items(), key=lambda x: -x[1])

    research["domain_candidates"] = [
        {"domain": d, "confidence": c} for d, c in sorted_domains[:10]
    ]

    # Crawl top domain candidates (skip blocked domains)
    domains_to_crawl = [
        d
        for d, _ in sorted_domains[: max_crawl * 2]  # Get more candidates to filter
        if d not in BLOCKED_DOMAINS and not any(b in d for b in BLOCKED_DOMAINS)
    ][:max_crawl]

    for domain in domains_to_crawl:
        result = crawl_domain(domain, company_name)
        if result:
            # AI verification for potential matches
            if result.get("is_match") and not result.get("is_parked"):
                ai_check = verify_domain_with_ai(client, model, company_data, result)
                result["ai_verified"] = ai_check.get("verified", False)
                result["ai_confidence"] = ai_check.get("confidence", 0)
                result["ai_reason"] = ai_check.get("reason", "")

                # Only accept if AI confirms it's the right company
                if ai_check.get("verified") and ai_check.get("confidence", 0) >= 0.6:
                    result["status"] = "verified"
                    result["is_match"] = True
                else:
                    # AI says it's NOT the right company
                    result["status"] = "wrong_company"
                    result["is_match"] = False

            research["crawl_results"].append(result)

            # Update best domain - only if AI verified
            if result.get("status") == "verified" and result.get("ai_verified"):
                match_conf = result.get("ai_confidence", 0.5)
                if match_conf > research["best_confidence"]:
                    research["best_domain"] = domain
                    research["best_confidence"] = round(match_conf, 2)

    return research


def find_company_dirs(date_dir: Path) -> List[Path]:
    """Find K-folders."""
    return [
        p
        for p in date_dir.iterdir()
        if p.is_dir() and p.name.startswith("K") and "-" in p.name
    ]


def load_company_data(company_dir: Path) -> Optional[Dict]:
    """Load company_data.json."""
    f = company_dir / "company_data.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_company_data(company_dir: Path, data: Dict):
    """Save company_data.json."""
    f = company_dir / "company_data.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_excel(xlsx_path: Path, updates: Dict[str, Dict]):
    """Update Excel with research results."""
    if not xlsx_path.exists():
        return

    try:
        df = pd.read_excel(xlsx_path, sheet_name="Data", engine="openpyxl").fillna("")

        # Add columns
        for col in ["domain_verified", "domain_status", "research_done"]:
            if col not in df.columns:
                df[col] = ""

        folder_col = None
        for col in ["Mapp", "Kungörelse-id"]:
            if col in df.columns:
                folder_col = col
                break

        if folder_col:
            for idx, row in df.iterrows():
                folder = str(row[folder_col]).replace("/", "-").strip()
                if folder in updates:
                    u = updates[folder]
                    df.at[idx, "domain_verified"] = u.get("domain", "")
                    df.at[idx, "domain_status"] = u.get("status", "")
                    df.at[idx, "domain_confidence"] = f"{u.get('confidence', 0):.2f}"
                    df.at[idx, "research_done"] = "Ja"

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
    print("STEP 2: AI RESEARCH & DOMAIN DISCOVERY")
    print("=" * 60)

    # Check if enabled
    if cfg.get("RESEARCH_ENABLED", "y").lower() not in ("y", "yes", "true", "1"):
        print("Research is disabled in config")
        return 0

    # Check OpenAI
    if not OPENAI_AVAILABLE:
        print("ERROR: openai library not installed")
        return 1

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        return 1

    try:
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"ERROR: Could not init OpenAI: {e}")
        return 1

    model = cfg.get("RESEARCH_MODEL", "gpt-4o")
    print(f"Using model: {model}")

    # Find date folder
    djupanalys = root / "djupanalys"
    if not djupanalys.exists():
        print("ERROR: djupanalys folder not found")
        return 1

    date_dirs = sorted(
        [p for p in djupanalys.iterdir() if p.is_dir() and re.match(r"^\d{8}$", p.name)]
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
            print(
                f"[WARN] TARGET_DATE={target_date} not found, using latest: {latest.name}"
            )
        else:
            print(f"Processing latest: {latest.name}")

    print(f"[INFO] Date folder path: {latest}")

    company_dirs = find_company_dirs(latest)
    print(f"Found {len(company_dirs)} companies")

    # Limit
    max_companies = int(cfg.get("PIPELINE_MAX_COMPANIES", "0"))
    if max_companies > 0:
        company_dirs = company_dirs[:max_companies]
        print(f"  (Limited to {max_companies})")

    # Process
    updates = {}
    researched = 0
    domains_found = 0

    for i, company_dir in enumerate(company_dirs, 1):
        data = load_company_data(company_dir)
        if not data or not data.get("company_name"):
            continue

        company_name = data["company_name"]
        print(
            f"  [{i}/{len(company_dirs)}] {company_name[:40]}...", end=" ", flush=True
        )

        # Run research
        research = research_company(client, model, data, cfg)

        # Update company_data
        data["research"] = research

        # Update domain info if better found
        if research["best_domain"]:
            data["domain"]["guess"] = research["best_domain"]
            data["domain"]["confidence"] = research["best_confidence"]
            data["domain"]["source"] = "ai_verified"
            data["domain"]["status"] = "verified"
            domains_found += 1
            print(f"-> {research['best_domain']} ({research['best_confidence']:.0%})")
        elif research["crawl_results"]:
            # Use best crawl result even if not perfect match
            best_crawl = max(
                research["crawl_results"], key=lambda x: x.get("match_ratio", 0)
            )
            if best_crawl.get("match_ratio", 0) > 0.3 and not best_crawl.get(
                "is_parked"
            ):
                data["domain"]["guess"] = best_crawl["domain"]
                data["domain"]["confidence"] = best_crawl["match_ratio"]
                data["domain"]["source"] = "ai_crawled"
                data["domain"]["status"] = best_crawl["status"]
                print(f"-> {best_crawl['domain']} ({best_crawl['match_ratio']:.0%})")
            else:
                print("no match")
        else:
            print("no domain")

        save_company_data(company_dir, data)
        researched += 1

        # Track for Excel
        updates[company_dir.name] = {
            "domain": data["domain"].get("guess", ""),
            "status": data["domain"].get("status", ""),
            "confidence": data["domain"].get("confidence", 0),
        }

    # Update Excel
    xlsx = next(latest.glob("kungorelser_*.xlsx"), None)
    if xlsx:
        update_excel(xlsx, updates)
        print(f"\nUpdated Excel: {xlsx.name}")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Companies researched: {researched}")
    print(f"Domains found/verified: {domains_found}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
