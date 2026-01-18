# 🎨 PANG Konfigurationshanterare

Ett modernt, professionellt GUI för att hantera alla PANG-inställningar på ett ställe.

## ✨ Designförbättringar

### Professionellt färgschema
- **Mörka, djupa toner** - Lättare för ögonen vid långvarig användning
- **Harmoniska accentfärger** - Modern blå som primärfärg, grön för success
- **Tydlig text-hierarki** - Ljusare text för viktigt innehåll, dimmer för sekundärt

### Förbättrade komponenter
- **Kort med ikoner** - Varje sektion har en ikon i en färgad bakgrund
- **Polerade inputs** - Rundade hörn, bättre borders, tydlig focus-state
- **Snygga sliders** - Med värde-display i egen ram
- **Professionella knappar** - Rundade hörn, tydliga hover-states
- **Förbättrade tooltips** - Med header och bättre formatering

### Bättre spacing
- **Konsistent spacing-system** - xs, sm, md, lg, xl, xxl
- **Mer luft** - Bättre padding och margins överallt
- **Tydlig hierarki** - Storlekar som visar vad som är viktigt

### Plattformsoberoende
- **Fungerar på Windows, macOS och Linux**
- **Anpassad efter skärmstorlek** - Centrerat och responsivt
- **Native look** - Använder systemets dark mode

## 📁 Filstruktur

```
gui/
├── config_gui.py          # Huvudprogrammet
├── GUIDE.md               # Fullständig användarguide
├── README.md              # Denna fil
├── start_gui.bat          # Windows-startskript
└── start_gui.command      # macOS-startskript
```

## 🚀 Snabbstart

### Windows
Dubbelklicka på `start_gui.bat`

### macOS
```bash
chmod +x start_gui.command
./start_gui.command
```

### Terminal (alla plattformar)
```bash
cd gui
python3 config_gui.py
```

## 🎯 Funktioner

- **💾 Spara alla** - Sparar till alla config-filer + skapar backup
- **▶️ Kör pipeline** - Startar main.py med nuvarande inställningar
- **🚀 Snabbkörning** - Kör med master-nummer utan att ändra config permanent
- **ℹ️ Tooltips** - Hover över info-ikoner för tips
- **📋 Flikar** - Organiserade i logiska grupper

## 🎨 Designprinciper

### Färger
- **Primär:** Blå (#3b82f6) - För huvudåtgärder
- **Success:** Grön (#10b981) - För sparning
- **Warning:** Orange (#f59e0b) - För varningar
- **Error:** Röd (#ef4444) - För fel

### Typografi
- **H1:** 28px bold - Huvudtitel
- **H2:** 20px bold - Sektionstitel
- **Body:** 14px - Brödtext
- **Caption:** 11px - Mindre text

### Spacing
- **xs:** 4px
- **sm:** 8px
- **md:** 12px
- **lg:** 16px
- **xl:** 24px
- **xxl:** 32px

## 🔧 Teknisk info

- **Ramverk:** CustomTkinter 5.2+
- **Python:** 3.10+
- **Plattformar:** Windows 10+, macOS 10.14+, Linux
- **Beroenden:** customtkinter, darkdetect

## 📝 Noteringar

- Alla ändringar sparas till respektive config-fil
- Backups skapas automatiskt i `.cursor/config_backups/`
- GUI:t ändrar inte funktionalitet, bara design
- Fungerar med både Windows och macOS native look
