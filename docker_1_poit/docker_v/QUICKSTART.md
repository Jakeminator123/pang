# QUICK START - Docker & Render Setup
# ===================================

## ✅ Vad jag har skapat:

1. **requirements.txt** - Alla Python-dependencies
2. **requirements-server.txt** - Bara Flask (för servern)
3. **Dockerfile.server** - Docker-image för Flask-servern
4. **Dockerfile.scraper** - Docker-image för scrapern (behöver refaktoreras senare)
5. **docker-compose.yml** - Kör både server och scraper lokalt
6. **render.yaml** - Konfiguration för Render deployment
7. **.dockerignore** - Ignorera onödiga filer i Docker builds
8. **DOCKER_SETUP.md** - Detaljerad guide

## 🚀 Nästa steg:

### 1. Installera Docker Desktop

**Windows:**
- Gå till: https://www.docker.com/products/docker-desktop/
- Ladda ner "Docker Desktop for Windows"
- Installera och starta Docker Desktop
- Vänta tills Docker är startad (ikon i systemfältet)

**Verifiera installation:**
```powershell
docker --version
docker-compose --version
```

### 2. Testa Flask-servern lokalt

```powershell
# Bygg Docker-image
docker build -f Dockerfile.server -t bolag-server .

# Kör containern
docker run -p 5000:5000 `
  -v "${PWD}/info_server:/app/info_server" `
  -v "${PWD}/log:/app/log" `
  bolag-server
```

Öppna webbläsaren: http://localhost:5000/health

Du ska se: `{"ok":true,"service":"collector","time":"..."}`

### 3. Testa med docker-compose (enklare)

```powershell
# Starta servern
docker-compose up server

# I en annan terminal, testa:
curl http://localhost:5000/health
```

### 4. Deploya till Render

**Förberedelser:**
- Skapa konto på https://render.com (gratis)
- Pusha projektet till GitHub/GitLab

**Deploy:**
1. Gå till Render Dashboard
2. Klicka "New +" → "Web Service"
3. Välj din GitHub-repo
4. Välj:
   - **Name**: bolagsverket-scraper-server
   - **Runtime**: Docker
   - **Dockerfile Path**: `Dockerfile.server`
   - **Docker Context**: `.` (root)
   - **Plan**: Free
5. Klicka "Create Web Service"
6. Vänta på deploy (tar ~5 min första gången)

**Din server kommer vara tillgänglig på:**
`https://bolagsverket-scraper-server.onrender.com`

## ⚠️ Viktiga noteringar:

1. **Render Free Plan har INGEN persistent disk**
   - Data i `info_server/` försvinner när containern startar om
   - Lösning: Använd Render Disk ($0.25/GB/månad) eller extern storage

2. **Scrapern fungerar inte ännu i Docker**
   - Den använder `pyautogui` som kräver fysisk skärm
   - Behöver refaktoreras för Selenium + headless Chrome
   - För nu: Kör scrapern lokalt, skicka data till Render-servern

3. **Extensionen behöver uppdateras**
   - Ändra `http://127.0.0.1:5000` till din Render-URL i `background.js`

## 📝 Checklista:

- [ ] Installera Docker Desktop
- [ ] Verifiera: `docker --version` fungerar
- [ ] Testa lokalt: `docker-compose up server`
- [ ] Verifiera: http://localhost:5000/health fungerar
- [ ] Pusha till GitHub
- [ ] Skapa Render-konto
- [ ] Deploya till Render
- [ ] Testa Render-URL: `https://din-app.onrender.com/health`
- [ ] Uppdatera extension med Render-URL

## 🆘 Felsökning:

**Docker startar inte:**
- Kontrollera att Docker Desktop är startad
- Kolla Windows Features: WSL2 måste vara aktiverat

**Port 5000 är upptagen:**
- Ändra port i docker-compose.yml eller använd annan port

**Render deploy misslyckas:**
- Kolla logs i Render Dashboard
- Verifiera att Dockerfile.server finns i root
- Kontrollera att requirements-server.txt finns

## 📚 Ytterligare info:

Se `DOCKER_SETUP.md` för mer detaljerad information.

