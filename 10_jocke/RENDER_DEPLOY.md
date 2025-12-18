# Deploy till Render.com

## Snabbguide

### Steg 1: Förbered Repo
✅ Repot är redan på GitHub: `https://github.com/Jakeminator123/jocke.git`

### Steg 2: Skapa Web Service på Render

1. **Gå till Render Dashboard**
   - Logga in på [render.com](https://render.com)
   - Klicka på "New +" → "Web Service"

2. **Anslut GitHub Repo**
   - Välj "Build and deploy from a Git repository"
   - Anslut till GitHub om inte redan gjort
   - Välj repo: `Jakeminator123/jocke`

3. **Konfigurera Service**
   ```
   Name: jocke-dashboard
   Region: Frankfurt (EU) eller närmaste
   Branch: main
   Root Directory: dashboard
   Runtime: Node
   Build Command: npm ci && npm run build
   Start Command: npm start
   Plan: Free (eller valfri)
   ```

4. **Environment Variables**
   Lägg till:
   ```
   NODE_ENV=production
   JOCKE_API=12345
   ```

5. **Klicka "Create Web Service"**
   - Render börjar bygga automatiskt
   - Vänta på att build ska klara (2-5 minuter)
   - Din site kommer vara live på: `https://jocke-dashboard.onrender.com`

## Viktiga Inställningar

### Health Check
- **Health Check Path:** `/`
- Render kommer automatiskt pinga denna endpoint

### Auto-Deploy
- ✅ **Auto-Deploy:** Aktiverat
- Varje push till `main` branch deployar automatiskt

### Persistent Disk (Rekommenderas!)
För att spara SQLite-databaser och ZIP-filer permanent:

1. **Gå till Render Dashboard → Disks**
2. **Klicka "Add Disk"**
3. **Konfigurera:**
   ```
   Name: jocke-data
   Mount Path: /var/data
   Size: 1 GB (eller större om behövs)
   ```
4. **Klicka "Create Disk"**

Nu kommer alla databaser och ZIP-filer automatiskt kopieras till `/var/data/[datum]/` när `convert_to_sqlite.py` körs.

**Viktigt:** Utan persistent disk försvinner all data när servicen startar om!

## Troubleshooting

### Build Fails
```bash
# Kolla logs i Render Dashboard
# Vanliga problem:
- node_modules saknas → Lägg till i .gitignore (redan gjort)
- Port fel → Next.js använder PORT env var automatiskt
- Memory → Free plan har 512MB RAM limit
```

### Site går ner efter inaktivitet
- Free plan på Render "spinner down" efter 15 min inaktivitet
- Första requesten kan ta 30-60 sekunder att starta
- Lösning: Uppgradera till paid plan eller använd cron job för att pinga

### Database Connection Issues
- SQLite-filer måste vara i persistent disk
- Uppdatera paths i API routes att använda `/var/data`

## Manual Deploy Commands

Om du vill deploya manuellt via Render CLI:
```bash
# Installera Render CLI
npm install -g render-cli

# Login
render login

# Deploy
cd dashboard
render deploy
```

## Monitoring

### Logs
- Gå till Render Dashboard → Logs
- Se real-time logs från din app

### Metrics
- Render visar CPU, Memory, Request metrics
- Gratis på Free plan

## Custom Domain

1. Gå till "Settings" → "Custom Domains"
2. Lägg till din domän
3. Följ DNS-instructions från Render
4. SSL-certifikat genereras automatiskt

