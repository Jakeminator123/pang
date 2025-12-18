"""API calls to Bolagsverket PoIT service."""

import requests

BASE_URL = "https://poit.bolagsverket.se"
API_BASE = f"{BASE_URL}/poit/rest"


def create_session(cookies: dict) -> requests.Session:
    """
    Create a requests session with cookies and proper headers.
    
    Args:
        cookies: Dictionary of cookies from Chrome session.
    
    Returns:
        Configured requests.Session object.
    """
    session = requests.Session()
    
    # Headers from network traffic analysis
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{BASE_URL}/poit-app/",
        "Origin": BASE_URL,
        "x-security-request": "required",  # Important for API access
    })
    
    # Add cookies to session
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".bolagsverket.se")
    
    return session


def fetch_kungorelser_list(session: requests.Session, api_date: str) -> list:
    """
    Fetch list of kungörelser via the SokKungorelse API.
    
    Args:
        session: Configured requests session with cookies.
        api_date: Date in YYYY-MM-DD format.
    
    Returns:
        List of kungörelse dictionaries, or empty list on failure.
    """
    params = {
        "sokord": "",
        "kungorelseid": "",
        "kungorelseObjektPersonOrgnummer": "",
        "kungorelseObjektNamn": "",
        "tidsperiod": "ANNAN_PERIOD",
        "tidsperiodFrom": api_date,
        "tidsperiodTom": api_date,
        "amnesomradeId": "2",
        "kungorelsetypId": "4",
        "underRubrikId": "6",
    }
    
    url = f"{API_BASE}/SokKungorelse"
    
    try:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"    [API ERROR] {e}")
    
    return []

