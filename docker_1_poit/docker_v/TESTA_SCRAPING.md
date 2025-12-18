# TESTA SCRAPING - Steg för steg
# ================================

## 1. VERIFIERA ATT SERVERN KÖRS
```powershell
docker ps --filter name=bolag-server-test
```
Bör visa: STATUS "Up X minutes"

## 2. FÖLJ SERVERNS LOGGAR (i en separat terminal)
```powershell
docker logs -f bolag-server-test
```
Detta visar ALLA requests i realtid. Lämna detta igång!

## 3. LADDA EXTENSIONEN I CHROME
1. Öppna Chrome
2. Gå till: chrome://extensions/
3. Aktivera "Developer mode" (höger upp)
4. Klicka "Load unpacked"
5. Välj: C:\Users\Propietario\Desktop\pang\1_poit\ext_bolag
6. Kontrollera att extensionen är AKTIVERAD (slidern är blå)

## 4. TESTA EXTENSIONEN
1. Öppna ny flik i Chrome
2. Gå till: https://poit.bolagsverket.se/poit-app/
3. Öppna Developer Tools (F12) → Console
4. Du bör se: `[PoIT Listener] Extension loaded`
5. Gör en sökning efter kungörelser
6. Kolla serverns loggar - du bör se:
   ```
   [REQUEST] POST /save från 172.17.0.1
     → JSON mottagen, typ: dict
   [SAVE] created | URL: https://poit.bolagsverket.se/...
     → 356 items
   ```

## 5. KONTROLLERA ATT DATA SPARATS
```powershell
# Kolla vilka filer som finns
curl http://localhost:5000/list

# Kolla dagens mapp
dir info_server\20251111
```

## 6. OM INGET HÄNDER
- Kontrollera att extensionen är aktiverad
- Kolla Chrome Console för fel
- Kolla serverns loggar för fel
- Testa att skicka manuellt:
  ```powershell
  curl -X POST http://localhost:5000/save -H "Content-Type: application/json" -d '{\"url\":\"test\",\"data\":{\"test\":123}}'
  ```

## LOGG-FORMAT
Nuvarande logging visar:
- `[REQUEST] POST /save` - När request kommer in
- `→ JSON mottagen` - Vad som mottogs
- `[SAVE] created/updated/duplicate` - Status
- `→ X items` - Antal items om det är en lista
- `[KUNGORELSE] ✓ Saved Kxxxxx-25` - När kungörelse sparas

