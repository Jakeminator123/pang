# KOMPLETT SYSTEM-GUIDE
# =====================
# Alla dessa delar MÅSTE fungera tillsammans för att scraping ska fungera:

## 1. FLASK-SERVER (MÅSTE köras)
- Körs nu i Docker: `bolag-server-test` på port 5000
- Tar emot data från extensionen via POST /save och POST /save_kungorelse
- Sparar data i info_server/YYYYMMDD/

**Status:** ✅ KÖRS (docker ps visar containern)

## 2. CHROME EXTENSION (MÅSTE vara laddad)
- Måste vara installerad i Chrome
- Fångar API-anrop från poit.bolagsverket.se
- Skickar data till http://127.0.0.1:5000/save
- Fångar även kungörelse-sidor och skickar till /save_kungorelse

**Status:** ⚠️ BEHÖVER VERIFIERAS (måste laddas manuellt i Chrome)

## 3. AUTOMATION-SCRIPT (valfritt men rekommenderat)
- scrape_kungorelser.py (gamla, kräver GUI)
- scrape_kungorelser_selenium.py (nya, fungerar headless)
- Öppnar sidor på Bolagsverket så extensionen kan fånga data

**Status:** ⚠️ INTE KÖRD ÄNNU

## DATAFLÖDE:
```
1. Automation/Manuell → Öppnar Bolagsverket i Chrome
2. Extension (injected.js) → Fångar API-anrop från sidan
3. Extension (content.js) → Skickar till background.js
4. Extension (background.js) → POST till http://127.0.0.1:5000/save
5. Flask Server → Sparar i info_server/YYYYMMDD/kungorelser_YYYYMMDD.json
6. Extension → Fångar kungörelse-sidor → POST till /save_kungorelse
7. Flask Server → Sparar i info_server/YYYYMMDD/Kxxxxxx-25/
```

## FÖR ATT FÅ DAGENS DATA (2025-11-11):

1. ✅ Servern körs redan
2. ⚠️ Ladda extensionen i Chrome:
   - Öppna chrome://extensions/
   - Aktivera "Developer mode"
   - Klicka "Load unpacked"
   - Välj mappen: C:\Users\Propietario\Desktop\pang\1_poit\ext_bolag
   
3. ⚠️ Testa extensionen:
   - Öppna https://poit.bolagsverket.se/poit-app/
   - Gör en sökning
   - Kolla serverns loggar: docker logs bolag-server-test
   - Kolla http://localhost:5000/list

4. ⚠️ Kör automation (valfritt):
   - python automation/scrape_kungorelser_selenium.py
   - ELLER använd gamla: python automation/scrape_kungorelser.py

## VIKTIGT:
- Extensionen pekar på http://127.0.0.1:5000 (localhost)
- Servern körs i Docker men exponeras på localhost:5000 ✅
- Extensionen måste ha permission för poit.bolagsverket.se ✅ (finns i manifest.json)
- Servern måste vara tillgänglig när extensionen försöker skicka data ✅

