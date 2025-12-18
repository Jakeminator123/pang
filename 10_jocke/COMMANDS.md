# Jocke Project - All Commands

## Dashboard (Next.js)

### Installation
```bash
cd dashboard
npm install
# eller
npm ci                    # Clean install (används i CI/CD)
```

### Development
```bash
cd dashboard
npm run dev               # Starta dev-server på http://localhost:3000
```

### Build & Production
```bash
cd dashboard
npm run build             # Bygg för produktion
npm start                 # Starta produktionsserver (efter build)
```

### Linting & Code Quality
```bash
cd dashboard
npm run lint              # Kör ESLint
npm run lint -- --fix    # Fixa automatiska ESLint-problem
```

### Clean Install (om node_modules är korrupt)
```powershell
# Windows PowerShell
cd dashboard
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm install
```

## Python Scripts

### Process Board Data
```bash
cd 10_jocke
python process_board_data.py              # Använder senaste datum-mappen
python process_board_data.py 20251212     # Specifikt datum
```

### Convert to SQLite
```bash
cd 10_jocke
python convert_to_sqlite.py               # Använder senaste datum-mappen
python convert_to_sqlite.py 20251212      # Specifikt datum
```

## Git Commands

### Basic Git
```bash
cd 10_jocke
git status                 # Visa ändringar
git add .                  # Lägg till alla ändringar
git commit -m "Message"    # Commita ändringar
git push                   # Pusha till GitHub
git pull                   # Hämta från GitHub
```

### Setup New Clone
```bash
git clone https://github.com/Jakeminator123/jocke.git
cd jocke/dashboard
npm install
npm run dev
```

## Complete Setup (Fresh Install)

### Windows PowerShell
```powershell
# 1. Klona repo
git clone https://github.com/Jakeminator123/jocke.git
cd jocke

# 2. Installera dashboard dependencies
cd dashboard
npm install

# 3. Starta dev-server
npm run dev

# 4. I annan terminal - Processa data
cd ..
python process_board_data.py 20251212
python convert_to_sqlite.py 20251212
```

## Production Deployment

### Render.com Deployment

#### Automatisk Deployment via GitHub
1. Gå till [Render.com](https://render.com) och logga in
2. Klicka på "New +" → "Web Service"
3. Anslut ditt GitHub-repo: `https://github.com/Jakeminator123/jocke.git`
4. Konfigurera:
   - **Name:** `jocke-dashboard`
   - **Root Directory:** `dashboard`
   - **Environment:** `Node`
   - **Build Command:** `npm ci && npm run build`
   - **Start Command:** `npm start`
   - **Plan:** Free (eller valfri plan)

#### Environment Variables på Render
Lägg till i Render Dashboard → Environment:
```
NODE_ENV=production
JOCKE_API=12345
```

#### Manual Deployment (om render.yaml används)
```bash
# Render.yaml finns i root och dashboard/
# Render kommer automatiskt hitta och använda den
```

### Build för produktion (lokalt)
```bash
cd dashboard
npm run build             # Skapar .next/ mapp
npm start                 # Startar på port 3000
```

### Med PM2 (Process Manager)
```bash
npm install -g pm2
cd dashboard
npm run build
pm2 start npm --name "jocke-dashboard" -- start
pm2 list                  # Visa processer
pm2 logs                  # Visa logs
pm2 stop jocke-dashboard  # Stoppa
```

### Med Docker (om du vill)
```dockerfile
# Skapa Dockerfile i dashboard/
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

```bash
docker build -t jocke-dashboard ./dashboard
docker run -p 3000:3000 jocke-dashboard
```

## Environment Variables

### Dashboard (.env.local)
```bash
cd dashboard
# Skapa .env.local
JOCKE_API=12345
NODE_ENV=production
```

## Troubleshooting

### NPM Install Problem (Windows)
```powershell
# Stäng alla terminaler och VS Code, sedan:
cd dashboard
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm cache clean --force
npm install
```

### Port Already in Use
```powershell
# Windows - Hitta process på port 3000
netstat -ano | findstr :3000
# Döda processen (ersätt PID)
taskkill /PID <PID> /F

# Eller ändra port i package.json:
# "dev": "next dev -p 3001"
```

### SQLite Database Locked
```bash
# Stäng alla processer som använder databasen
# Windows: Stäng VS Code och alla terminals
```

## Quick Reference

| Task | Command |
|------|---------|
| Install dependencies | `cd dashboard && npm install` |
| Start dev server | `cd dashboard && npm run dev` |
| Build production | `cd dashboard && npm run build` |
| Start production | `cd dashboard && npm start` |
| Process Excel data | `python process_board_data.py` |
| Convert to SQLite | `python convert_to_sqlite.py` |
| Git push | `git add . && git commit -m "msg" && git push` |

