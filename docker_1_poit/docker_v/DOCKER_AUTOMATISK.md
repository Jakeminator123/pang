# DOCKER AUTOMATISK SCRAPING - Komplett Guide
# ============================================

## ÖVERSIKT
När du kör `docker-compose up scraper` så händer detta AUTOMATISKT:
1. ✅ Flask-servern startar (om den inte redan körs)
2. ✅ Chrome installeras i scraper-containern
3. ✅ Extensionen laddas automatiskt i Chrome
4. ✅ Extensionen konfigureras med rätt server URL (http://server:5000)
5. ✅ Scrapern navigerar till Bolagsverket
6. ✅ Extensionen fångar API-anrop automatiskt
7. ✅ Data skickas till Flask-servern
8. ✅ Data sparas i info_server/YYYYMMDD/

## KÖR ALLT AUTOMATISKT

### Steg 1: Starta både server och scraper
```powershell
docker-compose up scraper
```

Detta kommer:
- Starta Flask-servern (om den inte redan körs)
- Bygga scraper-containern (första gången tar det tid)
- Köra scrapern automatiskt med Chrome + extension

### Steg 2: Följ loggarna
I samma terminal ser du:
- Flask-server loggar
- Scraper loggar
- Chrome startar
- Extension laddas
- Navigation och scraping

### Steg 3: Kolla resultat
```powershell
# I en annan terminal:
curl http://localhost:5000/list

# Eller kolla mappen:
dir info_server\20251111
```

## ENDAST SERVER (utan scraping)
```powershell
docker-compose up server
```

## ENDAST SCRAPER (server måste köra)
```powershell
docker-compose up scraper
```

## STOPPA ALLT
```powershell
docker-compose down
```

## VAD SOM ÄR FÖRINSTÄLLT

### I Dockerfile.scraper:
- ✅ Chrome installeras automatiskt
- ✅ ChromeDriver installeras automatiskt
- ✅ Python dependencies installeras
- ✅ Extensionen kopieras in
- ✅ Chrome profile sparas persistent (chrome_profile/)

### I docker-compose.yml:
- ✅ SERVER_URL sätts till http://server:5000 (Docker service name)
- ✅ HEADLESS=true (headless Chrome)
- ✅ Volumes för persistent data
- ✅ Scrapern väntar på att servern startar (depends_on)

### I scrape_kungorelser_selenium.py:
- ✅ Läser HEADLESS från environment
- ✅ Läser SERVER_URL från environment
- ✅ Laddar extension automatiskt
- ✅ Konfigurerar extension med rätt server URL
- ✅ Använder persistent Chrome profile

### I background.js (extension):
- ✅ Kan konfigureras via chrome.storage
- ✅ Fallback till default URL om inte satt
- ✅ Loggar vilken URL som används

## TROUBLESHOOTING

### Scrapern startar inte:
```powershell
# Kolla loggar
docker-compose logs scraper

# Bygg om
docker-compose build scraper
```

### Extensionen laddas inte:
- Kolla att ext_bolag/ finns i projektet
- Kolla scraper-loggar för fel

### Ingen data kommer:
- Kolla att servern körs: `docker ps`
- Kolla serverns loggar: `docker logs bolag-server-test`
- Kolla scraper-loggar: `docker-compose logs scraper`

### ChromeDriver-fel:
- Dockerfile.scraper installerar ChromeDriver automatiskt
- Om det misslyckas, kolla Chrome-versionen i loggarna

