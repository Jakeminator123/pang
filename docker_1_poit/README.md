# Docker-baserad Bolagsverket Scraper

Containeriserad version av Playwright-scrapern för Bolagsverket kungörelser.

## Förutsättningar

- Docker Desktop installerat
- docker-compose tillgängligt i PATH

## Snabbstart

```bash
# Bygg och kör
cd docker_1_poit
docker-compose up --build

# Med parametrar
TARGET_DATE=20251218 SCRAPE_COUNT=10 docker-compose up --build
```

## Via docker_main.py

```bash
# Från projektets rot
python docker_main.py 10           # Scrapa 10 kungörelser
python docker_main.py 10 --build   # Bygg om imagen först
python docker_main.py 5 -1218      # 5 kungörelser för 18 december
```

## Filstruktur

```
docker_1_poit/
├── Dockerfile.scraper     # Docker-image definition
├── docker-compose.yml     # Container-konfiguration
├── requirements.txt       # Python dependencies
├── config.txt             # Scraper-inställningar
├── scrape.py              # Entry point
├── lib/
│   ├── api.py             # API-anrop till Bolagsverket
│   └── scraper.py         # Playwright scraping-logik
└── docker_v/              # Arkiv (gammal Selenium-kod)
```

## Volymer

- `../1_poit/info_server` → `/app/output` - Där scrapad data sparas
- `./config.txt` → `/app/config.txt` - Konfigurationsfil

## Miljövariabler

| Variabel | Default | Beskrivning |
|----------|---------|-------------|
| `TARGET_DATE` | Dagens datum | Datum att scrapa (YYYYMMDD) |
| `SCRAPE_COUNT` | 10 | Antal kungörelser att scrapa |
| `HEADLESS` | true | Alltid true i Docker |

## Felsökning

### Docker startar inte
- Kontrollera att Docker Desktop körs
- Kör `docker ps` för att verifiera

### Ingen output skapas
- Kontrollera att volymen mountas korrekt
- Kör `docker-compose logs` för att se felmeddelanden

### CAPTCHA-problem
Docker kan inte hantera CAPTCHAs automatiskt. Om scraping misslyckas ofta:
1. Minska `SCRAPE_COUNT`
2. Öka väntetider i `config.txt`
3. Kör manuellt via `headless_main.py --visible` först för att lösa CAPTCHA

