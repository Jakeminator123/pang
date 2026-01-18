# 🎯 PANG Konfigurationshanterare - Användarguide

## Snabbstart

### Windows
Dubbelklicka på: `start_gui.bat`

### macOS
```bash
chmod +x start_gui.command   # Endast första gången
./start_gui.command
```

### Linux / Terminal
```bash
cd gui
python3 config_gui.py
```

---

## Översikt

Konfigurationshanteraren låter dig ändra alla inställningar för PANG-pipelinen 
på ett ställe, istället för att redigera flera olika textfiler.

```
┌─────────────────────────────────────────────────────────────┐
│  🎯 PANG Konfiguration                    [💾 Spara] [▶️ Kör]│
├─────────────────────────────────────────────────────────────┤
│  🚀 Snabbkörning med master-nummer: [____] [Kör]            │
├──────────┬──────────┬──────────┬────────────────────────────┤
│ Skrapning│ AI-Research│  Mail  │  Sajter                    │
├──────────┴──────────┴──────────┴────────────────────────────┤
│                                                             │
│  📝 Inställningar visas här med beskrivningar               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Flikar

### 🔍 Skrapning
Styr hur data hämtas från Bolagsverket.

| Inställning | Beskrivning |
|-------------|-------------|
| **Max kungörelser per dag** | Hur många företag som ska skrapas. Sätt till 0 för obegränsat. |
| **Max företag att bearbeta** | Begränsar antal företag genom AI-pipelinen. |
| **Radera CSV** | Ta bort CSV-filer efter konvertering till Excel. |

### 🤖 AI-Research
Inställningar för AI-driven företagsundersökning.

| Inställning | Beskrivning |
|-------------|-------------|
| **Aktivera AI-research** | Använd OpenAI för att söka info om företag online. |
| **AI-modell** | `gpt-4o` = bäst kvalitet, `gpt-4o-mini` = billigare. |
| **Sökningar per företag** | Antal webbsökningar (3-5 rekommenderas). |
| **Sök efter personer** | Hitta kontaktuppgifter för styrelsemedlemmar. |
| **HTTP-timeout** | Max väntetid vid domänkontroll. |
| **Max domäner att verifiera** | Antal domänkandidater som testas. |

### ✉️ Mail
Inställningar för automatisk e-postgenerering.

| Inställning | Beskrivning |
|-------------|-------------|
| **Aktivera mail-generering** | Skapa personliga säljmail automatiskt. |
| **Min domän-confidence** | Lägsta säkerhet på domänmatchning (%). |
| **Max mail** | Begränsar antal mail per körning. |

#### Ton & Stil (sliders 1-10)

| Slider | 1 = | 10 = | Rekommenderat |
|--------|-----|------|---------------|
| **Formalitet** | "Tjena!" | "Med vänlig hälsning" | 4-5 |
| **Säljighet** | Bara info | Aggressiv sälj | 2-4 |
| **Smicker** | Rakt på sak | "Ni är fantastiska!" | 1-3 |
| **Längd** | ~80 ord | ~200 ord | 4-6 |

### 🌐 Sajter
Demo-hemsidor och webbplats-audits.

| Inställning | Beskrivning |
|-------------|-------------|
| **Aktivera utvärdering** | AI bedömer vilka företag som ska få sajt. |
| **Min confidence för sajt** | Lägsta AI-säkerhet (0.0-1.0). |
| **Max sajter per körning** | Begränsar v0.dev API-anrop. |
| **Aktivera audit** | Analysera företagens befintliga hemsidor. |
| **Lägg till länk i mail** | Infoga preview/audit-URL automatiskt. |

---

## Funktioner

### 💾 Spara alla
Sparar alla inställningar till respektive config-fil:
- `1_poit/config.txt`
- `2_segment_info/config_simple.txt`
- `3_sajt/config_ny.txt`

**Backup skapas automatiskt** i `.cursor/config_backups/`

### ▶️ Kör pipeline
Sparar inställningar och startar `main.py` i ett nytt terminalfönster.

### 🚀 Snabbkörning med master-nummer
Kör pipelinen med ett specifikt antal företag utan att ändra config-filerna permanent.

Exempel: Ange `10` för att testa med bara 10 företag.

---

## Tooltips

Håll muspekaren över **ℹ️**-ikonen bredvid varje inställning för att se tips och rekommendationer.

---

## Filstruktur

```
pang/
├── gui/                          # GUI-mappen
│   ├── config_gui.py             # Huvudprogrammet
│   ├── GUIDE.md                  # Denna fil
│   ├── start_gui.bat             # Windows-startskript
│   └── start_gui.command         # macOS-startskript
│
├── 1_poit/
│   └── config.txt                # ← Sparas hit
├── 2_segment_info/
│   └── config_simple.txt         # ← Sparas hit
├── 3_sajt/
│   └── config_ny.txt             # ← Sparas hit
│
└── .cursor/
    └── config_backups/           # ← Backups sparas hit
```

---

## Felsökning

### GUI startar inte

**Windows:**
```batch
cd gui
python config_gui.py
```
Kolla felmeddelandet.

**macOS/Linux:**
```bash
cd gui
python3 config_gui.py
```

### Saknar customtkinter
GUI:t installerar automatiskt, men du kan göra det manuellt:
```bash
pip install customtkinter
```

### Ändringar sparas inte
- Kontrollera att du har skrivbehörighet till config-filerna
- Kolla `.cursor/config_backups/` för att se om backup skapades

### Pipeline startar inte
- Kontrollera att `main.py` finns i projektroten
- Kolla att Python finns i PATH

---

## Tangentbordsgenvägar

| Genväg | Funktion |
|--------|----------|
| `Ctrl+S` / `Cmd+S` | Spara (planerat) |
| `Tab` | Nästa inställning |
| `Shift+Tab` | Föregående inställning |

---

## Teknisk info

- **Ramverk:** CustomTkinter (modern Tkinter)
- **Python:** 3.10+
- **Plattformar:** Windows, macOS, Linux
- **Beroenden:** customtkinter, darkdetect

---

## Snabbreferens: Rekommenderade värden

### För testning
```
Max kungörelser: 20
Max företag: 20
Max mail: 10
Max sajter: 2
Max audits: 3
```

### För produktion
```
Max kungörelser: 200-500
Max företag: 150
Max mail: 100
Max sajter: 10-20
Max audits: 20
```

---

*Skapad för PANG-projektet. Vid frågor, se `.cursor/project_context.md`*
