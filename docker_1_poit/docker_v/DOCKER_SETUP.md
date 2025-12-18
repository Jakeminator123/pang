# DOCKER SETUP GUIDE
# ==================

## Installation av Docker

### Windows:
1. Ladda ner Docker Desktop från: https://www.docker.com/products/docker-desktop/
2. Installera och starta Docker Desktop
3. Verifiera installation: `docker --version` i PowerShell

### Mac:
1. Ladda ner Docker Desktop från: https://www.docker.com/products/docker-desktop/
2. Installera och starta Docker Desktop
3. Verifiera: `docker --version` i Terminal

### Linux:
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Logga ut och in igen
```

## Lokal testning

### 1. Testa Flask-servern lokalt:
```bash
# Bygg Docker-image
docker build -f Dockerfile.server -t bolag-server .

# Kör containern
docker run -p 5000:5000 \
  -v "%cd%/info_server:/app/info_server" \
  -v "%cd%/log:/app/log" \
  bolag-server
```

### 2. Testa med docker-compose:
```bash
# Starta både server och scraper
docker-compose up

# Eller bara servern
docker-compose up server
```

## Deploy till Render

### Steg 1: Pusha till GitHub/GitLab
```bash
git init
git add .
git commit -m "Initial commit with Docker setup"
git remote add origin <din-repo-url>
git push -u origin main
```

### Steg 2: Skapa nytt Web Service på Render
1. Gå till https://render.com
2. Klicka "New +" → "Web Service"
3. Välj din GitHub-repo
4. Välj:
   - **Name**: bolagsverket-scraper-server
   - **Runtime**: Docker
   - **Dockerfile Path**: Dockerfile.server
   - **Docker Context**: . (root)
   - **Plan**: Free (eller betald för persistent disk)

### Steg 3: Environment Variables
Inga behövs för nu, men du kan lägga till:
- `FLASK_ENV=production`
- `PORT=5000` (sätts automatiskt av Render)

### Steg 4: Deploy
Render kommer automatiskt deploya när du pushar till main branch.

## Viktiga noteringar

⚠️ **Persistent Storage**: Render's free plan har INGEN persistent disk. 
   Data i `info_server/` och `log/` försvinner när containern startar om.
   
💡 **Lösningar**:
   - Använd Render Disk (kostar ~$0.25/GB/månad)
   - Använd extern storage (AWS S3, Google Cloud Storage)
   - Kör scrapern lokalt och skicka data till Render-servern

⚠️ **Scrapern**: Den nuvarande scrapern använder pyautogui som inte fungerar i Docker.
   Den behöver refaktoreras för Selenium + headless Chrome.

## Nästa steg

1. ✅ Installera Docker Desktop
2. ✅ Testa lokalt med `docker-compose up server`
3. ✅ Verifiera att servern svarar på http://localhost:5000/health
4. ✅ Pusha till GitHub
5. ✅ Deploya till Render
6. ⏳ Refaktorera scrapern för headless Chrome (kommer senare)

